from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from sqlmodel import SQLModel

from alembic import context

# L'import est requis pour que SQLModel.metadata connaisse les tables.
from seo_keywords.config import settings
from seo_keywords.storage import models  # noqa: F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = SQLModel.metadata

# URL lue depuis la configuration plutôt qu'écrite en dur dans
# alembic.ini : le chemin diffère entre poste local et VPS.
config.set_main_option(
    "sqlalchemy.url", f"sqlite:///{settings.processed_output_dir}/keywords.db"
)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def include_object(obj, name, type_, reflected, compare_to):
    """Exclut les tables de sauvegarde de l'autogénération.

    keywordrecord_backup_* est conservée volontairement hors des modèles
    (trace de la migration CSV -> base). Sans ce filtre, Alembic
    proposerait de la supprimer à chaque révision et `alembic check`
    échouerait en permanence — un contrôle qui échoue toujours est un
    contrôle qu'on cesse de lire.
    """
    target = name or getattr(getattr(obj, "table", None), "name", "")
    return not str(target).startswith("keywordrecord_backup_")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
