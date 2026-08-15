"""Tests de curation — basés sur les vrais faux positifs trouvés dans la collecte fr."""

from __future__ import annotations

import csv

from seo_keywords.analysis.curation import (
    auto_filter,
    export_for_manual_tagging,
    export_foreign_language_csv,
    load_tagged_csv,
    separate_cross_language,
)
from seo_keywords.storage.models import KeywordRecord


def _record(keyword: str, seed: str = "seed", lang: str = "fr") -> KeywordRecord:
    return KeywordRecord(keyword=keyword, lang=lang, source="google_autocomplete", seed=seed)


def test_auto_filter_flags_competitor_brands():
    records = [
        _record("circuit madagascar tui"),
        _record("circuit madagascar leclerc"),
        _record("voyages bourdon madagascar"),
        _record("excursion nosy be tarif"),  # doit rester
    ]

    result = auto_filter(records)

    competitor_keywords = {r.keyword for r in result.competitor}
    assert "circuit madagascar tui" in competitor_keywords
    assert "circuit madagascar leclerc" in competitor_keywords
    assert "voyages bourdon madagascar" in competitor_keywords
    assert "excursion nosy be tarif" in {r.keyword for r in result.keeper}


def test_auto_filter_detects_wilderness_travel_and_kit_contamination():
    """Régression: wilderness travel = vrai concurrent (Berkeley, circuits
    Madagascar actifs, vérifié web) ; travel kit/set = contamination
    SKIN1004 confirmée (même famille produit que 'centella travel kit')."""
    records = [
        KeywordRecord(
            keyword="madagascar wilderness travel", lang="en",
            source="autocomplete", seed="madagascar trip w",
        ),
        KeywordRecord(
            keyword="madagascar travel kit", lang="en",
            source="autocomplete", seed="madagascar trip k",
        ),
        KeywordRecord(
            keyword="madagascar travel set", lang="en",
            source="autocomplete", seed="madagascar trip s",
        ),
    ]
    result = auto_filter(records)
    competitor_keywords = {r.keyword for r in result.competitor}
    off_topic_keywords = {r.keyword for r in result.off_topic}
    assert "madagascar wilderness travel" in competitor_keywords
    assert "madagascar travel kit" in off_topic_keywords
    assert "madagascar travel set" in off_topic_keywords


def test_auto_filter_flags_off_topic_false_positives():
    records = [
        _record("circuit automobile madagascar"),  # piège: "circuit" = course, pas tourisme
        _record("safari madagascar movie"),  # le film, pas du tourisme
        _record("voyage madagascar apk"),  # une appli
        _record("comment créer une agence de voyage à madagascar"),  # entrepreneur, pas touriste
        _record("tourisme madagascar chiffres"),  # chercheur/journaliste
        _record("excursion catamaran nosy be"),  # doit rester
    ]

    result = auto_filter(records)

    off_topic_keywords = {r.keyword for r in result.off_topic}
    assert "circuit automobile madagascar" in off_topic_keywords
    assert "safari madagascar movie" in off_topic_keywords
    assert "voyage madagascar apk" in off_topic_keywords
    assert "comment créer une agence de voyage à madagascar" in off_topic_keywords
    assert "tourisme madagascar chiffres" in off_topic_keywords
    assert "excursion catamaran nosy be" in {r.keyword for r in result.keeper}


def test_auto_filter_keeps_informational_content_opportunities():
    """Les questions pré-achat (budget, avis, vaccin...) sont du signal, pas du bruit —
    elles ne doivent PAS être filtrées automatiquement."""
    records = [
        _record("voyage madagascar budget"),
        _record("voyage madagascar avis"),
        _record("voyage madagascar vaccin"),
        _record("que faire a nosy be quand il pleut"),
    ]

    result = auto_filter(records)

    assert len(result.keeper) == 4
    assert len(result.competitor) == 0
    assert len(result.off_topic) == 0


def test_auto_filter_never_drops_records_silently():
    """Chaque record doit finir dans exactement un des trois lots — jamais perdu."""
    records = [
        _record("circuit madagascar tui"),
        _record("circuit automobile madagascar"),
        _record("excursion nosy be tarif"),
    ]

    result = auto_filter(records)
    total = len(result.keeper) + len(result.competitor) + len(result.off_topic)

    assert total == len(records)


def test_export_for_manual_tagging_creates_valid_csv(tmp_path):
    records = [
        _record("excursion nosy be tarif", seed="excursion nosy be"),
        _record("que faire a nosy be blog", seed="que faire nosy be"),
    ]
    output = tmp_path / "to_tag.csv"

    export_for_manual_tagging(records, str(output))

    assert output.exists()
    with open(output, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert rows[0]["intent"] == ""  # vide, à remplir par l'humain
    assert set(rows[0].keys()) == {"keyword", "seed", "lang", "intent", "notes"}


def test_load_tagged_csv_reads_only_filled_rows(tmp_path):
    csv_path = tmp_path / "tagged.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["keyword", "seed", "lang", "intent", "notes"])
        writer.writerow(["excursion nosy be tarif", "seed1", "fr", "transactionnel", ""])
        writer.writerow(["que faire a nosy be blog", "seed2", "fr", "informationnel", ""])
        writer.writerow(["pas encore tagué", "seed3", "fr", "", ""])  # ignoré

    tagged = load_tagged_csv(str(csv_path))

    assert tagged == {
        "excursion nosy be tarif": "transactionnel",
        "que faire a nosy be blog": "informationnel",
    }
    assert "pas encore tagué" not in tagged


def test_auto_filter_flags_new_travel_brands():
    """Marques ajoutées après revue du lot en (Jet2, British Airways,
    Virgin, Mercury Holidays, Kensington Tours, Intrepid)."""
    records = [
        _record("madagascar holidays jet2"),
        _record("madagascar holidays british airways"),
        _record("madagascar holidays virgin all inclusive"),
        _record("madagascar mercury holidays"),
        _record("madagascar kensington tours"),
        _record("madagascar tour intrepid"),
    ]

    result = auto_filter(records)

    assert len(result.competitor) == 6
    assert len(result.keeper) == 0


def test_auto_filter_excludes_vanilla_perfume_but_keeps_vanilla_islands():
    records = [
        KeywordRecord(
            keyword="madagascar vanilla travel size", lang="en",
            source="autocomplete", seed="madagascar vanilla",
        ),
        KeywordRecord(
            keyword="madagascar vanilla travel spray", lang="en",
            source="autocomplete", seed="madagascar vanilla",
        ),
        KeywordRecord(
            keyword="madagascar vanilla travel", lang="en",
            source="autocomplete", seed="madagascar vanilla",
        ),
    ]
    result = auto_filter(records)
    off_topic_keywords = {r.keyword for r in result.off_topic}
    keeper_keywords = {r.keyword for r in result.keeper}

    assert "madagascar vanilla travel size" in off_topic_keywords
    assert "madagascar vanilla travel spray" in off_topic_keywords
    assert "madagascar vanilla travel" in keeper_keywords


def test_auto_filter_detects_local_competitor_agencies():
    """Régression: dadamanga (Fort Dauphin, 25 ans, TripAdvisor Traveler's
    Choice) et jangaria (Diego Suarez) sont de vraies agences concurrentes
    trouvées via les needs_review, pas du bruit — vérifié par recherche web."""
    records = [
        KeywordRecord(
            keyword="dadamanga madagascar travel experts", lang="en",
            source="autocomplete", seed="madagascar trip e",
        ),
        KeywordRecord(
            keyword="madagascar jangaria travel", lang="en",
            source="autocomplete", seed="madagascar trip j",
        ),
    ]
    result = auto_filter(records)
    competitor_keywords = {r.keyword for r in result.competitor}
    assert "dadamanga madagascar travel experts" in competitor_keywords
    assert "madagascar jangaria travel" in competitor_keywords

def test_auto_filter_flags_public_holidays_as_off_topic():
    """'national/official/major holidays' = calendrier RH, pas une recherche
    de voyage -> doit être exclu, pas confondu avec 'holidays' au sens vacances."""
    records = [
        _record("madagascar national holidays"),
        _record("madagascar national holidays 2026"),
        _record("madagascar official holidays"),
        _record("madagascar major holidays"),
        _record("madagascar holidays in december"),  # doit rester (vacances, pas jours fériés)
    ]

    result = auto_filter(records)

    off_topic_keywords = {r.keyword for r in result.off_topic}
    assert "madagascar national holidays" in off_topic_keywords
    assert "madagascar national holidays 2026" in off_topic_keywords
    assert "madagascar official holidays" in off_topic_keywords
    assert "madagascar major holidays" in off_topic_keywords
    assert "madagascar holidays in december" in {r.keyword for r in result.keeper}


def test_separate_cross_language_flags_real_french_in_en_batch():
    """Cas réel: 'excursion en mer à nosy be' collecté sous lang=en mais
    en réalité français -> doit être séparé, pas laissé dans le lot en."""
    records = [
        _record("excursion en mer à nosy be", seed="excursion nosy be", lang="en"),
        _record("excursion depuis nosy be", seed="excursion nosy be", lang="en"),
        _record("is madagascar safe for tourists", seed="madagascar trip", lang="en"),
    ]

    same_lang, foreign = separate_cross_language(records, declared_lang="en")

    assert len(same_lang) == 1
    assert same_lang[0].keyword == "is madagascar safe for tourists"

    assert len(foreign) == 2
    detected_langs = {lang for _, lang in foreign}
    assert detected_langs == {"fr"}


def test_separate_cross_language_never_drops_records():
    records = [
        _record("excursion en mer à nosy be", lang="en"),
        _record("madagascar backpacking trip", lang="en"),
    ]

    same_lang, foreign = separate_cross_language(records, declared_lang="en")

    assert len(same_lang) + len(foreign) == len(records)


def test_export_foreign_language_csv_creates_valid_csv(tmp_path):
    records = [_record("excursion depuis nosy be", seed="excursion nosy be", lang="en")]
    _, foreign = separate_cross_language(records, declared_lang="en")
    output = tmp_path / "foreign.csv"

    export_foreign_language_csv(foreign, str(output))

    with open(output, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["detected_lang"] == "fr"
    assert rows[0]["declared_lang"] == "en"
    assert rows[0]["keyword"] == "excursion depuis nosy be"