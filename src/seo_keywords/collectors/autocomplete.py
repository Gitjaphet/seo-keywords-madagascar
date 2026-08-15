"""Collecteur basé sur l'API publique de suggestions Google (Autocomplete).

Endpoint officiel, non-authentifié, utilisé par la barre de recherche
Google elle-même. Ce n'est PAS du scraping de SERP (pas de parsing HTML
fragile, pas de contournement de captcha) : c'est un appel à un endpoint
JSON public. Reste correct : on respecte un délai entre requêtes.
"""

from __future__ import annotations

import logging
import time

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from seo_keywords.collectors.base import BaseCollector, KeywordSuggestion
from seo_keywords.config import settings

logger = logging.getLogger(__name__)

AUTOCOMPLETE_URL = "https://suggestqueries.google.com/complete/search"


class AutocompleteCollector(BaseCollector):
    source_name = "google_autocomplete"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.update(
            {"User-Agent": "Mozilla/5.0 (compatible; seo-keywords-madagascar/0.1)"}
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=False,
    )
    def _fetch(self, query: str, lang: str) -> list[str]:
        response = self._session.get(
            AUTOCOMPLETE_URL,
            params={"client": "firefox", "q": query, "hl": lang},
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        # Format de réponse: [query, [suggestion1, suggestion2, ...]]
        suggestions = data[1] if len(data) > 1 else []
        return [s for s in suggestions if isinstance(s, str)]

    def collect(self, seed: str, lang: str) -> list[KeywordSuggestion]:
        try:
            raw_suggestions = self._fetch(seed, lang)
        except Exception:
            logger.warning("Échec collecte autocomplete pour '%s' (%s)", seed, lang, exc_info=True)
            return []

        return [
            KeywordSuggestion(keyword=s.strip(), source=self.source_name, lang=lang, seed=seed)
            for s in raw_suggestions
            if s.strip()
        ]

    def collect_expanded(
        self, seed: str, lang: str, alphabet: str = settings.expansion_alphabet
    ) -> list[KeywordSuggestion]:
        """Étend un seed avec chaque lettre de l'alphabet ('excursion nosy be a',
        'excursion nosy be b', ...) pour creuser au-delà des ~10 suggestions
        de base que Google renvoie pour une requête nue.
        """
        all_suggestions: list[KeywordSuggestion] = list(self.collect(seed, lang))

        for letter in alphabet:
            all_suggestions.extend(self.collect(f"{seed} {letter}", lang))
            time.sleep(settings.request_delay_seconds)

        # Dédoublonnage en gardant l'ordre d'apparition
        seen: set[str] = set()
        deduped: list[KeywordSuggestion] = []
        for s in all_suggestions:
            key = s.keyword.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(s)
        return deduped
