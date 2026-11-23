"""Adapt CLI results and calculate dashboard-only inventory checks."""
from __future__ import annotations

import posixpath
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory

from openpyxl import load_workbook

from data_preprocessing import folder_object_distribution as distribution
from data_preprocessing import multi_weapon_review as review

from streamlit_app.file_handler import Dataset, Issue, image_name, path_parts

ANALYSIS_OPTIONS = {
    "전체 분석": "all",
    "객체 및 폴더별 분포 분석": "distribution",
    "복수 무기타입 검수": "review",
}
REVIEW_TYPES = ("서로 다른 복수 무기타입", "중복 및 복수 무기타입", "동일 무기타입 중복 의심")
EXCEL_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


@dataclass(frozen=True)
class Folder:
    name: str
    images: int
    objects: int

    @property
    def average(self) -> float:
        return self.objects / self.images if self.images else 0.0


@dataclass(frozen=True)
class ReviewRow:
    path: str
    folder: str
    filename: str
    object_number: int
    object_class: str
    weapon_type: str
    kind: str
    object_count: int


@dataclass
class Result:
    mode: str
    total_images: int
    image_count_inferred: bool
    anomalies: dict[str, list[Issue] | None]
    matches: dict[str, str]
    total_objects: int | None = None
    classes: dict[str, int] = field(default_factory=dict)
    folders: list[Folder] = field(default_factory=list)
    reviews: list[ReviewRow] = field(default_factory=list)
    workbooks: dict[str, bytes] = field(default_factory=dict)
    seconds: float = 0


def image_folders(folder: PurePosixPath) -> list[PurePosixPath]:
    folders = [folder]
    for index, part in enumerate(folder.parts):
        if part.casefold() in {"labels", "label", "labels_fixed", "annotations", "json"}:
            for sibling in ("images", "image"):
                folders.append(PurePosixPath(*folder.parts[:index], sibling, *folder.parts[index + 1:]))
    return folders


def inspect_dataset(dataset: Dataset) -> tuple[dict[str, list[Issue] | None], dict[str, str]]:
    """Use upload inventory for file checks independently of the CLI's object counts."""
    empty = [Issue(path, "Labelme shapes 배열이 비어 있습니다.") for path, info in dataset.valid.items()
             if not info.shape_count]
    if not dataset.images:
        return {"empty": empty, "missing": None, "invalid": dataset.json_issues, "mismatch": None}, {}
    by_stem = defaultdict(list)
    by_name = {}
    for image in dataset.images:
        path = PurePosixPath(image)
        by_stem[(str(path.parent).casefold(), path.stem.casefold())].append(image)
        by_name[image.casefold()] = image

    matched = {}
    paired_or_ambiguous = set()
    mismatches = []
    for filename in dataset.annotations:
        path = PurePosixPath(filename)
        info = dataset.valid.get(filename)
        declared_path = info.image_path.strip().replace("\\", "/") if info else ""
        declared = image_name(declared_path)
        folders = image_folders(path.parent)
        exact = None
        if declared_path and not declared_path.startswith("/") and not PureWindowsPath(declared_path).drive:
            key = posixpath.normpath((path.parent / declared_path).as_posix()).casefold()
            exact = by_name.get(key)
        candidates = [exact] if exact else []
        if not candidates:
            for folder in folders:
                candidates = by_stem.get((str(folder).casefold(), path.stem.casefold()), [])
                if candidates:
                    break
        if not candidates and declared:
            candidates = [by_name[key] for folder in folders
                          if (key := (folder / declared).as_posix().casefold()) in by_name]
        if not candidates:
            continue
        preferred = next((name for name in candidates if PurePosixPath(name).name.casefold() == declared.casefold()), None)
        if len(candidates) > 1 and preferred is None:
            paired_or_ambiguous.update(candidates)
            mismatches.append(Issue(filename, "동일 이름의 이미지 후보가 여러 개입니다. " + ", ".join(candidates)))
            continue
        image = preferred or candidates[0]
        paired_or_ambiguous.add(image)
        matched[filename] = image
        image_base = PurePosixPath(image).name
        if PurePosixPath(image).stem.casefold() != path.stem.casefold():
            mismatches.append(Issue(filename, f"JSON 파일명과 이미지 이름({image_base})이 다릅니다."))
        elif declared and declared.casefold() != image_base.casefold():
            mismatches.append(Issue(filename, f"imagePath의 파일명({declared})과 실제 이미지({image_base})가 다릅니다."))
    missing = [Issue(image, "같은 폴더 또는 대응 어노테이션 폴더에서 JSON을 찾을 수 없습니다.")
               for image in dataset.images if image not in paired_or_ambiguous]
    return {"empty": empty, "missing": missing, "invalid": dataset.json_issues, "mismatch": mismatches}, matched


def filter_reviews(rows: list[ReviewRow], kind=None, folder=None, object_class=None) -> list[ReviewRow]:
    return [row for row in rows if (kind is None or row.kind == kind)
            and (folder is None or row.folder == folder)
            and (object_class is None or row.object_class == object_class)]


def excel_text(value: str) -> str:
    return EXCEL_CONTROL.sub(lambda match: f"\\u{ord(match[0]):04x}", value)


def workbook_bytes(path: Path) -> bytes:
    # These reports contain no intended formulas. Preserve user-supplied text as text.
    workbook = load_workbook(path)
    try:
        for sheet in workbook:
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.data_type == "f":
                        cell.data_type = "s"
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()
    finally:
        workbook.close()


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def run_analysis(dataset: Dataset, mode: str) -> Result:
    if mode not in ANALYSIS_OPTIONS.values():
        raise ValueError("지원하지 않는 분석 옵션입니다.")
    started = time.perf_counter()
    anomalies, matches = inspect_dataset(dataset)
    result = Result(mode, len(dataset.images) if dataset.images else len(dataset.valid),
                    not dataset.images, anomalies, matches)
    with TemporaryDirectory(prefix="hanwha-labelme-") as temporary:
        workspace = Path(temporary).resolve()
        root = workspace / "dataset"
        root.mkdir()
        for files in (dataset.annotations, dataset.images):
            for filename, content in files.items():
                target = root.joinpath(*path_parts(filename))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        if mode in {"all", "distribution"}:
            aggregate = distribution.analyze_paths([root])
            counts = Counter()
            objects_by_folder = {}
            for folder in aggregate.folders:
                counts.update(folder.counts)
                objects_by_folder[relative(folder.path, root)] = sum(folder.counts.values())
            images_by_folder = Counter(str(PurePosixPath(path).parent) for path in dataset.images)
            folder_names = sorted(objects_by_folder.keys() | images_by_folder.keys())
            result.total_objects = aggregate.total_objects
            result.classes = {name: counts[name] for name in distribution.ALL_LABELS}
            result.folders = [Folder(name, images_by_folder[name], objects_by_folder.get(name, 0)) for name in folder_names]
            # Keep the CLI workbook shape and isolate text sanitization to the upload surface.
            export = replace(aggregate, independent_weapon_bboxes=[
                replace(item, image_path=excel_text(item.image_path)) for item in aggregate.independent_weapon_bboxes
            ])
            output = workspace / distribution.OUTPUT_FILENAME
            distribution.write_workbook(export, output)
            result.workbooks[output.name] = workbook_bytes(output)
        if mode in {"all", "review"}:
            reviewed = review.review_paths([root])
            for item in reviewed.items:
                path = relative(item.json_path, root)
                info = dataset.valid.get(path)
                result.reviews.append(ReviewRow(
                    path, relative(item.json_path.parent, root), item.json_filename, item.object_number,
                    excel_text(item.object_class), excel_text(item.weapon_value), item.duplicate_status,
                    info.shape_count if info else 0,
                ))
            export = replace(reviewed, items=[
                replace(item, image_filename=excel_text(item.image_filename), object_class=excel_text(item.object_class),
                        weapon_value=excel_text(item.weapon_value), weapon_direction=excel_text(item.weapon_direction))
                for item in reviewed.items
            ])
            output = workspace / review.OUTPUT_FILENAME
            review.write_workbook(export, output)
            result.workbooks[output.name] = workbook_bytes(output)
    result.seconds = time.perf_counter() - started
    return result
