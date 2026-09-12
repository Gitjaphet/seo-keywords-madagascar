"""Point d'entrée CLI : `uv run seo-keywords <commande>`."""


import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import track

from seo_keywords.analysis.cluster_export import build_rows, export_clusters_csv
from seo_keywords.analysis.cluster_pages import build_pages
from seo_keywords.analysis.clustering import (
    cluster_summary,
    export_clustered_csv,
    export_cross_language_report,
    load_clustered_csv,
)
from seo_keywords.analysis.curation import (
    auto_filter,
    export_for_manual_tagging,
    export_foreign_language_csv,
    separate_cross_language,
)
from seo_keywords.analysis.intent_classifier import (
    auto_classify_csv,
    classification_summary,
    export_classified_csv,
    export_needs_review_csv,
)
from seo_keywords.analysis.seasonality import export_monthly_csv, export_season_summary_csv
from seo_keywords.analysis.semantic_clustering import (
    DEFAULT_LINKAGE,
    DEFAULT_MODEL,
    DEFAULT_NOISE_PATTERN,
    DEFAULT_THRESHOLD,
    run_clustering,
)
from seo_keywords.collectors.autocomplete import AutocompleteCollector
from seo_keywords.collectors.trends import TrendsCollector
from seo_keywords.config import SEED_KEYWORDS, TARGET_MARKETS, settings
from seo_keywords.storage.repository import KeywordRepository

logging.basicConfig(
    level=logging.INFO, format="%(message)s", handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger(__name__)
console = Console()
app = typer.Typer(help="Collecte de mots-clés touristiques Madagascar")


@app.command()
def expand(
    lang: str = typer.Option(None, help="Limiter à une langue (fr/en/de). Sinon toutes."),
    limit_letters: int = typer.Option(
        26, help="Nombre de lettres a-z à tester par seed (26 = complet, plus lent)"
    ),
):
    """Étape 1 : étend les seeds via Google Autocomplete et sauvegarde en base."""
    collector = AutocompleteCollector()
    repo = KeywordRepository(settings.database_path)
    alphabet = settings.expansion_alphabet[:limit_letters]

    langs = [lang] if lang else list(SEED_KEYWORDS.keys())
    total_inserted = 0

    for lang_code in langs:
        seeds = SEED_KEYWORDS[lang_code]
        console.print(f"\n[bold cyan]Langue: {lang_code}[/bold cyan] ({len(seeds)} seeds)")
        for seed in track(seeds, description=f"Expansion [{lang_code}]"):
            suggestions = collector.collect_expanded(seed, lang_code, alphabet)
            inserted = repo.save_suggestions(suggestions)
            total_inserted += inserted
            logger.info("'%s' -> %d suggestions (%d nouvelles)", seed, len(suggestions), inserted)

    console.print(
        f"\n[bold green]✓ Terminé : {total_inserted} nouveaux mots-clés en base[/bold green]"
    )


@app.command()
def seasonality(
    lang: str = typer.Option("en", help="Langue des mots-clés à analyser"),
    top: int = typer.Option(15, help="Nombre max de mots-clés à interroger sur Trends"),
    geo: str = typer.Option("", help="Marché ciblé: '' (mondial), FR, DE, US, IT..."),
):
    """Étape 2 : interroge Google Trends pour la saisonnalité des mots-clés collectés."""
    repo = KeywordRepository(settings.database_path)
    records = repo.get_all_keywords(lang=lang)

    if not records:
        console.print(
            f"[bold red]Aucun mot-clé en base pour '{lang}'. "
            f"Lance d'abord `seo-keywords expand --lang {lang}`.[/bold red]"
        )
        raise typer.Exit(1)

    keywords = [r.keyword for r in records[:top]]
    console.print(f"[bold cyan]Interrogation Trends[/bold cyan] geo='{geo or 'mondial'}' "
                  f"pour {len(keywords)} mots-clés")

    trends = TrendsCollector()
    monthly_averages = trends.monthly_averages(keywords, geo=geo)

    for keyword, months in monthly_averages.items():
        repo.save_seasonality(keyword, geo, months)

    console.print(f"[bold green]✓ Saisonnalité sauvegardée pour {len(monthly_averages)} "
                  f"mots-clés[/bold green]")


@app.command()
def export(
    geo: str = typer.Option("", help="Marché à exporter: '' (mondial), FR, DE, US, IT..."),
):
    """Étape 3 : exporte les CSV finaux (mensuel + résumé par saison)."""
    repo = KeywordRepository(settings.database_path)
    records = repo.get_seasonality(geo=geo)

    if not records:
        console.print(f"[bold red]Aucune donnée de saisonnalité pour geo='{geo}'.[/bold red]")
        raise typer.Exit(1)

    suffix = geo or "monde"
    monthly_path = f"{settings.processed_output_dir}/seasonality_monthly_{suffix}.csv"
    summary_path = f"{settings.processed_output_dir}/seasonality_summary_{suffix}.csv"

    export_monthly_csv(records, monthly_path)
    export_season_summary_csv(records, summary_path)

    console.print(
        f"[bold green]✓ Exports créés :[/bold green]\n  - {monthly_path}\n  - {summary_path}"
    )


@app.command()
def curate(
    lang: str = typer.Option("fr", help="Langue des mots-clés à curer"),
):
    """Étape intermédiaire : filtre le bruit (marques concurrentes, faux positifs,
    artefacts d'une autre langue) et exporte un CSV à tagger manuellement
    (intention: transactionnel/informationnel/navigationnel/exclure)."""
    repo = KeywordRepository(settings.database_path)
    records = repo.get_all_keywords(lang=lang)

    if not records:
        console.print(f"[bold red]Aucun mot-clé en base pour '{lang}'.[/bold red]")
        raise typer.Exit(1)

    result = auto_filter(records)
    same_lang, foreign = separate_cross_language(result.keeper, declared_lang=lang)

    console.print(f"[bold cyan]Curation automatique[/bold cyan] ({len(records)} mots-clés)")
    console.print(f"  ✓ à garder / tagger        : {len(same_lang)}")
    console.print(f"  ✗ marques concurrentes     : {len(result.competitor)}")
    console.print(f"  ✗ hors-sujet               : {len(result.off_topic)}")
    console.print(f"  ✗ autre langue détectée    : {len(foreign)}")

    if result.competitor:
        console.print(
            "\n[dim]Marques concurrentes détectées (intelligence concurrentielle) :[/dim]"
        )
        for r in result.competitor:
            console.print(f"  [dim]- {r.keyword}[/dim]")

    if result.off_topic:
        console.print("\n[dim]Hors-sujet exclus :[/dim]")
        for r in result.off_topic:
            console.print(f"  [dim]- {r.keyword}[/dim]")

    if foreign:
        console.print("\n[dim]Autre langue détectée (extraits pour réutilisation) :[/dim]")
        for r, detected in foreign:
            console.print(f"  [dim]- [{detected}] {r.keyword}[/dim]")

    output_path = f"{settings.processed_output_dir}/to_tag_{lang}.csv"
    export_for_manual_tagging(same_lang, output_path)
    console.print(f"\n[bold green]✓ Export pour tagging manuel : {output_path}[/bold green]")
    console.print("[dim]Ouvre ce CSV et remplis la colonne 'intent' avec: "
                  "transactionnel / informationnel / navigationnel / exclure[/dim]")

    if foreign:
        foreign_path = f"{settings.processed_output_dir}/foreign_language_from_{lang}.csv"
        export_foreign_language_csv(foreign, foreign_path)
        console.print(
            f"[yellow]→ {len(foreign)} mots-clés détectés dans une autre langue, "
            f"sauvegardés dans {foreign_path} pour réutilisation future.[/yellow]"
        )



@app.command()
def cluster(
    lang: str = typer.Option("fr", help="Langue du CSV taggé à regrouper par thème"),
):
    """Étape 4 : regroupe les mots-clés taggés par thème (cluster) à partir
    de leur seed, pour préparer le mapping vers les pages du site.

    Sépare aussi les artefacts cross-langue (mots-clés collectés sous 'lang'
    mais en réalité écrits dans une autre langue, repérés via la colonne
    'notes') dans un fichier séparé, réutilisable lors du tagging de la
    bonne langue."""
    input_path = f"{settings.processed_output_dir}/to_tag_{lang}.csv"
    output_path = f"{settings.processed_output_dir}/clustered_{lang}.csv"
    cross_lang_path = f"{settings.processed_output_dir}/cross_language_from_{lang}.csv"

    if not Path(input_path).exists():
        console.print(
            f"[bold red]Fichier introuvable : {input_path}. "
            f"Lance d'abord `curate --lang {lang}` puis termine le tagging.[/bold red]"
        )
        raise typer.Exit(1)

    matching, cross_lang = load_clustered_csv(input_path, target_lang=lang)
    if not matching:
        console.print(
            f"[bold red]Aucune ligne taggée exploitable dans {input_path} "
            f"(colonne 'intent' vide ou tout marqué 'exclure').[/bold red]"
        )
        raise typer.Exit(1)

    export_clustered_csv(matching, output_path)
    summary = cluster_summary(matching)

    console.print(f"[bold cyan]Clustering[/bold cyan] ({len(matching)} mots-clés exploitables)")
    for cluster_name, count in sorted(summary.items(), key=lambda x: -x[1]):
        console.print(f"  {cluster_name:<25} {count}")

    console.print(f"\n[bold green]✓ Export : {output_path}[/bold green]")

    if cross_lang:
        export_cross_language_report(cross_lang, cross_lang_path)
        console.print(
            f"\n[yellow]⚠ {len(cross_lang)} mots-clés collectés sous '{lang}' mais "
            f"détectés dans une autre langue (via notes) — extraits et sauvegardés "
            f"dans {cross_lang_path} pour réutilisation future.[/yellow]"
        )


@app.command()
def classify(
    lang: str = typer.Option("fr", help="Langue du CSV taggé à classifier automatiquement"),
    include_commercial: bool = typer.Option(
        False,
        "--include-commercial",
        help="Active le 4e tier 'commercial investigation' (confiance plus "
        "faible: madagascar diving trip, etc.) — à contrôler par échantillonnage.",
    ),
):
    """Étape intermédiaire (alternative au tagging 100% manuel) : classe
    automatiquement l'intention par règles heuristiques multilingues.

    Respecte les lignes déjà taguées manuellement (jamais reclassées).
    Les lignes non taguées et non reconnues par une règle partent dans un
    fichier de révision manuelle réduit (needs_review_<lang>.csv), au lieu
    de devoir tagger tout le lot à la main."""
    input_path = f"{settings.processed_output_dir}/to_tag_{lang}.csv"
    classified_path = f"{settings.processed_output_dir}/classified_{lang}.csv"
    review_path = f"{settings.processed_output_dir}/needs_review_{lang}.csv"

    if not Path(input_path).exists():
        console.print(
            f"[bold red]Fichier introuvable : {input_path}. "
            f"Lance d'abord `curate --lang {lang}`.[/bold red]"
        )
        raise typer.Exit(1)

    result = auto_classify_csv(input_path, include_commercial_fallback=include_commercial)
    total = len(result.classified) + len(result.needs_review)
    auto_rate = (len(result.classified) / total * 100) if total else 0

    console.print(f"[bold cyan]Classification automatique[/bold cyan] ({total} mots-clés)")
    console.print(f"  ✓ classés automatiquement : {len(result.classified)} ({auto_rate:.0f}%)")
    console.print(f"  ? à réviser manuellement  : {len(result.needs_review)}")
    console.print()
    console.print("Répartition par intention :")
    for intent, count in sorted(classification_summary(result.classified).items(),
                                 key=lambda x: -x[1]):
        console.print(f"  {intent:<20} {count}")

    if include_commercial:
        commercial_count = sum(1 for i in result.classified if i.intent == "commercial")
        if commercial_count:
            console.print(
                f"\n[yellow]⚠ {commercial_count} mots-clés classés 'commercial' (confiance "
                f"plus faible) — filtre le CSV sur intent=commercial et contrôle un "
                f"échantillon d'environ 10% avant de faire confiance au lot entier.[/yellow]"
            )

    export_classified_csv(result.classified, classified_path)
    console.print(f"\n[bold green]✓ Export classifié : {classified_path}[/bold green]")

    if result.needs_review:
        export_needs_review_csv(result.needs_review, review_path)
        console.print(
            f"[yellow]→ {len(result.needs_review)} mots-clés à taguer manuellement "
            f"dans {review_path}[/yellow]"
        )

@app.command()
def markets():
    """Liste les marchés cibles configurés."""
    console.print("Marchés configurés :", TARGET_MARKETS)




@app.command("cluster-semantic")
def cluster_semantic(
    threshold: float = typer.Option(
        DEFAULT_THRESHOLD,
        help="Distance cosinus maximale au sein d'un cluster. Plus bas = "
        "clusters plus fins et plus nombreux.",
    ),
    linkage: str = typer.Option(
        DEFAULT_LINKAGE,
        help="Critère de liaison. 'complete' évite l'effet de chaînage qui "
        "produit un cluster géant absorbant tout le corpus.",
    ),
    model_name: str = typer.Option(DEFAULT_MODEL, help="Modèle d'embeddings"),
    keep_noise: bool = typer.Option(
        False,
        "--keep-noise",
        help="Conserve les termes de destination (madagascar, nosy be) lors "
        "de l'encodage. Déconseillé : ils saturent le signal.",
    ),
    notes: str = typer.Option("", help="Commentaire libre attaché au run"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Calcule et affiche, puis annule sans écrire"
    ),
):
    """Étape 5 : regroupe les mots-clés par proximité de sens.

    Remplace le regroupement par seed. Les mots-clés dont le cluster a
    été fixé à la main (cluster_source = manual) ne sont jamais
    réaffectés."""
    from sqlmodel import Session, create_engine

    engine = create_engine(f"sqlite:///{settings.database_path}")

    with Session(engine) as session:
        result = run_clustering(
            session,
            model_name=model_name,
            threshold=threshold,
            linkage=linkage,
            noise_pattern="" if keep_noise else DEFAULT_NOISE_PATTERN,
            notes=notes,
        )

        console.print(f"\n[bold cyan]Clustering sémantique[/bold cyan] (run {result.run_id})")
        console.print(f"  mots-clés regroupés   : {result.keyword_count}")
        console.print(f"  clusters              : {result.cluster_count}")
        console.print(f"  isolés (1 mot-clé)    : {result.singleton_count}")
        console.print(f"  plus gros cluster     : {result.largest_size}")
        if result.locked_count:
            console.print(
                f"  [yellow]verrouillés (manuel) : {result.locked_count} "
                f"— non réaffectés[/yellow]"
            )

        if result.largest_size > 80:
            console.print(
                "\n[yellow]⚠ Un cluster dépasse 80 mots-clés : c'est le signe "
                "d'un fourre-tout. Baisse le seuil.[/yellow]"
            )

        if dry_run:
            session.rollback()
            console.print("\n[yellow]dry-run : rien n'a été écrit[/yellow]")
        else:
            session.commit()
            console.print("\n[bold green]✓ Clusters enregistrés[/bold green]")


@app.command("export-clusters")
def export_clusters(
    run_id: int = typer.Option(
        0, help="Run à exporter. 0 = le plus récent."
    ),
    output: str = typer.Option(
        "", help="Chemin du CSV. Par défaut data/processed/clusters_review.csv"
    ),
    top: int = typer.Option(0, help="N'exporter que les N premiers clusters. 0 = tous."),
):
    """Étape 6 : exporte les clusters pour validation manuelle.

    Trié par potentiel réel, pas par taille : l'ancrage local et
    l'intention commerciale priment, la concurrence publicitaire pénalise.
    Les colonnes decision / fusionner_avec / url_cible / commentaire sont
    vides, à remplir."""
    from sqlmodel import Session, create_engine

    engine = create_engine(f"sqlite:///{settings.database_path}")
    target = output or f"{settings.processed_output_dir}/clusters_review.csv"

    with Session(engine) as session:
        rows = build_rows(session, run_id or None)

    if not rows:
        console.print(
            "[bold red]Aucun cluster à exporter. "
            "Lance d'abord `cluster-semantic`.[/bold red]"
        )
        raise typer.Exit(1)

    if top:
        rows = rows[:top]

    export_clusters_csv(rows, target)

    console.print(f"[bold cyan]Export clusters[/bold cyan] ({len(rows)} lignes)")
    console.print(f"\n{'prio':>6}  {'n':>3}  tête")
    for row in rows[:15]:
        console.print(f"{row.priority:>6.2f}  {row.keyword_count:>3}  {row.head}")

    console.print(f"\n[bold green]✓ {target}[/bold green]")
    console.print(
        "[dim]Colonnes à remplir : decision (garder/fusionner/scinder/ecarter), "
        "fusionner_avec (cluster_id), url_cible, commentaire[/dim]"
    )


@app.command("build-pages")
def build_pages_cmd(
    run_id: int = typer.Option(0, help="Run à décliner. 0 = le plus récent."),
    min_keywords: int = typer.Option(
        1,
        help="Nombre minimal de mots-clés dans une langue pour justifier "
        "une page. 2 écarte les langues anecdotiques.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Calcule et affiche, puis annule sans écrire"
    ),
):
    """Étape 7 : décline chaque cluster en une page par langue.

    Les pages d'un même cluster sont par construction les traductions
    les unes des autres : c'est ce qui alimentera les balises hreflang.
    Une page déjà relue (reviewed_at renseigné) n'est jamais modifiée."""
    from sqlmodel import Session, create_engine

    engine = create_engine(f"sqlite:///{settings.database_path}")

    with Session(engine) as session:
        result = build_pages(session, run_id or None, min_keywords)

        console.print(f"\n[bold cyan]Pages par langue[/bold cyan] (run {result.run_id})")
        console.print(f"  créées      : {result.created}")
        console.print(f"  rafraîchies : {result.updated}")
        if result.preserved:
            console.print(
                f"  [yellow]préservées  : {result.preserved} "
                f"— déjà relues, non modifiées[/yellow]"
            )
        console.print()
        for lang, count in result.pages_by_lang.items():
            console.print(f"  {lang:<4} {count}")

        if dry_run:
            session.rollback()
            console.print("\n[yellow]dry-run : rien n'a été écrit[/yellow]")
        else:
            session.commit()
            total = sum(result.pages_by_lang.values())
            console.print(f"\n[bold green]✓ {total} pages[/bold green]")


if __name__ == "__main__":
    app()
