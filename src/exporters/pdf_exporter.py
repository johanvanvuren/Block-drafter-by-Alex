"""
1:1 Scale Print-Ready PDF Exporter (Large-Format Plotters & Home-Printer Tiling).

Features:
- Enforces exact physical paper dimensions (A0, 36" Roll, A4, US Letter) at 1:1 scale (1 cm = 28.3464567 pt)
- For Tiled Home Printer layouts (A4 / US Letter):
  * Optional Page 0 Assembly Map showing the full tile grid, piece placement, and paper/waste stats
  * Clipped 1:1 pattern tiles with user-defined margins
  * Automatic Corner Crosshairs + Assembly Diamonds at all 4 margin corners
  * Page numbering & Grid Coordinate watermarks (e.g., "Tile R1C1 (A1)")
  * 5.0 cm x 5.0 cm (50 mm x 50 mm) 1:1 Scale Verification Box on the first pattern tile
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence, Tuple

from src.core.drafting_engine import DraftedBlockResult
from src.core.geometry import Point2D, polygon_centroid
from src.layout.nesting_engine import LayoutResult, PlacedPiece, TilePage

CM_TO_PT = 72.0 / 2.54  # 28.346456692913385 points per centimeter

try:
    from reportlab.pdfgen import canvas as rl_canvas

    HAS_REPORTLAB = True
except ImportError:  # pragma: no cover
    HAS_REPORTLAB = False


class PDFExporter:
    """Generates 1:1 scale print-ready PDFs for large-format plotters and tiled home printers."""

    @staticmethod
    def _layout_to_page_pt(
        pt: Point2D,
        tile: TilePage,
    ) -> Tuple[float, float]:
        """
        Convert layout coordinate (cm, y-down) into ReportLab page coordinate (pt, y-up)
        for a given `tile`.
        """
        local_x_cm = tile.margin_cm + (pt.x - tile.clip_min_x)
        local_y_down_cm = tile.margin_cm + (pt.y - tile.clip_min_y)
        local_y_up_cm = tile.paper_height_cm - local_y_down_cm
        return (local_x_cm * CM_TO_PT, local_y_up_cm * CM_TO_PT)

    @classmethod
    def export_layout(
        cls,
        draft: DraftedBlockResult,
        layout: LayoutResult,
        output_path: str | Path,
        include_assembly_map: bool = True,
        include_seam_allowance: bool = True,
    ) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        if HAS_REPORTLAB:
            cls._export_with_reportlab(
                draft=draft,
                layout=layout,
                output_path=out,
                include_assembly_map=include_assembly_map,
                include_seam_allowance=include_seam_allowance,
            )
        else:
            cls._export_fallback_pdf(
                draft=draft,
                layout=layout,
                output_path=out,
                include_seam_allowance=include_seam_allowance,
            )
        return out

    @classmethod
    def _export_with_reportlab(
        cls,
        draft: DraftedBlockResult,
        layout: LayoutResult,
        output_path: Path,
        include_assembly_map: bool,
        include_seam_allowance: bool,
    ) -> None:
        active_pages = [p for p in layout.pages if p.has_content]
        if not active_pages:
            active_pages = layout.pages[:1]

        first_w_pt = active_pages[0].paper_width_cm * CM_TO_PT
        first_h_pt = active_pages[0].paper_height_cm * CM_TO_PT

        c = rl_canvas.Canvas(str(output_path), pagesize=(first_w_pt, first_h_pt))
        c.setTitle(f"{draft.name} - {layout.paper_format.name}")
        c.setAuthor("Block Drafter by Alex")

        # 1. Optional Assembly Overview Page for Tiled Multi-Page Prints
        if include_assembly_map and layout.paper_format.is_tiled and len(active_pages) > 1:
            cls._draw_assembly_map_page(c, draft, layout, active_pages)
            c.showPage()

        # 2. Render each 1:1 Scale Sheet / Tile Page
        total_tiles = len(active_pages)
        for idx, tile in enumerate(active_pages):
            pw_pt = tile.paper_width_cm * CM_TO_PT
            ph_pt = tile.paper_height_cm * CM_TO_PT
            c.setPageSize((pw_pt, ph_pt))

            cls._draw_tile_page(
                c=c,
                draft=draft,
                layout=layout,
                tile=tile,
                tile_index=idx + 1,
                total_tiles=total_tiles,
                include_seam_allowance=include_seam_allowance,
                draw_scale_box=(idx == 0),
            )
            c.showPage()

        c.save()

    @classmethod
    def _draw_assembly_map_page(
        cls,
        c: "rl_canvas.Canvas",
        draft: DraftedBlockResult,
        layout: LayoutResult,
        active_pages: Sequence[TilePage],
    ) -> None:
        pw_cm = active_pages[0].paper_width_cm
        ph_cm = active_pages[0].paper_height_cm
        pw_pt = pw_cm * CM_TO_PT
        ph_pt = ph_cm * CM_TO_PT

        # Title Header
        c.setFillColorRGB(0.06, 0.09, 0.16)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(1.5 * CM_TO_PT, ph_pt - 1.8 * CM_TO_PT, f"PATTERN TILING ASSEMBLY MAP — {draft.name}")

        c.setFont("Helvetica", 9.5)
        c.setFillColorRGB(0.28, 0.33, 0.41)
        stats_line1 = (
            f"Format: {layout.paper_format.name}  |  Active Pages: {layout.active_page_count} "
            f"(Grid {layout.grid_rows} rows × {layout.grid_cols} cols)  |  Margin: {layout.margin_cm:.2f} cm"
        )
        stats_line2 = (
            f"Pattern Area: {layout.pattern_area_cm2:.1f} cm²  |  Total Paper Area: {layout.total_paper_area_cm2:.1f} cm² "
            f"({layout.total_paper_area_cm2 / 10000.0:.3f} m²)  |  Paper Waste: {layout.waste_percentage:.1f}%"
        )
        c.drawString(1.5 * CM_TO_PT, ph_pt - 2.45 * CM_TO_PT, stats_line1)
        c.drawString(1.5 * CM_TO_PT, ph_pt - 2.95 * CM_TO_PT, stats_line2)

        # Compute scale to fit the entire tile grid inside the map box
        avail_w_cm = pw_cm - 3.0
        avail_h_cm = ph_cm - 6.0
        total_grid_w = max(1.0, layout.grid_cols * active_pages[0].printable_width_cm)
        total_grid_h = max(1.0, layout.grid_rows * active_pages[0].printable_height_cm)
        map_scale = min(avail_w_cm / total_grid_w, avail_h_cm / total_grid_h) * 0.9

        origin_x_pt = 1.5 * CM_TO_PT
        origin_top_y_pt = ph_pt - 3.8 * CM_TO_PT

        # Draw each grid cell in the mini-map
        for p in layout.pages:
            gx_pt = origin_x_pt + p.clip_min_x * map_scale * CM_TO_PT
            gy_top_pt = origin_top_y_pt - p.clip_min_y * map_scale * CM_TO_PT
            gw_pt = p.printable_width_cm * map_scale * CM_TO_PT
            gh_pt = p.printable_height_cm * map_scale * CM_TO_PT

            if p.has_content:
                c.setFillColorRGB(0.95, 0.97, 1.0)
                c.setStrokeColorRGB(0.23, 0.51, 0.96)
            else:
                c.setFillColorRGB(0.96, 0.96, 0.96)
                c.setStrokeColorRGB(0.75, 0.75, 0.75)

            c.setLineWidth(0.8)
            c.rect(gx_pt, gy_top_pt - gh_pt, gw_pt, gh_pt, fill=1, stroke=1)

            c.setFillColorRGB(0.15, 0.23, 0.35)
            c.setFont("Helvetica-Bold", 7.5)
            label = f"{p.grid_code}" if p.has_content else f"{p.grid_code} (Skip)"
            c.drawString(gx_pt + 4, gy_top_pt - 11, label)

        # Draw miniature packed pieces inside the grid
        c.setStrokeColorRGB(0.06, 0.09, 0.16)
        c.setLineWidth(1.1)
        for placed in layout.placed_pieces:
            pts = placed.boundary_polygon
            if len(pts) < 2:
                continue
            path = c.beginPath()
            for i, pt in enumerate(pts):
                px = origin_x_pt + pt.x * map_scale * CM_TO_PT
                py = origin_top_y_pt - pt.y * map_scale * CM_TO_PT
                if i == 0:
                    path.moveTo(px, py)
                else:
                    path.lineTo(px, py)
            path.close()
            c.drawPath(path, stroke=1, fill=0)

    @classmethod
    def _draw_tile_page(
        cls,
        c: "rl_canvas.Canvas",
        draft: DraftedBlockResult,
        layout: LayoutResult,
        tile: TilePage,
        tile_index: int,
        total_tiles: int,
        include_seam_allowance: bool,
        draw_scale_box: bool,
    ) -> None:
        pw_pt = tile.paper_width_cm * CM_TO_PT
        ph_pt = tile.paper_height_cm * CM_TO_PT
        m_pt = tile.margin_cm * CM_TO_PT
        clip_w_pt = tile.printable_width_cm * CM_TO_PT
        clip_h_pt = tile.printable_height_cm * CM_TO_PT

        # 1. Draw Trim / Overlap Margin Frame & Corner Alignment Crosshairs + Diamonds
        c.saveState()
        c.setStrokeColorRGB(0.58, 0.64, 0.72)
        c.setLineWidth(0.6)
        c.setDash(4, 3)
        c.rect(m_pt, m_pt, clip_w_pt, clip_h_pt, stroke=1, fill=0)
        c.setDash()

        # Draw 4 corner alignment crosshairs + diamonds
        corners_pt = [
            (m_pt, m_pt),
            (m_pt + clip_w_pt, m_pt),
            (m_pt + clip_w_pt, m_pt + clip_h_pt),
            (m_pt, m_pt + clip_h_pt),
        ]
        target_r = 0.35 * CM_TO_PT
        c.setStrokeColorRGB(0.08, 0.58, 0.53)
        c.setLineWidth(0.8)
        for cx, cy in corners_pt:
            # Crosshair lines
            c.line(cx - target_r * 1.3, cy, cx + target_r * 1.3, cy)
            c.line(cx, cy - target_r * 1.3, cx, cy + target_r * 1.3)
            # Diamond polygon
            d_path = c.beginPath()
            d_path.moveTo(cx, cy + target_r)
            d_path.lineTo(cx + target_r, cy)
            d_path.lineTo(cx, cy - target_r)
            d_path.lineTo(cx - target_r, cy)
            d_path.close()
            c.drawPath(d_path, stroke=1, fill=0)

        # Header / Footer Margin Labels
        c.setFillColorRGB(0.35, 0.41, 0.49)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(
            m_pt + 4,
            ph_pt - m_pt + 4,
            f"{draft.name}  |  Tile {tile.grid_code}  |  Page {tile_index} of {total_tiles}  |  1:1 SCALE",
        )
        c.setFont("Helvetica", 7.0)
        c.drawRightString(
            pw_pt - m_pt - 4,
            ph_pt - m_pt + 4,
            f"Waste: {layout.waste_percentage:.1f}%  |  Print at 100% (Actual Size)",
        )
        c.restoreState()

        # 2. Clip to the printable tile frame and render pattern pieces at 1:1 scale
        c.saveState()
        clip_path = c.beginPath()
        clip_path.rect(m_pt, m_pt, clip_w_pt, clip_h_pt)
        c.clipPath(clip_path, stroke=0, fill=0)

        # Subtle grid watermark in tile center
        c.setFillColorRGB(0.90, 0.92, 0.95)
        c.setFont("Helvetica-Bold", 24)
        c.drawCentredString(pw_pt * 0.5, ph_pt * 0.5, tile.grid_code)

        # Draw 5.0 cm x 5.0 cm Scale Check Square on first tile
        if draw_scale_box:
            box_size_pt = 5.0 * CM_TO_PT
            bx = m_pt + 0.4 * CM_TO_PT
            by = ph_pt - m_pt - box_size_pt - 0.4 * CM_TO_PT
            c.setStrokeColorRGB(0.08, 0.58, 0.53)
            c.setFillColorRGB(0.94, 0.99, 0.98)
            c.setLineWidth(1.0)
            c.rect(bx, by, box_size_pt, box_size_pt, stroke=1, fill=1)
            c.setFillColorRGB(0.06, 0.46, 0.43)
            c.setFont("Helvetica-Bold", 7.5)
            c.drawCentredString(bx + box_size_pt * 0.5, by + box_size_pt * 0.55, "SCALE CHECK")
            c.setFont("Helvetica", 7.0)
            c.drawCentredString(bx + box_size_pt * 0.5, by + box_size_pt * 0.38, "5.0 cm × 5.0 cm")
            c.drawCentredString(bx + box_size_pt * 0.5, by + box_size_pt * 0.22, "(50 mm × 50 mm)")

        for placed in layout.placed_pieces:
            cls._draw_placed_piece_reportlab(c, placed, tile, include_seam_allowance)

        c.restoreState()

    @classmethod
    def _draw_placed_piece_reportlab(
        cls,
        c: "rl_canvas.Canvas",
        placed: PlacedPiece,
        tile: TilePage,
        include_seam_allowance: bool,
    ) -> None:
        # 1. Seam Allowance Outer Cut Line (dashed crimson)
        if (
            include_seam_allowance
            and placed.source_piece.seam_allowance_cm > 1e-6
            and len(placed.seam_allowance_polygon) >= 3
        ):
            c.saveState()
            c.setStrokeColorRGB(0.88, 0.11, 0.28)
            c.setLineWidth(1.1)
            c.setDash(5, 3)
            sa_path = c.beginPath()
            for i, pt in enumerate(placed.seam_allowance_polygon):
                px, py = cls._layout_to_page_pt(pt, tile)
                if i == 0:
                    sa_path.moveTo(px, py)
                else:
                    sa_path.lineTo(px, py)
            sa_path.close()
            c.drawPath(sa_path, stroke=1, fill=0)
            c.restoreState()

        # 2. Net Stitch / Pattern Boundary (solid dark slate)
        if len(placed.boundary_polygon) >= 3:
            c.saveState()
            c.setStrokeColorRGB(0.06, 0.09, 0.16)
            c.setLineWidth(1.5)
            b_path = c.beginPath()
            for i, pt in enumerate(placed.boundary_polygon):
                px, py = cls._layout_to_page_pt(pt, tile)
                if i == 0:
                    b_path.moveTo(px, py)
                else:
                    b_path.lineTo(px, py)
            b_path.close()
            c.drawPath(b_path, stroke=1, fill=0)
            c.restoreState()

        # 3. Internal Lines & Darts
        for il in placed.internal_lines:
            if len(il.points) < 2:
                continue
            c.saveState()
            if il.line_type == "dart":
                c.setStrokeColorRGB(0.49, 0.23, 0.93)
                c.setLineWidth(1.0)
            else:
                c.setStrokeColorRGB(0.39, 0.40, 0.95)
                c.setLineWidth(0.8)
                c.setDash(3, 2)
            il_path = c.beginPath()
            for i, pt in enumerate(il.points):
                px, py = cls._layout_to_page_pt(pt, tile)
                if i == 0:
                    il_path.moveTo(px, py)
                else:
                    il_path.lineTo(px, py)
            c.drawPath(il_path, stroke=1, fill=0)
            c.restoreState()

        # 4. Notches
        c.saveState()
        c.setStrokeColorRGB(0.06, 0.09, 0.16)
        c.setLineWidth(1.2)
        for notch in placed.notches:
            for t0, t1 in notch.ticks:
                p0 = cls._layout_to_page_pt(t0, tile)
                p1 = cls._layout_to_page_pt(t1, tile)
                c.line(p0[0], p0[1], p1[0], p1[1])
        c.restoreState()

        # 5. Grainline
        if placed.grainline:
            c.saveState()
            c.setStrokeColorRGB(0.05, 0.58, 0.53)
            c.setLineWidth(1.0)
            g0 = cls._layout_to_page_pt(placed.grainline.start, tile)
            g1 = cls._layout_to_page_pt(placed.grainline.end, tile)
            c.line(g0[0], g0[1], g1[0], g1[1])
            c.restoreState()

        # 6. Piece Label at Centroid
        c_pt = polygon_centroid(placed.boundary_polygon)
        lx, ly = cls._layout_to_page_pt(c_pt, tile)
        c.saveState()
        c.setFillColorRGB(0.06, 0.09, 0.16)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawCentredString(lx, ly + 4, placed.display_label)
        c.setFont("Helvetica", 7.5)
        c.setFillColorRGB(0.28, 0.33, 0.41)
        c.drawCentredString(
            lx,
            ly - 7,
            f"Rot: {placed.rotation_deg:.0f}° | SA: {placed.source_piece.seam_allowance_cm:.1f} cm",
        )
        c.restoreState()

    @classmethod
    def _export_fallback_pdf(
        cls,
        draft: DraftedBlockResult,
        layout: LayoutResult,
        output_path: Path,
        include_seam_allowance: bool,
    ) -> None:
        """Minimal raw PDF 1.4 vector writer fallback if ReportLab is not yet installed."""
        active_pages = [p for p in layout.pages if p.has_content] or layout.pages[:1]
        objects: List[bytes] = []

        def add_obj(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        font_id = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        page_ids: List[int] = []

        for tile in active_pages:
            pw_pt = tile.paper_width_cm * CM_TO_PT
            ph_pt = tile.paper_height_cm * CM_TO_PT
            m_pt = tile.margin_cm * CM_TO_PT
            cw_pt = tile.printable_width_cm * CM_TO_PT
            ch_pt = tile.printable_height_cm * CM_TO_PT

            cmds: List[str] = [
                "0.5 w",
                f"{m_pt:.2f} {m_pt:.2f} {cw_pt:.2f} {ch_pt:.2f} re S",
                "1.2 w",
            ]
            for placed in layout.placed_pieces:
                pts = placed.boundary_polygon
                if len(pts) >= 3:
                    for i, pt in enumerate(pts):
                        px, py = cls._layout_to_page_pt(pt, tile)
                        cmds.append(f"{px:.2f} {py:.2f} {'m' if i == 0 else 'l'}")
                    cmds.append("s")

            stream_bytes = "\n".join(cmds).encode("latin1")
            content_id = add_obj(
                f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("latin1")
                + stream_bytes
                + b"\nendstream"
            )
            page_id = add_obj(
                f"<< /Type /Page /Parent 99999 0 R /MediaBox [0 0 {pw_pt:.2f} {ph_pt:.2f}] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode(
                    "latin1"
                )
            )
            page_ids.append(page_id)

        kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
        pages_root_id = add_obj(
            f"<< /Type /Pages /Kids [{kids_str}] /Count {len(page_ids)} >>".encode("latin1")
        )
        # Patch parent reference
        for pid in page_ids:
            objects[pid - 1] = objects[pid - 1].replace(b"99999 0 R", f"{pages_root_id} 0 R".encode("latin1"))

        catalog_id = add_obj(f"<< /Type /Catalog /Pages {pages_root_id} 0 R >>".encode("latin1"))

        out_buf = bytearray(b"%PDF-1.4\n")
        offsets: List[int] = [0]
        for idx, obj_bytes in enumerate(objects, start=1):
            offsets.append(len(out_buf))
            out_buf.extend(f"{idx} 0 obj\n".encode("latin1"))
            out_buf.extend(obj_bytes)
            out_buf.extend(b"\nendobj\n")

        xref_pos = len(out_buf)
        out_buf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin1"))
        for off in offsets[1:]:
            out_buf.extend(f"{off:010d} 00000 n \n".encode("latin1"))
        out_buf.extend(
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
                "latin1"
            )
        )
        output_path.write_bytes(bytes(out_buf))
