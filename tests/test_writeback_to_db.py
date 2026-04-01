import writeback_to_db


def test_parse_number_street_returns_text_number():
    parsed = writeback_to_db._parse_number_street("440 College St")
    assert parsed == ("440", "College St")


def test_parse_number_street_handles_suffix_and_whitespace():
    parsed = writeback_to_db._parse_number_street("  59A   Kensington   Ave ")
    assert parsed == ("59", "Kensington Ave")

