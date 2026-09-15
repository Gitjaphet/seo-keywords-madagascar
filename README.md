## Modèle de données

Le schéma a évolué en 4 migrations Alembic successives : schéma initial
(`Keyword` / `SeasonalityRecord`), ajout du clustering sémantique
(`Cluster`, `ClusteringRun`), séparation cluster/page par langue
(`ClusterPage`), puis ajout du suivi de validation humaine
(`reviewed_at`, `reviewed_by_id`, `KeywordRevision`).

Principe central : **une décision humaine n'est jamais écrasée par le
pipeline automatique**. Chaque champ sujet à un recalcul (`intent`,
`cluster`) a un `*_source` (`unset` / `auto` / `manual`) — les
traitements par lot filtrent sur `auto` et laissent `manual` intact.
Chaque modification est tracée dans `KeywordRevision`, avec l'ancienne
et la nouvelle valeur.

```mermaid
erDiagram
    USER ||--o{ KEYWORD_REVISION : "auteur de"
    USER ||--o{ CLUSTER : "valide"
    USER ||--o{ KEYWORD : "valide"

    CLUSTERING_RUN ||--o{ CLUSTER : "produit"

    CLUSTER ||--o{ CLUSTER_PAGE : "décliné en pages"
    CLUSTER ||--o{ KEYWORD : "regroupe"
    CLUSTER }o--|| KEYWORD : "tête (head_keyword)"
    CLUSTER_PAGE }o--|| KEYWORD : "tête (head_keyword)"

    KEYWORD ||--o{ KEYWORD_METRIC : "mesuré par"
    KEYWORD ||--o{ KEYWORD_REVISION : "historique"

    USER {
        int id PK
        string email
        string display_name
        bool is_active
    }

    CLUSTERING_RUN {
        int id PK
        string model_name
        float distance_threshold
        string linkage
        int keyword_count
        int cluster_count
        datetime created_at
    }

    CLUSTER {
        int id PK
        int run_id FK
        int head_keyword_id FK
        string target_url
        enum status "to_create/published/to_merge/discarded"
        int total_volume
        datetime reviewed_at
        int reviewed_by_id FK
    }

    CLUSTER_PAGE {
        int id PK
        int cluster_id FK
        string lang
        int head_keyword_id FK
        string target_url
        string proposed_title
        enum status
    }

    KEYWORD {
        int id PK
        string keyword
        string lang
        string source
        enum intent "navigationnel/transactionnel/commercial/informationnel"
        enum intent_source "unset/auto/manual"
        int cluster_id FK
        enum cluster_source "unset/auto/manual"
        enum status "active/excluded/competitor/archived"
        int autocomplete_depth
        int reviewed_by_id FK
    }

    KEYWORD_METRIC {
        int id PK
        int keyword_id FK
        string market "ISO-2, vide = mondial"
        int search_volume
        bool volume_is_bucketed
        int ads_competition_index
        decimal cpc_low
        decimal cpc_high
        enum source "google_ads/google_trends/search_console"
        datetime fetched_at
    }

    KEYWORD_REVISION {
        int id PK
        int keyword_id FK
        string field_name
        string old_value
        string new_value
        int changed_by_id FK
        datetime changed_at
    }
```

`SeasonalityRecord` (saisonnalité Google Trends) reste volontairement en
dehors de ce schéma relationnel : données re-téléchargeables à tout
moment, sans décision humaine à protéger.

## Migrations

Le schéma est versionné avec **Alembic** :

```bash
# Appliquer toutes les migrations
uv run alembic upgrade head

# Générer une nouvelle migration après modification de models.py
uv run alembic revision --autogenerate -m "description du changement"

# Revenir en arrière d'une révision
uv run alembic downgrade -1
```
