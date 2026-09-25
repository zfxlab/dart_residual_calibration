"""Generic capture statistics and derived directions."""
import math
import unittest

from backend.capture.summary import summarize_capture
from backend.analysis.expressions import derive, Expression


class CaptureSummaryTests(unittest.TestCase):
    rows = [{"a": 0, "b": 2, "status": 1}, {"a": 2, "b": None, "status": 1},
            {"a": None, "b": 4, "status": 1}, {"a": 999, "b": 999, "status": 0}]
    config = {"fields": ["a", "b"], "valid_field": "status", "valid_value": "1"}

    def test_independent_statistics_preserve_zero(self):
        result = summarize_capture(self.rows, self.config)
        self.assertEqual(result["matched_count"], 3)
        self.assertEqual(result["rejected_count"], 1)
        a, b = result["statistics"]
        self.assertEqual(a["count"], 2)
        self.assertEqual(a["missing_count"], 1)
        self.assertEqual(a["mean"], 1)
        self.assertEqual(a["min"], 0)
        self.assertEqual(a["max"], 2)
        self.assertAlmostEqual(a["std"], math.sqrt(2))
        self.assertEqual(b["mean"], 3)

    def test_paired_statistics_use_same_records(self):
        result = summarize_capture(self.rows, {**self.config, "sample_mode": "paired"})
        a, b = result["statistics"]
        self.assertEqual(a["count"], 1)
        self.assertEqual(b["count"], 1)
        self.assertEqual(a["mean"], 0)
        self.assertEqual(b["mean"], 2)
        self.assertIsNone(a["std"])

    def test_no_valid_values_and_nonfinite(self):
        result = summarize_capture([{"a": None}, {"a": float("inf")}, {"a": False}, {"a": ""}],
                                   {"fields": ["a"]})
        self.assertEqual(result["statistics"][0]["count"], 0)
        for key in ["mean", "std", "min", "max"]:
            self.assertIsNone(result["statistics"][0][key])
        self.assertEqual(summarize_capture([], {"fields": ["a"]})["total_count"], 0)

    def test_validation_and_optional_condition(self):
        for config in [{"fields": []}, {"fields": ["a", "a"]}, {"fields": ["missing"]},
                       {"fields": ["a"], "sample_mode": "bad"}]:
            with self.assertRaises(ValueError):
                summarize_capture(self.rows, config)
        result = summarize_capture(self.rows, {"fields": ["a"]})
        self.assertEqual(result["matched_count"], 4)
        self.assertEqual(result["statistics"][0]["count"], 3)

    def test_derived_atan2_after_summary(self):
        result = derive({"columns": ["x_mean", "z_mean"],
                         "rows": [{"x_mean": 0, "z_mean": 1}, {"x_mean": 0, "z_mean": 0},
                                  {"x_mean": None, "z_mean": 1}, {"x_mean": 1, "z_mean": 1}],
                         "derived": [{"name": "yaw", "expression": "atan2([x_mean], [z_mean])*180/pi"}]})
        self.assertEqual([r["yaw"] for r in result["rows"]], [0, None, None, 45])
        for formula in ["atan2(1)", "atan2(1,2,3)", "sin(1,2)"]:
            with self.assertRaises(ValueError):
                Expression(formula)
