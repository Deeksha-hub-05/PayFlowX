
"""create transactions table

Revision ID: 7f3ecb9a93b0
Revises:
Create Date: 2026-10-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# Revision identifiers used by Alembic.
revision: str = "7f3ecb9a93b0"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", sa.String(length=100), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_transactions_merchant_id"),
        "transactions",
        ["merchant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transactions_status"),
        "transactions",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_transactions_status"),
        table_name="transactions",
    )
    op.drop_index(
        op.f("ix_transactions_merchant_id"),
        table_name="transactions",
    )
    op.drop_table("transactions")
