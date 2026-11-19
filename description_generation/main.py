"""Generate one English caption per annotation JSON with resumable Excel export."""
from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from datetime import datetime
from email.utils import parsedate_to_datetime
import logging
import random
import re
import sys
import time

from dotenv import dotenv_values
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from . import config as cfg
from .annotations import (
    ImageMatcher, discover_annotations, image_data_url, parse_annotation, scoped_resume_keys,
)
from .prompt import SYSTEM_PROMPT, build_annotation_text
from .rate_limiter import AsyncRateLimiter, RunStats
from .storage import append_checkpoint, load_results, save_excel

LOGGER = logging.getLogger("descriptions")
QUOTA_CODES = {
    "insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached",
    "billing_not_active", "organization_spend_limit_exceeded",
    "project_spend_limit_exceeded", "organization_usage_limit_exceeded",
}


def api_error_details(exc: APIStatusError) -> tuple[str, str]:
    """Extract machine-readable fields only; never log bodies, keys or headers."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    fields = []
    for name in ("code", "type"):
        value = body.get(name) if isinstance(body, dict) else None
        value = value or getattr(exc, name, None)
        fields.append(value if isinstance(value, str) and re.fullmatch(r"[a-z_]{1,80}", value) else "unknown")
    return tuple(fields)


def is_quota_error(exc: APIStatusError) -> bool:
    code, error_type = api_error_details(exc)
    return code in QUOTA_CODES or error_type == "insufficient_quota"


def api_error_hint(exc: APIStatusError) -> str:
    if is_quota_error(exc):
        return "API 크레딧/사용 한도 오류입니다. 해당 API 프로젝트의 Billing과 Limits를 확인한 뒤 다시 실행하세요."
    if exc.status_code == 429:
        return "API 요청/토큰 제한입니다. 잠시 후 재실행하거나 프로젝트의 모델별 Limits를 확인하세요."
    if exc.status_code == 401:
        return "프로젝트 .env의 OPENAI_API_KEY가 유효한지 확인하세요."
    if exc.status_code == 403:
        return "API 프로젝트 및 모델 접근 권한을 확인하세요."
    return "API 오류 코드와 요청 설정을 확인하세요."


def retry_delay(exc: Exception, attempt: int) -> float:
    delay = min(cfg.RETRY_MAX_SECONDS, cfg.RETRY_BASE_SECONDS * 2 ** (attempt - 1) + random.uniform(0, 1))
    if isinstance(exc, APIStatusError):
        raw = exc.response.headers.get("retry-after")
        if raw:
            try:
                server_delay = float(raw)
            except ValueError:
                try:
                    server_delay = parsedate_to_datetime(raw).timestamp() - time.time()
                except (ValueError, TypeError, OverflowError):
                    server_delay = 0.0
            if math.isfinite(server_delay):
                # The server's minimum wait must not be shortened by our backoff cap.
                delay = max(delay, server_delay)
    return delay


async def wait_before_retry(delay: float) -> None:
    while delay > 0:
        chunk = min(delay, 30.0)
        await asyncio.sleep(chunk)
        delay -= chunk


def setup_logging() -> None:
    cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOGGER.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in [logging.StreamHandler(sys.stdout), logging.FileHandler(
        cfg.LOG_DIR / f"run_{datetime.now():%Y%m%d_%H%M%S}.log", encoding="utf-8"
    )]:
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)


class InvalidDescription(ValueError):
    pass


def validate_description(text: str) -> str:
    text = text.strip()
    if not text:
        raise InvalidDescription("Empty API response")
    if len(text) > 32767:
        raise InvalidDescription("Description exceeds Excel cell limit")
    if re.search(r"[\uac00-\ud7a3]", text) or not re.search(r"[A-Za-z]", text):
        raise InvalidDescription("Description is not English")
    if re.match(r"(?i)^(description\s*:|\d+[.)]\s|[-*#>]\s|[\[{\"])", text) or "```" in text:
        raise InvalidDescription("Response contains a heading, numbering, JSON or Markdown")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
        raise InvalidDescription("Response contains invalid Excel control characters")
    return " ".join(text.split())


async def generate_description(client: AsyncOpenAI, annotation: dict, image_url: str, check_api=None,
                               limiter=None, stats=None) -> str:
    # UTF-8 byte count is a conservative text estimate; image allowance is approximate.
    estimated_tokens = len((SYSTEM_PROMPT + build_annotation_text(annotation)).encode("utf-8")) + 4096 + cfg.MAX_OUTPUT_TOKENS
    for attempt in range(1, cfg.MAX_ATTEMPTS + 1):
        try:
            if limiter is not None:
                await limiter.acquire(estimated_tokens)
            if check_api is not None:
                check_api()
            call_started = time.monotonic()
            if stats is not None:
                stats.active += 1
            try:
                response = await client.responses.create(
                model=cfg.MODEL, instructions=SYSTEM_PROMPT, store=False,
                max_output_tokens=cfg.MAX_OUTPUT_TOKENS,
                input=[{"role": "user", "content": [
                    {"type": "input_text", "text": build_annotation_text(annotation)},
                    {"type": "input_image", "image_url": image_url, "detail": cfg.IMAGE_DETAIL},
                ]}],
                )
            finally:
                if stats is not None:
                    stats.active -= 1
                    stats.calls += 1
                    stats.api_seconds += time.monotonic() - call_started
            if stats is not None:
                stats.record_usage(response)
            if response.status != "completed":
                raise InvalidDescription(f"API response status: {response.status}")
            return validate_description(response.output_text)
        except (APIConnectionError, APITimeoutError, APIStatusError, InvalidDescription) as exc:
            delay = retry_delay(exc, attempt)
            if isinstance(exc, APIStatusError) and exc.status_code == 429:
                if stats is not None:
                    stats.errors_429 += 1
                if limiter is not None and not is_quota_error(exc):
                    await limiter.cooldown(delay)
            retryable = not isinstance(exc, APIStatusError) or exc.status_code in {408, 409, 429} or exc.status_code >= 500
            if isinstance(exc, APIStatusError) and is_quota_error(exc):
                retryable = False
            if not retryable or attempt == cfg.MAX_ATTEMPTS:
                raise
            if stats is not None:
                stats.retries += 1
            # Do not log API response bodies, headers or keys.
            code, error_type = api_error_details(exc) if isinstance(exc, APIStatusError) else ("n/a", "n/a")
            LOGGER.warning("Retry %d/%d in %.1fs (%s, code=%s, type=%s)", attempt, cfg.MAX_ATTEMPTS, delay, type(exc).__name__, code, error_type)
            await wait_before_retry(delay)
    raise RuntimeError("Retry loop exhausted")


def format_duration(seconds: float) -> str:
    seconds = max(0, math.ceil(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def log_progress(processed: int, total: int, elapsed: float) -> None:
    remaining = max(0, total - processed)
    eta = format_duration(elapsed * remaining / processed) if processed else "계산 중"
    LOGGER.info("처리 완료 %d/%d (%.1f%%) | 남은 %d건 | 경과 %s | 예상 남은 시간 %s",
                processed, total, 100 * processed / total if total else 100.0,
                remaining, format_duration(elapsed), eta)


async def run_async() -> int:
    started_at = time.monotonic()
    for name, directory in (("IMAGE_DIR", cfg.IMAGE_DIR), ("JSON_DIR", cfg.JSON_DIR)):
        if not directory.is_dir():
            raise FileNotFoundError(f"{name} 입력 폴더가 없습니다: {directory}. SSD 연결과 config.py 경로를 확인하세요.")
    for directory in (cfg.OUTPUT_FILE.parent, cfg.CHECKPOINT_FILE.parent):
        directory.mkdir(parents=True, exist_ok=True)
    LOGGER.info("이미지 입력 폴더: %s", cfg.IMAGE_DIR)
    LOGGER.info("JSON 입력 폴더: %s", cfg.JSON_DIR)
    if cfg.MAX_ATTEMPTS < 1:
        raise ValueError("MAX_ATTEMPTS must be positive")
    if not isinstance(cfg.MAX_CONCURRENT_REQUESTS, int) or isinstance(cfg.MAX_CONCURRENT_REQUESTS, bool) or not 1 <= cfg.MAX_CONCURRENT_REQUESTS <= min(50, cfg.MAX_CONCURRENT_LIMIT):
        raise ValueError("MAX_CONCURRENT_REQUESTS must be an integer between 1 and 50")
    limiter = AsyncRateLimiter(cfg.RATE_LIMIT_RPM, cfg.RATE_LIMIT_TPM, cfg.RATE_LIMIT_SAFETY_FACTOR)
    stats = RunStats()
    LOGGER.info("Excel은 전체 처리 완료 후 한 번 저장합니다. 중단 시 checkpoint로 복구합니다.")
    LOGGER.info("Rate limits RPM=%s TPM=%s safety=%s; image tokens are estimates",
                cfg.RATE_LIMIT_RPM, cfg.RATE_LIMIT_TPM, cfg.RATE_LIMIT_SAFETY_FACTOR)
    LOGGER.info("JSON 탐색 시작: %s", cfg.JSON_DIR)
    files = await asyncio.to_thread(discover_annotations)
    if not files:
        LOGGER.info("입력 폴더와 하위 폴더에 annotation JSON 파일이 없습니다: %s", cfg.JSON_DIR)
        return 0
    LOGGER.info("Checkpoint 확인 시작")
    results = await asyncio.to_thread(load_results)
    LOGGER.info("Checkpoint 확인 완료: 재사용 후보 %d건", len(results))
    if not cfg.RESUME and cfg.CHECKPOINT_FILE.exists():
        # Start a new checkpoint without deleting old successful results.
        backup = cfg.CHECKPOINT_FILE.with_name(f"checkpoint_{time.time_ns()}.bak.jsonl")
        cfg.CHECKPOINT_FILE.replace(backup)
    LOGGER.info("이미지 목록 생성 시작: %s", cfg.IMAGE_DIR)
    matcher = await asyncio.to_thread(ImageMatcher, cfg.IMAGE_DIR)
    LOGGER.info("작업 처리 시작: %d건, 동시 작업 %d개; 해시는 각 작업에서 계산합니다",
                len(files), cfg.MAX_CONCURRENT_REQUESTS)
    rows = []
    success = failed = skipped = processed = 0
    client = None
    blocked_api_error = None
    log_progress(0, len(files), time.monotonic() - started_at)
    interrupted = False
    path_locks = defaultdict(asyncio.Lock)
    pending_files = iter(enumerate(files, 1))

    def check_api():
        if blocked_api_error is not None:
            raise blocked_api_error

    async def worker():
        nonlocal client, success, failed, skipped, processed, blocked_api_error
        for index, json_path in pending_files:
            LOGGER.debug("작업 시작 [%d/%d]: %s", index, len(files), json_path.relative_to(cfg.JSON_DIR))
            row_index = None
            try:
                _, annotation = parse_annotation(json_path)
                matched = matcher.resolve(json_path)
                image_path = matched.relative_to(matcher.root).as_posix()
                if len(image_path) > 32767 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", image_path):
                    raise ValueError("imagePath cannot be represented unchanged in an Excel cell")
                row_index = len(rows)
                rows.append((image_path, ""))
                # Reserve the Excel row before yielding, preserving annotation order.
                # Reading large images must not block the progress reporter or API tasks.
                resume_keys = await asyncio.to_thread(scoped_resume_keys, [json_path], matcher)
                result_key = resume_keys.get(json_path)
                if result_key is None:
                    raise ValueError("Unable to fingerprint image and annotation for safe resume")
                if cfg.RESUME and result_key in results:
                    rows[row_index] = (image_path, results[result_key])
                    skipped += 1
                    LOGGER.debug("Resume: already generated %s", image_path)
                else:
                    # Only jobs with the same verified source identity share results.
                    async with path_locks[result_key]:
                        if cfg.RESUME and result_key in results:
                            rows[row_index] = (image_path, results[result_key])
                            skipped += 1
                        else:
                            check_api()
                            if client is None:
                                # Explicitly read this one .env value; do not fall back to process environment.
                                key = dotenv_values(cfg.ENV_FILE, interpolate=False).get("OPENAI_API_KEY")
                                if not key or key.strip() in {"your_api_key", "..."}:
                                    raise ValueError("Set OPENAI_API_KEY in the project .env file")
                                client = AsyncOpenAI(api_key=key.strip(), max_retries=0, timeout=cfg.REQUEST_TIMEOUT)
                            image_url = await asyncio.to_thread(image_data_url, matched)
                            description = await generate_description(client, annotation, image_url, check_api, limiter, stats)
                            # No await between checkpoint and shared state updates.
                            append_checkpoint(image_path, description, resume_keys.get(json_path))
                            results[result_key] = description
                            rows[row_index] = (image_path, description)
                            success += 1
                            LOGGER.debug("API 호출 성공: %s — description 생성 및 체크포인트 저장 완료", image_path)
            except Exception as exc:
                failed += 1
                if row_index is None:
                    try:
                        matched = matcher.resolve(json_path)
                        rows.append((matched.relative_to(matcher.root).as_posix(), ""))
                    except (OSError, ValueError):
                        pass  # Missing/ambiguous matches have no actual image path to export.
                if isinstance(exc, APIStatusError):
                    code, error_type = api_error_details(exc)
                    LOGGER.error("Failed %s: %s (HTTP %s, code=%s, type=%s). %s", json_path.relative_to(cfg.JSON_DIR), type(exc).__name__, exc.status_code, code, error_type, api_error_hint(exc))
                    if is_quota_error(exc) or exc.status_code in {401, 403}:
                        blocked_api_error = exc
                else:
                    LOGGER.error("Failed %s: %s: %s", json_path.relative_to(cfg.JSON_DIR), type(exc).__name__, exc)
            processed += 1
            stats.completed.append(time.monotonic())

    def report():
        now = time.monotonic()
        elapsed = now - started_at
        while stats.completed and stats.completed[0] <= now - 60:
            stats.completed.popleft()
        limiter.prune(now)
        newly_processed = processed - skipped
        eta = format_duration(elapsed * (len(files) - processed) / newly_processed) if newly_processed else ("00:00:00" if processed == len(files) else "N/A")
        LOGGER.info("[Progress] %d/%d (%.2f%%) | Success: %d | Failed: %d | Resumed: %d",
                    processed, len(files), 100 * processed / len(files), success, failed, skipped)
        LOGGER.info("[Speed] Recent 60s: %d | %.1f items/min | Avg API: %s | Concurrency: %d | 429: %d | Retries: %d",
                    len(stats.completed), len(stats.completed) * 60 / min(60, max(elapsed, .001)),
                    f"{stats.api_seconds / stats.calls:.2f}s" if stats.calls else "N/A",
                    stats.active, stats.errors_429, stats.retries)
        LOGGER.info("[Tokens] Input: %s | Output: %s | Usage responses: %d/%d | Estimated TPM: %d | Wait (worker-seconds): %.1fs | Elapsed: %s | ETA: %s",
                    stats.input_tokens if stats.usage_responses else "N/A",
                    stats.output_tokens if stats.usage_responses else "N/A", stats.usage_responses, stats.calls,
                    limiter.tokens, limiter.wait_seconds, format_duration(elapsed), eta)

    async def reporter():
        while True:
            try:
                await asyncio.wait_for(asyncio.Event().wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
            report()

    reporting_task = asyncio.create_task(reporter())
    tasks = [asyncio.create_task(worker()) for _ in range(cfg.MAX_CONCURRENT_REQUESTS)]
    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        interrupted = True
        LOGGER.warning("Interrupted. Successful results remain in checkpoint; rerun to resume.")
    finally:
        reporting_task.cancel()
        await asyncio.gather(reporting_task, return_exceptions=True)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        saved = False
        if not interrupted and processed == len(files):
            saved = save_excel(rows)
        if client is not None:
            await client.close()
        LOGGER.info("Completed: success=%d, failed=%d, skipped=%d, processed=%d/%d", success, failed, skipped, processed, len(files))
        report()
        LOGGER.info("총 경과 시간: %s", format_duration(time.monotonic() - started_at))
        if saved:
            LOGGER.info("Excel: %s", cfg.OUTPUT_FILE)
    return 130 if interrupted else (1 if failed or not saved else 0)


def run() -> int:
    return asyncio.run(run_async())


def main() -> int:
    setup_logging()
    try:
        return run()
    except Exception as exc:
        LOGGER.error("Startup failed: %s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
