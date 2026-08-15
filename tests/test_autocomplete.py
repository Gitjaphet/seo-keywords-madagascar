"""Tests du collecteur Autocomplete — aucun appel réseau réel (mocks via `responses`)."""

from __future__ import annotations

import json

import responses

from seo_keywords.collectors.autocomplete import AUTOCOMPLETE_URL, AutocompleteCollector


@responses.activate
def test_collect_returns_suggestions():
    responses.add(
        responses.GET,
        AUTOCOMPLETE_URL,
        body=json.dumps(
            ["excursion nosy be", ["excursion nosy be prix", "excursion nosy be journée"]]
        ),
        status=200,
        content_type="application/json",
    )

    collector = AutocompleteCollector()
    result = collector.collect("excursion nosy be", "fr")

    assert len(result) == 2
    assert result[0].keyword == "excursion nosy be prix"
    assert result[0].source == "google_autocomplete"
    assert result[0].lang == "fr"
    assert result[0].seed == "excursion nosy be"


@responses.activate
def test_collect_handles_empty_response():
    responses.add(
        responses.GET,
        AUTOCOMPLETE_URL,
        body=json.dumps(["xyzabc123", []]),
        status=200,
        content_type="application/json",
    )

    collector = AutocompleteCollector()
    result = collector.collect("xyzabc123", "fr")

    assert result == []


@responses.activate
def test_collect_handles_network_error_gracefully():
    responses.add(responses.GET, AUTOCOMPLETE_URL, status=500)

    collector = AutocompleteCollector()
    # Ne doit JAMAIS lever d'exception : retourne une liste vide en cas d'échec
    result = collector.collect("excursion nosy be", "fr")

    assert result == []


@responses.activate
def test_collect_strips_whitespace_and_filters_empty():
    responses.add(
        responses.GET,
        AUTOCOMPLETE_URL,
        body=json.dumps(["seed", ["  suggestion avec espaces  ", "", "   "]]),
        status=200,
        content_type="application/json",
    )

    collector = AutocompleteCollector()
    result = collector.collect("seed", "fr")

    assert len(result) == 1
    assert result[0].keyword == "suggestion avec espaces"


@responses.activate
def test_collect_expanded_deduplicates():
    # Même réponse pour toutes les requêtes -> beaucoup de doublons attendus
    responses.add(
        responses.GET,
        AUTOCOMPLETE_URL,
        body=json.dumps(["seed", ["suggestion commune", "autre suggestion"]]),
        status=200,
        content_type="application/json",
    )

    collector = AutocompleteCollector()
    result = collector.collect_expanded("seed", "fr", alphabet="ab")

    # 3 appels (seed nu + 'a' + 'b'), mais suggestions identiques -> dédoublonné à 2
    assert len(result) == 2
    keywords = {s.keyword for s in result}
    assert keywords == {"suggestion commune", "autre suggestion"}
