"""Tests de l'analyse de saisonnalité."""

from __future__ import annotations

import csv

from seo_keywords.analysis.seasonality import (
    aggregate_by_season,
    export_monthly_csv,
    export_season_summary_csv,
)
from seo_keywords.config import Season
from seo_keywords.storage.models import SeasonalityRecord


def _make_records() -> list[SeasonalityRecord]:
    """Un mot-clé avec un score fort en haute saison, faible en saison cyclonique."""
    records = []
    scores = {1: 10, 2: 12, 3: 15, 4: 50, 5: 55, 6: 60, 7: 65, 8: 70, 9: 68, 10: 50, 11: 45, 12: 20}
    for month, score in scores.items():
        records.append(
            SeasonalityRecord(
                keyword="excursion nosy be", geo="", month=month, interest_score=score
            )
        )
    return records


def test_season_from_month_classification():
    assert Season.from_month(1) == Season.SAISON_CYCLONIQUE
    assert Season.from_month(2) == Season.SAISON_CYCLONIQUE
    assert Season.from_month(3) == Season.SAISON_CYCLONIQUE
    assert Season.from_month(4) == Season.HAUTE_SAISON
    assert Season.from_month(12) == Season.HAUTE_SAISON


def test_aggregate_by_season_computes_correct_averages():
    records = _make_records()
    result = aggregate_by_season(records)

    assert "excursion nosy be" in result
    scores = result["excursion nosy be"]

    expected_cyclonic = round((10 + 12 + 15) / 3, 2)
    expected_high = round((50 + 55 + 60 + 65 + 70 + 68 + 50 + 45 + 20) / 9, 2)

    assert scores[Season.SAISON_CYCLONIQUE] == expected_cyclonic
    assert scores[Season.HAUTE_SAISON] == expected_high
    assert scores[Season.HAUTE_SAISON] > scores[Season.SAISON_CYCLONIQUE]


def test_export_monthly_csv_writes_all_months(tmp_path):
    records = _make_records()
    output = tmp_path / "monthly.csv"

    export_monthly_csv(records, str(output))

    assert output.exists()
    with open(output, encoding="utf-8") as f:
        rows = list(csv.reader(f))

    assert rows[0] == ["keyword", "Jan", "Fév", "Mar", "Avr", "Mai", "Juin",
                        "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
    assert rows[1][0] == "excursion nosy be"
    assert len(rows[1]) == 13  # keyword + 12 mois


def test_export_season_summary_csv(tmp_path):
    records = _make_records()
    output = tmp_path / "summary.csv"

    export_season_summary_csv(records, str(output))

    assert output.exists()
    with open(output, encoding="utf-8") as f:
        rows = list(csv.reader(f))

    assert rows[0] == ["keyword", "haute_saison", "saison_cyclonique"]
    assert rows[1][0] == "excursion nosy be"
    haute_saison_val = float(rows[1][1])
    saison_cyclonique_val = float(rows[1][2])
    assert haute_saison_val > saison_cyclonique_val
