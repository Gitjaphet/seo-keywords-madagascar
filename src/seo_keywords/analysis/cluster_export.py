"""Export des clusters pour la validation humaine.

Le clustering produit une proposition, pas un verdict. Ce module met les
203 clusters dans un fichier relisible, trié par potentiel réel, avec
des colonnes vides pour les décisions.

Le tri n'est PAS la taille du cluster. Les gros clusters sont les
requêtes génériques (`madagaskar urlaub`, `viaggio madagascar`) où l'on
affronte DERTOUR, Gebeco et Intrepid. Les clusters gagnables sont les
petits, ancrés sur un lieu précis. Chaque composante du score est
exportée séparément pour que le tri reste discutable et re-triable.
"""

import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from seo_keywords.storage.models import (
    Cluster,
    ClusteringRun,
    Keyword,
    KeywordMetric,
)

__all__ = [
    "ClusterRow",
    "build_rows",
    "export_clusters_csv",
    "local_score",
    "region_score",
]

# Lieux précis de la zone d'opération. Une requête qui les mentionne
# vise une prestation locale identifiable, pas Madagascar en général.
LOCAL_PLACES = re.compile(
    r"\b("
    # Secteur de Nosy Be
    r"nosy\s*be|nosybe|nosy\s*iranja|nosy\s*komba|nosy\s*sakatia|"
    r"nosy\s*tanikely|nosy\s*mitsio|nosy\s*ve|hell\s*ville|"
    r"ambatoloaka|andilana|lokobe|mont\s*passot|ankify|djamandjary|"
    r"antsahampano|befotaka|"
    # Nord
    r"diego\s*suarez|antsiranana|ankarana|montagne\s*d.ambre|joffre|"
    r"mer\s*d.emeraude|ramena|"
    # Ouest et allée des baobabs
    r"morondava|baobab|tsingy|bemaraha|kirindy|belo\s*sur\s*mer|"
    r"tsiribihina|miandrivazo|majunga|mahajanga|ankarafantsika|"
    # Sud
    r"tulear|toliara|tuléar|isalo|ranohira|ifaty|anakao|"
    r"fort\s*dauphin|taolagnaro|berenty|"
    # Hauts plateaux et route du sud
    r"antsirabe|ambositra|fianarantsoa|ambalavao|tsaranoro|"
    r"andringitra|ranomafana|zafimaniry|"
    # Est
    r"andasibe|perinet|mantadia|sainte\s*marie|nosy\s*boraha|"
    r"ile\s*aux\s*nattes|tamatave|toamasina|masoala|maroantsetra|"
    r"nosy\s*mangabe|pangalanes|manakara|"
    # Capitale
    r"antananarivo|tananarive"
    r")\b",
    re.IGNORECASE,
)

# Circuits orientés par région ou par façade. Moins discriminants qu'un
# lieu nommé, mais bien plus que le générique : ce sont les circuits nord
# et sud qui portent le chiffre.
REGION_TERMS = re.compile(
    r"\b(nord|norden|north|settentrionale|sud|süden|south|meridionale|"
    r"ouest|westen|west|est|osten|east|orientale|occidentale|"
    r"hauts?\s*plateaux|côte\s*est|cote\s*est|ostküste|costa\s*est)\b",
    re.IGNORECASE,
)

# Intentions qui mènent à une réservation.
CONVERTING_INTENTS = {"transactionnel", "commercial"}

CSV_HEADER = [
    "cluster_id",
    "priorite",
    "n_mots_cles",
    "tete",
    "langue_tete",
    "intention_tete",
    "part_locale",
    "part_region",
    "part_commerciale",
    "concurrence_ads",
    "volume_total",
    "langues",
    "intentions",
    "mots_cles",
    # Colonnes de décision, à remplir à la main.
    "decision",
    "fusionner_avec",
    "url_cible",
    "commentaire",
]


@dataclass(frozen=True, slots=True)
class ClusterRow:
    cluster_id: int
    priority: float
    keyword_count: int
    head: str
    head_lang: str
    head_intent: str
    local_share: float
    region_share: float
    converting_share: float
    ads_competition: float | None
    total_volume: int
    langs: str
    intents: str
    keywords: str


def local_score(keywords: list[str]) -> float:
    """Part des mots-clés mentionnant un lieu précis de la zone."""
    if not keywords:
        return 0.0
    hits = sum(1 for k in keywords if LOCAL_PLACES.search(k))
    return hits / len(keywords)


def region_score(keywords: list[str]) -> float:
    """Part des mots-clés désignant une région ou une façade du pays."""
    if not keywords:
        return 0.0
    hits = sum(1 for k in keywords if REGION_TERMS.search(k))
    return hits / len(keywords)


def _priority(
    local_share: float,
    converting_share: float,
    competition: float | None,
    region_share: float = 0.0,
) -> float:
    """Score de priorité, volontairement simple et lisible.

    Un lieu nommé pèse double : l'intention est précise et la concurrence
    internationale faible. Une région orientée (circuit nord, circuit
    sud) pèse une fois et demie : c'est l'offre structurante de l'agence,
    sur un terrain moins disputé que le générique. La concurrence
    publicitaire, quand elle est connue, pénalise proportionnellement.
    """
    score = 2.0 * local_share + 1.5 * region_share + converting_share
    if competition is not None:
        score -= competition / 100.0
    return round(score, 3)


def build_rows(session: Session, run_id: int | None = None) -> list[ClusterRow]:
    if run_id is None:
        latest = session.exec(
            select(ClusteringRun).order_by(ClusteringRun.id.desc())  # type: ignore[union-attr]
        ).first()
        if latest is None:
            return []
        run_id = latest.id  # type: ignore[assignment]

    clusters = session.exec(
        select(Cluster).where(Cluster.run_id == run_id)
    ).all()

    rows: list[ClusterRow] = []
    for cluster in clusters:
        members = session.exec(
            select(Keyword).where(Keyword.cluster_id == cluster.id)
        ).all()
        if not members:
            continue

        labels = sorted({m.keyword for m in members})
        head = next((m for m in members if m.id == cluster.head_keyword_id), members[0])

        lang_counts = Counter(m.lang for m in members)
        intent_counts = Counter(
            m.intent.value if m.intent else "-" for m in members
        )
        converting = sum(
            count
            for intent, count in intent_counts.items()
            if intent in CONVERTING_INTENTS
        )

        indices = [
            metric.ads_competition_index
            for metric in session.exec(
                select(KeywordMetric).where(
                    KeywordMetric.keyword_id.in_([m.id for m in members])  # type: ignore[attr-defined]
                )
            ).all()
            if metric.ads_competition_index is not None
        ]
        competition = sum(indices) / len(indices) if indices else None

        local_share = round(local_score(labels), 3)
        region_share = round(region_score(labels), 3)
        converting_share = round(converting / len(members), 3)

        rows.append(
            ClusterRow(
                cluster_id=cluster.id,  # type: ignore[arg-type]
                priority=_priority(
                    local_share, converting_share, competition, region_share
                ),
                keyword_count=len(members),
                head=head.keyword,
                head_lang=head.lang,
                head_intent=head.intent.value if head.intent else "-",
                local_share=local_share,
                region_share=region_share,
                converting_share=converting_share,
                ads_competition=round(competition, 1) if competition else None,
                total_volume=cluster.total_volume,
                langs=" ".join(
                    f"{lang}:{n}" for lang, n in lang_counts.most_common()
                ),
                intents=" ".join(
                    f"{intent}:{n}" for intent, n in intent_counts.most_common()
                ),
                keywords=" | ".join(labels),
            )
        )

    rows.sort(key=lambda r: (-r.priority, -r.keyword_count))
    return rows


def export_clusters_csv(rows: list[ClusterRow], output_path: str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for row in rows:
            writer.writerow(
                [
                    row.cluster_id,
                    row.priority,
                    row.keyword_count,
                    row.head,
                    row.head_lang,
                    row.head_intent,
                    row.local_share,
                    row.region_share,
                    row.converting_share,
                    "" if row.ads_competition is None else row.ads_competition,
                    row.total_volume,
                    row.langs,
                    row.intents,
                    row.keywords,
                    "",  # decision
                    "",  # fusionner_avec
                    "",  # url_cible
                    "",  # commentaire
                ]
            )
