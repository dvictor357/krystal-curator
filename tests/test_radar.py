from krystal_curator.radar import render_radar


def test_radar_dimensions_and_labels():
    vals = [
        ("YLD", 0.9),
        ("TURN", 0.5),
        ("CONS", 0.7),
        ("LIVE", 1.0),
        ("DEPTH", 0.1),
        ("RISK", 0.3),
    ]
    out = render_radar(vals, cols=36, rows=13, show_values=False)
    lines = out.plain.split("\n")
    assert len(lines) == 13
    assert all(len(line) == 36 for line in lines)
    for label, _ in vals:
        assert label in out.plain
    assert any("⠀" <= ch <= "⣿" for ch in out.plain)  # braille drawn


def test_radar_clamps_out_of_range():
    out = render_radar([("A", 5.0), ("B", -1.0), ("C", 0.5)], cols=20, rows=9)
    assert "A 5.00" in out.plain
