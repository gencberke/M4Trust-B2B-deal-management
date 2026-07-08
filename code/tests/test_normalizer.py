from document_parser.normalizer import MarkdownNormalizer


def test_collapses_extra_blank_lines():
    text = "Madde 1\n\n\n\nMadde 2"
    assert MarkdownNormalizer().normalize(text) == "Madde 1\n\nMadde 2"


def test_collapses_repeated_spaces():
    text = "Bu   bir    test   cumlesidir."
    assert MarkdownNormalizer().normalize(text) == "Bu bir test cumlesidir."


def test_strips_leading_trailing_whitespace_per_line():
    text = "  Madde 1  \n  icerik  "
    assert MarkdownNormalizer().normalize(text) == "Madde 1\nicerik"


def test_strips_control_characters():
    text = "Merhaba\x0cDunya"
    assert MarkdownNormalizer().normalize(text) == "MerhabaDunya"


def test_strips_bom():
    text = chr(0xFEFF) + "Madde 1"
    assert MarkdownNormalizer().normalize(text) == "Madde 1"


def test_empty_input_returns_empty_string():
    assert MarkdownNormalizer().normalize("   \n\n  ") == ""
