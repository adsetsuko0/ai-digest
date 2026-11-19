"""add article embedding

Revision ID: 5b8e7c1d2a90
Revises: 206906016b42
Create Date: 2026-11-19 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.core.config import settings

# revision identifiers, used by Alembic.
revision: str = "5b8e7c1d2a90"
down_revision: Union[str, Sequence[str], None] = "206906016b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # The dimension comes from EMBEDDING_DIM at the moment the migration runs;
    # changing it later needs a new migration (and re-embedding the articles).
    op.add_column(
        "articles",
        sa.Column("embedding", Vector(settings.EMBEDDING_DIM), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("articles", "embedding")
    # the extension stays installed on purpose