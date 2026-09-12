"""Modèles de données persistés en base.

La base est la source de vérité du projet : les CSV sont des exports,
jamais des états intermédiaires.

Règle centrale : une décision humaine n'est jamais écrasée par le
pipeline automatique. Cette garantie repose sur les champs `*_source`,
que les traitements par lot doivent filtrer sur la valeur AUTO.
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Column, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel

__all__ = [
    "Cluster",
    "ClusterSource",
    "ClusterStatus",
    "ClusteringRun",
    "Intent",
    "IntentSource",
    "Keyword",
    "KeywordMetric",
    "KeywordRecord",
    "KeywordRevision",
    "KeywordStatus",
    "MetricSource",
    "SeasonalityRecord",
    "User",
]


def _now() -> datetime:
    return datetime.now(UTC)


def _enum_values(enum_cls: type[Enum]) -> list[str]:
    """Stocke les enums par leur valeur ('auto') et non par leur nom
    ('AUTO') : c'est cette forme qui circulera dans l'API et le
    dashboard."""
    return [member.value for member in enum_cls]


class Intent(str, Enum):
    """Intention de recherche. COMMERCIAL est un tier à confiance plus
    faible, tenu séparé des trois autres (cf. intent_classifier.py)."""

    NAVIGATIONNEL = "navigationnel"
    TRANSACTIONNEL = "transactionnel"
    COMMERCIAL = "commercial"
    INFORMATIONNEL = "informationnel"


class IntentSource(str, Enum):
    """Origine de la valeur d'intention. AUTO est réécrasable par le
    pipeline, MANUAL ne l'est jamais, UNSET signale une révision à faire."""

    UNSET = "unset"
    AUTO = "auto"
    MANUAL = "manual"


class ClusterSource(str, Enum):
    """Même logique que IntentSource, appliquée au regroupement.

    Un mot-clé déplacé à la main dans un autre cluster garde MANUAL et
    survit aux recalculs mensuels.
    """

    UNSET = "unset"
    AUTO = "auto"
    MANUAL = "manual"


class KeywordStatus(str, Enum):
    ACTIVE = "active"
    EXCLUDED = "excluded"  # rejeté définitivement, ne revient pas en révision
    COMPETITOR = "competitor"  # marque concurrente
    ARCHIVED = "archived"  # masqué du dashboard, conservé en base


class ClusterStatus(str, Enum):
    """Cycle de vie éditorial d'un cluster.

    C'est le suivi du plan de contenu : où en est la page qui vise ce
    groupe de mots-clés.
    """

    TO_CREATE = "to_create"  # aucune page ne le cible encore
    PUBLISHED = "published"  # une page existe (target_url renseignée)
    TO_MERGE = "to_merge"  # doublon d'un autre cluster, à fusionner
    DISCARDED = "discarded"  # hors sujet ou hors de portée


class MetricSource(str, Enum):
    GOOGLE_ADS = "google_ads"
    GOOGLE_TRENDS = "google_trends"
    SEARCH_CONSOLE = "search_console"


class User(SQLModel, table=True):
    __tablename__ = "user"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=255)
    hashed_password: str = Field(max_length=255)
    display_name: str = Field(default="", max_length=120)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_now)

    revisions: list["KeywordRevision"] = Relationship(back_populates="changed_by")


class ClusteringRun(SQLModel, table=True):
    """Trace d'un recalcul de regroupement.

    Chaque exécution mensuelle crée un run. Conserver les paramètres
    exacts permet de comparer deux recalculs : quels clusters ont
    fusionné, lesquels se sont scindés, lesquels sont apparus.
    Sans ça, un changement de résultat est ininterprétable.
    """

    __tablename__ = "clustering_run"

    id: int | None = Field(default=None, primary_key=True)

    model_name: str = Field(max_length=120)
    distance_threshold: float
    linkage: str = Field(default="complete", max_length=20)
    # Motif retiré des libellés avant encodage : les termes présents
    # partout (madagascar, nosy be) saturent le signal et masquent les
    # différences d'intention.
    noise_pattern: str = Field(default="", max_length=255)

    keyword_count: int = Field(default=0)
    cluster_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=_now, index=True)
    notes: str = Field(default="", max_length=500)

    clusters: list["Cluster"] = Relationship(back_populates="run")


class Cluster(SQLModel, table=True):
    """Un groupe de mots-clés partageant la même intention.

    Règle métier : un cluster = une page, jamais deux. Deux clusters
    pointant vers la même target_url signalent une cannibalisation,
    c'est-à-dire deux pages qui se disputent les mêmes requêtes et se
    pénalisent mutuellement.

    L'identifiant est volontairement opaque : le mot-clé principal peut
    changer d'un recalcul à l'autre, pas l'identité du cluster.
    """

    __tablename__ = "cluster"

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="clustering_run.id", index=True)

    # Mot-clé principal : la cible du title et du H1. Choisi sur le plus
    # gros volume quand il est connu, sur la centralité sémantique sinon.
    # FK circulaire avec keyword.cluster_id, d'où le use_alter : SQLite
    # ne peut pas créer les deux tables sans différer une contrainte.
    head_keyword_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("keyword.id", use_alter=True), nullable=True
        ),
    )

    # URL de la page qui vise ce cluster. Vide = page à écrire.
    target_url: str | None = Field(default=None, index=True, max_length=500)
    status: ClusterStatus = Field(
        default=ClusterStatus.TO_CREATE,
        sa_column=Column(
            SAEnum(ClusterStatus, values_callable=_enum_values),
            index=True,
            nullable=False,
            server_default=ClusterStatus.TO_CREATE.value,
        ),
    )

    keyword_count: int = Field(default=0)
    # Somme des volumes connus du groupe. Null-safe : un volume absent
    # vaut zéro ici, mais ne signifie pas que le mot-clé est sans valeur
    # (Google Ads ne chiffre pas la longue traîne).
    total_volume: int = Field(default=0, index=True)
    notes: str = Field(default="", max_length=500)
    created_at: datetime = Field(default_factory=_now)
    # Une validation humaine étalée sur 203 clusters et plusieurs
    # sessions a besoin de savoir où elle s'est arrêtée : TO_CREATE ne
    # distingue pas « relu et gardé » de « jamais regardé ».
    reviewed_at: datetime | None = Field(default=None, index=True)
    reviewed_by_id: int | None = Field(default=None, foreign_key="user.id")

    run: ClusteringRun = Relationship(back_populates="clusters")
    keywords: list["Keyword"] = Relationship(
        back_populates="cluster_ref",
        sa_relationship_kwargs={"foreign_keys": "[Keyword.cluster_id]"},
    )
    head_keyword: "Keyword" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Cluster.head_keyword_id]"},
    )


class Keyword(SQLModel, table=True):
    """Un mot-clé collecté, dans une langue donnée.

    Remplace l'ancien KeywordRecord dont il conserve tous les noms de
    champs (`source`, `collected_at`) pour ne rien casser côté curation.

    Un même libellé collecté dans deux langues (`safari madagascar`
    existe en fr et en it) donne deux lignes distinctes : le cluster et
    l'intention peuvent diverger d'un marché à l'autre.
    """

    __tablename__ = "keyword"
    __table_args__ = (UniqueConstraint("keyword", "lang", name="uq_keyword_lang"),)

    id: int | None = Field(default=None, primary_key=True)

    keyword: str = Field(index=True, max_length=255)
    lang: str = Field(index=True, max_length=5)
    source: str = Field(default="autocomplete", index=True, max_length=50)
    seed: str = Field(default="", index=True, max_length=255)
    collected_at: datetime = Field(default_factory=_now)

    intent: Intent | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(Intent, values_callable=_enum_values), index=True, nullable=True
        ),
    )
    intent_source: IntentSource = Field(
        default=IntentSource.UNSET,
        sa_column=Column(
            SAEnum(IntentSource, values_callable=_enum_values),
            index=True,
            nullable=False,
            server_default=IntentSource.UNSET.value,
        ),
    )
    matched_rule: str | None = Field(default=None, max_length=255)

    cluster_id: int | None = Field(
        default=None, foreign_key="cluster.id", index=True
    )
    cluster_source: ClusterSource = Field(
        default=ClusterSource.UNSET,
        sa_column=Column(
            SAEnum(ClusterSource, values_callable=_enum_values),
            index=True,
            nullable=False,
            server_default=ClusterSource.UNSET.value,
        ),
    )
    # Ancien regroupement par seed, conservé le temps de valider le
    # clustering sémantique. À supprimer dans une migration ultérieure.
    cluster: str | None = Field(default=None, max_length=100)

    status: KeywordStatus = Field(
        default=KeywordStatus.ACTIVE,
        sa_column=Column(
            SAEnum(KeywordStatus, values_callable=_enum_values),
            index=True,
            nullable=False,
            server_default=KeywordStatus.ACTIVE.value,
        ),
    )
    notes: str = Field(default="", max_length=500)

    # Nombre de collectes distinctes ayant remonté ce mot-clé. Seul signal
    # de popularité disponible sur la longue traîne, que Google Ads ne
    # chiffre pas (volume absent sous le seuil publicitaire).
    autocomplete_depth: int = Field(default=1)

    last_seen_at: datetime = Field(default_factory=_now, index=True)
    reviewed_at: datetime | None = Field(default=None)
    reviewed_by_id: int | None = Field(default=None, foreign_key="user.id")

    cluster_ref: Cluster | None = Relationship(
        back_populates="keywords",
        sa_relationship_kwargs={"foreign_keys": "[Keyword.cluster_id]"},
    )
    metrics: list["KeywordMetric"] = Relationship(
        back_populates="keyword_ref",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    revisions: list["KeywordRevision"] = Relationship(
        back_populates="keyword_ref",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "foreign_keys": "[KeywordRevision.keyword_id]",
        },
    )

    @property
    def is_locked(self) -> bool:
        """Vrai si le pipeline automatique doit passer son chemin."""
        return (
            self.intent_source is IntentSource.MANUAL
            or self.status is not KeywordStatus.ACTIVE
        )

    @property
    def cluster_is_locked(self) -> bool:
        """Vrai si le recalcul ne doit pas réaffecter ce mot-clé."""
        return self.cluster_source is ClusterSource.MANUAL


# Ancien nom, conservé le temps que curation.py, repository.py et les
# tests migrent. Même classe, donc aucun risque de divergence.
KeywordRecord = Keyword


class KeywordMetric(SQLModel, table=True):
    """Métriques externes, une ligne par mot-clé, marché et relevé.

    Le marché est distinct de la langue : le français se cherche depuis
    la France, la Belgique, la Suisse et La Réunion, avec des volumes
    différents. L'historique des relevés permet de suivre l'évolution
    d'un mot-clé dans le temps.
    """

    __tablename__ = "keyword_metric"
    __table_args__ = (
        UniqueConstraint(
            "keyword_id", "market", "source", "fetched_at", name="uq_metric_snapshot"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    keyword_id: int = Field(foreign_key="keyword.id", index=True)

    market: str = Field(index=True, max_length=5)  # code ISO-2, '' = mondial
    language: str = Field(default="", max_length=5)

    # Google Ads ne renvoie que des représentants de tranche (10, 50, 500,
    # 5000, 50000) sur un compte sans dépense publicitaire. Le booléen
    # empêche de confondre ces paliers avec une mesure réelle.
    search_volume: int | None = Field(default=None)
    volume_is_bucketed: bool = Field(default=True)

    # Concurrence PUBLICITAIRE, jamais difficulté SEO : mesure le nombre
    # d'annonceurs sur l'enchère, pas les backlinks à rattraper.
    ads_competition_index: int | None = Field(default=None)  # 0-100
    ads_competition_label: str | None = Field(default=None, max_length=20)

    cpc_low: Decimal | None = Field(default=None, sa_column=Column(Numeric(14, 2)))
    cpc_high: Decimal | None = Field(default=None, sa_column=Column(Numeric(14, 2)))
    currency: str = Field(default="", max_length=3)

    source: MetricSource = Field(
        default=MetricSource.GOOGLE_ADS,
        sa_column=Column(
            SAEnum(MetricSource, values_callable=_enum_values),
            index=True,
            nullable=False,
        ),
    )
    fetched_at: datetime = Field(default_factory=_now, index=True)

    keyword_ref: Keyword = Relationship(back_populates="metrics")


class KeywordRevision(SQLModel, table=True):
    """Journal d'audit : une ligne par champ modifié.

    Répond à « pourquoi ce mot-clé est-il classé ainsi ? » plusieurs mois
    après coup, et rend tout changement réversible.
    """

    __tablename__ = "keyword_revision"

    id: int | None = Field(default=None, primary_key=True)
    keyword_id: int = Field(foreign_key="keyword.id", index=True)

    field_name: str = Field(max_length=50)
    old_value: str | None = Field(default=None, max_length=255)
    new_value: str | None = Field(default=None, max_length=255)

    # None = modification faite par le pipeline automatique.
    changed_by_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    changed_at: datetime = Field(default_factory=_now, index=True)
    reason: str = Field(default="", max_length=255)

    keyword_ref: Keyword = Relationship(
        back_populates="revisions",
        sa_relationship_kwargs={"foreign_keys": "[KeywordRevision.keyword_id]"},
    )
    changed_by: User | None = Relationship(back_populates="revisions")


class SeasonalityRecord(SQLModel, table=True):
    """Score d'intérêt mensuel (Google Trends) pour un mot-clé et un marché.

    Volontairement laissé inchangé : ces données sont re-téléchargeables
    et ne contiennent aucune décision humaine à protéger.
    """

    id: int | None = Field(default=None, primary_key=True)
    keyword: str = Field(index=True)
    geo: str = Field(index=True, description="'' = mondial, sinon code pays ISO-2")
    month: int  # 1-12
    interest_score: float  # 0-100, relatif au lot de mots-clés interrogé
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
