"""
Unit and integration tests for Block Drafter by Alex:
- MathExpressionParser & natural instruction sentence parsing
- 2D Geometry intersections, splines, polygon area, and seam allowance offsetting
- Two-layer DraftingEngine with Basic Skirt & Bodice blocks across UK 8-16 sizes
- PrintLayoutEngine nesting, tiling, and waste percentage calculations
- PDF, SVG, and AAMA/Standard DXF exporters
"""

from __future__ import annotations

from pathlib import Path

from src.core.drafting_engine import DraftingEngine
from src.core.geometry import (
    Point2D,
    circle_circle_intersection,
    circle_line_intersection,
    line_line_intersection,
    offset_closed_polygon,
    polygon_area,
)
from src.core.math_parser import MathExpressionParser, parse_natural_instruction_line
from src.core.notebook_compiler import (
    NotebookCompiler,
    block_spec_to_notebook_script,
    suggest_parametric_formulas,
)
from src.core.sizing import SizingManager
from src.exporters.dxf_exporter import DXFExporter
from src.exporters.pdf_exporter import PDFExporter
from src.exporters.svg_exporter import SVGExporter
from src.layout.nesting_engine import PrintLayoutEngine


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_math_expression_parser_and_units() -> None:
    parser = MathExpressionParser(
        variables={"Waist": 68.0, "Nape to Waist": 41.0},
        points={"A": (0.0, 0.0), "B": (18.0, 0.0)},
        base_unit="cm",
    )
    assert abs(parser.evaluate("Waist / 4 + 1cm") - 18.0) < 1e-6
    assert abs(parser.evaluate("Nape to Waist + 15mm") - 42.5) < 1e-6
    assert abs(parser.evaluate("dist(A, B) + 2in") - (18.0 + 5.08)) < 1e-6
    assert abs(parser.evaluate("B.x * 2") - 36.0) < 1e-6


def test_natural_language_instruction_parser() -> None:
    p_a = parse_natural_instruction_line("Point A is the origin (0,0).")
    assert p_a["id"] == "A" and p_a["type"] == "absolute"

    p_b = parse_natural_instruction_line("Point B is (Waist / 4 + 1cm) on the X-axis from Point A.")
    assert p_b["id"] == "B" and p_b["type"] == "offset" and p_b["from"] == "A"
    assert p_b["dx"] == "Waist / 4 + 1cm" and p_b["dy"] == "0"

    p_c = parse_natural_instruction_line("Point C is (Nape to Waist) on the Y-axis from Point B.")
    assert p_c["id"] == "C" and p_c["type"] == "offset" and p_c["from"] == "B"
    assert p_c["dy"] == "Nape to Waist"


def test_geometry_intersections_and_seam_allowance() -> None:
    # Line-line intersection at (5, 5)
    p = line_line_intersection(
        Point2D(0, 5), Point2D(10, 5),
        Point2D(5, 0), Point2D(5, 10),
    )
    assert abs(p.x - 5.0) < 1e-6 and abs(p.y - 5.0) < 1e-6

    # Circle-line intersection
    cl = circle_line_intersection(
        Point2D(0, 0), 10.0,
        Point2D(0, 0), Point2D(20, 0),
        select="max_x",
    )
    assert abs(cl.x - 10.0) < 1e-6 and abs(cl.y) < 1e-6

    # Circle-circle intersection
    cc = circle_circle_intersection(
        Point2D(0, 0), 5.0,
        Point2D(6, 0), 5.0,
        select="max_y",
    )
    assert abs(cc.x - 3.0) < 1e-6 and abs(cc.y - 4.0) < 1e-6

    # 10x10 square offset by 1cm outward -> 12x12 square (area = 144 cm^2)
    sq = [Point2D(0, 0), Point2D(10, 0), Point2D(10, 10), Point2D(0, 10)]
    assert abs(polygon_area(sq) - 100.0) < 1e-6
    sa_sq = offset_closed_polygon(sq, 1.0)
    assert abs(polygon_area(sa_sq) - 144.0) < 1e-4


def test_skirt_and_bodice_blocks_across_uk_sizes(tmp_path: Path) -> None:
    engine = DraftingEngine()
    sizing = SizingManager(ROOT_DIR / "data" / "sizes" / "uk_metric.json")
    layout_engine = PrintLayoutEngine()

    for block_file in ["basic_skirt_block.json", "basic_bodice_block.json"]:
        spec = engine.load_block_file(ROOT_DIR / "data" / "blocks" / block_file)
        for size_name in ["UK 8", "UK 10", "UK 12", "UK 14", "UK 16"]:
            meas = sizing.select_preset(size_name)
            draft = engine.solve(spec, custom_measurements=meas)
            assert len(draft.pieces) == 2
            for piece in draft.pieces:
                assert piece.net_area_cm2 > 100.0
                assert piece.cut_area_cm2 > piece.net_area_cm2

        # Test layout optimization & exports on UK 12
        comparisons = layout_engine.compare_all_formats(draft, rotation_mode="cardinal_90")
        assert set(comparisons.keys()) == {"A0", "ROLL_36", "A4", "US_LETTER"}
        for res in comparisons.values():
            assert 0.0 < res.waste_percentage < 100.0
            assert res.total_paper_area_cm2 > res.pattern_area_cm2

        svg_out = SVGExporter.export_draft(draft, tmp_path / f"{draft.block_id}.svg")
        dxf_aama = DXFExporter.export_draft(draft, tmp_path / f"{draft.block_id}_aama.dxf", mode="aama")
        dxf_cad = DXFExporter.export_draft(draft, tmp_path / f"{draft.block_id}_cad.dxf", mode="standard_cad")
        pdf_out = PDFExporter.export_layout(draft, comparisons["A4"], tmp_path / f"{draft.block_id}_a4.pdf")

        assert svg_out.exists() and svg_out.stat().st_size > 500
        assert dxf_aama.exists() and dxf_aama.stat().st_size > 200
        assert dxf_cad.exists() and dxf_cad.stat().st_size > 200
        assert pdf_out.exists() and pdf_out.stat().st_size > 500


def test_notebook_compiler_and_roundtrip() -> None:
    engine = DraftingEngine()
    sizing = SizingManager(ROOT_DIR / "data" / "sizes" / "uk_metric.json")
    meas = sizing.select_preset("UK 10")

    script = """
    # Pattern Cutting Textbook Script Test
    Var ease = 1.5cm
    1. Point A is the origin (0, 0)
    2. From A go right (hips / 4 + ease) to B
    3. From A go down (skirt_length) to C
    4. Point D is coord (B.x, C.y)
    5. Midpoint of A and B is M
    6. From M go down (12cm) to Apex
    7. Point D_L is distance (dist(A, M) - 1.5cm) along A -> B
    8. Point D_R is distance (dist(A, M) + 1.5cm) along A -> B
    9. Point G_Top is offset (8cm, 6cm) from A
    10. From G_Top go down (25cm) to G_Bot
    Smooth curve top_curve through A, M, B
    Piece test_panel "Test Panel" (cut 2, sa 1.0cm): A -> D_L -> D_R -> B -> D -> C -> A
    Dart on test_panel: D_L -> Apex -> D_R
    Grainline on test_panel: G_Top -> G_Bot
    Notch on test_panel at B along B -> D (count 2)
    """

    spec, diags = NotebookCompiler.compile_script(script)
    assert not diags
    draft = engine.solve(spec, custom_measurements=meas)
    assert len(draft.points) == 10
    assert len(draft.pieces) == 1
    assert draft.pieces[0].net_area_cm2 > 500.0

    # Round-trip decompile -> compile on preloaded skirt block
    skirt_spec = engine.load_block_file(ROOT_DIR / "data" / "blocks" / "basic_skirt_block.json")
    decompiled = block_spec_to_notebook_script(skirt_spec)
    recompiled_spec, r_diags = NotebookCompiler.compile_script(
        decompiled,
        base_metadata=skirt_spec,
    )
    assert not r_diags
    re_draft = engine.solve(recompiled_spec, custom_measurements=meas)
    assert len(re_draft.pieces) == 2


def test_smart_parametric_formula_suggester() -> None:
    measurements = {"waist": 66.0, "hips": 90.0, "nape_to_waist": 40.7}
    # 66 / 4 + 1.0 = 17.5 cm
    suggestions = suggest_parametric_formulas(17.5, measurements)
    formulas = [expr for expr, _ in suggestions]
    assert any("waist / 4 + 1.00cm" in f for f in formulas)

