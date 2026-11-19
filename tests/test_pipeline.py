"""Offline behavioral tests. No real API requests and no user data changes."""
import asyncio
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from openai import RateLimitError, BadRequestError
from openpyxl import load_workbook
from PIL import Image

from description_generation import config as cfg, main


def fixture(image_path="m1-1-001.png"):
    return {
        "imagePath": image_path, "valid": False,
        "shapes": [{"label": "전차", "points": [[782, 319], [1170, 475]],
                    "시선방향": "측면", "무장여부": True,
                    "무기타입": ["포/포탑_1", "원격무장_1"], "무기방향": ["이외", "이외"]}],
    }


def response(text="One tank is facing to the side. Its mounted weapons have unspecified directions."):
    return SimpleNamespace(status="completed", output_text=text)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        settings = {
            "IMAGE_DIR": self.root / "images", "JSON_DIR": self.root / "json",
            "OUTPUT_FILE": self.root / "output" / "descriptions.xlsx",
            "CHECKPOINT_FILE": self.root / "output" / "checkpoint.jsonl",
            "ENV_FILE": self.root / ".env", "RESUME": True,
            "MAX_ATTEMPTS": 3, "SAVE_EVERY": 1,
        }
        self.patcher = patch.multiple(cfg, **settings)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        for directory in [cfg.IMAGE_DIR, cfg.JSON_DIR, cfg.OUTPUT_FILE.parent]:
            directory.mkdir(parents=True)
        cfg.ENV_FILE.write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")

    def write_json(self, name="sample.json", value=None):
        path = cfg.JSON_DIR / name
        path.write_text(json.dumps(fixture() if value is None else value, ensure_ascii=False), encoding="utf-8")
        return path

    def test_real_schema_and_false_valid(self):
        original, annotation = main.parse_annotation(self.write_json())
        self.assertEqual(original, "m1-1-001.png")
        self.assertEqual(annotation["class_counts"], {"tank": 1})
        self.assertIs(annotation["metadata"]["valid"], False)
        tank = annotation["objects"][0]
        self.assertEqual(tank["body_direction"], "side")
        self.assertEqual(tank["weapon_types"], ["gun/turret_1", "remote weapon system_1"])
        self.assertEqual(tank["weapon_directions"], ["other", "other"])
        self.assertEqual(tank["bbox"], [782, 319, 1170, 475])

    def test_counts_and_individual_person_attributes(self):
        value = fixture()
        value["shapes"] = [
            {"label": "군인", "points": [[1, 2], [3, 4]], "시선방향": "정면", "무장여부": True, "무기타입": ["소총"]},
            {"label": "군인", "points": [[5, 6], [7, 8]], "시선방향": "측면", "무장여부": False},
        ]
        _, annotation = main.parse_annotation(self.write_json(value=value))
        self.assertEqual(annotation["class_counts"], {"soldier": 2})
        self.assertEqual(annotation["objects"][0]["weapon_types"], ["rifle"])
        self.assertIs(annotation["objects"][1]["armed"], False)

    def test_relative_stem_and_ambiguity(self):
        nested = cfg.IMAGE_DIR / "nested"
        nested.mkdir()
        image = nested / "sample.png"
        image.write_bytes(b"matching only")
        matcher = main.ImageMatcher(cfg.IMAGE_DIR)
        annotation = cfg.JSON_DIR / "nested" / "sample.json"
        self.assertEqual(matcher.resolve(annotation), image)
        with self.assertRaises(FileNotFoundError):
            matcher.resolve(cfg.JSON_DIR / "sample.json")
        (nested / "sample.jpg").write_bytes(b"second matching file")
        matcher = main.ImageMatcher(cfg.IMAGE_DIR)
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            matcher.resolve(annotation)

    def test_nested_annotation_falls_back_to_flat_image(self):
        stem = "20240528_101454-frame-003225"
        annotation = cfg.JSON_DIR / "20240528" / f"{stem}.json"
        image = cfg.IMAGE_DIR / f"{stem}.png"
        image.touch()
        self.assertEqual(main.ImageMatcher(cfg.IMAGE_DIR).resolve(annotation), image)

        (cfg.IMAGE_DIR / f"{stem}.jpg").touch()
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            main.ImageMatcher(cfg.IMAGE_DIR).resolve(annotation)

    def test_image_conversion_and_validation(self):
        bmp = cfg.IMAGE_DIR / "sample.bmp"
        Image.new("RGB", (3, 3)).save(bmp)
        self.assertTrue(main.image_data_url(bmp).startswith("data:image/png;base64,"))
        bmp.write_bytes(b"broken image")
        with self.assertRaises(OSError):
            main.image_data_url(bmp)

    def test_external_folder_reads_nested_json_and_relative_image(self):
        source = self.root / "SSD 데이터" / "1차 납품" / "01-17-27-52"
        nested = source / "nested"
        nested.mkdir(parents=True)
        (nested / "sample.json").write_text(json.dumps(fixture("sample.png")), encoding="utf-8")
        Image.new("RGB", (3, 3)).save(nested / "sample.png")
        # A same-named image elsewhere must not override the annotation-relative path.
        (source / "sample.png").write_bytes(b"invalid image")
        client = MagicMock()
        client.responses.create = AsyncMock(return_value=response())
        client.close = AsyncMock()
        with patch.multiple(cfg, IMAGE_DIR=source, JSON_DIR=source), patch("description_generation.main.AsyncOpenAI", return_value=client):
            self.assertEqual(main.run(), 0)
        client.responses.create.assert_awaited_once()
        self.assertEqual(len(list(source.rglob("*"))), 4)

    def test_missing_input_folder_is_not_created(self):
        missing = self.root / "disconnected_ssd"
        with patch.object(cfg, "IMAGE_DIR", missing), self.assertRaises(FileNotFoundError):
            main.run()
        self.assertFalse(missing.exists())

    def test_excluded_json_and_excel_are_not_processed(self):
        self.write_json("1ST_TEST.json", fixture("excluded.png"))
        nested = cfg.JSON_DIR / "nested"
        nested.mkdir()
        (nested / "1st_test.json").write_text("invalid JSON", encoding="utf-8")
        (cfg.JSON_DIR / "report.xlsx").write_bytes(b"not an input")
        with patch.object(cfg, "EXCLUDED_JSON_FILES", {"1st_test.json"}), patch("description_generation.main.AsyncOpenAI") as constructor:
            self.assertEqual(main.run(), 0)
            constructor.assert_not_called()

    @patch("description_generation.main.asyncio.sleep")
    def test_empty_response_retry_and_combined_input(self, sleep):
        client = MagicMock()
        client.responses.create = AsyncMock()
        client.close = AsyncMock()
        client.responses.create.side_effect = [response(" "), response()]
        _, annotation = main.parse_annotation(self.write_json())
        description = asyncio.run(main.generate_description(client, annotation, "data:image/png;base64,AAAA"))
        self.assertTrue(description.startswith("One tank"))
        self.assertEqual(client.responses.create.call_count, 2)
        request = client.responses.create.call_args.kwargs
        self.assertEqual([item["type"] for item in request["input"][0]["content"]], ["input_text", "input_image"])
        self.assertIn('"valid":false', request["input"][0]["content"][0]["text"])
        self.assertFalse(request["store"])
        sleep.assert_called_once()

    @patch("description_generation.main.asyncio.sleep")
    def test_rate_limit_retry_and_permanent_error(self, sleep):
        client = MagicMock()
        client.responses.create = AsyncMock()
        client.close = AsyncMock()
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        limit = RateLimitError("test", response=httpx.Response(429, request=request), body=None)
        client.responses.create.side_effect = [limit, response()]
        asyncio.run(main.generate_description(client, {}, "data:image/png;base64,AAAA"))
        self.assertEqual(client.responses.create.call_count, 2)
        client.reset_mock()
        client.responses.create.side_effect = BadRequestError("test", response=httpx.Response(400, request=request), body=None)
        with self.assertRaises(BadRequestError):
            asyncio.run(main.generate_description(client, {}, "data:image/png;base64,AAAA"))
        self.assertEqual(client.responses.create.call_count, 1)

    @patch("description_generation.main.asyncio.sleep")
    def test_exhausted_empty_response_and_format_validation(self, sleep):
        client = MagicMock()
        client.responses.create = AsyncMock()
        client.close = AsyncMock()
        client.responses.create.return_value = response("")
        with self.assertRaises(main.InvalidDescription):
            asyncio.run(main.generate_description(client, {}, "data:image/png;base64,AAAA"))
        self.assertEqual(client.responses.create.call_count, cfg.MAX_ATTEMPTS)
        for text in ["Description: A tank.", "1. A tank.", "```A tank.```", "전차 한 대."]:
            with self.subTest(text=text), self.assertRaises(main.InvalidDescription):
                main.validate_description(text)

    @patch("description_generation.main.asyncio.sleep")
    def test_quota_errors_are_not_retried(self, sleep):
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        for code in main.QUOTA_CODES:
            with self.subTest(code=code):
                client = MagicMock()
                client.responses.create = AsyncMock()
                client.close = AsyncMock()
                error = RateLimitError("test", response=httpx.Response(429, request=request),
                                       body={"code": code, "type": "insufficient_quota"})
                client.responses.create.side_effect = error
                with self.assertRaises(RateLimitError):
                    asyncio.run(main.generate_description(client, {}, "data:image/png;base64,AAAA"))
                self.assertEqual(client.responses.create.call_count, 1)
                self.assertEqual(main.api_error_details(error), (code, "insufficient_quota"))
        sleep.assert_not_called()

    def test_retry_after_minimum_is_not_capped(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        error = RateLimitError("test", response=httpx.Response(429, request=request, headers={"Retry-After": "90"}),
                              body={"code": "rate_limit_exceeded", "type": "rate_limit_error"})
        self.assertEqual(main.retry_delay(error, 1), 90.0)
        error.response.headers["Retry-After"] = "invalid"
        self.assertGreater(main.retry_delay(error, 1), 0)

    def test_quota_error_blocks_later_requests_but_exports_all_rows(self):
        self.write_json("a.json", fixture("first.png"))
        self.write_json("b.json", fixture("second.png"))
        for name in ["a.png", "b.png"]:
            Image.new("RGB", (3, 3)).save(cfg.IMAGE_DIR / name)
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        client = MagicMock()
        client.responses.create = AsyncMock()
        client.close = AsyncMock()
        client.responses.create.side_effect = RateLimitError(
            "test", response=httpx.Response(429, request=request),
            body={"error": {"code": "insufficient_quota", "type": "insufficient_quota"}},
        )
        with patch("description_generation.main.AsyncOpenAI", return_value=client), patch("description_generation.main.asyncio.sleep") as sleep:
            self.assertEqual(main.run(), 1)
            sleep.assert_not_called()
        self.assertEqual(client.responses.create.call_count, 1)
        workbook = load_workbook(cfg.OUTPUT_FILE)
        try:
            rows = list(workbook["description"].values)
            self.assertEqual(rows[1:], [("a.png", None), ("b.png", None)])
        finally:
            workbook.close()

    def test_excel_original_paths_and_checkpoint_recovery(self):
        original = "=folder\\sample.png"
        self.assertTrue(main.save_excel([(original, "One tank is visible."), ("failed.png", "")]))
        workbook = load_workbook(cfg.OUTPUT_FILE)
        try:
            sheet = workbook["description"]
            self.assertEqual(tuple(cell.value for cell in sheet[1]), ("imagePath", "description"))
            self.assertEqual(sheet["A2"].value, original)
            self.assertEqual(sheet["A2"].data_type, "s")
        finally:
            workbook.close()
        with cfg.CHECKPOINT_FILE.open("w", encoding="utf-8") as handle:
            handle.write('{"interrupted":')
        job_key = "job:v2:" + "a" * 64
        main.append_checkpoint("recovered.png", "One soldier is standing.", job_key)
        results = main.load_results()
        self.assertEqual(results, {job_key: "One soldier is standing."})
        self.assertNotIn("failed.png", results)

    def test_pipeline_continues_then_resumes_without_api_calls(self):
        self.write_json("a_missing.json", fixture("missing.png"))
        self.write_json("b_good.json")
        (cfg.JSON_DIR / "d_corrupt.json").write_text("broken", encoding="utf-8")
        Image.new("RGB", (3, 3)).save(cfg.IMAGE_DIR / "b_good.png")
        client = MagicMock()
        client.responses.create = AsyncMock(return_value=response())
        client.close = AsyncMock()
        with patch("description_generation.main.AsyncOpenAI", return_value=client), self.assertLogs(main.LOGGER, level="ERROR") as logs:
            self.assertEqual(main.run(), 1)
        self.assertTrue(any("a_missing.json" in line and "Image not found" in line for line in logs.output))
        self.assertEqual(client.responses.create.call_count, 1)
        workbook = load_workbook(cfg.OUTPUT_FILE)
        try:
            self.assertEqual(list(workbook["description"].values),
                             [("imagePath", "description"), ("b_good.png", response().output_text)])
        finally:
            workbook.close()
        with patch("description_generation.main.AsyncOpenAI") as constructor:
            self.assertEqual(main.run(), 1)
            constructor.assert_not_called()

    def test_fresh_runs_call_api_for_every_annotation(self):
        self.write_json("a.json")
        self.write_json("b.json")
        for stem in ("a", "b"):
            Image.new("RGB", (3, 3)).save(cfg.IMAGE_DIR / f"{stem}.png")
        main.save_excel([("m1-1-001.png", "Old saved description.")])
        main.append_checkpoint("m1-1-001.png", "Old checkpoint description.")
        client = MagicMock()
        client.responses.create = AsyncMock()
        client.close = AsyncMock()
        descriptions = [f"One tank is visible in scene {number}." for number in range(4)]
        client.responses.create.side_effect = [response(text) for text in descriptions]
        with patch.object(cfg, "RESUME", False), patch("description_generation.main.AsyncOpenAI", return_value=client):
            self.assertEqual(main.run(), 0)
            self.assertEqual(main.run(), 0)
        self.assertEqual(client.responses.create.call_count, 4)
        workbook = load_workbook(cfg.OUTPUT_FILE)
        try:
            rows = list(workbook[cfg.SHEET_NAME].values)
            self.assertEqual([row[0] for row in rows[1:]], ["a.png", "b.png"])
            self.assertCountEqual([row[1] for row in rows[1:]], descriptions[2:])
        finally:
            workbook.close()

    def test_locked_excel_keeps_success_checkpoint(self):
        job_key = "job:v2:" + "b" * 64
        main.append_checkpoint("good.png", "One tank is visible.", job_key)
        with patch("description_generation.storage.os.replace", side_effect=PermissionError("locked")):
            self.assertFalse(main.save_excel([("good.png", "One tank is visible.")]))
        self.assertEqual(main.load_results()[job_key], "One tank is visible.")

    def test_concurrency_limit_and_output_order(self):
        for index in range(12):
            name = f"image{index:02}.png"
            self.write_json(f"image{index:02}.json", fixture(name))
            Image.new("RGB", (3, 3)).save(cfg.IMAGE_DIR / name)
        active = peak = 0
        all_active = asyncio.Event()

        async def create(**kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 10:
                all_active.set()
            await asyncio.wait_for(all_active.wait(), timeout=5)
            active -= 1
            return response()

        client = MagicMock()
        client.responses.create = AsyncMock(side_effect=create)
        client.close = AsyncMock()
        with patch("description_generation.main.AsyncOpenAI", return_value=client):
            self.assertEqual(main.run(), 0)
        self.assertEqual(peak, 10)
        self.assertEqual(client.responses.create.await_count, 12)
        workbook = load_workbook(cfg.OUTPUT_FILE)
        try:
            self.assertEqual([row[0] for row in list(workbook[cfg.SHEET_NAME].values)[1:]],
                             [f"image{index:02}.png" for index in range(12)])
        finally:
            workbook.close()

    def test_progress_estimates_remaining_time(self):
        with self.assertLogs(main.LOGGER, level="INFO") as logs:
            main.log_progress(0, 10, 0)
            main.log_progress(4, 10, 20)
            main.log_progress(10, 10, 50)
        self.assertIn("계산 중", logs.output[0])
        self.assertIn("처리 완료 4/10 (40.0%)", logs.output[1])
        self.assertIn("남은 6건", logs.output[1])
        self.assertIn("예상 남은 시간 00:00:30", logs.output[1])
        self.assertIn("예상 남은 시간 00:00:00", logs.output[2])
        self.assertEqual(main.format_duration(3661), "01:01:01")

    def test_twenty_and_fifty_workers_and_single_excel_save(self):
        for count in (20, 50):
            with self.subTest(workers=count):
                for index in range(55):
                    name = f"{index:02}.png"
                    self.write_json(f"{index:02}.json", fixture(name))
                    Image.new("RGB", (3, 3)).save(cfg.IMAGE_DIR / name)
                active = peak = 0
                all_active = asyncio.Event()

                async def create(**kwargs):
                    nonlocal active, peak
                    active += 1
                    peak = max(peak, active)
                    if active == count:
                        all_active.set()
                    # Synchronize the first batch instead of depending on disk speed.
                    await asyncio.wait_for(all_active.wait(), timeout=5)
                    active -= 1
                    return response()

                client = MagicMock()
                client.responses.create = AsyncMock(side_effect=create)
                client.close = AsyncMock()
                with patch.multiple(cfg, MAX_CONCURRENT_REQUESTS=count, RESUME=False), \
                        patch("description_generation.main.AsyncOpenAI", return_value=client), \
                        patch("description_generation.main.save_excel", wraps=main.save_excel) as save:
                    self.assertEqual(main.run(), 0)
                    save.assert_called_once()
                self.assertEqual(peak, count)
                self.assertEqual(client.responses.create.await_count, 55)
        with patch.object(cfg, "MAX_CONCURRENT_REQUESTS", 51), self.assertRaises(ValueError):
            main.run()

    def test_interruption_checkpoint_then_resume(self):
        for index in range(3):
            self.write_json(f"{index}.json", fixture(f"{index}.png"))
            Image.new("RGB", (3, 3)).save(cfg.IMAGE_DIR / f"{index}.png")
        client = MagicMock()
        client.responses.create = AsyncMock(side_effect=[response(), asyncio.CancelledError()])
        client.close = AsyncMock()
        with patch.object(cfg, "MAX_CONCURRENT_REQUESTS", 1), \
                patch("description_generation.main.AsyncOpenAI", return_value=client), patch("description_generation.main.save_excel") as save:
            self.assertEqual(main.run(), 130)
            save.assert_not_called()
        self.assertEqual(len(main.load_results()), 1)
        self.assertTrue(next(iter(main.load_results())).startswith("job:v2:"))
        client.responses.create = AsyncMock(return_value=response())
        with patch("description_generation.main.AsyncOpenAI", return_value=client), patch("description_generation.main.save_excel", wraps=main.save_excel) as save:
            self.assertEqual(main.run(), 0)
            save.assert_called_once()
        self.assertEqual(client.responses.create.await_count, 2)

    def test_conflicting_paths_are_not_reused_and_resume_separately(self):
        self.write_json("a.json")
        changed = fixture()
        changed["shapes"][0]["시선방향"] = "정면"
        self.write_json("b.json", changed)
        for stem in ("a", "b"):
            Image.new("RGB", (3, 3)).save(cfg.IMAGE_DIR / f"{stem}.png")
        main.append_checkpoint("m1-1-001.png", "An old ambiguous description.")
        client = MagicMock()
        client.responses.create = AsyncMock(side_effect=[response("A tank faces left."), response("A tank faces forward.")])
        client.close = AsyncMock()
        with patch("description_generation.main.AsyncOpenAI", return_value=client):
            self.assertEqual(main.run(), 0)
        self.assertEqual(client.responses.create.await_count, 2)
        with patch("description_generation.main.AsyncOpenAI") as constructor:
            self.assertEqual(main.run(), 0)
            constructor.assert_not_called()

    def test_split_roots_ignore_old_json_and_match_nested_stems(self):
        for folder, color in [("one", "red"), ("two/deeper", "blue")]:
            image_dir = cfg.IMAGE_DIR / folder
            label_dir = cfg.JSON_DIR / folder
            image_dir.mkdir(parents=True)
            label_dir.mkdir(parents=True)
            Image.new("RGB", (3, 3), color).save(image_dir / "same.png")
            (image_dir / "same.json").write_text("invalid old JSON", encoding="utf-8")
            value = fixture(r"Z:\obsolete\wrong-name.jpg")
            value["marker"] = folder
            (label_dir / "same.json").write_text(json.dumps(value), encoding="utf-8")
        (cfg.IMAGE_DIR / "only_old.json").write_text("invalid", encoding="utf-8")
        captured = []

        async def generate(client, annotation, image_url, *args):
            marker = annotation["metadata"]["marker"]
            matched = cfg.IMAGE_DIR / marker / "same.png"
            self.assertEqual(image_url, main.image_data_url(matched))
            captured.append(marker)
            return "A tank is visible in " + marker.replace("/", " ") + "."

        client = MagicMock()
        client.close = AsyncMock()
        with patch("description_generation.main.AsyncOpenAI", return_value=client), \
                patch("description_generation.main.generate_description", side_effect=generate), \
                patch("description_generation.main.parse_annotation", wraps=main.parse_annotation) as parse:
            self.assertEqual(main.run(), 0)
        self.assertEqual(set(captured), {"one", "two/deeper"})
        self.assertEqual(parse.call_count, 2)
        self.assertTrue(all(call.args[0].is_relative_to(cfg.JSON_DIR) for call in parse.call_args_list))
        workbook = load_workbook(cfg.OUTPUT_FILE)
        try:
            rows = list(workbook[cfg.SHEET_NAME].values)
            self.assertEqual(rows, [("imagePath", "description"),
                ("one/same.png", "A tank is visible in one."),
                ("two/deeper/same.png", "A tank is visible in two deeper.")])
        finally:
            workbook.close()

    def test_resume_invalidated_by_json_image_or_dataset_changes(self):
        path = self.write_json("sample.json")
        image = cfg.IMAGE_DIR / "sample.png"
        Image.new("RGB", (3, 3)).save(image)
        main.save_excel([("sample.png", "An old Excel caption.")])
        main.append_checkpoint("sample.png", "An old checkpoint caption.")
        main.append_checkpoint("sample.png", "An old scoped caption.", "json:" + str(path))
        client = MagicMock()
        client.responses.create = AsyncMock(return_value=response())
        client.close = AsyncMock()
        with patch("description_generation.main.AsyncOpenAI", return_value=client):
            self.assertEqual(main.run(), 0)
            self.assertEqual(client.responses.create.await_count, 1)
            self.assertEqual(main.run(), 0)
            self.assertEqual(client.responses.create.await_count, 1)
            value = fixture()
            value["shapes"][0]["points"] = [[1, 2], [3, 4]]
            self.write_json("sample.json", value)
            self.assertEqual(main.run(), 0)
            self.assertEqual(client.responses.create.await_count, 2)
            Image.new("RGB", (3, 3), "red").save(image)
            self.assertEqual(main.run(), 0)
            self.assertEqual(client.responses.create.await_count, 3)
            other = self.root / "another_dataset"
            other_images, other_labels = other / "images", other / "labels_fixed"
            other_images.mkdir(parents=True)
            other_labels.mkdir()
            (other_images / image.name).write_bytes(image.read_bytes())
            (other_labels / path.name).write_bytes(path.read_bytes())
            with patch.multiple(cfg, IMAGE_DIR=other_images, JSON_DIR=other_labels):
                self.assertEqual(main.run(), 0)
            self.assertEqual(client.responses.create.await_count, 4)

    def test_ambiguous_match_logs_error_and_other_jobs_continue(self):
        for name in ("ambiguous", "good"):
            self.write_json(name + ".json")
            Image.new("RGB", (3, 3)).save(cfg.IMAGE_DIR / (name + ".png"))
        Image.new("RGB", (3, 3)).save(cfg.IMAGE_DIR / "ambiguous.jpg")
        client = MagicMock()
        client.responses.create = AsyncMock(return_value=response())
        client.close = AsyncMock()
        with patch("description_generation.main.AsyncOpenAI", return_value=client), self.assertLogs(main.LOGGER, level="ERROR") as logs:
            self.assertEqual(main.run(), 1)
        self.assertEqual(client.responses.create.await_count, 1)
        self.assertTrue(any("Ambiguous image" in line and "ambiguous.json" in line for line in logs.output))

    def test_hashing_is_lazy_and_keeps_event_loop_responsive(self):
        for index in range(3):
            self.write_json(f"{index}.json", fixture(f"{index}.png"))
            Image.new("RGB", (3, 3)).save(cfg.IMAGE_DIR / f"{index}.png")
        hash_started = threading.Event()
        release_hash = threading.Event()
        hashed = []
        original = main.scoped_resume_keys

        def fingerprint(files, matcher):
            self.assertEqual(len(files), 1)
            if not hashed:
                hash_started.set()
                self.assertTrue(release_hash.wait(timeout=5), "Hashing blocked the event loop")
            hashed.append(files[0].stem)
            return original(files, matcher)

        async def create(**kwargs):
            if client.responses.create.await_count == 1:
                self.assertEqual(hashed, ["0"], "All files were hashed before the first API call")
            return response()

        client = MagicMock()
        client.responses.create = AsyncMock(side_effect=create)
        client.close = AsyncMock()

        async def exercise():
            task = asyncio.create_task(main.run_async())
            try:
                async with asyncio.timeout(5):
                    while not hash_started.is_set():
                        await asyncio.sleep(.01)
                self.assertFalse(task.done())
                release_hash.set()
                return await task
            finally:
                release_hash.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        with patch.object(cfg, "MAX_CONCURRENT_REQUESTS", 1), \
                patch("description_generation.main.scoped_resume_keys", side_effect=fingerprint), \
                patch("description_generation.main.AsyncOpenAI", return_value=client), \
                self.assertLogs(main.LOGGER, level="INFO") as logs:
            self.assertEqual(asyncio.run(exercise()), 0)
        self.assertEqual(hashed, ["0", "1", "2"])
        self.assertEqual(client.responses.create.await_count, 3)
        for message in ("JSON 탐색 시작", "JSON 탐색 완료", "이미지 목록 생성 시작", "이미지 목록 생성 완료", "작업 처리 시작"):
            self.assertTrue(any(message in line for line in logs.output), message)

    def test_usage_and_api_failure_statistics(self):
        client = MagicMock()
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        error = RateLimitError("test", response=httpx.Response(429, request=request), body=None)
        result = response()
        result.usage = SimpleNamespace(input_tokens=123, output_tokens=45)
        client.responses.create = AsyncMock(side_effect=[error, result])
        stats = main.RunStats()
        limiter = MagicMock()
        limiter.acquire = AsyncMock()
        limiter.cooldown = AsyncMock()
        with patch("description_generation.main.wait_before_retry", new=AsyncMock()):
            asyncio.run(main.generate_description(client, {}, "data:image/png;base64,AAAA", limiter=limiter, stats=stats))
        self.assertEqual((stats.active, stats.calls, stats.errors_429, stats.retries), (0, 2, 1, 1))
        self.assertEqual((stats.input_tokens, stats.output_tokens, stats.usage_responses), (123, 45, 1))
        self.assertEqual(limiter.acquire.await_count, 2)
        limiter.cooldown.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

