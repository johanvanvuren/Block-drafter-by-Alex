"""
Safe AST-based Mathematical & Geometric Expression Parser for Garment Block Drafting.

Supports:
- Standard arithmetic operators: +, -, *, /, **, unary +/-
- Unit-suffixed numeric literals: 1.5cm, 12mm, 0.5in (normalized to cm)
- Measurement & derived variable lookup: waist, hips, nape_to_waist, etc.
- Point coordinate attribute access: A.x, A.y, B_Side_Waist.x
- Geometric query functions: dist(P1, P2), angle(P1, P2), dx(P1, P2), dy(P1, P2)
- Trigonometric & math functions: sqrt, sin, cos, tan, asin, acos, atan2, abs, min, max
- Human-readable instruction sentence parser for natural drafting phrases.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple


UNIT_TO_CM: Dict[str, float] = {
    "cm": 1.0,
    "mm": 0.1,
    "m": 100.0,
    "in": 2.54,
    "inch": 2.54,
    "inches": 2.54,
}

# Regex matching numeric literals followed immediately by unit suffix: e.g. "1.5cm", "10mm", ".5in"
_UNIT_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(\d+(?:\.\d+)?|\.\d+)\s*(cm|mm|inches|inch|in|m)\b",
    re.IGNORECASE,
)


class FormulaEvaluationError(ValueError):
    """Raised when a drafting formula cannot be parsed or evaluated."""


@dataclass(frozen=True)
class PointRef:
    """Lightweight 2D point coordinate container exposed to formula expressions."""

    x: float
    y: float


class MathExpressionParser:
    """
    Safe AST expression evaluator tailored for parametric garment pattern drafting.
    All lengths are normalized to centimeters (cm) by default.
    """

    _BINARY_OPS: Dict[type, Callable[[float, float], float]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
    }

    _UNARY_OPS: Dict[type, Callable[[float], float]] = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    def __init__(
        self,
        variables: Optional[Mapping[str, float]] = None,
        points: Optional[Mapping[str, Tuple[float, float] | PointRef | Any]] = None,
        base_unit: str = "cm",
    ) -> None:
        self.base_unit = base_unit.lower()
        self.variables: Dict[str, float] = {}
        if variables:
            for k, v in variables.items():
                self.set_variable(k, float(v))

        self.points: Dict[str, PointRef] = {}
        if points:
            for k, pt in points.items():
                self.set_point(k, pt)

    def set_variable(self, name: str, value: float) -> None:
        """Register a variable under both its exact name and normalized snake_case name."""
        val = float(value)
        self.variables[name] = val
        normalized = self.normalize_identifier(name)
        self.variables[normalized] = val

    def set_point(self, point_id: str, pt: Tuple[float, float] | PointRef | Any) -> None:
        """Register a resolved 2D point for attribute (P.x, P.y) and function (dist(A, B)) use."""
        if isinstance(pt, PointRef):
            self.points[point_id] = pt
        elif hasattr(pt, "x") and hasattr(pt, "y"):
            self.points[point_id] = PointRef(float(pt.x), float(pt.y))
        elif isinstance(pt, (tuple, list)) and len(pt) >= 2:
            self.points[point_id] = PointRef(float(pt[0]), float(pt[1]))
        else:
            raise TypeError(f"Unsupported point representation for '{point_id}': {pt!r}")

    @staticmethod
    def normalize_identifier(text: str) -> str:
        """Convert human labels like 'Nape to Waist' into 'nape_to_waist'."""
        cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", text.strip())
        return cleaned.strip("_").lower()

    def preprocess_expression(self, expr: str) -> str:
        """
        Convert unit-suffixed numbers (e.g. '1.5cm', '12mm', '2in') into numeric values in base_unit,
        and normalize multi-word variable references where applicable.
        """
        target_scale = UNIT_TO_CM.get(self.base_unit, 1.0)

        def _replace_unit(match: re.Match[str]) -> str:
            number_str, unit_str = match.group(1), match.group(2).lower()
            value_cm = float(number_str) * UNIT_TO_CM[unit_str]
            converted = value_cm / target_scale
            return f"({converted:.8g})"

        processed = _UNIT_LITERAL_RE.sub(_replace_unit, expr.strip())

        # Replace known multi-word variable names (longest first) if written with spaces
        multi_word_keys = sorted(
            [k for k in self.variables if " " in k],
            key=len,
            reverse=True,
        )
        for key in multi_word_keys:
            pattern = re.compile(re.escape(key), re.IGNORECASE)
            processed = pattern.sub(self.normalize_identifier(key), processed)

        return processed

    def evaluate(self, expression: str | int | float) -> float:
        """Evaluate a mathematical or geometric formula into a float value (in base_unit)."""
        if isinstance(expression, (int, float)):
            return float(expression)

        if not isinstance(expression, str) or not expression.strip():
            raise FormulaEvaluationError("Formula expression cannot be empty.")

        preprocessed = self.preprocess_expression(expression)
        try:
            tree = ast.parse(preprocessed, mode="eval")
        except SyntaxError as exc:
            raise FormulaEvaluationError(
                f"Syntax error in formula '{expression}' (preprocessed as '{preprocessed}'): {exc}"
            ) from exc

        try:
            result = self._eval_node(tree.body)
        except FormulaEvaluationError:
            raise
        except Exception as exc:
            raise FormulaEvaluationError(
                f"Failed evaluating formula '{expression}': {exc}"
            ) from exc

        if not isinstance(result, (int, float)) or math.isnan(result) or math.isinf(result):
            raise FormulaEvaluationError(
                f"Formula '{expression}' did not evaluate to a finite number (got {result!r})."
            )
        return float(result)

    def _resolve_point_arg(self, node: ast.AST) -> PointRef:
        """Resolve an AST argument node to a registered PointRef."""
        if isinstance(node, ast.Name):
            pid = node.id
            if pid in self.points:
                return self.points[pid]
            raise FormulaEvaluationError(f"Unknown point '{pid}' in geometric function call.")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            pid = node.value
            if pid in self.points:
                return self.points[pid]
            raise FormulaEvaluationError(f"Unknown point '{pid}' in geometric function call.")
        raise FormulaEvaluationError(
            f"Expected a point identifier (e.g., A, B) in geometric function, got {ast.dump(node)}"
        )

    def _eval_node(self, node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise FormulaEvaluationError(f"Unsupported constant value: {node.value!r}")

        if isinstance(node, ast.Name):
            ident = node.id
            if ident in self.variables:
                return self.variables[ident]
            norm = self.normalize_identifier(ident)
            if norm in self.variables:
                return self.variables[norm]
            if ident == "pi":
                return math.pi
            raise FormulaEvaluationError(
                f"Unknown variable '{ident}'. Available variables: {sorted(self.variables.keys())}"
            )

        if isinstance(node, ast.Attribute):
            # Point attribute access: e.g. A.x or A.y
            if isinstance(node.value, ast.Name):
                pt_name = node.value.id
                if pt_name not in self.points:
                    raise FormulaEvaluationError(
                        f"Unknown point '{pt_name}' referenced in '{pt_name}.{node.attr}'."
                    )
                pt = self.points[pt_name]
                if node.attr == "x":
                    return pt.x
                if node.attr == "y":
                    return pt.y
                raise FormulaEvaluationError(
                    f"Point '{pt_name}' only supports '.x' and '.y' attributes, not '.{node.attr}'."
                )
            raise FormulaEvaluationError(f"Unsupported attribute access: {ast.dump(node)}")

        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in self._BINARY_OPS:
                raise FormulaEvaluationError(f"Unsupported binary operator: {op_type.__name__}")
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            if op_type is ast.Div and abs(right) < 1e-12:
                raise FormulaEvaluationError("Division by zero in formula.")
            return float(self._BINARY_OPS[op_type](left, right))

        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in self._UNARY_OPS:
                raise FormulaEvaluationError(f"Unsupported unary operator: {op_type.__name__}")
            operand = self._eval_node(node.operand)
            return float(self._UNARY_OPS[op_type](operand))

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise FormulaEvaluationError("Only direct function calls are allowed in formulas.")
            fname = node.func.id.lower()

            # Geometric point-to-point functions
            if fname in ("dist", "distance"):
                if len(node.args) != 2:
                    raise FormulaEvaluationError("dist(P1, P2) requires exactly 2 point arguments.")
                p1 = self._resolve_point_arg(node.args[0])
                p2 = self._resolve_point_arg(node.args[1])
                return math.hypot(p2.x - p1.x, p2.y - p1.y)

            if fname == "dx":
                if len(node.args) != 2:
                    raise FormulaEvaluationError("dx(P1, P2) requires exactly 2 point arguments.")
                p1 = self._resolve_point_arg(node.args[0])
                p2 = self._resolve_point_arg(node.args[1])
                return p2.x - p1.x

            if fname == "dy":
                if len(node.args) != 2:
                    raise FormulaEvaluationError("dy(P1, P2) requires exactly 2 point arguments.")
                p1 = self._resolve_point_arg(node.args[0])
                p2 = self._resolve_point_arg(node.args[1])
                return p2.y - p1.y

            if fname == "angle":
                if len(node.args) != 2:
                    raise FormulaEvaluationError("angle(P1, P2) requires exactly 2 point arguments.")
                p1 = self._resolve_point_arg(node.args[0])
                p2 = self._resolve_point_arg(node.args[1])
                return math.degrees(math.atan2(p2.y - p1.y, p2.x - p1.x))

            # Standard scalar math functions
            scalar_args = [self._eval_node(arg) for arg in node.args]

            math_funcs: Dict[str, Callable[..., float]] = {
                "sqrt": math.sqrt,
                "abs": abs,
                "min": min,
                "max": max,
                "round": round,
                "sin": lambda deg: math.sin(math.radians(deg)),
                "cos": lambda deg: math.cos(math.radians(deg)),
                "tan": lambda deg: math.tan(math.radians(deg)),
                "asin": lambda val: math.degrees(math.asin(val)),
                "acos": lambda val: math.degrees(math.acos(val)),
                "atan2": lambda y, x: math.degrees(math.atan2(y, x)),
                "deg": math.degrees,
                "rad": math.radians,
            }
            if fname not in math_funcs:
                raise FormulaEvaluationError(f"Unsupported function '{fname}' in formula.")
            return float(math_funcs[fname](*scalar_args))

        raise FormulaEvaluationError(f"Unsupported syntax element in formula: {type(node).__name__}")


def parse_natural_instruction_line(sentence: str) -> Dict[str, Any]:
    """
    Utility parser that converts human-readable drafting sentences into canonical JSON point definitions.

    Supported patterns include:
    - "Point A is the origin (0,0)."
    - "Point B is (Waist / 4 + 1cm) on the X-axis from Point A."
    - "Point C is (Nape to Waist) on the Y-axis from Point B."
    - "Point D is offset (2cm, -1.5cm) from Point B."
    - "Point E is 12cm at angle 18 deg from Point A."
    """
    text = sentence.strip().rstrip(".")

    # 1. Origin / absolute coordinates: "Point A is the origin (0,0)" or "Point A is (x, y)"
    m_origin = re.match(
        r"^Point\s+([A-Za-z0-9_]+)\s+is\s+(?:the\s+origin\s*)?\(\s*([^,]+)\s*,\s*([^)]+)\s*\)$",
        text,
        re.IGNORECASE,
    )
    if m_origin:
        pid, x_expr, y_expr = m_origin.group(1), m_origin.group(2).strip(), m_origin.group(3).strip()
        return {"id": pid, "label": f"Point {pid}", "type": "absolute", "x": x_expr, "y": y_expr}

    # 2. Axis offset: "Point B is (Waist / 4 + 1cm) on the X-axis from Point A"
    m_axis = re.match(
        r"^Point\s+([A-Za-z0-9_]+)\s+is\s+\(?(.+?)\)?\s+on\s+the\s+([XY])-axis\s+from\s+Point\s+([A-Za-z0-9_]+)$",
        text,
        re.IGNORECASE,
    )
    if m_axis:
        pid, formula, axis, ref_pt = (
            m_axis.group(1),
            m_axis.group(2).strip(),
            m_axis.group(3).upper(),
            m_axis.group(4),
        )
        return {
            "id": pid,
            "label": f"Point {pid}",
            "type": "offset",
            "from": ref_pt,
            "dx": formula if axis == "X" else "0",
            "dy": formula if axis == "Y" else "0",
        }

    # 3. 2D Offset: "Point D is offset (dx, dy) from Point B"
    m_offset = re.match(
        r"^Point\s+([A-Za-z0-9_]+)\s+is\s+offset\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)\s+from\s+Point\s+([A-Za-z0-9_]+)$",
        text,
        re.IGNORECASE,
    )
    if m_offset:
        pid, dx_expr, dy_expr, ref_pt = (
            m_offset.group(1),
            m_offset.group(2).strip(),
            m_offset.group(3).strip(),
            m_offset.group(4),
        )
        return {
            "id": pid,
            "label": f"Point {pid}",
            "type": "offset",
            "from": ref_pt,
            "dx": dx_expr,
            "dy": dy_expr,
        }

    # 4. Polar: "Point E is (12cm) at angle (18) from Point A"
    m_polar = re.match(
        r"^Point\s+([A-Za-z0-9_]+)\s+is\s+\(?(.+?)\)?\s+at\s+angle\s+\(?([+-]?\d+(?:\.\d+)?)\)?(?:\s*deg(?:rees)?)?\s+from\s+Point\s+([A-Za-z0-9_]+)$",
        text,
        re.IGNORECASE,
    )
    if m_polar:
        pid, length_expr, angle_expr, ref_pt = (
            m_polar.group(1),
            m_polar.group(2).strip(),
            m_polar.group(3).strip(),
            m_polar.group(4),
        )
        return {
            "id": pid,
            "label": f"Point {pid}",
            "type": "polar",
            "from": ref_pt,
            "length": length_expr,
            "angle": angle_expr,
        }

    raise FormulaEvaluationError(f"Could not parse natural instruction sentence: '{sentence}'")
