"""Shared rolling-window request reservations; image token counts are estimates."""
import asyncio
from collections import deque
import math
import time


class AsyncRateLimiter:
    def __init__(self, rpm=None, tpm=None, safety=0.8, *, clock=time.monotonic,
                 sleep=asyncio.sleep):
        if not isinstance(safety, (int, float)) or not 0 < safety <= 1:
            raise ValueError("RATE_LIMIT_SAFETY_FACTOR must be in (0, 1]")
        for value in (rpm, tpm):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or value <= 0):
                raise ValueError("RPM/TPM must be positive finite numbers or None")
        self.rpm = max(1, math.floor(rpm * safety)) if rpm is not None else None
        self.tpm = math.floor(tpm * safety) if tpm is not None else None
        self.clock, self.sleep = clock, sleep
        self.events = deque()
        self.tokens = 0
        self.cooldown_until = 0.0
        self.wait_seconds = 0.0
        self.lock = asyncio.Lock()

    def prune(self, now):
        while self.events and self.events[0][0] <= now - 60:
            _, tokens = self.events.popleft()
            self.tokens -= tokens

    async def acquire(self, tokens):
        if self.tpm is not None and tokens > self.tpm:
            raise ValueError("Estimated request tokens exceed effective TPM; increase configured TPM")
        started = self.clock()
        try:
            while True:
                async with self.lock:
                    now = self.clock()
                    self.prune(now)
                    delay = max(0.0, self.cooldown_until - now)
                    if ((self.rpm is not None and len(self.events) >= self.rpm)
                            or (self.tpm is not None and self.tokens + tokens > self.tpm)):
                        delay = max(delay, self.events[0][0] + 60 - now)
                    if delay <= 0:
                        self.events.append((now, tokens))
                        self.tokens += tokens
                        return
                await self.sleep(min(delay, 30.0))
        finally:
            self.wait_seconds += self.clock() - started

    async def cooldown(self, seconds):
        async with self.lock:
            self.cooldown_until = max(self.cooldown_until, self.clock() + seconds)


class RunStats:
    def __init__(self):
        self.active = self.calls = self.errors_429 = self.retries = 0
        self.api_seconds = 0.0
        self.input_tokens = self.output_tokens = 0
        self.usage_responses = 0
        self.completed = deque()

    def record_usage(self, response):
        usage = getattr(response, "usage", None)
        incoming = getattr(usage, "input_tokens", None)
        outgoing = getattr(usage, "output_tokens", None)
        if isinstance(incoming, int) and isinstance(outgoing, int):
            self.input_tokens += incoming
            self.output_tokens += outgoing
            self.usage_responses += 1
