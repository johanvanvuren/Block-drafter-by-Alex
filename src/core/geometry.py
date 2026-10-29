"""
2D Computational Geometry Engine for Garment Pattern Drafting.

Provides:
- Point2D, LineSegment2D, CubicBezier2D, CatmullRomSpline2D primitives
- Line-line, circle-line, and circle-circle intersection solvers
- Perpendicular projection and offset helpers
- Smooth spline to cubic Bezier conversion and adaptive polyline tessellation
- Closed polygon area (Shoelace formula), centroid, bounding box, rotation, and translation
- Outward miter-limited polygon offsetting for automatic Seam Allowance generation
- Inward perpendicular Notch tick calculation
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Point2D:
    """Immutable 2D coordinate with optional drafting metadata."""

    x: float
    y: float
    id: str = ""
    label: str = ""
    formula_summary: str = ""

    def distance_to(self, other: Point2D) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def translated(self, dx: float, dy: float) -> Point2D:
        return Point2D(self.x + dx, self.y + dy, self.id, self.label, self.formula_summary)

    def rotated(self, angle_deg: float, origin: Optional[Point2D] = None) -> Point2D:
        ox = origin.x if origin else 0.0
        oy = origin.y if origin else 0.0
        rad = math.radians(angle_deg)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        dx, dy = self.x - ox, self.y - oy
        return Point2D(
            ox + dx * cos_a - dy * sin_a,
            oy + dx * sin_a + dy * cos_a,
            self.id,
            self.label,
            self.formula_summary,
        )

    def as_tuple(self) -> Tuple[float, float]:
        return (self.x, self.y)


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned 2D bounding box in pattern units (cm)."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return max(0.0, self.max_x - self.min_x)

    @property
    def height(self) -> float:
        return max(0.0, self.max_y - self.min_y)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> Point2D:
        return Point2D((self.min_x + self.max_x) * 0.5, (self.min_y + self.max_y) * 0.5)


@dataclass
class LineSegment2D:
    """Straight 2D line segment between two points."""

    p0: Point2D
    p1: Point2D
    id: str = ""
    label: str = ""

    def tessellate(self, steps: int = 1) -> List[Point2D]:
        return [self.p0, self.p1]

    def reversed(self) -> LineSegment2D:
        return LineSegment2D(self.p1, self.p0, self.id, self.label)


@dataclass
class CubicBezier2D:
    """Cubic Bezier curve defined by four control points (p0, p1, p2, p3)."""

    p0: Point2D
    p1: Point2D
    p2: Point2D
    p3: Point2D
    id: str = ""
    label: str = ""

    @classmethod
    def from_polar_handles(
        cls,
        p0: Point2D,
        p3: Point2D,
        handle1_angle_deg: float,
        handle1_length: float,
        handle2_angle_deg: float,
        handle2_length: float,
        curve_id: str = "",
        label: str = "",
    ) -> CubicBezier2D:
        p1 = polar_point(p0, handle1_length, handle1_angle_deg)
        p2 = polar_point(p3, handle2_length, handle2_angle_deg)
        return cls(p0=p0, p1=p1, p2=p2, p3=p3, id=curve_id, label=label)

    def evaluate_at(self, t: float) -> Point2D:
        u = 1.0 - t
        b0 = u * u * u
        b1 = 3.0 * u * u * t
        b2 = 3.0 * u * t * t
        b3 = t * t * t
        x = b0 * self.p0.x + b1 * self.p1.x + b2 * self.p2.x + b3 * self.p3.x
        y = b0 * self.p0.y + b1 * self.p1.y + b2 * self.p2.y + b3 * self.p3.y
        return Point2D(x, y)

    def tessellate(self, steps: int = 32) -> List[Point2D]:
        return [self.evaluate_at(i / steps) for i in range(steps + 1)]

    def reversed(self) -> CubicBezier2D:
        return CubicBezier2D(self.p3, self.p2, self.p1, self.p0, self.id, self.label)


@dataclass
class CatmullRomSpline2D:
    """Smooth spline passing through 3 or more points, convertible to CubicBeziers."""

    knots: List[Point2D]
    id: str = ""
    label: str = ""
    tension: float = 0.5

    def to_beziers(self) -> List[CubicBezier2D]:
        n = len(self.knots)
        if n < 2:
            return []
        if n == 2:
            p0, p1 = self.knots[0], self.knots[1]
            c1 = line_interpolation(p0, p1, t=1.0 / 3.0)
            c2 = line_interpolation(p0, p1, t=2.0 / 3.0)
            return [CubicBezier2D(p0, c1, c2, p1, self.id, self.label)]

        # Phantom endpoints for natural end tangents
        pts = [
            Point2D(2 * self.knots[0].x - self.knots[1].x, 2 * self.knots[0].y - self.knots[1].y),
            *self.knots,
            Point2D(
                2 * self.knots[-1].x - self.knots[-2].x,
                2 * self.knots[-1].y - self.knots[-2].y,
            ),
        ]

        beziers: List[CubicBezier2D] = []
        alpha = 1.0 / 6.0
        for i in range(1, len(pts) - 2):
            p_prev, p_curr, p_next, p_next2 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
            c1 = Point2D(
                p_curr.x + (p_next.x - p_prev.x) * alpha,
                p_curr.y + (p_next.y - p_prev.y) * alpha,
            )
            c2 = Point2D(
                p_next.x - (p_next2.x - p_curr.x) * alpha,
                p_next.y - (p_next2.y - p_curr.y) * alpha,
            )
            beziers.append(CubicBezier2D(p_curr, c1, c2, p_next, f"{self.id}_seg{i}", self.label))
        return beziers

    def tessellate(self, steps_per_segment: int = 24) -> List[Point2D]:
        beziers = self.to_beziers()
        if not beziers:
            return list(self.knots)
        result: List[Point2D] = []
        for idx, bez in enumerate(beziers):
            seg_pts = bez.tessellate(steps_per_segment)
            if idx > 0:
                seg_pts = seg_pts[1:]
            result.extend(seg_pts)
        return result

    def reversed(self) -> CatmullRomSpline2D:
        return CatmullRomSpline2D(list(reversed(self.knots)), self.id, self.label, self.tension)


# ---------------------------------------------------------------------------
# Core Geometric Construction Solvers
# ---------------------------------------------------------------------------


def polar_point(
    origin: Point2D,
    length: float,
    angle_deg: float,
    point_id: str = "",
    label: str = "",
    formula_summary: str = "",
) -> Point2D:
    """Compute a point at (length, angle_deg) from origin (0 deg = +X, 90 deg = +Y)."""
    rad = math.radians(angle_deg)
    return Point2D(
        x=origin.x + length * math.cos(rad),
        y=origin.y + length * math.sin(rad),
        id=point_id,
        label=label,
        formula_summary=formula_summary,
    )


def line_interpolation(
    p1: Point2D,
    p2: Point2D,
    t: Optional[float] = None,
    distance: Optional[float] = None,
    point_id: str = "",
    label: str = "",
    formula_summary: str = "",
) -> Point2D:
    """Compute a point along line P1->P2 by normalized ratio t or signed distance from P1."""
    seg_len = p1.distance_to(p2)
    if seg_len < 1e-12:
        return Point2D(p1.x, p1.y, point_id, label, formula_summary)

    ratio = t if t is not None else (distance / seg_len if distance is not None else 0.5)
    return Point2D(
        x=p1.x + (p2.x - p1.x) * ratio,
        y=p1.y + (p2.y - p1.y) * ratio,
        id=point_id,
        label=label,
        formula_summary=formula_summary,
    )


def perpendicular_point(
    line_p1: Point2D,
    line_p2: Point2D,
    from_point: Point2D,
    length: float,
    side: str = "left",
    point_id: str = "",
    label: str = "",
    formula_summary: str = "",
) -> Point2D:
    """Compute a point at distance `length` perpendicular to line (line_p1 -> line_p2) from `from_point`."""
    dx = line_p2.x - line_p1.x
    dy = line_p2.y - line_p1.y
    norm = math.hypot(dx, dy)
    if norm < 1e-12:
        raise ValueError("Cannot compute perpendicular to a zero-length line.")
    ux, uy = dx / norm, dy / norm
    if side.lower() == "left":
        nx, ny = -uy, ux
    else:
        nx, ny = uy, -ux
    return Point2D(
        x=from_point.x + nx * length,
        y=from_point.y + ny * length,
        id=point_id,
        label=label,
        formula_summary=formula_summary,
    )


def line_line_intersection(
    p1: Point2D,
    p2: Point2D,
    p3: Point2D,
    p4: Point2D,
    point_id: str = "",
    label: str = "",
    formula_summary: str = "",
) -> Point2D:
    """Compute infinite line-line intersection between (p1, p2) and (p3, p4)."""
    x1, y1 = p1.x, p1.y
    x2, y2 = p2.x, p2.y
    x3, y3 = p3.x, p3.y
    x4, y4 = p4.x, p4.y

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        raise ValueError("Lines are parallel or coincident; cannot intersect.")

    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
    return Point2D(px, py, point_id, label, formula_summary)


def _select_candidate(candidates: List[Point2D], select: str) -> Point2D:
    if not candidates:
        raise ValueError("No geometric intersection candidates found.")
    mode = select.lower()
    if mode == "min_x":
        return min(candidates, key=lambda p: p.x)
    if mode == "max_x":
        return max(candidates, key=lambda p: p.x)
    if mode == "min_y":
        return min(candidates, key=lambda p: p.y)
    if mode == "max_y":
        return max(candidates, key=lambda p: p.y)
    if mode == "second" and len(candidates) > 1:
        return candidates[1]
    return candidates[0]


def circle_line_intersection(
    center: Point2D,
    radius: float,
    line_p1: Point2D,
    line_p2: Point2D,
    select: str = "first",
    point_id: str = "",
    label: str = "",
    formula_summary: str = "",
) -> Point2D:
    """Intersect circle (center, radius) with infinite line through (line_p1, line_p2)."""
    dx = line_p2.x - line_p1.x
    dy = line_p2.y - line_p1.y
    fx = line_p1.x - center.x
    fy = line_p1.y - center.y

    a = dx * dx + dy * dy
    if a < 1e-12:
        raise ValueError("Line endpoints for circle-line intersection are identical.")
    b = 2.0 * (fx * dx + fy * dy)
    c = (fx * fx + fy * fy) - radius * radius

    discriminant = b * b - 4.0 * a * c
    if discriminant < -1e-9:
        raise ValueError(
            f"Circle (r={radius:.2f}) does not intersect line ({line_p1.id}->{line_p2.id})."
        )
    discriminant = max(0.0, discriminant)
    sqrt_disc = math.sqrt(discriminant)

    t1 = (-b - sqrt_disc) / (2.0 * a)
    t2 = (-b + sqrt_disc) / (2.0 * a)
    candidates = [
        Point2D(line_p1.x + t1 * dx, line_p1.y + t1 * dy, point_id, label, formula_summary),
        Point2D(line_p1.x + t2 * dx, line_p1.y + t2 * dy, point_id, label, formula_summary),
    ]
    return _select_candidate(candidates, select)


def circle_circle_intersection(
    c1: Point2D,
    r1: float,
    c2: Point2D,
    r2: float,
    select: str = "first",
    point_id: str = "",
    label: str = "",
    formula_summary: str = "",
) -> Point2D:
    """Intersect two circles (c1, r1) and (c2, r2)."""
    d = c1.distance_to(c2)
    if d < 1e-12 or d > r1 + r2 + 1e-7 or d < abs(r1 - r2) - 1e-7:
        raise ValueError(
            f"Circles at {c1.id} (r={r1:.2f}) and {c2.id} (r={r2:.2f}) do not intersect (d={d:.2f})."
        )

    a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d)
    h_sq = max(0.0, r1 * r1 - a * a)
    h = math.sqrt(h_sq)

    x2 = c1.x + a * (c2.x - c1.x) / d
    y2 = c1.y + a * (c2.y - c1.y) / d

    rx = -(c2.y - c1.y) * (h / d)
    ry = (c2.x - c1.x) * (h / d)

    candidates = [
        Point2D(x2 + rx, y2 + ry, point_id, label, formula_summary),
        Point2D(x2 - rx, y2 - ry, point_id, label, formula_summary),
    ]
    return _select_candidate(candidates, select)


# ---------------------------------------------------------------------------
# Polygon Area, Bounding Box, Seam Allowance Offset & Notch Helpers
# ---------------------------------------------------------------------------


def deduplicate_Sequential_points(pts: Sequence[Point2D], eps: float = 1e-5) -> List[Point2D]:
    """Remove consecutive duplicate points in a polyline or polygon."""
    if not pts:
        return []
    cleaned = [pts[0]]
    for pt in pts[1:]:
        if pt.distance_to(cleaned[-1]) > eps:
            cleaned.append(pt)
    if len(cleaned) > 1 and cleaned[0].distance_to(cleaned[-1]) <= eps:
        cleaned.pop()
    return cleaned


def polygon_signed_area(pts: Sequence[Point2D]) -> float:
    """Compute signed area via Shoelace formula (>0 clockwise in y-down / counter-clockwise in y-up)."""
    n = len(pts)
    if n < 3:
        return 0.0
    area2 = 0.0
    for i in range(n):
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        area2 += p1.x * p2.y - p2.x * p1.y
    return 0.5 * area2


def polygon_area(pts: Sequence[Point2D]) -> float:
    """Compute absolute area of a closed polygon in square units (cm^2)."""
    return abs(polygon_signed_area(pts))


def polygon_centroid(pts: Sequence[Point2D]) -> Point2D:
    """Compute area-weighted centroid of a closed polygon."""
    cleaned = deduplicate_Sequential_points(pts)
    n = len(cleaned)
    if n == 0:
        return Point2D(0.0, 0.0)
    if n < 3:
        return Point2D(
            sum(p.x for p in cleaned) / n,
            sum(p.y for p in cleaned) / n,
        )
    signed_a = polygon_signed_area(cleaned)
    if abs(signed_a) < 1e-9:
        return Point2D(
            sum(p.x for p in cleaned) / n,
            sum(p.y for p in cleaned) / n,
        )
    cx, cy = 0.0, 0.0
    for i in range(n):
        p1 = cleaned[i]
        p2 = cleaned[(i + 1) % n]
        cross = p1.x * p2.y - p2.x * p1.y
        cx += (p1.x + p2.x) * cross
        cy += (p1.y + p2.y) * cross
    factor = 1.0 / (6.0 * signed_a)
    return Point2D(cx * factor, cy * factor)


def polygon_bounding_box(pts: Sequence[Point2D]) -> BoundingBox:
    """Compute axis-aligned bounding box of a sequence of points."""
    if not pts:
        return BoundingBox(0.0, 0.0, 0.0, 0.0)
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    return BoundingBox(min(xs), min(ys), max(xs), max(ys))


def offset_closed_polygon(
    pts: Sequence[Point2D],
    offset_distance: float,
    miter_limit: float = 2.5,
) -> List[Point2D]:
    """
    Generate an outward offset contour (seam allowance) around a closed polygon.
    Automatically detects winding order so positive `offset_distance` always expands outward.
    """
    ring = deduplicate_Sequential_points(pts, eps=1e-4)
    n = len(ring)
    if n < 3 or abs(offset_distance) < 1e-6:
        return list(ring)

    # Determine winding sign: for signed_area > 0, outward normal of edge (dx, dy) is (dy, -dx)
    signed_a = polygon_signed_area(ring)
    winding_sign = 1.0 if signed_a >= 0.0 else -1.0

    normals: List[Tuple[float, float]] = []
    for i in range(n):
        p1 = ring[i]
        p2 = ring[(i + 1) % n]
        dx = p2.x - p1.x
        dy = p2.y - p1.y
        length = math.hypot(dx, dy)
        if length < 1e-9:
            normals.append((0.0, 0.0))
        else:
            nx = (dy / length) * winding_sign
            ny = (-dx / length) * winding_sign
            normals.append((nx, ny))

    offset_pts: List[Point2D] = []
    for i in range(n):
        n_prev = normals[(i - 1) % n]
        n_curr = normals[i]
        bx = n_prev[0] + n_curr[0]
        by = n_prev[1] + n_curr[1]
        b_len = math.hypot(bx, by)
        if b_len < 1e-6:
            mx, my = n_curr[0], n_curr[1]
            scale = offset_distance
        else:
            bx /= b_len
            by /= b_len
            dot = bx * n_curr[0] + by * n_curr[1]
            scale = offset_distance / max(dot, 1.0 / miter_limit)
            scale = min(scale, offset_distance * miter_limit)
            mx, my = bx, by

        pt = ring[i]
        offset_pts.append(Point2D(pt.x + mx * scale, pt.y + my * scale))

    # Close contour by appending first point
    if offset_pts:
        offset_pts.append(offset_pts[0])
    return offset_pts


def compute_notch_ticks(
    notch_pt: Point2D,
    edge_start: Point2D,
    edge_end: Point2D,
    polygon_pts: Sequence[Point2D],
    length_cm: float = 0.5,
    count: int = 1,
    spacing_cm: float = 0.35,
) -> List[Tuple[Point2D, Point2D]]:
    """
    Compute one or more perpendicular notch tick segments at `notch_pt` along edge (edge_start -> edge_end),
    pointing inward toward the interior of the pattern piece.
    """
    dx = edge_end.x - edge_start.x
    dy = edge_end.y - edge_start.y
    edge_len = math.hypot(dx, dy)
    if edge_len < 1e-9:
        return []

    ux, uy = dx / edge_len, dy / edge_len
    # Inward normal is opposite of outward normal
    ring = deduplicate_Sequential_points(polygon_pts)
    signed_a = polygon_signed_area(ring)
    winding_sign = 1.0 if signed_a >= 0.0 else -1.0
    inward_nx = -(uy * winding_sign)
    inward_ny = ux * winding_sign

    ticks: List[Tuple[Point2D, Point2D]] = []
    start_offset = -0.5 * (count - 1) * spacing_cm
    for i in range(max(1, count)):
        along = start_offset + i * spacing_cm
        base = Point2D(notch_pt.x + ux * along, notch_pt.y + uy * along)
        tip = Point2D(base.x + inward_nx * length_cm, base.y + inward_ny * length_cm)
        ticks.append((base, tip))
    return ticks
