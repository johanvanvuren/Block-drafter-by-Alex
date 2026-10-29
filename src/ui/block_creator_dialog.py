"""
Modal "Block Creator Studio" Dialog (`BlockCreatorDialog`).

Unites all three block-creation workflows in a dedicated studio window:
- "Pattern Cutting Textbook" Notebook — multi-line plain-English
  recipe editor with live compilation, line-by-line diagnostics, and instant 2D canvas preview.
- New Block Measurement Checklist + Guided Visual Step, Curve & "Click-to-Trace" Piece Builder
  (every action automatically writes a readable textbook line into the Notebook).
- Reference Image / Paper Pattern Trace-to-Formula — load an image onto the 2D canvas,
  calibrate 1:1 scale via 2 clicked points, align Origin (0,0), and click landmarks on the image
  with the Smart Parametric Formula Assistant suggesting measurement-based formulas.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.drafting_engine import DraftedBlockResult, DraftingEngine
from src.core.geometry import Point2D
from src.core.notebook_compiler import (
    NotebookCompiler,
    block_spec_to_notebook_script,
    format_curve_as_notebook_line,
    format_point_as_notebook_line,
    suggest_parametric_formulas,
)
from src.core.sizing import SizingManager
from src.ui.canvas_view import PatternCanvasView


STARTER_WORKING_BOX_SCRIPT = """# ===========================================================================
# PATTERN CUTTING NOTEBOOK: Custom Garment Block
# Write or paste plain-English drafting steps below, or use the Visual Builder
# and Reference Image Tracer tabs below to append steps automatically!
# ===========================================================================

# --- 1. Derived Variables & Ease Formulas ---
Var ease = 1.5cm
Var block_width = hips / 4 + ease

# --- 2. Parametric Construction Points ---
1. Point A is the origin (0, 0)
2. From A go right (block_width) to B
3. From A go down (skirt_length) to C
4. Point D is coord (B.x, C.y)
5. From A go down (waist_to_hip) to E
6. Point F is coord (B.x, E.y)
7. Point W_Side is offset (waist / 4 + 2.5cm, -1.0cm) from A
8. Midpoint of A and W_Side is D_Mid
9. Point D_Left is distance (dist(A, D_Mid) - 1.25cm) along A -> W_Side
10. Point D_Right is distance (dist(A, D_Mid) + 1.25cm) along A -> W_Side
11. From D_Mid go down (12.0cm) to D_Apex
12. Point G_Top is offset (block_width * 0.45, 6.0cm) from A
13. From G_Top go down (30.0cm) to G_Bot

# --- 3. Construction Curves & Guidelines ---
Bezier curve hip_curve from W_Side to F handles (80, dist(W_Side, F) * 0.38) and (-90, dist(W_Side, F) * 0.38)

# --- 4. Extracted Pattern Pieces, Darts, Grainlines & Notches ---
Piece main_panel "Custom Block Panel" (cut 2, sa 1.0cm): A -> D_Left -> D_Right -> W_Side -> curve(hip_curve) -> F -> D -> C -> A
Dart on main_panel: D_Left -> D_Apex -> D_Right
Internal line on main_panel: E -> F
Grainline on main_panel: G_Top -> G_Bot
Notch on main_panel at F along F -> D (count 1)
"""

BLANK_ORIGIN_SCRIPT = """# ===========================================================================
# PATTERN CUTTING NOTEBOOK: New Blank Garment Block
# ===========================================================================

1. Point A is the origin (0, 0)
2. From A go right (waist / 4 + 2cm) to B
3. From A go down (nape_to_waist) to C
4. Point D is coord (B.x, C.y)
"""


class SmartTraceFormulaDialog(QDialog):
    """
    Smart Parametric Formula Assistant Dialog.
    Shown when a user clicks a landmark on a calibrated Reference Image.
    """

    def __init__(
        self,
        parent: QWidget,
        suggested_point_id: str,
        ref_point_id: str,
        dx_cm: float,
        dy_cm: float,
        measurements: Mapping[str, float],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Smart Parametric Trace-to-Formula Assistant")
        self.resize(540, 320)

        layout = QVBoxLayout(self)

        info = QLabel(
            f"<b>Clicked Landmark on Reference Image:</b><br/>"
            f"Measured offset from <code>Point {ref_point_id}</code>: "
            f"<b>ΔX = {dx_cm:+.2f} cm</b>, <b>ΔY = {dy_cm:+.2f} cm</b>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()

        self.pt_id_edit = QLineEdit(suggested_point_id)
        form.addRow("New Point ID:", self.pt_id_edit)

        self.ref_id_label = QLabel(ref_point_id)
        form.addRow("Reference Point:", self.ref_id_label)

        # Populate X formula suggestions
        self.dx_combo = QComboBox()
        self.dx_combo.setEditable(True)
        for expr, desc in suggest_parametric_formulas(dx_cm, measurements):
            self.dx_combo.addItem(desc, expr)
        if self.dx_combo.count() > 0:
            self.dx_combo.setEditText(str(self.dx_combo.itemData(0)))
        self.dx_combo.currentIndexChanged.connect(
            lambda idx: self.dx_combo.setEditText(str(self.dx_combo.itemData(idx)))
        )
        form.addRow("ΔX Formula (Horizontal):", self.dx_combo)

        # Populate Y formula suggestions
        self.dy_combo = QComboBox()
        self.dy_combo.setEditable(True)
        for expr, desc in suggest_parametric_formulas(dy_cm, measurements):
            self.dy_combo.addItem(desc, expr)
        if self.dy_combo.count() > 0:
            self.dy_combo.setEditText(str(self.dy_combo.itemData(0)))
        self.dy_combo.currentIndexChanged.connect(
            lambda idx: self.dy_combo.setEditText(str(self.dy_combo.itemData(idx)))
        )
        form.addRow("ΔY Formula (Vertical):", self.dy_combo)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        accept_btn = QPushButton("✓ Add Parametric Point to Notebook")
        accept_btn.setObjectName("primaryBtn")
        accept_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(accept_btn)
        layout.addLayout(btn_row)

    def get_point_spec(self, ref_point_id: str) -> Dict[str, Any]:
        pid = re.sub(r"[^A-Za-z0-9_]", "_", self.pt_id_edit.text().strip()) or "P_Traced"
        dx_expr = self.dx_combo.currentText().split("  [")[0].strip() or "0"
        dy_expr = self.dy_combo.currentText().split("  [")[0].strip() or "0"
        return {
            "id": pid,
            "label": f"Point {pid}",
            "type": "offset",
            "from": ref_point_id,
            "dx": dx_expr,
            "dy": dy_expr,
        }


class BlockCreatorDialog(QDialog):
    """
    Full-screen modal studio window for creating or editing a Garment Block from scratch
    using Option 3 (Pattern Cutting Textbook Notebook), Option 1 (Visual Step & Piece Builder),
    and Option 5 (Reference Image Trace-to-Formula).
    """

    def __init__(
        self,
        parent: Optional[QWidget],
        sizing_manager: SizingManager,
        blocks_dir: Path,
        theme: str = "light",
        initial_block_spec: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Block Creator Studio — Create Garment Block from Scratch")
        self.setModal(True)

        # Responsive window sizing to fit comfortably within screen bounds
        screen = QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            w = min(1320, max(880, int(avail.width() * 0.94)))
            h = min(840, max(580, int(avail.height() * 0.90)))
            self.resize(w, h)
        else:
            self.resize(1180, 740)
        self.setMinimumSize(860, 540)

        self.sizing_manager = sizing_manager
        self.blocks_dir = blocks_dir
        self.theme = theme
        self.drafting_engine = DraftingEngine()

        self.saved_block_path: Optional[Path] = None
        self.compiled_block_spec: Dict[str, Any] = {}
        self.current_draft: Optional[DraftedBlockResult] = None

        # Custom user-defined measurements added in this session
        self.custom_measurement_defs: Dict[str, Dict[str, Any]] = {}
        self.measurement_checkboxes: Dict[str, QCheckBox] = {}

        # Click-to-Trace state & Reference Calibration state
        self._click_to_trace_target: str = "none"  # "none", "piece", "spline", "dart"
        self._traced_chain_tokens: List[str] = []
        self._calibration_clicks: List[Point2D] = []

        self._compile_timer = QTimer(self)
        self._compile_timer.setSingleShot(True)
        self._compile_timer.setInterval(260)
        self._compile_timer.timeout.connect(self._compile_and_render_notebook)

        self._build_ui()

        if initial_block_spec:
            self._populate_from_existing_spec(initial_block_spec)
        else:
            self._load_starter_script(STARTER_WORKING_BOX_SCRIPT)

    # -----------------------------------------------------------------------
    # UI Construction
    # -----------------------------------------------------------------------

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        # Top Banner
        header_row = QHBoxLayout()
        title_lbl = QLabel(
            "<b>BLOCK CREATOR STUDIO</b> — Author blocks via <b>Pattern Cutting Notebook (Recipe)</b>, "
            "<b>Visual Builder</b>, or <b>Reference Image Trace</b>"
        )
        title_lbl.setStyleSheet("font-size: 12px;")
        title_lbl.setWordWrap(True)
        header_row.addWidget(title_lbl, 1)

        tpl_box_btn = QPushButton("Load Box Starter")
        tpl_box_btn.setToolTip("Load standard working box template")
        tpl_box_btn.clicked.connect(lambda: self._load_starter_script(STARTER_WORKING_BOX_SCRIPT))
        tpl_blank_btn = QPushButton("Reset to Blank Origin")
        tpl_blank_btn.setToolTip("Start fresh with Point A at (0,0)")
        tpl_blank_btn.clicked.connect(lambda: self._load_starter_script(BLANK_ORIGIN_SCRIPT))
        header_row.addWidget(tpl_box_btn)
        header_row.addWidget(tpl_blank_btn)
        root_layout.addLayout(header_row)

        # 3-Column Splitter: [1. Metadata & Measurements] | [2. Notebook & Builders] | [3. 2D CAD Canvas]
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter, 1)

        left_col = self._create_left_metadata_and_measurements_column()
        center_col = self._create_center_notebook_and_builders_column()
        right_col = self._create_right_canvas_column()

        left_col.setMinimumWidth(220)
        center_col.setMinimumWidth(320)
        right_col.setMinimumWidth(280)
        splitter.setChildrenCollapsible(True)

        splitter.addWidget(left_col)
        splitter.addWidget(center_col)
        splitter.addWidget(right_col)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([260, 580, 540])

        # Bottom Action Footer
        footer = QHBoxLayout()
        self.status_banner = QLabel("Ready.")
        self.status_banner.setStyleSheet("font-weight: bold; color: #059669;")
        footer.addWidget(self.status_banner, 1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        export_json_btn = QPushButton("Save JSON As...")
        export_json_btn.setToolTip("Export block definition to a JSON file")
        export_json_btn.clicked.connect(self._on_export_block_as)

        save_load_btn = QPushButton("✓ Save & Open in Workspace")
        save_load_btn.setObjectName("primaryBtn")
        save_load_btn.setToolTip("Save block to application library and load it immediately into the workspace")
        save_load_btn.clicked.connect(self._on_save_and_open_in_workspace)

        footer.addWidget(cancel_btn)
        footer.addWidget(export_json_btn)
        footer.addWidget(save_load_btn)
        root_layout.addLayout(footer)

    def _create_left_metadata_and_measurements_column(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)

        # 1. Block Identity Group
        meta_group = QGroupBox("1. New Block Identity")
        meta_form = QFormLayout(meta_group)

        self.name_edit = QLineEdit("Custom Garment Block")
        self.name_edit.textChanged.connect(self._on_name_changed)
        meta_form.addRow("Block Name:", self.name_edit)

        self.id_edit = QLineEdit("custom_garment_block")
        meta_form.addRow("File ID:", self.id_edit)

        self.desc_edit = QLineEdit("Custom parametric garment sloper.")
        meta_form.addRow("Description:", self.desc_edit)

        layout.addWidget(meta_group)

        # 2. Required Body Measurements Checklist
        meas_group = QGroupBox("2. Required Body Measurements")
        meas_layout = QVBoxLayout(meas_group)

        hint = QLabel("Check measurements used by this garment:")
        hint.setWordWrap(True)
        meas_layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.meas_list_widget = QWidget()
        self.meas_list_layout = QVBoxLayout(self.meas_list_widget)
        self.meas_list_layout.setContentsMargins(2, 2, 2, 2)
        self.meas_list_layout.setSpacing(4)

        default_checked = {"waist", "hips", "waist_to_hip", "skirt_length", "bust", "nape_to_waist"}
        for key, field_def in self.sizing_manager.definitions.items():
            cb = QCheckBox(f"{field_def.label} ({key})")
            cb.setChecked(key in default_checked)
            cb.toggled.connect(self._on_measurements_selection_changed)
            self.measurement_checkboxes[key] = cb
            self.meas_list_layout.addWidget(cb)

        self.meas_list_layout.addStretch(1)
        scroll.setWidget(self.meas_list_widget)
        meas_layout.addWidget(scroll, 1)

        # Custom Measurement Adder
        add_m_row = QHBoxLayout()
        self.custom_m_key = QLineEdit()
        self.custom_m_key.setPlaceholderText("e.g. sleeve_len")
        self.custom_m_val = QDoubleSpinBox()
        self.custom_m_val.setRange(1.0, 250.0)
        self.custom_m_val.setValue(58.0)
        self.custom_m_val.setSuffix(" cm")
        add_m_btn = QPushButton("+ Add")
        add_m_btn.clicked.connect(self._on_add_custom_measurement)
        add_m_row.addWidget(self.custom_m_key, 1)
        add_m_row.addWidget(self.custom_m_val)
        add_m_row.addWidget(add_m_btn)
        meas_layout.addLayout(add_m_row)

        layout.addWidget(meas_group, 1)

        # 3. Clickable Formula Variable Pills
        pills_group = QGroupBox("3. Click-to-Insert Formula Pills")
        pills_layout = QVBoxLayout(pills_group)
        self.pills_grid = QGridLayout()
        self.pills_grid.setSpacing(4)
        pills_layout.addLayout(self.pills_grid)
        self._rebuild_formula_pills()
        layout.addWidget(pills_group)

        return panel

    def _create_center_notebook_and_builders_column(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)

        self.authoring_tabs = QTabWidget()
        self.authoring_tabs.addTab(
            self._create_option3_notebook_tab(),
            "Pattern Cutting Notebook",
        )
        self.authoring_tabs.addTab(
            self._create_option1_visual_builder_tab(),
            "Visual Step & Piece Builder",
        )
        self.authoring_tabs.addTab(
            self._create_option5_image_tracer_tab(),
            "Reference Image Trace-to-Formula",
        )
        self.authoring_tabs.addTab(
            self._create_compiled_json_preview_tab(),
            "Compiled JSON Preview",
        )

        layout.addWidget(self.authoring_tabs, 1)
        return panel

    def _create_option3_notebook_tab(self) -> QWidget:
        page = QWidget()
        nb_layout = QVBoxLayout(page)
        nb_layout.setContentsMargins(6, 6, 6, 6)
        nb_layout.setSpacing(6)

        nb_help = QLabel(
            "<b>Pattern Cutting Textbook Notebook</b>: Type or paste plain-English drafting recipes below (e.g. "
            "<code>From A go right (waist / 4 + 1cm) to B</code>, "
            "<code>Midpoint of A and B is M</code>, <code>Smooth curve armhole through P1, P2, P3</code>, "
            "<code>Piece back \"Back\" (cut 2, sa 1.0cm): A -> B -> C -> A</code>). "
            "The 2D canvas preview updates live as you type."
        )
        nb_help.setWordWrap(True)
        nb_layout.addWidget(nb_help)

        self.notebook_editor = QPlainTextEdit()
        self.notebook_editor.setFont(QFont("Consolas", 10))
        self.notebook_editor.textChanged.connect(lambda: self._compile_timer.start())
        nb_layout.addWidget(self.notebook_editor, 1)

        nb_btn_row = QHBoxLayout()
        compile_btn = QPushButton("Compile & Update Canvas Now")
        compile_btn.setObjectName("primaryBtn")
        compile_btn.clicked.connect(self._compile_and_render_notebook)
        nb_btn_row.addWidget(compile_btn)

        syntax_btn = QPushButton("Insert Sample Step Snippet...")
        syntax_btn.clicked.connect(self._on_insert_snippet)
        nb_btn_row.addWidget(syntax_btn)
        nb_btn_row.addStretch(1)
        nb_layout.addLayout(nb_btn_row)

        return page

    def _create_option1_visual_builder_tab(self) -> QWidget:
        sub_tabs = QTabWidget()

        # --- Sub-tab 1A: Add Point Builder ---
        pt_page = QWidget()
        pt_form = QFormLayout(pt_page)

        self.v_pt_id = QLineEdit("P_New")
        pt_form.addRow("New Point ID:", self.v_pt_id)

        self.v_pt_op = QComboBox()
        self.v_pt_op.addItem("Go Direction (Right / Left / Down / Up) from Point", "dir_offset")
        self.v_pt_op.addItem("2D Offset (ΔX, ΔY) from Point", "offset_2d")
        self.v_pt_op.addItem("Square Across & Down from Two Points (P1.x, P2.y)", "coord_ref")
        self.v_pt_op.addItem("Polar Distance & Angle (deg) from Point", "polar")
        self.v_pt_op.addItem("Midpoint (50%) between Two Points", "midpoint")
        self.v_pt_op.addItem("Distance along Line (P1 -> P2)", "line_dist")
        self.v_pt_op.addItem("Perpendicular from Point on Line (P1 -> P2)", "perpendicular")
        self.v_pt_op.addItem("Intersection of Two Lines (P1-P2 & P3-P4)", "line_intersection")
        pt_form.addRow("Operation:", self.v_pt_op)

        ref_row = QHBoxLayout()
        self.v_ref_p1 = QComboBox()
        self.v_ref_p2 = QComboBox()
        self.v_dir_combo = QComboBox()
        for d_label in ["right", "down", "left", "up"]:
            self.v_dir_combo.addItem(d_label)
        ref_row.addWidget(QLabel("From / P1:"))
        ref_row.addWidget(self.v_ref_p1, 1)
        ref_row.addWidget(QLabel("P2:"))
        ref_row.addWidget(self.v_ref_p2, 1)
        ref_row.addWidget(QLabel("Dir:"))
        ref_row.addWidget(self.v_dir_combo)
        pt_form.addRow("References:", ref_row)

        self.v_formula_1 = QLineEdit("waist / 4 + 1.5cm")
        self.v_formula_1.setPlaceholderText("Primary formula (Distance / ΔX / Length)")
        pt_form.addRow("Formula 1 (Dist/ΔX):", self.v_formula_1)

        self.v_formula_2 = QLineEdit("0")
        self.v_formula_2.setPlaceholderText("Secondary formula (ΔY / Angle deg / P3-P4)")
        pt_form.addRow("Formula 2 (ΔY/Angle):", self.v_formula_2)

        add_pt_btn = QPushButton("+ Append Point Step to Notebook")
        add_pt_btn.setObjectName("accentBtn")
        add_pt_btn.clicked.connect(self._on_visual_add_point)
        pt_form.addRow("", add_pt_btn)

        pt_scroll = QScrollArea()
        pt_scroll.setWidgetResizable(True)
        pt_scroll.setFrameShape(QFrame.Shape.NoFrame)
        pt_scroll.setWidget(pt_page)
        sub_tabs.addTab(pt_scroll, "1. Add Point")

        # --- Sub-tab 1B: Add Curve (Spline / Bezier) ---
        curve_page = QWidget()
        c_form = QFormLayout(curve_page)

        self.v_curve_id = QLineEdit("armhole_curve")
        c_form.addRow("Curve ID:", self.v_curve_id)

        self.v_curve_type = QComboBox()
        self.v_curve_type.addItem("Smooth Spline Curve through 3+ Points", "spline")
        self.v_curve_type.addItem("Cubic Bezier Curve between 2 Points (with Handle Angles)", "cubic_bezier")
        self.v_curve_type.addItem("Straight Construction Guideline", "line")
        c_form.addRow("Curve Type:", self.v_curve_type)

        self.v_curve_pts_edit = QLineEdit()
        self.v_curve_pts_edit.setPlaceholderText("Click points on 2D Canvas or type IDs: e.g. A, E, C")
        c_form.addRow("Points Sequence:", self.v_curve_pts_edit)

        c_trace_row = QHBoxLayout()
        self.c_trace_btn = QPushButton("🎯 Click Points on Canvas")
        self.c_trace_btn.setToolTip("Click construction points in order on the 2D canvas to fill sequence")
        self.c_trace_btn.setCheckable(True)
        self.c_trace_btn.toggled.connect(lambda checked: self._set_click_trace_target("spline" if checked else "none"))
        clear_c_btn = QPushButton("Clear")
        clear_c_btn.clicked.connect(lambda: self.v_curve_pts_edit.clear())
        c_trace_row.addWidget(self.c_trace_btn, 1)
        c_trace_row.addWidget(clear_c_btn)
        c_form.addRow("", c_trace_row)

        bez_row = QHBoxLayout()
        self.v_bez_a1 = QLineEdit("75")
        self.v_bez_a2 = QLineEdit("-90")
        bez_row.addWidget(QLabel("Start Angle (deg):"))
        bez_row.addWidget(self.v_bez_a1)
        bez_row.addWidget(QLabel("End Angle (deg):"))
        bez_row.addWidget(self.v_bez_a2)
        c_form.addRow("Bezier Angles:", bez_row)

        add_curve_btn = QPushButton("+ Append Curve to Notebook")
        add_curve_btn.setObjectName("accentBtn")
        add_curve_btn.clicked.connect(self._on_visual_add_curve)
        c_form.addRow("", add_curve_btn)

        curve_scroll = QScrollArea()
        curve_scroll.setWidgetResizable(True)
        curve_scroll.setFrameShape(QFrame.Shape.NoFrame)
        curve_scroll.setWidget(curve_page)
        sub_tabs.addTab(curve_scroll, "2. Add Curve")

        # --- Sub-tab 1C: Pattern Piece & Dart Click-to-Trace Builder ---
        piece_page = QWidget()
        p_form = QFormLayout(piece_page)

        p_meta_row = QHBoxLayout()
        self.v_piece_id = QLineEdit("front_panel")
        self.v_piece_name = QLineEdit("Front Panel")
        self.v_piece_cut = QSpinBox()
        self.v_piece_cut.setRange(1, 10)
        self.v_piece_cut.setValue(1)
        self.v_piece_sa = QDoubleSpinBox()
        self.v_piece_sa.setRange(0.0, 5.0)
        self.v_piece_sa.setSingleStep(0.25)
        self.v_piece_sa.setValue(1.0)
        self.v_piece_sa.setSuffix(" cm")
        p_meta_row.addWidget(QLabel("ID:"))
        p_meta_row.addWidget(self.v_piece_id)
        p_meta_row.addWidget(QLabel("Name:"))
        p_meta_row.addWidget(self.v_piece_name, 1)
        p_meta_row.addWidget(QLabel("Cut:"))
        p_meta_row.addWidget(self.v_piece_cut)
        p_meta_row.addWidget(QLabel("SA:"))
        p_meta_row.addWidget(self.v_piece_sa)
        p_form.addRow("Piece Info:", p_meta_row)

        self.v_piece_chain_edit = QLineEdit()
        self.v_piece_chain_edit.setPlaceholderText("e.g. A -> B -> curve(hip_curve) -> D -> C -> A")
        p_form.addRow("Boundary Loop:", self.v_piece_chain_edit)

        p_pick_row = QHBoxLayout()
        self.p_trace_btn = QPushButton("🎯 Click-to-Trace Loop")
        self.p_trace_btn.setToolTip("Click boundary points in order on canvas to trace piece outline")
        self.p_trace_btn.setCheckable(True)
        self.p_trace_btn.toggled.connect(lambda checked: self._set_click_trace_target("piece" if checked else "none"))

        self.v_insert_curve_combo = QComboBox()
        ins_curve_btn = QPushButton("+ Insert Curve")
        ins_curve_btn.clicked.connect(self._on_insert_curve_into_piece_chain)
        clear_p_btn = QPushButton("Clear")
        clear_p_btn.clicked.connect(self._on_clear_piece_chain)

        p_pick_row.addWidget(self.p_trace_btn, 1)
        p_pick_row.addWidget(self.v_insert_curve_combo)
        p_pick_row.addWidget(ins_curve_btn)
        p_pick_row.addWidget(clear_p_btn)
        p_form.addRow("Trace Helpers:", p_pick_row)

        p_actions_row = QHBoxLayout()
        add_piece_btn = QPushButton("+ Append Piece")
        add_piece_btn.setObjectName("primaryBtn")
        add_piece_btn.setToolTip("Append closed pattern piece boundary to notebook")
        add_piece_btn.clicked.connect(self._on_visual_add_piece)

        add_dart_btn = QPushButton("+ Add Dart (3 Pts)")
        add_dart_btn.setToolTip("Add dart using the last 3 points in boundary chain")
        add_dart_btn.clicked.connect(self._on_visual_add_dart)

        add_grain_btn = QPushButton("+ Add Grainline (2 Pts)")
        add_grain_btn.setToolTip("Add grainline using the last 2 points in boundary chain")
        add_grain_btn.clicked.connect(self._on_visual_add_grainline)

        p_actions_row.addWidget(add_piece_btn, 1)
        p_actions_row.addWidget(add_dart_btn)
        p_actions_row.addWidget(add_grain_btn)
        p_form.addRow("", p_actions_row)

        piece_scroll = QScrollArea()
        piece_scroll.setWidgetResizable(True)
        piece_scroll.setFrameShape(QFrame.Shape.NoFrame)
        piece_scroll.setWidget(piece_page)
        sub_tabs.addTab(piece_scroll, "3. Trace Pattern Piece & Darts")
        return sub_tabs

    def _create_option5_image_tracer_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        desc = QLabel(
            "<b>Reference Image / Paper Pattern Trace-to-Formula</b><br/>"
            "1. Load a photo or diagram of a pattern block.<br/>"
            "2. Click <b>Calibrate Scale</b> and click two points of known distance on the image.<br/>"
            "3. Click <b>Set Origin (0,0)</b> and click where Point A (0,0) sits on the image.<br/>"
            "4. Toggle <b>Trace Landmarks</b> and click corners on the image — the Smart Assistant will "
            "suggest parametric measurement formulas and append them to the Pattern Cutting Notebook!"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        row1 = QHBoxLayout()
        load_img_btn = QPushButton("📂 Load Reference Image (PNG/JPG)...")
        load_img_btn.setObjectName("primaryBtn")
        load_img_btn.clicked.connect(self._on_load_reference_image)

        clear_img_btn = QPushButton("Clear Image")
        clear_img_btn.clicked.connect(lambda: self.canvas_view.clear_reference_image())

        self.img_visible_cb = QCheckBox("Show Image")
        self.img_visible_cb.setChecked(True)
        self.img_visible_cb.toggled.connect(lambda v: self.canvas_view.set_reference_visible(v))

        row1.addWidget(load_img_btn)
        row1.addWidget(clear_img_btn)
        row1.addWidget(self.img_visible_cb)
        row1.addWidget(QLabel("Opacity:"))

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(55)
        self.opacity_slider.valueChanged.connect(lambda v: self.canvas_view.set_reference_opacity(v / 100.0))
        row1.addWidget(self.opacity_slider, 1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.calib_btn = QPushButton("📏 1. Calibrate Scale")
        self.calib_btn.setToolTip("Click 2 points of known distance on the image to set real-world scale")
        self.calib_btn.setCheckable(True)
        self.calib_btn.toggled.connect(self._on_toggle_calibrate_mode)

        self.origin_btn = QPushButton("🎯 2. Set Origin (0,0)")
        self.origin_btn.setToolTip("Click where Point A (0,0) sits on the image")
        self.origin_btn.setCheckable(True)
        self.origin_btn.toggled.connect(self._on_toggle_origin_mode)

        self.trace_img_btn = QPushButton("✏️ 3. Trace Landmarks")
        self.trace_img_btn.setToolTip("Click landmark corners on the image to suggest formulas")
        self.trace_img_btn.setCheckable(True)
        self.trace_img_btn.setObjectName("accentBtn")
        self.trace_img_btn.toggled.connect(self._on_toggle_image_trace_mode)

        row2.addWidget(self.calib_btn)
        row2.addWidget(self.origin_btn)
        row2.addWidget(self.trace_img_btn)
        layout.addLayout(row2)

        ref_row = QHBoxLayout()
        ref_row.addWidget(QLabel("Measure Traced Point Relative To:"))
        self.trace_ref_combo = QComboBox()
        ref_row.addWidget(self.trace_ref_combo, 1)
        layout.addLayout(ref_row)

        layout.addStretch(1)
        scroll.setWidget(page)
        return scroll

    def _create_compiled_json_preview_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.compiled_json_view = QPlainTextEdit()
        self.compiled_json_view.setReadOnly(True)
        self.compiled_json_view.setFont(QFont("Consolas", 9))
        layout.addWidget(self.compiled_json_view, 1)
        return page

    def _create_right_canvas_column(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)

        top_bar = QHBoxLayout()
        self.canvas_mode_label = QLabel("<b>Live 2D Preview</b>")
        self.canvas_mode_label.setToolTip("Scroll to Zoom, Drag to Pan")
        top_bar.addWidget(self.canvas_mode_label)
        top_bar.addStretch(1)

        self.creator_coord_lbl = QLabel("(0.00 cm, 0.00 cm)")
        self.creator_coord_lbl.setStyleSheet("font-weight: bold; color: #0284c7; padding-right: 10px;")
        top_bar.addWidget(self.creator_coord_lbl)

        fit_btn = QPushButton("Fit View")
        fit_btn.clicked.connect(lambda: self.canvas_view.fit_content_in_view())
        top_bar.addWidget(fit_btn)
        layout.addLayout(top_bar)

        self.canvas_view = PatternCanvasView(theme=self.theme)
        self.canvas_view.cursorMovedCm.connect(self._on_canvas_cursor_moved)
        self.canvas_view.pointClicked.connect(self._on_existing_point_clicked_on_canvas)
        self.canvas_view.canvasClickedCm.connect(self._on_canvas_clicked_in_tool_mode)
        layout.addWidget(self.canvas_view, 1)
        return panel

    # -----------------------------------------------------------------------
    # Notebook Compilation & Synchronization
    # -----------------------------------------------------------------------

    def _get_selected_required_measurements(self) -> List[Dict[str, Any]]:
        reqs: List[Dict[str, Any]] = []
        active_vals = self.sizing_manager.get_active_measurements()
        for key, cb in self.measurement_checkboxes.items():
            if not cb.isChecked():
                continue
            if key in self.sizing_manager.definitions:
                d = self.sizing_manager.definitions[key]
                reqs.append(
                    {
                        "key": key,
                        "label": d.label,
                        "default_cm": float(active_vals.get(key, d.default_cm)),
                        "min_cm": d.min_cm,
                        "max_cm": d.max_cm,
                    }
                )
            elif key in self.custom_measurement_defs:
                reqs.append(dict(self.custom_measurement_defs[key]))
        return reqs

    def _rebuild_formula_pills(self) -> None:
        while self.pills_grid.count():
            item = self.pills_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        checked_keys = [k for k, cb in self.measurement_checkboxes.items() if cb.isChecked()]
        tokens = checked_keys[:9] + ["/ 4", "/ 2", "+ 1.5cm"]
        for idx, tok in enumerate(tokens):
            btn = QPushButton(tok)
            btn.setStyleSheet("padding: 3px 6px; font-size: 11px;")
            btn.clicked.connect(lambda _, t=tok: self._insert_pill_token(t))
            self.pills_grid.addWidget(btn, idx // 3, idx % 3)

    def _insert_pill_token(self, token: str) -> None:
        # Insert into v_formula_1 if focused, else insert into notebook editor
        fw = self.focusWidget()
        if isinstance(fw, QLineEdit):
            fw.insert(f" {token} ")
        else:
            self.notebook_editor.insertPlainText(token)

    def _load_starter_script(self, script_text: str) -> None:
        self.notebook_editor.setPlainText(script_text)
        self._compile_and_render_notebook(auto_fit=True)

    def _populate_from_existing_spec(self, spec: Mapping[str, Any]) -> None:
        self.name_edit.setText(str(spec.get("name", "Custom Garment Block")))
        self.id_edit.setText(str(spec.get("block_id", "custom_block")))
        self.desc_edit.setText(str(spec.get("description", "")))

        req_keys = {str(r["key"]) for r in spec.get("required_measurements", [])}
        for k, cb in self.measurement_checkboxes.items():
            cb.setChecked(k in req_keys)

        script = block_spec_to_notebook_script(spec)
        self.notebook_editor.setPlainText(script)
        self._compile_and_render_notebook(auto_fit=True)

    def _compile_and_render_notebook(self, auto_fit: bool = False) -> None:
        meta = {
            "block_id": self.id_edit.text().strip() or "custom_block",
            "name": self.name_edit.text().strip() or "Custom Garment Block",
            "description": self.desc_edit.text().strip(),
            "unit": "cm",
            "required_measurements": self._get_selected_required_measurements(),
        }
        script = self.notebook_editor.toPlainText()
        spec, diagnostics = NotebookCompiler.compile_script(script, base_metadata=meta)
        self.compiled_block_spec = spec
        self.compiled_json_view.setPlainText(json.dumps(spec, indent=2))

        if diagnostics:
            first_err = diagnostics[0]
            self.status_banner.setStyleSheet("font-weight: bold; color: #e11d48;")
            self.status_banner.setText(
                f"Line {first_err.line_number}: {first_err.message}"
            )
            return

        try:
            active_meas = self.sizing_manager.get_active_measurements(spec)
            for k, cdef in self.custom_measurement_defs.items():
                active_meas.setdefault(k, float(cdef["default_cm"]))
            draft = self.drafting_engine.solve(spec, custom_measurements=active_meas)
            self.current_draft = draft
            self.canvas_view.update_data(draft, auto_fit=auto_fit)
            self._refresh_reference_dropdowns(draft)

            self.status_banner.setStyleSheet("font-weight: bold; color: #059669;")
            self.status_banner.setText(
                f"✓ Compiled Successfully: {len(draft.points)} points, "
                f"{len(draft.construction_curves)} curves, {len(draft.pieces)} pattern piece(s)"
            )
        except Exception as exc:
            self.status_banner.setStyleSheet("font-weight: bold; color: #d97706;")
            self.status_banner.setText(f"Drafting Evaluation Notice: {exc}")

    def _refresh_reference_dropdowns(self, draft: DraftedBlockResult) -> None:
        pt_ids = list(draft.points.keys())
        for combo in (self.v_ref_p1, self.v_ref_p2, self.trace_ref_combo):
            curr = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            for pid in pt_ids:
                combo.addItem(pid)
            if curr in pt_ids:
                combo.setCurrentText(curr)
            elif pt_ids:
                combo.setCurrentIndex(len(pt_ids) - 1 if combo is self.v_ref_p1 else 0)
            combo.blockSignals(False)

        curve_ids = list(draft.construction_curves.keys())
        curr_c = self.v_insert_curve_combo.currentText()
        self.v_insert_curve_combo.clear()
        for cid in curve_ids:
            self.v_insert_curve_combo.addItem(f"curve({cid})")
            self.v_insert_curve_combo.addItem(f"rev_curve({cid})")
        if curr_c:
            self.v_insert_curve_combo.setCurrentText(curr_c)

    def _append_notebook_line(self, line: str) -> None:
        current_text = self.notebook_editor.toPlainText().rstrip()
        updated = f"{current_text}\n{line}\n" if current_text else f"{line}\n"
        self.notebook_editor.setPlainText(updated)
        self._compile_and_render_notebook(auto_fit=False)

    # -----------------------------------------------------------------------
    # Visual Form & Click-to-Trace Handlers
    # -----------------------------------------------------------------------

    def _on_name_changed(self, text: str) -> None:
        slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
        if slug:
            self.id_edit.setText(slug)

    def _on_measurements_selection_changed(self) -> None:
        self._rebuild_formula_pills()
        self._compile_and_render_notebook(auto_fit=False)

    def _on_add_custom_measurement(self) -> None:
        raw_key = self.custom_m_key.text().strip()
        key = re.sub(r"[^a-z0-9_]", "_", raw_key.lower()).strip("_")
        if not key:
            return
        val = self.custom_m_val.value()
        self.custom_measurement_defs[key] = {
            "key": key,
            "label": raw_key.replace("_", " ").title(),
            "default_cm": val,
            "min_cm": 1.0,
            "max_cm": 250.0,
        }
        if key not in self.measurement_checkboxes:
            cb = QCheckBox(f"{raw_key.title()} ({key} = {val:.1f}cm)")
            cb.setChecked(True)
            cb.toggled.connect(self._on_measurements_selection_changed)
            self.measurement_checkboxes[key] = cb
            self.meas_list_layout.insertWidget(self.meas_list_layout.count() - 1, cb)
        self.custom_m_key.clear()
        self._on_measurements_selection_changed()

    def _on_visual_add_point(self) -> None:
        pid = re.sub(r"[^A-Za-z0-9_]", "_", self.v_pt_id.text().strip()) or "P_New"
        op = str(self.v_pt_op.currentData())
        p1 = self.v_ref_p1.currentText() or "A"
        p2 = self.v_ref_p2.currentText() or "B"
        direction = self.v_dir_combo.currentText()
        f1 = self.v_formula_1.text().strip() or "10cm"
        f2 = self.v_formula_2.text().strip() or "0"

        if op == "dir_offset":
            line = f"From {p1} go {direction} ({f1}) to {pid}"
        elif op == "offset_2d":
            line = f"Point {pid} is offset ({f1}, {f2}) from {p1}"
        elif op == "coord_ref":
            line = f"Point {pid} is coord ({p1}.x, {p2}.y)"
        elif op == "polar":
            line = f"Point {pid} is ({f1}) at angle ({f2}) from {p1}"
        elif op == "midpoint":
            line = f"Midpoint of {p1} and {p2} is {pid}"
        elif op == "line_dist":
            line = f"Point {pid} is distance ({f1}) along {p1} -> {p2}"
        elif op == "perpendicular":
            side = "left" if direction in ("left", "up") else "right"
            line = f"Point {pid} is perpendicular ({f1}) {side} from {p1} on line {p1} -> {p2}"
        elif op == "line_intersection":
            parts = [p.strip() for p in re.split(r"[,->\s]+", f2) if p.strip()]
            p3 = parts[0] if len(parts) > 0 else "C"
            p4 = parts[1] if len(parts) > 1 else "D"
            line = f"Intersect line {p1}->{p2} and line {p3}->{p4} at {pid}"
        else:
            line = f"From {p1} go right ({f1}) to {pid}"

        self._append_notebook_line(line)
        # Auto-advance point name suggestion
        self.v_pt_id.setText(f"P{len(self.compiled_block_spec.get('points', [])) + 1}")

    def _on_visual_add_curve(self) -> None:
        cid = re.sub(r"[^A-Za-z0-9_]", "_", self.v_curve_id.text().strip()) or "curve_1"
        ctype = str(self.v_curve_type.currentData())
        pts = [p.strip() for p in re.split(r"[,->\s]+", self.v_curve_pts_edit.text()) if p.strip()]
        if len(pts) < 2:
            QMessageBox.warning(self, "Add Curve", "Please select or click at least 2 points for the curve.")
            return

        if ctype == "spline":
            line = f"Smooth curve {cid} through {', '.join(pts)}"
        elif ctype == "cubic_bezier":
            p0, p3 = pts[0], pts[-1]
            a1 = self.v_bez_a1.text().strip() or "75"
            a2 = self.v_bez_a2.text().strip() or "-90"
            line = (
                f"Bezier curve {cid} from {p0} to {p3} "
                f"handles ({a1}, dist({p0}, {p3}) * 0.38) and ({a2}, dist({p0}, {p3}) * 0.38)"
            )
        else:
            line = f"Line {cid} from {pts[0]} to {pts[-1]}"

        self._append_notebook_line(line)

    def _set_click_trace_target(self, target: str) -> None:
        self._click_to_trace_target = target
        if target == "none":
            self.canvas_view.set_highlighted_points([])
            self.canvas_mode_label.setText("<b>Live 2D Preview</b>")
        else:
            self.canvas_mode_label.setText(
                f"<b>🎯 CLICK-TO-TRACE ACTIVE ({target.upper()})</b>: Click construction points in order on the canvas!"
            )

    def _on_existing_point_clicked_on_canvas(self, point_id: str) -> None:
        # Always set clicked point as Reference P1 for convenience
        if self.v_ref_p1.findText(point_id) >= 0:
            self.v_ref_p1.setCurrentText(point_id)

        if self._click_to_trace_target == "spline":
            curr = [p.strip() for p in self.v_curve_pts_edit.text().split(",") if p.strip()]
            curr.append(point_id)
            self.v_curve_pts_edit.setText(", ".join(curr))
            self.canvas_view.set_highlighted_points(curr)
        elif self._click_to_trace_target == "piece":
            self._traced_chain_tokens.append(point_id)
            self.v_piece_chain_edit.setText(" -> ".join(self._traced_chain_tokens))
            self.canvas_view.set_highlighted_points(
                [t for t in self._traced_chain_tokens if not t.startswith(("curve(", "rev_curve("))]
            )

    def _on_insert_curve_into_piece_chain(self) -> None:
        ctok = self.v_insert_curve_combo.currentText().strip()
        if not ctok:
            return
        curr = [t.strip() for t in self.v_piece_chain_edit.text().split("->") if t.strip()]
        curr.append(ctok)
        self._traced_chain_tokens = curr
        self.v_piece_chain_edit.setText(" -> ".join(curr))

    def _on_clear_piece_chain(self) -> None:
        self._traced_chain_tokens.clear()
        self.v_piece_chain_edit.clear()
        self.canvas_view.set_highlighted_points([])

    def _on_visual_add_piece(self) -> None:
        pid = re.sub(r"[^A-Za-z0-9_]", "_", self.v_piece_id.text().strip()) or "panel_1"
        pname = self.v_piece_name.text().strip() or "Pattern Piece"
        cut = self.v_piece_cut.value()
        sa = self.v_piece_sa.value()
        chain = self.v_piece_chain_edit.text().strip()
        if not chain:
            QMessageBox.warning(
                self,
                "Trace Pattern Piece",
                "Click points on the 2D canvas (with Click-to-Trace active) or enter a point loop first.",
            )
            return
        tokens = [t.strip() for t in chain.split("->") if t.strip()]
        # Auto-close loop if first and last point differ
        if len(tokens) >= 3 and tokens[0] != tokens[-1] and not tokens[-1].endswith(")"):
            tokens.append(tokens[0])
        line = f'Piece {pid} "{pname}" (cut {cut}, sa {sa:.1f}cm): {" -> ".join(tokens)}'
        self._append_notebook_line(line)
        self.p_trace_btn.setChecked(False)

    def _on_visual_add_dart(self) -> None:
        pid = re.sub(r"[^A-Za-z0-9_]", "_", self.v_piece_id.text().strip()) or "panel_1"
        tokens = [t.strip() for t in self.v_piece_chain_edit.text().split("->") if t.strip()]
        if len(tokens) < 3:
            QMessageBox.information(
                self,
                "Add Dart",
                "Click 3 points on the canvas (Left Leg -> Apex -> Right Leg) in the Boundary Loop box first.",
            )
            return
        dart_pts = tokens[-3:]
        self._append_notebook_line(f"Dart on {pid}: {' -> '.join(dart_pts)}")

    def _on_visual_add_grainline(self) -> None:
        pid = re.sub(r"[^A-Za-z0-9_]", "_", self.v_piece_id.text().strip()) or "panel_1"
        tokens = [t.strip() for t in self.v_piece_chain_edit.text().split("->") if t.strip()]
        if len(tokens) < 2:
            QMessageBox.information(
                self,
                "Add Grainline",
                "Click 2 points on the canvas (Grain Top -> Grain Bottom) in the Boundary Loop box first.",
            )
            return
        g_pts = tokens[-2:]
        self._append_notebook_line(f"Grainline on {pid}: {g_pts[0]} -> {g_pts[1]}")

    def _on_insert_snippet(self) -> None:
        snippets = [
            "From A go right (waist / 4 + 2cm) to B",
            "From A go down (nape_to_waist) to C",
            "Point D is coord (B.x, C.y)",
            "Point Sh_Tip is (shoulder_length) at angle (18) from A",
            "Midpoint of A and B is M",
            "Smooth curve armhole through P1, P2, P3",
            'Piece front_block "Front Block" (cut 1, sa 1.0cm): A -> B -> D -> C -> A',
            "Dart on front_block: D_L -> D_Apex -> D_R",
            "Grainline on front_block: G_Top -> G_Bot",
        ]
        choice, ok = QInputDialog.getItem(
            self,
            "Insert Pattern Cutting Textbook Snippet",
            "Select a template instruction line to append:",
            snippets,
            0,
            False,
        )
        if ok and choice:
            self._append_notebook_line(choice)

    # -----------------------------------------------------------------------
    # Reference Image Calibration, Origin & Smart Trace-to-Formula
    # -----------------------------------------------------------------------

    def _on_load_reference_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Reference Pattern Image or Diagram",
            str(self.blocks_dir.parent),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if file_path:
            if not self.canvas_view.load_reference_image(file_path):
                QMessageBox.warning(self, "Image Load Error", "Could not load the selected image file.")
            else:
                self.status_banner.setText(
                    "Reference image loaded! Next: Click '1. Calibrate Scale' and click 2 points of known distance."
                )

    def _on_toggle_calibrate_mode(self, checked: bool) -> None:
        if checked:
            self.origin_btn.setChecked(False)
            self.trace_img_btn.setChecked(False)
            self._calibration_clicks.clear()
            self.canvas_view.set_calibration_markers([])
            self.canvas_view.set_interaction_mode("calibrate")
            self.canvas_mode_label.setText(
                "<b>📏 CALIBRATE SCALE</b>: Click Point 1 and Point 2 on a known length on the image."
            )
        elif self.canvas_view.interaction_mode == "calibrate":
            self.canvas_view.set_interaction_mode("pan")
            self.canvas_mode_label.setText("<b>Live 2D Preview</b>")

    def _on_toggle_origin_mode(self, checked: bool) -> None:
        if checked:
            self.calib_btn.setChecked(False)
            self.trace_img_btn.setChecked(False)
            self.canvas_view.set_interaction_mode("set_origin")
            self.canvas_mode_label.setText(
                "<b>🎯 SET ORIGIN (0,0)</b>: Click on the image where Point A (0,0) should sit."
            )
        elif self.canvas_view.interaction_mode == "set_origin":
            self.canvas_view.set_interaction_mode("pan")
            self.canvas_mode_label.setText("<b>Live 2D Preview</b>")

    def _on_toggle_image_trace_mode(self, checked: bool) -> None:
        if checked:
            self.calib_btn.setChecked(False)
            self.origin_btn.setChecked(False)
            self.canvas_view.set_interaction_mode("trace_point")
            self.canvas_mode_label.setText(
                "<b>✏️ TRACE LANDMARK POINTS</b>: Click any corner on the reference image to generate a parametric formula!"
            )
        elif self.canvas_view.interaction_mode == "trace_point":
            self.canvas_view.set_interaction_mode("pan")
            self.canvas_mode_label.setText("<b>Live 2D Preview</b>")

    def _on_canvas_clicked_in_tool_mode(self, x_cm: float, y_cm: float) -> None:
        mode = self.canvas_view.interaction_mode
        clicked_pt = Point2D(x_cm, y_cm)

        if mode == "calibrate":
            self._calibration_clicks.append(clicked_pt)
            self.canvas_view.set_calibration_markers(self._calibration_clicks)
            if len(self._calibration_clicks) == 2:
                p1, p2 = self._calibration_clicks[0], self._calibration_clicks[1]
                real_cm, ok = QInputDialog.getDouble(
                    self,
                    "Calibrate Reference Image Scale",
                    "Enter the real-world physical distance (in cm) between Calib P1 and Calib P2:",
                    20.0,
                    0.5,
                    500.0,
                    2,
                )
                if ok and real_cm > 0:
                    self.canvas_view.calibrate_reference_scale(p1, p2, real_cm)
                    self.status_banner.setText(
                        f"✓ Reference image calibrated to 1:1 scale ({real_cm:.2f} cm)!"
                    )
                self.calib_btn.setChecked(False)
            return

        if mode == "set_origin":
            self.canvas_view.align_reference_origin_to_click(clicked_pt)
            self.origin_btn.setChecked(False)
            self.status_banner.setText("✓ Reference image aligned to CAD Origin (0, 0)!")
            return

        if mode == "trace_point":
            ref_id = self.trace_ref_combo.currentText() or "A"
            ref_pt = (
                self.current_draft.points.get(ref_id, Point2D(0.0, 0.0))
                if self.current_draft
                else Point2D(0.0, 0.0)
            )
            dx_cm = x_cm - ref_pt.x
            dy_cm = y_cm - ref_pt.y

            next_num = len(self.compiled_block_spec.get("points", [])) + 1
            suggested_id = f"P{next_num}"

            active_meas = self.sizing_manager.get_active_measurements(self.compiled_block_spec)
            dlg = SmartTraceFormulaDialog(
                self,
                suggested_point_id=suggested_id,
                ref_point_id=ref_id,
                dx_cm=dx_cm,
                dy_cm=dy_cm,
                measurements=active_meas,
            )
            if dlg.exec() == QDialog.DialogCode.Accepted:
                pt_spec = dlg.get_point_spec(ref_id)
                nb_line = format_point_as_notebook_line(pt_spec)
                self._append_notebook_line(nb_line)

    def _on_canvas_cursor_moved(self, x_cm: float, y_cm: float, nearest_info: str) -> None:
        self.creator_coord_lbl.setText(f"Cursor: ({x_cm:.2f} cm, {y_cm:.2f} cm)")

    # -----------------------------------------------------------------------
    # Saving & Exporting Block
    # -----------------------------------------------------------------------

    def _validate_before_save(self) -> bool:
        self._compile_and_render_notebook(auto_fit=False)
        if not self.compiled_block_spec.get("points"):
            QMessageBox.warning(self, "Save Block", "The block must contain at least one construction point.")
            return False
        return True

    def _on_export_block_as(self) -> None:
        if not self._validate_before_save():
            return
        default_name = f"{self.compiled_block_spec.get('block_id', 'custom_block')}.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Garment Block JSON",
            str(self.blocks_dir / default_name),
            "Block JSON Files (*.json)",
        )
        if file_path:
            out = Path(file_path)
            out.write_text(json.dumps(self.compiled_block_spec, indent=2), encoding="utf-8")
            self.saved_block_path = out
            QMessageBox.information(self, "Saved Block JSON", f"Saved block to:\n{out}")

    def _on_save_and_open_in_workspace(self) -> None:
        if not self._validate_before_save():
            return
        block_id = re.sub(
            r"[^a-z0-9_]",
            "_",
            str(self.compiled_block_spec.get("block_id", "custom_block")).lower(),
        ).strip("_") or "custom_block"
        self.compiled_block_spec["block_id"] = block_id
        out_path = self.blocks_dir / f"{block_id}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(self.compiled_block_spec, indent=2), encoding="utf-8")
        self.saved_block_path = out_path
        self.accept()
