"""
Interactive 2D Vector CAD Viewport (PySide6 QGraphicsView / QGraphicsScene).

Supports dynamic Light Mode and Dark Mode palettes across two live views:
1. "drafting": Parametric Construction Grid + Reference Image Underlay (Option 5) +
   Layer 1 Construction Points/Curves + Layer 2 Pattern Pieces + Click-to-Trace selection (Option 1)
2. "layout": Print Optimization & Tiling Preview showing A0 / 36" Roll / A4 / US Letter sheets,
   margin frames, corner crosshairs + diamonds, scale calibration square, and nested pattern pieces.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

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
    polygon_centroid,
)
from src.layout.nesting_engine import LayoutResult, PlacedPiece

# Scale factor: 1 cm in pattern coordinates = 12.0 scene pixels at 1.0x zoom
SCENE_PX_PER_CM = 12.0


class ConstructionPointItem(QGraphicsEllipseItem):
    """Interactive construction point node that highlights on hover and reports its formula."""

    def __init__(
        self,
        pt: Point2D,
        radius_px: float = 4.6,
        theme: str = "light",
        is_highlighted: bool = False,
    ) -> None:
        cx = pt.x * SCENE_PX_PER_CM
        cy = pt.y * SCENE_PX_PER_CM
        r = radius_px * (1.35 if is_highlighted else 1.0)
        super().__init__(cx - r, cy - r, r * 2.0, r * 2.0)
        self.point_data = pt
        self.theme = theme
        self.setAcceptHoverEvents(True)
        self.setZValue(35 if is_highlighted else 30)

        pen_color = QColor("#0f172a")
        if is_highlighted:
            self.fill_color = QColor("#10b981")
        else:
            self.fill_color = QColor("#0284c7") if theme == "light" else QColor("#38bdf8")
        self.hover_color = QColor("#f59e0b")

        pen = QPen(pen_color, 1.4 if is_highlighted else 1.2)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(self.fill_color))

        tooltip = (
            f"<b>Point {pt.id}</b> — {pt.label}<br/>"
            f"Coords: <code>({pt.x:.2f} cm, {pt.y:.2f} cm)</code><br/>"
            f"Formula: <code>{pt.formula_summary}</code><br/>"
            f"<i>Click to select point in Builder / Tracer</i>"
        )
        self.setToolTip(tooltip)

    def hoverEnterEvent(self, event) -> None:  # type: ignore[override]
        self.setBrush(QBrush(self.hover_color))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # type: ignore[override]
        self.setBrush(QBrush(self.fill_color))
        super().hoverLeaveEvent(event)


class PatternCanvasView(QGraphicsView):
    """
    Hardware-accelerated 2D Vector CAD Viewport with zoom, pan, grid rendering,
    live cursor coordinate inspection, layer visibility toggles, Reference Image underlay,
    Click-to-Trace point selection, and dynamic Light/Dark themes.
    """

    cursorMovedCm = Signal(float, float, str)  # (x_cm, y_cm, nearest_point_summary)
    pointClicked = Signal(str)                 # Emitted when a construction point is clicked
    canvasClickedCm = Signal(float, float)     # Emitted when clicking on the canvas in tool/trace mode

    def __init__(self, parent=None, theme: str = "light") -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setMouseTracking(True)

        self.theme: str = theme
        self._apply_background_brush()

        self.view_mode: str = "drafting"  # "drafting" or "layout"
        # Interactive tool mode: "pan", "select_point", "calibrate", "set_origin", "trace_point"
        self.interaction_mode: str = "pan"

        self.layer_visibility: Dict[str, bool] = {
            "construction": True,
            "points": True,
            "seam_line": True,
            "seam_allowance": True,
            "internal_darts": True,
            "grainline": True,
            "notches": True,
            "labels": True,
        }

        self._current_draft: Optional[DraftedBlockResult] = None
        self._current_layout: Optional[LayoutResult] = None
        self._highlighted_points: List[str] = []

        # Reference Image Underlay state
        self._ref_pixmap: Optional[QPixmap] = None
        self._ref_image_path: Optional[Path] = None
        self._ref_opacity: float = 0.55
        self._ref_visible: bool = True
        self._ref_cm_per_image_px: float = 0.05  # Default: 20 image px = 1 cm
        self._ref_origin_x_cm: float = 0.0       # Top-left of image in cm coords
        self._ref_origin_y_cm: float = 0.0
        self._calibration_markers_cm: List[Point2D] = []
        self._mouse_press_pos = None

    # -----------------------------------------------------------------------
    # Theme, Layer & Interaction Mode Configuration
    # -----------------------------------------------------------------------

    def set_theme(self, theme_name: str) -> None:
        """Switch between 'light' and 'dark' visual canvas theme."""
        if self.theme != theme_name:
            self.theme = theme_name
            self._apply_background_brush()
            self.refresh_scene()

    def _apply_background_brush(self) -> None:
        if self.theme == "light":
            self.setBackgroundBrush(QBrush(QColor("#f8fafc")))
        else:
            self.setBackgroundBrush(QBrush(QColor("#0b1120")))

    def set_interaction_mode(self, mode: str) -> None:
        """
        Set interaction mode:
        - 'pan': Standard scroll-hand drag + clicking a point emits `pointClicked`
        - 'calibrate': Crosshair cursor for clicking 2 scale calibration points on Reference Image
        - 'set_origin': Crosshair cursor for clicking where (0,0) sits on Reference Image
        - 'trace_point': Crosshair cursor for clicking landmarks on Reference Image to create points
        """
        self.interaction_mode = mode
        if mode == "pan":
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.unsetCursor()
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)

    def set_highlighted_points(self, point_ids: Sequence[str]) -> None:
        self._highlighted_points = list(point_ids)
        self.refresh_scene()

    def set_layer_visible(self, layer_key: str, visible: bool) -> None:
        self.layer_visibility[layer_key] = visible
        self.refresh_scene()

    def set_view_mode(self, mode: str) -> None:
        self.view_mode = mode
        self.refresh_scene()
        self.fit_content_in_view()

    # -----------------------------------------------------------------------
    # Option 5: Reference Image Underlay Controls
    # -----------------------------------------------------------------------

    def load_reference_image(self, file_path: str | Path) -> bool:
        path = Path(file_path)
        pix = QPixmap(str(path))
        if pix.isNull():
            return False
        self._ref_pixmap = pix
        self._ref_image_path = path
        self._ref_visible = True
        # Default scale: fit width to roughly 50 cm on the grid initially
        w_px = max(1, pix.width())
        self._ref_cm_per_image_px = 50.0 / w_px
        self._ref_origin_x_cm = 0.0
        self._ref_origin_y_cm = 0.0
        self._calibration_markers_cm.clear()
        self.refresh_scene()
        self.fit_content_in_view()
        return True

    def clear_reference_image(self) -> None:
        self._ref_pixmap = None
        self._ref_image_path = None
        self._calibration_markers_cm.clear()
        self.refresh_scene()

    def set_reference_opacity(self, opacity: float) -> None:
        self._ref_opacity = max(0.05, min(1.0, float(opacity)))
        self.refresh_scene()

    def set_reference_visible(self, visible: bool) -> None:
        self._ref_visible = bool(visible)
        self.refresh_scene()

    def set_calibration_markers(self, pts: Sequence[Point2D]) -> None:
        self._calibration_markers_cm = list(pts)
        self.refresh_scene()

    def calibrate_reference_scale(
        self,
        p1_cm: Point2D,
        p2_cm: Point2D,
        real_distance_cm: float,
    ) -> None:
        """
        Rescale the reference image so the distance between `p1_cm` and `p2_cm`
        becomes `real_distance_cm`.
        """
        if self._ref_pixmap is None or real_distance_cm <= 1e-4:
            return
        measured_cm = p1_cm.distance_to(p2_cm)
        if measured_cm <= 1e-6:
            return
        ratio = real_distance_cm / measured_cm
        # Keep p1_cm anchored at its current position while scaling
        self._ref_cm_per_image_px *= ratio
        self._ref_origin_x_cm = p1_cm.x - (p1_cm.x - self._ref_origin_x_cm) * ratio
        self._ref_origin_y_cm = p1_cm.y - (p1_cm.y - self._ref_origin_y_cm) * ratio
        self._calibration_markers_cm.clear()
        self.refresh_scene()

    def align_reference_origin_to_click(self, clicked_cm: Point2D) -> None:
        """Shift the reference image so `clicked_cm` on the image moves to `(0, 0)`."""
        if self._ref_pixmap is None:
            return
        self._ref_origin_x_cm -= clicked_cm.x
        self._ref_origin_y_cm -= clicked_cm.y
        self.refresh_scene()

    # -----------------------------------------------------------------------
    # Data & Viewport Updates
    # -----------------------------------------------------------------------

    def update_data(
        self,
        draft: DraftedBlockResult,
        layout: Optional[LayoutResult] = None,
        auto_fit: bool = False,
    ) -> None:
        self._current_draft = draft
        if layout is not None:
            self._current_layout = layout
        self.refresh_scene()
        if auto_fit:
            self.fit_content_in_view()

    def fit_content_in_view(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if rect.isNull() or rect.width() < 1.0 or rect.height() < 1.0:
            return
        padded = rect.adjusted(-60, -60, 60, 60)
        self.fitInView(padded, Qt.AspectRatioMode.KeepAspectRatio)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)

        minor_step = SCENE_PX_PER_CM
        major_step = SCENE_PX_PER_CM * 10.0

        left = math.floor(rect.left() / minor_step) * minor_step
        top = math.floor(rect.top() / minor_step) * minor_step

        is_light = self.theme == "light"

        # 1 cm minor grid
        minor_color = QColor(226, 232, 240, 220) if is_light else QColor(30, 41, 59, 130)
        minor_pen = QPen(minor_color, 1.0)
        minor_pen.setCosmetic(True)
        painter.setPen(minor_pen)

        x = left
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += minor_step

        y = top
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += minor_step

        # 10 cm major CAD grid
        major_left = math.floor(rect.left() / major_step) * major_step
        major_top = math.floor(rect.top() / major_step) * major_step

        major_color = QColor(203, 213, 225, 240) if is_light else QColor(51, 65, 85, 200)
        major_pen = QPen(major_color, 1.2)
        major_pen.setCosmetic(True)
        painter.setPen(major_pen)

        x = major_left
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += major_step

        y = major_top
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += major_step

        # Origin (0,0) axes
        axis_color = QColor(2, 132, 199, 160) if is_light else QColor(56, 189, 248, 120)
        axis_pen = QPen(axis_color, 1.5)
        axis_pen.setCosmetic(True)
        painter.setPen(axis_pen)
        painter.drawLine(QPointF(0, rect.top()), QPointF(0, rect.bottom()))
        painter.drawLine(QPointF(rect.left(), 0), QPointF(rect.right(), 0))

    def wheelEvent(self, event: QWheelEvent) -> None:
        zoom_in_factor = 1.16
        zoom_out_factor = 1.0 / zoom_in_factor
        factor = zoom_in_factor if event.angleDelta().y() > 0 else zoom_out_factor
        self.scale(factor, factor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_press_pos = event.position()
            if self.interaction_mode != "pan":
                scene_pt = self.mapToScene(event.position().toPoint())
                x_cm = scene_pt.x() / SCENE_PX_PER_CM
                y_cm = scene_pt.y() / SCENE_PX_PER_CM
                self.canvasClickedCm.emit(x_cm, y_cm)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.interaction_mode == "pan"
            and self._mouse_press_pos is not None
        ):
            delta = event.position() - self._mouse_press_pos
            # If user clicked without dragging, check if they clicked on a construction point
            if math.hypot(delta.x(), delta.y()) < 5.0 and self._current_draft and self.view_mode == "drafting":
                scene_pt = self.mapToScene(event.position().toPoint())
                x_cm = scene_pt.x() / SCENE_PX_PER_CM
                y_cm = scene_pt.y() / SCENE_PX_PER_CM
                best_id: Optional[str] = None
                best_dist = 1.6  # cm click snap radius
                for pid, pt in self._current_draft.points.items():
                    d = math.hypot(pt.x - x_cm, pt.y - y_cm)
                    if d < best_dist:
                        best_dist = d
                        best_id = pid
                if best_id is not None:
                    self.pointClicked.emit(best_id)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        scene_pt = self.mapToScene(event.position().toPoint())
        x_cm = scene_pt.x() / SCENE_PX_PER_CM
        y_cm = scene_pt.y() / SCENE_PX_PER_CM

        nearest_info = ""
        if self._current_draft and self.view_mode == "drafting":
            best_dist = 1.8  # cm snap radius
            for pt in self._current_draft.points.values():
                d = math.hypot(pt.x - x_cm, pt.y - y_cm)
                if d < best_dist:
                    best_dist = d
                    nearest_info = f"Point {pt.id} ({pt.label}): ({pt.x:.2f}, {pt.y:.2f}) cm | {pt.formula_summary}"

        self.cursorMovedCm.emit(x_cm, y_cm, nearest_info)
        super().mouseMoveEvent(event)

    # -----------------------------------------------------------------------
    # Scene Rendering
    # -----------------------------------------------------------------------

    def refresh_scene(self) -> None:
        self._scene.clear()

        if self.view_mode == "drafting":
            self._render_reference_image_underlay()

        if self._current_draft is None:
            return

        if self.view_mode == "layout" and self._current_layout is not None:
            self._render_layout_scene(self._current_draft, self._current_layout)
        else:
            self._render_drafting_scene(self._current_draft)

    def _render_reference_image_underlay(self) -> None:
        """Render the calibrated Reference Image (Option 5) below construction geometry."""
        if self._ref_pixmap is None or not self._ref_visible:
            return

        pix_item = QGraphicsPixmapItem(self._ref_pixmap)
        pix_item.setOpacity(self._ref_opacity)
        scale_factor = self._ref_cm_per_image_px * SCENE_PX_PER_CM
        pix_item.setScale(scale_factor)
        pix_item.setPos(
            self._ref_origin_x_cm * SCENE_PX_PER_CM,
            self._ref_origin_y_cm * SCENE_PX_PER_CM,
        )
        pix_item.setZValue(-10)
        self._scene.addItem(pix_item)

        # Render any active calibration markers
        for idx, c_pt in enumerate(self._calibration_markers_cm, start=1):
            cx = c_pt.x * SCENE_PX_PER_CM
            cy = c_pt.y * SCENE_PX_PER_CM
            marker = QGraphicsEllipseItem(cx - 6, cy - 6, 12, 12)
            pen = QPen(QColor("#e11d48"), 2.0)
            pen.setCosmetic(True)
            marker.setPen(pen)
            marker.setBrush(QBrush(QColor(225, 29, 72, 90)))
            marker.setZValue(40)
            self._scene.addItem(marker)

            lbl = QGraphicsSimpleTextItem(f"Calib P{idx} ({c_pt.x:.1f}, {c_pt.y:.1f})")
            lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            lbl.setBrush(QBrush(QColor("#e11d48")))
            lbl.setPos(cx + 8, cy - 10)
            lbl.setFlag(lbl.GraphicsItemFlag.ItemIgnoresTransformations, True)
            lbl.setZValue(41)
            self._scene.addItem(lbl)

    def _render_drafting_scene(self, draft: DraftedBlockResult) -> None:
        s = SCENE_PX_PER_CM
        is_light = self.theme == "light"

        # 1. Layer 2 Pattern Pieces
        if is_light:
            piece_colors = [
                QColor(14, 165, 233, 24),
                QColor(16, 185, 129, 24),
                QColor(168, 85, 247, 24),
                QColor(245, 158, 11, 24),
            ]
        else:
            piece_colors = [
                QColor(14, 165, 233, 32),
                QColor(16, 185, 129, 32),
                QColor(168, 85, 247, 32),
                QColor(245, 158, 11, 32),
            ]

        for idx, piece in enumerate(draft.pieces):
            fill_color = piece_colors[idx % len(piece_colors)]
            self._render_draft_piece(piece, fill_color)

        # 2. Layer 1 Construction Curves & Guidelines
        if self.layer_visibility.get("construction", True):
            curve_color = QColor("#64748b") if is_light else QColor("#94a3b8")
            const_pen = QPen(curve_color, 1.3, Qt.PenStyle.DashLine)
            const_pen.setCosmetic(True)
            for curve in draft.construction_curves.values():
                path = self._curve_to_qpath(curve)
                item = QGraphicsPathItem(path)
                item.setPen(const_pen)
                item.setZValue(12)
                self._scene.addItem(item)

        # 3. Layer 1 Construction Points & Point Labels
        if self.layer_visibility.get("points", True):
            lbl_font = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
            label_color = QColor("#0f172a") if is_light else QColor("#e2e8f0")
            highlight_set = set(self._highlighted_points)
            for pid, pt in draft.points.items():
                is_hi = pid in highlight_set
                node = ConstructionPointItem(pt, theme=self.theme, is_highlighted=is_hi)
                self._scene.addItem(node)

                if self.layer_visibility.get("labels", True):
                    txt = QGraphicsSimpleTextItem(pid)
                    txt.setFont(lbl_font)
                    txt.setBrush(QBrush(QColor("#059669") if is_hi else label_color))
                    txt.setPos(pt.x * s + 5.0, pt.y * s - 14.0)
                    txt.setFlag(txt.GraphicsItemFlag.ItemIgnoresTransformations, True)
                    txt.setZValue(32)
                    self._scene.addItem(txt)

    def _render_draft_piece(self, piece: ResolvedPatternPiece, fill_color: QColor) -> None:
        s = SCENE_PX_PER_CM
        is_light = self.theme == "light"

        # Seam allowance contour (dashed rose/crimson)
        if (
            self.layer_visibility.get("seam_allowance", True)
            and piece.seam_allowance_cm > 1e-6
            and len(piece.seam_allowance_polygon) >= 3
        ):
            sa_poly = QPolygonF([QPointF(p.x * s, p.y * s) for p in piece.seam_allowance_polygon])
            sa_item = QGraphicsPolygonItem(sa_poly)
            sa_color = QColor("#e11d48") if is_light else QColor("#f43f5e")
            sa_pen = QPen(sa_color, 1.5, Qt.PenStyle.DashLine)
            sa_pen.setCosmetic(True)
            sa_item.setPen(sa_pen)
            sa_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            sa_item.setZValue(14)
            self._scene.addItem(sa_item)

        # Stitch / Pattern Boundary (exact cubic Beziers + lines)
        if self.layer_visibility.get("seam_line", True) and piece.boundary_segments:
            b_path = QPainterPath()
            for i, seg in enumerate(piece.boundary_segments):
                seg_path = self._curve_to_qpath(seg)
                if i == 0:
                    b_path.addPath(seg_path)
                else:
                    b_path.connectPath(seg_path)
            b_path.closeSubpath()

            b_item = QGraphicsPathItem(b_path)
            boundary_pen_color = QColor("#0f172a") if is_light else QColor("#f8fafc")
            b_pen = QPen(boundary_pen_color, 2.2)
            b_pen.setCosmetic(True)
            b_item.setPen(b_pen)
            b_item.setBrush(QBrush(fill_color))
            b_item.setZValue(15)
            self._scene.addItem(b_item)

        # Internal lines & Darts
        if self.layer_visibility.get("internal_darts", True):
            for il in piece.internal_lines:
                if len(il.points) < 2:
                    continue
                il_path = QPainterPath(QPointF(il.points[0].x * s, il.points[0].y * s))
                for p in il.points[1:]:
                    il_path.lineTo(p.x * s, p.y * s)
                il_item = QGraphicsPathItem(il_path)
                if il.line_type == "dart":
                    pen_color = QColor("#7c3aed") if is_light else QColor("#c084fc")
                    pen = QPen(pen_color, 1.7)
                else:
                    pen_color = QColor("#4f46e5") if is_light else QColor("#818cf8")
                    pen = QPen(pen_color, 1.2, Qt.PenStyle.DotLine)
                pen.setCosmetic(True)
                il_item.setPen(pen)
                il_item.setZValue(18)
                self._scene.addItem(il_item)

        # Notches
        if self.layer_visibility.get("notches", True):
            notch_color = QColor("#d97706") if is_light else QColor("#facc15")
            notch_pen = QPen(notch_color, 2.0)
            notch_pen.setCosmetic(True)
            for notch in piece.notches:
                for t0, t1 in notch.ticks:
                    n_path = QPainterPath(QPointF(t0.x * s, t0.y * s))
                    n_path.lineTo(t1.x * s, t1.y * s)
                    n_item = QGraphicsPathItem(n_path)
                    n_item.setPen(notch_pen)
                    n_item.setZValue(20)
                    self._scene.addItem(n_item)

        # Grainline
        if self.layer_visibility.get("grainline", True) and piece.grainline:
            self._draw_grainline(piece.grainline.start, piece.grainline.end, piece.grainline.label)

        # Piece Centroid Title
        if self.layer_visibility.get("labels", True):
            c_pt = piece.centroid
            title = QGraphicsSimpleTextItem(
                f"{piece.name}\nCut {piece.cut_count}× | SA {piece.seam_allowance_cm:.1f} cm\nArea: {piece.cut_area_cm2:.1f} cm²"
            )
            title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            title_color = QColor("#0f172a") if is_light else QColor("#bae6fd")
            title.setBrush(QBrush(title_color))
            title.setPos(c_pt.x * s - 45, c_pt.y * s - 18)
            title.setFlag(title.GraphicsItemFlag.ItemIgnoresTransformations, True)
            title.setZValue(25)
            self._scene.addItem(title)

    def _render_layout_scene(self, draft: DraftedBlockResult, layout: LayoutResult) -> None:
        s = SCENE_PX_PER_CM
        is_light = self.theme == "light"

        # 1. Draw each paper tile / sheet in the layout
        for tile in layout.pages:
            paper_x = (tile.clip_min_x - tile.margin_cm) * s
            paper_y = (tile.clip_min_y - tile.margin_cm) * s
            paper_w = tile.paper_width_cm * s
            paper_h = tile.paper_height_cm * s

            sheet_rect = QGraphicsRectItem(paper_x, paper_y, paper_w, paper_h)
            if is_light:
                if tile.has_content:
                    sheet_pen = QPen(QColor("#94a3b8"), 1.5)
                    sheet_brush = QBrush(QColor("#ffffff"))
                else:
                    sheet_pen = QPen(QColor("#cbd5e1"), 1.0, Qt.PenStyle.DotLine)
                    sheet_brush = QBrush(QColor("#f1f5f9"))
            else:
                if tile.has_content:
                    sheet_pen = QPen(QColor("#475569"), 1.5)
                    sheet_brush = QBrush(QColor(15, 23, 42, 210))
                else:
                    sheet_pen = QPen(QColor("#334155"), 1.0, Qt.PenStyle.DotLine)
                    sheet_brush = QBrush(QColor(15, 23, 42, 90))

            sheet_pen.setCosmetic(True)
            sheet_rect.setPen(sheet_pen)
            sheet_rect.setBrush(sheet_brush)
            sheet_rect.setZValue(1)
            self._scene.addItem(sheet_rect)

            # Printable margin boundary inside tile
            clip_x = tile.clip_min_x * s
            clip_y = tile.clip_min_y * s
            clip_w = tile.printable_width_cm * s
            clip_h = tile.printable_height_cm * s

            margin_rect = QGraphicsRectItem(clip_x, clip_y, clip_w, clip_h)
            margin_color = (
                QColor("#0d9488" if tile.has_content else "#cbd5e1")
                if is_light
                else QColor("#0d9488" if tile.has_content else "#334155")
            )
            margin_pen = QPen(margin_color, 1.1, Qt.PenStyle.DashLine)
            margin_pen.setCosmetic(True)
            margin_rect.setPen(margin_pen)
            margin_rect.setZValue(3)
            self._scene.addItem(margin_rect)

            # Corner Alignment Crosshairs + Diamonds
            if tile.has_content:
                for corner_pt in tile.alignment_corners_layout_cm:
                    self._draw_alignment_diamond(corner_pt.x * s, corner_pt.y * s)

            # Tile Grid Code Badge
            badge = QGraphicsSimpleTextItem(
                f"{tile.grid_code}" if tile.has_content else f"{tile.grid_code} [Empty]"
            )
            badge.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            if is_light:
                badge_color = QColor("#0f766e" if tile.has_content else "#94a3b8")
            else:
                badge_color = QColor("#5eead4" if tile.has_content else "#64748b")
            badge.setBrush(QBrush(badge_color))
            badge.setPos(clip_x + 6, clip_y + 4)
            badge.setFlag(badge.GraphicsItemFlag.ItemIgnoresTransformations, True)
            badge.setZValue(25)
            self._scene.addItem(badge)

        # 2. Draw 5cm x 5cm Scale Check Square on first tile
        if layout.pages:
            first_tile = layout.pages[0]
            scale_rect = QGraphicsRectItem(
                (first_tile.clip_min_x + 0.4) * s,
                (first_tile.clip_min_y + 0.4) * s,
                5.0 * s,
                5.0 * s,
            )
            scale_pen_color = QColor("#0d9488") if is_light else QColor("#14b8a6")
            scale_fill_color = QColor(13, 148, 136, 25) if is_light else QColor(20, 184, 166, 35)
            scale_pen = QPen(scale_pen_color, 1.5)
            scale_pen.setCosmetic(True)
            scale_rect.setPen(scale_pen)
            scale_rect.setBrush(QBrush(scale_fill_color))
            scale_rect.setZValue(8)
            self._scene.addItem(scale_rect)

            sc_lbl = QGraphicsSimpleTextItem("5×5 cm\nScale Box")
            sc_lbl.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            sc_text_color = QColor("#0f766e") if is_light else QColor("#99f6e4")
            sc_lbl.setBrush(QBrush(sc_text_color))
            sc_lbl.setPos((first_tile.clip_min_x + 1.0) * s, (first_tile.clip_min_y + 1.5) * s)
            sc_lbl.setFlag(sc_lbl.GraphicsItemFlag.ItemIgnoresTransformations, True)
            sc_lbl.setZValue(26)
            self._scene.addItem(sc_lbl)

        # 3. Draw Placed Pattern Pieces
        if is_light:
            piece_colors = [
                QColor(2, 132, 199, 45),
                QColor(16, 185, 129, 45),
                QColor(168, 85, 247, 45),
                QColor(245, 158, 11, 45),
            ]
        else:
            piece_colors = [
                QColor(56, 189, 248, 55),
                QColor(52, 211, 153, 55),
                QColor(192, 132, 252, 55),
                QColor(251, 191, 36, 55),
            ]

        for idx, placed in enumerate(layout.placed_pieces):
            self._render_placed_piece(placed, piece_colors[idx % len(piece_colors)])

    def _render_placed_piece(self, placed: PlacedPiece, fill_color: QColor) -> None:
        s = SCENE_PX_PER_CM
        is_light = self.theme == "light"

        if (
            self.layer_visibility.get("seam_allowance", True)
            and placed.source_piece.seam_allowance_cm > 1e-6
            and len(placed.seam_allowance_polygon) >= 3
        ):
            sa_poly = QPolygonF([QPointF(p.x * s, p.y * s) for p in placed.seam_allowance_polygon])
            sa_item = QGraphicsPolygonItem(sa_poly)
            sa_pen_color = QColor("#e11d48") if is_light else QColor("#fb7185")
            sa_pen = QPen(sa_pen_color, 1.4, Qt.PenStyle.DashLine)
            sa_pen.setCosmetic(True)
            sa_item.setPen(sa_pen)
            sa_item.setZValue(14)
            self._scene.addItem(sa_item)

        if len(placed.boundary_polygon) >= 3:
            b_poly = QPolygonF([QPointF(p.x * s, p.y * s) for p in placed.boundary_polygon])
            b_item = QGraphicsPolygonItem(b_poly)
            b_pen_color = QColor("#0f172a") if is_light else QColor("#f8fafc")
            b_pen = QPen(b_pen_color, 2.0)
            b_pen.setCosmetic(True)
            b_item.setPen(b_pen)
            b_item.setBrush(QBrush(fill_color))
            b_item.setZValue(15)
            self._scene.addItem(b_item)

        if self.layer_visibility.get("internal_darts", True):
            for il in placed.internal_lines:
                if len(il.points) < 2:
                    continue
                il_path = QPainterPath(QPointF(il.points[0].x * s, il.points[0].y * s))
                for p in il.points[1:]:
                    il_path.lineTo(p.x * s, p.y * s)
                il_item = QGraphicsPathItem(il_path)
                il_color = QColor("#7c3aed") if is_light else QColor("#c084fc")
                pen = QPen(il_color, 1.5)
                pen.setCosmetic(True)
                il_item.setPen(pen)
                il_item.setZValue(17)
                self._scene.addItem(il_item)

        if self.layer_visibility.get("grainline", True) and placed.grainline:
            self._draw_grainline(placed.grainline.start, placed.grainline.end, placed.grainline.label)

        if self.layer_visibility.get("labels", True):
            c_pt = polygon_centroid(placed.boundary_polygon)
            lbl = QGraphicsSimpleTextItem(
                f"{placed.display_label}\nRot: {placed.rotation_deg:.0f}° | {placed.area_cm2:.0f} cm²"
            )
            lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            lbl_color = QColor("#0f172a") if is_light else QColor("#f8fafc")
            lbl.setBrush(QBrush(lbl_color))
            lbl.setPos(c_pt.x * s - 35, c_pt.y * s - 12)
            lbl.setFlag(lbl.GraphicsItemFlag.ItemIgnoresTransformations, True)
            lbl.setZValue(26)
            self._scene.addItem(lbl)

    def _draw_grainline(self, start: Point2D, end: Point2D, label: str) -> None:
        s = SCENE_PX_PER_CM
        is_light = self.theme == "light"
        path = QPainterPath(QPointF(start.x * s, start.y * s))
        path.lineTo(end.x * s, end.y * s)
        item = QGraphicsPathItem(path)
        g_color = QColor("#0d9488") if is_light else QColor("#2dd4bf")
        pen = QPen(g_color, 1.6)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setZValue(19)
        self._scene.addItem(item)

    def _draw_alignment_diamond(self, cx: float, cy: float) -> None:
        r = 0.35 * SCENE_PX_PER_CM
        is_light = self.theme == "light"
        path = QPainterPath()
        # Crosshair
        path.moveTo(cx - r * 1.3, cy)
        path.lineTo(cx + r * 1.3, cy)
        path.moveTo(cx, cy - r * 1.3)
        path.lineTo(cx, cy + r * 1.3)
        # Diamond
        path.moveTo(cx, cy - r)
        path.lineTo(cx + r, cy)
        path.lineTo(cx, cy + r)
        path.lineTo(cx - r, cy)
        path.closeSubpath()

        item = QGraphicsPathItem(path)
        d_color = QColor("#059669") if is_light else QColor("#10b981")
        pen = QPen(d_color, 1.2)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setZValue(22)
        self._scene.addItem(item)

    @classmethod
    def _curve_to_qpath(cls, curve: CurvePrimitive) -> QPainterPath:
        s = SCENE_PX_PER_CM
        path = QPainterPath()
        if isinstance(curve, LineSegment2D):
            path.moveTo(curve.p0.x * s, curve.p0.y * s)
            path.lineTo(curve.p1.x * s, curve.p1.y * s)
        elif isinstance(curve, CubicBezier2D):
            path.moveTo(curve.p0.x * s, curve.p0.y * s)
            path.cubicTo(
                curve.p1.x * s,
                curve.p1.y * s,
                curve.p2.x * s,
                curve.p2.y * s,
                curve.p3.x * s,
                curve.p3.y * s,
            )
        elif isinstance(curve, CatmullRomSpline2D):
            beziers = curve.to_beziers()
            for idx, bez in enumerate(beziers):
                if idx == 0:
                    path.moveTo(bez.p0.x * s, bez.p0.y * s)
                path.cubicTo(
                    bez.p1.x * s,
                    bez.p1.y * s,
                    bez.p2.x * s,
                    bez.p2.y * s,
                    bez.p3.x * s,
                    bez.p3.y * s,
                )
        return path
