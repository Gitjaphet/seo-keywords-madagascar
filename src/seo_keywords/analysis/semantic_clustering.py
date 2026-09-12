"""Clustering sémantique multilingue des mots-clés.

Remplace le regroupement par seed (10 règles, 7 clusters) par un
regroupement fondé sur le sens : chaque libellé devient un vecteur, et
les vecteurs proches forment un cluster.

Deux choix de conception méritent une explication.

`linkage="complete"` plutôt que `"average"` : en moyenne, les groupes
fusionnent de proche en proche (A ressemble à B, B à C, C à D) et un
cluster géant absorbe tout le corpus — mesuré à 966 libellés sur 1347.
Le lien complet exige que *tous* les membres soient proches entre eux.

Le retrait des termes de destination avant encodage : « madagascar » et
« nosy be » apparaissent dans la majorité du corpus et saturent le
signal. Le modèle voyait « ces deux requêtes parlent de Nosy Be »
plutôt que « l'une veut réserver, l'autre veut s'informer ». Les
libellés stockés en base restent intacts ; seul le calcul les ignore.
"""

import re
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sqlmodel import Session, select

from seo_keywords.storage.models import (
    Cluster,
    ClusteringRun,
    ClusterSource,
    Keyword,
    KeywordMetric,
    KeywordRevision,
    KeywordStatus,
)

__all__ = [
    "DEFAULT_LINKAGE",
    "DEFAULT_MODEL",
    "DEFAULT_NOISE_PATTERN",
    "DEFAULT_THRESHOLD",
    "ClusteringResult",
    "assign_groups",
    "pick_head_index",
    "run_clustering",
    "strip_noise",
]

DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
# Validé empiriquement : 203 clusters, 32 isolés, plus gros groupe à 49.
# À 0.50 la distinction entre 'holidays' et 'vacation' se perd.
DEFAULT_THRESHOLD = 0.40
DEFAULT_LINKAGE = "complete"
DEFAULT_NOISE_PATTERN = r"\b(madagascar|madagaskar|nosy\s*be|hell\s*ville)\b"

REVISION_REASON = "clustering sémantique"


@dataclass(frozen=True, slots=True)
class ClusteringResult:
    run_id: int
    cluster_count: int
    keyword_count: int
    locked_count: int
    singleton_count: int
    largest_size: int


def strip_noise(text: str, pattern: str = DEFAULT_NOISE_PATTERN) -> str:
    """Retire les termes omniprésents avant encodage.

    Si le libellé n'est composé que de bruit ('madagascar' seul), on le
    conserve tel quel : mieux vaut un vecteur peu discriminant qu'une
    chaîne vide.
    """
    if not pattern:
        return text
    cleaned = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or text


def assign_groups(
    vectors: np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
    linkage: str = DEFAULT_LINKAGE,
) -> np.ndarray:
    """Regroupe les vecteurs. Renvoie un numéro de groupe par vecteur.

    Le seuil est une DISTANCE cosinus : 0.40 regroupe ce qui a une
    similarité d'au moins 0.60.
    """
    if len(vectors) == 0:
        return np.array([], dtype=int)
    if len(vectors) == 1:
        return np.array([0], dtype=int)

    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold,
        metric="cosine",
        linkage=linkage,
    )
    return model.fit_predict(vectors)


def pick_head_index(
    member_indices: list[int],
    vectors: np.ndarray,
    volumes: list[int | None],
) -> int:
    """Désigne le mot-clé principal du groupe.

    La méthode de référence est le plus gros volume de recherche : c'est
    lui qui ira dans le title et le H1. Faute de volume — Google Ads ne
    chiffre pas la longue traîne —, on retombe sur la centralité
    sémantique, c'est-à-dire le libellé le plus proche du centre du
    groupe. C'est un substitut assumé, pas la norme du métier.
    """
    if len(member_indices) == 1:
        return member_indices[0]

    known = [(volumes[i], i) for i in member_indices if volumes[i] is not None]
    if known:
        return max(known)[1]

    subset = vectors[member_indices]
    centroid = subset.mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm:
        centroid = centroid / norm
    similarities = subset @ centroid
    return member_indices[int(similarities.argmax())]


def _load_volumes(session: Session, keyword_ids: list[int]) -> dict[int, int]:
    """Volume le plus élevé connu par mot-clé, tous marchés confondus.

    Un mot-clé peut avoir plusieurs relevés (France, Belgique, plusieurs
    dates) : on retient le maximum, qui représente son meilleur marché.
    """
    best: dict[int, int] = {}
    metrics = session.exec(
        select(KeywordMetric).where(KeywordMetric.keyword_id.in_(keyword_ids))  # type: ignore[attr-defined]
    ).all()
    for metric in metrics:
        if metric.search_volume is None:
            continue
        current = best.get(metric.keyword_id)
        if current is None or metric.search_volume > current:
            best[metric.keyword_id] = metric.search_volume
    return best


def _encode(labels: list[str], model_name: str) -> np.ndarray:
    """Import différé : charger le modèle coûte une dizaine de secondes,
    inutile de le payer à l'import du module ni dans les tests."""
    import logging
    import os

    # Le modèle est en cache local : inutile d'interroger Hugging Face à
    # chaque lancement. Rend la commande utilisable hors ligne et évite
    # une quinzaine de requêtes réseau dans le cron.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    for name in ("httpx", "huggingface_hub", "sentence_transformers", "transformers"):
        logging.getLogger(name).setLevel(logging.WARNING)

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    return model.encode(labels, batch_size=64, normalize_embeddings=True)


def run_clustering(
    session: Session,
    *,
    model_name: str = DEFAULT_MODEL,
    threshold: float = DEFAULT_THRESHOLD,
    linkage: str = DEFAULT_LINKAGE,
    noise_pattern: str = DEFAULT_NOISE_PATTERN,
    notes: str = "",
) -> ClusteringResult:
    """Recalcule les clusters et les écrit en base.

    Ne touche jamais un mot-clé dont `cluster_source` vaut MANUAL : un
    déplacement décidé à la main survit à tous les recalculs.
    """
    keywords = list(
        session.exec(
            select(Keyword).where(Keyword.status == KeywordStatus.ACTIVE)
        ).all()
    )
    movable = [k for k in keywords if not k.cluster_is_locked]
    locked_count = len(keywords) - len(movable)

    # Un libellé identique collecté en fr et en en (artefact de seeds
    # partagés) doit donner UN vecteur et UN cluster, sinon il pèse
    # double dans la taille du groupe.
    by_label: dict[str, list[Keyword]] = defaultdict(list)
    for keyword in movable:
        by_label[keyword.keyword].append(keyword)
    labels = sorted(by_label)

    vectors = _encode([strip_noise(label, noise_pattern) for label in labels], model_name)
    groups = assign_groups(vectors, threshold=threshold, linkage=linkage)

    volume_by_id = _load_volumes(
        session, [k.id for k in movable if k.id is not None]
    )
    # Volume du libellé = meilleur volume parmi les lignes qui le portent.
    label_volumes: list[int | None] = []
    for label in labels:
        candidates = [
            volume_by_id[k.id]
            for k in by_label[label]
            if k.id is not None and k.id in volume_by_id
        ]
        label_volumes.append(max(candidates) if candidates else None)

    run = ClusteringRun(
        model_name=model_name,
        distance_threshold=threshold,
        linkage=linkage,
        noise_pattern=noise_pattern,
        keyword_count=len(movable),
        notes=notes,
    )
    session.add(run)
    session.flush()

    members: dict[int, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        members[int(group)].append(index)

    singleton_count = 0
    largest_size = 0

    for member_indices in members.values():
        head_index = pick_head_index(member_indices, vectors, label_volumes)
        group_keywords = [k for i in member_indices for k in by_label[labels[i]]]
        head_keyword = by_label[labels[head_index]][0]

        total_volume = sum(
            volume_by_id.get(k.id, 0) for k in group_keywords if k.id is not None
        )
        cluster = Cluster(
            run_id=run.id,  # type: ignore[arg-type]
            keyword_count=len(group_keywords),
            total_volume=total_volume,
        )
        session.add(cluster)
        session.flush()
        cluster.head_keyword_id = head_keyword.id

        for keyword in group_keywords:
            _apply_cluster(session, keyword, cluster.id)

        if len(member_indices) == 1:
            singleton_count += 1
        largest_size = max(largest_size, len(group_keywords))

    run.cluster_count = len(members)

    return ClusteringResult(
        run_id=run.id,  # type: ignore[arg-type]
        cluster_count=len(members),
        keyword_count=len(movable),
        locked_count=locked_count,
        singleton_count=singleton_count,
        largest_size=largest_size,
    )


def _apply_cluster(session: Session, keyword: Keyword, cluster_id: int | None) -> None:
    """Rattache un mot-clé à son cluster, en journalisant le changement."""
    if keyword.cluster_id == cluster_id:
        return
    session.add(
        KeywordRevision(
            keyword_id=keyword.id,  # type: ignore[arg-type]
            field_name="cluster_id",
            old_value=None if keyword.cluster_id is None else str(keyword.cluster_id),
            new_value=None if cluster_id is None else str(cluster_id),
            changed_by_id=None,
            reason=REVISION_REASON,
        )
    )
    keyword.cluster_id = cluster_id
    keyword.cluster_source = ClusterSource.AUTO
