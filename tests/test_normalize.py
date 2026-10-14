"""Arabic number normalization: paren negatives split by bidi controls, Eastern
digits, thousands separators — `(‪)5,991,288` → `-5991288` and friends."""

from new_horizons.shared.text.arabic import (
    clean_arabic,
    index_normalize,
    normalize_numbers,
    parse_amount,
)


def test_paren_negative_with_bidi_control():
    # A paren pair split by a bidi control char.
    assert normalize_numbers("(‪)5,991,288") == "-5991288"


def test_paren_negative_plain():
    assert normalize_numbers("(3,223,114)") == "-3223114"


def test_paren_negative_reversed_and_double_close():
    # Shapes right-to-left extraction scatters around a negative figure.
    assert normalize_numbers(") 7,022,634 )") == "-7022634"
    assert normalize_numbers(")5,991,288(") == "-5991288"


def test_positive_number_commas_stripped():
    assert normalize_numbers("4,128,996") == "4128996"


def test_eastern_arabic_digits():
    assert normalize_numbers("١٢٣٤٥") == "12345"
    assert normalize_numbers("(٥٬٩٩١٫٥)") != "(٥٬٩٩١٫٥)"  # translated + signed


def test_tatweel_and_diacritics_stripped():
    assert clean_arabic("التـــأمين") == "التأمين"
    assert clean_arabic("مُدَقَّقَة") == "مدققة"


def test_index_only_unification():
    # Alef variants + ta-marbuta unify in the INDEX form only.
    assert index_normalize("إيرادات") == "ايرادات"
    assert index_normalize("مدققة") == "مدققه"
    # Display cleaning must NOT unify letters.
    assert clean_arabic("إيرادات") == "إيرادات"


def test_parse_amount():
    assert parse_amount("4,128,996") == 4128996
    assert parse_amount("(3,552,516)") == -3552516
    assert parse_amount("إيضاح") is None
