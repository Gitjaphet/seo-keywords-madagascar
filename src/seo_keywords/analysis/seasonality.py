"""Agrège les scores de saisonnalité par mois et par saison touristique."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from seo_keywords.config import Season
from seo_keywords.storage.models import SeasonalityRecord

MONTH_LABELS_FR = [
    "Jan", "Fév", "Mar", "Avr", "Mai", "Juin",
    "Juil", "Août", "Sep", "Oct", "Nov", "Déc",
]


def aggregate_by_season(records: list[SeasonalityRecord]) -> dict[str, dict[Season, float]]:
    """Pour chaque mot-clé, moyenne l'intérêt sur haute saison vs saison cyclonique."""
    by_keyword_month: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in records:
        by_keyword_month[r.keyword][r.month].append(r.interest_score)

    result: dict[str, dict[Season, float]] = {}
    for keyword, months in by_keyword_month.items():
        season_scores: dict[Season, list[float]] = defaultdict(list)
        for month, scores in months.items():
            season = Season.from_month(month)
            season_scores[season].extend(scores)

        result[keyword] = {
            season: round(sum(scores) / len(scores), 2)
            for season, scores in season_scores.items()
            if scores
        }
    return result


def export_monthly_csv(records: list[SeasonalityRecord], output_path: str) -> None:
    """Exporte un CSV: keyword, Jan, Fév, ..., Déc — un mot-clé par ligne."""
    by_keyword_month: dict[str, dict[int, float]] = defaultdict(dict)
    for r in records:
        by_keyword_month[r.keyword][r.month] = r.interest_score

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["keyword", *MONTH_LABELS_FR])
        for keyword, months in sorted(by_keyword_month.items()):
            row = [keyword] + [months.get(m, 0) for m in range(1, 13)]
            writer.writerow(row)


def export_season_summary_csv(records: list[SeasonalityRecord], output_path: str) -> None:
    """Exporte un CSV résumé: keyword, haute_saison, saison_cyclonique."""
    aggregated = aggregate_by_season(records)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["keyword", Season.HAUTE_SAISON.value, Season.SAISON_CYCLONIQUE.value])
        for keyword, scores in sorted(aggregated.items()):
            writer.writerow(
                [
                    keyword,
                    scores.get(Season.HAUTE_SAISON, 0),
                    scores.get(Season.SAISON_CYCLONIQUE, 0),
                ]
            )
