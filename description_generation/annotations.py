"""Discover, parse, and match Labelme inputs for Description generation."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import time
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from . import config as cfg

LOGGER = logging.getLogger("descriptions")
STRUCTURAL_KEYS = {"label", "points", "group_id", "shape_type", "mask"}
VEHICLES = {"light tactical vehicle", "tank", "self-propelled artillery", "armored vehicle", "civilian vehicle"}


def map_values(value, mapping: dict):
    if isinstance(value, list):
        return [map_values(item, mapping) for item in value]
    return mapping.get(value, value) if isinstance(value, str) else value


def translate_weapon(value):
    if isinstance(value, list):
        return [translate_weapon(item) for item in value]
    if isinstance(value, str):
        name, separator, suffix = value.rpartition("_")
        if separator and suffix.isdigit():
            return cfg.WEAPON_NAMES.get(name, name) + separator + suffix
        return cfg.WEAPON_NAMES.get(value, value)
    return value


def parse_annotation(path: Path) -> tuple[str, dict]:
    with path.open(encoding="utf-8-sig") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("JSON root must be an object")
    image_path = raw.get("imagePath")
    if not isinstance(image_path, str) or not image_path.strip():
        raise ValueError("imagePath must be a nonempty string")
    shapes = raw.get("shapes")
    if not isinstance(shapes, list):
        raise ValueError("Expected LabelMe shapes array")
    objects = []
    for number, shape in enumerate(shapes, 1):
        if not isinstance(shape, dict) or not isinstance(shape.get("label"), str) or not shape["label"].strip():
            raise ValueError(f"shapes[{number - 1}] must have a nonempty label")
        points = shape.get("points")
        if not isinstance(points, list) or not points:
            raise ValueError(f"shapes[{number - 1}] is missing points/bbox")
        for point in points:
            if not isinstance(point, list) or len(point) != 2 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) for v in point
            ):
                raise ValueError(f"shapes[{number - 1}] has malformed points")
        cls = cfg.CLASS_NAMES.get(shape["label"], shape["label"])
        attrs = {k: v for k, v in shape.items() if k not in STRUCTURAL_KEYS}
        # Keep original attributes (including flags/custom fields) as well as English conveniences.
        item = {"object_id": number, "class": cls, "original_class": shape["label"],
                "bbox": [min(p[0] for p in points), min(p[1] for p in points),
                         max(p[0] for p in points), max(p[1] for p in points)],
                "attributes": attrs}
        if "시선방향" in shape:
            item["body_direction" if cls in VEHICLES else "gaze_direction"] = map_values(shape["시선방향"], cfg.DIRECTIONS)
        for source, target in [("본체방향", "body_direction"), ("무기방향", "weapon_directions")]:
            if source in shape:
                item[target] = map_values(shape[source], cfg.DIRECTIONS)
        if "무장여부" in shape:
            item["armed"] = shape["무장여부"]
        if "무기타입" in shape:
            item["weapon_types"] = translate_weapon(shape["무기타입"])
        types, directions = item.get("weapon_types"), item.get("weapon_directions")
        if isinstance(types, list) and isinstance(directions, list) and len(types) != len(directions):
            raise ValueError(f"shapes[{number - 1}] weapon type/direction lengths differ")
        objects.append(item)
    # Exclude embedded image bytes; the actual image is sent separately. Preserve all other metadata.
    metadata = {k: v for k, v in raw.items() if k not in {"shapes", "imageData"}}
    return image_path, {"metadata": metadata, "class_counts": dict(Counter(o["class"] for o in objects)), "objects": objects}


class ImageMatcher:
    def __init__(self, root: Path, json_root: Path | None = None):
        self.root = root.resolve()
        self.json_root = (cfg.JSON_DIR if json_root is None else json_root).resolve()
        self.by_relative_stem = defaultdict(list)
        scanned = images = 0
        last_report = time.monotonic()
        for path in self.root.rglob("*"):
            scanned += 1
            if path.is_file() and path.suffix.lower() in cfg.IMAGE_EXTENSIONS:
                path.resolve().relative_to(self.root)
                relative = path.relative_to(self.root).with_suffix("").as_posix()
                self.by_relative_stem[relative.casefold()].append(path)
                images += 1
            if time.monotonic() - last_report >= 5:
                LOGGER.info("이미지 목록 생성 중: %d개 항목 확인, 이미지 %d개", scanned, images)
                last_report = time.monotonic()
        LOGGER.info("이미지 목록 생성 완료: 이미지 %d개 (파일 내용은 작업별로 읽습니다)", images)

    def resolve(self, json_path: Path) -> Path:
        relative = json_path.resolve().relative_to(self.json_root)
        key = relative.with_suffix("").as_posix().casefold()
        matches = self.by_relative_stem.get(key, [])
        if not matches and relative.parent != Path("."):
            matches = self.by_relative_stem.get(relative.stem.casefold(), [])
            flat_candidate = self.root / relative.stem
            fallback = f" or {flat_candidate}"
        else:
            fallback = ""
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"Ambiguous image for annotation {relative}: "
                             + ", ".join(str(p.relative_to(self.root)) for p in matches))
        raise FileNotFoundError(f"Image not found for annotation {relative}: "
                                f"expected {self.root / relative.with_suffix('')}{fallback} "
                                "with a supported image extension")


def image_data_url(path: Path) -> str:
    # Pillow verifies the input and converts unsupported BMP/TIFF to API-compatible PNG.
    with Image.open(path) as image:
        image.load()
        if getattr(image, "n_frames", 1) > 1:
            raise ValueError("Animated images are not supported; provide a still image")
        mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}.get(image.format)
        if mime:
            content = path.read_bytes()
        else:
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
            content, mime = buffer.getvalue(), "image/png"
    return f"data:{mime};base64," + base64.b64encode(content).decode("ascii")


def scoped_resume_keys(files, matcher):
    """Bind results to both sources. Workers call this for one job in a thread."""
    keys = {}
    for path in files:
        try:
            matched = matcher.resolve(path)
            identity = [str(matcher.root), str(matcher.json_root),
                        path.resolve().relative_to(matcher.json_root).as_posix(),
                        matched.relative_to(matcher.root).as_posix(),
                        hashlib.sha256(path.read_bytes()).hexdigest()]
            image_hash = hashlib.sha256()
            with matched.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    image_hash.update(chunk)
            identity.append(image_hash.hexdigest())
            keys[path] = "job:v2:" + hashlib.sha256(
                json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()
        except (OSError, ValueError):
            continue  # The worker retains the existing failure policy.
    return keys


def discover_annotations():
    excluded_names = {name.casefold() for name in cfg.EXCLUDED_JSON_FILES}
    files = []
    scanned = 0
    last_report = time.monotonic()
    for path in cfg.JSON_DIR.rglob("*"):
        scanned += 1
        if path.is_file() and path.suffix.lower() == ".json" and path.name.casefold() not in excluded_names:
            files.append(path)
        if time.monotonic() - last_report >= 5:
            LOGGER.info("JSON 탐색 중: %d개 항목 확인, 대상 JSON %d개", scanned, len(files))
            last_report = time.monotonic()
    LOGGER.info("JSON 탐색 완료: 대상 JSON %d개", len(files))
    return sorted(files)
