"""Tests du classificateur d'intention — exemples basés sur les vrais mots-clés
collectés (fr/en/de/it)."""

from __future__ import annotations

import csv

from seo_keywords.analysis.intent_classifier import (
    auto_classify_csv,
    classification_summary,
    classify_commercial_fallback,
    classify_intent,
    export_classified_csv,
    export_needs_review_csv,
)


def _write_csv(path, rows: list[dict]) -> None:
    fieldnames = ["keyword", "seed", "lang", "intent", "notes"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_classify_intent_transactional_fr():
    assert classify_intent("excursion nosy be tarif")[0] == "transactionnel"
    assert classify_intent("safari madagascar prix")[0] == "transactionnel"
    assert classify_intent("croisiere nosy be pas cher")[0] == "transactionnel"


def test_classify_intent_transactional_en():
    assert classify_intent("madagascar trip cost")[0] == "transactionnel"
    assert classify_intent("book madagascar trip")[0] == "transactionnel"
    assert classify_intent("cheap madagascar vacation")[0] == "transactionnel"


def test_classify_intent_transactional_de():
    assert classify_intent("madagaskar reise günstig")[0] == "transactionnel"
    assert classify_intent("madagaskar rundreise buchen")[0] == "transactionnel"


def test_classify_intent_transactional_it():
    assert classify_intent("viaggio madagascar prezzo")[0] == "transactionnel"
    assert classify_intent("tour madagascar economico")[0] == "transactionnel"


def test_classify_intent_plural_trip_and_excursion_bug():
    """Régression: COMMERCIAL_PATTERNS avait 'trip' et 'excursion' au
    singulier seulement — 'trips'/'excursions' au pluriel ne matchaient
    jamais malgré \\b, car le 's' colle au mot. Trouvé via needs_review_en
    ('nosy be day trips', 'shore excursions nosy be')."""
    assert classify_commercial_fallback("nosy be day trips")[0] == "commercial"
    assert classify_commercial_fallback("shore excursions nosy be")[0] == "commercial"


def test_classify_intent_official_safety_and_seasonal_cluster():
    """Régression: cluster 'sécurité officielle' (alert/ban/cdc/danger/gov/
    guidance/health) et cluster saisonnier (mois + travel) trouvés dans
    needs_review_en, tous sans aucun pattern matché."""
    assert classify_intent("madagascar travel alert")[0] == "informationnel"
    assert classify_intent("madagascar travel cdc")[0] == "informationnel"
    assert classify_intent("madagascar travel january")[0] == "informationnel"
    assert classify_intent("madagascar travel in december")[0] == "informationnel"


def test_classify_intent_wiki_travel_is_navigational():
    assert classify_intent("madagascar wiki travel")[0] == "navigationnel"

    
def test_classify_intent_informational_fr():
    assert classify_intent("que faire a nosy be blog")[0] == "informationnel"
    assert classify_intent("voyage madagascar avis")[0] == "informationnel"

def test_classify_intent_travel_agency_is_commercial():
    # classify_intent() ne gère pas le commercial (tier séparé, confiance
    # plus faible) — il doit renvoyer None, et c'est classify_commercial_fallback
    # qui prend le relais.
    assert classify_intent("best travel agency in madagascar") is None
    result = classify_commercial_fallback("best travel agency in madagascar")
    assert result is not None
    assert result[0] == "commercial"
    assert classify_commercial_fallback("madagascar travel agents")[0] == "commercial"


def test_classify_intent_catches_advisory_and_things_to_do():
    """Régression: diagnostic needs_review_en a montré 128/128 cas sans
    aucun pattern matché, dont un cluster net 'travel advisory/gov/visa'
    et 'things to do' non couvert par la variante 'what to do'."""
    assert classify_intent("things to do in madagascar")[0] == "informationnel"
    assert classify_intent("madagascar travel state gov")[0] == "informationnel"
    assert classify_intent("madagascar visa policy")[0] == "informationnel"

def test_classify_intent_informational_en():
    assert classify_intent("how to plan madagascar trip")[0] == "informationnel"
    assert classify_intent("best time to visit madagascar")[0] == "informationnel"
    assert classify_intent("madagascar trip review")[0] == "informationnel"


def test_classify_intent_informational_de():
    assert classify_intent("madagaskar reise erfahrung")[0] == "informationnel"
    assert classify_intent("wann nach madagaskar reisen")[0] == "informationnel"


def test_classify_intent_catches_question_words_mid_string():
    """Régression: la méthode de collecte (seed + lettre) place presque
    toujours le mot interrogatif APRÈS le seed, jamais en tout début de
    mot-clé. Des patterns ancrés avec '^' rateraient donc systématiquement
    ces vraies questions. Vérifie que ce n'est plus le cas."""
    assert classify_intent("vacanza madagascar quando andare")[0] == "informationnel"
    assert classify_intent("madagascar trip is it safe")[0] == "informationnel"
    assert classify_intent("strand madagaskar urlaub gefährlich")[0] == "informationnel"


def test_classify_intent_informational_it():
    assert classify_intent("madagascar recensioni viaggio")[0] == "informationnel"
    assert classify_intent("quando andare in madagascar")[0] == "informationnel"


def test_classify_intent_navigational_brands():
    assert classify_intent("madagascar trip advisor reviews")[0] == "navigationnel"
    assert classify_intent("book madagascar getyourguide")[0] == "navigationnel"
    assert classify_intent("madagascar lonely planet guide")[0] == "navigationnel"


def test_classify_intent_navigational_takes_priority_over_transactional():
    # Contient à la fois un signal transactionnel ('book') et navigationnel
    # (marque) -> navigationnel doit gagner (signal plus fort et univoque)
    intent, _ = classify_intent("book madagascar trip on booking.com")
    assert intent == "navigationnel"


def test_classify_intent_returns_none_for_ambiguous_keyword():
    assert classify_intent("madagascar red island") is None
    assert classify_intent("nosy be") is None


def test_classify_intent_never_returns_commercial_tier():
    """classify_intent() (tiers 1-3 haute confiance) ne doit JAMAIS renvoyer
    'commercial' — ce tier est strictement séparé, opt-in via
    classify_commercial_fallback()."""
    result = classify_intent("madagascar diving trip")
    assert result is None  # pas de faux 'commercial' silencieux


def test_classify_commercial_fallback_catches_trip_type_descriptors():
    intent, rule = classify_commercial_fallback("madagascar diving trip")
    assert intent == "commercial"
    assert rule.startswith("commercial:")

    assert classify_commercial_fallback("madagascar family vacation")[0] == "commercial"
    assert classify_commercial_fallback("madagascar luxury holidays")[0] == "commercial"


def test_classify_commercial_fallback_multilingual():
    assert classify_commercial_fallback("circuit accompagné madagascar")[0] == "commercial"
    assert classify_commercial_fallback("madagaskar rundreise")[0] == "commercial"
    assert classify_commercial_fallback("viaggio organizzato madagascar")[0] == "commercial"


def test_classify_commercial_fallback_returns_none_when_truly_ambiguous():
    assert classify_commercial_fallback("madagascar red island") is None
    assert classify_commercial_fallback("nosy be") is None


def test_auto_classify_csv_respects_already_tagged_rows(tmp_path):
    """Une ligne déjà taguée manuellement ne doit JAMAIS être reclassée,
    même si un pattern automatique matcherait différemment."""
    csv_path = tmp_path / "to_tag.csv"
    _write_csv(csv_path, [
        {"keyword": "excursion nosy be tarif", "seed": "excursion nosy be",
         "lang": "fr", "intent": "informationnel", "notes": "tagué à la main volontairement"},
    ])

    result = auto_classify_csv(str(csv_path))

    assert len(result.classified) == 1
    assert result.classified[0].intent == "informationnel"  # pas 'transactionnel'
    assert result.classified[0].matched_rule == "manuel"
    assert result.needs_review == []


def test_auto_classify_csv_splits_matched_and_ambiguous(tmp_path):
    csv_path = tmp_path / "to_tag.csv"
    _write_csv(csv_path, [
        {"keyword": "madagascar trip cost", "seed": "madagascar trip",
         "lang": "en", "intent": "", "notes": ""},
        {"keyword": "madagascar red island", "seed": "madagascar trip",
         "lang": "en", "intent": "", "notes": ""},
    ])

    result = auto_classify_csv(str(csv_path))

    assert len(result.classified) == 1
    assert result.classified[0].keyword == "madagascar trip cost"
    assert result.classified[0].intent == "transactionnel"

    assert len(result.needs_review) == 1
    assert result.needs_review[0]["keyword"] == "madagascar red island"


def test_auto_classify_csv_commercial_fallback_disabled_by_default(tmp_path):
    """Sans include_commercial_fallback=True, 'madagascar diving trip'
    (aucun signal fort) doit partir en révision, pas être deviné."""
    csv_path = tmp_path / "to_tag.csv"
    _write_csv(csv_path, [
        {"keyword": "madagascar diving trip", "seed": "madagascar trip",
         "lang": "en", "intent": "", "notes": ""},
    ])

    result = auto_classify_csv(str(csv_path))

    assert len(result.classified) == 0
    assert len(result.needs_review) == 1


def test_auto_classify_csv_commercial_fallback_opt_in(tmp_path):
    csv_path = tmp_path / "to_tag.csv"
    _write_csv(csv_path, [
        {"keyword": "madagascar diving trip", "seed": "madagascar trip",
         "lang": "en", "intent": "", "notes": ""},
        {"keyword": "madagascar trip cost", "seed": "madagascar trip",
         "lang": "en", "intent": "", "notes": ""},  # doit rester tier haute confiance
        {"keyword": "madagascar red island", "seed": "madagascar trip",
         "lang": "en", "intent": "", "notes": ""},  # toujours ambigu même avec fallback
    ])

    result = auto_classify_csv(str(csv_path), include_commercial_fallback=True)

    by_keyword = {item.keyword: item for item in result.classified}
    assert by_keyword["madagascar diving trip"].intent == "commercial"
    assert by_keyword["madagascar diving trip"].matched_rule.startswith("commercial:")
    assert by_keyword["madagascar trip cost"].intent == "transactionnel"  # pas écrasé

    assert len(result.needs_review) == 1
    assert result.needs_review[0]["keyword"] == "madagascar red island"


def test_auto_classify_csv_never_drops_rows(tmp_path):
    csv_path = tmp_path / "to_tag.csv"
    _write_csv(csv_path, [
        {"keyword": "madagascar trip cost", "seed": "x", "lang": "en", "intent": "", "notes": ""},
        {"keyword": "ambiguous keyword", "seed": "x", "lang": "en", "intent": "", "notes": ""},
        {"keyword": "already tagged", "seed": "x", "lang": "en", "intent": "transactionnel",
         "notes": ""},
    ])

    result = auto_classify_csv(str(csv_path))
    total = len(result.classified) + len(result.needs_review)

    assert total == 3


def test_export_classified_csv_creates_valid_csv(tmp_path):
    from seo_keywords.analysis.intent_classifier import ClassifiedKeyword

    items = [
        ClassifiedKeyword("madagascar trip cost", "madagascar trip", "en",
                           "transactionnel", r"\bcost\b"),
    ]
    output = tmp_path / "classified.csv"

    export_classified_csv(items, str(output))

    with open(output, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["intent"] == "transactionnel"
    assert rows[0]["matched_rule"] == r"\bcost\b"


def test_export_needs_review_csv_creates_taggable_format(tmp_path):
    rows = [{"keyword": "madagascar red island", "seed": "madagascar trip",
             "lang": "en", "intent": "", "notes": ""}]
    output = tmp_path / "needs_review.csv"

    export_needs_review_csv(rows, str(output))

    with open(output, encoding="utf-8") as f:
        result_rows = list(csv.DictReader(f))

    assert len(result_rows) == 1
    assert result_rows[0]["intent"] == ""  # prêt pour tagging manuel
    assert set(result_rows[0].keys()) == {"keyword", "seed", "lang", "intent", "notes"}


def test_classification_summary_counts_never_drop_items():
    from seo_keywords.analysis.intent_classifier import ClassifiedKeyword

    items = [
        ClassifiedKeyword("kw1", "s", "en", "transactionnel", "r1"),
        ClassifiedKeyword("kw2", "s", "en", "transactionnel", "r2"),
        ClassifiedKeyword("kw3", "s", "en", "informationnel", "r3"),
    ]

    summary = classification_summary(items)

    assert summary == {"transactionnel": 2, "informationnel": 1}
    assert sum(summary.values()) == len(items)