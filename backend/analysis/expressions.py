"""Bounded arithmetic AST interpreter shared by derived columns and fitting.

No eval/exec, attribute access, indexing, Python calls, or code compilation.
"""

import ast
import operator
import re

import numpy as np

def direction_atan2(y, x):
    return np.where((y == 0) & (x == 0), np.nan, np.arctan2(y, x))


FUNCTIONS = {"sin": np.sin, "cos": np.cos, "tan": np.tan, "exp": np.exp,
             "log": np.log, "ln": np.log, "sqrt": np.sqrt, "abs": np.abs,
             "atan2": direction_atan2}
CONSTANTS = {"pi": np.pi, "e": np.e}
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.Pow: np.power}


class Expression:
    def __init__(self, text, *, columns=False):
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise ValueError("表达式不能为空且最多 1000 字符。")
        self.text = text
        self.columns = {}

        def substitute(match):
            symbol = f"__column_{len(self.columns)}"
            self.columns[symbol] = match[1]
            return symbol

        translated = re.sub(r"\[([^\[\]]+)\]", substitute, text) if columns else text
        try:
            self.tree = ast.parse(translated, mode="eval").body
        except (SyntaxError, RecursionError) as error:
            raise ValueError("表达式语法错误。幂使用 **，列名使用 [列名]。") from error
        if len(list(ast.walk(self.tree))) > 150:
            raise ValueError("表达式过于复杂。")
        self.names = set()
        self._validate(self.tree, 0)
        if columns and self.names - set(self.columns):
            raise ValueError("列运算只能使用 [列名]、常数和白名单数学函数。")

    def _validate(self, node, depth):
        if depth > 24:
            raise ValueError("表达式嵌套过深。")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if not np.isfinite(float(node.value)):
                raise ValueError("常数必须有限。")
        elif isinstance(node, ast.Name):
            if node.id not in CONSTANTS:
                if node.id.startswith("_") and node.id not in self.columns:
                    raise ValueError("不允许此变量名。")
                self.names.add(node.id)
        elif isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            self._validate(node.left, depth + 1)
            self._validate(node.right, depth + 1)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            self._validate(node.operand, depth + 1)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in FUNCTIONS and not node.keywords):
            arity = 2 if node.func.id == "atan2" else 1
            if len(node.args) != arity:
                raise ValueError(f"{node.func.id} 需要 {arity} 个参数。")
            for argument in node.args:
                self._validate(argument, depth + 1)
        else:
            raise ValueError("仅允许加减乘除、**、括号，以及 sin/cos/tan/exp/log/sqrt/abs/atan2。")

    def evaluate(self, variables):
        def visit(node):
            if isinstance(node, ast.Constant):
                return np.float64(node.value)
            if isinstance(node, ast.Name):
                return CONSTANTS[node.id] if node.id in CONSTANTS else variables[node.id]
            if isinstance(node, ast.BinOp):
                return BINARY[type(node.op)](visit(node.left), visit(node.right))
            if isinstance(node, ast.UnaryOp):
                return -visit(node.operand) if isinstance(node.op, ast.USub) else visit(node.operand)
            return FUNCTIONS[node.func.id](*(visit(arg) for arg in node.args))
        with np.errstate(all="ignore"):
            return np.asarray(visit(self.tree), dtype=float)


def numeric_column(rows, name):
    def convert(row):
        try:
            value = row.get(name)
            return float(value) if value is not None and not isinstance(value, bool) else np.nan
        except (ValueError, TypeError):
            return np.nan
    return np.asarray([convert(row) for row in rows], dtype=float)


def column_expression(rows, columns, text):
    expression = Expression(text, columns=True)
    missing = set(expression.columns.values()) - set(columns)
    if missing:
        raise ValueError("字段不存在：" + ", ".join(sorted(missing)))
    variables = {alias: numeric_column(rows, name) for alias, name in expression.columns.items()}
    result = np.broadcast_to(expression.evaluate(variables), (len(rows),)).copy()
    for values in variables.values():
        result[~np.isfinite(values)] = np.nan
    return result


def derive(payload):
    rows, columns = payload["rows"], payload["columns"]
    definitions = payload.get("derived", [])
    if not isinstance(rows, list) or len(rows) > 100000 or len(definitions) > 64:
        raise ValueError("最多 100000 行、64 个派生列。")
    if not all(isinstance(r, dict) for r in rows):
        raise ValueError("记录必须为对象。")
    names = [d["name"] for d in definitions]
    if any(not isinstance(n, str) or not n.strip() for n in names) or len(set(names)) != len(names):
        raise ValueError("派生列名称不能为空或重复。")
    expressions = {d["name"]: Expression(d["expression"], columns=True) for d in definitions}
    all_columns = list(dict.fromkeys([*columns, *names]))
    ordered, visiting = [], set()

    def order(name):
        if name in visiting:
            raise ValueError("派生列存在循环依赖：" + name)
        if name in ordered:
            return
        visiting.add(name)
        for dependency in expressions[name].columns.values():
            if dependency not in all_columns:
                raise ValueError("字段不存在：" + dependency)
            if dependency in expressions:
                order(dependency)
        visiting.remove(name)
        ordered.append(name)

    for name in names:
        order(name)
    result = [r.copy() for r in rows]
    diagnostics = {}
    for name in ordered:
        values = column_expression(result, all_columns, expressions[name].text)
        finite = np.isfinite(values)
        diagnostics[name] = {"valid": int(finite.sum()), "invalid": int((~finite).sum())}
        for row, value, valid in zip(result, values, finite, strict=True):
            row[name] = float(value) if valid else None
    return {"rows": result, "columns": all_columns, "derived": definitions, "diagnostics": diagnostics}
