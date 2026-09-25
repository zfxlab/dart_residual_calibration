"""Generic per-field statistics for one stopped capture."""

import math
from statistics import stdev


def finite_number(value):
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def summarize_capture(samples, config):
    fields = config.get("fields", [])
    if (not isinstance(fields, list) or not 1 <= len(fields) <= 64
            or any(not isinstance(f, str) or not f for f in fields)
            or len(set(fields)) != len(fields)):
        raise ValueError("请选择 1–64 个不重复的统计字段。")
    mode = config.get("sample_mode", "independent")
    if mode not in ("independent", "paired"):
        raise ValueError("统计方式必须为 independent 或 paired。")
    valid_field = config.get("valid_field", "")
    valid_value = str(config.get("valid_value", ""))
    available = {key for row in samples for key in row}
    if samples and (set(fields) - available or (valid_field and valid_field not in available)):
        raise ValueError("所选字段不存在于本次采集中。")
    expected = finite_number(valid_value)
    matched = []
    for row in samples:
        actual = row.get(valid_field)
        text = str(actual).lower() if isinstance(actual, bool) else str(actual)
        match = actual is not None and (finite_number(actual) == expected if expected is not None else text == valid_value)
        if not valid_field or match:
            matched.append([finite_number(row.get(f)) for f in fields])
    used = [row for row in matched if all(v is not None for v in row)] if mode == "paired" else matched
    statistics = []
    for index, field in enumerate(fields):
        values = [row[index] for row in used if row[index] is not None]
        count = len(values)
        mean = math.fsum(v / count for v in values) if count else None
        sd = stdev(values) if count > 1 else None
        if sd is not None and not math.isfinite(sd):
            raise ValueError("数值范围过大，无法计算标准差。")
        statistics.append({"field": field, "count": count, "missing_count": len(matched) - count,
                           "mean": mean, "std": sd, "min": min(values) if count else None,
                           "max": max(values) if count else None})
    return {"total_count": len(samples), "matched_count": len(matched),
            "rejected_count": len(samples) - len(matched), "fields": fields,
            "sample_mode": mode, "valid_field": valid_field,
            "valid_value": valid_value if valid_field else "", "statistics": statistics}
