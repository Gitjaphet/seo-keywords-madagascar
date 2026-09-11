"""Génère le refresh token OAuth pour l'API Google Ads.

À lancer UNE FOIS, en local, avec un navigateur disponible. Le refresh
token obtenu reste valable tant qu'il n'est pas révoqué : il alimente
ensuite le cron sans aucune réauthentification.

Les jetons de développeur ayant été supprimés le 9 septembre 2026, les
niveaux d'accès sont désormais portés par le projet Google Cloud qui a
émis ces identifiants OAuth — d'où l'absence de developer_token ici.

Usage :
    python scripts/google_ads_authorize.py chemin/vers/client_secret.json
"""

import argparse
import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

# Portée minimale : lecture et écriture sur l'API Google Ads. Il n'en
# existe pas de plus restreinte côté Google.
SCOPES = ["https://www.googleapis.com/auth/adwords"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "client_secret",
        type=Path,
        help="fichier JSON téléchargé depuis Google Cloud Console",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="port local pour la redirection OAuth (défaut 8080)",
    )
    args = parser.parse_args()

    if not args.client_secret.exists():
        print(f"Fichier introuvable : {args.client_secret}", file=sys.stderr)
        return 1

    payload = json.loads(args.client_secret.read_text(encoding="utf-8"))
    block = payload.get("installed") or payload.get("web")
    if block is None:
        print(
            "JSON inattendu : ni clé 'installed' ni 'web'. Vérifie que le "
            "client OAuth est bien de type « Application de bureau ».",
            file=sys.stderr,
        )
        return 1

    flow = InstalledAppFlow.from_client_config({"installed": block}, scopes=SCOPES)

    # Un navigateur s'ouvre ; l'écran « Google n'a pas validé cette
    # application » est attendu tant que l'app reste en mode test.
    # Passer par « Paramètres avancés » puis le lien de continuation.
    # Le message d'invitation part sur stderr : la sortie standard ne
    # doit contenir que les variables, pour permettre `>> .env`.
    credentials = flow.run_local_server(
        authorization_prompt_message=(
            "Ouvre cette URL pour autoriser l'application :\n{url}"
        ),
        port=args.port,
        prompt="consent",  # force l'émission d'un refresh_token
        access_type="offline",
    )

    if not credentials.refresh_token:
        print(
            "Aucun refresh token renvoyé. Révoque l'accès de l'application "
            "sur https://myaccount.google.com/permissions puis relance.",
            file=sys.stderr,
        )
        return 1

    print("\n--- À placer dans ton .env ---\n")
    print("GOOGLE_ADS_USE_PROTO_PLUS=True")
    print(f"GOOGLE_ADS_CLIENT_ID={block['client_id']}")
    print(f"GOOGLE_ADS_CLIENT_SECRET={block['client_secret']}")
    print(f"GOOGLE_ADS_REFRESH_TOKEN={credentials.refresh_token}")
    print("\n(pas de GOOGLE_ADS_DEVELOPER_TOKEN : supprimé le 09/09/2026)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
