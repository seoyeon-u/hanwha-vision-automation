"""Persist generated Descriptions and resumable job checkpoints."""
import json
import logging
import os
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from . import config as cfg

LOGGER = logging.getLogger("descriptions")


def load_results() -> dict[str, str]:
    results = {}
    if not cfg.RESUME:
        return results
    # Excel has no source identity. Resume only content-scoped v2 checkpoints.
    if cfg.CHECKPOINT_FILE.exists():
        with cfg.CHECKPOINT_FILE.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    if not isinstance(item.get("imagePath"), str) or not isinstance(item.get("description"), str) or not item["description"].strip():
                        raise ValueError("Invalid checkpoint entry")
                    key = item.get("jobKey")
                    if isinstance(key, str) and re.fullmatch(r"job:v2:[0-9a-f]{64}", key):
                        results[key] = item["description"]
                    else:
                        LOGGER.warning("Ignoring legacy checkpoint line %d without a verified job key", number)
                except (ValueError, TypeError, AttributeError):
                    LOGGER.warning("Ignoring damaged checkpoint line %d", number)
    return results


def append_checkpoint(image_path: str, description: str, job_key: str | None = None) -> None:
    with cfg.CHECKPOINT_FILE.open("a", encoding="utf-8") as handle:
        # Leading newline separates a possibly interrupted final line from the new entry.
        item = {"imagePath": image_path, "description": description}
        if job_key is not None:
            item["jobKey"] = job_key
        handle.write("\n" + json.dumps(item, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def save_excel(rows: list[tuple[str, str]]) -> bool:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = cfg.SHEET_NAME
    sheet.append(["imagePath", "description"])
    for row_number, (image_path, description) in enumerate(rows, 2):
        sheet.append([image_path, description])
        # Store paths exactly as text, including paths starting with '='.
        for cell in (sheet.cell(row_number, 1), sheet.cell(row_number, 2)):
            cell.data_type = "s"
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.column_dimensions["A"].width = 45
    sheet.column_dimensions["B"].width = 110
    temp = cfg.OUTPUT_FILE.with_name(cfg.OUTPUT_FILE.stem + ".tmp.xlsx")
    try:
        workbook.save(temp)
        os.replace(temp, cfg.OUTPUT_FILE)
        return True
    except OSError as exc:
        LOGGER.error("Excel save failed (%s). Close Excel and rerun; successful results remain in checkpoint.", type(exc).__name__)
        return False
    finally:
        workbook.close()
