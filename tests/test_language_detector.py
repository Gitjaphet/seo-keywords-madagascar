"""Tests du détecteur de langue — exemples réels du lot 'en' contaminé par du français."""

from __future__ import annotations

from seo_keywords.analysis.language_detector import detect_language


def test_detect_language_flags_real_french_artifacts_from_en_batch():
    assert detect_language("excursion en mer à nosy be") == "fr"
    assert detect_language("excursion depuis nosy be") == "fr"
    assert detect_language("excursion de nosy be") == "fr"


def test_detect_language_flags_german():
    assert detect_language("madagaskar reise und rundreise") == "de"
    assert detect_language("warum nach madagaskar reisen") == "de"


def test_detect_language_flags_italian():
    assert detect_language("quanto costa un viaggio in madagascar") == "it"
    assert detect_language("perché andare in madagascar") == "it"


def test_detect_language_returns_none_for_ambiguous_english():
    # Pas de marqueur fort d'une autre langue -> ne tranche pas
    assert detect_language("excursion nosy be") is None
    assert detect_language("madagascar backpacking trip") is None
    assert detect_language("is madagascar safe for tourists") is None


def test_detect_language_ignores_shared_content_words():
    # 'safari' est identique en fr/en/it -> ne doit jamais déclencher une détection
    assert detect_language("safari madagascar") is None
    assert detect_language("best safari madagascar tours") is None


def test_detect_language_returns_none_on_tie():
    # Mot-clé construit artificiellement pour matcher fr et de à égalité (1-1)
    result = detect_language("depuis und madagascar")
    assert result is None