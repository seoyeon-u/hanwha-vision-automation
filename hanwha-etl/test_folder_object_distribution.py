import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from folder_object_distribution import (
    HEADERS,
    WEAPON_BBOX_WORKSHEET_NAME,
    WORKSHEET_NAME,
    analyze_paths,
    write_workbook,
)


class FolderObjectDistributionTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def write_json(self, path, data, encoding="utf-8"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding=encoding)
        return path

    def test_five_file_expected_distribution_and_no_images(self):
        folder = self.root / "샘플 폴더"
        for index in range(5):
            shapes = [
                {
                    "label": "소형전술차량",
                    "무장여부": True,
                    "무기타입": "원격무장_1",
                }
            ]
            if index < 3:
                shapes.append({"label": "민간차량", "무장여부": False, "무기타입": None})
            self.write_json(
                folder / f"sample-{index}.json",
                {"shapes": shapes, "imagePath": f"missing-{index}.png"},
            )

        result = analyze_paths([folder])
        self.assertEqual(len(result.folders), 1)
        summary = result.folders[0]
        self.assertEqual(summary.json_count, 5)
        self.assertEqual(summary.image_count, 0)
        self.assertEqual(summary.counts["소형전술차량"], 5)
        self.assertEqual(summary.counts["민간차량"], 3)
        self.assertEqual(summary.counts["원격무장"], 0)
        self.assertEqual(result.total_objects, 8)
        for label in ("민간인", "군인", "전차", "자주포", "장갑차", "소총", "대전차화기", "포/포탑"):
            self.assertEqual(summary.counts[label], 0)

    def test_nested_folders_duplicate_paths_and_images(self):
        first = self.root / "top" / "same"
        second = self.root / "top" / "child" / "same"
        file_one = self.write_json(first / "one.json", {"shapes": []})
        self.write_json(second / "two.JSON", {"shapes": []})
        (first / "one.png").write_bytes(b"image")

        result = analyze_paths([self.root / "top", file_one, first])
        self.assertEqual(len(result.folders), 2)
        self.assertEqual(result.total_json_files, 2)
        self.assertEqual(result.total_images, 1)
        self.assertEqual(len({folder.display_path for folder in result.folders}), 2)
        self.assertTrue(any("child" in folder.display_path for folder in result.folders))

    def test_parallel_workers_match_sequential_results(self):
        folder = self.root / "parallel"
        for index in range(24):
            self.write_json(
                folder / f"{index:02d}.json",
                {
                    "shapes": [
                        {"label": "군인 > 소총", "무기타입": "소총_1"},
                        {"label": "원격무장", "무기타입": None},
                    ]
                },
            )
        (folder / "bad.json").write_text("{ invalid", encoding="utf-8")

        sequential = analyze_paths([folder], max_workers=1)
        parallel = analyze_paths([folder], max_workers=4)
        self.assertEqual(sequential.total_json_files, parallel.total_json_files)
        self.assertEqual(sequential.total_objects, parallel.total_objects)
        self.assertEqual(sequential.total_images, parallel.total_images)
        self.assertEqual(sequential.error_json_count, parallel.error_json_count)
        self.assertEqual(
            [dict(item.counts) for item in sequential.folders],
            [dict(item.counts) for item in parallel.folders],
        )
        self.assertEqual(
            sequential.independent_weapon_bboxes,
            parallel.independent_weapon_bboxes,
        )

    def test_independent_weapon_bbox_details_match_counts_and_source_paths(self):
        first_folder = self.root / "검수 완료" / "폴더 A"
        second_folder = self.root / "검수 완료" / "폴더 B"
        first_file = self.write_json(
            first_folder / "frame 001.json",
            {
                "imagePath": r"images\not-present.png",
                "shapes": [
                    {"label": "군인", "무기타입": "소총_1", "points": [[0, 0], [1, 1]]},
                    {"label": "전차", "무기타입": "포/포탑_1", "points": [[2, 2], [3, 3]]},
                    {"label": "군인>소총", "points": [[4, 4], [5, 5]]},
                    {"label": "소총", "points": [[10, 11], [20, 21]]},
                    {"label": "소총", "points": [[30, 31], [40, 41]]},
                    {"label": "소총", "points": [[50, 51], [60, 61]]},
                    {"label": "대전차화기", "points": [[70, 71], [80, 81]]},
                    {"label": "원격무장", "points": [[90, 91], [100, 101]]},
                    {"label": "포/포탑", "points": [[110, 111], [120, 121]]},
                ],
            },
        )
        second_file = self.write_json(
            second_folder / "frame 002.json",
            {
                "imagePath": "missing-image.png",
                "shapes": [{"label": "소총", "points": [[1, 2], [3, 4]]}],
            },
        )

        result = analyze_paths([self.root / "검수 완료"])
        self.assertEqual(result.total_json_files, 2)
        self.assertEqual(len(result.folders), 2)
        folder_counts = {folder.path: folder.counts for folder in result.folders}
        self.assertEqual(folder_counts[first_folder.resolve()]["군인"], 2)
        self.assertEqual(folder_counts[first_folder.resolve()]["전차"], 1)
        self.assertEqual(folder_counts[first_folder.resolve()]["소총"], 3)
        self.assertEqual(folder_counts[first_folder.resolve()]["대전차화기"], 1)
        self.assertEqual(folder_counts[first_folder.resolve()]["원격무장"], 1)
        self.assertEqual(folder_counts[first_folder.resolve()]["포/포탑"], 1)
        self.assertEqual(folder_counts[second_folder.resolve()]["소총"], 1)

        details = result.independent_weapon_bboxes
        self.assertEqual(len(details), 7)
        self.assertEqual(
            sum(folder.counts[label] for folder in result.folders for label in (
                "소총", "대전차화기", "원격무장", "포/포탑"
            )),
            len(details),
        )
        self.assertEqual(
            [detail.bbox_index for detail in details if detail.json_path == first_file.resolve()],
            [4, 5, 6, 7, 8, 9],
        )
        self.assertEqual(details[0].folder_path, str(first_folder.resolve()))
        self.assertEqual(details[0].image_path, r"images\not-present.png")
        self.assertEqual(details[0].bbox_coordinates, "[[10,11],[20,21]]")
        self.assertTrue(all(detail.json_path.is_absolute() for detail in details))
        self.assertEqual(details[-1].json_path, second_file.resolve())

        output = write_workbook(result, self.root / "details.xlsx")
        workbook = load_workbook(output)
        sheet = workbook[WEAPON_BBOX_WORKSHEET_NAME]
        self.assertEqual(
            [cell.value for cell in sheet[1]],
            ["번호", "폴더 경로", "무기 객체 유형", "JSON 파일명", "JSON 파일 전체 경로", "이미지 파일명", "BBox 인덱스", "BBox 좌표"],
        )
        self.assertEqual(sheet.max_row - 1, 7)
        self.assertEqual(sheet["E2"].value, str(first_file.resolve()))
        self.assertIsNotNone(sheet["E2"].hyperlink)
        self.assertEqual(sheet["F2"].value, r"images\not-present.png")
        self.assertEqual(sheet["G2"].value, 4)

    def test_weapon_attributes_do_not_create_detail_rows_and_empty_sheet_has_header(self):
        path = self.write_json(
            self.root / "attributes-only" / "attributes.json",
            {
                "shapes": [
                    {"label": "군인", "무기타입": "소총_1"},
                    {"label": "전차", "무기타입": "포/포탑_1,원격무장_1"},
                    {"label": "군인>소총", "무기타입": "소총_1"},
                ]
            },
        )
        result = analyze_paths([path])
        self.assertEqual(result.folders[0].counts["군인"], 2)
        self.assertEqual(result.folders[0].counts["전차"], 1)
        self.assertEqual(sum(result.folders[0].counts[label] for label in (
            "소총", "대전차화기", "원격무장", "포/포탑"
        )), 0)
        self.assertEqual(result.independent_weapon_bboxes, [])

        output = write_workbook(result, self.root / "no-details.xlsx")
        workbook = load_workbook(output)
        sheet = workbook[WEAPON_BBOX_WORKSHEET_NAME]
        self.assertEqual(sheet.max_row, 1)
        self.assertEqual(sheet["A1"].value, "번호")
        self.assertEqual(sheet["H1"].value, "BBox 좌표")

    def test_bbox_representative_label_only_and_hierarchical_labels(self):
        path = self.write_json(
            self.root / "weapons" / "weapons.json",
            {
                "shapes": [
                    {"label": "군인", "무기타입": "소총_1"},
                    {"label": "군인", "무기타입": "소총_1"},
                    {"label": "소총"},
                    {"label": "전차", "무기타입": "포/포탑_1,원격무장_1"},
                    {"label": "원격무장", "무기타입": None},
                    {"label": "군인 > 소총", "무기타입": "소총_1"},
                    {"label": "알수없는 객체", "무기타입": "대전차화기_1"},
                ]
            },
        )
        result = analyze_paths([path])
        counts = result.folders[0].counts
        self.assertEqual(counts["군인"], 3)
        self.assertEqual(counts["소총"], 1)
        self.assertEqual(counts["전차"], 1)
        self.assertEqual(counts["원격무장"], 1)
        self.assertEqual(counts["대전차화기"], 0)
        self.assertEqual(counts["포/포탑"], 0)
        self.assertEqual(result.total_objects, 6)
        self.assertEqual(
            sum(counts[label] for label in (
                "민간인", "군인", "민간차량", "소형전술차량", "전차", "자주포",
                "장갑차", "소총", "대전차화기", "원격무장", "포/포탑",
            )),
            result.total_objects,
        )
        self.assertTrue(
            any("인식되지 않는 대표 label" in error["오류 또는 확인 필요 사유"] for error in result.errors)
        )

    def test_bad_json_missing_shapes_unknown_label_and_utf8_bom(self):
        folder = self.root / "edge cases"
        folder.mkdir()
        (folder / "bad.json").write_text("{ broken", encoding="utf-8")
        self.write_json(folder / "missing.json", {"imagePath": None})
        bom_path = folder / "bom.json"
        bom_path.write_text(
            json.dumps(
                {"shapes": [{"label": "미등록 객체", "무기타입": None, "무장여부": False}]},
                ensure_ascii=False,
            ),
            encoding="utf-8-sig",
        )

        result = analyze_paths([folder, self.root / "does-not-exist"])
        self.assertEqual(result.total_json_files, 2)
        self.assertEqual(result.error_json_count, 3)
        reasons = "\n".join(error["오류 또는 확인 필요 사유"] for error in result.errors)
        self.assertIn("JSON 파일을 읽을 수 없습니다", reasons)
        self.assertIn("shapes 필드", reasons)
        self.assertIn("인식되지 않는 대표 label", reasons)
        self.assertIn("경로를 찾을 수 없거나 접근", reasons)

    def test_workbook_headers_totals_and_error_log(self):
        self.write_json(
            self.root / "output" / "data.json",
            {"shapes": [{"label": "전차", "무장여부": False, "무기타입": None}]},
        )
        result = analyze_paths([self.root / "output"])
        output = write_workbook(result, self.root / "result.xlsx")
        workbook = load_workbook(output, data_only=True)
        self.assertEqual(workbook.sheetnames, [WORKSHEET_NAME, WEAPON_BBOX_WORKSHEET_NAME])
        sheet = workbook[WORKSHEET_NAME]
        self.assertEqual([cell.value for cell in sheet[1]], HEADERS)
        self.assertEqual(sheet["H2"].value, 1)
        self.assertEqual(sheet["A3"].value, "전체 합계")
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(sheet["D2"].value, 0)

        error_result = analyze_paths([self.root / "missing"])
        error_output = write_workbook(error_result, self.root / "with-errors.xlsx")
        error_workbook = load_workbook(error_output, data_only=True)
        self.assertEqual(error_workbook.sheetnames[:2], [WORKSHEET_NAME, WEAPON_BBOX_WORKSHEET_NAME])
        self.assertIn("집계 오류 로그", error_workbook.sheetnames)
        self.assertEqual(error_workbook["집계 오류 로그"]["A1"].value, "폴더 경로")


if __name__ == "__main__":
    unittest.main()
