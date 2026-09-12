"""Déclinaison des clusters en pages, une par langue.

Un cluster est une intention de recherche ; une page en est la
réalisation dans une langue. Le cluster « requin-baleine » donne trois
pages — fr, en, it — qui sont par construction les traductions les unes
des autres.

Séparé du clustering à dessein : après avoir fusionné deux clusters à la
main, on veut régénérer les pages sans relancer l'encodage complet.

Garantie d'idempotence : régénérer ne détruit jamais une décision
humaine. `target_url`, `status`, `notes` et `reviewed_at` sont préservés
sur une page existante ; seuls le head et le décompte sont rafraîchis.
"""

from dataclasses import dataclass

from sqlmodel import Session, select

from seo_keywords.analysis.cluster_export import LOCAL_PLACES
from seo_keywords.analysis.language_detector import detect_language
from seo_keywords.storage.models import (
    Cluster,
    ClusteringRun,
    ClusterPage,
    Keyword,
    KeywordMetric,
)

__all__ = ["BuildPagesResult", "build_pages", "pick_page_head"]


@dataclass(frozen=True, slots=True)
class BuildPagesResult:
    run_id: int
    created: int
    updated: int
    preserved: int
    pages_by_lang: dict[str, int]


def pick_page_head(
    candidates: list[Keyword], volumes: dict[int, int]
) -> Keyword:
    """Désigne le mot-clé principal d'une page, au sein d'une langue.

    Par ordre de priorité :
      1. le plus gros volume de recherche connu — la règle du métier ;
      2. à défaut, un mot-clé ancré sur un lieu précis de la zone : c'est
         le seul avantage structurel d'une agence locale, autant le
         mettre dans le title ;
      3. à défaut, la formulation la plus courte, presque toujours la
         plus recherchée à sens égal ;
      4. l'ordre alphabétique, pour que le résultat soit déterministe.
    """

    def sort_key(keyword: Keyword) -> tuple[int, int, int, int, str]:
        volume = volumes.get(keyword.id or -1, 0)
        is_local = 1 if LOCAL_PLACES.search(keyword.keyword) else 0
        # `lang` est la langue de COLLECTE, pas celle du libellé : Google
        # remonte des requêtes françaises sous hl=en. Quand le détecteur
        # tranche et contredit, on relègue — il reste silencieux sur la
        # plupart des requêtes courtes, que la relecture humaine traitera.
        detected = detect_language(keyword.keyword)
        mismatch = 1 if detected and detected != keyword.lang else 0
        return (
            mismatch,
            -volume,
            -is_local,
            len(keyword.keyword.split()),
            keyword.keyword,
        )

    return min(candidates, key=sort_key)


def _load_volumes(session: Session, keyword_ids: list[int]) -> dict[int, int]:
    best: dict[int, int] = {}
    if not keyword_ids:
        return best
    for metric in session.exec(
        select(KeywordMetric).where(KeywordMetric.keyword_id.in_(keyword_ids))  # type: ignore[attr-defined]
    ).all():
        if metric.search_volume is None:
            continue
        current = best.get(metric.keyword_id)
        if current is None or metric.search_volume > current:
            best[metric.keyword_id] = metric.search_volume
    return best


def build_pages(
    session: Session,
    run_id: int | None = None,
    min_keywords: int = 1,
) -> BuildPagesResult:
    """Crée ou rafraîchit une page par cluster et par langue.

    `min_keywords` écarte les langues trop peu représentées : une seule
    occurrence allemande dans un cluster français ne justifie pas une
    page allemande.
    """
    if run_id is None:
        latest = session.exec(
            select(ClusteringRun).order_by(ClusteringRun.id.desc())  # type: ignore[union-attr]
        ).first()
        if latest is None:
            return BuildPagesResult(0, 0, 0, 0, {})
        run_id = latest.id  # type: ignore[assignment]

    clusters = session.exec(select(Cluster).where(Cluster.run_id == run_id)).all()

    created = updated = preserved = 0
    pages_by_lang: dict[str, int] = {}

    for cluster in clusters:
        members = session.exec(
            select(Keyword).where(Keyword.cluster_id == cluster.id)
        ).all()
        if not members:
            continue

        volumes = _load_volumes(session, [m.id for m in members if m.id])

        by_lang: dict[str, list[Keyword]] = {}
        for member in members:
            by_lang.setdefault(member.lang, []).append(member)

        for lang, candidates in by_lang.items():
            if len(candidates) < min_keywords:
                continue

            head = pick_page_head(candidates, volumes)
            existing = session.exec(
                select(ClusterPage).where(
                    ClusterPage.cluster_id == cluster.id,
                    ClusterPage.lang == lang,
                )
            ).first()

            if existing is None:
                session.add(
                    ClusterPage(
                        cluster_id=cluster.id,  # type: ignore[arg-type]
                        lang=lang,
                        head_keyword_id=head.id,
                        keyword_count=len(candidates),
                    )
                )
                created += 1
            else:
                # target_url, status, notes et reviewed_at sont la
                # propriété de l'humain : on n'y touche pas.
                if existing.reviewed_at is not None:
                    preserved += 1
                else:
                    existing.head_keyword_id = head.id
                    updated += 1
                existing.keyword_count = len(candidates)

            pages_by_lang[lang] = pages_by_lang.get(lang, 0) + 1

    return BuildPagesResult(
        run_id=run_id,  # type: ignore[arg-type]
        created=created,
        updated=updated,
        preserved=preserved,
        pages_by_lang=dict(sorted(pages_by_lang.items())),
    )
