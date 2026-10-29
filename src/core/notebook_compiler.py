"""
Pattern Cutting Textbook Notebook Compiler, Decompiler & Smart Formula Suggester.

Implements:
1. Multi-line "Pattern Cutting Textbook" Notebook parser (`NotebookCompiler`)
   supporting:
   - Comments (`# ...` or `// ...`) and numbered steps (`1.`, `2)`, `Step 3:`)
   - Derived Variables:
       `Var hip_ease = 1.5cm` or `Let hip_ease = 1.5cm`
   - Origin & Absolute Points:
       `Point A is the origin (0, 0)`
       `Point A is (0, 1.5cm)`
   - Directional Offsets (Textbook style):
       `From A go down (skirt_length) to C`
       `From A go right (waist / 4 + 2cm) to B`
       `Point B is (waist / 4 + 1cm) right from A`  (supports right, left, down, up, X-axis, Y-axis)
   - 2D Offsets:
       `Point W_B is offset (back_waist_span, -1.25cm) from A`
   - Squaring / Coordinate Reference:
       `Square from B.x and C.y as D` or `Square across from C and down from B as D`
   - Polar (Distance & Angle):
       `Point B_Sh is (shoulder_length + 1.2cm) at angle 18 deg from BN_Side`
   - Line Interpolation & Midpoints:
       `Midpoint of A and W_B is BD_M`
       `Point M is 0.55 along B to W_F`
       `Point BD_L is dist (dist(A, BD_M) - 1.75cm) along A to W_B`
   - Perpendiculars:
       `From BD_M go perpendicular 14cm right of A -> W_B as BD_Apex`
   - Intersections:
       `Intersect line A-B and line C-D at P_Int`
       `Intersect circle at Nape radius 12cm with line A-B at Sh_Pt (select max_x)`
       `Intersect circle at A radius 10cm with circle at B radius 10cm at Apex (select max_y)`
   - Construction Curves (Spline & Cubic Bezier):
       `Smooth curve back_armhole through B_Sh_Tip, B_Cross, B_Underarm`
       `Bezier curve back_hip_curve from W_B to H_B handles (78 deg, dist(W_B, H_B)*0.38) and (-90 deg, dist(W_B, H_B)*0.38)`
       `Line cb_line from A to C`
   - Pattern Pieces, Darts, Internal Lines, Grainlines & Notches:
       `Piece skirt_back "Skirt Back Block" (cut 2, sa 1.0cm): A -> BD_L -> BD_R -> W_B -> curve(back_hip_curve) -> Hem_B -> C -> A`
       `Dart on skirt_back: BD_L -> BD_Apex -> BD_R`
       `Internal line on skirt_back: E -> H_B`
       `Grainline on skirt_back: BG_Top -> BG_Bot`
       `Notch on skirt_back at H_B along H_B -> Hem_B (count 2)`

2. Decompiler (`block_spec_to_notebook_script`):
   Converts any JSON Block Instruction dictionary into a clean, editable textbook notebook script.

3. Smart Formula Suggester (`suggest_parametric_formulas`):
   Matches a traced 2D distance (cm) against active UK body measurements and common fractions
   (1/2, 1/4, 1/5, 1/6, 1/8, 1.0) to propose parametric formulas like `waist / 4 + 1.0cm`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


@dataclass
class NotebookParseDiagnostic:
    """Line-level status or error message produced by the NotebookCompiler."""

    line_number: int
    raw_line: str
    message: str
    is_error: bool = True


class NotebookCompiler:
    """Compiles a multi-line Pattern Cutting Textbook Notebook script into a block_spec dict."""

    _STEP_PREFIX_RE = re.compile(r"^\s*(?:(?:step\s+)?\d+[\.\)\:\-]\s*)", re.IGNORECASE)

    @classmethod
    def compile_script(
        cls,
        script_text: str,
        base_metadata: Optional[Mapping[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], List[NotebookParseDiagnostic]]:
        """
        Compile `script_text` into a canonical `block_spec` dictionary and return any diagnostics.
        """
        meta = dict(base_metadata) if base_metadata else {}
        block_spec: Dict[str, Any] = {
            "schema_version": "1.0",
            "block_id": str(meta.get("block_id", "custom_block")),
            "name": str(meta.get("name", "Custom Garment Block")),
            "description": str(meta.get("description", "Created in Pattern Cutting Notebook Studio.")),
            "unit": str(meta.get("unit", "cm")),
            "coordinate_system": "y_down",
            "required_measurements": list(meta.get("required_measurements", [])),
            "derived_variables": {},
            "points": [],
            "construction": [],
            "pieces": [],
        }

        pieces_by_id: Dict[str, Dict[str, Any]] = {}
        diagnostics: List[NotebookParseDiagnostic] = []

        for idx, raw_line in enumerate(script_text.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("//"):
                continue

            # Strip optional leading numbering like "1. " or "Step 2: "
            line = cls._STEP_PREFIX_RE.sub("", stripped).strip().rstrip(".")
            if not line:
                continue

            try:
                cls._parse_single_line(line, block_spec, pieces_by_id)
            except Exception as exc:
                diagnostics.append(
                    NotebookParseDiagnostic(
                        line_number=idx,
                        raw_line=raw_line,
                        message=str(exc),
                        is_error=True,
                    )
                )

        return block_spec, diagnostics

    @classmethod
    def _parse_single_line(
        cls,
        line: str,
        block_spec: Dict[str, Any],
        pieces_by_id: Dict[str, Dict[str, Any]],
    ) -> None:
        # 1. Derived Variable: "Var hip_ease = 1.5cm" or "Let back_width = hips / 4 + 0.5cm"
        m_var = re.match(
            r"^(?:var|let|variable)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        if m_var:
            var_name, expr = m_var.group(1).strip(), m_var.group(2).strip()
            block_spec["derived_variables"][var_name] = expr
            return

        # 2. Origin / Absolute Point:
        #    "Point A is the origin (0, 0)" or "Point A is (0, 1.5cm)" or "Origin A at (0, 0)"
        m_abs = re.match(
            r"^(?:Point\s+|Origin\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+(?:is\s+(?:the\s+origin\s*)?|at\s*|=?\s*)\(\s*([^,]+)\s*,\s*([^)]+)\s*\)$",
            line,
            re.IGNORECASE,
        )
        if m_abs and not line.lower().startswith(("piece ", "bezier ", "smooth ", "curve ")):
            pid, x_expr, y_expr = m_abs.group(1), m_abs.group(2).strip(), m_abs.group(3).strip()
            cls._upsert_point(
                block_spec,
                {"id": pid, "label": f"Point {pid}", "type": "absolute", "x": x_expr, "y": y_expr},
            )
            return

        # 3. Textbook Directional Offset (Form A):
        #    "From A go right (waist / 4 + 1cm) to B" or "From A go down skirt_length to C"
        m_from_dir = re.match(
            r"^From\s+(?:Point\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+go\s+(right|left|down|up|east|west|south|north)\s+\(?(.+?)\)?\s+(?:to|as)\s+(?:Point\s+)?([A-Za-z_][A-Za-z0-9_]*)$",
            line,
            re.IGNORECASE,
        )
        if m_from_dir:
            ref_pt, direction, expr, pid = (
                m_from_dir.group(1),
                m_from_dir.group(2).lower(),
                m_from_dir.group(3).strip(),
                m_from_dir.group(4),
            )
            dx, dy = cls._dir_to_dx_dy(direction, expr)
            cls._upsert_point(
                block_spec,
                {"id": pid, "label": f"Point {pid}", "type": "offset", "from": ref_pt, "dx": dx, "dy": dy},
            )
            return

        # 4. Directional / Axis Offset (Form B):
        #    "Point B is (Waist / 4 + 1cm) on the X-axis from Point A"
        #    "Point B is (Waist / 4 + 1cm) right from Point A"
        m_axis = re.match(
            r"^Point\s+([A-Za-z_][A-Za-z0-9_]*)\s+is\s+\(?(.+?)\)?\s+(?:on\s+the\s+([XY])-axis|to\s+the\s+(right|left)|(?:going\s+)?(right|left|down|up))\s+from\s+(?:Point\s+)?([A-Za-z_][A-Za-z0-9_]*)$",
            line,
            re.IGNORECASE,
        )
        if m_axis:
            pid = m_axis.group(1)
            expr = m_axis.group(2).strip()
            axis = m_axis.group(3)
            dir1 = m_axis.group(4)
            dir2 = m_axis.group(5)
            ref_pt = m_axis.group(6)
            if axis:
                direction = "right" if axis.upper() == "X" else "down"
            else:
                direction = (dir1 or dir2).lower()
            dx, dy = cls._dir_to_dx_dy(direction, expr)
            cls._upsert_point(
                block_spec,
                {"id": pid, "label": f"Point {pid}", "type": "offset", "from": ref_pt, "dx": dx, "dy": dy},
            )
            return

        # 5. General 2D Offset:
        #    "Point W_B is offset (back_waist_span, -1.25cm) from Point A"
        #    "From A offset (dx, dy) to W_B"
        m_off = re.match(
            r"^(?:Point\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+is\s+offset\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)\s+from\s+(?:Point\s+)?([A-Za-z_][A-Za-z0-9_]*)$",
            line,
            re.IGNORECASE,
        )
        if m_off:
            pid, dx_e, dy_e, ref_pt = (
                m_off.group(1),
                m_off.group(2).strip(),
                m_off.group(3).strip(),
                m_off.group(4),
            )
            cls._upsert_point(
                block_spec,
                {"id": pid, "label": f"Point {pid}", "type": "offset", "from": ref_pt, "dx": dx_e, "dy": dy_e},
            )
            return

        # 6. Squaring / Coordinate Reference:
        #    "Square from B.x and C.y as D" or "Point D has X of B and Y of C" or "Point D is coord (B.x, C.y)"
        m_sq1 = re.match(
            r"^(?:Square\s+from\s+|Point\s+([A-Za-z_][A-Za-z0-9_]*)\s+is\s+coord\s*\(\s*)([^,]+?)(?:\s+and\s+|\s*,\s*)([^)]+?)\)?(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?$",
            line,
            re.IGNORECASE,
        )
        if m_sq1 and (m_sq1.group(1) or m_sq1.group(4)):
            pid = m_sq1.group(1) or m_sq1.group(4)
            x_e = m_sq1.group(2).strip()
            y_e = m_sq1.group(3).strip()
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", x_e):
                x_e = f"{x_e}.x"
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", y_e):
                y_e = f"{y_e}.y"
            cls._upsert_point(
                block_spec,
                {"id": pid, "label": f"Point {pid}", "type": "coord_ref", "x": x_e, "y": y_e},
            )
            return

        m_sq2 = re.match(
            r"^(?:Square\s+down\s+from\s+([A-Za-z_][A-Za-z0-9_]*)\s+and\s+across\s+from\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:to|as)\s+([A-Za-z_][A-Za-z0-9_]*)|Point\s+([A-Za-z_][A-Za-z0-9_]*)\s+has\s+X\s+of\s+([A-Za-z_][A-Za-z0-9_]*)\s+and\s+Y\s+of\s+([A-Za-z_][A-Za-z0-9_]*))$",
            line,
            re.IGNORECASE,
        )
        if m_sq2:
            if m_sq2.group(3):
                px, py, pid = m_sq2.group(1), m_sq2.group(2), m_sq2.group(3)
            else:
                pid, px, py = m_sq2.group(4), m_sq2.group(5), m_sq2.group(6)
            cls._upsert_point(
                block_spec,
                {"id": pid, "label": f"Point {pid}", "type": "coord_ref", "x": f"{px}.x", "y": f"{py}.y"},
            )
            return

        # 7. Polar (Distance & Angle):
        #    "Point B_Sh_Tip is (shoulder_length + 1.2cm) at angle (18) from BN_Side"
        #    "From BN_Side go (shoulder_length) at angle 18 deg to B_Sh_Tip"
        m_polar = re.match(
            r"^(?:Point\s+([A-Za-z_][A-Za-z0-9_]*)\s+is\s+\(?(.+?)\)?\s+at\s+angle\s+\(?([^)]+?)\)?(?:\s*deg(?:rees)?)?\s+from\s+(?:Point\s+)?([A-Za-z_][A-Za-z0-9_]*)|From\s+(?:Point\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+go\s+\(?(.+?)\)?\s+at\s+angle\s+\(?([^)]+?)\)?(?:\s*deg(?:rees)?)?\s+(?:to|as)\s+(?:Point\s+)?([A-Za-z_][A-Za-z0-9_]*))$",
            line,
            re.IGNORECASE,
        )
        if m_polar:
            if m_polar.group(1):
                pid, l_e, a_e, ref_pt = m_polar.group(1), m_polar.group(2), m_polar.group(3), m_polar.group(4)
            else:
                ref_pt, l_e, a_e, pid = m_polar.group(5), m_polar.group(6), m_polar.group(7), m_polar.group(8)
            a_clean = re.sub(r"\s*deg(?:rees)?\s*$", "", a_e.strip(), flags=re.IGNORECASE)
            cls._upsert_point(
                block_spec,
                {
                    "id": pid,
                    "label": f"Point {pid}",
                    "type": "polar",
                    "from": ref_pt,
                    "length": l_e.strip(),
                    "angle": a_clean,
                },
            )
            return

        # 8. Midpoint & Line Interpolation:
        #    "Midpoint of A and W_B is BD_M"
        #    "Point BD_M is ratio (0.5) along A to W_B"
        #    "Point BD_L is distance (dist(A, BD_M) - 1.75cm) along A to W_B"
        m_mid = re.match(
            r"^Midpoint\s+of\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:and|to)\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:is|as)\s+([A-Za-z_][A-Za-z0-9_]*)$",
            line,
            re.IGNORECASE,
        )
        if m_mid:
            p1, p2, pid = m_mid.group(1), m_mid.group(2), m_mid.group(3)
            cls._upsert_point(
                block_spec,
                {"id": pid, "label": f"Point {pid}", "type": "line_interp", "line": [p1, p2], "t": "0.5"},
            )
            return

        m_interp = re.match(
            r"^Point\s+([A-Za-z_][A-Za-z0-9_]*)\s+is\s+(ratio|distance|dist)\s+\(?(.+?)\)?\s+along\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:->|to|-)\s*([A-Za-z_][A-Za-z0-9_]*)$",
            line,
            re.IGNORECASE,
        )
        if m_interp:
            pid, mode, expr, p1, p2 = (
                m_interp.group(1),
                m_interp.group(2).lower(),
                m_interp.group(3).strip(),
                m_interp.group(4),
                m_interp.group(5),
            )
            pt_dict: Dict[str, Any] = {
                "id": pid,
                "label": f"Point {pid}",
                "type": "line_interp",
                "line": [p1, p2],
            }
            if mode == "ratio":
                pt_dict["t"] = expr
            else:
                pt_dict["distance"] = expr
            cls._upsert_point(block_spec, pt_dict)
            return

        # 9. Perpendicular Point:
        #    "Point Apex is perpendicular (14cm) (left|right) from BD_M on line A to W_B"
        m_perp = re.match(
            r"^Point\s+([A-Za-z_][A-Za-z0-9_]*)\s+is\s+perpendicular\s+\(?(.+?)\)?\s*(?:(left|right)\s+)?from\s+([A-Za-z_][A-Za-z0-9_]*)\s+on\s+line\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:->|to|-)\s*([A-Za-z_][A-Za-z0-9_]*)$",
            line,
            re.IGNORECASE,
        )
        if m_perp:
            pid, l_e, side, from_pt, p1, p2 = (
                m_perp.group(1),
                m_perp.group(2).strip(),
                (m_perp.group(3) or "left").lower(),
                m_perp.group(4),
                m_perp.group(5),
                m_perp.group(6),
            )
            cls._upsert_point(
                block_spec,
                {
                    "id": pid,
                    "label": f"Point {pid}",
                    "type": "perpendicular",
                    "line": [p1, p2],
                    "from": from_pt,
                    "length": l_e,
                    "side": side,
                },
            )
            return

        # 10. Intersections (Line-Line, Circle-Line, Circle-Circle):
        #     "Intersect line A-B and line C-D at P_Int"
        m_ll = re.match(
            r"^Intersect\s+line\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:->|to|-)\s*([A-Za-z_][A-Za-z0-9_]*)\s+(?:and|with)\s+line\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:->|to|-)\s*([A-Za-z_][A-Za-z0-9_]*)\s+(?:at|as)\s+([A-Za-z_][A-Za-z0-9_]*)$",
            line,
            re.IGNORECASE,
        )
        if m_ll:
            p1, p2, p3, p4, pid = m_ll.groups()
            cls._upsert_point(
                block_spec,
                {
                    "id": pid,
                    "label": f"Point {pid}",
                    "type": "line_intersection",
                    "line1": [p1, p2],
                    "line2": [p3, p4],
                },
            )
            return

        m_cl = re.match(
            r"^Intersect\s+circle\s+at\s+([A-Za-z_][A-Za-z0-9_]*)\s+radius\s+\(?(.+?)\)?\s+with\s+line\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:->|to|-)\s*([A-Za-z_][A-Za-z0-9_]*)\s+(?:at|as)\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*\(\s*select\s+([a-z_]+)\s*\))?$",
            line,
            re.IGNORECASE,
        )
        if m_cl:
            c_id, r_e, lp1, lp2, pid, sel = m_cl.groups()
            cls._upsert_point(
                block_spec,
                {
                    "id": pid,
                    "label": f"Point {pid}",
                    "type": "circle_line_intersection",
                    "center": c_id,
                    "radius": r_e.strip(),
                    "line": [lp1, lp2],
                    "select": (sel or "first").lower(),
                },
            )
            return

        # 11. Construction Line / Smooth Spline / Cubic Bezier:
        #     "Guide line cb_line from A to C" or "Line cb_line from A to C"
        m_cline = re.match(
            r"^(?:Guide\s+)?Line\s+([A-Za-z_][A-Za-z0-9_]*)\s+from\s+([A-Za-z_][A-Za-z0-9_]*)\s+to\s+([A-Za-z_][A-Za-z0-9_]*)$",
            line,
            re.IGNORECASE,
        )
        if m_cline:
            cid, p0, p1 = m_cline.groups()
            cls._upsert_curve(
                block_spec,
                {"id": cid, "label": cid, "type": "line", "from": p0, "to": p1},
            )
            return

        #     "Smooth curve back_armhole through B_Sh_Tip, B_Cross, B_Underarm"
        m_spline = re.match(
            r"^(?:Smooth\s+curve|Spline)\s+([A-Za-z_][A-Za-z0-9_]*)\s+through\s+(.+)$",
            line,
            re.IGNORECASE,
        )
        if m_spline:
            cid = m_spline.group(1)
            pts = [p.strip() for p in re.split(r"[,->]+", m_spline.group(2)) if p.strip()]
            cls._upsert_curve(
                block_spec,
                {"id": cid, "label": cid, "type": "spline", "points": pts},
            )
            return

        #     "Bezier curve back_hip_curve from W_B to H_B handles (78, dist(W_B, H_B)*0.38) and (-90, dist(W_B, H_B)*0.38)"
        m_bez = re.match(
            r"^Bezier(?:\s+curve)?\s+([A-Za-z_][A-Za-z0-9_]*)\s+from\s+([A-Za-z_][A-Za-z0-9_]*)\s+to\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+handles\s+(.+))?$",
            line,
            re.IGNORECASE,
        )
        if m_bez:
            cid, p0, p3, handles_raw = m_bez.groups()
            a1, l1, a2, l2 = "45", f"dist({p0}, {p3}) * 0.35", "-90", f"dist({p0}, {p3}) * 0.35"
            if handles_raw:
                h_parts = re.split(r"\)\s+and\s+\(", handles_raw.strip())
                if len(h_parts) == 2:
                    h1_str = h_parts[0].lstrip("(").strip()
                    h2_str = h_parts[1].rstrip(")").strip()
                    if "," in h1_str:
                        a1_cand, l1_cand = h1_str.split(",", 1)
                        a1, l1 = a1_cand.strip(), l1_cand.strip()
                    if "," in h2_str:
                        a2_cand, l2_cand = h2_str.split(",", 1)
                        a2, l2 = a2_cand.strip(), l2_cand.strip()
            c_dict: Dict[str, Any] = {
                "id": cid,
                "label": cid,
                "type": "cubic_bezier",
                "p0": p0,
                "p3": p3,
                "handle1_angle": a1,
                "handle1_length": l1,
                "handle2_angle": a2,
                "handle2_length": l2,
            }
            cls._upsert_curve(block_spec, c_dict)
            return

        # 12. Pattern Piece Boundary:
        #     `Piece skirt_back "Skirt Back Block" (cut 2, sa 1.0cm): A -> BD_L -> curve(back_hip_curve) -> C -> A`
        m_piece = re.match(
            r"^Piece\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+\"([^\"]+)\")?(?:\s*\(\s*cut\s+(\d+)(?:\s*,\s*sa\s+([0-9.]+)\s*(?:cm)?)?\s*\))?\s*:\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        if m_piece:
            pid, pname, cut_str, sa_str, chain_str = m_piece.groups()
            pname = pname or pid.replace("_", " ").title()
            cut_count = int(cut_str) if cut_str else 1
            sa_cm = float(sa_str) if sa_str else 1.0

            tokens = [t.strip() for t in re.split(r"\s*->\s*|\s*,\s*", chain_str) if t.strip()]
            boundary = cls._compile_piece_chain(tokens, block_spec)
            piece_obj = pieces_by_id.get(
                pid,
                {
                    "id": pid,
                    "name": pname,
                    "cut_count": cut_count,
                    "seam_allowance_cm": sa_cm,
                    "boundary": boundary,
                    "internal_lines": [],
                    "notches": [],
                },
            )
            piece_obj["name"] = pname
            piece_obj["cut_count"] = cut_count
            piece_obj["seam_allowance_cm"] = sa_cm
            piece_obj["boundary"] = boundary
            if pid not in pieces_by_id:
                pieces_by_id[pid] = piece_obj
                block_spec["pieces"].append(piece_obj)
            return

        # 13. Dart / Internal Line on Piece:
        #     `Dart on skirt_back: BD_L -> BD_Apex -> BD_R`
        #     `Internal line on skirt_back: E -> H_B`
        m_int = re.match(
            r"^(Dart|Internal(?:\s+line)?|Fold(?:\s+line)?)\s+on\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        if m_int:
            kind_raw, pid, pts_str = m_int.groups()
            piece_obj = cls._ensure_piece(pid, pieces_by_id, block_spec)
            pts = [p.strip() for p in re.split(r"\s*->\s*|\s*,\s*", pts_str) if p.strip()]
            ltype = "dart" if kind_raw.lower().startswith("dart") else (
                "fold" if kind_raw.lower().startswith("fold") else "internal"
            )
            il_id = f"{ltype}_{len(piece_obj['internal_lines']) + 1}"
            piece_obj["internal_lines"].append(
                {"id": il_id, "label": f"{ltype.title()} ({'->'.join(pts)})", "type": ltype, "points": pts}
            )
            return

        # 14. Grainline on Piece:
        #     `Grainline on skirt_back: BG_Top -> BG_Bot`
        m_grain = re.match(
            r"^Grainline\s+on\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:->|to|,)\s*([A-Za-z_][A-Za-z0-9_]*)$",
            line,
            re.IGNORECASE,
        )
        if m_grain:
            pid, g_from, g_to = m_grain.groups()
            piece_obj = cls._ensure_piece(pid, pieces_by_id, block_spec)
            piece_obj["grainline"] = {"from": g_from, "to": g_to, "label": f"{pid.upper()} GRAINLINE"}
            return

        # 15. Notch on Piece:
        #     `Notch on skirt_back at H_B along H_B -> Hem_B (count 2)`
        m_notch = re.match(
            r"^Notch\s+on\s+([A-Za-z_][A-Za-z0-9_]*)\s+at\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+along\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:->|to)\s*([A-Za-z_][A-Za-z0-9_]*))?(?:\s*\(\s*count\s+(\d+)\s*\))?$",
            line,
            re.IGNORECASE,
        )
        if m_notch:
            pid, pt_id, e_from, e_to, cnt_str = m_notch.groups()
            piece_obj = cls._ensure_piece(pid, pieces_by_id, block_spec)
            piece_obj["notches"].append(
                {
                    "id": f"notch_{pt_id}_{len(piece_obj['notches']) + 1}",
                    "point": pt_id,
                    "edge_from": e_from or pt_id,
                    "edge_to": e_to or pt_id,
                    "count": int(cnt_str) if cnt_str else 1,
                }
            )
            return

        raise ValueError(f"Unrecognized notebook instruction: '{line}'")

    @staticmethod
    def _dir_to_dx_dy(direction: str, expr: str) -> Tuple[str, str]:
        d = direction.lower()
        if d in ("right", "east"):
            return (expr, "0")
        if d in ("left", "west"):
            return (f"-({expr})", "0")
        if d in ("down", "south"):
            return ("0", expr)
        if d in ("up", "north"):
            return ("0", f"-({expr})")
        return (expr, "0")

    @staticmethod
    def _upsert_point(block_spec: Dict[str, Any], pt_dict: Dict[str, Any]) -> None:
        pts = block_spec["points"]
        for i, existing in enumerate(pts):
            if existing.get("id") == pt_dict["id"]:
                pts[i] = pt_dict
                return
        pts.append(pt_dict)

    @staticmethod
    def _upsert_curve(block_spec: Dict[str, Any], c_dict: Dict[str, Any]) -> None:
        curves = block_spec["construction"]
        for i, existing in enumerate(curves):
            if existing.get("id") == c_dict["id"]:
                curves[i] = c_dict
                return
        curves.append(c_dict)

    @staticmethod
    def _ensure_piece(
        pid: str,
        pieces_by_id: Dict[str, Dict[str, Any]],
        block_spec: Dict[str, Any],
    ) -> Dict[str, Any]:
        if pid not in pieces_by_id:
            obj: Dict[str, Any] = {
                "id": pid,
                "name": pid.replace("_", " ").title(),
                "cut_count": 1,
                "seam_allowance_cm": 1.0,
                "boundary": [],
                "internal_lines": [],
                "notches": [],
            }
            pieces_by_id[pid] = obj
            block_spec["pieces"].append(obj)
        return pieces_by_id[pid]

    @classmethod
    def _compile_piece_chain(
        cls,
        tokens: Sequence[str],
        block_spec: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Convert a token chain like `["A", "BD_L", "BD_R", "W_B", "curve(back_hip_curve)", "H_B", "Hem_B", "C", "A"]`
        into boundary segments (`line` and `curve_ref`).
        """
        known_curves = {c["id"]: c for c in block_spec.get("construction", [])}
        boundary: List[Dict[str, Any]] = []

        i = 0
        n = len(tokens)
        while i < n:
            tok = tokens[i]
            m_cref = re.match(r"^(?:curve|rev_curve)\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)$", tok, re.IGNORECASE)
            if m_cref or tok in known_curves:
                cid = m_cref.group(1) if m_cref else tok
                is_rev = tok.lower().startswith("rev_curve(")
                boundary.append({"type": "curve_ref", "curve_id": cid, "reverse": is_rev})
                i += 1
                continue

            if i + 1 < n:
                next_tok = tokens[i + 1]
                # If next token is a curve reference, don't emit a straight line across the curve
                if re.match(r"^(?:curve|rev_curve)\(", next_tok, re.IGNORECASE) or next_tok in known_curves:
                    i += 1
                    continue
                boundary.append({"type": "line", "from": tok, "to": next_tok})
            i += 1

        return boundary


# ---------------------------------------------------------------------------
# Decompiler: Block Instruction JSON -> Pattern Cutting Textbook Notebook
# ---------------------------------------------------------------------------


def block_spec_to_notebook_script(block_spec: Mapping[str, Any]) -> str:
    """Convert a canonical `block_spec` JSON dictionary into a readable Pattern Cutting Notebook script."""
    lines: List[str] = [
        f"# ===========================================================================",
        f"# PATTERN CUTTING NOTEBOOK: {block_spec.get('name', 'Custom Block')}",
        f"# {block_spec.get('description', '')}",
        f"# ===========================================================================",
        "",
    ]

    derived = block_spec.get("derived_variables", {})
    if derived:
        lines.append("# --- 1. Derived Variables & Ease Formulas ---")
        for k, v in derived.items():
            lines.append(f"Var {k} = {v}")
        lines.append("")

    pts = block_spec.get("points", [])
    if pts:
        lines.append("# --- 2. Parametric Construction Points ---")
        for idx, pt in enumerate(pts, start=1):
            lines.append(f"{idx}. {format_point_as_notebook_line(pt)}")
        lines.append("")

    curves = block_spec.get("construction", [])
    if curves:
        lines.append("# --- 3. Construction Curves & Guidelines ---")
        for c in curves:
            lines.append(format_curve_as_notebook_line(c))
        lines.append("")

    pieces = block_spec.get("pieces", [])
    if pieces:
        lines.append("# --- 4. Extracted Pattern Pieces, Darts, Grainlines & Notches ---")
        for p in pieces:
            lines.extend(format_piece_as_notebook_lines(p))
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def format_point_as_notebook_line(pt: Mapping[str, Any]) -> str:
    pid = str(pt["id"])
    ptype = str(pt.get("type", "absolute")).lower()

    if ptype == "absolute":
        x_e, y_e = str(pt.get("x", 0)), str(pt.get("y", 0))
        if x_e in ("0", "0.0") and y_e in ("0", "0.0"):
            return f"Point {pid} is the origin (0, 0)"
        return f"Point {pid} is ({x_e}, {y_e})"

    if ptype == "offset":
        ref = str(pt["from"])
        dx = str(pt.get("dx", "0")).strip()
        dy = str(pt.get("dy", "0")).strip()
        if dy in ("0", "0.0"):
            return f"From {ref} go right ({dx}) to {pid}"
        if dx in ("0", "0.0"):
            return f"From {ref} go down ({dy}) to {pid}"
        return f"Point {pid} is offset ({dx}, {dy}) from {ref}"

    if ptype == "coord_ref":
        return f"Point {pid} is coord ({pt.get('x', 0)}, {pt.get('y', 0)})"

    if ptype == "polar":
        return (
            f"Point {pid} is ({pt.get('length', 0)}) at angle ({pt.get('angle', 0)}) "
            f"from {pt.get('from', 'A')}"
        )

    if ptype == "line_interp":
        l_ids = pt.get("line", ["A", "B"])
        if "t" in pt:
            t_str = str(pt["t"]).strip()
            if t_str in ("0.5", "1/2"):
                return f"Midpoint of {l_ids[0]} and {l_ids[1]} is {pid}"
            return f"Point {pid} is ratio ({t_str}) along {l_ids[0]} -> {l_ids[1]}"
        return f"Point {pid} is distance ({pt.get('distance', 0)}) along {l_ids[0]} -> {l_ids[1]}"

    if ptype == "perpendicular":
        l_ids = pt.get("line", ["A", "B"])
        side = str(pt.get("side", "left"))
        from_pt = str(pt.get("from", l_ids[0]))
        return (
            f"Point {pid} is perpendicular ({pt.get('length', 0)}) {side} "
            f"from {from_pt} on line {l_ids[0]} -> {l_ids[1]}"
        )

    if ptype == "line_intersection":
        l1 = pt.get("line1", ["A", "B"])
        l2 = pt.get("line2", ["C", "D"])
        return f"Intersect line {l1[0]}->{l1[1]} and line {l2[0]}->{l2[1]} at {pid}"

    if ptype == "circle_line_intersection":
        l_ids = pt.get("line", ["A", "B"])
        sel = pt.get("select", "first")
        return (
            f"Intersect circle at {pt['center']} radius ({pt['radius']}) "
            f"with line {l_ids[0]}->{l_ids[1]} at {pid} (select {sel})"
        )

    return f"Point {pid} is ({pt.get('x', 0)}, {pt.get('y', 0)})"


def format_curve_as_notebook_line(c: Mapping[str, Any]) -> str:
    cid = str(c["id"])
    ctype = str(c["type"]).lower()
    if ctype == "line":
        return f"Line {cid} from {c['from']} to {c['to']}"
    if ctype == "spline":
        pts_str = ", ".join(str(p) for p in c.get("points", []))
        return f"Smooth curve {cid} through {pts_str}"
    if ctype == "cubic_bezier":
        return (
            f"Bezier curve {cid} from {c['p0']} to {c['p3']} "
            f"handles ({c.get('handle1_angle', 0)}, {c.get('handle1_length', '5cm')}) "
            f"and ({c.get('handle2_angle', 180)}, {c.get('handle2_length', '5cm')})"
        )
    return f"# Curve {cid}"


def format_piece_as_notebook_lines(p: Mapping[str, Any]) -> List[str]:
    pid = str(p["id"])
    pname = str(p.get("name", pid))
    cut = int(p.get("cut_count", 1))
    sa = float(p.get("seam_allowance_cm", 1.0))

    tokens: List[str] = []
    for seg in p.get("boundary", []):
        stype = str(seg.get("type", "line")).lower()
        if stype == "line":
            f_pt, t_pt = str(seg["from"]), str(seg["to"])
            if not tokens or tokens[-1] != f_pt:
                tokens.append(f_pt)
            tokens.append(t_pt)
        elif stype == "curve_ref":
            cid = str(seg["curve_id"])
            rev = bool(seg.get("reverse", False))
            tokens.append(f"rev_curve({cid})" if rev else f"curve({cid})")

    chain = " -> ".join(tokens)
    out = [f'Piece {pid} "{pname}" (cut {cut}, sa {sa:.1f}cm): {chain}']

    for il in p.get("internal_lines", []):
        ltype = str(il.get("type", "internal")).lower()
        prefix = "Dart" if ltype == "dart" else ("Fold line" if ltype == "fold" else "Internal line")
        pts_chain = " -> ".join(str(pt) for pt in il.get("points", []))
        out.append(f"{prefix} on {pid}: {pts_chain}")

    if "grainline" in p and p["grainline"]:
        gl = p["grainline"]
        out.append(f"Grainline on {pid}: {gl['from']} -> {gl['to']}")

    for n in p.get("notches", []):
        cnt = int(n.get("count", 1))
        ef = n.get("edge_from", n["point"])
        et = n.get("edge_to", n["point"])
        out.append(f"Notch on {pid} at {n['point']} along {ef} -> {et} (count {cnt})")

    return out


# ---------------------------------------------------------------------------
# Option 5: Smart Parametric Formula Suggester (Trace-to-Formula)
# ---------------------------------------------------------------------------


def suggest_parametric_formulas(
    target_distance_cm: float,
    measurements: Mapping[str, float],
    max_suggestions: int = 5,
) -> List[Tuple[str, str]]:
    """
    Given a traced distance in centimeters (`target_distance_cm`) and the active body
    measurements dict, return a list of `(formula_string, explanation_label)` candidates
    sorted by how closely a standard pattern-making fraction of a body measurement matches.
    """
    abs_d = abs(target_distance_cm)
    sign_prefix = "-" if target_distance_cm < -1e-4 else ""

    if abs_d < 0.05:
        return [("0", "Zero offset (0.00 cm)")]

    candidates: List[Tuple[float, str, str]] = []
    divisors = [1, 2, 4, 5, 6, 8, 10]

    for m_key, m_val in measurements.items():
        if m_val <= 0 or " " in m_key:
            continue
        for div in divisors:
            base = m_val / div
            diff = abs_d - base
            # Prefer formulas where the residual ease/offset is within [-6cm, +6cm]
            if abs(diff) <= 6.0:
                base_expr = m_key if div == 1 else f"{m_key} / {div}"
                if abs(diff) < 0.08:
                    expr = f"{sign_prefix}({base_expr})" if sign_prefix else base_expr
                elif diff > 0:
                    expr = f"{base_expr} + {diff:.2f}cm"
                    if sign_prefix:
                        expr = f"-({expr})"
                else:
                    expr = f"{base_expr} - {abs(diff):.2f}cm"
                    if sign_prefix:
                        expr = f"-({expr})"

                # Score favors small residual diff and common divisors (1, 2, 4)
                div_penalty = 0.0 if div in (1, 2, 4) else 0.4
                score = abs(diff) + div_penalty
                desc = f"{expr}  [= {target_distance_cm:.2f} cm from {m_key}={m_val:.1f}cm]"
                candidates.append((score, expr, desc))

    candidates.sort(key=lambda item: item[0])

    # Deduplicate while preserving order, and always include the exact measured cm literal
    results: List[Tuple[str, str]] = []
    seen = set()
    for _, expr, desc in candidates:
        if expr not in seen:
            seen.add(expr)
            results.append((expr, desc))
            if len(results) >= max_suggestions - 1:
                break

    exact_expr = f"{target_distance_cm:.2f}cm"
    results.append((exact_expr, f"{exact_expr}  [Exact measured distance]"))
    return results
