# Labelme 검수 대상 추출

Labelme JSON의 `shapes` 배열에 항목이 있는 경우, 해당 이미지와 JSON을 지정한 폴더에 함께 복사합니다.

## Windows에서 실행하기

1. Python 3.10 이상을 설치합니다. Windows용 Python 설치 프로그램에서 `tcl/tk and IDLE` 옵션을 포함하세요. 이 프로그램은 Python 표준 라이브러리만 사용합니다.
2. 파일 탐색기에서 이 README가 있는 `labelme_review_filter` 폴더를 엽니다. 주소 표시줄에 `powershell`을 입력하고 Enter를 누릅니다.
3. 다음 명령을 실행합니다. 환경에서 `python` 명령을 사용한다면 `py`를 `python`으로 바꿔 실행하세요.

   ```powershell
   py main.py
   ```

4. 탐색기에서 이미지와 JSON을 함께 선택하고 **경로 복사**를 누른 뒤 프로그램 입력창에 붙여넣습니다. **입력 폴더 선택**으로 폴더를 추가하거나, 폴더 경로를 직접 붙여넣어도 됩니다. 입력 순서는 자유롭고, 경로에 큰따옴표, 한글, 공백이 있어도 됩니다.
5. **출력 폴더 선택**을 누르거나 출력 경로를 직접 입력합니다. 직접 입력한 폴더가 없으면 프로그램이 생성합니다.
6. **객체 있는 파일만 추출**을 누릅니다. 완료 후 화면의 처리 결과와 출력 폴더의 `처리내역_*.csv`를 확인하세요.

## 매칭 및 기록 기준

- 지원 이미지 형식은 JPG, JPEG, PNG, BMP, TIF, TIFF입니다. 폴더를 입력하면 해당 폴더 바로 아래 파일을 검색합니다. 하위 폴더는 각각 입력할 수 있습니다.
- 같은 폴더에서 확장자를 제외한 이름이 같은 이미지와 JSON을 연결합니다. 이름을 비교할 때 대소문자를 구분하지 않으며, 반복 입력한 경로는 한 번만 처리합니다.
- 같은 폴더에 같은 이름의 이미지가 여러 형식으로 있으면 해당 묶음을 충돌로 기록합니다. 출력 이름이 이미 있으면 해당 쌍 전체를 건너뜁니다. 서로 다른 입력 폴더에 동명 쌍이 있으면 먼저 성공한 복사본을 출력 폴더에 보존합니다.
- 전체 쌍에는 이미지와 JSON이 각각 하나씩 매칭된 경우를 포함합니다. 누락된 파일은 매칭 후보별로 빠진 상대 파일을 셉니다. `shapes` 키 누락은 별도 경고로 표시합니다.
- 원본 파일은 읽기와 복사에만 사용합니다. 빈 `shapes` 배열은 CSV에 `excluded`로, 복사는 `copied`로, 누락·충돌·실패는 `error`로 기록합니다.
- CSV는 실행마다 새로 생성하며 Excel에서 한글을 읽을 수 있도록 UTF-8 BOM으로 저장합니다. `output_path`는 복사된 두 파일이 들어 있는 폴더입니다.

## EXE 만들기

Windows에서 이 폴더의 PowerShell을 열고 실행합니다. PyInstaller는 EXE를 만들 때만 설치합니다.

```powershell
py -m pip install pyinstaller
py -m PyInstaller --onefile --windowed --name LabelmeReviewFilter main.py
```

빌드가 끝나면 `dist\LabelmeReviewFilter.exe`를 실행합니다.
