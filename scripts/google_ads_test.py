"""Test de connexion à l'API Google Ads.

Vérifie trois choses d'un coup :
  1. les identifiants OAuth du .env sont valides
  2. le niveau d'accès du projet Cloud autorise les comptes de production
  3. KeywordPlanIdeaService répond sur le compte interrogé

Le même lot de 15 mots-clés que le test manuel du planificateur, pour
pouvoir comparer les chiffres ligne à ligne.

Usage :
    uv run python scripts/google_ads_test.py
    uv run python scripts/google_ads_test.py --market DE
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

# Identifiants géographiques et linguistiques de Google Ads. Ce sont des
# constantes de l'API, pas des codes ISO.
GEO_TARGETS = {"FR": 2250, "DE": 2276, "IT": 2380, "BE": 2056, "CH": 2756}
LANGUAGES = {"fr": 1002, "en": 1000, "de": 1001, "it": 1004}

SAMPLE_KEYWORDS = [
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
    "que faire a nosy be",
    "que faire a hell ville nosy be",
    "excursion nosy iranja",
    "plantation vanille nosy be",
    "agence excursion nosy be",
]


def micros_to_units(micros: int | None) -> str:
    """L'API exprime les montants en micro-unités de la devise du compte."""
    if not micros:
        return "—"
    return f"{micros / 1_000_000:,.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", default="FR", choices=sorted(GEO_TARGETS))
    parser.add_argument("--lang", default="fr", choices=sorted(LANGUAGES))
    args = parser.parse_args()

    load_dotenv(Path(__file__).parent.parent / ".env")

    customer_id = os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "").replace("-", "")
    if not customer_id:
        print("GOOGLE_ADS_CUSTOMER_ID absent du .env", file=sys.stderr)
        return 1

    try:
        client = GoogleAdsClient.load_from_env()
    except Exception as exc:  # noqa: BLE001
        print(f"Configuration invalide : {exc}", file=sys.stderr)
        return 1

    service = client.get_service("KeywordPlanIdeaService")
    request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    request.customer_id = customer_id
    request.keywords.extend(SAMPLE_KEYWORDS)
    request.geo_target_constants.append(
        f"geoTargetConstants/{GEO_TARGETS[args.market]}"
    )
    request.language = f"languageConstants/{LANGUAGES[args.lang]}"
    request.keyword_plan_network = (
        client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    )
    # Sans ce drapeau, l'API regroupe les variantes proches sous une même
    # ligne et on perd la correspondance avec les mots-clés envoyés.
    request.include_adult_keywords = False

    try:
        response = service.generate_keyword_historical_metrics(request=request)
    except GoogleAdsException as exc:
        print(f"\n✗ Appel refusé (request_id {exc.request_id})", file=sys.stderr)
        for error in exc.failure.errors:
            print(f"  {error.error_code}: {error.message}", file=sys.stderr)
        return 1

    print(f"\nMarché {args.market} · langue {args.lang}\n")
    header = f"{'mot-clé':<34}{'volume':>10}{'conc.':>7}{'CPC bas':>10}{'CPC haut':>10}"
    print(header)
    print("-" * len(header))

    rows = 0
    monthly_seen = False
    for result in response.results:
        metrics = result.keyword_metrics
        volume = metrics.avg_monthly_searches
        index = metrics.competition_index
        if metrics.monthly_search_volumes:
            monthly_seen = True
        print(
            f"{result.text[:33]:<34}"
            f"{volume if volume else '—':>10}"
            f"{index if index else '—':>7}"
            f"{micros_to_units(metrics.low_top_of_page_bid_micros):>10}"
            f"{micros_to_units(metrics.high_top_of_page_bid_micros):>10}"
        )
        rows += 1

    print(f"\n✓ {rows} lignes reçues — la connexion fonctionne")
    print(
        "  ventilation mensuelle : "
        + ("disponible" if monthly_seen else "absente (compte sans dépense)")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
