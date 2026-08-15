"""Point d'entrée CLI : `uv run seo-keywords <commande>`."""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import track

from seo_keywords.analysis.curation import auto_filter, export_for_manual_tagging
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
    """Étape intermédiaire : filtre le bruit (marques concurrentes, faux positifs)
    et exporte un CSV à tagger manuellement (intention: transactionnel/informationnel/
    navigationnel/exclure)."""
    repo = KeywordRepository(settings.database_path)
    records = repo.get_all_keywords(lang=lang)

    if not records:
        console.print(f"[bold red]Aucun mot-clé en base pour '{lang}'.[/bold red]")
        raise typer.Exit(1)

    result = auto_filter(records)

    console.print(f"[bold cyan]Curation automatique[/bold cyan] ({len(records)} mots-clés)")
    console.print(f"  ✓ à garder / tagger    : {len(result.keeper)}")
    console.print(f"  ✗ marques concurrentes : {len(result.competitor)}")
    console.print(f"  ✗ hors-sujet           : {len(result.off_topic)}")

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

    output_path = f"{settings.processed_output_dir}/to_tag_{lang}.csv"
    export_for_manual_tagging(result.keeper, output_path)
    console.print(f"\n[bold green]✓ Export pour tagging manuel : {output_path}[/bold green]")
    console.print("[dim]Ouvre ce CSV et remplis la colonne 'intent' avec: "
                  "transactionnel / informationnel / navigationnel / exclure[/dim]")


@app.command()
def markets():
    """Liste les marchés cibles configurés."""
    console.print("Marchés configurés :", TARGET_MARKETS)


if __name__ == "__main__":
    app()
