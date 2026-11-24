"""Exercise uploads, legacy analysis, report compatibility and Streamlit reruns."""
from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import load_workbook
from PIL import Image
from streamlit.testing.v1 import AppTest

from data_preprocessing import folder_object_distribution as distribution
from data_preprocessing import multi_weapon_review as review
from streamlit_app import file_handler
from streamlit_app.analysis import filter_reviews, run_analysis
from streamlit_app.annotation_viewer import draw_annotation
from streamlit_app.charts import object_figures


@dataclass
class Upload:
    name: str
    data: bytes

    @property
    def size(self):
        return len(self.data)

    def getvalue(self):
        return self.data


SHAPE = {"label": "전차", "shape_type": "rectangle", "points": [[10, 10], [35, 35]],
         "무기타입": ["포/포탑_1", "원격무장"]}


def annotation(image, *shapes):
    return json.dumps({"imagePath": image, "imageWidth": 50, "imageHeight": 40,
                       "shapes": list(shapes)}, ensure_ascii=False).encode()


def png():
    data = BytesIO()
    Image.new("RGB", (100, 80), "white").save(data, "PNG")
    return data.getvalue()


def archive(entries):
    data = BytesIO()
    with ZipFile(data, "w") as zipped:
        for name, contents in entries.items():
            zipped.writestr(name, contents)
    return data.getvalue()


def sample():
    return archive({
        "lot-a/a.json": annotation("a.png", SHAPE, {"label": "소총", "points": [[8, 8], [10, 10]]}),
        "lot-a/a.png": png(),
        "lot-a/extra.png": png(),
        "lot-b/b.json": annotation("wrong.png", {**SHAPE, "label": "군인",
                  "무기타입": ["포/포탑_1", "포/포탑_2", "원격무장"]}),
        "lot-b/b.png": png(),
        "lot-b/c.json": annotation("c.png"),
        "lot-b/c.png": png(),
        "lot-b/corrupt.json": b"{broken",
        "images-only/extra.png": png(),
    })


class DatasetTests(unittest.TestCase):
    def test_legacy_results_zip_statistics_and_excel(self):
        dataset = file_handler.prepare_uploads([Upload("dataset.zip", sample())])
        result = run_analysis(dataset, "all")
        self.assertEqual((dataset.json_count, len(dataset.images), result.total_images), (4, 5, 5))
        self.assertEqual(result.total_objects, 3)
        self.assertEqual({name: count for name, count in result.classes.items() if count},
                         {"전차": 1, "군인": 1, "소총": 1})
        folders = {folder.name: folder for folder in result.folders}
        self.assertEqual((folders["lot-a"].images, folders["lot-a"].objects, folders["lot-a"].average), (2, 2, 1.0))
        self.assertEqual((folders["images-only"].images, folders["images-only"].objects), (1, 0))
        self.assertEqual([issue.file for issue in result.anomalies["empty"]], ["lot-b/c.json"])
        self.assertCountEqual([issue.file for issue in result.anomalies["missing"]],
                              ["lot-a/extra.png", "images-only/extra.png"])
        self.assertEqual([issue.file for issue in result.anomalies["invalid"]], ["lot-b/corrupt.json"])
        self.assertEqual([issue.file for issue in result.anomalies["mismatch"]], ["lot-b/b.json"])
        self.assertCountEqual([row.kind for row in result.reviews],
                              ["서로 다른 복수 무기타입", "중복 및 복수 무기타입"])
        self.assertEqual([row.path for row in filter_reviews(result.reviews, "중복 및 복수 무기타입", "lot-b", "군인")],
                         ["lot-b/b.json"])
        self.assertEqual(filter_reviews(result.reviews, "중복 및 복수 무기타입", "lot-a", "군인"), [])
        for module in (distribution, review):
            workbook = load_workbook(BytesIO(result.workbooks[module.OUTPUT_FILENAME]))
            try:
                self.assertIn(module.WORKSHEET_NAME, workbook.sheetnames)
                self.assertEqual([cell.value for cell in workbook[module.WORKSHEET_NAME][1]], module.HEADERS)
            finally:
                workbook.close()

    def test_json_only_and_selected_mode(self):
        dataset = file_handler.prepare_uploads([
            Upload("a.json", annotation("a.png", SHAPE)), Upload("bad.json", b"{"), Upload("structure.json", b"[]"),
        ])
        result = run_analysis(dataset, "distribution")
        self.assertEqual(dataset.json_count, 3)
        self.assertEqual(result.total_images, 1)
        self.assertTrue(result.image_count_inferred)
        self.assertEqual(result.folders[0].average, 0)
        self.assertIsNone(result.anomalies["missing"])
        self.assertIsNone(result.anomalies["mismatch"])
        self.assertEqual(len(result.anomalies["invalid"]), 2)
        self.assertEqual(list(result.workbooks), [distribution.OUTPUT_FILENAME])
        with patch.object(distribution, "analyze_paths", side_effect=AssertionError("unselected analysis ran")):
            selected = run_analysis(dataset, "review")
        self.assertIsNone(selected.total_objects)
        self.assertEqual(list(selected.workbooks), [review.OUTPUT_FILENAME])

    def test_damaged_archive_unsafe_paths_duplicates_and_size(self):
        upload = Upload("mixed.zip", archive({
            "../escape.json": b"{}", "C:/escape.json": b"{}", "lot/CON.txt": b"bad",
            "lot/a.json": annotation("a.png"), "lot/A.JSON": annotation("different.png"),
            "lot/larger.json": b"x" * 300,
            "lot/other.html": b"bad",
        }))
        with patch.object(file_handler, "MAX_FILE", 200):
            dataset = file_handler.prepare_uploads([upload, Upload("broken.zip", b"broken"), Upload("script.py", b"bad")])
        self.assertEqual(list(dataset.annotations), ["lot/a.json"])
        self.assertEqual(len(dataset.upload_issues), 8)
        self.assertEqual(len(dataset.json_issues), 0)

    def test_expansion_budget_includes_rejected_members(self):
        content = annotation("a.png")
        upload = Upload("limited.zip", archive({"a.json": content, "A.JSON": content, "b.json": content}))
        with patch.object(file_handler, "MAX_EXPANDED", len(content) * 2):
            dataset = file_handler.prepare_uploads([upload])
        self.assertEqual(list(dataset.annotations), ["a.json"])
        self.assertEqual(len(dataset.upload_issues), 2)
        self.assertIn("용량 제한", dataset.upload_issues[-1].reason)

    def test_mirrored_image_folders_and_coordinate_scaling(self):
        dataset = file_handler.prepare_uploads([Upload("paired.zip", archive({
            "batch/labels/small/a.json": annotation("a.png", SHAPE),
            "batch/images/small/a.png": png(),
            "external/b.png": png(),
            "batch/labels/small/b.json": annotation("../../../external/b.png", SHAPE),
        }))])
        result = run_analysis(dataset, "review")
        self.assertEqual(result.matches["batch/labels/small/a.json"], "batch/images/small/a.png")
        self.assertEqual(result.matches["batch/labels/small/b.json"], "external/b.png")
        self.assertEqual(result.anomalies["missing"], [])
        data = file_handler.labelme(dataset.annotations["batch/labels/small/a.json"])
        data["shapes"].append({"shape_type": "mask", "points": [[0, 0]]})
        rendered, skipped = draw_annotation(png(), data, 1)
        self.assertEqual(rendered.size, (100, 80))
        self.assertEqual(rendered.getpixel((66, 20)), (246, 163, 28))
        self.assertEqual(skipped, [2])

    def test_chart_values(self):
        bar, pie = object_figures({"A": 1, "B": 3, "C": 0})
        self.assertEqual(list(bar.data[0].x), ["B", "A", "C"])
        self.assertEqual(list(bar.data[0].customdata), [0.75, 0.25, 0])
        self.assertEqual(list(pie.data[0].values), [3, 1])


class StreamlitTests(unittest.TestCase):
    def test_upload_run_filters_downloads_and_reset(self):
        path = Path(__file__).resolve().parents[1] / "streamlit_app" / "app.py"
        app = AppTest.from_file(str(path), default_timeout=25).run()
        self.assertFalse(app.exception)
        self.assertTrue(app.button(key="run_analysis").disabled)
        app.file_uploader[0].upload("dataset.zip", sample(), "application/zip").run()
        self.assertFalse(app.exception)
        self.assertNotIn("result", app.session_state)
        self.assertFalse(app.button(key="run_analysis").disabled)
        app.button(key="run_analysis").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.session_state["result"].total_objects, 3)
        self.assertEqual(len(app.get("plotly_chart")), 4)
        self.assertEqual(len(app.download_button), 2)

        with patch("streamlit_app.analysis.run_analysis", side_effect=AssertionError("analysis repeated")):
            app.selectbox(key="folder_sort").set_value("이미지 수").run()
            app.selectbox(key="review_folder").set_value("lot-b").run()
            app.selectbox(key="review_class").set_value("군인").run()
            app.selectbox(key="review_item").select_index(0).run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertTrue(any(item.value == "선택한 검수 항목" for item in app.subheader))
            app.download_button[0].click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertEqual(app.session_state["result"].total_objects, 3)
            app.radio(key="analysis_option").set_value("복수 무기타입 검수").run()
            self.assertEqual(app.session_state["result"].mode, "all")
        app.button(key="run_analysis").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.session_state["result"].mode, "review")
        self.assertEqual(len(app.download_button), 1)
        app.file_uploader[0].clear().run()
        self.assertNotIn("result", app.session_state)
        self.assertTrue(app.button(key="run_analysis").disabled)
