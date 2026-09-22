"""System-Python ROS worker; stdout is a JSON-lines stream to the web process."""

import argparse
import json
import os
import time

from topic_data import sample_from_message


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    # Keep ROS imports here so the offline page never needs rclpy in its venv.
    import rclpy
    from dart_interfaces.msg import StereoTarget
    from rclpy.qos import qos_profile_sensor_data

    if not all(hasattr(StereoTarget(), name) for name in ("distance", "yaw")):
        raise RuntimeError("StereoTarget 缺少 distance/yaw，请重新编译并 source 工作区")
    rclpy.init()
    node = rclpy.create_node(f"residual_capture_{os.getpid()}")
    start = time.monotonic()
    count = 0
    parent_pid = os.getppid()

    def callback(message):
        nonlocal count
        if not args.preview and count >= args.limit:
            return
        print(json.dumps(sample_from_message(message, time.monotonic() - start)), flush=True)
        count += 1

    node.create_subscription(StereoTarget, args.topic, callback, qos_profile_sensor_data)
    try:
        while rclpy.ok() and os.getppid() == parent_pid:
            if not args.preview and (
                time.monotonic() - start >= args.duration or count >= args.limit
            ):
                break
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
