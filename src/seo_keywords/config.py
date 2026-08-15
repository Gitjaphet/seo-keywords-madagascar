"""Configuration centrale du projet.

Toutes les valeurs "métier" (seeds, langues, saisons) vivent ici,
séparées de la logique de collecte, pour pouvoir les ajuster
sans toucher au code.
"""

from __future__ import annotations

from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class Season(str, Enum):
    """Saisons touristiques à Madagascar (côte ouest / Nosy Be)."""

    HAUTE_SAISON = "haute_saison"  # avril - décembre : sec, très fréquenté
    SAISON_CYCLONIQUE = "saison_cyclonique"  # janvier - mars : pluies, cyclones

    @classmethod
    def from_month(cls, month: int) -> Season:
        if month in (1, 2, 3):
            return cls.SAISON_CYCLONIQUE
        return cls.HAUTE_SAISON


# Mots-clés de départ, par langue. Ce sont les points d'entrée
# pour l'expansion via Google Autocomplete.
SEED_KEYWORDS: dict[str, list[str]] = {
    "fr": [
        "excursion nosy be",
        "circuit madagascar",
        "tour operateur madagascar",
        "agence de voyage madagascar",
        "que faire nosy be",
        "voyage madagascar",
        "excursion ile aux nattes",
        "safari madagascar",
        "croisiere nosy be",
        "sejour madagascar",
    ],
    "en": [
        "excursion nosy be",
        "madagascar tour package",
        "madagascar travel agency",
        "things to do nosy be",
        "madagascar trip",
        "madagascar safari tour",
        "nosy be day trip",
        "madagascar vacation",
    ],
    "de": [
        "ausflug nosy be",
        "madagaskar reise",
        "madagaskar rundreise",
        "reiseveranstalter madagaskar",
        "madagaskar urlaub",
    ],
}

# Marchés (géo Google Trends) prioritaires à comparer.
# '' = mondial, sinon code pays ISO-2.
TARGET_MARKETS: list[str] = ["", "FR", "DE", "US", "IT"]


class Settings(BaseSettings):
    """Paramètres runtime, surchargeables via variables d'environnement (.env)."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="SEO_", extra="ignore")

    database_path: str = "data/processed/keywords.db"
    raw_output_dir: str = "data/raw"
    processed_output_dir: str = "data/processed"

    # Politesse réseau : délai entre deux requêtes (secondes)
    request_delay_seconds: float = 0.5
    request_timeout_seconds: float = 8.0
    max_retries: int = 3

    # Alphabet utilisé pour l'expansion "seed + lettre" (a-z par défaut)
    expansion_alphabet: str = "abcdefghijklmnopqrstuvwxyz"

    trends_timeframe: str = "today 5-y"


settings = Settings()
