# Hanwha Vision image descriptions

로컬 이미지와 LabelMe annotation JSON을 함께 OpenAI Responses API에 전달하여 영어 description을 만들고 Excel로 저장합니다. Python **3.10 이상**을 사용하세요.

## 실행 방법

프로젝트 폴더에서 다음 명령을 실행합니다.

```powershell
pip install -r requirements.txt
```

생성되어 있는 `.env`에 키만 입력합니다. `.env`가 없다면 `.env.example`을 `.env`로 복사합니다.

```env
OPENAI_API_KEY=your_actual_api_key
```

`.env`에서는 `OPENAI_API_KEY` 한 값만 읽으며, 다른 환경 변수나 시스템 환경의 키를 대신 사용하지 않습니다. 모델, 경로, 재시도 및 저장 주기는 `config.py`에서 변경합니다. 기본 모델은 `gpt-4.1`이며 계정에서 사용 가능한 이미지 입력 지원 Responses 모델로 변경할 수 있습니다.

이미지는 `data/images/`, JSON은 `data/json/`에 넣습니다. 하위 폴더도 탐색합니다. 제공된 샘플로 시작하려면:

```powershell
Copy-Item "$env:USERPROFILE/Downloads/m1-1-001.png" data/images/
Copy-Item "$env:USERPROFILE/Downloads/m1-1-001.json" data/json/
python main.py
```

일반 실행도 `python main.py` 한 명령입니다. Windows에서 `python`을 찾지 못하면 Python 3.10 이상을 설치하고 **Add Python to PATH**를 선택한 뒤 터미널을 다시 엽니다. 설치 환경에서 `py`만 지원하면 `py -m pip install -r requirements.txt`, `py main.py`를 사용할 수 있습니다.

실제 API 요청에는 비용이 발생합니다. API 키는 Git에 커밋하지 마세요. `.gitignore`는 `.env`, 입력 데이터, 출력 및 로그를 제외합니다.

## 디렉토리 구조

```text
hanwha-vision-automation/
├── .env                  # OPENAI_API_KEY만 입력
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
├── main.py               # 파싱, 매칭, 요청, 재시도, resume, Excel 저장
├── config.py             # 모든 기본 설정
├── prompt.py             # 작성 규칙, few-shot 예시
├── tests/
│   └── test_pipeline.py   # 실제 API 비용 없이 검증
├── data/
│   ├── images/
│   └── json/
├── output/
│   ├── descriptions.xlsx # 실행 시 생성
│   └── checkpoint.jsonl  # 성공 결과를 매 건 기록
└── logs/
    └── run_YYYYMMDD_HHMMSS.log
```

## 실제 JSON 파싱

첨부 `m1-1-001.json`의 실제 구조를 기준으로 구현했습니다.

```json
{
  "shapes": [{
    "label": "전차",
    "points": [[782.0, 319.0], [1170.0, 475.0]],
    "시선방향": "측면",
    "무장여부": true,
    "무기타입": ["포/포탑_1", "원격무장_1"],
    "무기방향": ["이외", "이외"],
    "shape_type": "rectangle"
  }],
  "imagePath": "m1-1-001.png",
  "imageWidth": 1280,
  "imageHeight": 720
}
```

`shapes`의 각 항목을 한 객체로 계산하고 `label`을 지정된 영어 class로 변환합니다. `points`로 bbox를 계산하여 모델이 객체와 이미지 속 행동을 연결할 수 있도록 제공합니다. 좌표는 최종 description에 쓰지 않도록 지시합니다. 객체별 추가 속성, `flags`, 이미지 메타데이터도 전달하며, 중복 이미지 바이트인 `imageData`는 제외합니다.

샘플에는 `valid` 키가 없습니다. `valid`가 존재하면 그대로 전달하고, `false`라도 필터링하지 않습니다. 사람의 `시선방향`은 시선/향하는 방향, 차량의 `시선방향`은 본체 방향으로 해석합니다. `본체방향`이 따로 있으면 우선합니다. `무기타입`과 `무기방향` 배열은 동일 인덱스로 연결하며 길이가 다르면 오류로 기록합니다. `_1`은 식별 접미사로 취급합니다. `이외`는 `other`로 보존하여 전방/측방/후방으로 임의 변환하지 않습니다. 샘플은 tank 한 대로 계산되고 두 무장 타입과 각각의 방향을 전달합니다.

다른 JSON 스키마(`objects`, `annotations` 등)는 자동 추측하지 않고 로그에 오류를 남깁니다. 그런 데이터는 `parse_annotation()`을 해당 스키마에 맞게 수정해야 합니다. class/방향/무기 번역은 `config.py`의 매핑에서 확장할 수 있습니다.

## 처리 흐름

1. JSON을 정렬하여 탐색하고 원본 `imagePath`, 객체와 속성을 읽습니다.
2. 상대경로는 이미지 루트 기준, 절대경로는 해당 위치에서 매칭합니다. 찾지 못하면 basename으로 재탐색합니다. 같은 basename이 여러 개면 잘못 연결하지 않고 오류 처리합니다. Windows의 `\\`와 `/`를 지원하고 원본 문자열은 Excel에서 유지합니다.
3. 기존 Excel과 체크포인트에서 성공한 `imagePath`를 찾으면 API 호출 없이 재사용합니다.
4. 이미지를 확인하고 Base64 data URL로 변환합니다. PNG/JPEG/WEBP/정지 GIF를 지원하고 BMP/TIFF는 PNG로 변환합니다. 애니메이션 이미지는 오류 처리합니다.
5. 한 Responses 요청에 실제 이미지와 annotation 정보를 함께 넣습니다. JSON class/개수/속성을 우선하고, 이미지는 행동과 장면 확인에 사용하도록 지시합니다. 영어 본문 한 개를 반환하도록 작성 규칙과 세 가지 few-shot을 적용합니다. 데이터 내부의 지시문은 따르지 않도록 프롬프트에 명시합니다.
6. 빈 응답, 불완전 응답, 형식 오류, 일시적인 Rate Limit, 연결/timeout 및 서버 오류는 최대 5회 재시도합니다. 지수 백오프와 jitter를 적용하며 숫자/HTTP 날짜 형식 `Retry-After`도 반영합니다. 인증/권한/크레딧/한도 오류는 재시도하지 않고 추가 API 호출을 중단합니다.
7. 성공 즉시 체크포인트를 flush/fsync합니다. Excel은 기본 10건 처리 또는 60초 경과 후 다음 처리 완료 시점, 그리고 종료 시 저장합니다. 긴 API 요청 중 타이머가 별도로 Excel을 저장하는 방식은 아닙니다.
8. 성공/실패/재사용 건수, 현재 JSON 파일 및 진행률을 콘솔과 로그에 출력합니다. 실패가 있으면 종료 코드 1, 정상 완료는 0, Ctrl+C 중단은 130입니다.

## Excel 및 resume

결과는 `output/descriptions.xlsx`, 시트는 정확히 `description`, 헤더는 정확히 `imagePath`, `description`입니다. 현재 입력 JSON당 한 행을 만들며, 같은 `imagePath`를 가진 JSON이 여러 개면 행은 각각 유지하고 이미 성공한 description을 재사용합니다. 같은 경로의 annotation을 변경했다면 아래 재생성 방법을 사용하세요.

이미지 없음/API 실패/객체 정보 오류는 읽을 수 있는 원본 `imagePath`와 빈 description으로 남겨 다음 실행에서 다시 시도합니다. **파일 자체가 파싱되지 않거나 유효한 `imagePath`가 없으면 원본 경로를 알 수 없으므로 Excel 행을 만들지 않고 로그에 기록합니다.** `valid=false`는 실패 조건이 아니며 정상적으로 생성 요청합니다.

동일 명령을 다시 실행하면 공백이 아닌 성공 결과만 건너뜁니다. Excel 저장은 임시 파일 저장 후 교체하는 방식입니다. Windows에서 결과 Excel을 열어 두면 교체가 실패할 수 있으므로 닫고 다시 실행하세요. 이 경우에도 매 건 성공 결과는 체크포인트에 남습니다. 강제 종료로 체크포인트 마지막 줄이 손상되면 그 줄만 무시합니다. Ctrl+C 시 이전에 복구한 성공 결과도 보존합니다.

전체 재생성이 필요하면 `config.py`의 `RESUME = False`로 변경하세요. 기존 체크포인트는 `.bak.jsonl`로 이동하고 Excel은 새 결과로 갱신됩니다. 다음 실행부터 재사용하려면 다시 `True`로 바꿉니다. Excel 최대 데이터 행 수는 1,048,575개입니다. 현재 프로그램은 그보다 많은 데이터에 대한 파일 분할을 제공하지 않습니다. 같은 출력 폴더에 여러 프로세스를 동시에 실행하지 마세요.

형식/빈 응답은 코드로 검증하지만, 자연어의 모든 의미적 속성 일치를 코드가 보장하지는 않습니다. 실제 데이터에서 소량의 결과를 검토한 후 대량 실행하세요. API 응답은 `store=False`로 요청합니다.

## 검증

설치 후 실제 API 호출 없이 테스트:

```powershell
python -m unittest discover -s tests -v
```

테스트는 샘플 구조의 파싱, 경로 매칭과 중복 basename 거부, API 요청의 이미지+annotation 전달, 빈 응답/Rate Limit 재시도, Excel 원본 경로 보존과 checkpoint 복구, 실패 후 계속 처리 및 resume를 확인합니다.

구현에 참고한 공식 문서: [OpenAI 이미지 입력 및 Responses API](https://developers.openai.com/api/docs/guides/images-vision).

## HTTP 429 오류 해결

로그에 `HTTP 429`만 표시되던 부분을 수정하여 이제 `code=...`, `type=...`과 해결 안내를 표시합니다. 기존 로그만으로는 일시적인 요청 제한인지 크레딧/사용 한도 문제인지 구분할 수 없습니다.

- `insufficient_quota`, `credit_balance_exhausted`: 사용 중인 API 프로젝트의 크레딧과 결제 상태를 확인하세요.
- `organization_spend_limit_exceeded`, `project_spend_limit_exceeded`, `organization_usage_limit_exceeded`: 해당 조직/프로젝트의 사용 한도를 확인하세요.
- `rate_limit_exceeded`, `slow_down`: 요청/토큰 제한입니다. 프로그램이 자동 재시도하고, 계속 실패하면 잠시 후 다시 실행하세요.
- `code=unknown`, `type=unknown`: 서버 응답에 상세 오류 코드가 없는 경우입니다. HTTP 상태와 계정의 Billing/Limits를 함께 확인해야 합니다.

크레딧/한도 오류는 대기만으로 해결되지 않으므로 재시도하지 않고, 같은 실행의 이후 미처리 이미지에도 추가 API 호출을 하지 않습니다. 인증(401)/권한(403) 오류도 동일하게 처리하며 기존 성공 결과는 재사용합니다. 실패한 행은 빈 description으로 저장하여 계정 문제 해결 후 재실행할 수 있습니다. 일시적 오류는 재시도를 유지하고, `Retry-After`가 60초를 초과해도 서버가 지정한 최소 대기시간을 지킵니다.

계정 설정은 [OpenAI Platform](https://platform.openai.com/)의 해당 프로젝트 Billing 및 Limits에서 확인하세요. 상세 원인과 조치는 [공식 오류 코드 문서](https://developers.openai.com/api/docs/guides/error-codes)를 참고하세요.
