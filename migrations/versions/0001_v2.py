"""Add v2 tables without changing legacy data."""

from alembic import op
from migrations.schema_0001 import metadata

revision = "0001_v2"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind())


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore the pre-migration backup instead")
