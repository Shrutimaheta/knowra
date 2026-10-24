from alembic import context
from app.store import engine


def run(connection):
    context.configure(connection=connection, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    with engine().connect() as connection:
        run(connection)
