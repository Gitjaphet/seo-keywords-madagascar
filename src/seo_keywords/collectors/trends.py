"""Collecteur basé sur Google Trends (via pytrends).

Fournit un volume d'intérêt RELATIF (0-100, normalisé par lot de requête),
pas un volume absolu de recherches. Suffisant pour dégager un pattern de
saisonnalité (quels mois montent/descendent), pas pour du reporting de
volume brut — pour ça, il faudra Google Ads Keyword Planner API.
"""

from __future__ import annotations

import logging
import time

from pytrends.request import TrendReq

from seo_keywords.config import settings

logger = logging.getLogger(__name__)

MAX_KEYWORDS_PER_BATCH = 5  # limite imposée par Google Trends


class TrendsCollector:
    source_name = "google_trends"

    def __init__(self, tz_offset_minutes: int = 180) -> None:
        # tz=180 -> UTC+3, fuseau de Madagascar
        self._pytrends = TrendReq(hl="fr-FR", tz=tz_offset_minutes)

    def monthly_averages(
        self, keywords: list[str], geo: str = "", timeframe: str | None = None
    ) -> dict[str, dict[int, float]]:
        """Retourne, pour chaque mot-clé, la moyenne d'intérêt par mois (1-12).

        Le résultat est un dict: {keyword: {1: 23.4, 2: 18.1, ..., 12: 45.0}}
        """
        timeframe = timeframe or settings.trends_timeframe
        results: dict[str, dict[int, float]] = {}

        for i in range(0, len(keywords), MAX_KEYWORDS_PER_BATCH):
            batch = keywords[i : i + MAX_KEYWORDS_PER_BATCH]
            try:
                self._pytrends.build_payload(batch, timeframe=timeframe, geo=geo)
                df = self._pytrends.interest_over_time()
            except Exception:
                logger.warning("Échec Trends pour le lot %s (geo=%s)", batch, geo, exc_info=True)
                continue

            if df.empty:
                continue

            df = df.drop(columns=["isPartial"], errors="ignore")
            df["month"] = df.index.month
            monthly = df.groupby("month")[batch].mean()

            for kw in batch:
                if kw in monthly.columns:
                    results[kw] = {int(m): round(float(v), 2) for m, v in monthly[kw].items()}

            time.sleep(settings.request_delay_seconds * 4)  # Trends est sensible au rate-limit

        return results
