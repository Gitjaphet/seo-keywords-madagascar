"""Point d'entrée CLI : `uv run seo-keywords <commande>`."""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import track

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


if __name__ == "__main__":
    app()
