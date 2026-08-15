"""Interface commune à tous les collecteurs de mots-clés.

Chaque nouvelle source (Bing Suggest, YouTube Suggest, Google Ads API...)
doit implémenter cette interface pour rester interchangeable avec
le reste du pipeline (storage, analysis, cli).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KeywordSuggestion:
    """Un mot-clé collecté, avec son contexte de collecte."""

    keyword: str
    source: str  # ex: "google_autocomplete", "google_trends"
    lang: str  # ex: "fr", "en", "de"
    seed: str  # mot-clé racine ayant produit cette suggestion


class BaseCollector(ABC):
    """Contrat que tout collecteur doit respecter."""

    source_name: str

    @abstractmethod
    def collect(self, seed: str, lang: str) -> list[KeywordSuggestion]:
        """Collecte les suggestions pour un seed et une langue donnés.

        Doit toujours retourner une liste (vide en cas d'échec réseau,
        jamais lever d'exception pour une erreur réseau ponctuelle —
        voir tenacity retry dans les implémentations concrètes).
        """
        raise NotImplementedError
