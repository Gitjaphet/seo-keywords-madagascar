"""Scission d'un cluster trop large en sous-clusters.

Le seuil global (0.40) est un compromis : il convient à la majorité du
corpus mais laisse quelques fourre-tout. Plutôt que de baisser le seuil
partout — ce qui émietterait les bons clusters —, on le baisse
localement sur les clusters concernés.

Les mots-clés scindés passent en `cluster_source = MANUAL` : la décision
est définitive et survit à tous les recalculs. C'est le principe même de
la validation humaine — elle prime sur l'algorithme, pour toujours.
"""

from collections import Counter
from dataclasses import dataclass

import numpy as np
from sqlmodel import Session, select

from seo_keywords.analysis.semantic_clustering import (
    DEFAULT_LINKAGE,
    DEFAULT_MODEL,
    DEFAULT_NOISE_PATTERN,
    _encode,
    assign_groups,
    pick_head_index,
    strip_noise,
)
from seo_keywords.storage.models import (
    Cluster,
    ClusterSource,
    ClusterStatus,
    Keyword,
    KeywordMetric,
    KeywordRevision,
)

__all__ = ["SplitResult", "split_cluster"]

REASON = "scission manuelle"


@dataclass(frozen=True, slots=True)
class SplitResult:
    source_cluster_id: int
    new_cluster_ids: list[int]
    sizes: list[int]
    heads: list[str]


def split_cluster(
    session: Session,
    cluster_id: int,
    threshold: float,
    *,
    by_lang: bool = False,
    model_name: str = DEFAULT_MODEL,
    linkage: str = DEFAULT_LINKAGE,
    noise_pattern: str = DEFAULT_NOISE_PATTERN,
) -> SplitResult:
    """Redécoupe un cluster à un seuil plus strict.

    Le cluster d'origine est vidé et marqué DISCARDED, avec une note
    renvoyant vers les nouveaux. Son identifiant reste en base : les
    révisions qui le mentionnent doivent rester lisibles.
    """
    source = session.get(Cluster, cluster_id)
    if source is None:
        raise ValueError(f"cluster {cluster_id} introuvable")

    members = list(
        session.exec(select(Keyword).where(Keyword.cluster_id == cluster_id)).all()
    )
    if len(members) < 2:
        return SplitResult(cluster_id, [], [], [])

    by_label: dict[str, list[Keyword]] = {}
    for member in members:
        by_label.setdefault(member.keyword, []).append(member)
    labels = sorted(by_label)

    vectors = _encode(
        [strip_noise(label, noise_pattern) for label in labels], model_name
    )

    if by_lang:
        # Un libellé collecté en plusieurs langues suit sa langue
        # majoritaire ; toutes ses lignes restent ensemble.
        lang_of: dict[str, str] = {}
        for label, rows in by_label.items():
            counts = Counter(r.lang for r in rows)
            lang_of[label] = min(counts, key=lambda x: (-counts[x], x))

        groups = np.empty(len(labels), dtype=int)
        offset = 0
        for lang in sorted(set(lang_of.values())):
            positions = [i for i, label in enumerate(labels) if lang_of[label] == lang]
            local = assign_groups(
                vectors[positions], threshold=threshold, linkage=linkage
            )
            for position, group in zip(positions, local, strict=True):
                groups[position] = offset + int(group)
            offset += int(local.max()) + 1 if len(local) else 0
    else:
        groups = assign_groups(vectors, threshold=threshold, linkage=linkage)

    volumes: dict[int, int] = {}
    for metric in session.exec(
        select(KeywordMetric).where(
            KeywordMetric.keyword_id.in_([m.id for m in members if m.id])  # type: ignore[attr-defined]
        )
    ).all():
        if metric.search_volume is None:
            continue
        current = volumes.get(metric.keyword_id)
        if current is None or metric.search_volume > current:
            volumes[metric.keyword_id] = metric.search_volume

    label_volumes: list[int | None] = []
    for label in labels:
        found = [volumes[k.id] for k in by_label[label] if k.id in volumes]
        label_volumes.append(max(found) if found else None)

    indices_by_group: dict[int, list[int]] = {}
    for index, group in enumerate(groups):
        indices_by_group.setdefault(int(group), []).append(index)

    new_ids: list[int] = []
    sizes: list[int] = []
    heads: list[str] = []

    for member_indices in indices_by_group.values():
        head_index = pick_head_index(
            member_indices, vectors, label_volumes, labels
        )
        group_keywords = [k for i in member_indices for k in by_label[labels[i]]]
        head_keyword = by_label[labels[head_index]][0]

        child = Cluster(
            run_id=source.run_id,
            keyword_count=len(group_keywords),
            total_volume=sum(
                volumes.get(k.id, 0) for k in group_keywords if k.id
            ),
            notes=(
                f"issu de la scission du cluster {cluster_id}"
                + (" (par langue)" if by_lang else "")
            ),
        )
        session.add(child)
        session.flush()
        child.head_keyword_id = head_keyword.id

        for keyword in group_keywords:
            session.add(
                KeywordRevision(
                    keyword_id=keyword.id,  # type: ignore[arg-type]
                    field_name="cluster_id",
                    old_value=str(cluster_id),
                    new_value=str(child.id),
                    changed_by_id=None,
                    reason=REASON,
                )
            )
            keyword.cluster_id = child.id
            # Verrou : la décision survit à tous les recalculs futurs.
            keyword.cluster_source = ClusterSource.MANUAL

        new_ids.append(child.id)  # type: ignore[arg-type]
        sizes.append(len(group_keywords))
        heads.append(head_keyword.keyword)

    source.status = ClusterStatus.DISCARDED
    source.keyword_count = 0
    source.notes = (
        (source.notes or "")
        + f" [scindé en {', '.join(str(i) for i in new_ids)}]"
    ).strip()

    order = np.argsort([-s for s in sizes])
    return SplitResult(
        source_cluster_id=cluster_id,
        new_cluster_ids=[new_ids[i] for i in order],
        sizes=[sizes[i] for i in order],
        heads=[heads[i] for i in order],
    )
