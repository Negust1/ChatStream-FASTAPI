import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))


import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.session import Base
from app.config import settings


import app.models  # noqa: F401  
# required for Alembic model discovery


config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)


target_metadata = Base.metadata


# Offline 


def run_migrations_offline():
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()



# Online migrations

def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,

        # Flags 

        compare_type=True,
        compare_server_default=True,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        future=True,
    )

    async with engine.begin() as connection:
        await connection.run_sync(do_run_migrations)

    await engine.dispose()


def run_migrations_online_wrapper():
    asyncio.run(run_migrations_online())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online_wrapper()


