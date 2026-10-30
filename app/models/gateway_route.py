
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GatewayRoute(Base):
    __tablename__ = "gateway_routes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    gateway_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    cost_per_transaction: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )