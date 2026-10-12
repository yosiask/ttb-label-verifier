from app.core.normalize import clean, normalize, normalize_whitespace


def test_case_and_apostrophes_ignored():
    assert normalize("STONE'S THROW") == normalize("Stone’s Throw") == "stones throw"


def test_punctuation_and_whitespace():
    assert normalize("  Old  Tom-Distillery,\nBardstown ") == "old tom distillery bardstown"


def test_clean_keeps_case_and_punctuation():
    assert clean("Stone’s   Throw—Co.") == "Stone's Throw-Co."


def test_warning_whitespace_only():
    assert normalize_whitespace("GOVERNMENT  WARNING:\n(1) imp-\nairs") == "GOVERNMENT WARNING: (1) impairs"
    # case is never touched
    assert normalize_whitespace("Government Warning:") == "Government Warning:"
