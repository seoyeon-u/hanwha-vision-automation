"""Aggregate LabelMe JSON annotations into a folder-level Excel workbook."""

from __future__ import annotations

import codecs
import json
import os
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


WORKSHEET_NAME = "폴더별 객체 분포 집계"
WEAPON_BBOX_WORKSHEET_NAME = "독립 무기 BBox 상세"
ERRORS_WORKSHEET_NAME = "집계 오류 로그"
OUTPUT_FILENAME = "폴더별 객체 분포 집계.xlsx"
HEADERS = [
    "폴더 경로",
    "이미지 수량",
    "json 수량",
    "민간인",
    "군인",
    "민간차량",
    "소형전술차량",
    "전차",
    "자주포",
    "장갑차",
    "소총",
    "대전차화기",
    "원격무장",
    "포/포탑",
]
CLASS_LABELS = HEADERS[3:10]
WEAPON_LABELS = HEADERS[10:14]
ALL_LABELS = CLASS_LABELS + WEAPON_LABELS
LABEL_INDEX = {label: index for index, label in enumerate(ALL_LABELS)}
WEAPON_LABEL_SET = frozenset(WEAPON_LABELS)
IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
PROGRESS_FILE_INTERVAL = 250
PROGRESS_TIME_INTERVAL = 1.0
MAX_PENDING_FILES_PER_WORKER = 2


@dataclass
class FolderResult:
    path: Path
    display_path: str
    image_count: int = 0
    json_count: int = 0
    counts: Counter[str] = field(default_factory=Counter)


@dataclass
class AnalysisResult:
    folders: list[FolderResult]
    errors: list[dict[str, str]]
    total_objects: int
    total_json_files: int
    total_images: int
    timings: dict[str, float] = field(default_factory=dict)
    independent_weapon_bboxes: list[WeaponBBoxDetail] = field(default_factory=list)

    @property
    def error_json_count(self) -> int:
        return len(
            {
                (entry["폴더 경로"], entry["JSON 파일명"])
                for entry in self.errors
                if entry["JSON 파일명"]
            }
        )

    @property
    def weapon_totals(self) -> Counter[str]:
        totals: Counter[str] = Counter()
        for folder in self.folders:
            totals.update({label: folder.counts[label] for label in WEAPON_LABELS})
        return totals


@dataclass
class ProcessedFile:
    path: Path
    readable_json: bool
    counts: Counter[str] = field(default_factory=Counter)
    total_objects: int = 0
    independent_weapon_bboxes: list[WeaponBBoxDetail] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    read_parse_seconds: float = 0.0
    bbox_seconds: float = 0.0


@dataclass
class WeaponBBoxDetail:
    folder_path: str
    weapon_type: str
    json_filename: str
    json_path: Path
    image_path: str
    bbox_index: int
    bbox_coordinates: str


def _error(
    errors: list[dict[str, str]],
    folder_path: str,
    json_filename: str,
    object_index: str,
    reason: str,
) -> None:
    errors.append(
        {
            "폴더 경로": folder_path,
            "JSON 파일명": json_filename,
            "객체 인덱스": object_index,
            "오류 또는 확인 필요 사유": reason,
        }
    )


def _display_paths(
    folders: Iterable[Path], roots: list[Path]
) -> dict[Path, str]:
    result: dict[Path, str] = {}
    for folder in folders:
        candidate_paths: list[str] = []
        for root in roots:
            try:
                relative = folder.relative_to(root)
            except ValueError:
                continue
            candidate_paths.append(root.name if str(relative) == "." else str(relative))
        result[folder] = min(
            candidate_paths,
            key=lambda value: (len(Path(value).parts), value.casefold()),
        ) if candidate_paths else folder.name

    labels: dict[str, list[Path]] = defaultdict(list)
    for folder, label in result.items():
        labels[label.casefold()].append(folder)
    duplicate_folders = [
        folder
        for group in labels.values()
        if len(group) > 1
        for folder in group
    ]
    if duplicate_folders:
        try:
            common_root = Path(os.path.commonpath([str(root) for root in roots]))
        except ValueError:
            common_root = Path(duplicate_folders[0].anchor)
        for folder in duplicate_folders:
            try:
                result[folder] = str(folder.relative_to(common_root))
            except ValueError:
                result[folder] = str(folder)
    return result


def _process_json_file(json_path: Path) -> ProcessedFile:
    errors: list[dict[str, str]] = []
    result = ProcessedFile(json_path, readable_json=False, errors=errors)
    read_started = time.perf_counter()
    try:
        with json_path.open("rb") as json_file:
            raw_json = json_file.read()
        if raw_json.startswith(codecs.BOM_UTF8):
            raw_json = raw_json[len(codecs.BOM_UTF8):]
        data = json.loads(raw_json)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        result.read_parse_seconds = time.perf_counter() - read_started
        _error(
            errors,
            str(json_path.parent),
            json_path.name,
            "",
            f"JSON 파일을 읽을 수 없습니다: {exc}",
        )
        return result
    result.read_parse_seconds = time.perf_counter() - read_started
    result.readable_json = True

    if not isinstance(data, dict):
        _error(
            errors,
            str(json_path.parent),
            json_path.name,
            "",
            "JSON 최상위 값이 객체(dict)가 아닙니다.",
        )
        return result

    shapes = data.get("shapes")
    if not isinstance(shapes, list):
        _error(
            errors,
            str(json_path.parent),
            json_path.name,
            "",
            "shapes 필드가 없거나 배열 형식이 아닙니다.",
        )
        return result

    image_path = data.get("imagePath")
    image_path_value = image_path if isinstance(image_path, str) else ""
    bbox_started = time.perf_counter()
    for shape_index, shape in enumerate(shapes):
        object_index = str(shape_index)
        if not isinstance(shape, dict):
            _error(
                errors,
                str(json_path.parent),
                json_path.name,
                object_index,
                "객체 항목이 JSON 객체(dict)가 아닙니다.",
            )
            continue

        label = shape.get("label")
        if isinstance(label, str):
            representative_label = label.partition(">")[0].strip()
            label_index = LABEL_INDEX.get(representative_label)
        else:
            representative_label = None
            label_index = None

        if label_index is None:
            _error(
                errors,
                str(json_path.parent),
                json_path.name,
                object_index,
                f"인식되지 않는 대표 label입니다: {label!r}",
            )
        else:
            result.counts[ALL_LABELS[label_index]] += 1
            result.total_objects += 1
            if representative_label in WEAPON_LABEL_SET:
                points = shape.get("points")
                result.independent_weapon_bboxes.append(
                    WeaponBBoxDetail(
                        folder_path=str(json_path.parent),
                        weapon_type=representative_label,
                        json_filename=json_path.name,
                        json_path=json_path,
                        image_path=image_path_value,
                        bbox_index=shape_index + 1,
                        bbox_coordinates=(
                            json.dumps(points, ensure_ascii=False, separators=(",", ":"))
                            if points is not None
                            else ""
                        ),
                    )
                )
    result.bbox_seconds = time.perf_counter() - bbox_started
    return result


def analyze_paths(
    input_paths: Iterable[str | Path],
    progress_callback: Callable[[int, int], None] | None = None,
    max_workers: int = 1,
) -> AnalysisResult:
    """Scan and aggregate annotations, limiting concurrent file work when enabled."""
    discovery_started = time.perf_counter()
    errors: list[dict[str, str]] = []
    roots: list[Path] = []
    directory_roots: list[Path] = []
    files: set[Path] = set()
    direct_file_folders: set[Path] = set()

    for raw_path in input_paths:
        raw_text = str(raw_path).strip().strip('"').strip("'")
        try:
            path = Path(raw_text).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            _error(errors, raw_text, "", "", f"경로를 찾을 수 없거나 접근할 수 없습니다: {exc}")
            continue

        if path.is_file():
            if path.suffix.casefold() != ".json":
                _error(errors, str(path.parent), path.name, "", "JSON 파일이 아닙니다.")
                continue
            roots.append(path.parent)
            files.add(path)
            direct_file_folders.add(path.parent)
            continue

        if not path.is_dir():
            _error(errors, str(path), "", "", "파일 또는 폴더 경로가 아닙니다.")
            continue

        roots.append(path)
        directory_roots.append(path)

    unique_directory_roots = {
        os.path.normcase(str(path)): path for path in directory_roots
    }
    directory_roots = sorted(
        unique_directory_roots.values(),
        key=lambda path: (len(path.parts), str(path).casefold()),
    )
    scan_roots: list[Path] = []
    for path in directory_roots:
        if not any(path == parent or parent in path.parents for parent in scan_roots):
            scan_roots.append(path)

    directory_root_set = set(directory_roots)
    image_counts: dict[Path, int] = {}
    json_folders: set[Path] = set()
    root_json_presence: dict[Path, bool] = {path: False for path in directory_roots}

    def scan_failure(path: Path, exc: OSError) -> None:
        _error(
            errors,
            str(path),
            "",
            "",
            f"폴더를 탐색할 수 없습니다: {exc}",
        )

    for root in scan_roots:
        pending_directories = [root]
        while pending_directories:
            current = pending_directories.pop()
            image_count = 0
            has_json_in_directory = False
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                pending_directories.append(Path(entry.path))
                            else:
                                suffix = os.path.splitext(entry.name)[1].casefold()
                                if suffix in IMAGE_EXTENSIONS or suffix == ".json":
                                    if entry.is_file():
                                        if suffix in IMAGE_EXTENSIONS:
                                            image_count += 1
                                        else:
                                            json_path = Path(entry.path)
                                            files.add(json_path)
                                            json_folders.add(current)
                                            has_json_in_directory = True
                        except OSError as exc:
                            scan_failure(Path(entry.path), exc)
            except OSError as exc:
                scan_failure(current, exc)
            if has_json_in_directory or current in directory_root_set:
                image_counts[current] = image_count

    roots_with_json: set[Path] = set()
    for json_folder in json_folders:
        current = json_folder
        while True:
            if current in directory_root_set:
                roots_with_json.add(current)
            parent = current.parent
            if parent == current:
                break
            current = parent
    for path in roots_with_json:
        root_json_presence[path] = True

    folders_without_json = {
        path for path, has_json in root_json_presence.items() if not has_json
    }

    for folder in direct_file_folders:
        if folder not in image_counts:
            image_count = 0
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        try:
                            if os.path.splitext(entry.name)[1].casefold() in IMAGE_EXTENSIONS and entry.is_file():
                                image_count += 1
                        except OSError as exc:
                            scan_failure(Path(entry.path), exc)
            except OSError as exc:
                scan_failure(folder, exc)
            image_counts[folder] = image_count

    folder_paths = json_folders | folders_without_json | direct_file_folders
    display_paths = _display_paths(folder_paths, roots)
    results = {
        folder: FolderResult(
            folder,
            display_paths[folder],
            image_count=image_counts.get(folder, 0),
        )
        for folder in folder_paths
    }
    sorted_files = sorted(files, key=lambda path: str(path).casefold())
    del files, image_counts, json_folders, root_json_presence, roots_with_json
    del directory_root_set, folders_without_json, direct_file_folders, directory_roots, scan_roots, roots
    discovery_seconds = time.perf_counter() - discovery_started

    total_objects = 0
    total_json_files = 0
    worker_read_parse_seconds = 0.0
    worker_bbox_seconds = 0.0
    merge_seconds = 0.0
    file_errors: list[dict[str, str]] = []
    independent_weapon_bboxes: list[WeaponBBoxDetail] = []
    processing_started = time.perf_counter()
    progress_started = processing_started
    def merge_processed_file(processed: ProcessedFile) -> None:
        nonlocal total_objects, total_json_files, merge_seconds
        merge_started = time.perf_counter()
        folder_result = results.get(processed.path.parent)
        if folder_result is None:
            folder_result = FolderResult(
                processed.path.parent,
                display_paths.get(processed.path.parent, processed.path.parent.name),
            )
            results[processed.path.parent] = folder_result
        if processed.readable_json:
            total_json_files += 1
            folder_result.json_count += 1
        folder_result.counts.update(processed.counts)
        total_objects += processed.total_objects
        independent_weapon_bboxes.extend(processed.independent_weapon_bboxes)
        file_errors.extend(processed.errors)
        merge_seconds += time.perf_counter() - merge_started

    def report_progress(completed: int) -> None:
        nonlocal progress_started
        if progress_callback is None:
            return
        now = time.perf_counter()
        if (
            completed == len(sorted_files)
            or completed % PROGRESS_FILE_INTERVAL == 0
            or now - progress_started >= PROGRESS_TIME_INTERVAL
        ):
            progress_callback(completed, len(sorted_files))
            progress_started = now

    if max_workers <= 1:
        for index, json_path in enumerate(sorted_files, start=1):
            processed = _process_json_file(json_path)
            worker_read_parse_seconds += processed.read_parse_seconds
            worker_bbox_seconds += processed.bbox_seconds
            merge_processed_file(processed)
            report_progress(index)
    elif sorted_files:
        worker_count = min(max_workers, len(sorted_files))
        max_pending = worker_count * MAX_PENDING_FILES_PER_WORKER
        file_iterator = iter(sorted_files)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            pending = set()
            while len(pending) < max_pending:
                try:
                    pending.add(executor.submit(_process_json_file, next(file_iterator)))
                except StopIteration:
                    break
            completed = 0
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    processed = future.result()
                    worker_read_parse_seconds += processed.read_parse_seconds
                    worker_bbox_seconds += processed.bbox_seconds
                    merge_processed_file(processed)
                    completed += 1
                    report_progress(completed)
                while len(pending) < max_pending:
                    try:
                        pending.add(executor.submit(_process_json_file, next(file_iterator)))
                    except StopIteration:
                        break
    processing_wall_seconds = time.perf_counter() - processing_started
    errors.extend(
        sorted(
            file_errors,
            key=lambda entry: (
                entry["폴더 경로"].casefold(),
                entry["JSON 파일명"].casefold(),
                int(entry["객체 인덱스"]) if entry["객체 인덱스"].isdigit() else -1,
                entry["오류 또는 확인 필요 사유"],
            ),
        )
    )

    weapon_bbox_count = sum(
        folder.counts[label]
        for folder in results.values()
        for label in WEAPON_LABELS
    )
    if weapon_bbox_count != len(independent_weapon_bboxes):
        _error(
            errors,
            "",
            "",
            "",
            "독립 무기 BBox 상세 건수와 집계 수량이 일치하지 않습니다: "
            f"집계={weapon_bbox_count}, 상세={len(independent_weapon_bboxes)}",
        )
    independent_weapon_bboxes.sort(
        key=lambda item: (
            item.folder_path.casefold(),
            item.json_filename.casefold(),
            item.bbox_index,
        )
    )

    folder_list = sorted(
        results.values(), key=lambda item: (item.display_path.casefold(), str(item.path).casefold())
    )
    return AnalysisResult(
        folders=folder_list,
        errors=errors,
        total_objects=total_objects,
        total_json_files=total_json_files,
        total_images=sum(folder.image_count for folder in folder_list),
        independent_weapon_bboxes=independent_weapon_bboxes,
        timings={
            "discovery_seconds": discovery_seconds,
            "processing_wall_seconds": processing_wall_seconds,
            "worker_read_parse_seconds": worker_read_parse_seconds,
            "worker_bbox_seconds": worker_bbox_seconds,
            "merge_wall_seconds": merge_seconds,
        },
    )


def write_workbook(result: AnalysisResult, output_path: str | Path) -> Path:
    """Write the summary and, when needed, the validation log."""
    output = Path(output_path)
    workbook = Workbook()
    summary = workbook.active
    summary.title = WORKSHEET_NAME
    summary.append(HEADERS)

    for folder in result.folders:
        summary.append(
            [
                folder.display_path,
                folder.image_count,
                folder.json_count,
                *(folder.counts[label] for label in CLASS_LABELS),
                *(folder.counts[label] for label in WEAPON_LABELS),
            ]
        )

    total_row = summary.max_row + 1
    summary.append(
        [
            "전체 합계",
            sum(folder.image_count for folder in result.folders),
            sum(folder.json_count for folder in result.folders),
            *(
                sum(folder.counts[label] for folder in result.folders)
                for label in CLASS_LABELS + WEAPON_LABELS
            ),
        ]
    )

    header_fill = PatternFill("solid", fgColor="1F4E78")
    total_fill = PatternFill("solid", fgColor="D9EAF7")
    header_font = Font(bold=True, color="FFFFFF")
    total_font = Font(bold=True)
    thin_gray = Side(style="thin", color="B7C9D6")
    border = Border(left=thin_gray, right=thin_gray, top=thin_gray, bottom=thin_gray)

    for row in summary.iter_rows():
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(vertical="center")
            if cell.row == 1:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif cell.row == total_row:
                cell.fill = total_fill
                cell.font = total_font
            elif cell.column >= 2:
                cell.number_format = "0"
    summary.freeze_panes = "A2"
    summary.auto_filter.ref = f"A1:N{total_row - 1}" if total_row > 2 else "A1:N1"
    summary.column_dimensions["A"].width = max(
        24, min(60, max((len(str(row[0].value or "")) for row in summary.iter_rows(min_col=1, max_col=1)), default=0) + 2)
    )
    for column in range(2, len(HEADERS) + 1):
        summary.column_dimensions[get_column_letter(column)].width = 14
    summary.row_dimensions[1].height = 24

    weapon_details = workbook.create_sheet(WEAPON_BBOX_WORKSHEET_NAME)
    weapon_detail_headers = [
        "번호",
        "폴더 경로",
        "무기 객체 유형",
        "JSON 파일명",
        "JSON 파일 전체 경로",
        "이미지 파일명",
        "BBox 인덱스",
        "BBox 좌표",
    ]
    weapon_details.append(weapon_detail_headers)
    for row_number, detail in enumerate(result.independent_weapon_bboxes, start=1):
        weapon_details.append(
            [
                row_number,
                detail.folder_path,
                detail.weapon_type,
                detail.json_filename,
                str(detail.json_path),
                detail.image_path,
                detail.bbox_index,
                detail.bbox_coordinates,
            ]
        )
        path_cell = weapon_details.cell(row=weapon_details.max_row, column=5)
        path_cell.hyperlink = detail.json_path.resolve().as_uri()
        path_cell.style = "Hyperlink"
    for row in weapon_details.iter_rows():
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=cell.column in {2, 5, 6, 8})
            if cell.row == 1:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            elif cell.column in {1, 7}:
                cell.number_format = "0"
    weapon_details.freeze_panes = "A2"
    weapon_details.auto_filter.ref = f"A1:H{max(1, weapon_details.max_row)}"
    for column, width in enumerate((10, 48, 18, 38, 72, 42, 14, 48), start=1):
        weapon_details.column_dimensions[get_column_letter(column)].width = width
    weapon_details.row_dimensions[1].height = 30

    if result.errors:
        errors_sheet = workbook.create_sheet(ERRORS_WORKSHEET_NAME)
        error_headers = ["폴더 경로", "JSON 파일명", "객체 인덱스", "오류 또는 확인 필요 사유"]
        errors_sheet.append(error_headers)
        for entry in result.errors:
            errors_sheet.append([entry[header] for header in error_headers])
        for row in errors_sheet.iter_rows():
            for cell in row:
                cell.border = border
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if cell.row == 1:
                    cell.fill = header_fill
                    cell.font = header_font
        errors_sheet.freeze_panes = "A2"
        errors_sheet.auto_filter.ref = f"A1:D{errors_sheet.max_row}"
        for column, width in enumerate((55, 38, 14, 90), start=1):
            errors_sheet.column_dimensions[get_column_letter(column)].width = width

    workbook.save(output)
    return output.resolve()


def read_input_paths() -> list[str]:
    print("JSON 파일 또는 폴더 경로를 붙여넣으세요:")
    print("(여러 경로는 줄마다 붙여넣고, 입력을 마치려면 빈 줄을 입력하세요.)")
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
        answer = input(f"'{output_path.name}' 파일이 이미 있습니다. 덮어쓰시겠습니까? (y/n): ").strip().casefold()
        if answer in {"y", "yes", "예"}:
            return True
        if answer in {"n", "no", "아니오"}:
            return False
        print("y 또는 n으로 입력해 주세요.")


def main() -> int:
    input_paths = read_input_paths()
    run_started = time.perf_counter()
    if not input_paths:
        print("입력한 경로가 없습니다. 헤더가 포함된 빈 결과 파일을 생성합니다.")
        errors = [
            {
                "폴더 경로": "",
                "JSON 파일명": "",
                "객체 인덱스": "",
                "오류 또는 확인 필요 사유": "분석할 경로가 입력되지 않았습니다.",
            }
        ]
        result = AnalysisResult([], errors, 0, 0, 0)
    else:
        result = analyze_paths(
            input_paths,
            progress_callback=lambda current, total: print(
                f"\r처리 진행: {current:,} / {total:,} "
                f"({current / total:.1%})",
                end="",
                flush=True,
            ),
        )
        if result.total_json_files:
            print()

    output_path = Path.cwd() / OUTPUT_FILENAME
    if output_path.exists() and not _confirm_overwrite(output_path):
        print("저장을 취소했습니다. 기존 파일은 변경되지 않았습니다.")
        return 1
    try:
        workbook_started = time.perf_counter()
        saved_path = write_workbook(result, output_path)
        workbook_seconds = time.perf_counter() - workbook_started
    except OSError as exc:
        print(f"엑셀 파일 저장에 실패했습니다: {exc}", file=sys.stderr)
        return 1

    total_seconds = time.perf_counter() - run_started
    files_per_second = result.total_json_files / total_seconds if total_seconds else 0.0
    print("\n[처리 결과]")
    print(f"- JSON 파일 수: {result.total_json_files:,}개")
    print(f"- 분석 폴더 수: {len(result.folders):,}개")
    print(f"- 정상 처리 수량: {result.total_json_files:,}개")
    print(f"- 발견한 이미지 파일 수: {result.total_images:,}개")
    print(f"- 인식된 대표 객체 BBox 수: {result.total_objects:,}개")
    print(f"- 오류 파일 수: {result.error_json_count:,}개")
    print(f"- 초당 처리 파일 수: {files_per_second:,.1f}개/초")
    print(f"- 전체 실행 시간: {total_seconds:.3f}초")
    print(
        "- 폴더/파일 탐색 시간: "
        f"{result.timings.get('discovery_seconds', 0.0):.3f}초"
    )
    print(
        "- JSON 읽기/파싱/분류 실제 경과 시간: "
        f"{result.timings.get('processing_wall_seconds', 0.0):.3f}초"
    )
    print(
        "- JSON 읽기/파싱 작업자 누적 시간: "
        f"{result.timings.get('worker_read_parse_seconds', 0.0):.3f}초"
    )
    print(
        "- BBox 집계 작업자 누적 시간: "
        f"{result.timings.get('worker_bbox_seconds', 0.0):.3f}초"
    )
    print(f"- 폴더별 결과 취합 경과 시간: {result.timings.get('merge_wall_seconds', 0.0):.3f}초")
    print(f"- 엑셀 생성/저장 시간: {workbook_seconds:.3f}초")
    print("- 무기 유형별 대표 BBox 수:")
    for weapon in WEAPON_LABELS:
        print(f"  {weapon}: {result.weapon_totals[weapon]:,}")
    if result.errors:
        print(
            f"- 오류 로그 항목 수: {len(result.errors):,}개 "
            f"(엑셀의 '{ERRORS_WORKSHEET_NAME}' 시트 확인)"
        )
    print(f"- 엑셀 파일 경로: {saved_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
