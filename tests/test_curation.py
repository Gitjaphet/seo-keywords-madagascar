"""Tests de curation — basés sur les vrais faux positifs trouvés dans la collecte fr."""

from __future__ import annotations

import csv

from seo_keywords.analysis.curation import auto_filter, export_for_manual_tagging, load_tagged_csv
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
