
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GatewayCircuitBreaker(Base):
    __tablename__ = "gateway_circuit_breakers"

    __table_args__ = (
        UniqueConstraint(
            "gateway_name",
            "payment_method",
            name="uq_gateway_circuit_breaker",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    gateway_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    payment_method: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )

    state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="CLOSED",
    )

    failure_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    failure_threshold: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
    )

    recovery_timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
    )

    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
