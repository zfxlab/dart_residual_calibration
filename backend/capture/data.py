"""ROS-independent observation schema, segmentation and statistics."""

import math
from statistics import mean, stdev

FIELDS = {
    "distance": "m",
    "yaw": "rad",
    "position.x": "m",
    "position.y": "m",
    "position.z": "m",
    "ray_gap_m": "m",
}


def sample_from_message(message, elapsed):
    sample = {
        "elapsed_s": elapsed,
        "stamp_ns": message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec,
        "frame_id": message.header.frame_id,
        "status": int(message.status),
    }
    for field in FIELDS:
        value = message
        for part in field.split("."):
            value = getattr(value, part)
        sample[field] = float(value) if math.isfinite(value) else None
    return sample


def assign_segment(sample, previous):
    """Separate frames and ROS clock rollback, while retaining receive-time order."""
    segment = previous["segment"] if previous else 0
    if previous and (
        sample["frame_id"] != previous["frame_id"] or sample["stamp_ns"] < previous["stamp_ns"]
    ):
        segment += 1
    return {**sample, "segment": segment}


def valid_value(sample, field):
    value = sample.get(field)
    return sample["status"] == 1 and value is not None and math.isfinite(value)


def summarize(samples, fields):
    result = []
    for field in fields:
        values = [sample[field] for sample in samples if valid_value(sample, field)]
        result.append(
            {
                "field": field,
                "unit": FIELDS[field],
                "total": len(samples),
                "valid": len(values),
                "valid_ratio": len(values) / len(samples) if samples else None,
                "mean": mean(values) if values else None,
                "std_sample": stdev(values) if len(values) > 1 else None,
                "min": min(values) if values else None,
                "max": max(values) if values else None,
            }
        )
    return result
