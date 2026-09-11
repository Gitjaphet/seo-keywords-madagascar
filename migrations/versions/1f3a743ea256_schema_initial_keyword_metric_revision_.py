"""schema initial: keyword, metric, revision, user

Revision ID: 1f3a743ea256
Revises: 
Create Date: 2026-09-11 05:44:49.101091

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1f3a743ea256'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Révision de référence.

    Les tables ont été créées par SQLModel.create_all() lors de la
    migration CSV -> base, puis estampillées ici avec `alembic stamp`.
    Volontairement vide : elle sert de point de départ aux révisions
    suivantes, pas à recréer un schéma déjà en place.

    La table keywordrecord_backup_* est délibérément absente des
    modèles ; elle ne doit pas être supprimée par Alembic.
    """


def downgrade() -> None:
    """Pas de retour en arrière depuis la révision de référence."""
    raise NotImplementedError(
        "La révision initiale ne peut pas être annulée : "
        "restaurer data/processed/keywords.db.bak à la place."
    )
