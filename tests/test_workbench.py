"""Numerical and HTTP contracts of the independent data workbench."""

import json
import math
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.server import Handler, ThreadingHTTPServer, fit_data


class WorkbenchFitTests(unittest.TestCase):
    def test_supported_models_predict_held_out_data(self):
        cases = {
            "constant": lambda x: 4,
            "linear": lambda x: 2 + 3*x,
            "quadratic": lambda x: 2 + 3*x + .2*x*x,
            "cubic": lambda x: 2 + 3*x + .2*x*x + .1*x**3,
            "exponential": lambda x: math.exp(.2 + .3*x),
            "logarithmic": lambda x: 2 + 3*math.log(x),
            "power": lambda x: 2*x**1.5,
        }
        for model, function in cases.items():
            with self.subTest(model=model):
                rows = [{"a": i/4, "b": function(i/4)} for i in range(1, 31)]
                result = fit_data({"rows": rows, "x": "a", "y": "b", "model": model})
                self.assertLess(result["validation"]["rmse"], 1e-8)
                self.assertEqual(result["train"]["count"], 24)
                self.assertEqual(result["validation"]["count"], 6)

    def test_constant_x_and_invalid_domains(self):
        rows = [{"x": 1, "y": 4}] * 10
        self.assertEqual(fit_data({"rows": rows, "x": "x", "y": "y", "model": "constant"})["train"]["rmse"], 0)
        with self.assertRaisesRegex(ValueError, "变化不足"):
            fit_data({"rows": rows, "x": "x", "y": "y"})
        with self.assertRaisesRegex(ValueError, "X > 0"):
            fit_data({"rows": [{"x": i, "y": 1} for i in range(-5, 6)], "x": "x", "y": "y", "model": "power"})

    def test_missing_values_excluded_before_split(self):
        rows = [{"x": i, "y": 2*i} for i in range(10)] + [{"x": None, "y": 1}]
        result = fit_data({"rows": rows, "x": "x", "y": "y"})
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["validation"]["count"], 2)


class WorkbenchHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def post(self, path, payload, origin=None):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        return urlopen(Request(self.base+path, json.dumps(payload).encode(), headers), timeout=5)

    def test_static_ui_and_csv_import(self):
        with urlopen(self.base, timeout=5) as response:
            self.assertIn(b"Data Workbench", response.read())
        with self.post("/api/import", {"csv": "time,voltage,label\n0,1.2,A\n1,,B\n"}) as response:
            data = json.load(response)
            self.assertEqual(data["columns"], ["time", "voltage", "label"])
            self.assertIsNone(data["rows"][1]["voltage"])

    def test_invalid_fit_and_cross_origin_are_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.post("/api/fit", {"rows": [], "x": "x", "y": "y"})
        self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            self.post("/api/capture/stop", {}, "https://example.com")
        self.assertEqual(error.exception.code, 403)

    def test_capture_summary_requires_stopped_matching_capture(self):
        capture = SimpleNamespace(id="capture-test", topic="/ray", running=False,
                                  snapshot=lambda: ([{"x": 0, "z": 1, "status": 1}], [], None))
        payload = {"capture_id": capture.id, "fields": ["x", "z"], "valid_field": "status", "valid_value": "1"}
        with patch.object(Handler, "capture", capture):
            with self.post("/api/capture/summary", payload) as response:
                result = json.load(response)
                self.assertEqual(result["statistics"][0]["mean"], 0)
                self.assertEqual(result["capture_id"], capture.id)
            for bad in [{**payload, "capture_id": "previous"}, {**payload, "fields": ["missing"]}]:
                with self.assertRaises(HTTPError) as error:
                    self.post("/api/capture/summary", bad)
                self.assertEqual(error.exception.code, 400)
            capture.running = True
            with self.assertRaises(HTTPError) as error:
                self.post("/api/capture/summary", payload)
            self.assertEqual(error.exception.code, 400)
