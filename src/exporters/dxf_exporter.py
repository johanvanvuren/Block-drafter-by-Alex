"""
CAD-Compatible Vector DXF Exporter (CLO3D, Gerber AccuMark, Optitex, AutoCAD).

Supports two industry modes:
1. "aama" (AAMA / ASTM D6673 Standard):
   - Packages each pattern piece as a DXF BLOCK + INSERT
   - Uses standard numbered layers:
     * Layer 1: Piece Boundary (closed POLYLINE / LWPOLYLINE)
     * Layer 4: Notches (LINE perpendicular to boundary)
     * Layer 7: Grainline (LINE inside boundary)
     * Layer 8: Internal Lines & Darts (LWPOLYLINE)
     * Layer 14: Seam / Cut Allowance Line (LWPOLYLINE)
     * Layer 15: Piece Name & Size Annotation (TEXT)
2. "standard_cad" (General Layered CAD Mode):
   - Outputs flat Modelspace geometry on semantic named layers:
     CUT_LINE, SEAM_LINE, INTERNAL_DARTS, GRAINLINE, NOTCHES, CONSTRUCTION, LABELS
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence, Tuple

from src.core.drafting_engine import DraftedBlockResult, ResolvedPatternPiece
from src.core.geometry import Point2D

try:
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    HAS_EZDXF = True
except ImportError:  # pragma: no cover
    HAS_EZDXF = False


class DXFExporter:
    """Exports drafted garment blocks to AAMA/ASTM D6673 or Standard Layered CAD DXF."""

    @staticmethod
    def _cad_pt(pt: Point2D, scale: float = 1.0) -> Tuple[float, float]:
        """Convert pattern y-down coordinate into right-handed CAD y-up coordinate."""
        return (pt.x * scale, -pt.y * scale)

    @classmethod
    def export_draft(
        cls,
        draft: DraftedBlockResult,
        output_path: str | Path,
        mode: str = "aama",
        unit_scale: float = 1.0,  # 1.0 = cm, 10.0 = mm
        include_construction: bool = True,
    ) -> Path:
        """
        Export `draft` to DXF at `output_path`.
        `mode`: "aama" (CLO3D/Gerber/Optitex BLOCK + numbered layers) or "standard_cad" (Modelspace named layers).
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        if HAS_EZDXF:
            if mode.lower() == "aama":
                cls._export_aama_ezdxf(draft, out, unit_scale)
            else:
                cls._export_standard_ezdxf(draft, out, unit_scale, include_construction)
        else:
            cls._export_ascii_dxf_fallback(draft, out, mode, unit_scale, include_construction)

        return out

    @classmethod
    def _export_aama_ezdxf(
        cls,
        draft: DraftedBlockResult,
        output_path: Path,
        scale: float,
    ) -> None:
        doc = ezdxf.new("R2000")
        # Define AAMA / ASTM D6673 numbered layers
        aama_layers = [
            ("1", 7),   # Boundary (White/Black)
            ("4", 1),   # Notches (Red)
            ("7", 3),   # Grainline (Green)
            ("8", 5),   # Internal lines / Darts (Blue)
            ("14", 6),  # Cut / Seam Allowance line (Magenta)
            ("15", 2),  # Annotation Text (Yellow)
        ]
        for layer_name, color_aci in aama_layers:
            if layer_name not in doc.layers:
                doc.layers.add(name=layer_name, color=color_aci)

        msp = doc.modelspace()

        for piece in draft.pieces:
            block_name = piece.id.upper().replace(" ", "_")
            blk = doc.blocks.new(name=block_name)

            # Layer 1: Closed Pattern Boundary
            boundary_pts = [cls._cad_pt(p, scale) for p in piece.boundary_polygon]
            if boundary_pts:
                blk.add_lwpolyline(boundary_pts, close=True, dxfattribs={"layer": "1"})

            # Layer 14: Seam Allowance Outer Cut Line
            if piece.seam_allowance_cm > 1e-6 and piece.seam_allowance_polygon:
                sa_pts = [cls._cad_pt(p, scale) for p in piece.seam_allowance_polygon]
                blk.add_lwpolyline(sa_pts, close=True, dxfattribs={"layer": "14"})

            # Layer 8: Internal Lines & Darts
            for il in piece.internal_lines:
                il_pts = [cls._cad_pt(p, scale) for p in il.points]
                if len(il_pts) >= 2:
                    blk.add_lwpolyline(il_pts, close=False, dxfattribs={"layer": "8"})

            # Layer 7: Grainline
            if piece.grainline:
                g0 = cls._cad_pt(piece.grainline.start, scale)
                g1 = cls._cad_pt(piece.grainline.end, scale)
                blk.add_line(g0, g1, dxfattribs={"layer": "7"})

            # Layer 4: Notches
            for notch in piece.notches:
                for t0, t1 in notch.ticks:
                    blk.add_line(
                        cls._cad_pt(t0, scale),
                        cls._cad_pt(t1, scale),
                        dxfattribs={"layer": "4"},
                    )

            # Layer 15: Piece Annotation Text
            c_pt = cls._cad_pt(piece.centroid, scale)
            txt = blk.add_text(
                f"{piece.name} (x{piece.cut_count})",
                dxfattribs={"layer": "15", "height": 1.0 * scale},
            )
            txt.set_placement(c_pt, align=TextEntityAlignment.MIDDLE_CENTER)

            msp.add_blockref(block_name, (0.0, 0.0))

        doc.saveas(output_path)

    @classmethod
    def _export_standard_ezdxf(
        cls,
        draft: DraftedBlockResult,
        output_path: Path,
        scale: float,
        include_construction: bool,
    ) -> None:
        doc = ezdxf.new("R2000")
        named_layers = [
            ("CUT_LINE", 1),
            ("SEAM_LINE", 7),
            ("INTERNAL_DARTS", 5),
            ("GRAINLINE", 3),
            ("NOTCHES", 2),
            ("CONSTRUCTION", 8),
            ("LABELS", 4),
        ]
        for lname, color_aci in named_layers:
            if lname not in doc.layers:
                doc.layers.add(name=lname, color=color_aci)

        msp = doc.modelspace()

        if include_construction:
            for curve in draft.construction_curves.values():
                c_pts = [cls._cad_pt(p, scale) for p in curve.tessellate()]
                if len(c_pts) >= 2:
                    msp.add_lwpolyline(c_pts, close=False, dxfattribs={"layer": "CONSTRUCTION"})
            for pid, pt in draft.points.items():
                cad_p = cls._cad_pt(pt, scale)
                msp.add_point(cad_p, dxfattribs={"layer": "CONSTRUCTION"})
                lbl = msp.add_text(
                    pid,
                    dxfattribs={"layer": "LABELS", "height": 0.45 * scale},
                )
                lbl.set_placement((cad_p[0] + 0.3 * scale, cad_p[1] + 0.3 * scale))

        for piece in draft.pieces:
            # SEAM_LINE
            b_pts = [cls._cad_pt(p, scale) for p in piece.boundary_polygon]
            if b_pts:
                msp.add_lwpolyline(b_pts, close=True, dxfattribs={"layer": "SEAM_LINE"})

            # CUT_LINE
            if piece.seam_allowance_cm > 1e-6 and piece.seam_allowance_polygon:
                sa_pts = [cls._cad_pt(p, scale) for p in piece.seam_allowance_polygon]
                msp.add_lwpolyline(sa_pts, close=True, dxfattribs={"layer": "CUT_LINE"})

            # INTERNAL_DARTS
            for il in piece.internal_lines:
                il_pts = [cls._cad_pt(p, scale) for p in il.points]
                if len(il_pts) >= 2:
                    msp.add_lwpolyline(il_pts, close=False, dxfattribs={"layer": "INTERNAL_DARTS"})

            # GRAINLINE
            if piece.grainline:
                msp.add_line(
                    cls._cad_pt(piece.grainline.start, scale),
                    cls._cad_pt(piece.grainline.end, scale),
                    dxfattribs={"layer": "GRAINLINE"},
                )

            # NOTCHES
            for notch in piece.notches:
                for t0, t1 in notch.ticks:
                    msp.add_line(
                        cls._cad_pt(t0, scale),
                        cls._cad_pt(t1, scale),
                        dxfattribs={"layer": "NOTCHES"},
                    )

            # Piece Label
            c_pt = cls._cad_pt(piece.centroid, scale)
            txt = msp.add_text(
                f"{piece.name} (Cut {piece.cut_count}x)",
                dxfattribs={"layer": "LABELS", "height": 0.8 * scale},
            )
            txt.set_placement(c_pt, align=TextEntityAlignment.MIDDLE_CENTER)

        doc.saveas(output_path)

    @classmethod
    def _export_ascii_dxf_fallback(
        cls,
        draft: DraftedBlockResult,
        output_path: Path,
        mode: str,
        scale: float,
        include_construction: bool,
    ) -> None:
        """Zero-dependency R12 ASCII DXF writer fallback if ezdxf is not yet installed."""
        is_aama = mode.lower() == "aama"
        l_bound = "1" if is_aama else "SEAM_LINE"
        l_cut = "14" if is_aama else "CUT_LINE"
        l_int = "8" if is_aama else "INTERNAL_DARTS"
        l_grain = "7" if is_aama else "GRAINLINE"
        l_notch = "4" if is_aama else "NOTCHES"
        l_text = "15" if is_aama else "LABELS"

        out_lines: List[str] = ["0", "SECTION", "2", "ENTITIES"]

        def _add_polyline(pts: Sequence[Tuple[float, float]], layer: str, closed: bool) -> None:
            if len(pts) < 2:
                return
            out_lines.extend(["0", "POLYLINE", "8", layer, "66", "1", "70", "1" if closed else "0"])
            for x, y in pts:
                out_lines.extend(["0", "VERTEX", "8", layer, "10", f"{x:.4f}", "20", f"{y:.4f}", "30", "0.0"])
            out_lines.extend(["0", "SEQEND"])

        def _add_line(p0: Tuple[float, float], p1: Tuple[float, float], layer: str) -> None:
            out_lines.extend([
                "0", "LINE", "8", layer,
                "10", f"{p0[0]:.4f}", "20", f"{p0[1]:.4f}", "30", "0.0",
                "11", f"{p1[0]:.4f}", "21", f"{p1[1]:.4f}", "31", "0.0",
            ])

        for piece in draft.pieces:
            _add_polyline([cls._cad_pt(p, scale) for p in piece.boundary_polygon], l_bound, True)
            if piece.seam_allowance_cm > 1e-6 and piece.seam_allowance_polygon:
                _add_polyline([cls._cad_pt(p, scale) for p in piece.seam_allowance_polygon], l_cut, True)
            for il in piece.internal_lines:
                _add_polyline([cls._cad_pt(p, scale) for p in il.points], l_int, False)
            if piece.grainline:
                _add_line(
                    cls._cad_pt(piece.grainline.start, scale),
                    cls._cad_pt(piece.grainline.end, scale),
                    l_grain,
                )
            for notch in piece.notches:
                for t0, t1 in notch.ticks:
                    _add_line(cls._cad_pt(t0, scale), cls._cad_pt(t1, scale), l_notch)
            cx, cy = cls._cad_pt(piece.centroid, scale)
            out_lines.extend([
                "0", "TEXT", "8", l_text,
                "10", f"{cx:.4f}", "20", f"{cy:.4f}", "30", "0.0",
                "40", f"{0.8 * scale:.4f}", "1", f"{piece.name} (x{piece.cut_count})",
            ])

        out_lines.extend(["0", "ENDSEC", "0", "EOF"])
        output_path.write_text("\n".join(out_lines), encoding="utf-8")
