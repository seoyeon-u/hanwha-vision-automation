"""Draw Labelme geometry on a bounded image preview."""
from __future__ import annotations

import math
from io import BytesIO

from PIL import Image, ImageDraw, ImageOps

SHAPES = {"rectangle": 2, "polygon": 3, "circle": 2, "point": 1, "line": 2, "linestrip": 2}


def shape_points(shape: dict) -> list[list[float]]:
    points = shape.get("points")
    if not isinstance(points, list) or any(
        not isinstance(point, list) or len(point) != 2
        or any(type(value) not in {int, float} or not abs(value) < 10**8 for value in point)
        for point in points
    ):
        return []
    return points


def draw_annotation(content: bytes, annotation: dict, selected: int) -> tuple[Image.Image, list[int]]:
    with Image.open(BytesIO(content)) as source:
        if source.width * source.height > 40_000_000:
            raise ValueError("미리보기 이미지가 4,000만 픽셀을 초과합니다.")
        dimensions = (annotation.get("imageWidth"), annotation.get("imageHeight"))
        has_dimensions = all(type(value) is int and 0
         < value <= 1_000_000 for value in dimensions)
        oriented = ImageOps.exif_transpose(source)
        if has_dimensions and dimensions == source.size and source.size != oriented.size:
            oriented = source
        width, height = dimensions if has_dimensions else oriented.size
        image = oriented.convert("RGB")
    image.thumbnail((1440, 1440))
    draw = ImageDraw.Draw(image, "RGBA")
    skipped = []
    for index, shape in enumerate(annotation["shapes"], 1):
        if not isinstance(shape, dict):
            skipped.append(index)
            continue
        kind = shape.get("shape_type") or "polygon"
        points = shape_points(shape)
        if not isinstance(kind, str) or kind not in SHAPES or len(points) < SHAPES[kind]:
            skipped.append(index)
            continue
        sx, sy = image.width / width, image.height / height
        converted = [(max(-4 * image.width, min(5 * image.width, x * sx)),
                      max(-4 * image.height, min(5 * image.height, y * sy))) for x, y in points]
        x1, y1 = converted[0]
        color = (246, 163, 28, 255) if index == selected else (33, 102, 225, 255)
        thickness = 4 if index == selected else 2
        if kind == "rectangle":
            x2, y2 = converted[1]
            draw.rectangle((min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)),
                           outline=color, width=thickness, fill=(*color[:3], 36))
        elif kind == "circle":
            radius = math.dist(points[0], points[1])
            rx, ry = min(radius * sx, 5 * image.width), min(radius * sy, 5 * image.height)
            draw.ellipse((x1 - rx, y1 - ry, x1 + rx, y1 + ry), outline=color, width=thickness)
        elif kind == "polygon":
            draw.polygon(converted, fill=(*color[:3], 36), outline=color, width=thickness)
        elif kind == "point":
            draw.ellipse((x1 - 4, y1 - 4, x1 + 4, y1 + 4), fill=color)
        else:
            draw.line(converted[:2] if kind == "line" else converted, fill=color, width=thickness)
        if 0 <= x1 < image.width and 0 <= y1 < image.height:
            label = str(index)
            box = draw.textbbox((x1 + 3, y1 + 2), label)
            draw.rectangle((box[0] - 2, box[1] - 1, box[2] + 2, box[3] + 1), fill=(18, 34, 64, 235))
            draw.text((x1 + 3, y1 + 2), label, fill=(255, 255, 255, 255))
    return image, skipped
