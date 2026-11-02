import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from multi_weapon_review.main import (
    HEADERS,
    WORKSHEET_NAME,
    review_paths,
    write_workbook,
)


class MultiWeaponReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def test_extracts_only_multiple_values_and_classifies_duplicates(self):
        path = self.write_json(
            self.root / "folder" / "data.json",
            {
                "imagePath": r"images\frame-001.png",
                "shapes": [
                    {"label": "군인", "무기타입": "원격무장_1"},
                    {"label": "군인", "무기타입": "원격무장_1,원격무장_2"},
                    {"label": "전차", "무기타입": "포/포탑_1,원격무장_1"},
                    {"label": "군인", "무기타입": "소총_1,소총_2"},
                    {"label": "전차", "무기타입": "포/포탑_1"},
                    {"label": "군인", "무기타입": None},
                    {"label": "군인", "무기타입": ""},
                    {"label": "장갑차", "무기타입": ["소총_1", "포/포탑_1", "원격무장_1"]},
                    {"label": "장갑차", "무기타입": "소총_1,소총_2,원격무장_1"},
                    {"label": "장갑차", "무기타입": "None"},
                ],
            },
        )
        result = review_paths([path], max_workers=1)
        self.assertEqual(len(result.items), 5)
        self.assertEqual([item.object_number for item in result.items], [2, 3, 4, 8, 9])
        self.assertEqual(result.items[0].duplicate_status, "동일 무기타입 중복 의심")
        self.assertEqual(result.items[1].duplicate_status, "서로 다른 복수 무기타입")
        self.assertEqual(result.items[2].duplicate_status, "동일 무기타입 중복 의심")
        self.assertEqual(result.items[3].weapon_count, 3)
        self.assertEqual(result.items[4].duplicate_status, "중복 및 복수 무기타입")
        self.assertEqual(result.items[0].image_filename, "frame-001.png")

    def test_array_entries_preserve_raw_value_and_accept_utf8_bom(self):
        path = self.root / "bom.json"
        path.write_text(
            json.dumps(
                {"shapes": [{"label": "군인", "무기타입": ["소총_1", "소총_2"]}]},
                ensure_ascii=False,
            ),
            encoding="utf-8-sig",
        )
        result = review_paths([path])
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].weapon_value, '["소총_1","소총_2"]')
        self.assertEqual(result.items[0].weapon_count, 2)

    def test_scans_nested_folders_and_deduplicates_overlapping_inputs(self):
        nested = self.root / "top" / "nested"
        file_path = self.write_json(
            nested / "data.json",
            {"shapes": [{"label": "차량", "무기타입": "소총_1,대전차화기_1"}]},
        )
        result = review_paths([self.root / "top", file_path, nested, nested])
        self.assertEqual(result.total_json_files, 1)
        self.assertEqual(len(result.items), 1)

    def test_accepts_a_standalone_json_file(self):
        path = self.write_json(
            self.root / "standalone.json",
            {"shapes": [{"label": "차량", "무기타입": "소총_1,원격무장_1"}]},
        )
        result = review_paths([path, path])
        self.assertEqual(result.total_json_files, 1)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].json_filename, "standalone.json")

    def test_bad_json_missing_shapes_and_missing_path_are_logged_without_abort(self):
        folder = self.root / "broken"
        folder.mkdir()
        (folder / "bad.json").write_text("{ invalid", encoding="utf-8")
        self.write_json(folder / "missing-shapes.json", {"imagePath": "x.png"})
        result = review_paths([folder, self.root / "not-found"])
        self.assertEqual(result.total_json_files, 2)
        self.assertEqual(result.readable_json_files, 1)
        self.assertEqual(len(result.errors), 3)
        self.assertTrue(any("shapes 필드" in item["오류 내용"] for item in result.errors))

    def test_handles_many_files_and_reports_progress(self):
        folder = self.root / "many"
        for index in range(1000):
            self.write_json(
                folder / f"{index:04d}.json",
                {"shapes": [{"label": "군인", "무기타입": "소총_1,대전차화기_1"}]},
            )
        progress = []
        result = review_paths([folder], progress_callback=progress.append, max_workers=4)
        self.assertEqual(result.total_json_files, 1000)
        self.assertEqual(result.readable_json_files, 1000)
        self.assertEqual(len(result.items), 1000)
        self.assertTrue(progress)
        self.assertEqual(progress[-1], 1000)

    def test_workbook_headers_hyperlinks_and_empty_output(self):
        path = self.write_json(
            self.root / "data.json",
            {
                "imagePath": "frame.png",
                "shapes": [{"label": "군인", "무기타입": "소총_1,원격무장_1"}],
            },
        )
        result = review_paths([path])
        output = write_workbook(result, self.root / "review.xlsx")
        workbook = load_workbook(output)
        sheet = workbook[WORKSHEET_NAME]
        self.assertEqual([cell.value for cell in sheet[1]], HEADERS)
        self.assertEqual(sheet["E2"].value, 1)
        self.assertEqual(sheet["K2"].value, "미검수")
        self.assertIsNotNone(sheet["C2"].hyperlink)
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertTrue(sheet.auto_filter.ref.startswith("A1:L"))

        empty_result = review_paths([self.root / "empty"])
        empty_output = write_workbook(empty_result, self.root / "empty-review.xlsx")
        empty_sheet = load_workbook(empty_output)[WORKSHEET_NAME]
        self.assertEqual([cell.value for cell in empty_sheet[1]], HEADERS)
        self.assertEqual(empty_sheet.max_row, 1)


if __name__ == "__main__":
    unittest.main()
