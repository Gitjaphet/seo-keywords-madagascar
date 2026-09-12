"""Audit automatique des clusters.

Le clustering produit une proposition. Ce module cherche les défauts
mécaniquement repérables, pour que la relecture humaine porte sur une
trentaine de cas au lieu de deux cents.

Il ne juge pas les intentions — c'est un jugement humain, comme le note
déjà curation.py. Il signale ce qui cloche : deux clusters qui disent la
même chose, un cluster qui mélange deux intentions, une marque
concurrente restée en tête, un fourre-tout.
"""

import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum

import numpy as np
from sqlmodel import Session, select

from seo_keywords.analysis.cluster_export import LOCAL_PLACES
from seo_keywords.analysis.curation import COMPETITOR_BRANDS, OFF_TOPIC_PATTERNS
from seo_keywords.analysis.semantic_clustering import (
    DEFAULT_MODEL,
    DEFAULT_NOISE_PATTERN,
    strip_noise,
)
from seo_keywords.storage.models import Cluster, ClusteringRun, Keyword

__all__ = [
    "DEFAULT_MERGE_THRESHOLD",
    "DEFAULT_OVERSIZED",
    "ClusterIssue",
    "IssueKind",
    "audit_clusters",
    "find_brand_hits",
    "find_off_topic_hits",
    "mixed_intent_ratio",
]

# Deux centroïdes au-dessus de ce seuil désignent la même intention.
# Calibré haut : une fusion abusive coûte plus cher qu'un doublon laissé.
DEFAULT_MERGE_THRESHOLD = 0.85
# Au-delà, un cluster n'est plus une page mais une rubrique.
DEFAULT_OVERSIZED = 40
# Proportion minimale de l'intention minoritaire pour parler de mélange.
MIXED_INTENT_FLOOR = 0.30

CONVERTING = {"transactionnel", "commercial"}
INFORMING = {"informationnel"}

_BRAND_RE = re.compile(
    r"\b(" + "|".join(re.escape(b) for b in COMPETITOR_BRANDS) + r")\b",
    re.IGNORECASE,
)
_OFF_TOPIC_RE = re.compile("|".join(OFF_TOPIC_PATTERNS), re.IGNORECASE)


class IssueKind(str, Enum):
    MERGE = "fusionner"
    MIXED_INTENT = "intentions_melangees"
    COMPETITOR = "marque_concurrente"
    OFF_TOPIC = "hors_sujet"
    OVERSIZED = "fourre_tout"


@dataclass(frozen=True, slots=True)
class ClusterIssue:
    cluster_id: int
    kind: IssueKind
    detail: str
    suggestion: str
    auto_applicable: bool


def find_brand_hits(keywords: list[str]) -> list[str]:
    """Mots-clés contenant une marque concurrente connue."""
    return [k for k in keywords if _BRAND_RE.search(k)]


def find_off_topic_hits(keywords: list[str]) -> list[str]:
    """Mots-clés correspondant à un motif hors sujet connu."""
    return [k for k in keywords if _OFF_TOPIC_RE.search(k)]


def mixed_intent_ratio(intents: list[str]) -> float:
    """Part de l'intention minoritaire entre « convertir » et « informer ».

    0 signifie un cluster homogène, 0.5 un mélange parfait. Au-delà de
    MIXED_INTENT_FLOOR, le cluster mérite probablement deux pages : une
    qui capte en amont, une qui convertit.
    """
    converting = sum(1 for i in intents if i in CONVERTING)
    informing = sum(1 for i in intents if i in INFORMING)
    total = converting + informing
    if total == 0:
        return 0.0
    return min(converting, informing) / total


def _encode(labels: list[str], model_name: str) -> np.ndarray:
    import logging
    import os

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    for name in ("httpx", "huggingface_hub", "sentence_transformers", "transformers"):
        logging.getLogger(name).setLevel(logging.WARNING)

    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name).encode(
        labels, batch_size=64, normalize_embeddings=True
    )


def audit_clusters(
    session: Session,
    run_id: int | None = None,
    *,
    model_name: str = DEFAULT_MODEL,
    merge_threshold: float = DEFAULT_MERGE_THRESHOLD,
    oversized: int = DEFAULT_OVERSIZED,
) -> list[ClusterIssue]:
    if run_id is None:
        latest = session.exec(
            select(ClusteringRun).order_by(ClusteringRun.id.desc())  # type: ignore[union-attr]
        ).first()
        if latest is None:
            return []
        run_id = latest.id  # type: ignore[assignment]

    clusters = session.exec(select(Cluster).where(Cluster.run_id == run_id)).all()

    members: dict[int, list[Keyword]] = {}
    for cluster in clusters:
        rows = session.exec(
            select(Keyword).where(Keyword.cluster_id == cluster.id)
        ).all()
        if rows:
            members[cluster.id] = list(rows)  # type: ignore[index]

    issues: list[ClusterIssue] = []
    heads = {c.id: c.head_keyword_id for c in clusters}

    # --- défauts internes à un cluster -----------------------------------
    for cluster_id, rows in members.items():
        labels = sorted({r.keyword for r in rows})
        head = next(
            (r.keyword for r in rows if r.id == heads.get(cluster_id)), labels[0]
        )

        brands = find_brand_hits(labels)
        if brands:
            head_is_brand = bool(_BRAND_RE.search(head))
            issues.append(
                ClusterIssue(
                    cluster_id=cluster_id,
                    kind=IssueKind.COMPETITOR,
                    detail=f"{len(brands)}/{len(labels)} : {', '.join(brands[:3])}",
                    suggestion=(
                        "écarter le cluster (tête = marque)"
                        if head_is_brand
                        else "retirer les mots-clés de marque du cluster"
                    ),
                    auto_applicable=not head_is_brand,
                )
            )

        off_topic = find_off_topic_hits(labels)
        if off_topic:
            issues.append(
                ClusterIssue(
                    cluster_id=cluster_id,
                    kind=IssueKind.OFF_TOPIC,
                    detail=f"{len(off_topic)}/{len(labels)} : {', '.join(off_topic[:3])}",
                    suggestion=(
                        "écarter le cluster"
                        if len(off_topic) > len(labels) / 2
                        else "retirer les mots-clés hors sujet"
                    ),
                    auto_applicable=True,
                )
            )

        intents = [r.intent.value for r in rows if r.intent]
        ratio = mixed_intent_ratio(intents)
        if ratio >= MIXED_INTENT_FLOOR:
            counts = Counter(intents)
            issues.append(
                ClusterIssue(
                    cluster_id=cluster_id,
                    kind=IssueKind.MIXED_INTENT,
                    detail=" ".join(f"{i}:{n}" for i, n in counts.most_common()),
                    suggestion="scinder : une page qui informe, une qui convertit",
                    auto_applicable=False,
                )
            )

        if len(rows) > oversized:
            local = sum(1 for label in labels if LOCAL_PLACES.search(label))
            issues.append(
                ClusterIssue(
                    cluster_id=cluster_id,
                    kind=IssueKind.OVERSIZED,
                    detail=f"{len(rows)} mots-clés, {local} ancrés localement",
                    suggestion="scinder ou baisser le seuil sur ce sous-ensemble",
                    auto_applicable=False,
                )
            )

    # --- doublons entre clusters -----------------------------------------
    ids = sorted(members)
    if len(ids) > 1:
        all_labels: list[str] = []
        spans: list[tuple[int, int]] = []
        for cluster_id in ids:
            labels = sorted({r.keyword for r in members[cluster_id]})
            start = len(all_labels)
            all_labels.extend(strip_noise(x, DEFAULT_NOISE_PATTERN) for x in labels)
            spans.append((start, len(all_labels)))

        vectors = _encode(all_labels, model_name)
        centroids = np.vstack(
            [
                vectors[start:end].mean(axis=0)
                / (np.linalg.norm(vectors[start:end].mean(axis=0)) or 1.0)
                for start, end in spans
            ]
        )
        similarity = centroids @ centroids.T
        np.fill_diagonal(similarity, 0.0)

        seen: set[tuple[int, int]] = set()
        for i, j in zip(*np.where(similarity >= merge_threshold), strict=True):
            pair = (min(int(i), int(j)), max(int(i), int(j)))
            if pair in seen:
                continue
            seen.add(pair)
            left, right = ids[pair[0]], ids[pair[1]]
            issues.append(
                ClusterIssue(
                    cluster_id=left,
                    kind=IssueKind.MERGE,
                    detail=f"similarité {similarity[pair]:.3f} avec le cluster {right}",
                    suggestion=f"fusionner {right} dans {left}",
                    # Jamais automatique : le contrôle sur la paire la
                    # plus proche du corpus (219/267, 0.957) était un
                    # faux positif — « safari madagascar » rapproché du
                    # film d'animation par partage de vocabulaire.
                    auto_applicable=False,
                )
            )

    issues.sort(key=lambda issue: (issue.kind.value, issue.cluster_id))
    return issues
