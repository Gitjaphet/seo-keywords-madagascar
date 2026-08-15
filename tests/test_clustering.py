"""Tests du clustering — inclut la réconciliation de langue (artefacts EN/IT
noté en 'notes' sur des lignes collectées sous lang=fr)."""

from __future__ import annotations

import csv

from seo_keywords.analysis.clustering import (
    assign_cluster,
    cluster_summary,
    export_clustered_csv,
    export_cross_language_report,
    load_clustered_csv,
    resolve_language,
)


def _write_csv(path, rows: list[dict]) -> None:
    fieldnames = ["keyword", "seed", "lang", "intent", "notes"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_assign_cluster_matches_real_seeds():
    assert assign_cluster("excursion nosy be") == "excursions_mer"
    assert assign_cluster("circuit madagascar c") == "circuits_multijours"
    assert assign_cluster("safari madagascar b") == "safari"
    assert assign_cluster("agence de voyage madagascar a") == "agences_prestataires"


def test_assign_cluster_falls_back_to_autre_for_unknown_seed():
    assert assign_cluster("mot-clé jamais vu") == "autre"


def test_resolve_language_returns_declared_when_no_override():
    assert resolve_language("fr", "") == "fr"
    assert resolve_language("fr", "confusion avec compagnie aerienne") == "fr"


def test_resolve_language_applies_override_from_notes():
    # Cas réel: 'best tour operator madagascar' collecté sous fr, en réalité EN
    assert resolve_language("fr", "EN") == "en"
    assert resolve_language("fr", "IT") == "it"
    assert resolve_language("fr", " it ") == "it"  # tolère espaces


def test_load_clustered_csv_ignores_untagged_and_excluded_rows(tmp_path):
    csv_path = tmp_path / "tagged.csv"
    _write_csv(csv_path, [
        {"keyword": "excursion nosy be tarif", "seed": "excursion nosy be",
         "lang": "fr", "intent": "transactionnel", "notes": ""},
        {"keyword": "pas encore tagué", "seed": "excursion nosy be",
         "lang": "fr", "intent": "", "notes": ""},
        {"keyword": "circuit madagascar tui", "seed": "circuit madagascar",
         "lang": "fr", "intent": "exclure", "notes": "concurrent"},
    ])

    matching, cross_lang = load_clustered_csv(str(csv_path), target_lang="fr")

    assert len(matching) == 1
    assert matching[0].keyword == "excursion nosy be tarif"
    assert cross_lang == []


def test_load_clustered_csv_assigns_cluster_from_seed(tmp_path):
    csv_path = tmp_path / "tagged.csv"
    _write_csv(csv_path, [
        {"keyword": "que faire a nosy be blog", "seed": "que faire nosy be",
         "lang": "fr", "intent": "informationnel", "notes": ""},
    ])

    matching, _ = load_clustered_csv(str(csv_path), target_lang="fr")

    assert matching[0].cluster == "activites_infos"


def test_load_clustered_csv_separates_cross_language_artifacts(tmp_path):
    """Cas réel: 'best tour operator madagascar' et 'migliori tour operator
    madagascar' collectés sous lang=fr, notés EN/IT dans notes -> doivent
    être exclus du lot fr et retrouvés dans le lot cross_language."""
    csv_path = tmp_path / "tagged.csv"
    _write_csv(csv_path, [
        {"keyword": "agence de voyage madagascar", "seed": "agence de voyage madagascar",
         "lang": "fr", "intent": "transactionnel", "notes": ""},
        {"keyword": "best tour operator madagascar", "seed": "tour operateur madagascar",
         "lang": "fr", "intent": "transactionnel", "notes": "EN"},
        {"keyword": "migliori tour operator madagascar", "seed": "tour operateur madagascar",
         "lang": "fr", "intent": "transactionnel", "notes": "IT"},
    ])

    matching, cross_lang = load_clustered_csv(str(csv_path), target_lang="fr")

    assert len(matching) == 1
    assert matching[0].keyword == "agence de voyage madagascar"

    assert len(cross_lang) == 2
    resolved_langs = {item.lang for item in cross_lang}
    assert resolved_langs == {"en", "it"}
    # Le cluster et l'intent taggé sont préservés, pas perdus
    en_item = next(i for i in cross_lang if i.lang == "en")
    assert en_item.cluster == "agences_prestataires"
    assert en_item.intent == "transactionnel"


def test_load_clustered_csv_without_target_lang_returns_all_as_matching(tmp_path):
    csv_path = tmp_path / "tagged.csv"
    _write_csv(csv_path, [
        {"keyword": "excursion nosy be tarif", "seed": "excursion nosy be",
         "lang": "fr", "intent": "transactionnel", "notes": ""},
    ])

    matching, cross_lang = load_clustered_csv(str(csv_path), target_lang=None)

    assert len(matching) == 1
    assert cross_lang == []


def test_export_clustered_csv_creates_valid_csv_sorted_by_cluster(tmp_path):
    csv_path = tmp_path / "tagged.csv"
    _write_csv(csv_path, [
        {"keyword": "safari madagascar prix", "seed": "safari madagascar",
         "lang": "fr", "intent": "transactionnel", "notes": ""},
        {"keyword": "excursion nosy be tarif", "seed": "excursion nosy be",
         "lang": "fr", "intent": "transactionnel", "notes": ""},
    ])
    matching, _ = load_clustered_csv(str(csv_path), target_lang="fr")
    output = tmp_path / "clustered.csv"

    export_clustered_csv(matching, str(output))

    with open(output, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["cluster"] == "excursions_mer"  # alphabétiquement avant 'safari'
    assert rows[1]["cluster"] == "safari"


def test_export_cross_language_report_creates_valid_csv(tmp_path):
    csv_path = tmp_path / "tagged.csv"
    _write_csv(csv_path, [
        {"keyword": "best tour operator madagascar", "seed": "tour operateur madagascar",
         "lang": "fr", "intent": "transactionnel", "notes": "EN"},
    ])
    _, cross_lang = load_clustered_csv(str(csv_path), target_lang="fr")
    output = tmp_path / "cross_lang.csv"

    export_cross_language_report(cross_lang, str(output))

    with open(output, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["resolved_lang"] == "en"
    assert rows[0]["keyword"] == "best tour operator madagascar"
    assert rows[0]["intent"] == "transactionnel"


def test_cluster_summary_counts_never_drop_items():
    from seo_keywords.analysis.clustering import TaggedKeyword

    items = [
        TaggedKeyword("kw1", "seed1", "fr", "transactionnel", "", "excursions_mer"),
        TaggedKeyword("kw2", "seed2", "fr", "transactionnel", "", "excursions_mer"),
        TaggedKeyword("kw3", "seed3", "fr", "informationnel", "", "safari"),
    ]

    summary = cluster_summary(items)

    assert summary == {"excursions_mer": 2, "safari": 1}
    assert sum(summary.values()) == len(items)