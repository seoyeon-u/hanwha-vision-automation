"""Validate uploaded datasets and keep all archive paths relative."""
from __future__ import annotations

import json
import re
import stat
import time
import unicodedata
import zlib
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePosixPath
from typing import Iterable, Protocol
from zipfile import BadZipFile, ZipFile

from PIL import Image

from data_preprocessing.folder_object_distribution import IMAGE_EXTENSIONS

MAX_UPLOAD_MIB = 128
MAX_UPLOAD = MAX_UPLOAD_MIB * 1024**2
MAX_EXPANDED = 256 * 1024**2
MAX_FILE = 32 * 1024**2
MAX_ENTRIES = 10_000
DATA_EXTENSIONS = IMAGE_EXTENSIONS | {".json"}
WINDOWS_DEVICE = re.compile(r"(?i:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[0-9¹²³])")


class Upload(Protocol):
    name: str
    size: int

    def getvalue(self) -> bytes: ...


@dataclass(frozen=True)
class Issue:
    file: str
    reason: str


@dataclass(frozen=True)
class AnnotationInfo:
    shape_count: int
    image_path: str


@dataclass
class Dataset:
    uploads: list[str] = field(default_factory=list)
    annotations: dict[str, bytes] = field(default_factory=dict)
    valid: dict[str, AnnotationInfo] = field(default_factory=dict)
    images: dict[str, bytes] = field(default_factory=dict)
    rejected_jsons: int = 0
    json_issues: list[Issue] = field(default_factory=list)
    upload_issues: list[Issue] = field(default_factory=list)
    seconds: float = 0

    @property
    def json_count(self) -> int:
        return len(self.annotations) + self.rejected_jsons


def path_parts(name: str) -> tuple[str, ...]:
    name = name.replace("\\", "/").rstrip("/")
    parts = tuple(name.split("/"))
    if len(parts) > 24 or len(name) > 220 or any(
        not part or part in {".", ".."} or len(part) > 150 or part.endswith((".", " "))
        or re.search(r'[\x00-\x1f<>:"|?*]', part) or WINDOWS_DEVICE.fullmatch(part.split(".", 1)[0].rstrip())
        for part in parts
    ):
        raise ValueError("허용되지 않는 파일 경로입니다.")
    return parts


def labelme(content: bytes) -> dict:
    data = json.loads(content)
    if not isinstance(data, dict) or not isinstance(data.get("shapes"), list):
        raise ValueError("Labelme JSON에 shapes 배열이 필요합니다.")
    return data


def image_name(value: object) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].strip() if isinstance(value, str) else ""


def check_depth(data: object, depth: int = 0) -> None:
    if depth > 100:
        raise RecursionError("JSON 중첩 깊이가 100단계를 초과했습니다.")
    if isinstance(data, (dict, list)):
        for value in data.values() if isinstance(data, dict) else data:
            if isinstance(value, (dict, list)):
                check_depth(value, depth + 1)


def prepare_uploads(uploads: Iterable[Upload]) -> Dataset:
    started = time.perf_counter()
    dataset = Dataset()
    used = set()
    folders = {}
    uploaded = expanded = scanned = 0

    def add(parts: tuple[str, ...], content: bytes) -> None:
        name = "/".join(parts)
        canonical = tuple(unicodedata.normalize("NFC", part).casefold() for part in parts)
        if canonical in used or canonical in folders:
            raise ValueError("같은 경로의 파일이 이미 있어 기존 파일을 유지했습니다.")
        for index in range(1, len(parts)):
            parent = canonical[:index]
            if parent in used or parent in folders and folders[parent] != parts[:index]:
                raise ValueError("대소문자 또는 폴더·파일 경로가 충돌합니다.")
        for index in range(1, len(parts)):
            folders[canonical[:index]] = parts[:index]
        used.add(canonical)
        if PurePosixPath(name).suffix.casefold() != ".json":
            dataset.images[name] = content
            try:
                with Image.open(BytesIO(content)) as image:
                    image.verify()
            except (EOFError, OSError, SyntaxError, TypeError, ValueError, Image.DecompressionBombError):
                dataset.upload_issues.append(Issue(name, "이미지 형식을 확인하거나 파일을 읽을 수 없습니다."))
            return
        try:
            data = labelme(content)
            check_depth(data)
            declared = data.get("imagePath")
            dataset.valid[name] = AnnotationInfo(len(data["shapes"]), declared if isinstance(declared, str) else "")
            invalid_shapes = sum(not isinstance(shape, dict) for shape in data["shapes"])
            if invalid_shapes:
                dataset.json_issues.append(Issue(name, f"객체 형식이 올바르지 않은 shapes 항목 {invalid_shapes}개"))
        except RecursionError:
            dataset.json_issues.append(Issue(name, "JSON 중첩 깊이 초과로 분석에서 제외했습니다."))
            dataset.rejected_jsons += 1
            return
        except (ValueError, UnicodeError) as exc:
            dataset.json_issues.append(Issue(name, f"JSON 파싱 또는 구조 오류 ({exc})"))
        dataset.annotations[name] = content

    for upload in uploads:
        dataset.uploads.append(upload.name)
        try:
            parts = path_parts(upload.name)
            if len(parts) != 1:
                raise ValueError("직접 업로드에는 파일명만 사용할 수 있습니다.")
            extension = PurePosixPath(parts[-1]).suffix.casefold()
            if extension not in {".zip", ".json"}:
                raise ValueError("JSON 또는 ZIP 파일을 선택해 주세요.")
            if not 0 < upload.size <= MAX_UPLOAD - uploaded:
                raise ValueError("빈 파일 또는 전체 업로드 용량 제한을 초과했습니다.")
            uploaded += upload.size
            scanned += 1
            if scanned > MAX_ENTRIES:
                raise ValueError("파일 수 제한을 초과했습니다.")
            if extension == ".json":
                if upload.size > min(MAX_FILE, MAX_EXPANDED - expanded):
                    raise ValueError("개별 JSON 또는 전체 처리 용량 제한을 초과했습니다.")
                payload = upload.getvalue()
                expanded += len(payload)
                add(parts, payload)
                continue
            with ZipFile(BytesIO(upload.getvalue())) as archive:
                entries = archive.infolist()
                if scanned + len(entries) > MAX_ENTRIES:
                    raise ValueError("ZIP 파일 수 제한을 초과했습니다.")
                scanned += len(entries)
                for entry in entries:
                    entry_name = f"{upload.name} / {entry.orig_filename}"
                    try:
                        member = path_parts(entry.orig_filename)
                        kind = stat.S_IFMT(entry.external_attr >> 16)
                        if kind not in {0, stat.S_IFREG, stat.S_IFDIR} or entry.flag_bits & 1:
                            raise ValueError("링크, 특수 파일 및 암호화된 항목은 지원하지 않습니다.")
                        if entry.is_dir():
                            continue
                        if PurePosixPath(member[-1]).suffix.casefold() not in DATA_EXTENSIONS:
                            raise ValueError("지원하지 않는 확장자입니다.")
                        if entry.file_size > min(MAX_FILE, MAX_EXPANDED - expanded):
                            raise ValueError("개별 파일 또는 전체 압축 해제 용량 제한을 초과했습니다.")
                        # Charge attempted entries too, even if a duplicate or CRC error discards them.
                        expanded += entry.file_size
                        with archive.open(entry) as stream:
                            payload = stream.read(entry.file_size + 1)
                        if len(payload) != entry.file_size:
                            raise ValueError("ZIP 항목의 실제 크기와 기록된 크기가 다릅니다.")
                        add(member, payload)
                    except (BadZipFile, EOFError, OSError, RuntimeError, ValueError, zlib.error) as exc:
                        dataset.upload_issues.append(Issue(entry_name, str(exc)))
        except BadZipFile as exc:
            dataset.upload_issues.append(Issue(upload.name, f"손상되었거나 ZIP 형식이 아닙니다. ({exc})"))
        except (OSError, ValueError) as exc:
            dataset.upload_issues.append(Issue(upload.name, str(exc)))
    dataset.seconds = time.perf_counter() - started
    return dataset
