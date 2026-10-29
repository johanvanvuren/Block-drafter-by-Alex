"""
Two-Layer Parametric Garment Block Drafting Engine.

Layer 1: Evaluates derived variables, parametric construction points, and construction lines/curves.
Layer 2: Extracts closed cuttable PatternPiece objects with boundary geometry, internal lines/darts,
         grainlines, notches, and automatic seam allowance contours.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from src.core.geometry import (
    BoundingBox,
    CatmullRomSpline2D,
    CubicBezier2D,
    LineSegment2D,
    Point2D,
    circle_circle_intersection,
    circle_line_intersection,
    compute_notch_ticks,
    line_interpolation,
    line_line_intersection,
    offset_closed_polygon,
    perpendicular_point,
    polar_point,
    polygon_area,
    polygon_bounding_box,
    polygon_centroid,
)
from src.core.math_parser import FormulaEvaluationError, MathExpressionParser

CurvePrimitive = Union[LineSegment2D, CubicBezier2D, CatmullRomSpline2D]


@dataclass
class InternalLine:
    """Internal pattern marking (e.g., waist dart, bust dart, balance line, fold line)."""

    id: str
    label: str
    line_type: str  # "dart", "internal", "fold"
    points: List[Point2D]


@dataclass
class Grainline:
    """Pattern piece grainline arrow definition."""

    start: Point2D
    end: Point2D
    label: str = "GRAINLINE"


@dataclass
class NotchMark:
    """Resolved notch ticks along a pattern boundary."""

    id: str
    anchor: Point2D
    ticks: List[Tuple[Point2D, Point2D]]
    count: int = 1


@dataclass
class ResolvedPatternPiece:
    """A closed, cuttable garment pattern piece extracted in Layer 2."""

    id: str
    name: str
    cut_count: int
    seam_allowance_cm: float
    boundary_segments: List[CurvePrimitive]
    boundary_polygon: List[Point2D]
    seam_allowance_polygon: List[Point2D]
    internal_lines: List[InternalLine] = field(default_factory=list)
    grainline: Optional[Grainline] = None
    notches: List[NotchMark] = field(default_factory=list)

    @property
    def net_area_cm2(self) -> float:
        return polygon_area(self.boundary_polygon)

    @property
    def cut_area_cm2(self) -> float:
        if self.seam_allowance_cm > 1e-6 and len(self.seam_allowance_polygon) >= 3:
            return polygon_area(self.seam_allowance_polygon)
        return self.net_area_cm2

    @property
    def active_outer_polygon(self) -> List[Point2D]:
        if self.seam_allowance_cm > 1e-6 and len(self.seam_allowance_polygon) >= 3:
            return self.seam_allowance_polygon
        return self.boundary_polygon

    @property
    def bounding_box(self) -> BoundingBox:
        return polygon_bounding_box(self.active_outer_polygon)

    @property
    def centroid(self) -> Point2D:
        return polygon_centroid(self.boundary_polygon)


@dataclass
class DraftedBlockResult:
    """Complete solved output of a Garment Block instruction set."""

    block_id: str
    name: str
    description: str
    unit: str
    measurements: Dict[str, float]
    derived_variables: Dict[str, float]
    points: Dict[str, Point2D]
    construction_curves: Dict[str, CurvePrimitive]
    pieces: List[ResolvedPatternPiece]

    @property
    def overall_bounding_box(self) -> BoundingBox:
        all_pts: List[Point2D] = list(self.points.values())
        for curve in self.construction_curves.values():
            all_pts.extend(curve.tessellate())
        for piece in self.pieces:
            all_pts.extend(piece.active_outer_polygon)
        return polygon_bounding_box(all_pts)


class DraftingEngine:
    """
    Executes parametric garment block instructions against a set of body measurements.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def load_block_file(file_path: str | Path) -> Dict[str, Any]:
        path = Path(file_path)
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def solve(
        self,
        block_spec: Mapping[str, Any],
        custom_measurements: Optional[Mapping[str, float]] = None,
        seam_allowance_override_cm: Optional[float] = None,
    ) -> DraftedBlockResult:
        """
        Solve all derived variables, construction points, construction curves, and pattern pieces.
        """
        unit = str(block_spec.get("unit", "cm")).lower()

        # 1. Populate required measurements (using defaults if not overridden)
        measurements: Dict[str, float] = {}
        for req in block_spec.get("required_measurements", []):
            key = str(req["key"])
            default_val = float(req.get("default_cm", 0.0))
            measurements[key] = default_val
            # Also register human label for natural expression lookup
            if "label" in req:
                measurements[str(req["label"])] = default_val

        if custom_measurements:
            for k, v in custom_measurements.items():
                measurements[k] = float(v)

        parser = MathExpressionParser(variables=measurements, base_unit=unit)

        # 2. Evaluate derived_variables in order
        derived_vars: Dict[str, float] = {}
        for var_name, expr in block_spec.get("derived_variables", {}).items():
            val = parser.evaluate(expr)
            derived_vars[var_name] = val
            parser.set_variable(var_name, val)

        # 3. Evaluate Layer 1 Construction Points
        points: Dict[str, Point2D] = {}
        for pt_spec in block_spec.get("points", []):
            pt = self._resolve_point(pt_spec, points, parser)
            points[pt.id] = pt
            parser.set_point(pt.id, pt)

        # 4. Evaluate Layer 1 Construction Curves & Lines
        construction_curves: Dict[str, CurvePrimitive] = {}
        for c_spec in block_spec.get("construction", []):
            curve = self._resolve_curve(c_spec, points, parser)
            construction_curves[curve.id] = curve

        # 5. Evaluate Layer 2 Extracted Pattern Pieces
        pieces: List[ResolvedPatternPiece] = []
        for p_spec in block_spec.get("pieces", []):
            piece = self._resolve_piece(
                p_spec,
                points=points,
                construction_curves=construction_curves,
                parser=parser,
                seam_allowance_override_cm=seam_allowance_override_cm,
            )
            pieces.append(piece)

        # Clean measurements dict to primary keys
        clean_measurements = {
            str(req["key"]): parser.variables[str(req["key"])]
            for req in block_spec.get("required_measurements", [])
            if str(req["key"]) in parser.variables
        }
        if not clean_measurements:
            clean_measurements = dict(measurements)

        return DraftedBlockResult(
            block_id=str(block_spec.get("block_id", "custom_block")),
            name=str(block_spec.get("name", "Custom Garment Block")),
            description=str(block_spec.get("description", "")),
            unit=unit,
            measurements=clean_measurements,
            derived_variables=derived_vars,
            points=points,
            construction_curves=construction_curves,
            pieces=pieces,
        )

    def _get_point(self, pt_id: str, points: Mapping[str, Point2D], context: str) -> Point2D:
        if pt_id not in points:
            raise FormulaEvaluationError(f"Unknown point '{pt_id}' referenced in {context}.")
        return points[pt_id]

    def _resolve_point(
        self,
        pt_spec: Mapping[str, Any],
        points: Mapping[str, Point2D],
        parser: MathExpressionParser,
    ) -> Point2D:
        pid = str(pt_spec["id"])
        label = str(pt_spec.get("label", pid))
        ptype = str(pt_spec.get("type", "absolute")).lower()

        if ptype == "absolute":
            x_expr = pt_spec.get("x", 0)
            y_expr = pt_spec.get("y", 0)
            x = parser.evaluate(x_expr)
            y = parser.evaluate(y_expr)
            return Point2D(x, y, pid, label, f"({x_expr}, {y_expr})")

        if ptype == "offset":
            ref_id = str(pt_spec["from"])
            ref_pt = self._get_point(ref_id, points, f"point '{pid}'")
            dx_expr = pt_spec.get("dx", 0)
            dy_expr = pt_spec.get("dy", 0)
            dx = parser.evaluate(dx_expr)
            dy = parser.evaluate(dy_expr)
            return Point2D(
                ref_pt.x + dx,
                ref_pt.y + dy,
                pid,
                label,
                f"from {ref_id} + ({dx_expr}, {dy_expr})",
            )

        if ptype == "coord_ref":
            x_expr = pt_spec.get("x", 0)
            y_expr = pt_spec.get("y", 0)
            x = parser.evaluate(x_expr)
            y = parser.evaluate(y_expr)
            return Point2D(x, y, pid, label, f"coord({x_expr}, {y_expr})")

        if ptype == "polar":
            ref_id = str(pt_spec["from"])
            ref_pt = self._get_point(ref_id, points, f"point '{pid}'")
            len_expr = pt_spec.get("length", 0)
            ang_expr = pt_spec.get("angle", 0)
            length = parser.evaluate(len_expr)
            angle = parser.evaluate(ang_expr)
            return polar_point(
                ref_pt,
                length,
                angle,
                pid,
                label,
                f"polar({ref_id}, len={len_expr}, ang={ang_expr} deg)",
            )

        if ptype == "line_interp":
            line_ids = pt_spec["line"]
            p1 = self._get_point(str(line_ids[0]), points, f"point '{pid}'")
            p2 = self._get_point(str(line_ids[1]), points, f"point '{pid}'")
            t_val = parser.evaluate(pt_spec["t"]) if "t" in pt_spec else None
            dist_val = parser.evaluate(pt_spec["distance"]) if "distance" in pt_spec else None
            summary = (
                f"interp({line_ids[0]}->{line_ids[1]}, t={pt_spec.get('t')})"
                if "t" in pt_spec
                else f"interp({line_ids[0]}->{line_ids[1]}, dist={pt_spec.get('distance')})"
            )
            return line_interpolation(p1, p2, t=t_val, distance=dist_val, point_id=pid, label=label, formula_summary=summary)

        if ptype == "perpendicular":
            line_ids = pt_spec["line"]
            p1 = self._get_point(str(line_ids[0]), points, f"point '{pid}'")
            p2 = self._get_point(str(line_ids[1]), points, f"point '{pid}'")
            from_id = str(pt_spec.get("from", line_ids[0]))
            from_pt = self._get_point(from_id, points, f"point '{pid}'")
            length = parser.evaluate(pt_spec["length"])
            side = str(pt_spec.get("side", "left"))
            return perpendicular_point(
                p1,
                p2,
                from_pt,
                length,
                side=side,
                point_id=pid,
                label=label,
                formula_summary=f"perp({line_ids[0]}->{line_ids[1]} from {from_id}, {pt_spec['length']})",
            )

        if ptype == "line_intersection":
            l1 = pt_spec["line1"]
            l2 = pt_spec["line2"]
            p1 = self._get_point(str(l1[0]), points, f"point '{pid}'")
            p2 = self._get_point(str(l1[1]), points, f"point '{pid}'")
            p3 = self._get_point(str(l2[0]), points, f"point '{pid}'")
            p4 = self._get_point(str(l2[1]), points, f"point '{pid}'")
            return line_line_intersection(
                p1,
                p2,
                p3,
                p4,
                point_id=pid,
                label=label,
                formula_summary=f"intersect({l1[0]}-{l1[1]}, {l2[0]}-{l2[1]})",
            )

        if ptype == "circle_line_intersection":
            center = self._get_point(str(pt_spec["center"]), points, f"point '{pid}'")
            radius = parser.evaluate(pt_spec["radius"])
            line_ids = pt_spec["line"]
            lp1 = self._get_point(str(line_ids[0]), points, f"point '{pid}'")
            lp2 = self._get_point(str(line_ids[1]), points, f"point '{pid}'")
            select = str(pt_spec.get("select", "first"))
            return circle_line_intersection(
                center,
                radius,
                lp1,
                lp2,
                select=select,
                point_id=pid,
                label=label,
                formula_summary=f"circle_line({pt_spec['center']}, r={pt_spec['radius']})",
            )

        if ptype == "circle_circle_intersection":
            c1 = self._get_point(str(pt_spec["center1"]), points, f"point '{pid}'")
            r1 = parser.evaluate(pt_spec["radius1"])
            c2 = self._get_point(str(pt_spec["center2"]), points, f"point '{pid}'")
            r2 = parser.evaluate(pt_spec["radius2"])
            select = str(pt_spec.get("select", "first"))
            return circle_circle_intersection(
                c1,
                r1,
                c2,
                r2,
                select=select,
                point_id=pid,
                label=label,
                formula_summary=f"circle_circle({pt_spec['center1']}, {pt_spec['center2']})",
            )

        raise FormulaEvaluationError(f"Unsupported point type '{ptype}' for point '{pid}'.")

    def _resolve_curve(
        self,
        c_spec: Mapping[str, Any],
        points: Mapping[str, Point2D],
        parser: MathExpressionParser,
    ) -> CurvePrimitive:
        cid = str(c_spec["id"])
        label = str(c_spec.get("label", cid))
        ctype = str(c_spec["type"]).lower()

        if ctype == "line":
            p0 = self._get_point(str(c_spec["from"]), points, f"curve '{cid}'")
            p1 = self._get_point(str(c_spec["to"]), points, f"curve '{cid}'")
            return LineSegment2D(p0, p1, cid, label)

        if ctype == "cubic_bezier":
            p0 = self._get_point(str(c_spec["p0"]), points, f"curve '{cid}'")
            p3 = self._get_point(str(c_spec["p3"]), points, f"curve '{cid}'")
            if "p1" in c_spec and "p2" in c_spec:
                p1 = self._get_point(str(c_spec["p1"]), points, f"curve '{cid}'")
                p2 = self._get_point(str(c_spec["p2"]), points, f"curve '{cid}'")
                return CubicBezier2D(p0, p1, p2, p3, cid, label)
            h1_ang = parser.evaluate(c_spec.get("handle1_angle", 0))
            h1_len = parser.evaluate(c_spec.get("handle1_length", p0.distance_to(p3) / 3.0))
            h2_ang = parser.evaluate(c_spec.get("handle2_angle", 180))
            h2_len = parser.evaluate(c_spec.get("handle2_length", p0.distance_to(p3) / 3.0))
            return CubicBezier2D.from_polar_handles(
                p0, p3, h1_ang, h1_len, h2_ang, h2_len, curve_id=cid, label=label
            )

        if ctype == "spline":
            knot_ids = c_spec.get("points", [])
            knots = [self._get_point(str(kid), points, f"spline '{cid}'") for kid in knot_ids]
            return CatmullRomSpline2D(knots=knots, id=cid, label=label)

        raise FormulaEvaluationError(f"Unsupported construction curve type '{ctype}' for '{cid}'.")

    def _resolve_piece(
        self,
        p_spec: Mapping[str, Any],
        points: Mapping[str, Point2D],
        construction_curves: Mapping[str, CurvePrimitive],
        parser: MathExpressionParser,
        seam_allowance_override_cm: Optional[float] = None,
    ) -> ResolvedPatternPiece:
        piece_id = str(p_spec["id"])
        name = str(p_spec.get("name", piece_id))
        cut_count = int(p_spec.get("cut_count", 1))
        sa_cm = (
            float(seam_allowance_override_cm)
            if seam_allowance_override_cm is not None
            else parser.evaluate(p_spec.get("seam_allowance_cm", 1.0))
        )

        boundary_segments: List[CurvePrimitive] = []
        boundary_polygon: List[Point2D] = []

        for seg_spec in p_spec.get("boundary", []):
            stype = str(seg_spec["type"]).lower()
            if stype == "line":
                p0 = self._get_point(str(seg_spec["from"]), points, f"piece '{piece_id}' boundary")
                p1 = self._get_point(str(seg_spec["to"]), points, f"piece '{piece_id}' boundary")
                seg = LineSegment2D(p0, p1)
            elif stype == "curve_ref":
                cid = str(seg_spec["curve_id"])
                if cid not in construction_curves:
                    raise FormulaEvaluationError(
                        f"Unknown curve_id '{cid}' in piece '{piece_id}' boundary."
                    )
                base_curve = construction_curves[cid]
                seg = base_curve.reversed() if seg_spec.get("reverse", False) else base_curve
            elif stype in ("cubic_bezier", "spline"):
                seg = self._resolve_curve(
                    {"id": f"{piece_id}_edge", **seg_spec},
                    points,
                    parser,
                )
            else:
                raise FormulaEvaluationError(
                    f"Unsupported boundary segment type '{stype}' in piece '{piece_id}'."
                )

            boundary_segments.append(seg)
            tess = seg.tessellate()
            if boundary_polygon and tess:
                boundary_polygon.extend(tess[1:])
            else:
                boundary_polygon.extend(tess)

        seam_allowance_polygon = (
            offset_closed_polygon(boundary_polygon, sa_cm) if sa_cm > 1e-6 else []
        )

        # Resolve internal lines & darts
        internal_lines: List[InternalLine] = []
        for il_spec in p_spec.get("internal_lines", []):
            il_pts = [
                self._get_point(str(pid), points, f"piece '{piece_id}' internal line")
                for pid in il_spec.get("points", [])
            ]
            internal_lines.append(
                InternalLine(
                    id=str(il_spec["id"]),
                    label=str(il_spec.get("label", il_spec["id"])),
                    line_type=str(il_spec.get("type", "internal")),
                    points=il_pts,
                )
            )

        # Resolve grainline
        grainline: Optional[Grainline] = None
        if "grainline" in p_spec and p_spec["grainline"]:
            gl_spec = p_spec["grainline"]
            g_start = self._get_point(str(gl_spec["from"]), points, f"piece '{piece_id}' grainline")
            g_end = self._get_point(str(gl_spec["to"]), points, f"piece '{piece_id}' grainline")
            grainline = Grainline(
                start=g_start,
                end=g_end,
                label=str(gl_spec.get("label", "GRAINLINE")),
            )

        # Resolve notches
        notches: List[NotchMark] = []
        for n_spec in p_spec.get("notches", []):
            anchor = self._get_point(str(n_spec["point"]), points, f"piece '{piece_id}' notch")
            e_from = self._get_point(
                str(n_spec.get("edge_from", n_spec["point"])), points, f"piece '{piece_id}' notch"
            )
            e_to = self._get_point(
                str(n_spec.get("edge_to", n_spec["point"])), points, f"piece '{piece_id}' notch"
            )
            length_cm = float(n_spec.get("length_cm", 0.5))
            count = int(n_spec.get("count", 1))
            ticks = compute_notch_ticks(
                anchor,
                e_from,
                e_to,
                boundary_polygon,
                length_cm=length_cm,
                count=count,
            )
            notches.append(
                NotchMark(
                    id=str(n_spec.get("id", f"notch_{n_spec['point']}")),
                    anchor=anchor,
                    ticks=ticks,
                    count=count,
                )
            )

        return ResolvedPatternPiece(
            id=piece_id,
            name=name,
            cut_count=cut_count,
            seam_allowance_cm=sa_cm,
            boundary_segments=boundary_segments,
            boundary_polygon=boundary_polygon,
            seam_allowance_polygon=seam_allowance_polygon,
            internal_lines=internal_lines,
            grainline=grainline,
            notches=notches,
        )
