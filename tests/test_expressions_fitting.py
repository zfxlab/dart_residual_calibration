"""Expression safety, derived dependencies and constrained fitting contracts."""

import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.analysis.expressions import Expression, derive
from backend.analysis.fitting import fit_data


class ExpressionTests(unittest.TestCase):
    def test_dependencies_domains_and_missing_values(self):
        payload = {
            "columns": ["a", "b"],
            "rows": [{"a": 9, "b": 4}, {"a": None, "b": 0}, {"a": -1, "b": 2}],
            "derived": [
                {"name": "z", "expression": "sqrt([delta])"},
                {"name": "delta", "expression": "[a]-[b]"},
                {"name": "missing", "expression": "[a]**0"},
                {"name": "ratio", "expression": "[a]/[b]"},
            ],
        }
        result = derive(payload)
        self.assertAlmostEqual(result["rows"][0]["z"], math.sqrt(5))
        self.assertIsNone(result["rows"][1]["missing"])
        self.assertIsNone(result["rows"][1]["ratio"])
        self.assertIsNone(result["rows"][2]["z"])
        self.assertEqual(result["diagnostics"]["z"]["invalid"], 2)
        self.assertNotIn("z", payload["rows"][0])

    def test_recompute_overwrites_stale_derived_values(self):
        payload = {
            "columns": ["x", "error"],
            "rows": [{"x": 3, "error": 99}],
            "derived": [{"name": "error", "expression": "[x]-1"}],
        }
        self.assertEqual(derive(payload)["rows"][0]["error"], 2)
        payload["rows"][0]["x"] = 7
        self.assertEqual(derive(payload)["rows"][0]["error"], 6)

    def test_reject_cycles_missing_fields_and_python(self):
        for expr in [
            "__import__('os')",
            "x.__class__",
            "x[0]",
            "(lambda: 1)()",
            "[x for x in range(3)]",
        ]:
            with self.subTest(expr=expr), self.assertRaises(ValueError):
                Expression(expr)
        with self.assertRaisesRegex(ValueError, "循环"):
            derive(
                {
                    "columns": ["x"],
                    "rows": [{"x": 1}],
                    "derived": [
                        {"name": "a", "expression": "[b]+1"},
                        {"name": "b", "expression": "[a]-1"},
                    ],
                }
            )
        with self.assertRaisesRegex(ValueError, "不存在"):
            derive(
                {
                    "columns": ["x"],
                    "rows": [],
                    "derived": [{"name": "z", "expression": "[absent]+1"}],
                }
            )


class CustomFitTests(unittest.TestCase):
    def rows(self):
        return [
            {
                "x": i / 10,
                "reference": 2 + 3 * i / 10,
                "offset": 1,
                "batch": "A" if i < 24 else "B",
                "w": 1,
            }
            for i in range(30)
        ]

    def payload(self, **extra):
        return {
            "rows": self.rows(),
            "x_expression": "[x]",
            "y_expression": "[reference]-[offset]",
            "model": "custom",
            "formula": "a+b*x",
            **extra,
        }

    def test_column_expression_fixed_parameter_group_and_export(self):
        result = fit_data(
            self.payload(
                group="batch",
                parameters={
                    "a": {"initial": 1, "fixed": True},
                    "b": {"initial": 2, "lower": 0, "upper": 5},
                },
            )
        )
        self.assertEqual(result["parameters"][0]["value"], 1)
        self.assertAlmostEqual(result["parameters"][1]["value"], 3)
        self.assertLess(result["validation"]["rmse"], 1e-8)
        self.assertEqual(result["validation"]["count"], 6)
        self.assertEqual(result["configuration"]["y_expression"], "[reference]-[offset]")
        self.assertEqual(len(result["source_fingerprint"]), 64)
        self.assertIsNotNone(result["parameters"][1]["ci95"])

    def test_robust_loss_and_weights_reduce_outlier_effect(self):
        payload = self.payload(validation=0)
        payload["rows"][-1]["reference"] += 100
        ordinary = fit_data(payload)
        robust = fit_data({**payload, "loss": "soft_l1", "f_scale": 0.2})
        self.assertLess(
            abs(robust["parameters"][1]["value"] - 3), abs(ordinary["parameters"][1]["value"] - 3)
        )
        self.assertIsNone(robust["parameters"][0]["ci95"])
        payload["rows"][-1]["w"] = 0
        weighted = fit_data({**payload, "weight": "w"})
        self.assertEqual(weighted["skipped"], 1)
        self.assertAlmostEqual(weighted["parameters"][1]["value"], 3)

    def test_invalid_bounds_and_initial_domain(self):
        with self.assertRaisesRegex(ValueError, "初值或上下限"):
            fit_data(self.payload(parameters={"a": {"initial": 5, "lower": 0, "upper": 2}}))
        with self.assertRaisesRegex(ValueError, "无定义"):
            fit_data(self.payload(formula="sqrt(a-x)", parameters={"a": {"initial": -1}}))
        with self.assertRaisesRegex(ValueError, "未知参数"):
            fit_data(self.payload(parameters={"wrong": {"initial": 1}}))

    def test_custom_exponential_and_identifiability(self):
        rows = [{"x": float(x), "y": 4 * np.exp(-0.7 * x) + 2} for x in np.linspace(0, 4, 60)]
        result = fit_data(
            {
                "rows": rows,
                "x": "x",
                "y": "y",
                "model": "custom",
                "formula": "a*exp(-b*x)+c",
                "parameters": {"b": {"initial": 0.5, "lower": 0.01}},
            }
        )
        self.assertLess(result["validation"]["rmse"], 1e-7)
        self.assertAlmostEqual(result["parameters"][1]["value"], 0.7, places=6)
