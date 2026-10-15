"""Edit settings here. .env contains ONLY OPENAI_API_KEY."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# SSD 데이터 폴더의 전체 경로를 지정하세요. None이면 기존 data 폴더를 사용합니다.
# 예: INPUT_DIR = Path(r"E:\원시데이터\hanwha\1차 납품\01-17-27-52")
INPUT_DIR = Path(r"D:\26pj227-a_한화에어로스페이스 원시데이터\hanwha\1차 납품")
IMAGE_DIR = INPUT_DIR if INPUT_DIR is not None else BASE_DIR / "data" / "images"
JSON_DIR = INPUT_DIR if INPUT_DIR is not None else BASE_DIR / "data" / "json"
# 입력에서 제외할 JSON 파일명. 하위 폴더에도 적용되며 대소문자를 구분하지 않습니다.
# Excel 파일은 원래 입력 대상이 아니므로 여기에 추가할 필요가 없습니다.
EXCLUDED_JSON_FILES = {"1st_test.json"}
OUTPUT_FILE = BASE_DIR / "output" / "descriptions.xlsx"
CHECKPOINT_FILE = BASE_DIR / "output" / "checkpoint.jsonl"
LOG_DIR = BASE_DIR / "logs"
ENV_FILE = BASE_DIR / ".env"
SHEET_NAME = "description"
MODEL = "gpt-4.1"
IMAGE_DETAIL = "high"
MAX_OUTPUT_TOKENS = 2000
REQUEST_TIMEOUT = 120.0
MAX_ATTEMPTS = 5
MAX_CONCURRENT_REQUESTS = 5
RETRY_BASE_SECONDS = 2.0
RETRY_MAX_SECONDS = 60.0
SAVE_EVERY = 10
SAVE_INTERVAL_SECONDS = 60.0
# Always request fresh descriptions by default. Set True only to resume saved work.
RESUME = True
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}

CLASS_NAMES = {
    "민간인": "civilian", "군인": "soldier", "민간차량": "civilian vehicle",
    "소형전술차량": "light tactical vehicle", "전차": "tank",
    "자주포": "self-propelled artillery", "장갑차": "armored vehicle",
}
DIRECTIONS = {"정면": "front", "측면": "side", "후면": "rear", "불분명": "unclear", "이외": "other"}
WEAPON_NAMES = {"소총": "rifle", "포/포탑": "gun/turret", "원격무장": "remote weapon system"}
