"""Classification automatique de l'intention de recherche par règles
heuristiques multilingues (fr/en/de/it), pour éviter de tagger des
centaines/milliers de mots-clés à la main.

Principe : une règle claire l'emporte toujours sur une hypothèse implicite.
Si aucune règle ne matche, le mot-clé n'est PAS deviné au hasard — il part
dans une file de révision manuelle. Mieux vaut un lot plus petit à taguer
à la main que des intentions fausses qui polluent le clustering et le
mapping vers les pages du site.

Ordre de priorité des règles : navigationnel > transactionnel > informationnel.
Une marque de plateforme de voyage (TripAdvisor, Booking.com...) est un
signal fort et univoque, donc vérifiée en premier.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

NAVIGATIONAL_PATTERNS: list[str] = [
    r"tripadvisor", r"trip advisor", r"booking\.com", r"\bbooking\b",
    r"getyourguide", r"get your guide", r"\bviator\b", r"lonely planet",
    r"\bexpedia\b", r"\bklook\b", r"\bcivitatis\b", r"\bkayak\b",
    r"\bskyscanner\b", r"\bopodo\b", r"holidaycheck",
]

TRANSACTIONAL_PATTERNS: list[str] = [
    # FR
    r"\bprix\b", r"pas cher", r"\btarif", r"r[ée]server", r"r[ée]servation",
    r"\bdevis\b", r"combien co[uû]te",
    # EN
    r"\bprice\b", r"\bcost\b", r"\bcheap\b", r"\bbook\b", r"\bbooking\b",
    r"how much", r"\bpackage",
    # DE
    r"\bpreis\b", r"g[uü]nstig", r"\bkosten\b", r"\bbuchen\b", r"\bbuchung",
    # IT
    r"\bprezzo\b", r"economic", r"\bprenota", r"\bcosto\b",
]

INFORMATIONAL_PATTERNS: list[str] = [
    # FR
    r"^que faire", r"^comment\b", r"^pourquoi\b", r"\bavis\b", r"\bblog\b",
    r"\bconseil", r"\bguide\b", r"itin[ée]raire", r"^quand\b",
    # EN
    r"^how to", r"^what to", r"^why\b", r"\breview", r"\btips\b",
    r"\bguide\b", r"\bitinerary\b", r"^when\b", r"^best time",
    r"^is\b", r"^are\b", r"^do i\b", r"^does\b", r"^can\b",
    r"^how many\b", r"^how safe\b",
    # DE
    r"^wie\b", r"^warum\b", r"\berfahrung", r"\btipps\b", r"reisef[uü]hrer",
    r"^wann\b", r"\breddit\b", r"\bplanen\b", r"highlights?\b", r"\bbilder\b",
    r"\baktuell\b", r"reise wert", r"urlaub wert", r"was beachten",
    r"\bsprache\b",
    # IT
    r"^come\b", r"^perch[eé]\b", r"\brecensioni\b", r"\bconsigli\b",
    r"\bitinerario\b", r"^quando\b", r"cosa portare", r"\bmappa\b", r"\bmap\b",
]

# Niveau 4 (Google search-intent model): "commercial investigation" — la
# personne compare des TYPES de voyage sans avoir encore d'intention de
# réservation ferme ni de question précise. Distinct de 'transactionnel'
# (signal d'achat explicite: prix, book, package) et de 'informationnel'
# (question ou contenu éditorial explicite). Appliqué en dernier recours,
# seulement si rien d'autre n'a matché — jamais mélangé aux tiers à haute
# confiance : le 'matched_rule' reste préfixé 'commercial:' pour rester
# facilement filtrable et contrôlable par échantillonnage.
COMMERCIAL_PATTERNS: list[str] = [
    # EN
    r"\btrip\b", r"\btour\b", r"\btours\b", r"\bvacation\b", r"\bholiday",
    # FR
    r"\bvoyage\b", r"\bcircuit\b", r"\bs[ée]jour\b", r"\bexcursion\b",
    # DE
    r"\breise\b", r"\burlaub\b", r"\brundreise\b",
    # IT
    r"\bviaggio\b", r"\bvacanza\b",
]

def _first_match(text: str, patterns: list[str]) -> str | None:
    lowered = text.lower()
    for pattern in patterns:
        if re.search(pattern, lowered):
            return pattern
    return None


def classify_intent(keyword: str) -> tuple[str, str] | None:
    """Retourne (intent, pattern_déclencheur) si une règle matche, sinon None
    (le mot-clé doit être révisé manuellement).

    N'inclut PAS le niveau 'commercial' (voir classify_commercial_fallback) :
    ce sont deux tiers de confiance différents, jamais mélangés silencieusement.
    """
    if match := _first_match(keyword, NAVIGATIONAL_PATTERNS):
        return "navigationnel", match
    if match := _first_match(keyword, TRANSACTIONAL_PATTERNS):
        return "transactionnel", match
    if match := _first_match(keyword, INFORMATIONAL_PATTERNS):
        return "informationnel", match
    return None


def classify_commercial_fallback(keyword: str) -> tuple[str, str] | None:
    """Niveau 4 (fallback, confiance plus faible) : détecte une intention
    'commercial investigation' (comparaison de types de voyage, ex: 'madagascar
    diving trip') quand rien d'autre n'a matché. Le pattern déclencheur est
    préfixé 'commercial:' pour rester facilement filtrable/auditable — jamais
    fusionné avec les classifications à haute confiance de classify_intent().
    """
    if match := _first_match(keyword, COMMERCIAL_PATTERNS):
        return "commercial", f"commercial:{match}"
    return None


@dataclass(frozen=True, slots=True)
class ClassifiedKeyword:
    keyword: str
    seed: str
    lang: str
    intent: str
    matched_rule: str  # pattern déclencheur, ou 'manuel' si déjà tagué avant


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    classified: list[ClassifiedKeyword]
    needs_review: list[dict[str, str]]  # lignes brutes non classées, pour tagging manuel


def auto_classify_csv(
    input_path: str, include_commercial_fallback: bool = False
) -> ClassificationResult:
    """Relit un CSV issu de `curate` (colonnes: keyword, seed, lang, intent, notes)
    et classe automatiquement l'intention par règles.

    Les lignes déjà taguées manuellement (intent non vide) sont respectées
    telles quelles et ne sont JAMAIS reclassées automatiquement. Les lignes
    non taguées et non matchées par une règle partent dans needs_review —
    rien n'est deviné au hasard, rien n'est perdu.

    include_commercial_fallback (défaut False) : active le 4e tier de
    confiance plus faible (voir classify_commercial_fallback). Explicitement
    opt-in — jamais activé par défaut, pour que l'appelant décide en
    connaissance de cause du compromis précision/couverture.
    """
    classified: list[ClassifiedKeyword] = []
    needs_review: list[dict[str, str]] = []

    with open(input_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            existing_intent = row.get("intent", "").strip().lower()
            if existing_intent:
                classified.append(
                    ClassifiedKeyword(
                        keyword=row["keyword"], seed=row["seed"], lang=row["lang"],
                        intent=existing_intent, matched_rule="manuel",
                    )
                )
                continue

            result = classify_intent(row["keyword"])
            if result is None and include_commercial_fallback:
                result = classify_commercial_fallback(row["keyword"])

            if result is None:
                needs_review.append(row)
                continue

            intent, rule = result
            classified.append(
                ClassifiedKeyword(
                    keyword=row["keyword"], seed=row["seed"], lang=row["lang"],
                    intent=intent, matched_rule=rule,
                )
            )

    return ClassificationResult(classified=classified, needs_review=needs_review)


def export_classified_csv(items: list[ClassifiedKeyword], output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["keyword", "seed", "lang", "intent", "matched_rule"])
        for item in sorted(items, key=lambda x: (x.intent, x.keyword)):
            writer.writerow(
                [item.keyword, item.seed, item.lang, item.intent, item.matched_rule]
            )


def export_needs_review_csv(rows: list[dict[str, str]], output_path: str) -> None:
    """Exporte les mots-clés non classés automatiquement, au même format que
    `curate` (colonnes keyword, seed, lang, intent, notes) pour un tagging
    manuel réduit au strict nécessaire."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["keyword", "seed", "lang", "intent", "notes"])
        for row in sorted(rows, key=lambda r: r["keyword"]):
            writer.writerow([row["keyword"], row["seed"], row["lang"], "", ""])


def classification_summary(items: list[ClassifiedKeyword]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for item in items:
        summary[item.intent] = summary.get(item.intent, 0) + 1
    return summary