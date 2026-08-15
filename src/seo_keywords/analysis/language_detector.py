"""Détection heuristique de la langue réelle d'un mot-clé, à partir de mots
fonction (prépositions, articles, adverbes interrogatifs) propres à chaque
langue. Sert à repérer les artefacts cross-langue AVANT le tagging manuel —
Google Autocomplete retourne parfois des résultats dans une autre langue
que celle demandée via le paramètre hl (déjà observé fr->en/it, et
maintenant en->fr).

Approche volontairement conservatrice : seuls des marqueurs peu ambigus
sont utilisés (mots grammaticaux propres à une langue, pas des mots de
contenu qui pourraient apparaître dans plusieurs langues, ex: 'safari' est
exclu car identique en fr/en/it). En cas de score nul ou d'égalité entre
langues, on ne tranche pas — mieux vaut laisser le mot-clé dans sa langue
déclarée que de se tromper.
"""

from __future__ import annotations

import re

LANGUAGE_MARKERS: dict[str, list[str]] = {
    "fr": [
        r"\bdepuis\b", r"\ben mer\b", r"\bdu\b", r"\bdes\b", r"\bde\b", r"\bavec\b",
        r"\bsans\b", r"\bchez\b", r"\bpourquoi\b", r"\bcombien\b", r"\boù\b",
        r"qu'est-ce",
    ],
    "de": [
        r"\bund\b", r"\bnach\b", r"\bf[uü]r\b", r"\bmit\b", r"\bohne\b",
        r"\bwarum\b", r"\bwann\b", r"wie viel", r"\breise\b", r"\burlaub\b",
    ],
    "it": [
        r"perch[eé]", r"per[oò]", r"\bsenza\b", r"quanto costa",
        r"dove andare", r"\bviaggio\b", r"\bvacanza\b",
    ],
}


def detect_language(keyword: str) -> str | None:
    """Retourne le code langue détecté si un marqueur univoque matche,
    sinon None (pas de signal clair -> on ne tranche pas)."""
    lowered = keyword.lower()
    scores: dict[str, int] = {}
    for lang, patterns in LANGUAGE_MARKERS.items():
        count = sum(1 for p in patterns if re.search(p, lowered))
        if count:
            scores[lang] = count

    if not scores:
        return None

    best_lang = max(scores, key=lambda lang_key: scores[lang_key])
    if list(scores.values()).count(scores[best_lang]) > 1:
        return None  # égalité entre plusieurs langues -> pas de décision
    return best_lang