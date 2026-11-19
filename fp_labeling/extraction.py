"""Match and copy Labelme review pairs and record processing results."""
import csv
import json
import os
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from uuid import uuid4


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
EXTENSIONS = IMAGE_EXTENSIONS | {".json"}
CSV_COLUMNS = (
    "image_filename", "json_filename", "object_count", "status", "reason",
    "output_path",
)


def collect_files(input_text, groups, report):
    seen = set()

    def add(path):
        if path.suffix.lower() not in EXTENSIONS:
            return
        resolved = path.resolve()
        identity = os.path.normcase(str(resolved))
        if identity in seen:
            return
        seen.add(identity)
        key = (os.path.normcase(str(path.parent.resolve())), path.stem.casefold())
        kind = "json" if path.suffix.lower() == ".json" else "image"
        groups.setdefault(key, {"image": [], "json": []})[kind].append(path)

    for line in input_text.splitlines():
        value = line.strip().strip('"')
        if not value:
            continue
        try:
            path = Path(value).absolute()
            if path.is_dir():
                # Scan only this folder so previous output subfolders stay out.
                for child in sorted(path.iterdir()):
                    try:
                        if child.is_file():
                            add(child)
                    except (OSError, ValueError, RuntimeError) as exc:
                        report(child, f"파일 접근 실패 ({exc})")
            elif not path.is_file():
                report(path, "경로가 없거나 파일에 접근할 수 없습니다.")
            elif path.suffix.lower() not in EXTENSIONS:
                report(path, "지원하지 않는 확장자입니다.")
            else:
                add(path)
        except (OSError, ValueError, RuntimeError) as exc:
            report(value, f"경로 처리 실패 ({exc})")


def copy_pair(image, annotation, output):
    """Reserve both names exclusively before copying either source."""
    reserved = []
    try:
        for source in (image, annotation):
            target = output / source.name
            with target.open("xb"):
                reserved.append(target)
        for source, target in zip((image, annotation), reserved):
            shutil.copy2(source, target)
    except OSError as exc:
        cleanup_errors = []
        for target in reversed(reserved):
            try:
                target.unlink()
            except PermissionError:
                # On Windows copy2 may have copied a read-only attribute.
                try:
                    target.chmod(0o600)
                    target.unlink()
                except OSError as cleanup_exc:
                    cleanup_errors.append(str(cleanup_exc))
            except OSError as cleanup_exc:
                cleanup_errors.append(str(cleanup_exc))
        reason = f"출력 파일명 충돌 ({exc.filename})" if isinstance(
            exc, FileExistsError
        ) else f"복사 실패 ({exc})"
        if cleanup_errors:
            reason += " / 생성 파일 정리 실패 (" + ", ".join(cleanup_errors) + ")"
        return False, isinstance(exc, FileExistsError), reason
    return True, False, ""


def extract(input_text, output, notify):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    groups = {}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = output / f"처리내역_{stamp}_{uuid4().hex[:8]}.csv"
    with log_path.open("x", encoding="utf-8-sig", newline="") as log:
        writer = csv.writer(log)
        writer.writerow(CSV_COLUMNS)

        def report(path, reason):
            stats["input_warnings"] += 1
            name = Path(path).name
            suffix = Path(path).suffix.lower()
            writer.writerow((
                name if suffix in IMAGE_EXTENSIONS else "",
                name if suffix == ".json" else "",
                "", "error", f"{path} — {reason}", "",
            ))
            notify("message", f"[경고] {path} — {reason}")

        notify("message", "입력 경로를 검색하고 있습니다.")
        collect_files(input_text, groups, report)
        total = len(groups)
        notify("progress", (0, total))
        for index, group in enumerate(groups.values(), 1):
            images, annotations = group["image"], group["json"]
            image_names = " / ".join(path.name for path in images)
            json_names = " / ".join(path.name for path in annotations)
            paths = images + annotations
            count, status, reason, destination = "", "error", "", ""
            level = "오류"
            if not images or not annotations:
                stats["missing"] += 1
                reason = "대응 이미지 누락" if not images else "대응 JSON 누락"
                level = "경고"
            elif len(images) != 1 or len(annotations) != 1:
                stats["collisions"] += 1
                reason = "같은 폴더에서 기본 이름이 같은 이미지 또는 JSON이 여러 개입니다."
                level = "경고"
            else:
                stats["pairs"] += 1
                image, annotation = images[0], annotations[0]
                try:
                    with annotation.open(encoding="utf-8-sig") as source:
                        data = json.load(source)
                    if not isinstance(data, dict):
                        raise ValueError("JSON 최상위 값이 객체가 아닙니다.")
                    if "shapes" not in data:
                        raise KeyError("shapes")
                    shapes = data["shapes"]
                    if not isinstance(shapes, list):
                        raise ValueError("shapes 값이 배열이 아닙니다.")
                except KeyError:
                    stats["missing_shapes"] += 1
                    reason = "shapes 키가 없습니다."
                    level = "경고"
                except (OSError, ValueError, RecursionError) as exc:
                    stats["json_errors"] += 1
                    reason = f"JSON 읽기 또는 형식 오류 ({exc})"
                else:
                    count = len(shapes)
                    if count == 0:
                        stats["empty"] += 1
                        status, reason = "excluded", "shapes 배열이 비어 있습니다."
                    else:
                        stats["with_objects"] += 1
                        copied, collision, reason = copy_pair(image, annotation, output)
                        if copied:
                            stats["copied"] += 1
                            status, destination = "copied", str(output)
                        elif collision:
                            stats["collisions"] += 1
                            level = "경고"
                        else:
                            stats["copy_errors"] += 1
            if status == "error":
                sources = " / ".join(str(path) for path in paths)
                notify("message", f"[{level}] {sources} — {reason}")
                reason = f"{reason} / 입력: {sources}"
            writer.writerow((image_names, json_names, count, status, reason, destination))
            notify("progress", (index, total))
    return stats, output, log_path
