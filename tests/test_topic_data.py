import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.capture.data import assign_segment, summarize


class StatisticsTests(unittest.TestCase):
    def test_invalid_and_nonfinite_are_excluded_per_field(self):
        samples = [
            {"status": 1, "distance": 10.0, "yaw": 0.1},
            {"status": 0, "distance": 0.0, "yaw": 0.0},
            {"status": 2, "distance": 0.0, "yaw": 0.0},
            {"status": 1, "distance": 14.0, "yaw": None},
            {"status": 1, "distance": math.inf, "yaw": 0.3},
        ]
        distance, yaw = summarize(samples, ["distance", "yaw"])
        self.assertEqual(distance["mean"], 12.0)
        self.assertEqual(distance["valid"], 2)
        self.assertEqual(distance["total"], 5)
        self.assertEqual(distance["valid_ratio"], 0.4)
        self.assertAlmostEqual(distance["std_sample"], math.sqrt(8))
        self.assertAlmostEqual(yaw["mean"], 0.2)

    def test_empty_and_single_sample(self):
        empty = summarize([], ["distance"])[0]
        self.assertIsNone(empty["mean"])
        self.assertIsNone(empty["valid_ratio"])
        single = summarize([{"status": 1, "distance": 5}], ["distance"])[0]
        self.assertEqual(single["mean"], 5)
        self.assertIsNone(single["std_sample"])

    def test_frame_changes_and_clock_rollback_split_segments(self):
        first = assign_segment({"frame_id": "a", "stamp_ns": 100}, None)
        second = assign_segment({"frame_id": "a", "stamp_ns": 101}, first)
        rollback = assign_segment({"frame_id": "a", "stamp_ns": 90}, second)
        changed = assign_segment({"frame_id": "b", "stamp_ns": 91}, rollback)
        self.assertEqual([s["segment"] for s in (first, second, rollback, changed)], [0, 0, 1, 2])


if __name__ == "__main__":
    unittest.main()
