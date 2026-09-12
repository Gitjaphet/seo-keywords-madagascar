"""Application des corrections d'audit qui ne demandent aucun arbitrage.

Deux familles seulement : les marques concurrentes et les mots-clés hors
sujet. Toutes deux reposent sur des listes explicites, relues et
vérifiées sur pièces — pas sur un score.

Les fusions en sont volontairement exclues. Le contrôle sur la paire la
plus proche du corpus (219/267, similarité 0.957) a montré un faux
positif : le modèle rapproche « safari madagascar » du film d'animation
parce qu'ils partagent le vocabulaire. Aucun seuil n'est sûr ici, la
fusion reste un arbitrage humain.
"""

from dataclasses import dataclass

from sqlmodel import Session, select

from seo_keywords.analysis.cluster_qa import find_brand_hits, find_off_topic_hits
from seo_keywords.storage.models import (
    Cluster,
    ClusteringRun,
    ClusterStatus,
    Keyword,
    KeywordRevision,
    KeywordStatus,
)

__all__ = ["FixResult", "apply_safe_fixes"]

REASON = "audit automatique"


@dataclass(frozen=True, slots=True)
class FixResult:
    run_id: int
    competitors: int
    off_topic: int
    clusters_discarded: int
    examples: list[str]


def _set_status(
    session: Session, keyword: Keyword, status: KeywordStatus, reason: str
) -> bool:
    if keyword.status is status:
        return False
    session.add(
        KeywordRevision(
            keyword_id=keyword.id,  # type: ignore[arg-type]
            field_name="status",
            old_value=keyword.status.value,
            new_value=status.value,
            changed_by_id=None,
            reason=reason,
        )
    )
    keyword.status = status
    return True


def apply_safe_fixes(session: Session, run_id: int | None = None) -> FixResult:
    """Écarte les mots-clés de marque et hors sujet.

    Un cluster dont TOUS les mots-clés sont écartés passe en DISCARDED :
    il ne représente plus rien.
    """
    if run_id is None:
        latest = session.exec(
            select(ClusteringRun).order_by(ClusteringRun.id.desc())  # type: ignore[union-attr]
        ).first()
        if latest is None:
            return FixResult(0, 0, 0, 0, [])
        run_id = latest.id  # type: ignore[assignment]

    clusters = session.exec(select(Cluster).where(Cluster.run_id == run_id)).all()

    competitors = off_topic = discarded = 0
    examples: list[str] = []

    for cluster in clusters:
        members = session.exec(
            select(Keyword).where(Keyword.cluster_id == cluster.id)
        ).all()
        if not members:
            continue

        labels = sorted({m.keyword for m in members})
        brands = set(find_brand_hits(labels))
        topics = set(find_off_topic_hits(labels)) - brands

        for member in members:
            if member.keyword in brands:
                if _set_status(
                    session, member, KeywordStatus.COMPETITOR, f"{REASON} : marque"
                ):
                    competitors += 1
                    if len(examples) < 10:
                        examples.append(f"marque    {member.keyword}")
            elif member.keyword in topics and _set_status(
                session, member, KeywordStatus.EXCLUDED, f"{REASON} : hors sujet"
            ):
                off_topic += 1
                if len(examples) < 10:
                    examples.append(f"hors sujet {member.keyword}")

        # Un cluster entièrement vidé n'a plus d'objet.
        if len(brands | topics) == len(labels):
            cluster.status = ClusterStatus.DISCARDED
            cluster.notes = (cluster.notes or "") + f" [{REASON} : cluster vide]"
            discarded += 1

    return FixResult(
        run_id=run_id,  # type: ignore[arg-type]
        competitors=competitors,
        off_topic=off_topic,
        clusters_discarded=discarded,
        examples=examples,
    )
