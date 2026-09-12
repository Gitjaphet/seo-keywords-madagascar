"""Classification automatique de l'intention, directement en base.

Achève la transition commencée par la migration CSV -> base : `classify`
lisait et écrivait des fichiers, ce qui laissait la base à l'écart du
flux. Ici, les règles s'appliquent sur `Keyword` et le résultat est
journalisé.

Garantie centrale : une ligne dont `intent_source` vaut MANUAL n'est
jamais touchée. C'est la clause `WHERE` qui le garantit, pas une
convention qu'il faudrait penser à respecter.
"""

from collections import Counter
from dataclasses import dataclass

from sqlmodel import Session, select

from seo_keywords.analysis.intent_classifier import (
    classify_commercial_fallback,
    classify_intent,
)
from seo_keywords.storage.models import (
    Intent,
    IntentSource,
    Keyword,
    KeywordRevision,
    KeywordStatus,
)

__all__ = ["ClassifyResult", "classify_keywords"]

REASON = "classification automatique"


@dataclass(frozen=True, slots=True)
class ClassifyResult:
    considered: int
    classified: int
    unmatched: int
    locked: int
    by_intent: dict[str, int]


def classify_keywords(
    session: Session,
    lang: str | None = None,
    *,
    include_commercial: bool = True,
) -> ClassifyResult:
    """Applique les règles d'intention aux mots-clés non verrouillés.

    `include_commercial` active le tier à confiance plus faible, tenu
    séparé des trois autres dans intent_classifier.py. Il est actif par
    défaut ici : sur un corpus de plusieurs milliers de mots-clés, une
    intention approximative vaut mieux qu'aucune, et `matched_rule`
    garde la trace de la règle employée pour un contrôle par sondage.
    """
    statement = select(Keyword).where(
        Keyword.status == KeywordStatus.ACTIVE,
        Keyword.intent_source != IntentSource.MANUAL,
    )
    if lang:
        statement = statement.where(Keyword.lang == lang)

    candidates = list(session.exec(statement).all())

    locked_statement = select(Keyword).where(
        Keyword.intent_source == IntentSource.MANUAL
    )
    if lang:
        locked_statement = locked_statement.where(Keyword.lang == lang)
    locked = len(session.exec(locked_statement).all())

    classified = 0
    counts: Counter[str] = Counter()

    for keyword in candidates:
        matched = classify_intent(keyword.keyword)
        rule: str | None = None

        if matched is not None:
            intent_value, rule = matched
        elif include_commercial:
            fallback = classify_commercial_fallback(keyword.keyword)
            if fallback is None:
                continue
            intent_value, rule = fallback
        else:
            continue

        try:
            intent = Intent(intent_value)
        except ValueError:
            continue

        if keyword.intent is not intent:
            session.add(
                KeywordRevision(
                    keyword_id=keyword.id,  # type: ignore[arg-type]
                    field_name="intent",
                    old_value=keyword.intent.value if keyword.intent else None,
                    new_value=intent.value,
                    changed_by_id=None,
                    reason=REASON,
                )
            )
        keyword.intent = intent
        keyword.intent_source = IntentSource.AUTO
        keyword.matched_rule = (rule or "")[:255] or None
        classified += 1
        counts[intent.value] += 1

    return ClassifyResult(
        considered=len(candidates),
        classified=classified,
        unmatched=len(candidates) - classified,
        locked=locked,
        by_intent=dict(counts.most_common()),
    )
