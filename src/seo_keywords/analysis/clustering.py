"""Clustering thématique des mots-clés taggés : regroupe par thème de contenu
pour préparer le mapping vers les pages de sakalavatours.com.

Approche : règles déterministes basées sur le seed d'origine (le seed est
déjà porteur de sens fort, cf. config.SEED_KEYWORDS). Pas de clustering
automatique par similarité pour l'instant — le dataset est encore petit et
les seeds structurent déjà bien le thème ; à revisiter avec des embeddings
si le volume augmente significativement (langues en/de/it comprises).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

# Ordre important : le premier pattern qui matche gagne.
# Basé sur les seeds réels observés dans data/processed/to_tag_fr.csv.
SEED_CLUSTER_RULES: list[tuple[str, str]] = [
    (r"^excursion ile aux nattes", "excursions_mer"),
    (r"^excursion nosy be", "excursions_mer"),
    (r"^croisiere nosy be", "excursions_mer"),
    (r"^circuit madagascar", "circuits_multijours"),
    (r"^safari madagascar", "safari"),
    (r"^sejour madagascar", "hebergement"),
    (r"^agence de voyage madagascar", "agences_prestataires"),
    (r"^tour operateur madagascar", "agences_prestataires"),
    (r"^que faire nosy be", "activites_infos"),
    (r"^voyage madagascar", "voyage_generique"),
]

DEFAULT_CLUSTER = "autre"

# Codes langue reconnus comme "override" dans la colonne notes. Convention
# établie manuellement pendant le tagging : quand un mot-clé collecté sous
# une langue est en réalité écrit dans une autre (artefact Google Suggest
# qui ignore parfois le paramètre hl), on note le vrai code langue ici.
LANGUAGE_OVERRIDE_CODES: set[str] = {"fr", "en", "de", "it"}


@dataclass(frozen=True, slots=True)
class TaggedKeyword:
    keyword: str
    seed: str
    lang: str  # langue résolue (corrigée si override détecté dans notes)
    intent: str
    notes: str
    cluster: str


def assign_cluster(seed: str) -> str:
    """Détermine le cluster thématique d'un mot-clé à partir de son seed."""
    lowered = seed.lower()
    for pattern, cluster_name in SEED_CLUSTER_RULES:
        if re.match(pattern, lowered):
            return cluster_name
    return DEFAULT_CLUSTER


def resolve_language(declared_lang: str, notes: str) -> str:
    """Corrige la langue déclarée si 'notes' contient un code langue override
    (ex: mot-clé collecté sous lang=fr mais en réalité en italien, noté 'IT').

    Retourne la langue déclarée si notes ne contient pas d'override valide.
    """
    marker = notes.strip().lower()
    if marker in LANGUAGE_OVERRIDE_CODES:
        return marker
    return declared_lang


def load_clustered_csv(
    input_path: str, target_lang: str | None = None
) -> tuple[list[TaggedKeyword], list[TaggedKeyword]]:
    """Relit un CSV taggé (colonne intent remplie), résout la vraie langue de
    chaque ligne, et assigne un cluster thématique à partir du seed.

    Ignore les lignes non encore taggées et celles marquées 'exclure'.

    Retourne (matching, cross_language) :
    - matching : lignes dont la langue résolue == target_lang (ou toutes si
      target_lang est None)
    - cross_language : lignes dont la langue résolue diffère de la langue
      déclarée dans le fichier — jamais perdues, juste séparées pour être
      réutilisées lors du tagging de la bonne langue plus tard.
    """
    matching: list[TaggedKeyword] = []
    cross_language: list[TaggedKeyword] = []

    with open(input_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            intent = row.get("intent", "").strip().lower()
            if not intent or intent == "exclure":
                continue

            declared_lang = row["lang"]
            notes = row.get("notes", "")
            resolved_lang = resolve_language(declared_lang, notes)
            seed = row["seed"]

            item = TaggedKeyword(
                keyword=row["keyword"],
                seed=seed,
                lang=resolved_lang,
                intent=intent,
                notes=notes,
                cluster=assign_cluster(seed),
            )

            is_cross_language = resolved_lang != declared_lang.strip().lower()
            if is_cross_language:
                cross_language.append(item)
            elif target_lang is None or resolved_lang == target_lang.strip().lower():
                matching.append(item)

    return matching, cross_language


def export_clustered_csv(items: list[TaggedKeyword], output_path: str) -> None:
    """Exporte le CSV final, trié par cluster puis par mot-clé."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["cluster", "keyword", "seed", "lang", "intent", "notes"])
        for item in sorted(items, key=lambda x: (x.cluster, x.keyword)):
            writer.writerow(
                [item.cluster, item.keyword, item.seed, item.lang, item.intent, item.notes]
            )


def export_cross_language_report(items: list[TaggedKeyword], output_path: str) -> None:
    """Exporte les mots-clés dont la langue a été corrigée, triés par langue
    résolue. Utile pour pré-remplir le tagging quand la bonne langue sera
    collectée via `expand --lang <langue>` — le travail de tag n'est pas perdu.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["resolved_lang", "keyword", "seed", "cluster", "intent"])
        for item in sorted(items, key=lambda x: (x.lang, x.keyword)):
            writer.writerow([item.lang, item.keyword, item.seed, item.cluster, item.intent])


def cluster_summary(items: list[TaggedKeyword]) -> dict[str, int]:
    """Compte le nombre de mots-clés par cluster."""
    summary: dict[str, int] = {}
    for item in items:
        summary[item.cluster] = summary.get(item.cluster, 0) + 1
    return summary