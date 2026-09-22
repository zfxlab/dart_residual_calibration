"""Optional ROS integration test: source workspace, set RUN_ROS_CAPTURE_TESTS=1."""

import os
import sys
import time
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from topic_capture import Capture
from topic_data import summarize


@unittest.skipUnless(os.environ.get("RUN_ROS_CAPTURE_TESTS") == "1", "requires sourced ROS")
class RosCaptureTests(unittest.TestCase):
    def test_preview_rolls_buffer_without_stopping_at_limit(self):
        import rclpy
        from dart_interfaces.msg import StereoTarget
        from rclpy.qos import qos_profile_sensor_data

        rclpy.init()
        node = rclpy.create_node("residual_preview_test")
        topic = f"/residual_test_{uuid.uuid4().hex}"
        publisher = node.create_publisher(StereoTarget, topic, qos_profile_sensor_data)
        capture = Capture(topic, duration=0, limit=5, preview=True)
        try:
            deadline = time.monotonic() + 8
            first_stamp = None
            rolled = False
            while capture.running and time.monotonic() < deadline:
                message = StereoTarget()
                message.header.frame_id = "test_center"
                message.header.stamp = node.get_clock().now().to_msg()
                message.status = 1
                message.distance = 25.0
                publisher.publish(message)
                rclpy.spin_once(node, timeout_sec=0.05)
                samples, logs, _ = capture.snapshot()
                self.assertLessEqual(len(samples), 5)
                if samples and first_stamp is None:
                    first_stamp = samples[0]["stamp_ns"]
                if len(samples) == 5 and samples[0]["stamp_ns"] > first_stamp:
                    rolled = True
                    break
            self.assertTrue(rolled, logs)
            self.assertTrue(capture.running)
            capture.stop()
            self.assertFalse(capture.running)
        finally:
            capture.stop()
            node.destroy_node()
            rclpy.shutdown()

    def test_best_effort_capture_limit_and_statistics(self):
        import rclpy
        from dart_interfaces.msg import StereoTarget
        from rclpy.qos import qos_profile_sensor_data

        rclpy.init()
        node = rclpy.create_node("residual_capture_test")
        topic = f"/residual_test_{uuid.uuid4().hex}"
        publisher = node.create_publisher(StereoTarget, topic, qos_profile_sensor_data)
        capture = Capture(topic, duration=8, limit=12)
        try:
            deadline = time.monotonic() + 12
            sequence = 0
            while capture.running and time.monotonic() < deadline:
                message = StereoTarget()
                message.header.frame_id = "test_center"
                message.header.stamp = node.get_clock().now().to_msg()
                message.status = 1 if sequence % 2 else 2
                message.distance = 25.0 if message.status == 1 else 0.0
                message.yaw = 0.1 if message.status == 1 else 0.0
                publisher.publish(message)
                sequence += 1
                rclpy.spin_once(node, timeout_sec=0.05)
            samples, logs, _ = capture.snapshot()
            self.assertEqual(len(samples), 12, logs)
            self.assertFalse(capture.running)
            self.assertEqual(capture.process.returncode, 0)
            stats = summarize(samples, ["distance", "yaw"])
            self.assertEqual(stats[0]["mean"], 25.0)
            self.assertAlmostEqual(stats[1]["mean"], 0.1)
            self.assertLess(stats[0]["valid"], 12)
        finally:
            capture.stop()
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    unittest.main()
