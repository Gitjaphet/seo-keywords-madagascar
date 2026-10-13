"""Commande export-pdf, greffée sur l'application CLI existante.

Vit à part de cli.py pour garder l'export isolé du pipeline de
collecte : le rapport ne fait que lire, il n'a rien à faire au milieu
des commandes qui écrivent.
"""

from __future__ import annotations

import typer
from rich.console import Console
from sqlmodel import Session, create_engine

from seo_keywords.cli import app
from seo_keywords.config import settings
from seo_keywords.export.pdf_report import collect_report_data, render_pdf

console = Console()


@app.command("export-pdf")
def export_pdf_cmd(
    run_id: int = typer.Option(0, help="Run à restituer. 0 = le plus récent."),
    min_keywords: int = typer.Option(
        2,
        help="Nombre minimal de mots-clés pour qu'un cluster figure dans la "
        "liste des pages d'une langue. 1 fait remonter la longue traîne "
        "isolée et rend le rapport illisible.",
    ),
    oversized: int = typer.Option(
        40, help="Taille au-delà de laquelle un cluster part en annexe."
    ),
    output: str = typer.Option(
        "", help="Chemin du PDF. Vide = data/processed/rapport_seo.pdf"
    ),
) -> None:
    """Étape 11 : exporte un rapport PDF de synthèse, une section par langue.

    Lecture seule : aucune écriture en base."""
    engine = create_engine(f"sqlite:///{settings.database_path}")
    target = output or f"{settings.processed_output_dir}/rapport_seo.pdf"

    with Session(engine) as session:
        try:
            data = collect_report_data(
                session,
                run_id or None,
                min_keywords=min_keywords,
                oversized_threshold=oversized,
            )
        except ValueError as exc:
            console.print(f"[bold red]{exc}[/bold red]")
            raise typer.Exit(1) from exc

    render_pdf(data, target)

    console.print(f"\n[bold cyan]Rapport PDF[/bold cyan] (run {data.run.run_id})")
    console.print(f"  mots-clés      : {data.total_keywords}")
    console.print(f"  actifs         : {data.total_active}")
    console.print(f"  sans intention : {data.total_unset}")
    console.print()
    for stats in data.langs:
        console.print(
            f"  {stats.lang:<4} {stats.active:>5} actifs   "
            f"{len(stats.pages):>4} pages   "
            f"[dim]{stats.pages_skipped} écartées[/dim]"
        )
    if data.oversized:
        console.print(
            f"\n[yellow]⚠ {len(data.oversized)} clusters surdimensionnés "
            f"listés en annexe.[/yellow]"
        )

    console.print(f"\n[bold green]✓ {target}[/bold green]")