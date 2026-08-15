"""Couche d'accès aux données : écriture/lecture SQLite.

Isole le reste du code de la base de données choisie. Passer de SQLite
à Postgres plus tard = changer une URL de connexion, rien d'autre.
"""

from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from seo_keywords.collectors.base import KeywordSuggestion
from seo_keywords.storage.models import KeywordRecord, SeasonalityRecord


class KeywordRepository:
    def __init__(self, database_path: str) -> None:
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{database_path}")
        SQLModel.metadata.create_all(self._engine)

    def save_suggestions(self, suggestions: list[KeywordSuggestion]) -> int:
        """Insère les nouveaux mots-clés, ignore ceux déjà connus
        (même keyword + lang + source). Retourne le nombre insérés.
        """
        inserted = 0
        with Session(self._engine) as session:
            for s in suggestions:
                exists = session.exec(
                    select(KeywordRecord).where(
                        KeywordRecord.keyword == s.keyword,
                        KeywordRecord.lang == s.lang,
                        KeywordRecord.source == s.source,
                    )
                ).first()
                if exists:
                    continue
                session.add(
                    KeywordRecord(keyword=s.keyword, lang=s.lang, source=s.source, seed=s.seed)
                )
                inserted += 1
            session.commit()
        return inserted

    def save_seasonality(self, keyword: str, geo: str, monthly_scores: dict[int, float]) -> None:
        with Session(self._engine) as session:
            for month, score in monthly_scores.items():
                session.add(
                    SeasonalityRecord(keyword=keyword, geo=geo, month=month, interest_score=score)
                )
            session.commit()

    def get_all_keywords(self, lang: str | None = None) -> list[KeywordRecord]:
        with Session(self._engine) as session:
            query = select(KeywordRecord)
            if lang:
                query = query.where(KeywordRecord.lang == lang)
            return list(session.exec(query).all())

    def get_seasonality(self, geo: str = "") -> list[SeasonalityRecord]:
        with Session(self._engine) as session:
            query = select(SeasonalityRecord).where(SeasonalityRecord.geo == geo)
            return list(session.exec(query).all())
