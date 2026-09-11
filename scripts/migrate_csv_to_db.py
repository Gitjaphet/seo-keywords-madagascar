"""Migration des CSV vers la base — la base devient la source de vérité.

Idempotent : relançable autant de fois que nécessaire sans dupliquer ni
écraser. Une décision MANUAL déjà posée n'est jamais rétrogradée en AUTO.

Contrôles de fin : si le nombre de décisions manuelles ne correspond pas
à l'attendu, la transaction est annulée et rien n'est écrit.

Usage :
    python scripts/migrate_csv_to_db.py --dry-run
    python scripts/migrate_csv_to_db.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from seo_keywords.storage.models import (
    Intent,
    IntentSource,
    Keyword,
    KeywordMetric,
    KeywordRevision,
    KeywordStatus,
    MetricSource,
)

PROCESSED_DIR = Path("data/processed")
GOOGLE_ADS_DIR = Path("data/raw/google_ads")
DB_PATH = PROCESSED_DIR / "keywords.db"

# Nombre de lignes taguées à la main dans to_tag_fr.csv. Le script échoue
# si le compte final diverge : c'est le garde-fou contre une perte
# silencieuse du travail manuel.
EXPECTED_MANUAL = 146

MIGRATION_REASON = "migration initiale CSV -> base"

# Valeurs de la colonne 'intent' des CSV qui ne sont pas des intentions
# mais des décisions de rejet. Le modèle sépare les deux notions.
STATUS_KEYWORDS: dict[str, KeywordStatus] = {
    "exclure": KeywordStatus.EXCLUDED,
    "concurrent": KeywordStatus.COMPETITOR,
}


# --------------------------------------------------------------------------
# Lecture des CSV
# --------------------------------------------------------------------------


def read_rows_tolerant(path: Path, n_fixed: int) -> list[list[str]]:
    """Lit un CSV dont le dernier champ peut contenir des virgules non
    échappées (saisie manuelle dans un tableur).

    Les `n_fixed` premières colonnes ne contiennent jamais de virgule :
    tout ce qui suit est réassemblé en un seul champ.
    """
    if not path.exists():
        return []

    rows: list[list[str]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)  # en-tête
        for raw in reader:
            if not raw or not raw[0].strip():
                continue
            if len(raw) > n_fixed:
                raw = [*raw[:n_fixed], ",".join(raw[n_fixed:]).strip()]
            while len(raw) < n_fixed + 1:
                raw.append("")
            rows.append([field.strip() for field in raw])
    return rows


def parse_intent(value: str) -> tuple[Intent | None, KeywordStatus | None]:
    """Traduit la colonne 'intent' d'un CSV.

    Renvoie (intention, statut). L'un des deux est None : soit c'est une
    vraie intention de recherche, soit c'est une décision de rejet.
    """
    cleaned = value.strip().lower()
    if not cleaned:
        return None, None
    if cleaned in STATUS_KEYWORDS:
        return None, STATUS_KEYWORDS[cleaned]
    try:
        return Intent(cleaned), None
    except ValueError:
        print(f"  ! intention inconnue ignorée : {value!r}", file=sys.stderr)
        return None, None


def parse_decimal(value: str) -> Decimal | None:
    """Convertit un montant Google Ads ('"17406,00"') en Decimal."""
    cleaned = value.strip().strip('"').replace("\u202f", "").replace(" ", "")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned.replace(",", "."))
    except InvalidOperation:
        return None


def read_google_ads(path: Path) -> list[dict[str, str]]:
    """Lit l'export 'Keyword Stats' de Google Ads.

    Extension .csv trompeuse : UTF-16 little-endian, séparé par des
    tabulations, avec deux lignes de titre avant l'en-tête réel.
    """
    if not path.exists():
        return []

    with path.open(encoding="utf-16", newline="") as handle:
        lines = handle.read().splitlines()

    reader = csv.DictReader(lines[2:], delimiter="\t")
    # Les lignes sans mot-clé sont des totaux ('Tous', 'France'), pas des
    # données : on les écarte.
    return [row for row in reader if (row.get("Keyword") or "").strip()]


# --------------------------------------------------------------------------
# Écriture
# --------------------------------------------------------------------------


def log_change(
    session: Session,
    keyword: Keyword,
    field_name: str,
    old: object,
    new: object,
) -> None:
    """Journalise un changement de valeur, s'il y en a un."""
    old_str = None if old is None else str(getattr(old, "value", old))
    new_str = None if new is None else str(getattr(new, "value", new))
    if old_str == new_str:
        return
    session.add(
        KeywordRevision(
            keyword_id=keyword.id,  # type: ignore[arg-type]
            field_name=field_name,
            old_value=old_str,
            new_value=new_str,
            changed_by_id=None,
            reason=MIGRATION_REASON,
        )
    )


def apply_field(
    session: Session, keyword: Keyword, field_name: str, new_value: object
) -> None:
    """Pose une valeur en journalisant l'ancienne."""
    old_value = getattr(keyword, field_name)
    if old_value == new_value:
        return
    log_change(session, keyword, field_name, old_value, new_value)
    setattr(keyword, field_name, new_value)


def get_or_create(session: Session, kw: str, lang: str, seed: str) -> Keyword:
    existing = session.exec(
        select(Keyword).where(Keyword.keyword == kw, Keyword.lang == lang)
    ).first()
    if existing is not None:
        return existing

    created = Keyword(keyword=kw, lang=lang, seed=seed)
    session.add(created)
    session.flush()  # pour obtenir l'id avant de journaliser
    return created


# --------------------------------------------------------------------------
# Étapes
# --------------------------------------------------------------------------


def copy_legacy_table(session: Session) -> int:
    """Recopie keywordrecord vers keyword, sans écraser l'existant."""
    tables = {
        row[0]
        for row in session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")  # type: ignore[arg-type]
        )
    }
    if "keywordrecord" not in tables:
        print("  keywordrecord absente (déjà migrée), étape ignorée")
        return 0

    session.execute(
        text(  # type: ignore[arg-type]
            """
            INSERT INTO keyword (keyword, lang, source, seed, collected_at,
                                 intent_source, status, notes,
                                 autocomplete_depth, last_seen_at)
            SELECT r.keyword, r.lang, r.source, r.seed, r.collected_at,
                   'unset', 'active', '', 1, r.collected_at
            FROM keywordrecord AS r
            WHERE NOT EXISTS (
                SELECT 1 FROM keyword AS k
                WHERE k.keyword = r.keyword AND k.lang = r.lang
            )
            """
        )
    )
    inserted = session.execute(text("SELECT COUNT(*) FROM keyword")).one()[0]  # type: ignore[arg-type]
    return int(inserted)


def apply_manual_tags(session: Session) -> int:
    """to_tag_fr.csv — les décisions humaines. Priorité absolue."""
    rows = read_rows_tolerant(PROCESSED_DIR / "to_tag_fr.csv", n_fixed=4)
    count = 0
    for kw, seed, lang, raw_intent, notes in rows:
        if not raw_intent:
            continue
        intent, status = parse_intent(raw_intent)
        if intent is None and status is None:
            continue

        record = get_or_create(session, kw, lang, seed)
        apply_field(session, record, "intent", intent)
        apply_field(session, record, "intent_source", IntentSource.MANUAL)
        if status is not None:
            apply_field(session, record, "status", status)
        if notes:
            apply_field(session, record, "notes", notes[:500])
        record.reviewed_at = record.reviewed_at or datetime.now(UTC)
        count += 1
    return count


def apply_auto_tags(session: Session, langs: tuple[str, ...]) -> int:
    """classified_*.csv — jamais appliqué sur une ligne MANUAL."""
    count = 0
    for lang in langs:
        rows = read_rows_tolerant(
            PROCESSED_DIR / f"classified_{lang}.csv", n_fixed=4
        )
        for kw, seed, row_lang, raw_intent, matched_rule in rows:
            intent, status = parse_intent(raw_intent)
            record = get_or_create(session, kw, row_lang or lang, seed)

            if record.intent_source is IntentSource.MANUAL:
                continue  # verrou : le pipeline ne touche pas à l'humain

            apply_field(session, record, "intent", intent)
            apply_field(session, record, "intent_source", IntentSource.AUTO)
            apply_field(session, record, "matched_rule", matched_rule[:255] or None)
            if status is not None:
                apply_field(session, record, "status", status)
            count += 1
    return count


def apply_clusters(session: Session) -> int:
    """clustered_fr.csv — schéma : cluster,keyword,seed,lang,intent,notes."""
    rows = read_rows_tolerant(PROCESSED_DIR / "clustered_fr.csv", n_fixed=5)
    count = 0
    for cluster, kw, seed, lang, _intent, _notes in rows:
        if not cluster:
            continue
        record = get_or_create(session, kw, lang, seed)
        apply_field(session, record, "cluster", cluster)
        count += 1
    return count


def apply_google_ads(session: Session) -> int:
    """Crée les relevés de métriques. Marché FR (test manuel du 10/09)."""
    files = sorted(GOOGLE_ADS_DIR.glob("Keyword Stats*.csv"))
    if not files:
        print("  aucun export Google Ads trouvé, étape ignorée")
        return 0

    count = 0
    for path in files:
        fetched_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        for row in read_google_ads(path):
            kw = (row.get("Keyword") or "").strip()
            record = session.exec(
                select(Keyword).where(Keyword.keyword == kw, Keyword.lang == "fr")
            ).first()
            if record is None:
                continue

            already = session.exec(
                select(KeywordMetric).where(
                    KeywordMetric.keyword_id == record.id,
                    KeywordMetric.market == "FR",
                    KeywordMetric.source == MetricSource.GOOGLE_ADS,
                    KeywordMetric.fetched_at == fetched_at,
                )
            ).first()
            if already is not None:
                continue

            volume_raw = (row.get("Avg. monthly searches") or "").strip()
            index_raw = (row.get("Competition (indexed value)") or "").strip()

            session.add(
                KeywordMetric(
                    keyword_id=record.id,  # type: ignore[arg-type]
                    market="FR",
                    language="fr",
                    search_volume=int(float(volume_raw)) if volume_raw else None,
                    volume_is_bucketed=True,
                    ads_competition_index=int(index_raw) if index_raw else None,
                    ads_competition_label=(row.get("Competition") or "").strip()
                    or None,
                    cpc_low=parse_decimal(row.get("Top of page bid (low range)") or ""),
                    cpc_high=parse_decimal(
                        row.get("Top of page bid (high range)") or ""
                    ),
                    currency=(row.get("Currency") or "").strip()[:3],
                    source=MetricSource.GOOGLE_ADS,
                    fetched_at=fetched_at,
                )
            )
            count += 1
    return count


def backup_legacy_table(session: Session) -> None:
    """Renomme keywordrecord plutôt que de la supprimer."""
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    target = f"keywordrecord_backup_{stamp}"
    tables = {
        row[0]
        for row in session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")  # type: ignore[arg-type]
        )
    }
    if "keywordrecord" not in tables or target in tables:
        return
    session.execute(text(f"ALTER TABLE keywordrecord RENAME TO {target}"))  # type: ignore[arg-type]
    print(f"  keywordrecord sauvegardée sous {target}")


def report(session: Session) -> Counter[str]:
    """Rapport de contrôle."""
    keywords = session.exec(select(Keyword)).all()
    counts: Counter[str] = Counter()
    for record in keywords:
        counts[f"status:{record.status.value}"] += 1
        counts[f"source:{record.intent_source.value}"] += 1
        if record.cluster:
            counts["avec cluster"] += 1
    counts["total"] = len(keywords)
    counts["métriques"] = len(session.exec(select(KeywordMetric)).all())
    counts["révisions"] = len(session.exec(select(KeywordRevision)).all())
    return counts


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="exécute tout puis annule, sans rien écrire",
    )
    parser.add_argument(
        "--expected-manual",
        type=int,
        default=EXPECTED_MANUAL,
        help=f"nombre attendu de décisions manuelles (défaut {EXPECTED_MANUAL})",
    )
    args = parser.parse_args()

    engine = create_engine(f"sqlite:///{DB_PATH}")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        print("→ recopie de keywordrecord")
        total = copy_legacy_table(session)
        print(f"  {total} lignes dans keyword")

        print("→ décisions manuelles (to_tag_fr.csv)")
        print(f"  {apply_manual_tags(session)} appliquées")

        print("→ classification automatique (classified_*.csv)")
        print(f"  {apply_auto_tags(session, ('en', 'de', 'it'))} appliquées")

        print("→ clusters (clustered_fr.csv)")
        print(f"  {apply_clusters(session)} appliqués")

        print("→ métriques Google Ads")
        print(f"  {apply_google_ads(session)} relevés créés")

        session.flush()
        counts = report(session)

        print("\n--- contrôle ---")
        for key in sorted(counts):
            print(f"  {key:<22} {counts[key]}")

        manual = counts["source:manual"]
        if manual != args.expected_manual:
            print(
                f"\n✗ ÉCHEC : {manual} décisions manuelles, "
                f"{args.expected_manual} attendues. Annulation.",
                file=sys.stderr,
            )
            session.rollback()
            return 1

        if args.dry_run:
            session.rollback()
            print("\n✓ contrôles passés — dry-run, rien n'a été écrit")
            return 0

        backup_legacy_table(session)
        session.commit()
        print("\n✓ migration appliquée")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
