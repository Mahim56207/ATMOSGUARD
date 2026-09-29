"""make_diagrams.py: the slide diagrams are well-formed SVG and say what the pipeline does."""
import xml.etree.ElementTree as ET

import make_diagrams as md


def test_every_diagram_is_well_formed_svg():
    for name, fn in md.DIAGRAMS.items():
        root = ET.fromstring(fn())
        assert root.tag.endswith("svg"), name
        assert root.attrib["viewBox"].startswith("0 0 ")


def test_the_pipeline_diagram_names_every_layer_and_verdict():
    text = md.pipeline()
    for word in ("L0 physics", "L1 health", "L2 normality", "L3 multivariate", "Timing", "Fusion", "VALID", "WEATHER", "SUSPECT", "FAULT"):
        assert word in text


def test_wrap_keeps_lines_inside_the_width():
    rows = md.wrap(["a long sentence that has to be broken into several shorter lines to fit"], 200, 15)
    assert len(rows) > 1 and all(len(r) * 15 * 0.57 <= 200 + 15 for r in rows)
