"""
Clean 1:1 Scale Vector SVG Exporter for Adobe Illustrator, Inkscape, and Affinity Designer.

Outputs physical millimeter (mm) dimensions (1cm = 10mm) with semantic layer groups:
- #construction-geometry
- #pattern-pieces (with stitch boundary, seam allowance, internal lines/darts, grainlines, notches)
- #annotations
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import List, Sequence

from src.core.drafting_engine import (
    CurvePrimitive,
    DraftedBlockResult,
    ResolvedPatternPiece,
)
from src.core.geometry import (
    CatmullRomSpline2D,
    CubicBezier2D,
    LineSegment2D,
    Point2D,
)
from src.layout.nesting_engine import LayoutResult

CM_TO_MM = 10.0


class SVGExporter:
    """Generates clean, layered 1:1 scale SVG vector files from drafted blocks or nested layouts."""

    @staticmethod
    def _curve_to_svg_path_d(
        segments: Sequence[CurvePrimitive],
        offset_x_cm: float,
        offset_y_cm: float,
        close_path: bool = False,
    ) -> str:
        commands: List[str] = []
        for idx, seg in enumerate(segments):
            if isinstance(seg, LineSegment2D):
                x0 = (seg.p0.x + offset_x_cm) * CM_TO_MM
                y0 = (seg.p0.y + offset_y_cm) * CM_TO_MM
                x1 = (seg.p1.x + offset_x_cm) * CM_TO_MM
                y1 = (seg.p1.y + offset_y_cm) * CM_TO_MM
                if idx == 0:
                    commands.append(f"M {x0:.3f} {y0:.3f}")
                commands.append(f"L {x1:.3f} {y1:.3f}")
            elif isinstance(seg, CubicBezier2D):
                x0 = (seg.p0.x + offset_x_cm) * CM_TO_MM
                y0 = (seg.p0.y + offset_y_cm) * CM_TO_MM
                x1 = (seg.p1.x + offset_x_cm) * CM_TO_MM
                y1 = (seg.p1.y + offset_y_cm) * CM_TO_MM
                x2 = (seg.p2.x + offset_x_cm) * CM_TO_MM
                y2 = (seg.p2.y + offset_y_cm) * CM_TO_MM
                x3 = (seg.p3.x + offset_x_cm) * CM_TO_MM
                y3 = (seg.p3.y + offset_y_cm) * CM_TO_MM
                if idx == 0:
                    commands.append(f"M {x0:.3f} {y0:.3f}")
                commands.append(f"C {x1:.3f} {y1:.3f}, {x2:.3f} {y2:.3f}, {x3:.3f} {y3:.3f}")
            elif isinstance(seg, CatmullRomSpline2D):
                beziers = seg.to_beziers()
                for b_idx, bez in enumerate(beziers):
                    x0 = (bez.p0.x + offset_x_cm) * CM_TO_MM
                    y0 = (bez.p0.y + offset_y_cm) * CM_TO_MM
                    x1 = (bez.p1.x + offset_x_cm) * CM_TO_MM
                    y1 = (bez.p1.y + offset_y_cm) * CM_TO_MM
                    x2 = (bez.p2.x + offset_x_cm) * CM_TO_MM
                    y2 = (bez.p2.y + offset_y_cm) * CM_TO_MM
                    x3 = (bez.p3.x + offset_x_cm) * CM_TO_MM
                    y3 = (bez.p3.y + offset_y_cm) * CM_TO_MM
                    if idx == 0 and b_idx == 0:
                        commands.append(f"M {x0:.3f} {y0:.3f}")
                    commands.append(f"C {x1:.3f} {y1:.3f}, {x2:.3f} {y2:.3f}, {x3:.3f} {y3:.3f}")
        if close_path and commands:
            commands.append("Z")
        return " ".join(commands)

    @staticmethod
    def _polyline_to_svg_path_d(
        pts: Sequence[Point2D],
        offset_x_cm: float,
        offset_y_cm: float,
        close_path: bool = False,
    ) -> str:
        if not pts:
            return ""
        parts = [
            f"{'M' if i == 0 else 'L'} {(p.x + offset_x_cm) * CM_TO_MM:.3f} {(p.y + offset_y_cm) * CM_TO_MM:.3f}"
            for i, p in enumerate(pts)
        ]
        if close_path:
            parts.append("Z")
        return " ".join(parts)

    @classmethod
    def export_draft(
        cls,
        draft: DraftedBlockResult,
        output_path: str | Path,
        include_construction: bool = True,
        include_seam_allowance: bool = True,
        padding_cm: float = 3.0,
    ) -> Path:
        """Export the drafted block at 1:1 physical scale to an SVG file."""
        bbox = draft.overall_bounding_box
        shift_x = -bbox.min_x + padding_cm
        shift_y = -bbox.min_y + padding_cm
        width_mm = (bbox.width + 2.0 * padding_cm) * CM_TO_MM
        height_mm = (bbox.height + 2.0 * padding_cm) * CM_TO_MM

        lines: List[str] = [
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width_mm:.2f}mm" height="{height_mm:.2f}mm" '
            f'viewBox="0 0 {width_mm:.2f} {height_mm:.2f}">',
            f"  <title>{html.escape(draft.name)}</title>",
            "  <defs>",
            '    <marker id="grain-arrow" viewBox="0 0 10 10" refX="5" refY="5" '
            'markerWidth="5" markerHeight="5" orient="auto-start-reverse">',
            '      <path d="M 0 1.5 L 10 5 L 0 8.5 z" fill="#0d9488"/>',
            "    </marker>",
            "  </defs>",
        ]

        # Layer 1: Construction Geometry
        if include_construction:
            lines.append('  <g id="construction-geometry" stroke="#64748b" fill="none">')
            for cid, curve in draft.construction_curves.items():
                path_d = cls._curve_to_svg_path_d([curve], shift_x, shift_y, close_path=False)
                lines.append(
                    f'    <path id="const-{html.escape(cid)}" d="{path_d}" '
                    f'stroke-width="0.35" stroke-dasharray="2.5,2.0" />'
                )
            for pid, pt in draft.points.items():
                px = (pt.x + shift_x) * CM_TO_MM
                py = (pt.y + shift_y) * CM_TO_MM
                lines.append(
                    f'    <circle id="pt-{html.escape(pid)}" cx="{px:.3f}" cy="{py:.3f}" '
                    f'r="1.1" fill="#38bdf8" stroke="none" />'
                )
                lines.append(
                    f'    <text x="{px + 2.0:.3f}" y="{py - 1.5:.3f}" '
                    f'font-family="Segoe UI, Arial, sans-serif" font-size="3.2" fill="#475569">'
                    f"{html.escape(pid)}</text>"
                )
            lines.append("  </g>")

        # Layer 2: Extracted Pattern Pieces
        lines.append('  <g id="pattern-pieces" fill="none">')
        for piece in draft.pieces:
            lines.append(f'    <g id="piece-{html.escape(piece.id)}">')

            # Seam allowance outer cut line
            if include_seam_allowance and piece.seam_allowance_cm > 1e-6 and piece.seam_allowance_polygon:
                sa_d = cls._polyline_to_svg_path_d(
                    piece.seam_allowance_polygon, shift_x, shift_y, close_path=True
                )
                lines.append(
                    f'      <path id="{html.escape(piece.id)}-cut-line" d="{sa_d}" '
                    f'stroke="#e11d48" stroke-width="0.55" stroke-dasharray="4.0,2.0" />'
                )

            # Net stitch/pattern boundary (exact vector curves)
            bound_d = cls._curve_to_svg_path_d(
                piece.boundary_segments, shift_x, shift_y, close_path=True
            )
            lines.append(
                f'      <path id="{html.escape(piece.id)}-seam-line" d="{bound_d}" '
                f'stroke="#0f172a" stroke-width="0.75" />'
            )

            # Internal lines & Darts
            for il in piece.internal_lines:
                il_d = cls._polyline_to_svg_path_d(il.points, shift_x, shift_y, close_path=False)
                color = "#7c3aed" if il.line_type == "dart" else "#6366f1"
                lines.append(
                    f'      <path id="{html.escape(piece.id)}-{html.escape(il.id)}" d="{il_d}" '
                    f'stroke="{color}" stroke-width="0.45" />'
                )

            # Notches
            for notch in piece.notches:
                for idx, (t0, t1) in enumerate(notch.ticks):
                    x0, y0 = (t0.x + shift_x) * CM_TO_MM, (t0.y + shift_y) * CM_TO_MM
                    x1, y1 = (t1.x + shift_x) * CM_TO_MM, (t1.y + shift_y) * CM_TO_MM
                    lines.append(
                        f'      <line id="{html.escape(notch.id)}-{idx}" '
                        f'x1="{x0:.3f}" y1="{y0:.3f}" x2="{x1:.3f}" y2="{y1:.3f}" '
                        f'stroke="#0f172a" stroke-width="0.6" />'
                    )

            # Grainline
            if piece.grainline:
                gx0 = (piece.grainline.start.x + shift_x) * CM_TO_MM
                gy0 = (piece.grainline.start.y + shift_y) * CM_TO_MM
                gx1 = (piece.grainline.end.x + shift_x) * CM_TO_MM
                gy1 = (piece.grainline.end.y + shift_y) * CM_TO_MM
                lines.append(
                    f'      <line id="{html.escape(piece.id)}-grainline" '
                    f'x1="{gx0:.3f}" y1="{gy0:.3f}" x2="{gx1:.3f}" y2="{gy1:.3f}" '
                    f'stroke="#0d9488" stroke-width="0.5" '
                    f'marker-start="url(#grain-arrow)" marker-end="url(#grain-arrow)" />'
                )

            # Piece Centroid Label
            c_pt = piece.centroid
            cx = (c_pt.x + shift_x) * CM_TO_MM
            cy = (c_pt.y + shift_y) * CM_TO_MM
            lines.append(
                f'      <text x="{cx:.3f}" y="{cy:.3f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="4.8" font-weight="bold" fill="#0f172a">'
                f"{html.escape(piece.name)} (Cut {piece.cut_count}x)</text>"
            )
            lines.append(
                f'      <text x="{cx:.3f}" y="{cy + 6.0:.3f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="3.5" fill="#475569">'
                f"SA: {piece.seam_allowance_cm:.1f}cm | Area: {piece.cut_area_cm2:.1f} cm²</text>"
            )

            lines.append("    </g>")
        lines.append("  </g>")
        lines.append("</svg>")

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines), encoding="utf-8")
        return out
