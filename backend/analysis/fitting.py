"""Expression-based constrained fitting with explicit validation and uncertainty."""

import hashlib
import json

import numpy as np
from scipy.optimize import least_squares
from scipy.stats import t

from .expressions import Expression, column_expression, derive, numeric_column

MODELS = {
    "constant": "a", "linear": "a+b*x", "quadratic": "a+b*x+c*x**2",
    "cubic": "a+b*x+c*x**2+d*x**3", "exponential": "exp(a+b*x)",
    "logarithmic": "a+b*log(x)", "power": "exp(a)*x**b",
    "gaussian": "a*exp(-((x-b)/c)**2)+d", "sinusoidal": "a*sin(b*x+c)+d",
    "saturation": "a*x/(b+x)+c",
}


def describe_model(payload):
    formula = payload.get("formula", "") if payload.get("model") == "custom" else MODELS.get(payload.get("model", "linear"), "")
    expression = Expression(formula)
    parameters = sorted(expression.names - {"x"})
    if len(parameters) > 12:
        raise ValueError("最多支持 12 个参数。")
    return {"formula": formula, "parameters": parameters}


def fit_data(payload):
    rows = payload["rows"]
    if not isinstance(rows, list) or len(rows) > 100000 or not all(isinstance(r, dict) for r in rows):
        raise ValueError("最多支持 100000 行对象记录。")
    columns = payload.get("columns") or list(dict.fromkeys(k for row in rows for k in row))
    if payload.get("derived"):
        materialized = derive({**payload, "columns": columns})
        rows, columns = materialized["rows"], materialized["columns"]
    xtext = payload.get("x_expression") or f"[{payload['x']}]"
    ytext = payload.get("y_expression") or f"[{payload['y']}]"
    xall = column_expression(rows, columns, xtext)
    yall = column_expression(rows, columns, ytext)
    weight_name = payload.get("weight", "")
    if weight_name and weight_name not in columns:
        raise ValueError("权重字段不存在。")
    weights = numeric_column(rows, weight_name) if weight_name else np.ones(len(rows))
    keep = np.isfinite(xall) & np.isfinite(yall) & np.isfinite(weights) & (weights > 0)
    indices = np.flatnonzero(keep)
    x, y, weights = xall[keep], yall[keep], weights[keep]
    fraction = float(payload.get("validation", .2))
    if not 0 <= fraction <= .5:
        raise ValueError("验证比例应在 0–50% 之间。")
    validation = np.zeros(len(x), dtype=bool)
    group = payload.get("group", "")
    if group and fraction:
        if group not in columns:
            raise ValueError("批次字段不存在。")
        groups = [str(rows[i].get(group, "")) for i in indices]
        distinct = list(dict.fromkeys(groups))
        if len(distinct) < 2:
            raise ValueError("按批次验证至少需要两个不同批次。")
        chosen = set(distinct[-max(1, int(len(distinct)*fraction)):])
        validation = np.array([g in chosen for g in groups])
    elif fraction:
        count = int(len(x)*fraction)
        if count:
            validation[-count:] = True
    train = ~validation
    tx, ty, tw = x[train], y[train], weights[train]
    description = describe_model(payload)
    formula, names = description["formula"], description["parameters"]
    expression = Expression(formula)
    config = payload.get("parameters", {})
    unknown = set(config) - set(names)
    if unknown:
        raise ValueError("配置包含未知参数：" + ", ".join(sorted(unknown)))
    free = [n for n in names if not config.get(n, {}).get("fixed", False)]
    if len(tx) < max(2, len(free)+1):
        raise ValueError(f"至少需要 {max(2, len(free)+1)} 个有效训练点。")
    if "x" in expression.names and np.ptp(tx) <= 1e-12*max(1., np.max(np.abs(tx))):
        raise ValueError("X 变化不足，无法识别模型。")
    model = payload.get("model", "linear")
    if model in ("logarithmic", "power") and np.any(x <= 0):
        raise ValueError("对数和幂函数要求 X > 0。")
    if model in ("exponential", "power") and np.any(y <= 0):
        raise ValueError("该预设模型要求 Y > 0。")
    initial = {n: 1. for n in names}
    if model in ("constant", "linear", "quadratic", "cubic", "exponential", "power", "logarithmic"):
        degree = {"constant": 0, "quadratic": 2, "cubic": 3}.get(model, 1)
        sx = np.log(tx) if model in ("power", "logarithmic") else tx
        sy = np.log(ty) if model in ("power", "exponential") else ty
        if degree and len(np.unique(sx)) < degree+1:
            raise ValueError("不同 X 数量不足，请降低阶数。")
        coef = np.polynomial.Polynomial.fit(sx, sy, degree).convert().coef if degree else [np.mean(sy)]
        initial.update(dict(zip(names, coef, strict=True)))
    lower, upper = [], []
    for name in names:
        c = config.get(name, {})
        value = float(c.get("initial", initial[name]))
        lo = float(c["lower"]) if c.get("lower") is not None else -np.inf
        hi = float(c["upper"]) if c.get("upper") is not None else np.inf
        if not np.isfinite(value) or np.isnan(lo) or np.isnan(hi) or lo > hi or not lo <= value <= hi:
            raise ValueError(f"参数 {name} 的初值或上下限无效。")
        initial[name] = value
        if name in free:
            if lo == hi:
                raise ValueError(f"参数 {name} 上下限相同，请勾选固定参数。")
            lower.append(lo)
            upper.append(hi)

    def parameter_values(vector):
        return {**initial, **dict(zip(free, vector, strict=True))}

    def predict(values, vector):
        prediction = np.broadcast_to(expression.evaluate({"x": values, **parameter_values(vector)}), values.shape)
        if not np.all(np.isfinite(prediction)):
            raise ValueError("函数在当前参数/数据范围内无定义或溢出，请调整初值或参数边界。")
        return prediction

    def residual(vector):
        return (predict(tx, vector)-ty)*np.sqrt(tw)

    loss = payload.get("loss", "linear")
    scale = float(payload.get("f_scale", 1))
    if loss not in ("linear", "huber", "soft_l1") or not np.isfinite(scale) or scale <= 0:
        raise ValueError("损失函数或稳健尺度无效。")
    vector = np.array([initial[n] for n in free])
    fit = None
    if free:
        fit = least_squares(residual, vector, bounds=(lower, upper), loss=loss, f_scale=scale, max_nfev=2000, x_scale="jac")
        if not fit.success:
            raise ValueError("拟合未收敛：" + fit.message)
        vector = fit.x
    predictions = predict(x, vector)
    errors = predictions-y

    def metrics(mask):
        if not mask.any():
            return None
        e, values = errors[mask], y[mask]
        total = float(np.sum((values-values.mean())**2))
        return {"count": int(mask.sum()), "rmse": float(np.sqrt(np.mean(e**2))), "mae": float(np.mean(np.abs(e))),
                "max_abs": float(np.max(np.abs(e))), "r2": float(1-np.sum(e**2)/total) if total > 0 else None}

    warnings, intervals = [], {}
    if not validation.any():
        warnings.append("尚未独立验证。")
    if np.any((x[validation] < tx.min()) | (x[validation] > tx.max())):
        warnings.append("部分验证点在训练范围外；验证指标包含外推预测，请单独评估适用范围。")
    if fit is not None:
        rank = np.linalg.matrix_rank(fit.jac)
        if rank < len(free):
            warnings.append("参数不可充分识别：雅可比矩阵秩不足，不提供置信区间。")
        elif loss != "linear" or np.any(fit.active_mask):
            warnings.append("稳健拟合或参数触及边界，不提供普通最小二乘置信区间。")
        else:
            dof = len(tx)-len(free)
            covariance = np.linalg.pinv(fit.jac.T@fit.jac)*np.sum(residual(vector)**2)/dof
            radius = t.ppf(.975, dof)*np.sqrt(np.maximum(0, np.diag(covariance)))
            intervals = {n: [float(v-r), float(v+r)] for n, v, r in zip(free, vector, radius, strict=True)}
    grid = np.linspace(float(tx.min()), float(tx.max()), 300)
    params = parameter_values(vector)
    source = {"rows": rows, "derived": payload.get("derived", []), "x": xtext, "y": ytext}
    result = {"model": model, "formula": "y = " + formula, "x": xtext, "y": ytext,
              "coefficients": [float(params[n]) for n in names], "parameters": [{"name": n, "value": float(params[n]), "fixed": n not in free, "ci95": intervals.get(n)} for n in names],
              "coefficient_space": "y", "input_transform": "expression", "range": [float(tx.min()), float(tx.max())],
              "train": metrics(train), "validation": metrics(validation), "skipped": len(rows)-len(x),
              "curve": {"x": grid.tolist(), "y": predict(grid, vector).tolist()},
              "observations": {"x": x.tolist(), "y": y.tolist(), "validation": validation.tolist()},
              "residuals": {"x": x.tolist(), "y": errors.tolist()}, "warnings": warnings,
              "split_policy": f"last groups of {group}" if group else "last valid rows in original order",
              "objective": f"{loss} loss on sqrt(weight) * (prediction - Y); f_scale={scale}",
              "uncertainty": "local linear approximation, 95% Student t; conditional on model and independent errors",
              "source_fingerprint": hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
              "configuration": {k: v for k, v in payload.items() if k != "rows"},
              "extrapolation": "curve limited to training range; validation may extrapolate"}
    try:
        json.dumps(result, allow_nan=False)
    except ValueError as error:
        raise ValueError("结果包含非有限数值，请调整模型或数据量级。") from error
    return result
