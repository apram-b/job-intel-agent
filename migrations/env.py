from alembic import context
from sqlalchemy import create_engine
from job_intel.v2.schema import metadata
from job_intel.v2.storage import database_url

config = context.config
connection = config.attributes.get("connection")


def run(conn):
    context.configure(
        connection=conn, target_metadata=metadata, render_as_batch=conn.dialect.name == "sqlite"
    )
    with context.begin_transaction():
        context.run_migrations()


if connection is not None:
    run(connection)
else:
    with create_engine(database_url()).connect() as conn:
        run(conn)
