"""Tests du clustering sémantique.

Le modèle d'embeddings n'est jamais chargé ici : `_encode` est remplacé
par une fonction déterministe. Les tests valident la logique de
regroupement et les garanties de la base, pas la qualité sémantique du
modèle — celle-ci se mesure par observation, pas par assertion.
"""

import numpy as np
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from seo_keywords.analysis import semantic_clustering as sc
from seo_keywords.storage.models import (
    Cluster,
    ClusteringRun,
    ClusterSource,
    Keyword,
    KeywordMetric,
    KeywordRevision,
    KeywordStatus,
    MetricSource,
)

# --------------------------------------------------------------------------
# Fonctions pures
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("excursion nosy be tarif", "excursion tarif"),
        ("EXCURSION NOSY BE", "EXCURSION"),
        ("madagaskar rundreise", "rundreise"),
        ("que faire a hell ville nosy be", "que faire a"),
        ("nosybe excursion", "excursion"),  # graphie en un mot, même destination
        ("escursione a madagascar", "escursione a"),
    ],
)
def test_strip_noise_retire_les_termes_omnipresents(raw: str, expected: str) -> None:
    assert sc.strip_noise(raw) == expected


def test_strip_noise_conserve_un_libelle_entierement_bruit() -> None:
    """Mieux vaut un vecteur peu discriminant qu'une chaîne vide."""
    assert sc.strip_noise("madagascar") == "madagascar"
    assert sc.strip_noise("nosy be") == "nosy be"


def test_strip_noise_sans_motif_ne_change_rien() -> None:
    assert sc.strip_noise("excursion nosy be", pattern="") == "excursion nosy be"


def test_assign_groups_cas_limites() -> None:
    assert len(sc.assign_groups(np.empty((0, 3)))) == 0
    assert sc.assign_groups(np.array([[1.0, 0.0, 0.0]])).tolist() == [0]


def test_assign_groups_separe_deux_familles() -> None:
    vectors = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.99, 0.01, 0.0],
            [0.0, 1.0, 0.0],
            [0.01, 0.99, 0.0],
        ]
    )
    groups = sc.assign_groups(vectors, threshold=0.4)
    assert groups[0] == groups[1]
    assert groups[2] == groups[3]
    assert groups[0] != groups[2]


def test_pick_head_index_singleton() -> None:
    vectors = np.array([[1.0, 0.0]])
    assert sc.pick_head_index([0], vectors, [None]) == 0


def test_pick_head_index_le_volume_prime_sur_la_centralite() -> None:
    # L'indice 0 est le plus central, mais l'indice 2 a du volume.
    vectors = np.array([[1.0, 0.0], [0.9, 0.1], [0.5, 0.5]])
    assert sc.pick_head_index([0, 1, 2], vectors, [None, None, 500]) == 2


def test_pick_head_index_plus_gros_volume_gagne() -> None:
    vectors = np.array([[1.0, 0.0], [0.9, 0.1], [0.5, 0.5]])
    assert sc.pick_head_index([0, 1, 2], vectors, [50, 5000, 500]) == 1


def test_pick_head_index_repli_sur_la_centralite() -> None:
    """Sans aucun volume connu, le libellé le plus central l'emporte."""
    vectors = np.array([[1.0, 0.0], [0.99, 0.14], [0.98, 0.2], [-1.0, 0.0]])
    head = sc.pick_head_index([0, 1, 2, 3], vectors, [None] * 4)
    assert head in (0, 1, 2)
    assert head != 3


# --------------------------------------------------------------------------
# Intégration base
# --------------------------------------------------------------------------


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _fake_encode(labels: list[str], model_name: str) -> np.ndarray:
    """Vecteurs déterministes : le premier mot décide de la famille.

    'excursion ...' et 'excursion ...' se rejoignent, 'hotel ...' forme
    une autre famille. Suffisant pour tester la mécanique.
    """
    families = {"excursion": 0, "hotel": 1, "safari": 2}
    vectors = []
    for label in labels:
        first = label.split()[0] if label.split() else ""
        axis = families.get(first, 3)
        vec = np.zeros(4)
        vec[axis] = 1.0
        vectors.append(vec)
    return np.array(vectors)


@pytest.fixture(autouse=True)
def _patch_encode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc, "_encode", _fake_encode)


def _add(session: Session, keyword: str, lang: str = "fr", **kwargs) -> Keyword:
    record = Keyword(keyword=keyword, lang=lang, **kwargs)
    session.add(record)
    session.flush()
    return record


def test_run_clustering_cree_run_et_clusters(session: Session) -> None:
    for kw in ("excursion nosy be", "excursion nosy iranja", "hotel nosy be"):
        _add(session, kw)

    result = sc.run_clustering(session)

    assert result.cluster_count == 2
    assert result.keyword_count == 3
    assert session.exec(select(ClusteringRun)).one().cluster_count == 2
    assert len(session.exec(select(Cluster)).all()) == 2


def test_run_clustering_rattache_et_journalise(session: Session) -> None:
    _add(session, "excursion nosy be")
    sc.run_clustering(session)

    keyword = session.exec(select(Keyword)).one()
    assert keyword.cluster_id is not None
    assert keyword.cluster_source is ClusterSource.AUTO

    revisions = session.exec(
        select(KeywordRevision).where(KeywordRevision.field_name == "cluster_id")
    ).all()
    assert len(revisions) == 1
    assert revisions[0].old_value is None


def test_run_clustering_respecte_le_verrou_manuel(session: Session) -> None:
    """Un déplacement décidé à la main survit au recalcul."""
    locked = _add(
        session,
        "excursion nosy be",
        cluster_id=None,
        cluster_source=ClusterSource.MANUAL,
    )
    _add(session, "hotel nosy be")

    result = sc.run_clustering(session)

    assert result.locked_count == 1
    assert result.keyword_count == 1
    session.refresh(locked)
    assert locked.cluster_id is None
    assert locked.cluster_source is ClusterSource.MANUAL


def test_run_clustering_ignore_les_non_actifs(session: Session) -> None:
    _add(session, "excursion nosy be")
    _add(session, "hotel a vendre", status=KeywordStatus.EXCLUDED)

    result = sc.run_clustering(session)

    assert result.keyword_count == 1


def test_run_clustering_deduplique_les_libelles_partages(session: Session) -> None:
    """Le même libellé en deux langues donne un vecteur et un cluster."""
    _add(session, "excursion nosy be", lang="fr")
    _add(session, "excursion nosy be", lang="en")

    result = sc.run_clustering(session)

    assert result.cluster_count == 1
    cluster = session.exec(select(Cluster)).one()
    assert cluster.keyword_count == 2  # les deux lignes sont rattachées


def test_run_clustering_head_suit_le_volume(session: Session) -> None:
    petit = _add(session, "excursion nosy be")
    gros = _add(session, "excursion nosy iranja")
    session.add(
        KeywordMetric(
            keyword_id=gros.id,
            market="FR",
            search_volume=500,
            source=MetricSource.GOOGLE_ADS,
        )
    )
    session.add(
        KeywordMetric(
            keyword_id=petit.id,
            market="FR",
            search_volume=10,
            source=MetricSource.GOOGLE_ADS,
        )
    )
    session.flush()

    sc.run_clustering(session)

    cluster = session.exec(select(Cluster)).one()
    assert cluster.head_keyword_id == gros.id
    assert cluster.total_volume == 510


def test_run_clustering_compte_les_isoles(session: Session) -> None:
    _add(session, "excursion nosy be")
    _add(session, "hotel nosy be")
    _add(session, "safari madagascar")

    result = sc.run_clustering(session)

    assert result.singleton_count == 3
    assert result.largest_size == 1


def test_run_clustering_sans_mot_cle_actif(session: Session) -> None:
    result = sc.run_clustering(session)
    assert result.cluster_count == 0
    assert result.keyword_count == 0


def test_pick_head_index_prefere_la_formulation_courte() -> None:
    """À sens équivalent, la requête la plus courte est la cible.

    Sans pénalité de longueur, la centralité choisit le compromis moyen
    du groupe ('madagaskar urlaub machen') plutôt que la requête
    principale ('madagaskar urlaub').
    """
    vectors = np.array([[1.0, 0.0], [0.98, 0.2], [0.98, -0.2]])
    labels = ["madagaskar urlaub machen wann", "madagaskar urlaub", "urlaub tipps"]
    assert sc.pick_head_index([0, 1, 2], vectors, [None] * 3, labels) == 1


def test_pick_head_index_sans_labels_reste_compatible() -> None:
    vectors = np.array([[1.0, 0.0], [0.9, 0.1], [-1.0, 0.0]])
    head = sc.pick_head_index([0, 1, 2], vectors, [None] * 3)
    assert head in (0, 1)
