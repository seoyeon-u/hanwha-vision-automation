import asyncio
import unittest

from description_generation.rate_limiter import AsyncRateLimiter


class LimiterTests(unittest.TestCase):
    def run_case(self, rpm=None, tpm=None, tokens=10, safety=1):
        now = [0.0]
        async def sleep(delay):
            now[0] += delay
            await asyncio.sleep(0)
        limiter = AsyncRateLimiter(rpm, tpm, safety, clock=lambda: now[0], sleep=sleep)
        async def run():
            await limiter.acquire(tokens)
            await limiter.acquire(tokens)
        asyncio.run(run())
        return now[0], limiter

    def test_rpm_rolling_window(self):
        elapsed, limiter = self.run_case(rpm=1)
        self.assertEqual(elapsed, 60)
        self.assertEqual(limiter.wait_seconds, 60)

    def test_tpm_and_safety(self):
        self.assertEqual(self.run_case(tpm=100, tokens=45, safety=.8)[0], 60)
        self.assertEqual(self.run_case(tpm=100, tokens=40, safety=.8)[0], 0)

    def test_unconfigured(self):
        self.assertEqual(self.run_case()[0], 0)

    def test_oversized_request_fails_without_hanging(self):
        limiter = AsyncRateLimiter(tpm=10)
        with self.assertRaises(ValueError):
            asyncio.run(limiter.acquire(20))

    def test_shared_cooldown_and_atomic_reservations(self):
        now = [0.0]
        admissions = []
        async def sleep(delay):
            now[0] += delay
            await asyncio.sleep(0)
        limiter = AsyncRateLimiter(rpm=1, safety=1, clock=lambda: now[0], sleep=sleep)
        async def worker():
            await limiter.acquire(10)
            admissions.append(now[0])
        async def run():
            await limiter.cooldown(90)
            await asyncio.gather(*(worker() for _ in range(3)))
        asyncio.run(run())
        self.assertGreaterEqual(admissions[0], 90)
        self.assertTrue(all(b - a >= 60 for a, b in zip(admissions, admissions[1:])))

    def test_invalid_settings(self):
        for kwargs in ({"rpm": 0}, {"tpm": -1}, {"safety": 0}, {"safety": 2}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                AsyncRateLimiter(**kwargs)
