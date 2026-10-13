"""L'export ne doit ni écrire en base ni inventer de chiffres."""

from datetime import UTC, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine

from seo_keywords.export.pdf_report import (
    UNSET_LABEL,
    collect_report_data,
    render_pdf,
)
from seo_keywords.storage.models import (
    Cluster,
    ClusterPage,
    ClusteringRun,
    Intent,
    IntentSource,
    Keyword,
    KeywordStatus,
)


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed(session: Session) -> None:
    run = ClusteringRun(
        model_name="paraphrase-multilingual-MiniLM-L12-v2",
        distance_threshold=0.4,
        linkage="complete",
        keyword_count=6,
        cluster_count=2,
        created_at=datetime.now(UTC),
    )
    session.add(run)
    session.commit()

    big = Cluster(run_id=run.id, keyword_count=3)
    small = Cluster(run_id=run.id, keyword_count=1)
    session.add_all([big, small])
    session.commit()

    keywords = [
        Keyword(
            keyword="excursion nosy be",
            lang="fr",
            intent=Intent.COMMERCIAL,
            intent_source=IntentSource.AUTO,
            cluster_id=big.id,
        ),
        Keyword(keyword="tsingy de bemaraha", lang="fr", cluster_id=big.id),
        Keyword(
            keyword="plongee madagascar",
            lang="fr",
            intent=Intent.INFORMATIONNEL,
            cluster_id=big.id,
        ),
        Keyword(
            keyword="tui madagascar",
            lang="fr",
            status=KeywordStatus.COMPETITOR,
            cluster_id=small.id,
        ),
        Keyword(
            keyword="recette mofo gasy",
            lang="fr",
            status=KeywordStatus.EXCLUDED,
            cluster_id=small.id,
        ),
        Keyword(
            keyword="nosy be whale shark",
            lang="en",
            intent=Intent.TRANSACTIONNEL,
            cluster_id=big.id,
        ),
    ]
    session.add_all(keywords)
    session.commit()

    session.add_all(
        [
            ClusterPage(
                cluster_id=big.id,
                lang="fr",
                proposed_title="Excursions à Nosy Be",
                keyword_count=3,
            ),
            ClusterPage(
                cluster_id=big.id,
                lang="en",
                proposed_title="Nosy Be excursions",
                keyword_count=1,
            ),
            ClusterPage(
                cluster_id=small.id,
                lang="fr",
                proposed_title="Page isolée",
                keyword_count=1,
            ),
        ]
    )
    session.commit()


def test_compte_les_statuts_par_langue(session: Session) -> None:
    _seed(session)
    data = collect_report_data(session)

    fr = next(s for s in data.langs if s.lang == "fr")
    assert fr.active == 3
    assert fr.competitor == 1
    assert fr.excluded == 1
    assert fr.total == 5


def test_les_sans_intention_forment_une_categorie(session: Session) -> None:
    _seed(session)
    data = collect_report_data(session)

    fr = next(s for s in data.langs if s.lang == "fr")
    assert fr.by_intent[UNSET_LABEL] == 1
    assert fr.by_intent[Intent.COMMERCIAL.value] == 1
    assert round(fr.unset_rate) == 33


def test_les_exclus_ne_comptent_pas_dans_les_intentions(session: Session) -> None:
    _seed(session)
    data = collect_report_data(session)

    fr = next(s for s in data.langs if s.lang == "fr")
    assert sum(fr.by_intent.values()) == fr.active


def test_min_keywords_ecarte_les_pages_isolees(session: Session) -> None:
    _seed(session)
    data = collect_report_data(session, min_keywords=2)

    fr = next(s for s in data.langs if s.lang == "fr")
    assert [p.title for p in fr.pages] == ["Excursions à Nosy Be"]
    assert fr.pages_skipped == 1


def test_min_keywords_a_un_garde_tout(session: Session) -> None:
    _seed(session)
    data = collect_report_data(session, min_keywords=1)

    fr = next(s for s in data.langs if s.lang == "fr")
    assert len(fr.pages) == 2
    assert fr.pages_skipped == 0


def test_langues_triees_par_volume_actif(session: Session) -> None:
    _seed(session)
    data = collect_report_data(session)

    assert [s.lang for s in data.langs] == ["fr", "en"]


def test_clusters_surdimensionnes_en_annexe(session: Session) -> None:
    _seed(session)
    data = collect_report_data(session, oversized_threshold=3)

    assert [c.keyword_count for c in data.oversized] == [3]


def test_refuse_un_run_inexistant(session: Session) -> None:
    _seed(session)
    with pytest.raises(ValueError, match="introuvable"):
        collect_report_data(session, run_id=999)


def test_refuse_une_base_sans_run(session: Session) -> None:
    with pytest.raises(ValueError, match="Aucun run"):
        collect_report_data(session)


def test_produit_un_pdf_valide(session: Session, tmp_path) -> None:
    _seed(session)
    data = collect_report_data(session)
    target = tmp_path / "rapport.pdf"

    render_pdf(data, str(target))

    assert target.exists()
    assert target.read_bytes()[:4] == b"%PDF"