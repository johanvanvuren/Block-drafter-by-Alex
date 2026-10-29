"""
Main PySide6 Desktop Window for "Block Drafter by Alex".

Unites:
- Left Panel: Garment Block selector, UK 8-16 Sizing presets, live bespoke measurement spinboxes, and Seam Allowance control
- Center Viewport: Interactive 2D Vector CAD Canvas (Drafting View & Print Tiling Preview) + Layer toggles + Light/Dark theme switcher
- Right Panel:
  * Tab 1: Live Step & Formula Editor (table of solved points + natural instruction sentence parser + live JSON editor)
  * Tab 2: Print Optimization & Minimum-Waste Comparison Matrix (A0, 36" Roll, A4, US Letter) + PDF/SVG/DXF Export Suite
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.drafting_engine import DraftedBlockResult, DraftingEngine
from src.core.math_parser import FormulaEvaluationError, parse_natural_instruction_line
from src.core.sizing import SizingManager
from src.exporters.dxf_exporter import DXFExporter
from src.exporters.pdf_exporter import PDFExporter
from src.exporters.svg_exporter import SVGExporter
from src.layout.nesting_engine import PAPER_FORMATS, LayoutResult, PrintLayoutEngine
from src.ui.block_creator_dialog import BlockCreatorDialog
from src.ui.canvas_view import PatternCanvasView


LIGHT_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #f8fafc;
    color: #0f172a;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}
QGroupBox {
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 10px;
    font-weight: bold;
    color: #0284c7;
    background-color: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QComboBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit, QTableWidget {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 4px 6px;
    color: #0f172a;
}
QComboBox:focus, QDoubleSpinBox:focus, QLineEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #0284c7;
}
QPushButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    padding: 6px 12px;
    color: #0f172a;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
}
QPushButton#primaryBtn {
    background-color: #0284c7;
    border-color: #0369a1;
    color: #ffffff;
}
QPushButton#primaryBtn:hover {
    background-color: #0369a1;
}
QPushButton#accentBtn {
    background-color: #0d9488;
    border-color: #0f766e;
    color: #ffffff;
}
QPushButton#accentBtn:hover {
    background-color: #0f766e;
}
QPushButton#themeBtn {
    background-color: #e2e8f0;
    border: 1px solid #cbd5e1;
    color: #0f172a;
    font-weight: bold;
}
QPushButton#themeBtn:hover {
    background-color: #cbd5e1;
}
QTabWidget::pane {
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    background-color: #ffffff;
}
QTabBar::tab {
    background: #e2e8f0;
    border: 1px solid #cbd5e1;
    padding: 7px 14px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    color: #475569;
}
QTabBar::tab:selected {
    background: #0284c7;
    color: #ffffff;
    font-weight: bold;
}
QHeaderView::section {
    background-color: #f1f5f9;
    color: #334155;
    padding: 4px;
    border: 1px solid #cbd5e1;
    font-weight: bold;
}
QStatusBar {
    background-color: #ffffff;
    border-top: 1px solid #e2e8f0;
}
"""


DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0f172a;
    color: #e2e8f0;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}
QGroupBox {
    border: 1px solid #1e293b;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 10px;
    font-weight: bold;
    color: #38bdf8;
    background-color: #0f172a;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QComboBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit, QTableWidget {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 4px 6px;
    color: #f8fafc;
}
QComboBox:focus, QDoubleSpinBox:focus, QLineEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #38bdf8;
}
QPushButton {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 5px;
    padding: 6px 12px;
    color: #f1f5f9;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #334155;
    border-color: #475569;
}
QPushButton#primaryBtn {
    background-color: #0284c7;
    border-color: #0369a1;
    color: #ffffff;
}
QPushButton#primaryBtn:hover {
    background-color: #0369a1;
}
QPushButton#accentBtn {
    background-color: #0d9488;
    border-color: #0f766e;
    color: #ffffff;
}
QPushButton#accentBtn:hover {
    background-color: #0f766e;
}
QPushButton#themeBtn {
    background-color: #334155;
    border: 1px solid #475569;
    color: #f8fafc;
    font-weight: bold;
}
QPushButton#themeBtn:hover {
    background-color: #475569;
}
QTabWidget::pane {
    border: 1px solid #1e293b;
    border-radius: 4px;
    background-color: #0f172a;
}
QTabBar::tab {
    background: #1e293b;
    border: 1px solid #334155;
    padding: 7px 14px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    color: #94a3b8;
}
QTabBar::tab:selected {
    background: #0284c7;
    color: #ffffff;
    font-weight: bold;
}
QHeaderView::section {
    background-color: #1e293b;
    color: #94a3b8;
    padding: 4px;
    border: 1px solid #334155;
    font-weight: bold;
}
QStatusBar {
    background-color: #0f172a;
    border-top: 1px solid #1e293b;
}
"""


class BlockDrafterMainWindow(QMainWindow):
    """Primary desktop application window for Parametric Garment Block Drafting."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Block Drafter by Alex — Parametric Garment Sloper & CAD Studio")
        
        # Responsive window sizing to fit comfortably within available desktop bounds
        screen = QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            w = min(1280, max(880, int(avail.width() * 0.90)))
            h = min(820, max(600, int(avail.height() * 0.88)))
            self.resize(w, h)
        else:
            self.resize(1180, 740)
        self.setMinimumSize(860, 540)

        self.current_theme: str = "light"
        # Support both normal Python run and PyInstaller bundle execution
        base_dir = getattr(sys, "_MEIPASS", None)
        self.root_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2]
        self.blocks_dir = self.root_dir / "data" / "blocks"

        self.drafting_engine = DraftingEngine()
        self.sizing_manager = SizingManager(self.root_dir / "data" / "sizes" / "uk_metric.json")
        self.layout_engine = PrintLayoutEngine()

        self.available_blocks: Dict[str, Path] = {}
        self.current_block_spec: Dict[str, Any] = {}
        self.current_draft: Optional[DraftedBlockResult] = None
        self.current_layout: Optional[LayoutResult] = None
        self.format_comparisons: Dict[str, LayoutResult] = {}

        self._measurement_spinboxes: Dict[str, QDoubleSpinBox] = {}
        self._updating_ui = False

        self._discover_builtin_blocks()
        self._build_ui()
        self.set_app_theme("light")
        self._load_initial_block()

    def _discover_builtin_blocks(self) -> None:
        self.available_blocks.clear()
        if self.blocks_dir.exists():
            for p in sorted(self.blocks_dir.glob("*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    name = str(data.get("name", p.stem))
                    self.available_blocks[name] = p
                except Exception:
                    continue

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(main_splitter, 1)

        # 1. Left Dock: Block & Sizing Panel
        left_panel = self._create_left_panel()
        main_splitter.addWidget(left_panel)

        # 2. Center Viewport: Interactive 2D CAD Canvas
        center_panel = self._create_center_panel()
        main_splitter.addWidget(center_panel)

        # 3. Right Dock: Formula Inspector + Print Layout & Export
        right_panel = self._create_right_panel()
        main_splitter.addWidget(right_panel)

        left_panel.setMinimumWidth(220)
        center_panel.setMinimumWidth(320)
        right_panel.setMinimumWidth(260)
        main_splitter.setChildrenCollapsible(True)

        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 0)
        main_splitter.setSizes([260, 660, 360])

        # Status Bar
        status = QStatusBar()
        self.setStatusBar(status)
        self.coord_label = QLabel("Cursor: (0.00 cm, 0.00 cm)")
        self.coord_label.setStyleSheet("color: #0284c7; font-weight: bold; padding-right: 16px;")
        self.inspect_label = QLabel("Hover over any construction point to inspect its formula.")
        self.inspect_label.setStyleSheet("color: #475569;")
        status.addPermanentWidget(self.coord_label)
        status.addWidget(self.inspect_label, 1)

    def set_app_theme(self, theme: str) -> None:
        """Switch desktop GUI stylesheet and canvas palette between 'light' and 'dark'."""
        self.current_theme = theme
        if theme == "light":
            self.setStyleSheet(LIGHT_STYLESHEET)
            if hasattr(self, "theme_btn"):
                self.theme_btn.setText("🌙 Dark Mode")
            if hasattr(self, "coord_label"):
                self.coord_label.setStyleSheet("color: #0284c7; font-weight: bold; padding-right: 16px;")
            if hasattr(self, "inspect_label"):
                self.inspect_label.setStyleSheet("color: #475569;")
        else:
            self.setStyleSheet(DARK_STYLESHEET)
            if hasattr(self, "theme_btn"):
                self.theme_btn.setText("☀️ Light Mode")
            if hasattr(self, "coord_label"):
                self.coord_label.setStyleSheet("color: #38bdf8; font-weight: bold; padding-right: 16px;")
            if hasattr(self, "inspect_label"):
                self.inspect_label.setStyleSheet("color: #94a3b8;")

        if hasattr(self, "canvas_view"):
            self.canvas_view.set_theme(theme)
        if hasattr(self, "active_waste_summary"):
            self._update_waste_summary_style()
        self._populate_waste_table()

    def toggle_theme(self) -> None:
        new_theme = "dark" if self.current_theme == "light" else "light"
        self.set_app_theme(new_theme)

    def _update_waste_summary_style(self) -> None:
        if self.current_theme == "light":
            self.active_waste_summary.setStyleSheet(
                "background-color: #f1f5f9; border: 1px solid #cbd5e1; border-left: 4px solid #0d9488; "
                "padding: 8px; border-radius: 4px; color: #0f172a;"
            )
        else:
            self.active_waste_summary.setStyleSheet(
                "background-color: #1e293b; border-left: 4px solid #0d9488; "
                "padding: 8px; border-radius: 4px; color: #f8fafc;"
            )

    def _create_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        # Block Selector Group
        blk_group = QGroupBox("1. Garment Block Library")
        blk_layout = QVBoxLayout(blk_group)

        self.block_combo = QComboBox()
        for name in self.available_blocks:
            self.block_combo.addItem(name)
        self.block_combo.currentTextChanged.connect(self._on_block_selected)
        blk_layout.addWidget(self.block_combo)

        studio_row = QHBoxLayout()
        new_blk_btn = QPushButton("+ New Block...")
        new_blk_btn.setObjectName("primaryBtn")
        new_blk_btn.setToolTip("Create a new garment block from scratch or textbook recipe")
        new_blk_btn.clicked.connect(lambda: self._on_open_block_creator_studio(edit_current=False))
        edit_blk_btn = QPushButton("Edit Studio...")
        edit_blk_btn.setObjectName("accentBtn")
        edit_blk_btn.setToolTip("Open current block in Block Creator Studio")
        edit_blk_btn.clicked.connect(lambda: self._on_open_block_creator_studio(edit_current=True))
        studio_row.addWidget(new_blk_btn, 1)
        studio_row.addWidget(edit_blk_btn)
        blk_layout.addLayout(studio_row)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("Load JSON...")
        load_btn.clicked.connect(self._on_load_custom_block_file)
        save_btn = QPushButton("Save JSON...")
        save_btn.clicked.connect(self._on_save_block_file)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(save_btn)
        blk_layout.addLayout(btn_row)
        layout.addWidget(blk_group)

        # Standard Sizing Group
        size_group = QGroupBox("2. Standard Size Preset (UK Metric)")
        size_layout = QVBoxLayout(size_group)

        size_row = QHBoxLayout()
        self.size_combo = QComboBox()
        for s_name in self.sizing_manager.list_size_names():
            self.size_combo.addItem(s_name)
        if "UK 10" in self.sizing_manager.list_size_names():
            self.size_combo.setCurrentText("UK 10")
        self.size_combo.currentTextChanged.connect(self._on_size_preset_changed)
        size_row.addWidget(self.size_combo, 1)

        reset_btn = QPushButton("Reset Size")
        reset_btn.clicked.connect(self._on_reset_size_measurements)
        size_row.addWidget(reset_btn)
        size_layout.addLayout(size_row)
        layout.addWidget(size_group)

        # Custom Measurements Scroll Area
        meas_group = QGroupBox("3. Body Measurements (cm — Live)")
        meas_outer = QVBoxLayout(meas_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.meas_form_container = QWidget()
        self.meas_form_layout = QFormLayout(self.meas_form_container)
        self.meas_form_layout.setContentsMargins(2, 2, 2, 2)
        self.meas_form_layout.setSpacing(6)
        scroll.setWidget(self.meas_form_container)
        meas_outer.addWidget(scroll, 1)
        layout.addWidget(meas_group, 1)

        # Seam Allowance Control
        sa_group = QGroupBox("4. Global Seam Allowance")
        sa_layout = QFormLayout(sa_group)
        self.sa_spin = QDoubleSpinBox()
        self.sa_spin.setRange(0.0, 5.0)
        self.sa_spin.setSingleStep(0.25)
        self.sa_spin.setValue(1.0)
        self.sa_spin.setSuffix(" cm")
        self.sa_spin.valueChanged.connect(self._recalculate_all)
        sa_layout.addRow("Seam Allowance:", self.sa_spin)
        layout.addWidget(sa_group)

        return panel

    def _create_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Row 1: Mode Switches & View / Theme Controls
        mode_bar = QHBoxLayout()
        mode_bar.setContentsMargins(0, 0, 0, 0)
        mode_bar.setSpacing(6)

        self.draft_mode_btn = QPushButton("Drafting Canvas")
        self.draft_mode_btn.setObjectName("primaryBtn")
        self.draft_mode_btn.setToolTip("Parametric Drafting & Construction View")
        self.draft_mode_btn.clicked.connect(lambda: self._switch_canvas_mode("drafting"))

        self.layout_mode_btn = QPushButton("Print & Tiling Preview")
        self.layout_mode_btn.setToolTip("Print Optimization & Page Tiling Layout")
        self.layout_mode_btn.clicked.connect(lambda: self._switch_canvas_mode("layout"))

        mode_bar.addWidget(self.draft_mode_btn)
        mode_bar.addWidget(self.layout_mode_btn)
        mode_bar.addStretch(1)

        fit_btn = QPushButton("Fit View")
        fit_btn.setToolTip("Fit all pattern pieces in current view")
        fit_btn.clicked.connect(lambda: self.canvas_view.fit_content_in_view())
        mode_bar.addWidget(fit_btn)

        # Dynamic Light/Dark Theme Switcher Button
        self.theme_btn = QPushButton("🌙 Dark Mode")
        self.theme_btn.setObjectName("themeBtn")
        self.theme_btn.clicked.connect(self.toggle_theme)
        mode_bar.addWidget(self.theme_btn)
        layout.addLayout(mode_bar)

        # Row 2: Layer Visibility Toggles (compact bar)
        layer_bar = QHBoxLayout()
        layer_bar.setContentsMargins(0, 0, 0, 0)
        layer_bar.setSpacing(6)

        layers_lbl = QLabel("Layers:")
        layers_lbl.setStyleSheet("font-weight: bold; color: #64748b; font-size: 11px;")
        layer_bar.addWidget(layers_lbl)

        layer_defs = [
            ("construction", "Guides"),
            ("points", "Points"),
            ("seam_line", "Seam"),
            ("seam_allowance", "Cut/SA"),
            ("internal_darts", "Darts"),
            ("grainline", "Grain"),
            ("notches", "Notches"),
            ("labels", "Labels"),
        ]
        for key, label in layer_defs:
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.toggled.connect(lambda checked, k=key: self.canvas_view.set_layer_visible(k, checked))
            layer_bar.addWidget(cb)

        layer_bar.addStretch(1)
        layout.addLayout(layer_bar)

        # Interactive 2D Vector Canvas
        self.canvas_view = PatternCanvasView(theme=self.current_theme)
        self.canvas_view.cursorMovedCm.connect(self._on_canvas_cursor_moved)
        layout.addWidget(self.canvas_view, 1)

        return panel

    def _create_right_panel(self) -> QWidget:
        tabs = QTabWidget()

        # Tab 1: Step & Formula Editor
        formula_tab = QWidget()
        f_layout = QVBoxLayout(formula_tab)

        pts_group = QGroupBox("Solved Parametric Points & Formulas")
        pts_layout = QVBoxLayout(pts_group)
        self.points_table = QTableWidget(0, 4)
        self.points_table.setHorizontalHeaderLabels(["ID", "Type", "Formula / Spec", "Coords (cm)"])
        self.points_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.points_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.points_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.points_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        pts_layout.addWidget(self.points_table)
        f_layout.addWidget(pts_group, 1)

        # Natural Language Instruction Quick-Adder
        nl_group = QGroupBox("Quick Natural Instruction Adder")
        nl_layout = QVBoxLayout(nl_group)
        self.nl_input = QLineEdit()
        self.nl_input.setPlaceholderText(
            'e.g. Point P_Custom is (waist / 4 + 1cm) on the X-axis from Point A'
        )
        add_nl_btn = QPushButton("Parse & Add Step to Block")
        add_nl_btn.setObjectName("accentBtn")
        add_nl_btn.clicked.connect(self._on_add_natural_instruction)
        nl_layout.addWidget(self.nl_input)
        nl_layout.addWidget(add_nl_btn)
        f_layout.addWidget(nl_group)

        # Live JSON Block Instruction Editor
        json_group = QGroupBox("Live Block Instruction JSON Editor")
        json_layout = QVBoxLayout(json_group)
        self.json_editor = QPlainTextEdit()
        self.json_editor.setFont(QFont("Consolas", 10))
        apply_json_btn = QPushButton("Apply JSON Instructions & Re-Solve")
        apply_json_btn.setObjectName("primaryBtn")
        apply_json_btn.clicked.connect(self._on_apply_json_editor)
        json_layout.addWidget(self.json_editor, 1)
        json_layout.addWidget(apply_json_btn)
        f_layout.addWidget(json_group, 1)

        tabs.addTab(formula_tab, "Step & Formula Editor")

        # Tab 2: Print Optimization, Tiling & CAD Export
        export_scroll = QScrollArea()
        export_scroll.setWidgetResizable(True)
        export_scroll.setFrameShape(QFrame.Shape.NoFrame)
        export_tab = QWidget()
        e_layout = QVBoxLayout(export_tab)
        e_layout.setContentsMargins(4, 4, 4, 4)
        e_layout.setSpacing(6)

        opt_group = QGroupBox("Print Optimization & Tiling Parameters")
        opt_form = QFormLayout(opt_group)

        self.format_combo = QComboBox()
        for fmt_id, fmt_spec in PAPER_FORMATS.items():
            self.format_combo.addItem(fmt_spec.name, fmt_id)
        self.format_combo.setCurrentIndex(2)  # Default to A4 Tiled
        self.format_combo.currentIndexChanged.connect(self._recalculate_layout_only)
        opt_form.addRow("Target Print Format:", self.format_combo)

        self.rotation_combo = QComboBox()
        self.rotation_combo.addItem("Cardinal (0° / 90° / 180° / 270°)", "cardinal_90")
        self.rotation_combo.addItem("Grainline-Locked (0° / 180°)", "grainline_locked")
        self.rotation_combo.addItem("Free Angle (15° increments)", "free_angle")
        self.rotation_combo.currentIndexChanged.connect(self._recalculate_layout_only)
        opt_form.addRow("Piece Rotation Policy:", self.rotation_combo)

        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setRange(0.5, 4.0)
        self.margin_spin.setSingleStep(0.1)
        self.margin_spin.setValue(1.2)
        self.margin_spin.setSuffix(" cm")
        self.margin_spin.valueChanged.connect(self._recalculate_layout_only)
        opt_form.addRow("Page Trim Margin:", self.margin_spin)

        self.expand_cuts_cb = QCheckBox("Pack all cut copies (e.g. 2× Back)")
        self.expand_cuts_cb.setToolTip("Pack all piece cut quantities instead of single sloper templates")
        self.expand_cuts_cb.toggled.connect(self._recalculate_layout_only)
        opt_form.addRow("", self.expand_cuts_cb)

        e_layout.addWidget(opt_group)

        # Waste Comparison Matrix Table
        waste_group = QGroupBox("Multi-Format Paper & Waste Comparison (Minimum Waste)")
        waste_layout = QVBoxLayout(waste_group)
        self.waste_table = QTableWidget(4, 5)
        self.waste_table.setHorizontalHeaderLabels(
            ["Format", "Pages / Length", "Pattern Area", "Paper Required", "Waste %"]
        )
        self.waste_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col_i in range(1, 5):
            self.waste_table.horizontalHeader().setSectionResizeMode(
                col_i, QHeaderView.ResizeMode.ResizeToContents
            )
        waste_layout.addWidget(self.waste_table)

        self.active_waste_summary = QLabel("")
        self.active_waste_summary.setWordWrap(True)
        self._update_waste_summary_style()
        waste_layout.addWidget(self.active_waste_summary)
        e_layout.addWidget(waste_group, 1)

        # Export Buttons Group
        exp_group = QGroupBox("Industry-Standard 1:1 Scale Exports")
        exp_layout = QVBoxLayout(exp_group)

        pdf_btn = QPushButton("Export 1:1 Print PDF (Plotter / Tiled)...")
        pdf_btn.setObjectName("primaryBtn")
        pdf_btn.setToolTip("Export 1:1 scale print-ready PDF for continuous roll plotters or tiled A4/Letter")
        pdf_btn.clicked.connect(self._on_export_pdf)
        exp_layout.addWidget(pdf_btn)

        svg_btn = QPushButton("Export 1:1 Vector SVG (Illustrator)...")
        svg_btn.setObjectName("accentBtn")
        svg_btn.setToolTip("Export clean 1:1 mm vector SVG compatible with Adobe Illustrator and Inkscape")
        svg_btn.clicked.connect(self._on_export_svg)
        exp_layout.addWidget(svg_btn)

        dxf_aama_btn = QPushButton("Export DXF (AAMA / ASTM D6673)...")
        dxf_aama_btn.setToolTip("Export apparel industry standard DXF with rule tables for Gerber, Optitex, CLO3D")
        dxf_aama_btn.clicked.connect(lambda: self._on_export_dxf("aama"))
        exp_layout.addWidget(dxf_aama_btn)

        dxf_cad_btn = QPushButton("Export Standard Layered DXF (AutoCAD)...")
        dxf_cad_btn.setToolTip("Export standard layered CAD DXF for AutoCAD, Rhino, and generic CAD")
        dxf_cad_btn.clicked.connect(lambda: self._on_export_dxf("standard_cad"))
        exp_layout.addWidget(dxf_cad_btn)

        e_layout.addWidget(exp_group)

        export_scroll.setWidget(export_tab)
        tabs.addTab(export_scroll, "Print Layout & Exports")
        return tabs

    # -----------------------------------------------------------------------
    # Block Loading & Live Reactive Calculation
    # -----------------------------------------------------------------------

    def _load_initial_block(self) -> None:
        if self.available_blocks:
            first_name = next(iter(self.available_blocks.keys()))
            self._load_block_from_path(self.available_blocks[first_name])

    def _load_block_from_path(self, path: Path) -> None:
        self.current_block_spec = copy.deepcopy(self.drafting_engine.load_block_file(path))
        self.sizing_manager.reset_overrides()
        self._rebuild_measurement_spinboxes()
        self._sync_json_editor()
        self._recalculate_all(auto_fit=True)

    def _rebuild_measurement_spinboxes(self) -> None:
        self._updating_ui = True
        while self.meas_form_layout.rowCount() > 0:
            self.meas_form_layout.removeRow(0)
        self._measurement_spinboxes.clear()

        active_meas = self.sizing_manager.get_active_measurements(self.current_block_spec)
        for req in self.current_block_spec.get("required_measurements", []):
            key = str(req["key"])
            label = str(req.get("label", key))
            min_v = float(req.get("min_cm", 5.0))
            max_v = float(req.get("max_cm", 250.0))
            val = float(active_meas.get(key, req.get("default_cm", 50.0)))

            spin = QDoubleSpinBox()
            spin.setRange(min_v, max_v)
            spin.setSingleStep(0.5)
            spin.setDecimals(2)
            spin.setValue(val)
            spin.setSuffix(" cm")
            spin.valueChanged.connect(lambda v, k=key: self._on_measurement_edited(k, v))
            self._measurement_spinboxes[key] = spin
            self.meas_form_layout.addRow(f"{label}:", spin)

        self._updating_ui = False

    def _sync_json_editor(self) -> None:
        self._updating_ui = True
        self.json_editor.setPlainText(json.dumps(self.current_block_spec, indent=2))
        self._updating_ui = False

    def _recalculate_all(self, auto_fit: bool = False) -> None:
        if self._updating_ui or not self.current_block_spec:
            return
        try:
            active_meas = self.sizing_manager.get_active_measurements(self.current_block_spec)
            sa_cm = self.sa_spin.value()
            self.current_draft = self.drafting_engine.solve(
                self.current_block_spec,
                custom_measurements=active_meas,
                seam_allowance_override_cm=sa_cm,
            )
            self._populate_points_table(self.current_draft)
            self._recalculate_layout_only(auto_fit=auto_fit)
        except Exception as exc:
            self.statusBar().showMessage(f"Drafting Error: {exc}", 8000)

    def _recalculate_layout_only(self, auto_fit: bool = False) -> None:
        if self.current_draft is None:
            return
        fmt_id = str(self.format_combo.currentData() or "A4")
        rot_mode = str(self.rotation_combo.currentData() or "cardinal_90")
        margin_cm = self.margin_spin.value()
        expand_cuts = self.expand_cuts_cb.isChecked()

        self.format_comparisons = self.layout_engine.compare_all_formats(
            draft=self.current_draft,
            rotation_mode=rot_mode,
            margin_cm=margin_cm,
            expand_cut_count=expand_cuts,
        )
        self.current_layout = self.format_comparisons[fmt_id]
        self._populate_waste_table()
        self.canvas_view.update_data(
            self.current_draft,
            self.current_layout,
            auto_fit=bool(auto_fit),
        )

    def _populate_points_table(self, draft: DraftedBlockResult) -> None:
        pt_specs = self.current_block_spec.get("points", [])
        self.points_table.setRowCount(len(pt_specs))
        for row_idx, spec in enumerate(pt_specs):
            pid = str(spec.get("id", ""))
            ptype = str(spec.get("type", ""))
            resolved = draft.points.get(pid)
            formula_str = resolved.formula_summary if resolved else ""
            coord_str = f"({resolved.x:.2f}, {resolved.y:.2f})" if resolved else "—"

            self.points_table.setItem(row_idx, 0, QTableWidgetItem(pid))
            self.points_table.setItem(row_idx, 1, QTableWidgetItem(ptype))
            self.points_table.setItem(row_idx, 2, QTableWidgetItem(formula_str))
            self.points_table.setItem(row_idx, 3, QTableWidgetItem(coord_str))

    def _populate_waste_table(self) -> None:
        if not self.format_comparisons:
            return

        # Find format with minimum waste percentage
        best_fmt_id = min(
            self.format_comparisons.keys(),
            key=lambda fid: self.format_comparisons[fid].waste_percentage,
        )

        is_light = self.current_theme == "light"
        best_color = QColor("#059669") if is_light else QColor("#34d399")

        self.waste_table.setRowCount(len(self.format_comparisons))
        for row, (fmt_id, res) in enumerate(self.format_comparisons.items()):
            is_best = fmt_id == best_fmt_id
            fmt_label = f"★ {res.paper_format.name}" if is_best else res.paper_format.name
            if res.paper_format.is_roll:
                pages_str = f"Roll: {res.pages[0].paper_height_cm:.1f} cm long"
            else:
                pages_str = f"{res.active_page_count} sheet(s) ({res.grid_rows}×{res.grid_cols})"

            pat_str = f"{res.pattern_area_cm2:.0f} cm²"
            pap_str = f"{res.total_paper_area_cm2:.0f} cm² ({res.total_paper_area_cm2 / 10000.0:.2f} m²)"
            waste_str = f"{res.waste_percentage:.1f}% waste"

            items = [
                QTableWidgetItem(fmt_label),
                QTableWidgetItem(pages_str),
                QTableWidgetItem(pat_str),
                QTableWidgetItem(pap_str),
                QTableWidgetItem(waste_str),
            ]
            for col, item in enumerate(items):
                if is_best:
                    item.setForeground(best_color)
                self.waste_table.setItem(row, col, item)

        if self.current_layout:
            cl = self.current_layout
            best_res = self.format_comparisons[best_fmt_id]
            self.active_waste_summary.setText(
                f"<b>Selected Format ({cl.paper_format.name}):</b><br/>"
                f"• Pattern Area: <b>{cl.pattern_area_cm2:.1f} cm²</b> | "
                f"Total Paper Required: <b>{cl.total_paper_area_cm2:.1f} cm² ({cl.total_paper_area_cm2 / 10000.0:.3f} m²)</b><br/>"
                f"• Paper Waste: <b>{cl.waste_percentage:.1f}%</b> ({cl.waste_area_cm2:.1f} cm² unused) | "
                f"Material Utilization: <b>{cl.utilization_percentage:.1f}%</b><br/>"
                f"• <i>Lowest-Waste Recommendation:</i> <b>{best_res.paper_format.name}</b> "
                f"({best_res.waste_percentage:.1f}% waste)"
            )

    # -----------------------------------------------------------------------
    # UI Event Handlers
    # -----------------------------------------------------------------------

    def _switch_canvas_mode(self, mode: str) -> None:
        if mode == "drafting":
            self.draft_mode_btn.setObjectName("primaryBtn")
            self.layout_mode_btn.setObjectName("")
        else:
            self.draft_mode_btn.setObjectName("")
            self.layout_mode_btn.setObjectName("primaryBtn")
        self.draft_mode_btn.style().unpolish(self.draft_mode_btn)
        self.draft_mode_btn.style().polish(self.draft_mode_btn)
        self.layout_mode_btn.style().unpolish(self.layout_mode_btn)
        self.layout_mode_btn.style().polish(self.layout_mode_btn)
        self.canvas_view.set_view_mode(mode)

    def _on_block_selected(self, block_name: str) -> None:
        if block_name in self.available_blocks:
            self._load_block_from_path(self.available_blocks[block_name])

    def _on_size_preset_changed(self, size_name: str) -> None:
        if not size_name or self._updating_ui:
            return
        self.sizing_manager.select_preset(size_name, clear_overrides=True)
        self._rebuild_measurement_spinboxes()
        self._recalculate_all(auto_fit=False)

    def _on_reset_size_measurements(self) -> None:
        self.sizing_manager.reset_overrides()
        self._rebuild_measurement_spinboxes()
        self._recalculate_all(auto_fit=False)

    def _on_measurement_edited(self, key: str, value: float) -> None:
        if self._updating_ui:
            return
        self.sizing_manager.set_custom_value(key, value)
        self._recalculate_all(auto_fit=False)

    def _on_canvas_cursor_moved(self, x_cm: float, y_cm: float, nearest_info: str) -> None:
        self.coord_label.setText(f"Cursor: ({x_cm:.2f} cm, {y_cm:.2f} cm)")
        if nearest_info:
            self.inspect_label.setText(nearest_info)
        else:
            self.inspect_label.setText("Hover over any construction point to inspect its formula.")

    def _on_add_natural_instruction(self) -> None:
        sentence = self.nl_input.text().strip()
        if not sentence:
            return
        try:
            pt_spec = parse_natural_instruction_line(sentence)
            pts_list = self.current_block_spec.setdefault("points", [])
            replaced = False
            for idx, existing in enumerate(pts_list):
                if existing.get("id") == pt_spec["id"]:
                    pts_list[idx] = pt_spec
                    replaced = True
                    break
            if not replaced:
                pts_list.append(pt_spec)
            self._sync_json_editor()
            self._recalculate_all(auto_fit=False)
            self.nl_input.clear()
            self.statusBar().showMessage(f"Added/updated Point '{pt_spec['id']}' from natural instruction.", 5000)
        except FormulaEvaluationError as exc:
            QMessageBox.warning(self, "Instruction Parse Error", str(exc))

    def _on_apply_json_editor(self) -> None:
        raw = self.json_editor.toPlainText()
        try:
            parsed = json.loads(raw)
            active_meas = self.sizing_manager.get_active_measurements(parsed)
            self.drafting_engine.solve(parsed, custom_measurements=active_meas)
            self.current_block_spec = parsed
            self._rebuild_measurement_spinboxes()
            self._recalculate_all(auto_fit=False)
            self.statusBar().showMessage("Block instructions updated and solved.", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Block Instruction Error", f"Failed to solve block JSON:\n{exc}")

    def _on_open_block_creator_studio(self, edit_current: bool = False) -> None:
        """Open the Block Creator Studio dialog (Notebook + Visual Builder + Image Trace)."""
        initial_spec = self.current_block_spec if edit_current else None
        dlg = BlockCreatorDialog(
            parent=self,
            sizing_manager=self.sizing_manager,
            blocks_dir=self.blocks_dir,
            theme=self.current_theme,
            initial_block_spec=initial_spec,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.saved_block_path is not None:
            self._discover_builtin_blocks()
            self.block_combo.blockSignals(True)
            self.block_combo.clear()
            for name in self.available_blocks:
                self.block_combo.addItem(name)
            saved_name = str(dlg.compiled_block_spec.get("name", dlg.saved_block_path.stem))
            if saved_name in self.available_blocks:
                self.block_combo.setCurrentText(saved_name)
            self.block_combo.blockSignals(False)
            self._load_block_from_path(dlg.saved_block_path)
            self.statusBar().showMessage(
                f"Loaded block '{saved_name}' from Block Creator Studio.",
                6000,
            )

    def _on_load_custom_block_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Garment Block JSON",
            str(self.blocks_dir),
            "Block JSON Files (*.json)",
        )
        if file_path:
            try:
                self._load_block_from_path(Path(file_path))
            except Exception as exc:
                QMessageBox.critical(self, "Load Error", f"Could not load block file:\n{exc}")

    def _on_save_block_file(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Garment Block JSON",
            str(self.blocks_dir / f"{self.current_block_spec.get('block_id', 'custom_block')}.json"),
            "Block JSON Files (*.json)",
        )
        if file_path:
            Path(file_path).write_text(json.dumps(self.current_block_spec, indent=2), encoding="utf-8")
            self.statusBar().showMessage(f"Saved block JSON to {file_path}", 5000)

    def _on_export_pdf(self) -> None:
        if not self.current_draft or not self.current_layout:
            return
        fmt_id = self.current_layout.paper_format.format_id.lower()
        default_name = f"{self.current_draft.block_id}_{self.sizing_manager.active_preset.replace(' ', '')}_{fmt_id}.pdf"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export 1:1 Print-Ready PDF",
            str(self.root_dir / default_name),
            "PDF Files (*.pdf)",
        )
        if file_path:
            out = PDFExporter.export_layout(
                draft=self.current_draft,
                layout=self.current_layout,
                output_path=file_path,
                include_assembly_map=True,
                include_seam_allowance=self.canvas_view.layer_visibility.get("seam_allowance", True),
            )
            QMessageBox.information(
                self,
                "PDF Export Complete",
                f"Exported 1:1 scale PDF to:\n{out}\n\n"
                f"Format: {self.current_layout.paper_format.name}\n"
                f"Active Pattern Sheets: {self.current_layout.active_page_count}\n"
                f"Paper Waste: {self.current_layout.waste_percentage:.1f}%",
            )

    def _on_export_svg(self) -> None:
        if not self.current_draft:
            return
        default_name = f"{self.current_draft.block_id}_{self.sizing_manager.active_preset.replace(' ', '')}.svg"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export 1:1 Vector SVG",
            str(self.root_dir / default_name),
            "SVG Vector Files (*.svg)",
        )
        if file_path:
            out = SVGExporter.export_draft(
                draft=self.current_draft,
                output_path=file_path,
                include_construction=self.canvas_view.layer_visibility.get("construction", True),
                include_seam_allowance=self.canvas_view.layer_visibility.get("seam_allowance", True),
            )
            QMessageBox.information(self, "SVG Export Complete", f"Exported 1:1 scale SVG to:\n{out}")

    def _on_export_dxf(self, mode: str) -> None:
        if not self.current_draft:
            return
        suffix = "AAMA_CLO3D" if mode == "aama" else "Standard_CAD"
        default_name = f"{self.current_draft.block_id}_{self.sizing_manager.active_preset.replace(' ', '')}_{suffix}.dxf"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {suffix} DXF",
            str(self.root_dir / default_name),
            "DXF CAD Files (*.dxf)",
        )
        if file_path:
            out = DXFExporter.export_draft(
                draft=self.current_draft,
                output_path=file_path,
                mode=mode,
            )
            QMessageBox.information(
                self,
                "DXF Export Complete",
                f"Exported {suffix} DXF to:\n{out}",
            )
