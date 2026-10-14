"""Normalization entry point for the ingest pipeline.

The implementation lives in `shared.text.arabic` so the kb_search tool can
normalize queries with the exact same rules at retrieval time. Index-only
transforms (alef variants, ta-marbuta) never touch display text.
"""

from new_horizons.shared.text.arabic import (  # noqa: F401
    BIDI,
    clean_arabic,
    detect_lang,
    index_normalize,
    normalize_numbers,
    parse_amount,
    strip_bidi,
)
