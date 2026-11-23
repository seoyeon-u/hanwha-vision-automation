# Hanwha Vision 데이터 처리 도구

Labelme 어노테이션의 객체 분포를 집계하고, 검수 대상을 추출하고, 이미지와 어노테이션을 바탕으로 영어 설명을 생성하는 Python 도구 모음입니다. 생성한 설명을 기존 Excel 파일에 병합할 수 있습니다.

| 도구 | 입력 | 결과 |
| --- | --- | --- |
| [데이터 전처리](#데이터-전처리) | Labelme JSON 또는 폴더 | 폴더별 객체 분포 및 복수 무기타입 검수 목록 |
| [이미지 설명 생성](#이미지-설명-생성) | 이미지와 Labelme JSON | 영어 설명을 담은 Excel, JSONL 체크포인트, 실행 로그 |
| [Excel 설명 병합](#excel-설명-병합) | 대상 Excel과 설명이 들어 있는 Excel | 설명을 반영한 Excel 사본 |
| [FP 검수 대상 추출](#fp-검수-대상-추출) | 이미지·JSON 파일 또는 폴더 | 객체가 표시된 이미지·JSON 쌍과 처리 내역 CSV |

## 설치

Python 3.10 이상을 사용합니다. Windows PowerShell에서 저장소 루트로 이동한 뒤 실행하세요.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

아래 실행 예시는 위 가상 환경을 기준으로 합니다. FP 검수 도구의 GUI를 실행하려면 Tcl/Tk가 포함된 Python이 필요합니다.

## 데이터 전처리

두 명령은 각각 독립적으로 실행할 수 있습니다. 실행 후 JSON 파일이나 폴더의 경로를 한 줄에 하나씩 입력하고, 빈 줄을 입력해 분석을 시작합니다.

```powershell
.\.venv\Scripts\python.exe -m data_preprocessing.folder_object_distribution
.\.venv\Scripts\python.exe -m data_preprocessing.multi_weapon_review
```

- 객체 분포 집계는 폴더별 이미지와 객체 수 등을 집계해 현재 작업 폴더에 `폴더별 객체 분포 집계.xlsx`를 저장합니다.
- 복수 무기타입 검수는 여러 무기 유형이 함께 표시된 어노테이션을 찾아 현재 작업 폴더에 `복수 무기타입 검수 목록.xlsx`를 저장합니다.

## 이미지 설명 생성

이미지와 Labelme JSON을 사용해 OpenAI API로 영어 설명을 생성합니다. JSON의 `imagePath`와 `shapes`를 사용하며, 이미지 데이터가 API로 전송됩니다.

1. `.env`가 없으면 `Copy-Item .env.example .env`를 실행하고 `.env`의 `OPENAI_API_KEY`에 API 키를 설정합니다.
2. [config.py](description_generation/config.py)에서 `INPUT_DIR`을 데이터셋 루트로 지정합니다. 현재 코드는 그 아래의 `image/`와 `labels/`를 사용합니다. 폴더명이 다르면 `IMAGE_DIR`과 `JSON_DIR`을 수정하세요.
3. 저장소 루트에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m description_generation.main
```

| 설정 | 현재 값 또는 동작 |
| --- | --- |
| `MODEL` | `gpt-4.1` |
| `EXCLUDED_JSON_FILES` | `1st_test.json` 제외 |
| `OUTPUT_FILE` | `output/3nd_22_descriptions.xlsx`의 `description` 시트에 `imagePath`, `description` 열 저장 |
| `CHECKPOINT_FILE` | 성공한 결과를 `output/3nd_22_checkpoint.jsonl`에 기록 |
| `LOG_DIR` | `logs/`에 실행 로그 저장 |
| `RESUME` | 현재 `False`로 새로 실행합니다. `True`로 설정하면 같은 작업의 성공 결과를 체크포인트에서 재사용합니다. |

동시 요청 수는 `MAX_CONCURRENT_REQUESTS`에서 조정할 수 있습니다. 분당 요청 및 토큰 한도를 설정하려면 `RATE_LIMIT_RPM`과 `RATE_LIMIT_TPM`을 사용하세요.

## Excel 설명 병합

```powershell
.\.venv\Scripts\python.exe -m description_merge.main
```

수정할 부모 `.xlsx`, 설명이 들어 있는 자식 `.xlsx`, 저장 경로 순으로 입력합니다. 두 파일의 대상 시트에는 `imagePath`와 `description` 헤더가 있어야 하며, 기존 헤더인 `DESCRIPTNION`도 지원합니다. 경로에서 파일명을 추출해 대소문자 구분 없이 비교하고, 일치하는 부모 행에 자식의 비어 있지 않은 설명을 반영합니다. 저장 경로를 비워 두면 부모 파일과 같은 폴더에 `<부모 파일명>_updated.xlsx`를 생성합니다.

## FP 검수 대상 추출

```powershell
.\.venv\Scripts\python.exe -m fp_labeling.main
```

GUI에서 입력 파일 또는 폴더와 결과 폴더를 지정합니다. 같은 폴더에 있고 확장자를 제외한 이름이 같은 이미지와 JSON을 짝지은 뒤, JSON의 `shapes` 배열에 항목이 있는 쌍을 결과 폴더에 복사합니다. 복사 결과, 누락, 이름 충돌 등의 처리 내역은 CSV로 저장됩니다.

## 테스트

저장소 루트에서 실행합니다. 테스트는 임시 파일과 모의 API 응답을 사용합니다.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
