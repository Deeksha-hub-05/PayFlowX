"""add gateway transaction cost

Revision ID: 8a2267797e20
Revises: f20933721b2e
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8a2267797e20"
down_revision: Union[str, Sequence[str], None] = "f20933721b2e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "gateway_routes",
        sa.Column(
            "cost_per_transaction",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
    )

    op.alter_column(
        "gateway_routes",
        "cost_per_transaction",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("gateway_routes", "cost_per_transaction")