"""Regression tests using actual multi-page Streamlit navigation."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None

ROOT = Path(__file__).resolve().parents[1]
OBSERVATION = "pages/1_话题观测.py"


class CompletedCapture:
    topic = "/camera/stereo_target"
    running = False
    limit = 100
    started = time.monotonic()
    stopped = False
    process = SimpleNamespace(returncode=0)

    def snapshot(self):
        return (
            [
                {
                    "elapsed_s": float(i),
                    "stamp_ns": i,
                    "frame_id": "test_center",
                    "status": 1,
                    "segment": 0,
                    "distance": 25.0,
                    "yaw": 0.1,
                }
                for i in range(4)
            ],
            [],
            time.monotonic(),
        )


@unittest.skipIf(AppTest is None, "requires tool venv with Streamlit")
class PageNavigationTests(unittest.TestCase):
    def test_restore_button_does_not_accumulate_drafts(self):
        from storage import new_project, save_draft

        with (
            tempfile.TemporaryDirectory() as drafts,
            patch.dict(os.environ, {"DART_CALIBRATION_DATA_DIR": drafts}),
        ):
            project = new_project("重复恢复测试")
            save_draft(project, drafts)
            app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=20)
            for _ in range(3):
                next(b for b in app.button if b.label == "恢复所选草稿").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["project"]["project_id"], project["project_id"])
                self.assertEqual(len(list(Path(drafts).glob("*.json"))), 1)

    def test_edits_models_fit_and_capture_survive_round_trip(self):
        with (
            tempfile.TemporaryDirectory() as drafts,
            patch.dict(os.environ, {"DART_CALIBRATION_DATA_DIR": drafts}),
        ):
            app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=20)
            next(b for b in app.button if b.label == "载入演示数据").click().run()
            app.text_input(key="project_name").set_value("保留当前测量").run()
            app.selectbox(key="model_distance").select("linear").run()
            # AppTest has no data_editor edit API; send its browser delta protobuf.
            widget_states = app._tree.get_widget_states()
            editor = widget_states.widgets.add()
            editor.id = app.dataframe[0].proto.id
            editor.string_value = json.dumps(
                {
                    "edited_rows": {0: {"notes": "切页前已提交的编辑"}},
                    "added_rows": [],
                    "deleted_rows": [],
                }
            )
            fit_id = next(b for b in app.button if b.label == "执行拟合").proto.id
            for widget in widget_states.widgets:
                if widget.id == fit_id:
                    widget.trigger_value = True
            app._run(widget_states, timeout=20)
            self.assertFalse(app.exception)
            project = app.session_state["project"]
            project_id = project["project_id"]
            self.assertEqual(project["measurements"][0]["notes"], "切页前已提交的编辑")
            records = project["measurements"]
            signature = app.session_state["fit_signature"]
            capture = CompletedCapture()
            app.session_state["topic_capture"] = capture
            app.session_state["observation_mode"] = "定时采集"
            app.switch_page(OBSERVATION).run()
            self.assertFalse(app.exception)
            app.multiselect(key="observation_fields").set_value(["distance"]).run()
            app.slider[0].set_range(1.0, 2.0).run()
            for _ in range(2):
                app.switch_page("app.py").run(timeout=20)
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["project"]["project_id"], project_id)
                self.assertEqual(app.session_state["project"]["measurements"], records)
                self.assertEqual(app.text_input(key="project_name").value, "保留当前测量")
                self.assertEqual(app.selectbox(key="model_distance").value, "linear")
                self.assertEqual(app.session_state["fit_signature"], signature)
                self.assertTrue(app.session_state["fit_results"])
                app.switch_page(OBSERVATION).run()
                self.assertFalse(app.exception)
                self.assertIs(app.session_state["topic_capture"], capture)
                self.assertEqual(app.multiselect(key="observation_fields").value, ["distance"])
                self.assertEqual(tuple(app.slider[0].value), (1.0, 2.0))
                self.assertEqual(app.dataframe[0].value.iloc[0]["total"], 2)

    def test_blank_settings_and_unstarted_edits_survive_navigation(self):
        app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=20)
        app.switch_page(OBSERVATION).run()
        self.assertEqual(app.text_input(key="observation_topic").value, "")
        self.assertEqual(app.multiselect(key="observation_fields").value, [])
        self.assertIsNone(app.number_input(key="observation_window").value)
        app.radio(key="observation_mode").set_value("定时采集").run()
        self.assertIsNone(app.number_input(key="observation_duration").value)
        self.assertIsNone(app.number_input(key="observation_limit").value)
        app.text_input(key="observation_topic").set_value("/my/stereo_target").run()
        app.number_input(key="observation_duration").set_value(45).run()
        app.number_input(key="observation_limit").set_value(900).run()
        app.number_input(key="observation_window").set_value(15).run()
        app.multiselect(key="observation_fields").set_value(["yaw"]).run()
        # No Start button is pressed. Switch both pages and modes.
        for _ in range(2):
            app.switch_page("app.py").run(timeout=20)
            app.switch_page(OBSERVATION).run()
            app.radio(key="observation_mode").set_value("实时预览").run()
            app.radio(key="observation_mode").set_value("定时采集").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.text_input(key="observation_topic").value, "/my/stereo_target")
            self.assertEqual(app.number_input(key="observation_duration").value, 45)
            self.assertEqual(app.number_input(key="observation_limit").value, 900)
            self.assertEqual(app.number_input(key="observation_window").value, 15)
            self.assertEqual(app.multiselect(key="observation_fields").value, ["yaw"])

    def test_preview_does_not_replace_recording(self):
        app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=20)
        saved = CompletedCapture()
        live = CompletedCapture()
        live.running = True
        app.session_state["topic_capture"] = saved
        app.switch_page(OBSERVATION).run()
        app.text_input(key="observation_topic").set_value("/preview_test").run()
        app.multiselect(key="observation_fields").set_value(["distance"]).run()
        with patch("topic_capture.Capture", return_value=live) as factory:
            next(b for b in app.button if b.label == "开始实时预览").click().run()
            factory.assert_called_once_with("/preview_test", 0, 5000, preview=True)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("plotly_chart")), 1)
        self.assertIs(app.session_state["topic_capture"], saved)
        app.switch_page("app.py").run(timeout=20)
        app.switch_page(OBSERVATION).run()
        self.assertIs(app.session_state["topic_preview"], live)
        self.assertIs(app.session_state["topic_capture"], saved)
        self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
