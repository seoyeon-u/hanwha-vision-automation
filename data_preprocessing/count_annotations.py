"""EO와 IR 폴더의 COCO 어노테이션을 집계해 Excel로 저장"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook
from openpyxl.styles import Border, Font, Side


OUTPUT_FILENAME = "오탐레이블링_집계.xlsx"
HEADERS = ("구분", "폴더", "이미지 수", "총 객체 수")


def count_annotations(path: Path) -> tuple[int, int]:
    # JSON 배열의 길이를 사용하므로 같은 이미지의 객체도 각각 집계한다.
    with path.open("rb") as source:
        data = json.load(source)

    if not isinstance(data, dict):
        raise ValueError("JSON 최상위 항목은 객체여야 합니다.")

    for key in ("images", "annotations"):
        if key not in data:
            raise ValueError(f"필수 항목 '{key}'이(가) 없습니다.")
        if not isinstance(data[key], list):
            raise ValueError(f"'{key}' 항목은 배열이어야 합니다.")

    return len(data["images"]), len(data["annotations"])


def save_report(output_path: Path, rows: list[tuple[str, str, int, int]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "오탐레이블링 집계"
    sheet.append(HEADERS)

    for row_number, row in enumerate(rows, start=2):
        sheet.append(row)
        # 폴더명이 '='로 시작해도 Excel에서 폴더명 그대로 표시한다.
        sheet.cell(row=row_number, column=2).data_type = "s"

    last_data_row = len(rows) + 1
    # 유효한 데이터가 하나도 없을 때도 SUM 수식으로 합계 0을 표시한다.
    image_sum = f"=SUM(C2:C{last_data_row})" if rows else "=SUM(0)"
    object_sum = f"=SUM(D2:D{last_data_row})" if rows else "=SUM(0)"
    sheet.append(("합계", None, image_sum, object_sum))

    line = Side(style="thin", color="BFBFBF")
    border = Border(left=line, right=line, top=line, bottom=line)
    bold = Font(bold=True)
    total_row = last_data_row + 1
    for row in sheet.iter_rows():
        for cell in row:
            cell.border = border
            if cell.row in (1, total_row):
                cell.font = bold
            if cell.row > 1 and cell.column in (3, 4):
                cell.number_format = "#,##0"

    max_folder_length = max((len(row[1]) for row in rows), default=0)
    sheet.column_dimensions["A"].width = 10
    sheet.column_dimensions["B"].width = min(255, max(24, 2 * max_folder_length + 2))
    sheet.column_dimensions["C"].width = 16
    sheet.column_dimensions["D"].width = 16

    # 새 보고서를 완전히 저장한 뒤 최종 파일로 옮긴다.
    with TemporaryDirectory(dir=output_path.parent) as temp_dir:
        temp_path = Path(temp_dir) / output_path.name
        workbook.save(temp_path)
        temp_path.replace(output_path)


def main() -> int:
    try:
        raw_path = input("최상위 _오탐레이블링 폴더 경로를 입력하세요: ")
        raw_path = raw_path.strip().removeprefix('"').removesuffix('"')
        if not raw_path.strip():
            print("[오류] 폴더 경로를 입력해 주세요.")
            return 1
        root = Path(raw_path).resolve()
        if not root.is_dir():
            print(f"[오류] 입력 경로가 존재하지 않거나 폴더가 아닙니다: {root}")
            return 1
    except (EOFError, OSError, ValueError, RuntimeError) as error:
        print(f"[오류] 입력 경로를 확인할 수 없습니다: {error}")
        return 1

    rows: list[tuple[str, str, int, int]] = []
    failed_files = 0
    skipped_folders = 0

    # 구분은 EO, IR 순서로 처리하고 하위 폴더는 이름순으로 정렬한다.
    for group in ("EO", "IR"):
        group_dir = root / group
        try:
            if not group_dir.is_dir():
                print(f"[경고] {group} 폴더가 없습니다: {group_dir}")
                continue
            folders = sorted(group_dir.glob("**/"), key=lambda path: (path.name, path))
        except OSError as error:
            print(f"[경고] 폴더를 탐색할 수 없습니다: {group_dir} ({error})")
            continue

        for folder in folders:
            if folder == group_dir:
                continue
            json_path = folder / "annotations.json"
            print(f"[처리 중] {folder.relative_to(root)}")
            try:
                images, objects = count_annotations(json_path)
            except FileNotFoundError:
                print(f"[경고] annotations.json이 없어 건너뜁니다: {json_path}")
                skipped_folders += 1
                continue
            except (OSError, ValueError, RecursionError) as error:
                print(f"[오류] {json_path} ({error})")
                failed_files += 1
                continue

            rows.append((group, folder.name, images, objects))
            print(f"  이미지 {images:,}개, 객체 {objects:,}개")

    print(f"\n처리 성공 파일 {len(rows):,}개, 실패 파일 {failed_files:,}개")
    print(f"annotations.json이 없어 건너뛴 폴더 {skipped_folders:,}개")
    print(f"전체 이미지 수 {sum(row[2] for row in rows):,}개")
    print(f"전체 객체 수 {sum(row[3] for row in rows):,}개")

    output_path = root / OUTPUT_FILENAME
    try:
        save_report(output_path, rows)
    except OSError as error:
        print(f"[오류] Excel 파일을 저장할 수 없습니다: {output_path} ({error})")
        return 1

    print(f"생성된 Excel 파일의 절대 경로: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
