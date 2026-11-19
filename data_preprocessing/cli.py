"""Interactive path input and overwrite confirmation for dataset reports."""
from pathlib import Path


def read_paths(instructions: str) -> list[str]:
    print("JSON 파일 또는 폴더 경로를 붙여넣으세요:")
    print(instructions)
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


def confirm_overwrite(output_path: Path) -> bool:
    while True:
        answer = input(f"'{output_path.name}' 파일이 이미 있습니다. 덮어쓰시겠습니까? (y/n): ").strip().casefold()
        if answer in {"y", "yes", "예"}:
            return True
        if answer in {"n", "no", "아니오"}:
            return False
        print("y 또는 n으로 입력해 주세요.")
