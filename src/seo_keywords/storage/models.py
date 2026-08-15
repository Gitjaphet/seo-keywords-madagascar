"""Modèles de données persistés en base."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class KeywordRecord(SQLModel, table=True):
    """Un mot-clé collecté, avec sa source et sa date de collecte.

    unique(keyword, lang, source) est appliqué au niveau applicatif
    (voir repository.upsert) plutôt qu'en contrainte DB stricte, pour
    pouvoir requêter facilement l'historique si besoin plus tard.
    """

    id: int | None = Field(default=None, primary_key=True)
    keyword: str = Field(index=True)
    lang: str = Field(index=True)
    source: str = Field(index=True)
    seed: str
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SeasonalityRecord(SQLModel, table=True):
    """Score d'intérêt mensuel (Google Trends) pour un mot-clé et un marché."""

    id: int | None = Field(default=None, primary_key=True)
    keyword: str = Field(index=True)
    geo: str = Field(index=True, description="'' = mondial, sinon code pays ISO-2")
    month: int  # 1-12
    interest_score: float  # 0-100, relatif au lot de mots-clés interrogé
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
