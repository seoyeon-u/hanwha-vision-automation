# Hanwha Vision 데이터 처리 자동화 도구

**이미지 데이터 전처리, 시각화 및 데이터 품질 검수 자동화 프로젝트**

이미지 데이터셋의 객체 분포 분석부터 검수 대상 추출, **OpenAI API 기반 영어 설명 생성**, Excel 데이터 병합, **Streamlit 기반 데이터 시각화 및 최종 데이터 검수**까지 지원하는 **Python 기반 데이터 처리 자동화 도구 모음**입니다.

데이터 전처리부터 최종 결과물 검수까지 각 작업 단계에 필요한 기능을 제공하며, 반복적인 데이터 정리 및 검수 작업을 자동화하여 **데이터 처리 효율성, 작업 편의성 및 데이터 품질 관리 효율성**을 높이는 것을 목표로 합니다.

<br>

## 📌 주요 기능

### 1. 데이터 전처리 및 객체 분포 분석

- Labelme JSON 어노테이션을 기반으로 **이미지 및 객체 분포 자동 집계**
- 폴더별 이미지 수와 객체 수 분석
- 여러 무기 유형이 함께 어노테이션된 **복수 무기타입 검수 대상 추출**
- 분석 결과를 Excel 파일로 자동 저장

### 2. OpenAI API 기반 이미지 설명 생성

- 이미지와 Labelme JSON 어노테이션을 활용한 **영어 이미지 설명 자동 생성**
- JSON의 `imagePath`, `shapes` 정보를 기반으로 이미지 및 객체 정보 처리
- **GPT-4.1 모델**을 활용한 이미지 설명 생성
- 비동기 API 요청을 통한 다중 이미지 처리
- JSONL 체크포인트를 통한 처리 결과 기록 및 재실행 지원
- 실행 로그 저장 및 API 요청 속도 제한 설정 지원

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

### 5. Streamlit 기반 데이터 전처리 시각화

- 기존 Python 데이터 전처리 로직을 활용한 **웹 기반 분석 대시보드**
- Labelme JSON 및 ZIP 데이터셋 업로드
- 전체 이미지 수, 객체 수, 검수 후보 수 및 분석 소요 시간 제공
- Plotly 기반 클래스별 객체 분포 및 비율 시각화
- 폴더별 데이터 통계 및 이상 현황 분석
- 복수 무기타입 검수 대상 필터링 및 상세 정보 확인
- 원본 이미지 기반 Labelme 어노테이션 시각화
- Excel 분석 결과 다운로드

<br>

## ⚙️ 기술 개요

| 구성 요소 | 설명 |
|-----------|------|
| 개발 언어 | Python 3.10 이상 |
| 데이터 어노테이션 | Labelme JSON, COCO JSON |
| AI 모델 | OpenAI GPT-4.1 |
| AI 연동 | OpenAI API |
| 데이터 처리 | Pandas, 이미지 및 JSON 기반 객체 정보 분석 |
| 데이터 관리 | OpenPyXL, Excel (.xlsx), JSONL, CSV |
| 비동기 처리 | 동시 API 요청 및 요청량 제한 관리 |
| 체크포인트 | JSONL 기반 처리 결과 저장 및 재사용 |
| 웹 대시보드 | Streamlit |
| 데이터 시각화 | Plotly |
| 이미지 처리 | Pillow |
| 상태 관리 | Streamlit Session State |
| GUI | Python Tkinter |
| 데이터 검수 | 파일 누락 확인, JSON 구조 검증 및 객체 수량 집계 |
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

기존 Description 테스트를 포함한 전체 테스트 실행에는 Python 3.11 이상이 필요합니다.

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

이미지 설명 생성 이외의 데이터 전처리, 시각화, Excel 병합 및 데이터 검수 기능은 OpenAI API 키 없이 실행할 수 있습니다.

<br>

## 📊 Streamlit 데이터 전처리 대시보드

기존 Python CLI 기반 데이터 전처리 기능을 웹 환경으로 확장한 **Labelme Dataset Preprocessing Dashboard**입니다.

데이터셋 업로드부터 객체 분포 분석, 데이터 이상 현황 확인, 복수 무기타입 검수 및 분석 결과 다운로드까지 하나의 웹 인터페이스에서 수행할 수 있습니다.

### 1. 대시보드 실행

초기 세팅을 완료한 후 저장소 루트에서 다음 명령어를 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app/app.py
```

실행 후 터미널에 표시되는 Local URL을 통해 웹 대시보드에 접속할 수 있습니다.

```text
http://localhost:8501
```

### 2. 데이터셋 업로드 및 분석 옵션

**지원 파일 형식**

- 단일 Labelme JSON 파일
- 복수 Labelme JSON 파일
- JSON 파일이 포함된 ZIP 파일
- 이미지 및 JSON 파일이 함께 포함된 ZIP 파일

ZIP 파일은 내부 폴더 구조를 유지하여 처리하며, 업로드 현황을 통해 파일 수와 검증 결과를 확인할 수 있습니다.

**분석 옵션**

| 분석 옵션 | 설명 |
|-----------|------|
| 전체 분석 | 객체 분포 분석 및 복수 무기타입 검수 통합 수행 |
| 객체 및 폴더별 분포 분석 | 클래스별 객체 분포 및 폴더별 데이터 통계 분석 |
| 복수 무기타입 검수 | 기존 검수 기준에 따른 검수 후보 추출 |

사이드바에서 데이터셋을 업로드하고 분석 옵션을 선택한 후 **데이터 분석 실행** 버튼을 클릭합니다.

**실행 화면**

<p align="center">
  <img src="https://private-user-images.githubusercontent.com/195836177/716971457-c7b31c46-6197-43af-8627-76cc7382088a.png?jwt=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJnaXRodWIuY29tIiwiYXVkIjoicmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbSIsImtleSI6ImtleTUiLCJleHAiOjE3OTU1MTA4NDcsIm5iZiI6MTc5NTUxMDU0NywicGF0aCI6Ii8xOTU4MzYxNzcvNzE2OTcxNDU3LWM3YjMxYzQ2LTYxOTctNDNhZi04NjI3LTc2Y2M3MzgyMDg4YS5wbmc_WC1BbXotQWxnb3JpdGhtPUFXUzQtSE1BQy1TSEEyNTYmWC1BbXotQ3JlZGVudGlhbD1BS0lBVkNPRFlMU0E1M1BRSzRaQSUyRjIwMjYxMTI0JTJGdXMtZWFzdC0xJTJGczMlMkZhd3M0X3JlcXVlc3QmWC1BbXotRGF0ZT0yMDI2MTEyNFQwODU1NDdaJlgtQW16LUV4cGlyZXM9MzAwJlgtQW16LVNpZ25hdHVyZT01NWYzNTYzOTM0NDBlYzY3ZDkwZDE5YTc5OWI3MjVmNTJiYjFlM2MyNDM2M2I3NzcyOGU1NmRmMjNlYzllNTk0JlgtQW16LVNpZ25lZEhlYWRlcnM9aG9zdCZyZXNwb25zZS1jb250ZW50LXR5cGU9aW1hZ2UlMkZwbmcifQ.NbbAkkmqAstVRX35lZH1VvzhnBTNtaeweZA_Bhoinxw" width="50%" alt="Streamlit 데이터 전처리 대시보드">
</p>

<p align="center">
  <sub>Labelme 데이터셋 업로드 및 분석 옵션 선택 화면</sub>
</p>

### 3. 데이터 분석 결과 시각화

분석 결과를 요약 카드, 인터랙티브 차트 및 테이블 형태로 제공합니다.

**분석 결과 요약**

- 전체 이미지 수
- 전체 객체 수
- 전체 검수 후보 수
- 전체 분석 소요 시간

**객체 클래스별 분포**

- 막대그래프를 활용한 클래스별 객체 수 비교
- 도넛 차트를 활용한 클래스별 객체 비율 확인
- 데이터셋 내 클래스 편중 및 불균형 파악

<p align="center">
  <img src="https://private-user-images.githubusercontent.com/195836177/716971538-f28fe3bc-e513-44a5-97f3-04e4ec652cd6.png?jwt=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJnaXRodWIuY29tIiwiYXVkIjoicmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbSIsImtleSI6ImtleTUiLCJleHAiOjE3OTU1MTA4NDcsIm5iZiI6MTc5NTUxMDU0NywicGF0aCI6Ii8xOTU4MzYxNzcvNzE2OTcxNTM4LWYyOGZlM2JjLWU1MTMtNDRhNS05N2YzLTA0ZTRlYzY1MmNkNi5wbmc_WC1BbXotQWxnb3JpdGhtPUFXUzQtSE1BQy1TSEEyNTYmWC1BbXotQ3JlZGVudGlhbD1BS0lBVkNPRFlMU0E1M1BRSzRaQSUyRjIwMjYxMTI0JTJGdXMtZWFzdC0xJTJGczMlMkZhd3M0X3JlcXVlc3QmWC1BbXotRGF0ZT0yMDI2MTEyNFQwODU1NDdaJlgtQW16LUV4cGlyZXM9MzAwJlgtQW16LVNpZ25hdHVyZT01MzYwN2VmZWRjMTAwNTQwNmFkOTNiNTZkYjI1ZjE2NTdhN2VmNGE2OWI5NmMyMjE0OTJmMTkzOGEyYjZkMjQ0JlgtQW16LVNpZ25lZEhlYWRlcnM9aG9zdCZyZXNwb25zZS1jb250ZW50LXR5cGU9aW1hZ2UlMkZwbmcifQ.t6rpjQqFVLGjU9SmMC77EFOkXMkSy-NfR78xyS6pcCY" width="50%" alt="데이터 분석 결과 및 객체 분포 시각화">
</p>

<p align="center">
  <sub>분석 결과 요약 및 클래스별 객체 분포 시각화 화면</sub>
</p>

**폴더별 데이터 분석**

- 폴더별 이미지 수 및 객체 수 집계
- 이미지당 평균 객체 수 계산
- 폴더별 데이터 분포 비교 및 필터링

**데이터 이상 현황**

- 객체가 없는 이미지
- JSON 파일 누락
- JSON 파싱 오류
- 이미지와 JSON 파일명 불일치

입력 데이터의 구성에 따라 판단할 수 없는 항목은 **확인 불가**로 표시합니다.

### 4. 복수 무기타입 검수

기존 `multi_weapon_review.py`의 검수 기준을 활용하여 검수 후보를 추출하고 결과를 시각화합니다.

- 서로 다른 복수 무기타입 검수 후보 확인
- 중복 및 복수 무기타입 검수 후보 확인
- 검수 유형, 폴더 및 객체 클래스별 필터링
- 검수 대상 파일의 객체 정보 및 상세 내용 확인

검수 화면은 읽기 전용으로 제공되며, 원본 이미지 및 JSON 파일을 수정하지 않습니다.


<br>

## 🚀 기능별 실행 방법

기존 Python CLI 및 GUI 기반 자동화 기능은 Streamlit 대시보드와 별도로 실행할 수 있습니다.

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

### 3. Excel 이미지 설명 병합

```powershell
.\.venv\Scripts\python.exe -m description_merge.main
```

실행 후 다음 순서로 경로를 입력합니다.

1. 설명을 병합할 기존 Excel 파일
2. 새로 생성된 설명이 포함된 Excel 파일
3. 병합 결과를 저장할 경로

### 4. FP 검수 대상 추출

```powershell
.\.venv\Scripts\python.exe -m fp_labeling.main
```

GUI에서 입력 파일 또는 폴더와 결과 저장 폴더를 지정합니다.

- 확장자를 제외한 파일명이 동일한 이미지와 JSON 자동 매칭
- JSON의 `shapes` 배열에 객체 정보가 있는 파일 추출
- 검수 대상 이미지 및 JSON 파일 복사
- 파일 처리 결과와 예외 내역을 CSV로 저장

**실행 화면**

<p align="center">
  <img src="https://github.com/user-attachments/assets/b898a330-77c9-4178-84da-1d58dc80fd1a" width="350" alt="FP 검수 대상 추출 GUI">
</p>

<p align="center">
  <sub>입력 경로 설정, 객체 검수 대상 추출 및 처리 결과 로그를 제공하는 GUI 화면</sub>
</p>


<br>

## ✅ 테스트 실행

테스트는 임시 파일 및 모의 API 응답을 사용하며, 저장소 루트에서 실행합니다.

### 전체 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

### Streamlit 대시보드 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_streamlit_dashboard.py" -v
```

Streamlit 대시보드 및 관련 테스트는 Python 3.10 이상에서 실행할 수 있으며, 기존 Description 테스트를 포함한 전체 테스트 실행에는 Python 3.11 이상이 필요합니다.

<br>

## 📁 프로젝트 구성

```text
hanwha-vision-automation/
├── data_preprocessing/          # 객체 분포 분석 및 복수 무기타입 검수
│   ├── folder_object_distribution.py
│   └── multi_weapon_review.py
├── description_generation/      # OpenAI API 기반 이미지 설명 생성
│   ├── config.py                # 데이터셋 및 API 실행 설정
│   └── main.py                  # 이미지 설명 생성 실행
├── description_merge/           # Excel 이미지 설명 병합
│   └── main.py
├── fp_labeling/                 # GUI 기반 FP 검수 대상 추출
│   └── main.py
├── streamlit_app/               # 데이터 전처리 시각화 대시보드
│   └── app.py                   # Streamlit 실행 진입점
├── tests/                       # 기능별 단위 테스트
├── docs/
│   └── images/                  # 기능별 실행 화면
│       ├── fp_labeling_gui.png
│       ├── streamlit_dashboard_main.png
│       └── streamlit_dashboard_analysis.png
├── output/                      # 이미지 설명 및 체크포인트 출력
├── logs/                        # 실행 로그
├── .env.example                 # 환경변수 설정 예시
├── requirements.txt             # Python 패키지 목록
└── README.md
```

<br>
