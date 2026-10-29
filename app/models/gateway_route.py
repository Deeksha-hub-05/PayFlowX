
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

from datetime import datetime, timezone


class GatewayRoute(Base):
    __tablename__ = "gateway_routes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    gateway_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
