# Hanwha Vision 데이터 처리 자동화 도구

**Labelme 기반 이미지 데이터 전처리 및 검수 자동화 프로젝트**

이미지 데이터셋의 객체 분포 분석부터 검수 대상 추출, **OpenAI API 기반 영어 설명 생성**, Excel 데이터 병합까지 지원하는 **Python 기반 데이터 처리 자동화 도구 모음**입니다.

반복적인 데이터 정리 및 검수 작업을 자동화하여 **데이터 처리 효율성과 작업 편의성**을 높이는 것을 목표로 합니다.

<br>

## 📌 주요 기능

### 1. 데이터 전처리 및 객체 분포 분석
- Labelme JSON 어노테이션을 기반으로 **이미지 및 객체 분포 자동 집계**
- 폴더별 이미지 수와 객체 수 분석
- 여러 무기 유형이 함께 어노테이션된 **복수 무기타입 검수 대상 추출**
- 분석 결과를 Excel 파일로 자동 저장

**결과 파일**
- `폴더별 객체 분포 집계.xlsx`
- `복수 무기타입 검수 목록.xlsx`

### 2. OpenAI API 기반 이미지 설명 생성
- 이미지와 Labelme JSON 어노테이션을 활용한 **영어 이미지 설명 자동 생성**
- JSON의 `imagePath`, `shapes` 정보를 기반으로 이미지 및 객체 정보 처리
- **GPT-4.1 모델**을 활용한 이미지 설명 생성
- 비동기 API 요청을 통한 다중 이미지 처리
- JSONL 체크포인트를 통한 처리 결과 기록 및 재실행 지원
- 실행 로그 저장 및 API 요청 속도 제한 설정 지원

**결과 파일**
- `output/3nd_22_descriptions.xlsx`
- `output/3nd_22_checkpoint.jsonl`
- `logs/` 실행 로그

### 3. Excel 이미지 설명 병합
- 기존 Excel 데이터에 새로 생성한 **이미지 설명 자동 병합**
- `imagePath`의 파일명을 기준으로 데이터 매칭
- 대소문자 구분 없이 동일 이미지 검색
- 기존 데이터 구조를 유지하면서 설명 정보 업데이트
- 원본 파일을 보존하고 새로운 Excel 파일로 저장

### 4. FP 검수 대상 자동 추출
- 이미지 및 Labelme JSON 파일의 **자동 매칭**
- 객체가 어노테이션된 이미지·JSON 쌍 추출
- GUI 기반 입력 및 출력 경로 설정
- 검수 대상 파일을 지정한 폴더에 자동 복사
- 파일 누락, 이름 충돌, 복사 결과 등을 CSV로 기록

<br>

## ⚙️ 기술 개요

| 구성 요소 | 설명 |
|-----------|------|
| 개발 언어 | Python 3.10 이상 |
| 데이터 어노테이션 | Labelme JSON |
| AI 모델 | OpenAI GPT-4.1 |
| AI 연동 | OpenAI API |
| 데이터 처리 | 이미지 및 JSON 기반 객체 정보 분석 |
| 데이터 관리 | Excel (.xlsx), JSONL, CSV |
| 비동기 처리 | 동시 API 요청 및 요청량 제한 관리 |
| 체크포인트 | JSONL 기반 처리 결과 저장 및 재사용 |
| GUI | Python Tkinter |
| 테스트 | unittest |

<br>

## 🛠️ 실행 환경 및 초기 세팅

### 1. 프로젝트 클론

```bash
git clone https://github.com/seoyeon-u/hanwha-vision-automation.git
cd hanwha-vision-automation
```

### 2. 가상환경 생성 및 패키지 설치

Python 3.10 이상 환경에서 실행하며, Windows PowerShell을 기준으로 합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. 환경변수 설정 (`.env`)

OpenAI API를 사용하는 이미지 설명 생성 기능을 실행하려면 환경변수 설정이 필요합니다.

```powershell
Copy-Item .env.example .env
```

`.env` 파일에 다음 항목을 설정합니다.

```env
OPENAI_API_KEY=your-openai-api-key
```

API 키는 이미지 설명 생성에 사용되며, `.env` 파일은 GitHub에 업로드하지 않도록 주의해야 합니다.

<br>

## 🚀 기능별 실행 방법

### 1. 데이터 전처리

**폴더별 객체 분포 집계**

```powershell
.\.venv\Scripts\python.exe -m data_preprocessing.folder_object_distribution
```

**복수 무기타입 검수 대상 추출**

```powershell
.\.venv\Scripts\python.exe -m data_preprocessing.multi_weapon_review
```

실행 후 분석할 JSON 파일 또는 폴더 경로를 한 줄씩 입력합니다.

입력을 마친 뒤 빈 줄을 입력하면 분석을 시작하며, 결과는 현재 작업 폴더에 Excel 파일로 저장됩니다.

### 2. 이미지 설명 생성

먼저 `description_generation/config.py`에서 데이터셋 경로를 설정합니다.

```python
INPUT_DIR = "your-dataset-path"
```

기본적으로 데이터셋의 `image/`, `labels/` 폴더를 사용하며, 폴더 구조가 다를 경우 `IMAGE_DIR`, `JSON_DIR`을 수정합니다.

**실행 명령어**

```powershell
.\.venv\Scripts\python.exe -m description_generation.main
```

**주요 설정**

| 설정 | 설명 |
|------|------|
| `MODEL` | GPT-4.1 모델 사용 |
| `INPUT_DIR` | 데이터셋 루트 경로 |
| `IMAGE_DIR` | 이미지 폴더 경로 |
| `JSON_DIR` | Labelme JSON 폴더 경로 |
| `OUTPUT_FILE` | 생성된 설명을 저장할 Excel 파일 |
| `CHECKPOINT_FILE` | 성공한 처리 결과를 기록할 JSONL 파일 |
| `LOG_DIR` | 실행 로그 저장 경로 |
| `RESUME` | 기존 체크포인트 재사용 여부 |
| `MAX_CONCURRENT_REQUESTS` | 동시 API 요청 수 |
| `RATE_LIMIT_RPM` | 분당 API 요청 제한 |
| `RATE_LIMIT_TPM` | 분당 토큰 사용량 제한 |

`RESUME=True`로 설정하면 동일 작업에서 성공한 결과를 체크포인트에서 재사용할 수 있습니다.

이미지 설명 생성 과정에서는 이미지 데이터가 OpenAI API로 전송되므로 데이터 보안 정책 및 API 사용 비용을 확인해야 합니다.

### 3. Excel 이미지 설명 병합

```powershell
.\.venv\Scripts\python.exe -m description_merge.main
```

실행 후 다음 순서로 경로를 입력합니다.

1. 설명을 병합할 기존 Excel 파일
2. 새로 생성된 설명이 포함된 Excel 파일
3. 병합 결과를 저장할 경로

두 Excel 파일은 `imagePath`, `description` 헤더를 기준으로 처리하며, 기존 헤더인 `DESCRIPTNION`도 지원합니다.

저장 경로를 입력하지 않으면 기존 Excel 파일과 동일한 폴더에 `<부모 파일명>_updated.xlsx`가 생성됩니다.

### 4. FP 검수 대상 추출

```powershell
.\.venv\Scripts\python.exe -m fp_labeling.main
```

GUI에서 입력 파일 또는 폴더와 결과 저장 폴더를 지정합니다.

- 확장자를 제외한 파일명이 동일한 이미지와 JSON 자동 매칭
- JSON의 `shapes` 배열에 객체 정보가 있는 파일 추출
- 검수 대상 이미지 및 JSON 파일 복사
- 파일 처리 결과와 예외 내역을 CSV로 저장

GUI 실행을 위해서는 Tcl/Tk가 포함된 Python 환경이 필요합니다.

**실행 화면**

<p align="center">
  <img src="https://github.com/user-attachments/assets/b898a330-77c9-4178-84da-1d58dc80fd1a" width="650" alt="FP 검수 대상 추출 GUI">
</p>

<p align="center">
  <sub>입력 경로 설정, 객체 검수 대상 추출 및 처리 결과 로그를 제공하는 GUI 화면</sub>
</p>

<br>

## ✅ 테스트 실행

테스트는 임시 파일 및 모의 API 응답을 사용하며, 저장소 루트에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

<br>

## 📁 프로젝트 구성

```text
hanwha-vision-automation/
├── data_preprocessing/       # 객체 분포 분석 및 복수 무기타입 검수
├── description_generation/   # OpenAI API 기반 이미지 설명 생성
│   ├── config.py             # 데이터셋 및 API 실행 설정
│   └── main.py               # 이미지 설명 생성 실행
├── description_merge/        # Excel 이미지 설명 병합
│   └── main.py
├── fp_labeling/              # GUI 기반 FP 검수 대상 추출
│   └── main.py
├── tests/                    # 기능별 단위 테스트
├── docs/
│   └── images/
│       └── fp_labeling_gui.png # FP 검수 GUI 실행 화면
├── output/                   # 이미지 설명 및 체크포인트 출력
├── logs/                     # 실행 로그
├── .env.example              # 환경변수 설정 예시
├── requirements.txt          # Python 패키지 목록
└── README.md
```

<br>
