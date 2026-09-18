from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import CampaignStatus


class CampaignCreate(BaseModel):
    topic: str = Field(min_length=3, max_length=200)
    audience_name: str = Field(min_length=2, max_length=200)
    additional_prompt: str = Field(default="", max_length=2000)
    recipient_emails: list[EmailStr] = Field(min_length=1)

    @field_validator("additional_prompt")
    @classmethod
    def normalize_additional_prompt(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("recipient_emails")
    @classmethod
    def unique_recipients(cls, value: list[EmailStr]) -> list[EmailStr]:
        return list(dict.fromkeys(value))


class CampaignSchedule(BaseModel):
    scheduled_for: datetime


class CampaignRecipientsUpdate(BaseModel):
    recipient_emails: list[EmailStr] = Field(min_length=1)

    @field_validator("recipient_emails")
    @classmethod
    def unique_recipients(cls, value: list[EmailStr]) -> list[EmailStr]:
        return list(dict.fromkeys(value))


class CampaignChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)

    @field_validator("prompt")
    @classmethod
    def normalize_chat_prompt(cls, value: str) -> str:
        return " ".join(value.split())


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    topic: str
    audience_name: str
    additional_prompt: str
    recipient_emails: list[str]
    recipient_count: int
    subject: str | None
    body_html: str | None
    poster_url: str | None
    status: CampaignStatus
    created_by: str
    approved_by: str | None
    scheduled_for: datetime | None
    sent_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action: str
    actor: str
    details: str | None
    occurred_at: datetime


class CampaignMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    poster_version_id: str | None
    poster_url: str | None
    created_by: str | None
    created_at: datetime


class PosterVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version_number: int
    prompt: str
    created_by: str
    created_at: datetime
    poster_url: str
    selected_for_sending: bool


class CampaignStudioRead(BaseModel):
    campaign: CampaignRead
    messages: list[CampaignMessageRead]
    versions: list[PosterVersionRead]
