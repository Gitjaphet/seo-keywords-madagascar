"""Tests du repository — utilise une base SQLite temporaire, jamais la vraie."""

from __future__ import annotations

from seo_keywords.collectors.base import KeywordSuggestion
from seo_keywords.storage.repository import KeywordRepository


def test_save_suggestions_inserts_new_keywords(tmp_path):
    repo = KeywordRepository(str(tmp_path / "test.db"))
    suggestions = [
        KeywordSuggestion(keyword="excursion nosy be prix", source="google_autocomplete",
                           lang="fr", seed="excursion nosy be"),
        KeywordSuggestion(keyword="excursion nosy be journée", source="google_autocomplete",
                           lang="fr", seed="excursion nosy be"),
    ]

    inserted = repo.save_suggestions(suggestions)

    assert inserted == 2
    assert len(repo.get_all_keywords(lang="fr")) == 2


def test_save_suggestions_deduplicates_on_second_run(tmp_path):
    repo = KeywordRepository(str(tmp_path / "test.db"))
    suggestions = [
        KeywordSuggestion(keyword="excursion nosy be prix", source="google_autocomplete",
                           lang="fr", seed="excursion nosy be"),
    ]

    first_run = repo.save_suggestions(suggestions)
    second_run = repo.save_suggestions(suggestions)  # même donnée, relancée

    assert first_run == 1
    assert second_run == 0  # rien de nouveau
    assert len(repo.get_all_keywords(lang="fr")) == 1


def test_get_all_keywords_filters_by_lang(tmp_path):
    repo = KeywordRepository(str(tmp_path / "test.db"))
    repo.save_suggestions([
        KeywordSuggestion(keyword="excursion", source="google_autocomplete", lang="fr", seed="x"),
        KeywordSuggestion(keyword="excursion", source="google_autocomplete", lang="en", seed="x"),
    ])

    fr_keywords = repo.get_all_keywords(lang="fr")
    en_keywords = repo.get_all_keywords(lang="en")

    assert len(fr_keywords) == 1
    assert len(en_keywords) == 1
    assert fr_keywords[0].lang == "fr"


def test_save_and_get_seasonality(tmp_path):
    repo = KeywordRepository(str(tmp_path / "test.db"))
    repo.save_seasonality("excursion nosy be", geo="", monthly_scores={1: 10.0, 4: 55.0})

    records = repo.get_seasonality(geo="")

    assert len(records) == 2
    months = {r.month for r in records}
    assert months == {1, 4}
