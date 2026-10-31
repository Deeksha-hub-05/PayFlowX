from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
)

from app.models.base import Base


class GatewayConfig(Base):
    __tablename__ = "gateway_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    gateway_name = Column(String(50), nullable=False, unique=True)

    is_enabled = Column(Boolean, nullable=False, default=True)

    timeout_ms = Column(Integer, nullable=False, default=2000)

    max_retries = Column(Integer, nullable=False, default=2)

    cost_per_transaction = Column(Float, nullable=False, default=0.0)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )