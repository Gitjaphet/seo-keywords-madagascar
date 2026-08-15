"""Diagnostic des mots-clés needs_review_*.csv : pourquoi échappent-ils
à la classification automatique ?

Ne réinvente aucune regex : importe les vraies listes *_PATTERNS depuis
seo_keywords.analysis.intent_classifier et applique chacune individuellement
pour distinguer deux causes bien différentes :
  - "aucun pattern"      : aucune catégorie ne matche -> vrai trou de règle
  - "patterns en conflit" : plusieurs catégories matchent -> ambiguïté
                            réelle du mot-clé, ou priorité mal définie
                            dans classify_intent()

Usage:
    uv run python scripts/diagnose_needs_review.py --lang en

Sortie:
    data/processed/diagnostic_no_match_<lang>.csv
    data/processed/diagnostic_conflict_<lang>.csv
    + un résumé console avec les mots les plus fréquents côté "aucun pattern",
      pour repérer vite les 1-2 patterns manquants qui expliquent le plus de cas.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

from seo_keywords.analysis import intent_classifier as ic

STOPWORDS = {
    "madagascar", "madagaskar", "nosy", "be", "de", "du", "la", "le", "les",
    "à", "en", "et", "for", "the", "a", "an", "of", "to", "in", "und", "der",
    "die", "das", "di", "il", "la", "per", "e",
}


def discover_pattern_groups() -> dict[str, list[str]]:
    """Récupère dynamiquement toutes les listes *_PATTERNS du module,
    pour rester fidèle au code réel même s'il évolue."""
    groups = {}
    for name, value in vars(ic).items():
        if name.endswith("_PATTERNS") and isinstance(value, list):
            groups[name] = value
    return groups


def matched_categories(keyword: str, groups: dict[str, list[str]]) -> list[str]:
    hits = []
    for category, patterns in groups.items():
        for pattern in patterns:
            if re.search(pattern, keyword, flags=re.IGNORECASE):
                hits.append(category)
                break
    return hits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", required=True)
    args = parser.parse_args()

    groups = discover_pattern_groups()
    print(f"Catégories de patterns détectées : {', '.join(groups)}\n")

    src = Path(f"data/processed/needs_review_{args.lang}.csv")
    rows = list(csv.DictReader(src.open(encoding="utf-8")))

    no_match, conflict, single = [], [], []
    word_counter: Counter[str] = Counter()

    for row in rows:
        keyword = row["keyword"]
        hits = matched_categories(keyword, groups)
        if not hits:
            no_match.append(row)
            for word in keyword.lower().split():
                if word not in STOPWORDS:
                    word_counter[word] += 1
        elif len(hits) > 1:
            row["matched_categories"] = " + ".join(hits)
            conflict.append(row)
        else:
            row["matched_categories"] = hits[0]
            single.append(row)

    print(f"Total needs_review : {len(rows)}")
    print(f"  Aucun pattern       : {len(no_match)}")
    print(f"  Patterns en conflit : {len(conflict)}")
    print(f"  Un seul pattern     : {len(single)}  (à investiguer : pourquoi "
          f"resté en review malgré un match clair — souvent un signe qu'il "
          f"manque une règle de priorité dans classify_intent)\n")

    print("Mots les plus fréquents côté 'aucun pattern' (candidats à une "
          "nouvelle règle) :")
    for word, count in word_counter.most_common(15):
        print(f"  {word:20s} {count}")

    out_dir = Path("data/processed")
    for name, data in [("no_match", no_match), ("conflict", conflict)]:
        out_path = out_dir / f"diagnostic_{name}_{args.lang}.csv"
        if data:
            with out_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
                writer.writeheader()
                writer.writerows(data)
            print(f"\n✓ Écrit : {out_path}")


if __name__ == "__main__":
    main()
