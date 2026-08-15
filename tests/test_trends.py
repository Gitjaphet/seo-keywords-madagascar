"""Tests du collecteur Trends — pytrends est mocké, aucun appel réseau réel."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from seo_keywords.collectors.trends import TrendsCollector


def _fake_interest_over_time_df(keyword: str) -> pd.DataFrame:
    """Simule un df pytrends: index datetime mensuel, colonne = mot-clé + isPartial."""
    dates = pd.date_range("2024-01-01", periods=12, freq="MS")
    values = [10, 12, 15, 40, 55, 60, 65, 70, 68, 50, 45, 20]  # creux Jan-Mar, pic Avr-Déc
    df = pd.DataFrame({keyword: values, "isPartial": [False] * 12}, index=dates)
    return df


@patch("seo_keywords.collectors.trends.TrendReq")
def test_monthly_averages_computes_correct_shape(mock_trendreq_cls):
    mock_instance = MagicMock()
    mock_trendreq_cls.return_value = mock_instance
    mock_instance.interest_over_time.return_value = _fake_interest_over_time_df("excursion nosy be")

    collector = TrendsCollector()
    result = collector.monthly_averages(["excursion nosy be"], geo="")

    assert "excursion nosy be" in result
    monthly = result["excursion nosy be"]
    assert set(monthly.keys()) == set(range(1, 13))
    # Vérifie le pattern attendu: saison cyclonique (Jan-Mar) < haute saison (Avr-Déc)
    cyclonic_avg = sum(monthly[m] for m in (1, 2, 3)) / 3
    high_season_avg = sum(monthly[m] for m in range(4, 13)) / 9
    assert cyclonic_avg < high_season_avg


@patch("seo_keywords.collectors.trends.TrendReq")
def test_monthly_averages_handles_empty_dataframe(mock_trendreq_cls):
    mock_instance = MagicMock()
    mock_trendreq_cls.return_value = mock_instance
    mock_instance.interest_over_time.return_value = pd.DataFrame()

    collector = TrendsCollector()
    result = collector.monthly_averages(["mot inexistant"], geo="")

    assert result == {}


@patch("seo_keywords.collectors.trends.TrendReq")
def test_monthly_averages_handles_exception_gracefully(mock_trendreq_cls):
    mock_instance = MagicMock()
    mock_trendreq_cls.return_value = mock_instance
    mock_instance.build_payload.side_effect = Exception("rate limited")

    collector = TrendsCollector()
    # Ne doit jamais lever d'exception : retourne un dict vide (ou partiel)
    result = collector.monthly_averages(["excursion nosy be"], geo="")

    assert result == {}


@patch("seo_keywords.collectors.trends.TrendReq")
def test_monthly_averages_batches_over_five_keywords(mock_trendreq_cls):
    mock_instance = MagicMock()
    mock_trendreq_cls.return_value = mock_instance

    keywords = [f"kw{i}" for i in range(7)]  # 7 mots-clés -> 2 lots (5 + 2)

    def fake_iot():
        # Retourne un df pour le lot courant, basé sur build_payload appelé juste avant
        called_kw_lists = [c.args[0] for c in mock_instance.build_payload.call_args_list]
        current_batch = called_kw_lists[-1]
        dates = pd.date_range("2024-01-01", periods=3, freq="MS")
        data = {kw: [10, 20, 30] for kw in current_batch}
        data["isPartial"] = [False, False, False]
        return pd.DataFrame(data, index=dates)

    mock_instance.interest_over_time.side_effect = fake_iot

    collector = TrendsCollector()
    result = collector.monthly_averages(keywords, geo="")

    assert mock_instance.build_payload.call_count == 2
    assert set(result.keys()) == set(keywords)
