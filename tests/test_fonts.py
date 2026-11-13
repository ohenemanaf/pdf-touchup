from pdf_touchup.fonts import FAMILIES, font_path, load_font, missing_glyphs


def _absent_char():
    font = load_font("serif")
    return next(c for c in ("₵", "𝔄", "☃") if not font.has_glyph(ord(c)))


def test_font_paths_exist():
    for family in FAMILIES:
        assert font_path(family).is_file()


def test_missing_glyphs():
    font = load_font("serif")
    assert missing_glyphs(font, "Kwame Asante") == []
    c = _absent_char()
    assert missing_glyphs(font, f"GH{c} 50 {c}") == [c]


def test_load_font_prefers_buffer():
    buf = font_path("mono").read_bytes()
    assert "Mono" in load_font("serif", buffer=buf).name
