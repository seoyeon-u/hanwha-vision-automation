import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fp_labeling.extraction import extract


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "한글 입력"
        self.source.mkdir()
        self.output = self.root / "검수 대상"

    def write_pair(self, directory, stem, payload, suffix=".png"):
        image = directory / f"{stem}{suffix}"
        annotation = directory / f"{stem}.json"
        image.write_bytes(b"image")
        annotation.write_text(payload, encoding="utf-8")
        return image, annotation

    def test_quoted_paths_folder_deduplication_and_csv(self):
        image, annotation = self.write_pair(self.source, "keep", '{"shapes":[{}]}')
        self.write_pair(self.source, "empty", '{"shapes":[]}')
        self.write_pair(self.source, "invalid", '{"shapes":true}')
        self.write_pair(self.source, "missing_key", '{}')
        (self.source / "orphan.jpg").touch()
        inputs = f'"{annotation}"\n"{image}"\n"{self.source}"'
        stats, _, log = extract(inputs, self.output, lambda *_: None)

        self.assertEqual(stats["copied"], 1)
        self.assertEqual(stats["empty"], 1)
        self.assertEqual(stats["json_errors"], 1)
        self.assertEqual(stats["missing_shapes"], 1)
        self.assertEqual(stats["missing"], 1)
        self.assertEqual((self.output / image.name).read_bytes(), image.read_bytes())
        self.assertEqual((self.output / annotation.name).read_bytes(), annotation.read_bytes())
        with log.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertCountEqual([row["status"] for row in rows],
                              ["copied", "excluded", "error", "error", "error"])

    def test_collision_and_failed_copy_leave_no_partial_pair(self):
        _, annotation = self.write_pair(self.source, "same", '{"shapes":[{}]}')
        other = self.root / "other"
        other.mkdir()
        self.write_pair(other, "same", '{"shapes":[{},{}]}', ".jpg")
        stats, _, _ = extract(f"{self.source}\n{other}", self.output, lambda *_: None)
        self.assertEqual(stats["collisions"], 1)
        self.assertFalse((self.output / "same.jpg").exists())
        self.assertEqual((self.output / "same.json").read_bytes(), annotation.read_bytes())

        failed = self.root / "failed"
        with patch("fp_labeling.extraction.shutil.copy2", side_effect=[None, PermissionError]):
            stats, _, _ = extract(str(self.source), failed, lambda *_: None)
        self.assertEqual(stats["copy_errors"], 1)
        self.assertEqual([path.suffix for path in failed.iterdir()], [".csv"])
