# seo-keywords-madagascar

Collecte et analyse de mots-clés touristiques pour Madagascar (excursions, circuits,
tours, agences de voyage) avec **analyse de saisonnalité** (haute saison avril-décembre
vs saison cyclonique janvier-mars).

## Approche

Pas de scraping de pages de résultats Google (fragile, contre les CGU). Deux sources
publiques et légales :

1. **Google Autocomplete** — endpoint JSON public utilisé par la barre de recherche
   Google elle-même. Sert à étendre une liste de mots-clés "seed" en dizaines de
   variantes réellement tapées par les internautes.
2. **Google Trends** (via `pytrends`) — volume d'intérêt *relatif* (0-100) dans le
   temps, permettant de dégager le pattern saisonnier par mot-clé et par marché
   (FR, DE, US, IT...).

## Installation

```bash
uv sync
```

## Utilisation

```bash
# 1. Étendre les seeds via Autocomplete et sauvegarder en base (data/processed/keywords.db)
uv run seo-keywords expand --lang fr
uv run seo-keywords expand --lang en
uv run seo-keywords expand --lang de

# 2. Interroger Google Trends pour la saisonnalité (marché mondial par défaut)
uv run seo-keywords seasonality --lang en --top 15 --geo ""

# Comparer un marché spécifique (ex: France)
uv run seo-keywords seasonality --lang fr --top 15 --geo FR

# 3. Exporter les CSV finaux
uv run seo-keywords export --geo ""
```

Les exports finaux atterrissent dans `data/processed/` :
- `seasonality_monthly_<marché>.csv` — score par mois (Jan-Déc)
- `seasonality_summary_<marché>.csv` — moyenne haute saison vs saison cyclonique

## Tests

Tous les appels réseau externes sont mockés dans les tests (`responses` pour les
requêtes HTTP, `unittest.mock` pour `pytrends`) — la suite tourne sans connexion
internet et sans dépendre de la disponibilité de Google.

```bash
uv run pytest
```

## Architecture

```
src/seo_keywords/
├── config.py           # seeds, langues, définition des saisons
├── collectors/
│   ├── base.py          # interface commune (KeywordSuggestion, BaseCollector)
│   ├── autocomplete.py  # Google Suggest
│   └── trends.py        # Google Trends
├── storage/
│   ├── models.py        # modèles SQLModel (KeywordRecord, SeasonalityRecord)
│   └── repository.py    # accès SQLite, dédoublonnage
├── analysis/
│   └── seasonality.py   # agrégation par saison, exports CSV
└── cli.py               # `seo-keywords <commande>`
```

## Limites connues

- Google Trends donne un volume **relatif**, pas absolu. Pour des chiffres de volume
  réel, il faudra l'API Google Ads Keyword Planner (nécessite un compte Ads approuvé).
- Une fois `sakalavatours.com` indexé, connecter **Google Search Console** donnera les
  requêtes exactes des visiteurs réels — la donnée la plus fiable, en complément.
- Respecter un délai entre requêtes (`SEO_REQUEST_DELAY_SECONDS` dans `.env`) pour
  rester correct vis-à-vis des endpoints publics utilisés.

## Roadmap possible

- [ ] Ajout d'un collecteur Bing Suggest (même interface `BaseCollector`)
- [ ] Intégration Google Search Console API une fois le site indexé
- [ ] Dashboard de visualisation (Streamlit ou export vers Grafana)
- [ ] Cron sur l'infra `medevstack` existante (Docker + GitHub Actions)
