"""System-Python ROS worker; stdout is a JSON-lines stream to the web process."""

import argparse
import json
import math
import os
import time

if __package__:
    from .data import sample_from_message
else:
    # Executed by system Python, with this directory on sys.path.
    from data import sample_from_message


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--message-type")
    args = parser.parse_args()
    # Keep ROS imports here so the offline page never needs rclpy in its venv.
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    if args.message_type:
        from rosidl_runtime_py.utilities import get_message
        message_class = get_message(args.message_type)
    else:
        from dart_interfaces.msg import StereoTarget
        message_class = StereoTarget
    if not args.message_type and not all(hasattr(message_class(), name) for name in ("distance", "yaw")):
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
        elapsed = time.monotonic() - start
        if args.message_type:
            from rosidl_runtime_py.convert import message_to_ordereddict
            sample = {"elapsed_s": elapsed, "stamp_ns": 0, "frame_id": ""}

            def flatten(value, prefix=""):
                for key, item in value.items():
                    name = f"{prefix}.{key}" if prefix else key
                    if isinstance(item, dict):
                        flatten(item, name)
                    elif isinstance(item, (int, float, str, bool)):
                        sample[name] = None if isinstance(item, float) and not math.isfinite(item) else item
            flatten(message_to_ordereddict(message))
            if hasattr(message, "header"):
                sample["stamp_ns"] = message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec
                sample["frame_id"] = message.header.frame_id
        else:
            sample = sample_from_message(message, elapsed)
        print(json.dumps(sample), flush=True)
        count += 1

    node.create_subscription(message_class, args.topic, callback, qos_profile_sensor_data)
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
