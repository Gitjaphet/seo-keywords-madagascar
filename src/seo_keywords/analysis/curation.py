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

from seo_keywords.storage.models import KeywordRecord

# Marques et enseignes concurrentes : on les repère pour l'intelligence
# concurrentielle, mais on ne cible jamais leur nom en SEO/SEA.
COMPETITOR_BRANDS: list[str] = [
    "tui", "leclerc", "fram", "kuoni", "nouvelles frontières", "nouvelles frontieres",
    "club med", "carrefour", "bourdon", "air france",
]

# Patterns de faux positifs sémantiques ou de mauvaise audience,
# identifiés lors de la revue manuelle du premier lot de collecte.
OFF_TOPIC_PATTERNS: list[str] = [
    r"\bmovie\b", r"\bapk\b", r"automobile", r"\bchien\b",
    r"recrutement", r"comment créer", r"chiffres", r"\bfilm\b",
    r"liste tour opérateur", r"tour operateur professionnel",
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
