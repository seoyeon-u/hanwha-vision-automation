"""Run with `python -m streamlit run streamlit_app/app.py` from the repository root."""
from __future__ import annotations

import logging
from collections import Counter
from pathlib import PurePosixPath

import pandas as pd
import streamlit as st
from PIL import Image

from streamlit_app.analysis import ANALYSIS_OPTIONS, REVIEW_TYPES, Result, ReviewRow, excel_text, filter_reviews, run_analysis
from streamlit_app.annotation_viewer import draw_annotation
from streamlit_app.charts import folder_figure, object_figures
from streamlit_app.file_handler import MAX_UPLOAD_MIB, Dataset, Issue, labelme, prepare_uploads

TITLE = "Hanwha Vision Data Analysis"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ANOMALY_LABELS = {
    "객체가 없는 이미지": "empty",
    "JSON 누락": "missing",
    "JSON 파싱·형식 오류": "invalid",
    "이미지와 JSON 파일명 불일치": "mismatch",
}
LOGGER = logging.getLogger(__name__)


def reset_upload() -> None:
    for key in ("dataset", "result", "run_error", "folder_filter", "review_kind", "review_folder",
                "review_class", "review_item", "anomaly_type"):
        st.session_state.pop(key, None)


def folder_label(folder: str) -> str:
    return "최상위 폴더" if folder == "." else folder


def show_issues(issues: list[Issue]) -> None:
    st.dataframe(pd.DataFrame(
        [{"파일": excel_text(issue.file), "상세 원인": excel_text(issue.reason)} for issue in issues],
        columns=["파일", "상세 원인"],
    ), hide_index=True, width="stretch")


def show_upload(dataset: Dataset) -> None:
    with st.container(border=True):
        st.subheader("업로드 현황")
        json_count, image_count, time = st.columns(3)
        json_count.metric("JSON 파일", f"{dataset.json_count:,}개")
        image_count.metric("이미지 파일", f"{len(dataset.images):,}개")
        time.metric("업로드 검증 시간", f"{dataset.seconds:.2f}초")
        issues = dataset.upload_issues + dataset.json_issues
        if issues:
            st.warning(f"파일 또는 형식 확인 사항 {len(issues):,}건")
        else:
            st.success("지원 파일의 형식 검증이 완료되었습니다.")
        with st.expander(f"업로드한 파일 {len(dataset.uploads):,}개"):
            st.dataframe(pd.DataFrame({"파일명": [excel_text(name) for name in dataset.uploads]}),
                         hide_index=True, width="stretch")
            if issues:
                show_issues(issues)


def show_summary(result: Result) -> None:
    st.subheader("분석 결과 요약")
    images, objects, reviews, elapsed = st.columns(4)
    images.metric("전체 이미지 수", f"{result.total_images:,}개", border=True,
                  help="이미지 파일이 없으면 shapes 배열이 확인된 JSON의 수를 표시합니다.")
    objects.metric("전체 객체 수", "미실행" if result.total_objects is None else f"{result.total_objects:,}개", border=True)
    reviews.metric("전체 검수 후보 수", "미실행" if result.mode == "distribution" else f"{len(result.reviews):,}건",
                   border=True)
    elapsed.metric("전체 분석 시간", f"{result.seconds:.2f}초", border=True)
    if result.image_count_inferred:
        st.caption("이미지가 포함되지 않아 유효한 어노테이션 수를 이미지 수로 표시합니다.")


def show_distribution(result: Result) -> None:
    st.header("객체 클래스별 분포")
    bar, pie = object_figures(result.classes)
    left, right = st.columns([3, 2])
    with left:
        st.subheader("클래스별 객체 수")
        st.plotly_chart(bar, width="stretch", key="object_bar")
    with right:
        st.subheader("클래스별 객체 비율")
        if result.total_objects:
            st.plotly_chart(pie, width="stretch", key="object_pie")
        else:
            st.info("비율을 계산할 집계 대상 객체가 없습니다.")

    st.header("폴더별 데이터 분석")
    picker, sorter = st.columns(2)
    folder = picker.selectbox("폴더 선택", [None, *(item.name for item in result.folders)],
                              format_func=lambda name: "전체 폴더" if name is None else folder_label(name),
                              key="folder_filter")
    sort_by = sorter.selectbox("정렬 기준", ["객체 수", "이미지 수"], key="folder_sort")
    rows = [{"폴더": folder_label(item.name), "이미지 수": item.images, "객체 수": item.objects,
             "이미지당 평균 객체 수": item.average}
            for item in result.folders if folder is None or item.name == folder]
    if not rows:
        st.info("표시할 폴더가 없습니다.")
        return
    frame = pd.DataFrame(rows).sort_values(sort_by, ascending=False, kind="stable")
    st.dataframe(frame, hide_index=True, width="stretch", column_config={
        "이미지당 평균 객체 수": st.column_config.NumberColumn(format="%.2f"),
    })
    if result.image_count_inferred:
        st.caption("폴더별 이미지 수와 평균은 업로드된 실제 이미지 수를 기준으로 표시합니다.")
    if len(rows) > 20:
        st.caption("비교 차트는 각 항목의 상위 20개 폴더를 표시합니다.")
    image_chart, object_chart = st.columns(2)
    with image_chart:
        st.subheader("폴더별 이미지 수")
        st.plotly_chart(folder_figure(frame, "이미지 수"), width="stretch", key="folder_images")
    with object_chart:
        st.subheader("폴더별 객체 수")
        st.plotly_chart(folder_figure(frame, "객체 수"), width="stretch", key="folder_objects")


def show_anomalies(result: Result) -> None:
    st.header("데이터 이상 현황")
    for column, (label, key) in zip(st.columns(4), ANOMALY_LABELS.items()):
        issues = result.anomalies[key]
        column.metric(label, "확인 불가" if issues is None else f"{len(issues):,}건", border=True)
    selected = st.selectbox("상세 오류 유형", list(ANOMALY_LABELS), key="anomaly_type")
    issues = result.anomalies[ANOMALY_LABELS[selected]]
    if issues is None:
        st.info("이 항목을 확인하려면 이미지가 포함된 ZIP을 업로드해 주세요.")
    elif issues:
        show_issues(issues)
    else:
        st.caption("이 유형에서 발견된 항목이 없습니다.")


def show_review_detail(dataset: Dataset, result: Result, selected: ReviewRow) -> None:
    annotation = labelme(dataset.annotations[selected.path])
    st.subheader("선택한 검수 항목")
    st.text(f"{selected.path} · 객체 {selected.object_number}번")
    st.text(selected.kind)
    rows = [{"객체 번호": index, "객체 클래스": excel_text(str(shape.get("label", ""))),
             "무기타입": excel_text(str(shape.get("무기타입", "") or "")),
             "도형": excel_text(str(shape.get("shape_type") or "polygon"))}
            for index, shape in enumerate(annotation["shapes"], 1) if isinstance(shape, dict)]
    file = result.matches.get(selected.path)
    if file:
        try:
            image, skipped = draw_annotation(dataset.images[file], annotation, selected.object_number)
            st.image(image, caption=f"{PurePosixPath(file).name} · 주황색은 선택한 검수 객체", width="stretch")
            if skipped:
                st.warning("지원하지 않는 도형 또는 좌표 오류가 있는 객체 번호 " + ", ".join(map(str, skipped)))
        except (OSError, TypeError, ValueError, Image.DecompressionBombError):
            st.warning("이미지 미리보기를 표시할 수 없습니다. 아래에서 JSON 객체 정보를 확인할 수 있습니다.")
    else:
        st.info("짝을 이룬 이미지가 없어 JSON 객체 정보를 표시합니다.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def show_reviews(dataset: Dataset, result: Result) -> None:
    st.header("복수 무기타입 검수")
    counts = Counter(row.kind for row in result.reviews)
    distinct, mixed, total = st.columns(3)
    distinct.metric(REVIEW_TYPES[0], f"{counts[REVIEW_TYPES[0]]:,}건", border=True)
    mixed.metric(REVIEW_TYPES[1], f"{counts[REVIEW_TYPES[1]]:,}건", border=True)
    total.metric("전체 검수 후보", f"{len(result.reviews):,}건", border=True)
    if counts[REVIEW_TYPES[2]]:
        st.caption(f"{REVIEW_TYPES[2]} {counts[REVIEW_TYPES[2]]:,}건")
    if not result.reviews:
        st.info("검수 후보가 없습니다.")
        return
    kind_col, folder_col, class_col = st.columns(3)
    kinds = sorted(counts)
    folders = sorted({row.folder for row in result.reviews})
    classes = sorted({row.object_class for row in result.reviews})
    kind = kind_col.selectbox("검수 유형", [None, *kinds], format_func=lambda value: value or "전체 유형",
                              key="review_kind")
    folder = folder_col.selectbox("검수 폴더", [None, *folders], key="review_folder",
                                  format_func=lambda value: "전체 폴더" if value is None else folder_label(value))
    object_class = class_col.selectbox("객체 클래스", [None, *classes], key="review_class",
                                       format_func=lambda value: "전체 클래스" if value is None else value or "이름 없음")
    rows = filter_reviews(result.reviews, kind, folder, object_class)
    st.caption(f"조건에 맞는 검수 후보 {len(rows):,}건")
    if not rows:
        st.info("선택 조건에 맞는 검수 후보가 없습니다.")
        return
    st.dataframe(pd.DataFrame([
        {"파일명": row.filename, "폴더": folder_label(row.folder), "객체 클래스": row.object_class,
         "무기타입": row.weapon_type, "검수 유형": row.kind, "객체 번호": row.object_number,
         "파일 내 객체 수": row.object_count} for row in rows
    ]), hide_index=True, width="stretch")
    selection = st.selectbox("상세 보기 파일", rows, index=None, key="review_item",
                             format_func=lambda row: f"{row.path} · 객체 {row.object_number}번")
    if selection:
        show_review_detail(dataset, result, selection)


def main() -> None:
    st.set_page_config(page_title=TITLE, layout="wide", initial_sidebar_state="expanded")
    st.html("""<style>
        .st-key-run_analysis button:not(:disabled) { background-color: #2459C4; border-color: #2459C4; color: white; }
        .st-key-run_analysis button:hover:not(:disabled) { background-color: #1A469F; border-color: #1A469F; }
    </style>""")
    st.title(TITLE)
    st.caption("Labelme Dataset Preprocessing Dashboard")
    with st.sidebar:
        st.header("데이터셋 업로드")
        uploads = st.file_uploader("Labelme JSON 또는 ZIP", type=["json", "zip"], accept_multiple_files=True,
                                   key="upload_files", on_change=reset_upload, max_upload_size=MAX_UPLOAD_MIB)
        st.caption("여러 JSON을 선택하거나 이미지와 JSON을 함께 ZIP으로 올릴 수 있습니다.")
        mode_name = st.radio("분석 옵션", tuple(ANALYSIS_OPTIONS), key="analysis_option")
        dataset = st.session_state.get("dataset")
        if dataset is None and uploads:
            with st.spinner("업로드 파일을 검증하고 있습니다."):
                dataset = prepare_uploads(uploads)
                st.session_state["dataset"] = dataset
        execute = st.button("데이터 분석 실행", type="primary", width="stretch", key="run_analysis",
                            disabled=not dataset or not (dataset.annotations or dataset.images))

    if not dataset:
        st.info("사이드바에서 파일을 선택한 뒤 데이터 분석을 실행해 주세요.")
        return
    show_upload(dataset)
    if execute:
        with st.spinner("Labelme 데이터를 분석하고 있습니다."):
            try:
                st.session_state["result"] = run_analysis(dataset, ANALYSIS_OPTIONS[mode_name])
                st.session_state.pop("run_error", None)
            except Exception as exc:
                LOGGER.error("Dataset analysis failed (%s)", type(exc).__name__)
                st.session_state["run_error"] = "분석 중 오류가 발생했습니다. 파일 형식과 경로 길이를 확인해 주세요."
    if error := st.session_state.get("run_error"):
        st.error(error)
    result = st.session_state.get("result")
    if not result:
        if not (dataset.annotations or dataset.images):
            st.info("분석에 사용할 수 있는 Labelme JSON 또는 이미지가 없습니다.")
        return
    completed_mode = next(name for name, mode in ANALYSIS_OPTIONS.items() if mode == result.mode)
    st.caption(f"최근 실행 옵션 · {completed_mode}")
    show_summary(result)
    if result.total_objects is not None:
        show_distribution(result)
    show_anomalies(result)
    if result.mode != "distribution":
        show_reviews(dataset, result)
    st.header("Excel 다운로드")
    for filename, contents in result.workbooks.items():
        st.download_button(filename, contents, file_name=filename, mime=XLSX_MIME,
                           key=f"download_{filename}", on_click="ignore")


if __name__ == "__main__":
    main()
