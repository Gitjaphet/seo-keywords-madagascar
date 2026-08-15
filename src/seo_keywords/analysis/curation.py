"""Curation des mots-clés collectés : filtrage automatique du bruit
et export pour catégorisation manuelle de l'intention de recherche.

Deux niveaux de filtrage automatique :
1. COMPETITOR_BRANDS : marques concurrentes (jamais à cibler en SEO)
2. OFF_TOPIC_PATTERNS : faux positifs sémantiques et mauvaise audience

Tout le reste passe en revue manuelle via export CSV — l'intention de
recherche (informationnelle / transactionnelle / navigationnelle) est
un jugement humain, pas quelque chose qu'on automatise fiablement avec
de simples règles.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from seo_keywords.analysis.language_detector import detect_language
from seo_keywords.storage.models import KeywordRecord

# Marques et enseignes concurrentes : on les repère pour l'intelligence
# concurrentielle, mais on ne cible jamais leur nom en SEO/SEA.
COMPETITOR_BRANDS: list[str] = [
    "tui", "leclerc", "fram", "kuoni", "nouvelles frontières", "nouvelles frontieres",
    "club med", "carrefour", "bourdon", "air france",
    "jet2", "british airways", "virgin", "mercury holidays", "kensington tours",
    "intrepid", "gebeco", "marco polo", "turisanda", "holidaycheck",
]

OFF_TOPIC_PATTERNS: list[str] = [
    r"\bmovie\b", r"\bapk\b", r"automobile", r"\bchien\b",
    r"recrutement", r"comment créer", r"chiffres", r"\bfilm\b",
    r"liste tour opérateur", r"tour operateur professionnel",
    r"release date", r"centella", r"skin1004",  # gamme cosmétique, film Madagascar 4
    r"national holidays?\b", r"official holidays?\b", r"major holidays?\b",
    # calendrier de jours fériés (RH/expat), pas une recherche de voyage
]


@dataclass(frozen=True, slots=True)
class CurationResult:
    keeper: list[KeywordRecord]
    competitor: list[KeywordRecord]
    off_topic: list[KeywordRecord]


def _matches_any(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return any(re.search(needle, lowered) for needle in needles)


def auto_filter(records: list[KeywordRecord]) -> CurationResult:
    """Sépare les mots-clés en trois lots : à garder, concurrents, hors-sujet.

    N'exclut JAMAIS silencieusement : les lots 'competitor' et 'off_topic'
    restent consultables pour audit, ils ne sont juste pas proposés pour
    le tagging manuel d'intention.
    """
    keeper: list[KeywordRecord] = []
    competitor: list[KeywordRecord] = []
    off_topic: list[KeywordRecord] = []

    for record in records:
        if _matches_any(record.keyword, COMPETITOR_BRANDS):
            competitor.append(record)
        elif _matches_any(record.keyword, OFF_TOPIC_PATTERNS):
            off_topic.append(record)
        else:
            keeper.append(record)

    return CurationResult(keeper=keeper, competitor=competitor, off_topic=off_topic)


def separate_cross_language(
    records: list[KeywordRecord], declared_lang: str
) -> tuple[list[KeywordRecord], list[tuple[KeywordRecord, str]]]:
    """Sépare les mots-clés dont la langue détectée automatiquement diffère
    de la langue déclarée (ex: 'excursion en mer à nosy be' collecté sous
    lang=en mais réellement en français).

    Conservateur par construction : ne déplace un mot-clé que si
    detect_language() renvoie un résultat univoque ET différent de
    declared_lang. En cas de doute, le mot-clé reste dans sa langue déclarée.

    Retourne (même_langue, [(record, langue_détectée), ...]).
    """
    same_lang: list[KeywordRecord] = []
    foreign: list[tuple[KeywordRecord, str]] = []
    for r in records:
        detected = detect_language(r.keyword)
        if detected and detected != declared_lang:
            foreign.append((r, detected))
        else:
            same_lang.append(r)
    return same_lang, foreign


def export_foreign_language_csv(
    items: list[tuple[KeywordRecord, str]], output_path: str
) -> None:
    """Exporte les mots-clés détectés dans une autre langue que celle
    déclarée, pour réutilisation lors de la collecte/tagging de la bonne
    langue plus tard."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["detected_lang", "keyword", "seed", "declared_lang"])
        for record, detected in sorted(items, key=lambda x: (x[1], x[0].keyword)):
            writer.writerow([detected, record.keyword, record.seed, record.lang])


def export_for_manual_tagging(records: list[KeywordRecord], output_path: str) -> None:
    """Exporte un CSV à ouvrir dans Excel/Sheets pour tagger l'intention à la main.

    Colonnes : keyword, seed, lang, intent (vide à remplir), notes (vide).
    Valeurs attendues pour 'intent' : transactionnel / informationnel /
    navigationnel / exclure
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["keyword", "seed", "lang", "intent", "notes"])
        for r in sorted(records, key=lambda x: x.keyword):
            writer.writerow([r.keyword, r.seed, r.lang, "", ""])


def load_tagged_csv(input_path: str) -> dict[str, str]:
    """Relit un CSV taggé manuellement et retourne {keyword: intent}.

    Ignore les lignes où 'intent' est vide (pas encore taguées).
    """
    tagged: dict[str, str] = {}
    with open(input_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            intent = row.get("intent", "").strip().lower()
            if intent:
                tagged[row["keyword"]] = intent
    return tagged