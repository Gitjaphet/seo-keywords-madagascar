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
        # Nosy Be et excursions insulaires
        "excursion nosy be",
        "que faire nosy be",
        "croisiere nosy be",
        "excursion ile aux nattes",
        "excursion nosy iranja",
        # Offre generique
        "circuit madagascar",
        "tour operateur madagascar",
        "agence de voyage madagascar",
        "voyage madagascar",
        "safari madagascar",
        "sejour madagascar",
        # Circuits par region
        "circuit nord madagascar",
        "circuit sud madagascar",
        "route nationale 7 madagascar",
        "traversee tsiribihina",
        # Parcs et sites
        "tsingy de bemaraha",
        "allee des baobabs",
        "parc isalo",
        "parc ranomafana",
        "andasibe mantadia",
        "montagne d ambre madagascar",
        "reserve ankarana",
        # Villes et points d'entree
        "diego suarez madagascar",
        "tulear madagascar",
        "morondava madagascar",
        "sainte marie madagascar",
        "antsirabe madagascar",
        "fort dauphin madagascar",
        # Themes
        "lemurien madagascar",
        "baleines sainte marie",
        "plongee madagascar",
        "trekking madagascar",
    ],
    "en": [
        "excursion nosy be",
        "things to do nosy be",
        "nosy be day trip",
        "nosy iranja excursion",
        "madagascar tour package",
        "madagascar travel agency",
        "madagascar trip",
        "madagascar safari tour",
        "madagascar vacation",
        "north madagascar tour",
        "south madagascar tour",
        "rn7 madagascar road trip",
        "tsingy de bemaraha",
        "avenue of the baobabs",
        "isalo national park",
        "ranomafana national park",
        "andasibe national park",
        "amber mountain madagascar",
        "ankarana reserve",
        "diego suarez madagascar",
        "tulear madagascar",
        "morondava madagascar",
        "sainte marie madagascar",
        "madagascar lemur tour",
        "whale watching madagascar",
        "madagascar diving",
        "madagascar trekking",
        "madagascar wildlife tour",
    ],
    "de": [
        "ausflug nosy be",
        "nosy be tagesausflug",
        "madagaskar reise",
        "madagaskar rundreise",
        "reiseveranstalter madagaskar",
        "madagaskar urlaub",
        "madagaskar nord rundreise",
        "madagaskar sued rundreise",
        "tsingy bemaraha",
        "baobab allee madagaskar",
        "isalo nationalpark",
        "ranomafana nationalpark",
        "andasibe madagaskar",
        "ankarana madagaskar",
        "diego suarez madagaskar",
        "tulear madagaskar",
        "morondava madagaskar",
        "sainte marie madagaskar",
        "lemuren madagaskar",
        "walbeobachtung madagaskar",
        "madagaskar tauchen",
        "madagaskar trekking",
        "madagaskar naturreise",
    ],
    "it": [
        "escursione nosy be",
        "cosa fare a nosy be",
        "crociera nosy be",
        "escursione nosy iranja",
        "tour madagascar",
        "tour operator madagascar",
        "agenzia di viaggi madagascar",
        "viaggio madagascar",
        "vacanza madagascar",
        "safari madagascar",
        "tour nord madagascar",
        "tour sud madagascar",
        "tsingy bemaraha",
        "viale dei baobab",
        "parco isalo",
        "parco ranomafana",
        "andasibe madagascar",
        "montagna d ambra madagascar",
        "diego suarez madagascar",
        "tulear madagascar",
        "morondava madagascar",
        "sainte marie madagascar",
        "lemuri madagascar",
        "avvistamento balene madagascar",
        "immersioni madagascar",
        "trekking madagascar",
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
