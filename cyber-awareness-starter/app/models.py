import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CampaignStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    topic: Mapped[str] = mapped_column(String(200))
    audience_name: Mapped[str] = mapped_column(String(200))
    additional_prompt: Mapped[str] = mapped_column(
        Text,
        default="",
        server_default=text("''"),
    )
    recipient_emails_json: Mapped[str] = mapped_column(Text, default="[]")
    subject: Mapped[str | None] = mapped_column(String(250), nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    poster_content_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CampaignStatus] = mapped_column(Enum(CampaignStatus), default=CampaignStatus.DRAFT)
    created_by: Mapped[str] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    poster_versions: Mapped[list["PosterVersion"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="PosterVersion.version_number",
    )
    messages: Mapped[list["CampaignMessage"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="CampaignMessage.created_at",
    )


class PosterVersion(Base):
    __tablename__ = "poster_versions"
    __table_args__ = (
        UniqueConstraint("campaign_id", "version_number", name="uq_poster_version"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.id"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(500))
    prompt: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(String(250))
    body_html: Mapped[str] = mapped_column(Text)
    content_json: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    campaign: Mapped[Campaign] = relationship(back_populates="poster_versions")
    messages: Mapped[list["CampaignMessage"]] = relationship(
        back_populates="poster_version"
    )


class CampaignMessage(Base):
    __tablename__ = "campaign_messages"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    poster_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("poster_versions.id"), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    campaign: Mapped[Campaign] = relationship(back_populates="messages")
    poster_version: Mapped[PosterVersion | None] = relationship(
        back_populates="messages"
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    action: Mapped[str] = mapped_column(String(80))
    actor: Mapped[str] = mapped_column(String(255))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    campaign: Mapped[Campaign] = relationship(back_populates="audit_events")
