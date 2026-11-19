import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

from description_merge.main import main


class DescriptionMergeTests(unittest.TestCase):
    def test_cli_updates_by_basename_and_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "부모 파일.xlsx"
            child = root / "설명 값.xlsx"
            for path, rows in (
                (parent, [("IMAGEPATH", "DESCRIPTNION"), (r"old\a.PNG", "before"),
                          ("b.png", "keep")]),
                (child, [("imagePath", "description"), ("new/a.png", "updated"),
                         ("b.png", "  ")]),
            ):
                workbook = Workbook()
                for row in rows:
                    workbook.active.append(row)
                workbook.save(path)
                workbook.close()

            originals = [path.read_bytes() for path in (parent, child)]
            with patch("builtins.input", side_effect=[f'"{parent}"', f'"{child}"', ""]), \
                    patch("builtins.print"):
                self.assertEqual(main(), 0)

            output = load_workbook(root / "부모 파일_updated.xlsx", read_only=True)
            try:
                self.assertEqual(list(output.active.values), [
                    ("IMAGEPATH", "DESCRIPTNION"), (r"old\a.PNG", "updated"), ("b.png", "keep"),
                ])
            finally:
                output.close()
            self.assertEqual([path.read_bytes() for path in (parent, child)], originals)
