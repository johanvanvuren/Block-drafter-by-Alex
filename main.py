"""
Entry point for "Block Drafter by Alex" — Custom Digital Garment Block (Sloper) Application.

Usage:
  1. Launch Desktop GUI (PySide6):
       python main.py
  2. Run CLI Headless Verification & Sample Export Suite:
       python main.py --headless-demo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.core.drafting_engine import DraftingEngine
from src.core.sizing import SizingManager
from src.exporters.dxf_exporter import DXFExporter
from src.exporters.pdf_exporter import PDFExporter
from src.exporters.svg_exporter import SVGExporter
from src.layout.nesting_engine import PrintLayoutEngine


def run_headless_demo() -> int:
    """Solve both pre-loaded blocks, print waste comparison tables, and generate sample exports."""
    root = Path(__file__).resolve().parent
    engine = DraftingEngine()
    sizing = SizingManager(root / "data" / "sizes" / "uk_metric.json")
    layout_engine = PrintLayoutEngine()
    exports_dir = root / "exports"
    exports_dir.mkdir(exist_ok=True)

    for block_path in sorted((root / "data" / "blocks").glob("*.json")):
        spec = engine.load_block_file(block_path)
        meas = sizing.select_preset("UK 10")
        draft = engine.solve(spec, custom_measurements=meas)

        print(f"\n{'=' * 74}")
        print(f"SOLVED BLOCK: {draft.name} (Size: {sizing.active_preset})")
        print(f"{'=' * 74}")
        print(f"Points solved: {len(draft.points)} | Construction curves: {len(draft.construction_curves)} | Pieces: {len(draft.pieces)}")
        for piece in draft.pieces:
            print(
                f"  - Piece '{piece.name}': Net Area = {piece.net_area_cm2:.1f} cm², "
                f"Cut Area (with {piece.seam_allowance_cm:.1f}cm SA) = {piece.cut_area_cm2:.1f} cm²"
            )

        comparisons = layout_engine.compare_all_formats(draft, rotation_mode="cardinal_90")
        print("\nPrint Optimization & Waste Comparison:")
        print(f"  {'Format':<42} | {'Pages/Len':<14} | {'Paper Area':<12} | {'Waste %':<8}")
        print(f"  {'-' * 42}-+-{'-' * 14}-+-{'-' * 12}-+-{'-' * 8}")
        for fmt_id, res in comparisons.items():
            pg = (
                f"{res.pages[0].paper_height_cm:.1f} cm roll"
                if res.paper_format.is_roll
                else f"{res.active_page_count} page(s)"
            )
            print(
                f"  {res.paper_format.name:<42} | {pg:<14} | "
                f"{res.total_paper_area_cm2:>8.0f} cm² | {res.waste_percentage:>6.1f}%"
            )

        # Export sample files
        stem = f"{draft.block_id}_UK10"
        svg_path = SVGExporter.export_draft(draft, exports_dir / f"{stem}.svg")
        dxf_aama = DXFExporter.export_draft(draft, exports_dir / f"{stem}_AAMA_CLO3D.dxf", mode="aama")
        dxf_cad = DXFExporter.export_draft(draft, exports_dir / f"{stem}_Standard_CAD.dxf", mode="standard_cad")
        pdf_a4 = PDFExporter.export_layout(draft, comparisons["A4"], exports_dir / f"{stem}_A4_Tiled.pdf")
        pdf_a0 = PDFExporter.export_layout(draft, comparisons["A0"], exports_dir / f"{stem}_A0_Plotter.pdf")

        print(f"\nGenerated 1:1 Exports in {exports_dir}:")
        print(f"  * SVG:       {svg_path.name}")
        print(f"  * DXF AAMA:  {dxf_aama.name}")
        print(f"  * DXF CAD:   {dxf_cad.name}")
        print(f"  * PDF A4:    {pdf_a4.name}")
        print(f"  * PDF A0:    {pdf_a0.name}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Block Drafter by Alex — Garment Block Drafting Studio")
    parser.add_argument(
        "--headless-demo",
        action="store_true",
        help="Run headless solver, print format waste comparison, and export sample PDF/SVG/DXF files.",
    )
    args = parser.parse_args()

    if args.headless_demo:
        return run_headless_demo()

    from PySide6.QtWidgets import QApplication
    from src.ui.main_window import BlockDrafterMainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Block Drafter by Alex")
    win = BlockDrafterMainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
