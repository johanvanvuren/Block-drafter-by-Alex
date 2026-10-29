"""
Print Optimization, 2D Nesting & Home-Printer Tiling Engine (Minimum Waste).

Features:
- Supports Large Format (A0 Sheet, 36-inch Roll) and Home Printer Tiling (A4, US Letter)
- Supports 3 rotation policies:
    1. grainline_locked (0 deg / 180 deg only)
    2. cardinal_90 (0 / 90 / 180 / 270 deg)
    3. free_angle (15 deg increments for tightest bounding fit)
- Computes exact Polygon Area (cm^2), Total Paper Required (cm^2 / m^2), Page Count, and Waste Percentage (%)
- Generates Tiled Pages with user-defined margins, corner Crosshair + Diamond alignment targets,
  grid labels (e.g., R1C1 [A1]), and a 5cm x 5cm 1:1 scale calibration box.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from src.core.drafting_engine import (
    DraftedBlockResult,
    Grainline,
    InternalLine,
    NotchMark,
    ResolvedPatternPiece,
)
from src.core.geometry import BoundingBox, Point2D, polygon_area, polygon_bounding_box


@dataclass(frozen=True)
class PaperFormatSpec:
    """Physical specification of a print format in centimeters."""

    format_id: str
    name: str
    width_cm: float
    height_cm: float  # For rolls, height_cm is 0.0 (dynamic length)
    is_roll: bool = False
    is_tiled: bool = False
    default_margin_cm: float = 1.2


PAPER_FORMATS: Dict[str, PaperFormatSpec] = {
    "A0": PaperFormatSpec(
        format_id="A0",
        name="A0 Plotter Sheet (84.1 × 118.9 cm)",
        width_cm=84.1,
        height_cm=118.9,
        is_roll=False,
        is_tiled=False,
        default_margin_cm=1.5,
    ),
    "ROLL_36": PaperFormatSpec(
        format_id="ROLL_36",
        name='36" Plotter Roll (91.44 cm wide × Dynamic)',
        width_cm=91.44,
        height_cm=0.0,
        is_roll=True,
        is_tiled=False,
        default_margin_cm=1.5,
    ),
    "A4": PaperFormatSpec(
        format_id="A4",
        name="A4 Home Printer Tiled (21.0 × 29.7 cm)",
        width_cm=21.0,
        height_cm=29.7,
        is_roll=False,
        is_tiled=True,
        default_margin_cm=1.2,
    ),
    "US_LETTER": PaperFormatSpec(
        format_id="US_LETTER",
        name="US Letter Home Printer Tiled (21.59 × 27.94 cm)",
        width_cm=21.59,
        height_cm=27.94,
        is_roll=False,
        is_tiled=True,
        default_margin_cm=1.2,
    ),
}


ROTATION_MODES: Dict[str, List[float]] = {
    "grainline_locked": [0.0, 180.0],
    "cardinal_90": [0.0, 90.0, 180.0, 270.0],
    "free_angle": [float(a) for a in range(0, 360, 15)],
}


@dataclass
class PlacedPiece:
    """A pattern piece transformed (rotated & translated) into print-layout space (cm)."""

    source_piece: ResolvedPatternPiece
    instance_index: int
    rotation_deg: float
    translation_x: float
    translation_y: float
    boundary_polygon: List[Point2D]
    seam_allowance_polygon: List[Point2D]
    internal_lines: List[InternalLine]
    grainline: Optional[Grainline]
    notches: List[NotchMark]
    bounding_box: BoundingBox
    area_cm2: float

    @property
    def display_label(self) -> str:
        if self.source_piece.cut_count > 1:
            return f"{self.source_piece.name} ({self.instance_index + 1}/{self.source_piece.cut_count})"
        return self.source_piece.name


@dataclass
class TilePage:
    """A single page/sheet in the generated print layout."""

    page_number: int
    row: int
    col: int
    grid_code: str  # e.g. "R1C1 (A1)"
    paper_width_cm: float
    paper_height_cm: float
    margin_cm: float
    # Printable window in layout coordinates (cm)
    clip_min_x: float
    clip_min_y: float
    clip_max_x: float
    clip_max_y: float
    has_content: bool = True

    @property
    def printable_width_cm(self) -> float:
        return self.clip_max_x - self.clip_min_x

    @property
    def printable_height_cm(self) -> float:
        return self.clip_max_y - self.clip_min_y

    @property
    def alignment_corners_layout_cm(self) -> List[Point2D]:
        """Four corner crosshair/diamond centers in layout space."""
        return [
            Point2D(self.clip_min_x, self.clip_min_y, "TL", "Top-Left"),
            Point2D(self.clip_max_x, self.clip_min_y, "TR", "Top-Right"),
            Point2D(self.clip_max_x, self.clip_max_y, "BR", "Bottom-Right"),
            Point2D(self.clip_min_x, self.clip_max_y, "BL", "Bottom-Left"),
        ]


@dataclass
class LayoutResult:
    """Complete output of the Print Optimization & Layout Engine."""

    paper_format: PaperFormatSpec
    rotation_mode: str
    margin_cm: float
    piece_spacing_cm: float
    placed_pieces: List[PlacedPiece]
    pages: List[TilePage]
    grid_rows: int
    grid_cols: int
    # Overall layout bounds
    used_width_cm: float
    used_height_cm: float
    # Area & Waste Metrics
    pattern_area_cm2: float
    total_paper_area_cm2: float
    waste_area_cm2: float
    waste_percentage: float
    utilization_percentage: float

    @property
    def active_page_count(self) -> int:
        return len([p for p in self.pages if p.has_content])

    @property
    def total_grid_pages(self) -> int:
        return len(self.pages)


class PrintLayoutEngine:
    """
    Optimizes 2D pattern piece placement for minimum paper waste and builds
    large-format or tiled home-printer sheet maps.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def transform_piece(
        piece: ResolvedPatternPiece,
        rotation_deg: float,
        target_min_x: float = 0.0,
        target_min_y: float = 0.0,
        instance_index: int = 0,
    ) -> PlacedPiece:
        """
        Rotate `piece` by `rotation_deg` around its centroid and translate so its
        outer bounding box top-left sits at `(target_min_x, target_min_y)`.
        """
        origin = piece.centroid

        rot_boundary = [pt.rotated(rotation_deg, origin) for pt in piece.boundary_polygon]
        rot_sa = [pt.rotated(rotation_deg, origin) for pt in piece.seam_allowance_polygon]

        outer_poly = rot_sa if (piece.seam_allowance_cm > 1e-6 and len(rot_sa) >= 3) else rot_boundary
        bbox = polygon_bounding_box(outer_poly)

        dx = target_min_x - bbox.min_x
        dy = target_min_y - bbox.min_y

        final_boundary = [pt.translated(dx, dy) for pt in rot_boundary]
        final_sa = [pt.translated(dx, dy) for pt in rot_sa]

        final_internals: List[InternalLine] = []
        for il in piece.internal_lines:
            final_internals.append(
                InternalLine(
                    id=il.id,
                    label=il.label,
                    line_type=il.line_type,
                    points=[pt.rotated(rotation_deg, origin).translated(dx, dy) for pt in il.points],
                )
            )

        final_grain: Optional[Grainline] = None
        if piece.grainline:
            final_grain = Grainline(
                start=piece.grainline.start.rotated(rotation_deg, origin).translated(dx, dy),
                end=piece.grainline.end.rotated(rotation_deg, origin).translated(dx, dy),
                label=piece.grainline.label,
            )

        final_notches: List[NotchMark] = []
        for n in piece.notches:
            final_notches.append(
                NotchMark(
                    id=n.id,
                    anchor=n.anchor.rotated(rotation_deg, origin).translated(dx, dy),
                    ticks=[
                        (
                            t0.rotated(rotation_deg, origin).translated(dx, dy),
                            t1.rotated(rotation_deg, origin).translated(dx, dy),
                        )
                        for (t0, t1) in n.ticks
                    ],
                    count=n.count,
                )
            )

        final_outer = final_sa if (piece.seam_allowance_cm > 1e-6 and len(final_sa) >= 3) else final_boundary
        final_bbox = polygon_bounding_box(final_outer)

        return PlacedPiece(
            source_piece=piece,
            instance_index=instance_index,
            rotation_deg=rotation_deg,
            translation_x=dx,
            translation_y=dy,
            boundary_polygon=final_boundary,
            seam_allowance_polygon=final_sa,
            internal_lines=final_internals,
            grainline=final_grain,
            notches=final_notches,
            bounding_box=final_bbox,
            area_cm2=piece.cut_area_cm2,
        )

    def optimize_layout(
        self,
        draft: DraftedBlockResult,
        format_id: str = "A4",
        rotation_mode: str = "cardinal_90",
        margin_cm: Optional[float] = None,
        piece_spacing_cm: float = 1.0,
        expand_cut_count: bool = False,
        skip_empty_tiles: bool = True,
    ) -> LayoutResult:
        """
        Pack pattern pieces to minimize paper waste for the chosen paper format,
        then generate large-format sheets or tiled home-printer pages.
        """
        if format_id not in PAPER_FORMATS:
            raise ValueError(f"Unknown paper format '{format_id}'. Options: {list(PAPER_FORMATS)}")

        fmt = PAPER_FORMATS[format_id]
        margin = float(margin_cm if margin_cm is not None else fmt.default_margin_cm)
        candidate_angles = ROTATION_MODES.get(rotation_mode, ROTATION_MODES["cardinal_90"])

        # Collect piece instances to pack
        instances: List[Tuple[ResolvedPatternPiece, int]] = []
        for piece in draft.pieces:
            copies = max(1, piece.cut_count) if expand_cut_count else 1
            for idx in range(copies):
                instances.append((piece, idx))

        # Determine target container width for packing
        if fmt.is_roll or not fmt.is_tiled:
            # For A0 or 36" roll, pack within the usable sheet/roll width
            max_bin_width = max(20.0, fmt.width_cm - 2.0 * margin)
        else:
            # For tiled formats (A4 / US Letter), test multiple grid column widths (1..5 cols)
            # and pick the layout that yields the minimum total paper area (lowest waste %)!
            tile_w = max(5.0, fmt.width_cm - 2.0 * margin)
            best_tiled_result: Optional[LayoutResult] = None
            for cols_try in range(1, 6):
                candidate_width = cols_try * tile_w
                res = self._pack_and_tile_for_width(
                    instances=instances,
                    fmt=fmt,
                    container_width_cm=candidate_width,
                    candidate_angles=candidate_angles,
                    rotation_mode=rotation_mode,
                    margin_cm=margin,
                    piece_spacing_cm=piece_spacing_cm,
                    skip_empty_tiles=skip_empty_tiles,
                )
                if best_tiled_result is None or (
                    res.total_paper_area_cm2 < best_tiled_result.total_paper_area_cm2 - 1e-3
                    or (
                        abs(res.total_paper_area_cm2 - best_tiled_result.total_paper_area_cm2) <= 1e-3
                        and res.used_width_cm * res.used_height_cm
                        < best_tiled_result.used_width_cm * best_tiled_result.used_height_cm
                    )
                ):
                    best_tiled_result = res
            assert best_tiled_result is not None
            return best_tiled_result

        return self._pack_and_tile_for_width(
            instances=instances,
            fmt=fmt,
            container_width_cm=max_bin_width,
            candidate_angles=candidate_angles,
            rotation_mode=rotation_mode,
            margin_cm=margin,
            piece_spacing_cm=piece_spacing_cm,
            skip_empty_tiles=skip_empty_tiles,
        )

    def _pack_and_tile_for_width(
        self,
        instances: Sequence[Tuple[ResolvedPatternPiece, int]],
        fmt: PaperFormatSpec,
        container_width_cm: float,
        candidate_angles: Sequence[float],
        rotation_mode: str,
        margin_cm: float,
        piece_spacing_cm: float,
        skip_empty_tiles: bool,
    ) -> LayoutResult:
        """
        Pack pieces into a strip of width `container_width_cm` using bottom-left skyline
        placement with orientation optimization, then build sheet/tile pages.
        """
        # 1. For each piece, evaluate candidate rotations and sort pieces largest-first
        piece_variants: List[List[PlacedPiece]] = []
        for piece, idx in instances:
            variants: List[PlacedPiece] = []
            for ang in candidate_angles:
                placed = self.transform_piece(piece, ang, 0.0, 0.0, instance_index=idx)
                variants.append(placed)
            # Sort variants by smallest bounding-box area, then narrowest width
            variants.sort(key=lambda v: (v.bounding_box.area, v.bounding_box.height, v.bounding_box.width))
            piece_variants.append(variants)

        # Sort items largest area first
        piece_variants.sort(key=lambda vars_list: vars_list[0].area_cm2, reverse=True)

        placed_pieces: List[PlacedPiece] = []
        occupied_boxes: List[BoundingBox] = []

        for variants in piece_variants:
            best_placement: Optional[PlacedPiece] = None
            best_score: Tuple[float, float, float] = (float("inf"), float("inf"), float("inf"))

            # Candidate anchor X and Y coordinates from existing placed boxes
            cand_xs = [0.0]
            cand_ys = [0.0]
            for box in occupied_boxes:
                cand_xs.append(box.max_x + piece_spacing_cm)
                cand_ys.append(box.max_y + piece_spacing_cm)
            cand_xs = sorted(set(cand_xs))
            cand_ys = sorted(set(cand_ys))

            # Evaluate top orientations (up to 6 best bounding variants for speed + accuracy)
            for var in variants[:6]:
                pw = var.bounding_box.width
                ph = var.bounding_box.height

                for cy in cand_ys:
                    for cx in cand_xs:
                        if cx > 0 and cx + pw > container_width_cm + 1e-5:
                            continue
                        trial_box = BoundingBox(cx, cy, cx + pw, cy + ph)
                        if self._overlaps_any(trial_box, occupied_boxes, piece_spacing_cm):
                            continue

                        # Score: minimize overall max_y (strip height), then max_x, then y+x
                        new_max_y = max([b.max_y for b in occupied_boxes] + [trial_box.max_y])
                        new_max_x = max([b.max_x for b in occupied_boxes] + [trial_box.max_x])
                        score = (new_max_y, new_max_x, cy + cx * 0.25)
                        if score < best_score:
                            best_score = score
                            best_placement = self.transform_piece(
                                var.source_piece,
                                var.rotation_deg,
                                target_min_x=cx,
                                target_min_y=cy,
                                instance_index=var.instance_index,
                            )

            if best_placement is None:
                # Fallback: stack below current bottom
                var = variants[0]
                bottom_y = (
                    max(b.max_y for b in occupied_boxes) + piece_spacing_cm
                    if occupied_boxes
                    else 0.0
                )
                best_placement = self.transform_piece(
                    var.source_piece,
                    var.rotation_deg,
                    target_min_x=0.0,
                    target_min_y=bottom_y,
                    instance_index=var.instance_index,
                )

            placed_pieces.append(best_placement)
            occupied_boxes.append(best_placement.bounding_box)

        used_width = max((b.max_x for b in occupied_boxes), default=0.0)
        used_height = max((b.max_y for b in occupied_boxes), default=0.0)
        pattern_area = sum(p.area_cm2 for p in placed_pieces)

        # 2. Generate Pages / Tiles & Compute Total Paper Area + Waste %
        pages: List[TilePage] = []
        if fmt.is_roll:
            # 36-inch roll: width is fixed (91.44cm), length is dynamic (used_height + 2*margin)
            roll_cut_length = max(10.0, used_height + 2.0 * margin_cm)
            # If pieces exceeded single roll width, multiple roll drops would be needed
            usable_w = max(10.0, fmt.width_cm - 2.0 * margin_cm)
            cols = max(1, math.ceil(used_width / usable_w))
            rows = 1
            for c in range(cols):
                pages.append(
                    TilePage(
                        page_number=c + 1,
                        row=0,
                        col=c,
                        grid_code=f"ROLL-{c + 1}",
                        paper_width_cm=fmt.width_cm,
                        paper_height_cm=roll_cut_length,
                        margin_cm=margin_cm,
                        clip_min_x=c * usable_w,
                        clip_min_y=0.0,
                        clip_max_x=(c + 1) * usable_w,
                        clip_max_y=used_height,
                        has_content=True,
                    )
                )
            total_paper_area = cols * fmt.width_cm * roll_cut_length
        else:
            # Fixed sheet size (A0, A4, US Letter)
            usable_w = max(5.0, fmt.width_cm - 2.0 * margin_cm)
            usable_h = max(5.0, fmt.height_cm - 2.0 * margin_cm)
            cols = max(1, math.ceil(max(used_width, 1.0) / usable_w))
            rows = max(1, math.ceil(max(used_height, 1.0) / usable_h))

            page_num = 1
            for r in range(rows):
                for c in range(cols):
                    c_min_x = c * usable_w
                    c_min_y = r * usable_h
                    c_max_x = (c + 1) * usable_w
                    c_max_y = (r + 1) * usable_h
                    tile_box = BoundingBox(c_min_x, c_min_y, c_max_x, c_max_y)
                    has_content = self._tile_has_piece_content(tile_box, placed_pieces)
                    # Always keep Page 1 (R1C1) for the calibration scale square
                    if r == 0 and c == 0:
                        has_content = True

                    col_letter = chr(ord("A") + (c % 26))
                    grid_code = f"R{r + 1}C{c + 1} ({col_letter}{r + 1})"
                    pages.append(
                        TilePage(
                            page_number=page_num,
                            row=r,
                            col=c,
                            grid_code=grid_code,
                            paper_width_cm=fmt.width_cm,
                            paper_height_cm=fmt.height_cm,
                            margin_cm=margin_cm,
                            clip_min_x=c_min_x,
                            clip_min_y=c_min_y,
                            clip_max_x=c_max_x,
                            clip_max_y=c_max_y,
                            has_content=has_content or not skip_empty_tiles,
                        )
                    )
                    if has_content or not skip_empty_tiles:
                        page_num += 1

            active_sheets = max(1, len([p for p in pages if p.has_content]))
            total_paper_area = active_sheets * fmt.width_cm * fmt.height_cm

        waste_area = max(0.0, total_paper_area - pattern_area)
        waste_pct = (waste_area / total_paper_area * 100.0) if total_paper_area > 0 else 0.0
        util_pct = max(0.0, 100.0 - waste_pct)

        return LayoutResult(
            paper_format=fmt,
            rotation_mode=rotation_mode,
            margin_cm=margin_cm,
            piece_spacing_cm=piece_spacing_cm,
            placed_pieces=placed_pieces,
            pages=pages,
            grid_rows=rows,
            grid_cols=cols,
            used_width_cm=used_width,
            used_height_cm=used_height,
            pattern_area_cm2=pattern_area,
            total_paper_area_cm2=total_paper_area,
            waste_area_cm2=waste_area,
            waste_percentage=waste_pct,
            utilization_percentage=util_pct,
        )

    def compare_all_formats(
        self,
        draft: DraftedBlockResult,
        rotation_mode: str = "cardinal_90",
        margin_cm: Optional[float] = None,
        piece_spacing_cm: float = 1.0,
        expand_cut_count: bool = False,
    ) -> Dict[str, LayoutResult]:
        """
        Run the layout optimizer across all 4 print formats (A0, 36" Roll, A4, US Letter)
        so the user can compare total paper required and waste percentage side-by-side.
        """
        results: Dict[str, LayoutResult] = {}
        for fmt_id in PAPER_FORMATS:
            results[fmt_id] = self.optimize_layout(
                draft=draft,
                format_id=fmt_id,
                rotation_mode=rotation_mode,
                margin_cm=margin_cm,
                piece_spacing_cm=piece_spacing_cm,
                expand_cut_count=expand_cut_count,
            )
        return results

    @staticmethod
    def _overlaps_any(
        candidate: BoundingBox,
        occupied: Sequence[BoundingBox],
        spacing: float,
    ) -> bool:
        half_gap = spacing * 0.5 - 1e-5
        for box in occupied:
            if not (
                candidate.max_x + half_gap <= box.min_x
                or candidate.min_x - half_gap >= box.max_x
                or candidate.max_y + half_gap <= box.min_y
                or candidate.min_y - half_gap >= box.max_y
            ):
                return True
        return False

    @staticmethod
    def _tile_has_piece_content(tile: BoundingBox, pieces: Sequence[PlacedPiece]) -> bool:
        for p in pieces:
            b = p.bounding_box
            if not (
                b.max_x < tile.min_x
                or b.min_x > tile.max_x
                or b.max_y < tile.min_y
                or b.min_y > tile.max_y
            ):
                return True
        return False
