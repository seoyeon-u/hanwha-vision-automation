from __future__ import annotations

import posixpath
import sys
from pathlib import Path
from typing import Any

try:
    from openpyxl import load_workbook
    from openpyxl.worksheet.worksheet import Worksheet
except ImportError as error:
    raise SystemExit(
        "필요한 패키지가 없습니다. 다음 명령으로 설치해 주세요: "
        "python -m pip install openpyxl"
    ) from error


IMAGEPATH_HEADERS = {"imagepath"}
DESCRIPTION_HEADERS = {"descriptnion", "description"}


def normalize_header(value: Any) -> str:
    return "".join(
        character
        for character in str(value or "").strip().casefold()
        if character not in " _-\t\r\n"
    )


def find_columns(worksheet: Worksheet) -> tuple[int, int, int] | None:
    """Return the header row and IMAGEPATH/DESCRIPTNION column indexes."""
    for header_row in range(1, min(worksheet.max_row, 20) + 1):
        headers = tuple(cell.value for cell in worksheet[header_row])
        path_columns = [
            index
            for index, value in enumerate(headers)
            if normalize_header(value) in IMAGEPATH_HEADERS
        ]
        description_columns = [
            index
            for index, value in enumerate(headers)
            if normalize_header(value) in DESCRIPTION_HEADERS
        ]
        if len(path_columns) > 1 or len(description_columns) > 1:
            raise ValueError(
                f"시트 '{worksheet.title}'의 {header_row}행에 "
                "IMAGEPATH 또는 DESCRIPTION 열이 중복되어 있습니다."
            )
        if path_columns and description_columns:
            return header_row, path_columns[0], description_columns[0]
    return None


def normalize_imagepath(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return posixpath.normpath(text.replace("\\", "/")).casefold()


def read_child_descriptions(child_path: Path) -> dict[str, Any]:
    workbook = load_workbook(child_path, read_only=True, data_only=True)
    descriptions: dict[str, Any] = {}
    matched_sheets = 0
    try:
        for worksheet in workbook.worksheets:
            columns = find_columns(worksheet)
            if columns is None:
                continue
            header_row, imagepath_column, description_column = columns
            matched_sheets += 1
            for row in worksheet.iter_rows(min_row=header_row + 1):
                imagepath = normalize_imagepath(row[imagepath_column].value)
                description = row[description_column].value
                if imagepath is not None and description is not None:
                    if not isinstance(description, str) or description.strip():
                        descriptions[imagepath] = description
    finally:
        workbook.close()

    if matched_sheets == 0:
        raise ValueError(
            f"자식 파일에 IMAGEPATH와 DESCRIPTNION 열을 찾을 수 없습니다: "
            f"{child_path}"
        )
    return descriptions


def update_parent(
    parent_path: Path,
    output_path: Path,
    descriptions: dict[str, Any],
) -> tuple[int, int]:
    workbook = load_workbook(parent_path)
    updated = 0
    matched_sheets = 0
    try:
        for worksheet in workbook.worksheets:
            columns = find_columns(worksheet)
            if columns is None:
                continue
            header_row, imagepath_column, description_column = columns
            matched_sheets += 1
            for row in worksheet.iter_rows(min_row=header_row + 1):
                imagepath = normalize_imagepath(row[imagepath_column].value)
                if imagepath is not None and imagepath in descriptions:
                    row[description_column].value = descriptions[imagepath]
                    updated += 1
        if matched_sheets == 0:
            raise ValueError(
                f"부모 파일에 IMAGEPATH와 DESCRIPTNION 열을 찾을 수 없습니다: "
                f"{parent_path}"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(output_path)
    finally:
        workbook.close()
    return updated, matched_sheets


def is_excel_path(path: Path) -> bool:
    return path.is_file() and path.suffix.casefold() == ".xlsx"


def ask_excel_path(prompt: str) -> Path:
    while True:
        path = Path(input(prompt).strip().strip('"')).expanduser()
        if is_excel_path(path):
            return path
        print("존재하는 .xlsx 파일 경로를 입력해 주세요.")


def ask_parent_and_children() -> tuple[Path, Path, Path]:
    parent_path = ask_excel_path("부모 파일 경로 (수정 대상): ")
    child1_path = ask_excel_path("자식 파일 1 경로 (설명값): ")
    child2_path = ask_excel_path("자식 파일 2 경로 (설명값): ")
    return parent_path, child1_path, child2_path


def main() -> int:
    print(
        "부모 파일 1개와 자식 파일 2개의 경로를 차례로 입력하세요. "
        "자식 파일 2개의 IMAGEPATH가 겹치면 두 번째 파일의 설명값을 사용합니다."
    )
    parent_path, child1_path, child2_path = ask_parent_and_children()

    default_output = parent_path.with_name(f"{parent_path.stem}_updated.xlsx")
    output_input = input(
        f"새 엑셀 파일 경로 (Enter: {default_output}): "
    ).strip().strip('"')
    output_path = Path(output_input).expanduser() if output_input else default_output
    if output_path.suffix.casefold() != ".xlsx":
        output_path = output_path.with_suffix(".xlsx")

    input_paths = {
        parent_path.resolve(),
        child1_path.resolve(),
        child2_path.resolve(),
    }
    if output_path.resolve() in input_paths:
        print("오류: 새 파일 경로는 부모/자식 입력 파일과 달라야 합니다.")
        return 1
    if output_path.exists() and input(
        "출력 파일이 이미 있습니다. 덮어쓸까요? (y/N): "
    ).strip().casefold() != "y":
        print("취소했습니다.")
        return 1

    try:
        descriptions = read_child_descriptions(child1_path)
        descriptions.update(read_child_descriptions(child2_path))
        updated, matched_sheets = update_parent(
            parent_path, output_path, descriptions
        )
    except (OSError, ValueError, KeyError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1

    print(f"완료: IMAGEPATH가 일치하는 {updated}개 행을 수정했습니다.")
    print(f"처리한 부모 시트: {matched_sheets}개")
    print(f"저장 파일: {output_path}")
    print("참고: 자식 파일의 빈 설명값은 부모 파일의 기존 값을 유지합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
