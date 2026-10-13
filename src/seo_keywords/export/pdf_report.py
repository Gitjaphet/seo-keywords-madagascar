"""Rapport PDF de synthèse, une section par langue.

Lecture seule stricte : aucune écriture, aucun commit. Un export ne
doit jamais pouvoir abîmer la base.

La collecte (`collect_report_data`) est séparée du rendu
(`render_pdf`) : la première est testable sans ReportLab et
réutilisable par le futur dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import func
from sqlmodel import Session, select

from seo_keywords.storage.models import (
    Cluster,
    ClusterPage,
    ClusteringRun,
    Intent,
    Keyword,
    KeywordStatus,
)

__all__ = [
    "LangStats",
    "OversizedCluster",
    "PageRow",
    "ReportData",
    "RunInfo",
    "collect_report_data",
    "render_pdf",
]

UNSET_LABEL = "sans intention"

INTENT_ORDER: tuple[str, ...] = (
    Intent.COMMERCIAL.value,
    Intent.INFORMATIONNEL.value,
    Intent.TRANSACTIONNEL.value,
    Intent.NAVIGATIONNEL.value,
    UNSET_LABEL,
)

INTENT_COLORS: dict[str, Color] = {
    Intent.COMMERCIAL.value: HexColor("#7F77DD"),
    Intent.INFORMATIONNEL.value: HexColor("#378ADD"),
    Intent.TRANSACTIONNEL.value: HexColor("#1D9E75"),
    Intent.NAVIGATIONNEL.value: HexColor("#888780"),
    UNSET_LABEL: HexColor("#D3D1C7"),
}

LANG_LABELS: dict[str, str] = {
    "fr": "Français",
    "en": "Anglais",
    "de": "Allemand",
    "it": "Italien",
}

LANG_FILL: dict[str, Color] = {
    "fr": HexColor("#E6F1FB"),
    "en": HexColor("#EEEDFE"),
    "de": HexColor("#FAEEDA"),
    "it": HexColor("#E1F5EE"),
}

LANG_INK: dict[str, Color] = {
    "fr": HexColor("#0C447C"),
    "en": HexColor("#3C3489"),
    "de": HexColor("#633806"),
    "it": HexColor("#085041"),
}

_FALLBACK_FILL = HexColor("#F1EFE8")
_FALLBACK_INK = HexColor("#2C2C2A")
_MUTED = HexColor("#5F5E5A")
_RULE = HexColor("#D3D1C7")


def _lang_label(lang: str) -> str:
    return LANG_LABELS.get(lang, lang.upper())


def _lang_fill(lang: str) -> Color:
    return LANG_FILL.get(lang, _FALLBACK_FILL)


def _lang_ink(lang: str) -> Color:
    return LANG_INK.get(lang, _FALLBACK_INK)


@dataclass(frozen=True)
class RunInfo:
    """Paramètres du run de clustering restitué."""

    run_id: int
    model_name: str
    distance_threshold: float
    linkage: str
    keyword_count: int
    cluster_count: int
    created_at: datetime


@dataclass(frozen=True)
class PageRow:
    """Une page projetée pour un cluster, dans une langue."""

    cluster_id: int
    title: str
    keyword_count: int
    status: str
    target_url: str | None


@dataclass(frozen=True)
class LangStats:
    """État du corpus pour une langue."""

    lang: str
    active: int
    excluded: int
    competitor: int
    archived: int
    by_intent: dict[str, int]
    pages: list[PageRow] = field(default_factory=list)
    pages_total: int = 0

    @property
    def total(self) -> int:
        return self.active + self.excluded + self.competitor + self.archived

    @property
    def pages_skipped(self) -> int:
        return self.pages_total - len(self.pages)

    @property
    def unset(self) -> int:
        return self.by_intent.get(UNSET_LABEL, 0)

    @property
    def unset_rate(self) -> float:
        return (self.unset / self.active * 100) if self.active else 0.0


@dataclass(frozen=True)
class OversizedCluster:
    """Cluster trop gros pour tenir sur une seule page éditoriale."""

    cluster_id: int
    keyword_count: int
    head: str


@dataclass(frozen=True)
class ReportData:
    """Tout ce que le PDF affiche, sans dépendance à ReportLab."""

    run: RunInfo
    generated_at: datetime
    langs: list[LangStats]
    oversized: list[OversizedCluster]
    min_keywords: int

    @property
    def total_keywords(self) -> int:
        return sum(s.total for s in self.langs)

    @property
    def total_active(self) -> int:
        return sum(s.active for s in self.langs)

    @property
    def total_unset(self) -> int:
        return sum(s.unset for s in self.langs)


def _resolve_run(session: Session, run_id: int | None) -> ClusteringRun:
    if run_id:
        run = session.get(ClusteringRun, run_id)
        if run is None:
            raise ValueError(f"Run {run_id} introuvable.")
        return run

    statement = select(ClusteringRun).order_by(ClusteringRun.id.desc())  # type: ignore[union-attr]
    run = session.exec(statement).first()
    if run is None:
        raise ValueError("Aucun run de clustering en base. Lance `cluster-semantic`.")
    return run


def _status_value(status: object) -> str:
    return status.value if isinstance(status, KeywordStatus) else str(status)


def _intent_value(intent: object) -> str:
    if intent is None or intent == "":
        return UNSET_LABEL
    return intent.value if isinstance(intent, Intent) else str(intent)


def _collect_counts(
    session: Session,
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    """Retourne (compteurs par statut, compteurs d'intention sur l'actif)."""
    statement = select(
        Keyword.lang,
        Keyword.status,
        Keyword.intent,
        func.count(Keyword.id),
    ).group_by(Keyword.lang, Keyword.status, Keyword.intent)

    by_status: dict[str, dict[str, int]] = {}
    by_intent: dict[str, dict[str, int]] = {}

    for lang, status, intent, count in session.exec(statement).all():
        status_key = _status_value(status)
        by_status.setdefault(lang, {})
        by_status[lang][status_key] = by_status[lang].get(status_key, 0) + count

        if status_key == KeywordStatus.ACTIVE.value:
            intent_key = _intent_value(intent)
            by_intent.setdefault(lang, {})
            by_intent[lang][intent_key] = by_intent[lang].get(intent_key, 0) + count

    return by_status, by_intent


def _collect_pages(
    session: Session, run_id: int, lang: str, min_keywords: int
) -> tuple[list[PageRow], int]:
    statement = (
        select(ClusterPage, Keyword.keyword)
        .join(Cluster, ClusterPage.cluster_id == Cluster.id)
        .outerjoin(Keyword, ClusterPage.head_keyword_id == Keyword.id)
        .where(Cluster.run_id == run_id)
        .where(ClusterPage.lang == lang)
        .order_by(ClusterPage.keyword_count.desc())  # type: ignore[union-attr]
    )

    rows: list[PageRow] = []
    total = 0
    for page, head in session.exec(statement).all():
        total += 1
        if page.keyword_count < min_keywords:
            continue
        title = page.proposed_title or head or f"cluster {page.cluster_id}"
        rows.append(
            PageRow(
                cluster_id=page.cluster_id,
                title=title,
                keyword_count=page.keyword_count,
                status=_status_value(page.status),
                target_url=page.target_url,
            )
        )
    return rows, total


def _collect_oversized(
    session: Session, run_id: int, threshold: int
) -> list[OversizedCluster]:
    statement = (
        select(Cluster, Keyword.keyword)
        .outerjoin(Keyword, Cluster.head_keyword_id == Keyword.id)
        .where(Cluster.run_id == run_id)
        .where(Cluster.keyword_count >= threshold)
        .order_by(Cluster.keyword_count.desc())  # type: ignore[union-attr]
    )
    return [
        OversizedCluster(
            cluster_id=cluster.id or 0,
            keyword_count=cluster.keyword_count,
            head=head or "—",
        )
        for cluster, head in session.exec(statement).all()
    ]


def collect_report_data(
    session: Session,
    run_id: int | None = None,
    min_keywords: int = 2,
    oversized_threshold: int = 40,
) -> ReportData:
    """Assemble l'intégralité du rapport. N'écrit rien."""
    run = _resolve_run(session, run_id)
    by_status, by_intent = _collect_counts(session)

    langs: list[LangStats] = []
    for lang in by_status:
        statuses = by_status[lang]
        intents = by_intent.get(lang, {})
        pages, pages_total = _collect_pages(session, run.id or 0, lang, min_keywords)
        langs.append(
            LangStats(
                lang=lang,
                active=statuses.get(KeywordStatus.ACTIVE.value, 0),
                excluded=statuses.get(KeywordStatus.EXCLUDED.value, 0),
                competitor=statuses.get(KeywordStatus.COMPETITOR.value, 0),
                archived=statuses.get(KeywordStatus.ARCHIVED.value, 0),
                by_intent={k: intents.get(k, 0) for k in INTENT_ORDER},
                pages=pages,
                pages_total=pages_total,
            )
        )

    langs.sort(key=lambda s: -s.active)

    return ReportData(
        run=RunInfo(
            run_id=run.id or 0,
            model_name=run.model_name,
            distance_threshold=run.distance_threshold,
            linkage=run.linkage,
            keyword_count=run.keyword_count,
            cluster_count=run.cluster_count,
            created_at=run.created_at,
        ),
        generated_at=datetime.now(UTC),
        langs=langs,
        oversized=_collect_oversized(session, run.id or 0, oversized_threshold),
        min_keywords=min_keywords,
    )


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle(
            "title", parent=base, fontName="Helvetica", fontSize=24, leading=30
        ),
        "h2": ParagraphStyle(
            "h2", parent=base, fontName="Helvetica", fontSize=15, leading=20
        ),
        "h3": ParagraphStyle(
            "h3",
            parent=base,
            fontName="Helvetica",
            fontSize=11,
            leading=15,
            textColor=_MUTED,
        ),
        "body": ParagraphStyle(
            "body", parent=base, fontSize=9.5, leading=14, alignment=TA_LEFT
        ),
        "muted": ParagraphStyle(
            "muted", parent=base, fontSize=8.5, leading=12, textColor=_MUTED
        ),
    }


def _footer(lang: str | None, label: str):
    def draw(canvas, doc) -> None:  # noqa: ANN001
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(_MUTED)
        y = 12 * mm
        canvas.setStrokeColor(_RULE)
        canvas.line(doc.leftMargin, y + 4 * mm, doc.leftMargin + doc.width, y + 4 * mm)
        canvas.drawString(doc.leftMargin, y, "seo-keywords-madagascar")
        right = f"{label} · page {doc.page}" if lang else f"page {doc.page}"
        canvas.drawRightString(doc.leftMargin + doc.width, y, right)
        canvas.restoreState()

    return draw


def _intent_bar(by_intent: dict[str, int], width: float) -> Table | Spacer:
    total = sum(by_intent.values())
    if total == 0:
        return Spacer(1, 2 * mm)

    widths: list[float] = []
    commands: list[tuple] = []
    for label in INTENT_ORDER:
        count = by_intent.get(label, 0)
        if count == 0:
            continue
        index = len(widths)
        widths.append(width * count / total)
        commands.append(("BACKGROUND", (index, 0), (index, 0), INTENT_COLORS[label]))

    table = Table([[""] * len(widths)], colWidths=widths, rowHeights=[4.5 * mm])
    table.setStyle(TableStyle([*commands, ("BOX", (0, 0), (-1, -1), 0, _RULE)]))
    return table


def _intent_legend(
    by_intent: dict[str, int], styles: dict[str, ParagraphStyle]
) -> Table:
    total = sum(by_intent.values()) or 1
    rows = []
    for label in INTENT_ORDER:
        count = by_intent.get(label, 0)
        rows.append(
            [
                "",
                Paragraph(label, styles["body"]),
                Paragraph(f"{count}", styles["body"]),
                Paragraph(f"{count / total * 100:.0f} %", styles["muted"]),
            ]
        )

    table = Table(rows, colWidths=[5 * mm, 60 * mm, 20 * mm, 20 * mm])
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
    ]
    for index, label in enumerate(INTENT_ORDER):
        style.append(("BACKGROUND", (0, index), (0, index), INTENT_COLORS[label]))
    table.setStyle(TableStyle(style))
    return table


def _cover(data: ReportData, styles: dict[str, ParagraphStyle], width: float) -> list:
    run = data.run
    rows = [
        ["Run de clustering", str(run.run_id)],
        ["Modèle d'embeddings", run.model_name],
        ["Seuil de distance", f"{run.distance_threshold}"],
        ["Critère de liaison", run.linkage],
        ["Mots-clés regroupés", f"{run.keyword_count}"],
        ["Clusters", f"{run.cluster_count}"],
        ["Run calculé le", run.created_at.strftime("%d/%m/%Y %H:%M")],
        [
            "Corpus en base",
            f"{data.total_keywords} mots-clés, {len(data.langs)} langues",
        ],
        ["Seuil de page retenu", f"≥ {data.min_keywords} mots-clés par langue"],
    ]
    table = Table(
        [[Paragraph(a, styles["body"]), Paragraph(b, styles["body"])] for a, b in rows],
        colWidths=[width * 0.45, width * 0.55],
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, _RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
            ]
        )
    )
    return [
        Spacer(1, 45 * mm),
        Paragraph("Mots-clés SEO Madagascar", styles["title"]),
        Paragraph("Rapport de synthèse par langue", styles["h3"]),
        Spacer(1, 12 * mm),
        table,
        Spacer(1, 8 * mm),
        Paragraph(
            f"Généré le {data.generated_at.strftime('%d/%m/%Y à %H:%M')} (UTC)",
            styles["muted"],
        ),
    ]


def _global_section(
    data: ReportData, styles: dict[str, ParagraphStyle], width: float
) -> list:
    header = ["Langue", "Actifs", "Sans intention", "Concurrents", "Exclus", "Total"]
    rows = [[Paragraph(f"<b>{h}</b>", styles["body"]) for h in header]]
    for stats in data.langs:
        rows.append(
            [
                Paragraph(_lang_label(stats.lang), styles["body"]),
                Paragraph(f"{stats.active}", styles["body"]),
                Paragraph(f"{stats.unset} ({stats.unset_rate:.0f} %)", styles["body"]),
                Paragraph(f"{stats.competitor}", styles["body"]),
                Paragraph(f"{stats.excluded}", styles["body"]),
                Paragraph(f"{stats.total}", styles["body"]),
            ]
        )

    table = Table(rows, colWidths=[width * 0.24, *[width * 0.152] * 5])
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, _MUTED),
                ("LINEBELOW", (0, 1), (-1, -2), 0.25, _RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
            ]
        )
    )

    story = [
        Paragraph("Synthèse globale", styles["h2"]),
        Spacer(1, 5 * mm),
        table,
        Spacer(1, 9 * mm),
        Paragraph("Répartition des intentions, par langue", styles["h3"]),
        Spacer(1, 3 * mm),
    ]

    for stats in data.langs:
        story.append(Paragraph(_lang_label(stats.lang), styles["muted"]))
        story.append(Spacer(1, 1.5 * mm))
        story.append(_intent_bar(stats.by_intent, width))
        story.append(Spacer(1, 4 * mm))

    story.append(Spacer(1, 3 * mm))
    story.append(_intent_legend(data.langs[0].by_intent, styles))
    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            "La légende ci-dessus détaille la première langue ; les couleurs "
            "valent pour toutes les barres.",
            styles["muted"],
        )
    )
    return story


def _lang_section(
    stats: LangStats, data: ReportData, styles: dict[str, ParagraphStyle], width: float
) -> list:
    band = Table(
        [[Paragraph(f"<b>{_lang_label(stats.lang)}</b>", styles["h2"])]],
        colWidths=[width],
    )
    band.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _lang_fill(stats.lang)),
                ("TEXTCOLOR", (0, 0), (-1, -1), _lang_ink(stats.lang)),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LINEBEFORE", (0, 0), (0, -1), 2.5, _lang_ink(stats.lang)),
            ]
        )
    )

    counters = Table(
        [
            [
                Paragraph(f"<b>{stats.active}</b><br/>actifs", styles["body"]),
                Paragraph(f"<b>{stats.unset}</b><br/>sans intention", styles["body"]),
                Paragraph(f"<b>{stats.competitor}</b><br/>concurrents", styles["body"]),
                Paragraph(f"<b>{stats.excluded}</b><br/>exclus", styles["body"]),
                Paragraph(
                    f"<b>{len(stats.pages)}</b><br/>pages retenues", styles["body"]
                ),
            ]
        ],
        colWidths=[width / 5] * 5,
    )
    counters.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F7F6F2")),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )

    story = [
        band,
        Spacer(1, 6 * mm),
        counters,
        Spacer(1, 7 * mm),
        Paragraph("Intentions de recherche", styles["h3"]),
        Spacer(1, 2 * mm),
        _intent_bar(stats.by_intent, width),
        Spacer(1, 3 * mm),
        _intent_legend(stats.by_intent, styles),
        Spacer(1, 8 * mm),
        Paragraph("Pages projetées", styles["h3"]),
        Spacer(1, 2 * mm),
    ]

    if not stats.pages:
        story.append(
            Paragraph(
                f"Aucun cluster n'atteint {data.min_keywords} mots-clés dans "
                f"cette langue.",
                styles["muted"],
            )
        )
        return story

    header = ["Cluster", "Titre proposé", "Mots-clés", "Statut"]
    rows = [[Paragraph(f"<b>{h}</b>", styles["body"]) for h in header]]
    for page in stats.pages:
        rows.append(
            [
                Paragraph(str(page.cluster_id), styles["body"]),
                Paragraph(page.title, styles["body"]),
                Paragraph(str(page.keyword_count), styles["body"]),
                Paragraph(page.status, styles["muted"]),
            ]
        )

    table = Table(
        rows,
        colWidths=[width * 0.12, width * 0.53, width * 0.15, width * 0.20],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, _MUTED),
                ("LINEBELOW", (0, 1), (-1, -2), 0.25, _RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
            ]
        )
    )
    story.append(table)

    if stats.pages_skipped:
        story.append(Spacer(1, 3 * mm))
        story.append(
            Paragraph(
                f"{stats.pages_skipped} clusters écartés : moins de "
                f"{data.min_keywords} mots-clés dans cette langue.",
                styles["muted"],
            )
        )
    return story


def _annex(data: ReportData, styles: dict[str, ParagraphStyle], width: float) -> list:
    story = [
        Paragraph("Annexe — clusters à retravailler", styles["h2"]),
        Spacer(1, 3 * mm),
        Paragraph(
            "Ces clusters dépassent la taille d'une page éditoriale. Ils "
            "mélangent probablement plusieurs intentions et méritent un "
            "redécoupage (split-cluster).",
            styles["body"],
        ),
        Spacer(1, 5 * mm),
    ]

    if not data.oversized:
        story.append(Paragraph("Aucun cluster surdimensionné.", styles["muted"]))
        return story

    header = ["Cluster", "Mots-clés", "Tête de cluster"]
    rows = [[Paragraph(f"<b>{h}</b>", styles["body"]) for h in header]]
    for cluster in data.oversized:
        rows.append(
            [
                Paragraph(str(cluster.cluster_id), styles["body"]),
                Paragraph(str(cluster.keyword_count), styles["body"]),
                Paragraph(cluster.head, styles["body"]),
            ]
        )

    table = Table(
        rows, colWidths=[width * 0.15, width * 0.18, width * 0.67], repeatRows=1
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, _MUTED),
                ("LINEBELOW", (0, 1), (-1, -2), 0.25, _RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
            ]
        )
    )
    story.append(table)
    return story


def render_pdf(data: ReportData, output_path: str) -> str:
    """Écrit le rapport et retourne le chemin produit."""
    doc = BaseDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title="Mots-clés SEO Madagascar",
        author="seo-keywords-madagascar",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")

    templates = [
        PageTemplate(id="cover", frames=[frame], onPage=_footer(None, "")),
        PageTemplate(id="global", frames=[frame], onPage=_footer(None, "")),
    ]
    for stats in data.langs:
        templates.append(
            PageTemplate(
                id=f"lang-{stats.lang}",
                frames=[frame],
                onPage=_footer(stats.lang, _lang_label(stats.lang)),
            )
        )
    templates.append(PageTemplate(id="annex", frames=[frame], onPage=_footer(None, "")))
    doc.addPageTemplates(templates)

    styles = _styles()
    story: list = []
    story += _cover(data, styles, doc.width)
    story.append(NextPageTemplate("global"))
    story.append(PageBreak())
    story += _global_section(data, styles, doc.width)

    for stats in data.langs:
        story.append(NextPageTemplate(f"lang-{stats.lang}"))
        story.append(PageBreak())
        story += _lang_section(stats, data, styles, doc.width)

    story.append(NextPageTemplate("annex"))
    story.append(PageBreak())
    story += _annex(data, styles, doc.width)

    doc.build(story)
    return output_path