"""Extract JSON annotations that contain multiple weapon-type entries."""

from __future__ import annotations

import codecs
import json
import os
import re
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


OUTPUT_FILENAME = "복수 무기타입 검수 목록.xlsx"
WORKSHEET_NAME = "복수 무기타입 검수 목록"
ERRORS_WORKSHEET_NAME = "처리 오류 로그"
HEADERS = [
    "폴더 경로",
    "JSON 파일명",
    "JSON 전체 경로",
    "이미지 파일명",
    "객체 번호",
    "객체 클래스",
    "무기타입 원본값",
    "무기타입 개수",
    "무기방향 원본값",
    "중복 여부",
    "검수 상태",
    "검수자 메모",
]
ERROR_HEADERS = ["폴더 경로", "JSON 파일명", "객체 번호", "오류 내용"]
WEAPON_SEPARATOR_RE = re.compile(r"[,;|，；]")
WEAPON_NUMBER_SUFFIX_RE = re.compile(r"_\d+$")
EMPTY_WEAPON_VALUES = {"", "none", "없음"}
PROGRESS_FILE_INTERVAL = 250
PROGRESS_TIME_INTERVAL = 1.0
MAX_PENDING_FILES_PER_WORKER = 2
DEFAULT_WORKERS = 4
MAX_WORKERS = 8


@dataclass
class ReviewItem:
    folder_path: str
    json_filename: str
    json_path: Path
    image_filename: str
    object_number: int
    object_class: str
    weapon_value: str
    weapon_count: int
    weapon_direction: str
    duplicate_status: str


@dataclass
class FileResult:
    path: Path
    review_items: list[ReviewItem] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ReviewResult:
    items: list[ReviewItem]
    errors: list[dict[str, str]]
    total_json_files: int
    readable_json_files: int
    timings: dict[str, float] = field(default_factory=dict)


def _raw_value(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _extract_weapon_entries(value: object) -> tuple[list[str], list[str]]:
    entries: list[str] = []
    notices: list[str] = []

    def add(item: object) -> None:
        if item is None:
            return
        if isinstance(item, str):
            entries.extend(
                part.strip()
                for part in WEAPON_SEPARATOR_RE.split(item)
                if part.strip().casefold() not in EMPTY_WEAPON_VALUES
            )
            return
        if isinstance(item, list):
            for nested in item:
                add(nested)
            return
        notices.append(f"무기타입 항목이 문자열/배열이 아닌 값입니다: {item!r}")

    add(value)
    return entries, notices


def _duplicate_status(entries: list[str]) -> str:
    weapon_kinds = [
        WEAPON_NUMBER_SUFFIX_RE.sub("", entry).strip().casefold()
        for entry in entries
    ]
    distinct_kinds = set(weapon_kinds)
    has_repeat = len(distinct_kinds) < len(weapon_kinds)
    has_multiple_kinds = len(distinct_kinds) > 1
    if has_repeat and has_multiple_kinds:
        return "중복 및 복수 무기타입"
    if has_repeat:
        return "동일 무기타입 중복 의심"
    return "서로 다른 복수 무기타입"


def _image_filename(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("\\", "/").rsplit("/", maxsplit=1)[-1]


def _record_error(
    errors: list[dict[str, str]],
    folder_path: str,
    json_filename: str,
    object_number: str,
    message: str,
) -> None:
    errors.append(
        {
            "폴더 경로": folder_path,
            "JSON 파일명": json_filename,
            "객체 번호": object_number,
            "오류 내용": message,
        }
    )


def _process_json_file(json_path: Path) -> FileResult:
    result = FileResult(path=json_path)
    try:
        with json_path.open("rb") as json_file:
            raw_json = json_file.read()
        if raw_json.startswith(codecs.BOM_UTF8):
            raw_json = raw_json[len(codecs.BOM_UTF8) :]
        data = json.loads(raw_json)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _record_error(result.errors, str(json_path.parent), json_path.name, "", f"JSON을 읽을 수 없습니다: {exc}")
        return result

    if not isinstance(data, dict):
        _record_error(result.errors, str(json_path.parent), json_path.name, "", "JSON 최상위 값이 객체(dict)가 아닙니다.")
        return result
    shapes = data.get("shapes")
    if not isinstance(shapes, list):
        _record_error(result.errors, str(json_path.parent), json_path.name, "", "shapes 필드가 없거나 배열 형식이 아닙니다.")
        return result

    image_filename = _image_filename(data.get("imagePath"))
    for index, shape in enumerate(shapes, start=1):
        if not isinstance(shape, dict):
            _record_error(result.errors, str(json_path.parent), json_path.name, str(index), "shape 항목이 객체(dict)가 아닙니다.")
            continue
        if "무기타입" not in shape:
            continue

        entries, notices = _extract_weapon_entries(shape["무기타입"])
        for notice in notices:
            _record_error(result.errors, str(json_path.parent), json_path.name, str(index), notice)
        if len(entries) < 2:
            continue

        object_class = shape.get("label")
        weapon_direction = shape.get("무기방향")
        result.review_items.append(
            ReviewItem(
                folder_path=str(json_path.parent),
                json_filename=json_path.name,
                json_path=json_path,
                image_filename=image_filename,
                object_number=index,
                object_class=object_class if isinstance(object_class, str) else _raw_value(object_class),
                weapon_value=_raw_value(shape["무기타입"]),
                weapon_count=len(entries),
                weapon_direction=_raw_value(weapon_direction),
                duplicate_status=_duplicate_status(entries),
            )
        )
    return result


def _normalized_path_key(path: Path) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _resolve_inputs(
    input_paths: Iterable[str | Path],
    errors: list[dict[str, str]],
) -> tuple[list[Path], list[Path]]:
    folder_roots: dict[str, Path] = {}
    direct_files: dict[str, Path] = {}
    for raw_path in input_paths:
        raw_text = str(raw_path).strip().strip('"').strip("'")
        try:
            path = Path(raw_text).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            _record_error(errors, raw_text, "", "", f"입력 경로에 접근할 수 없습니다: {exc}")
            continue
        if path.is_file():
            if path.suffix.casefold() != ".json":
                _record_error(errors, str(path.parent), path.name, "", "JSON 파일이 아닙니다.")
                continue
            direct_files.setdefault(_normalized_path_key(path), path)
        elif path.is_dir():
            folder_roots.setdefault(_normalized_path_key(path), path)
        else:
            _record_error(errors, str(path), "", "", "JSON 파일 또는 폴더 경로가 아닙니다.")

    sorted_roots = sorted(
        folder_roots.values(),
        key=lambda item: (len(item.parts), str(item).casefold()),
    )
    non_overlapping_roots: list[Path] = []
    for root in sorted_roots:
        if not any(root == parent or parent in root.parents for parent in non_overlapping_roots):
            non_overlapping_roots.append(root)

    direct_only_files = [
        path
        for path in direct_files.values()
        if not any(path == root or root in path.parents for root in non_overlapping_roots)
    ]
    return non_overlapping_roots, direct_only_files


def _walk_json_files(
    roots: list[Path],
    direct_files: list[Path],
    errors: list[dict[str, str]],
) -> Iterator[Path]:
    seen: set[str] = set()
    for path in direct_files:
        key = _normalized_path_key(path)
        if key not in seen:
            seen.add(key)
            yield path
    for root in roots:
        pending_directories = [root]
        while pending_directories:
            current = pending_directories.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                pending_directories.append(Path(entry.path))
                            elif entry.is_file() and entry.name.casefold().endswith(".json"):
                                path = Path(entry.path)
                                key = _normalized_path_key(path)
                                if key not in seen:
                                    seen.add(key)
                                    yield path
                        except OSError as exc:
                            _record_error(errors, current.as_posix(), entry.name, "", f"항목을 읽을 수 없습니다: {exc}")
            except OSError as exc:
                _record_error(errors, str(current), "", "", f"폴더를 탐색할 수 없습니다: {exc}")


def review_paths(
    input_paths: Iterable[str | Path],
    progress_callback: Callable[[int], None] | None = None,
    max_workers: int = DEFAULT_WORKERS,
) -> ReviewResult:
    """Find shapes with two or more non-empty weapon-type entries."""
    discovery_started = time.perf_counter()
    errors: list[dict[str, str]] = []
    roots, direct_files = _resolve_inputs(input_paths, errors)
    file_iterator = _walk_json_files(roots, direct_files, errors)

    worker_count = max(1, min(int(max_workers), MAX_WORKERS))
    max_pending = worker_count * MAX_PENDING_FILES_PER_WORKER
    pending: set[Future[FileResult]] = set()
    items: list[ReviewItem] = []
    processed_count = 0
    readable_count = 0
    completed_since_report = 0
    last_progress_time = time.perf_counter()
    started = time.perf_counter()
    exhausted = False
    discovery_seconds = time.perf_counter() - discovery_started

    def submit_until_full(executor: ThreadPoolExecutor) -> None:
        nonlocal exhausted, discovery_seconds
        while not exhausted and len(pending) < max_pending:
            scan_started = time.perf_counter()
            try:
                path = next(file_iterator)
            except StopIteration:
                exhausted = True
                discovery_seconds += time.perf_counter() - scan_started
                break
            discovery_seconds += time.perf_counter() - scan_started
            pending.add(executor.submit(_process_json_file, path))

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        submit_until_full(executor)
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                file_result = future.result()
                processed_count += 1
                readable_count += not any(
                    error["오류 내용"].startswith("JSON을 읽을 수 없습니다")
                    for error in file_result.errors
                )
                items.extend(file_result.review_items)
                errors.extend(file_result.errors)
                completed_since_report += 1
            pending.difference_update(completed)
            now = time.perf_counter()
            if progress_callback is not None and (
                completed_since_report >= PROGRESS_FILE_INTERVAL
                or now - last_progress_time >= PROGRESS_TIME_INTERVAL
            ):
                progress_callback(processed_count)
                completed_since_report = 0
                last_progress_time = now
            submit_until_full(executor)

    if progress_callback is not None and processed_count and completed_since_report:
        progress_callback(processed_count)
    items.sort(key=lambda item: (item.folder_path.casefold(), item.json_filename.casefold(), item.object_number))
    errors.sort(
        key=lambda item: (
            item["폴더 경로"].casefold(),
            item["JSON 파일명"].casefold(),
            int(item["객체 번호"]) if item["객체 번호"].isdigit() else 0,
            item["오류 내용"],
        )
    )
    processing_seconds = time.perf_counter() - started
    return ReviewResult(
        items=items,
        errors=errors,
        total_json_files=processed_count,
        readable_json_files=readable_count,
        timings={
            "discovery_seconds": discovery_seconds,
            "processing_seconds": processing_seconds,
        },
    )


def write_workbook(result: ReviewResult, output_path: str | Path) -> Path:
    output = Path(output_path)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = WORKSHEET_NAME
    sheet.append(HEADERS)

    for item in result.items:
        sheet.append(
            [
                item.folder_path,
                item.json_filename,
                str(item.json_path),
                item.image_filename,
                item.object_number,
                item.object_class,
                item.weapon_value,
                item.weapon_count,
                item.weapon_direction,
                item.duplicate_status,
                "미검수",
                "",
            ]
        )
        link_cell = sheet.cell(row=sheet.max_row, column=3)
        link_cell.hyperlink = item.json_path.resolve().as_uri()
        link_cell.style = "Hyperlink"

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(bold=True, color="FFFFFF")
    thin_side = Side(style="thin", color="B7C9D6")
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    for row in sheet.iter_rows():
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(vertical="center", wrap_text=cell.column in {6, 7, 9, 10, 12})
            if cell.row == 1:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            elif cell.column in {5, 8}:
                cell.number_format = "0"

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:L{max(1, sheet.max_row)}"
    widths = (38, 34, 64, 34, 12, 24, 42, 16, 24, 30, 14, 36)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.row_dimensions[1].height = 32

    if result.errors:
        error_sheet = workbook.create_sheet(ERRORS_WORKSHEET_NAME)
        error_sheet.append(ERROR_HEADERS)
        for entry in result.errors:
            error_sheet.append([entry[header] for header in ERROR_HEADERS])
        for row in error_sheet.iter_rows():
            for cell in row:
                cell.border = border
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if cell.row == 1:
                    cell.fill = header_fill
                    cell.font = header_font
        error_sheet.freeze_panes = "A2"
        error_sheet.auto_filter.ref = f"A1:D{max(1, error_sheet.max_row)}"
        for index, width in enumerate((48, 36, 14, 90), start=1):
            error_sheet.column_dimensions[get_column_letter(index)].width = width

    workbook.save(output)
    return output.resolve()


def read_input_paths() -> list[str]:
    print("JSON 파일 또는 폴더 경로를 붙여넣으세요:")
    print("(여러 경로는 줄마다 입력하고, 완료하려면 빈 줄을 입력하세요.)")
    paths: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            break
        paths.append(line.strip().strip('"').strip("'"))
    return paths


def _confirm_overwrite(output_path: Path) -> bool:
    while True:
        answer = input(f"'{output_path.name}' 파일이 있습니다. 덮어쓰시겠습니까? (y/n): ").strip().casefold()
        if answer in {"y", "yes", "예"}:
            return True
        if answer in {"n", "no", "아니오"}:
            return False
        print("y 또는 n으로 입력해 주세요.")


def main() -> int:
    input_paths = read_input_paths()
    if not input_paths:
        print("입력 경로가 없어 빈 검수 목록을 생성합니다.")
    output_path = Path.cwd() / OUTPUT_FILENAME
    result = review_paths(
        input_paths,
        progress_callback=lambda count: print(f"\r처리한 JSON 파일: {count:,}개", end="", flush=True),
    )
    if result.total_json_files:
        print()
    if output_path.exists() and not _confirm_overwrite(output_path):
        print("저장을 취소했습니다. 기존 파일은 변경되지 않았습니다.")
        return 1
    try:
        saved_path = write_workbook(result, output_path)
    except OSError as exc:
        print(f"엑셀 저장에 실패했습니다: {exc}", file=sys.stderr)
        return 1
    print(f"분석한 JSON 파일 수: {result.total_json_files:,}")
    print(f"정상 읽기 JSON 파일 수: {result.readable_json_files:,}")
    print(f"복수 무기타입 검수 대상 수: {len(result.items):,}")
    print(f"오류/확인 필요 항목 수: {len(result.errors):,}")
    print(f"JSON 탐색 시간: {result.timings['discovery_seconds']:.3f}초")
    print(f"JSON 처리 시간: {result.timings['processing_seconds']:.3f}초")
    print(f"결과 파일: {saved_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
