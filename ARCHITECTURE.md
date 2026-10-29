# Block Drafter by Alex — System Architecture & Specification

A local native desktop application built with **Python 3.12**, **PySide6 (Qt 6)**, **ezdxf**, and **ReportLab** that automates the creation of custom digital garment blocks (slopers), optimizes print layouts for minimum paper waste, and exports 1:1 scale patterns in **PDF**, **SVG**, and **AAMA/ASTM + Standard CAD DXF** formats.

---

## 1. Modular System Architecture

```
Block drafter by Alex/
├── main.py                              # Desktop GUI launcher & CLI headless verification suite
├── requirements.txt                     # PySide6, ezdxf, reportlab, pytest
├── schemas/
│   └── block_instruction.schema.json    # Canonical JSON Schema (v1.0) for Block Instructions
├── data/
│   ├── sizes/
│   │   └── uk_metric.json               # Pre-loaded UK 8, 10, 12, 14, 16 standard metric sizes (cm)
│   └── blocks/
│       ├── basic_skirt_block.json       # Parametric Back & Front Skirt Block with darts & hip curves
│       └── basic_bodice_block.json      # Parametric Back & Front Bodice Block with scye & bust darts
├── src/
│   ├── core/
│   │   ├── math_parser.py               # Safe AST formula parser, unit normalizer & natural phrase parser
│   │   ├── notebook_compiler.py         # Option 3 Textbook Notebook compiler/decompiler & Option 5 Smart Formula Suggester
│   │   ├── geometry.py                  # 2D intersections, Beziers, Catmull-Rom splines, seam allowance offset
│   │   ├── drafting_engine.py           # Two-layer parametric solver (Layer 1 Construction + Layer 2 Pieces)
│   │   └── sizing.py                    # Standard size preset & bespoke measurement override manager
│   ├── layout/
│   │   └── nesting_engine.py            # 2D nesting, multi-format waste calculator & home-printer tiler
│   ├── exporters/
│   │   ├── pdf_exporter.py              # 1:1 ReportLab PDF exporter (A0/36" Roll & Tiled A4/Letter + Crosshairs)
│   │   ├── svg_exporter.py              # 1:1 physical mm SVG exporter for Adobe Illustrator
│   │   └── dxf_exporter.py              # Dual-mode ezdxf exporter (AAMA/ASTM D6673 & Standard Layered CAD)
│   └── ui/
│       ├── canvas_view.py               # Interactive QGraphicsView 2D CAD viewport (Light/Dark, Image Trace, Click-to-Trace)
│       ├── block_creator_dialog.py      # Full-screen Modal Block Creator Studio (Option 3 Notebook + Option 1 + Option 5)
│       └── main_window.py               # Studio UI: Sizing Dock, CAD Viewport, Theme Switcher & Export Suite
└── tests/
    └── test_engine.py                   # Pytest suite covering math, geometry, blocks, nesting, and exports
```

---

## 2. Two-Layer "Block Instruction" Data Structure

Each garment block is stored as a human-readable JSON file validated against `schemas/block_instruction.schema.json`:

1. **`required_measurements` & `derived_variables`**:
   - Declares required body measurements (`waist`, `hips`, `bust`, `nape_to_waist`, etc.) and intermediate variables (`hip_ease = "1.5cm"`, `back_waist_span = "waist / 4 + back_dart_intake + 0.25cm"`).
2. **Layer 1 — `points` & `construction`**:
   - Evaluates ordered parametric points (`absolute`, `offset`, `coord_ref`, `polar`, `line_interp`, `perpendicular`, `line_intersection`, `circle_line_intersection`, `circle_circle_intersection`).
   - Constructs guidelines, `cubic_bezier` curves (with polar tangent handles), and smooth `spline` curves through multiple points.
3. **Layer 2 — `pieces` (Extracted Cuttable Pattern Pieces)**:
   - Traces closed boundary loops from Layer 1 points and curves.
   - Attaches `internal_lines` (waist/bust darts, balance lines), `grainline` vectors, perpendicular inward `notches`, and automatically offsets the closed polygon outward by `seam_allowance_cm`.

---

## 3. Running the Application

### Install Dependencies
```powershell
pip install -r requirements.txt
```

### Launch the PySide6 Desktop Studio
```powershell
python main.py
```

### Run Headless Verification & Generate Sample Exports
```powershell
python main.py --headless-demo
```

### Run Automated Test Suite
```powershell
pytest
```
