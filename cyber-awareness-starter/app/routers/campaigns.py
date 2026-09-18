import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import (
    AuditEvent,
    Campaign,
    CampaignMessage,
    CampaignStatus,
    PosterVersion,
)
from app.schemas import (
    AuditRead,
    CampaignChatRequest,
    CampaignCreate,
    CampaignMessageRead,
    CampaignRead,
    CampaignRecipientsUpdate,
    CampaignSchedule,
    CampaignStudioRead,
    PosterVersionRead,
)
from app.security import Authenticated
from app.services.ai import (
    campaign_content_from_json,
    campaign_content_to_dict,
    generate_campaign_content,
)
from app.services.graph import send_campaign_email
from app.services.poster import (
    build_poster_png,
    read_poster_image,
    remove_campaign_posters,
    safe_poster_path,
)


router = APIRouter(prefix="/campaigns", tags=["campaigns"])
Db = Annotated[Session, Depends(get_db)]
LOCKED_FOR_EDIT = {CampaignStatus.SENDING, CampaignStatus.SENT}


def serialize(campaign: Campaign) -> CampaignRead:
    recipients = json.loads(campaign.recipient_emails_json)
    return CampaignRead(
        **{
            column.name: getattr(campaign, column.name)
            for column in Campaign.__table__.columns
            if column.name
            not in {"recipient_emails_json", "poster_file_path", "poster_content_json"}
        },
        recipient_emails=recipients,
        recipient_count=len(recipients),
        poster_url=(
            f"/api/campaigns/{campaign.id}/poster"
            if campaign.poster_file_path
            else None
        ),
    )


def find_campaign(db: Session, campaign_id: str) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


def audit(
    db: Session,
    campaign: Campaign,
    action: str,
    actor: str,
    details: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            campaign_id=campaign.id,
            action=action,
            actor=actor,
            details=details,
        )
    )


def require_editable(campaign: Campaign) -> None:
    if campaign.status in LOCKED_FOR_EDIT:
        raise HTTPException(
            status_code=409,
            detail="A sending or sent campaign can no longer be edited",
        )


def version_url(campaign_id: str, version_id: str) -> str:
    return f"/api/campaigns/{campaign_id}/versions/{version_id}/poster"


def serialize_studio(campaign: Campaign) -> CampaignStudioRead:
    versions = [
        PosterVersionRead(
            id=item.id,
            version_number=item.version_number,
            prompt=item.prompt,
            created_by=item.created_by,
            created_at=item.created_at,
            poster_url=version_url(campaign.id, item.id),
            selected_for_sending=campaign.poster_file_path == item.file_path,
        )
        for item in campaign.poster_versions
    ]
    messages = [
        CampaignMessageRead(
            id=item.id,
            role=item.role,
            content=item.content,
            poster_version_id=item.poster_version_id,
            poster_url=(
                version_url(campaign.id, item.poster_version_id)
                if item.poster_version_id
                else None
            ),
            created_by=item.created_by,
            created_at=item.created_at,
        )
        for item in campaign.messages
    ]
    return CampaignStudioRead(
        campaign=serialize(campaign), messages=messages, versions=versions
    )


@router.get("", response_model=list[CampaignRead])
def list_campaigns(_: Authenticated, db: Db) -> list[CampaignRead]:
    campaigns = db.scalars(
        select(Campaign).order_by(Campaign.created_at.desc())
    ).all()
    return [serialize(item) for item in campaigns]


@router.post("", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(
    payload: CampaignCreate, user: Authenticated, db: Db
) -> CampaignRead:
    settings = get_settings()
    if len(payload.recipient_emails) > settings.max_recipients_per_campaign:
        raise HTTPException(
            status_code=400, detail="Recipient count exceeds configured limit"
        )
    campaign = Campaign(
        topic=payload.topic,
        audience_name=payload.audience_name,
        additional_prompt=payload.additional_prompt,
        recipient_emails_json=json.dumps(
            [str(item) for item in payload.recipient_emails]
        ),
        created_by=user.email,
    )
    db.add(campaign)
    db.flush()
    audit(db, campaign, "CREATED", user.email)
    db.commit()
    return serialize(campaign)


@router.get("/{campaign_id}", response_model=CampaignRead)
def get_campaign(campaign_id: str, _: Authenticated, db: Db) -> CampaignRead:
    return serialize(find_campaign(db, campaign_id))


@router.patch("/{campaign_id}/recipients", response_model=CampaignRead)
def update_campaign_recipients(
    campaign_id: str,
    payload: CampaignRecipientsUpdate,
    user: Authenticated,
    db: Db,
) -> CampaignRead:
    campaign = find_campaign(db, campaign_id)
    require_editable(campaign)
    settings = get_settings()
    recipients = [str(item) for item in payload.recipient_emails]
    if len(recipients) > settings.max_recipients_per_campaign:
        raise HTTPException(
            status_code=400, detail="Recipient count exceeds configured limit"
        )

    previous_recipients = json.loads(campaign.recipient_emails_json)
    if recipients == previous_recipients:
        return serialize(campaign)

    campaign.recipient_emails_json = json.dumps(recipients)
    if campaign.status in {CampaignStatus.APPROVED, CampaignStatus.SCHEDULED}:
        campaign.status = (
            CampaignStatus.GENERATED
            if campaign.poster_file_path
            else CampaignStatus.DRAFT
        )
        campaign.approved_by = None
        campaign.scheduled_for = None
    audit(
        db,
        campaign,
        "RECIPIENTS_UPDATED",
        user.email,
        f"Recipient count changed from {len(previous_recipients)} to {len(recipients)}",
    )
    db.commit()
    return serialize(campaign)


@router.get("/{campaign_id}/poster", response_class=FileResponse)
def get_campaign_poster(
    campaign_id: str, _: Authenticated, db: Db
) -> FileResponse:
    campaign = find_campaign(db, campaign_id)
    if not campaign.poster_file_path:
        raise HTTPException(status_code=404, detail="Poster has not been generated")
    return poster_response(campaign.poster_file_path, campaign.id)


@router.get(
    "/{campaign_id}/versions/{version_id}/poster", response_class=FileResponse
)
def get_version_poster(
    campaign_id: str, version_id: str, _: Authenticated, db: Db
) -> FileResponse:
    find_campaign(db, campaign_id)
    version = db.scalar(
        select(PosterVersion).where(
            PosterVersion.id == version_id,
            PosterVersion.campaign_id == campaign_id,
        )
    )
    if not version:
        raise HTTPException(status_code=404, detail="Poster version not found")
    return poster_response(version.file_path, f"{campaign_id}-v{version.version_number}")


@router.post(
    "/{campaign_id}/versions/{version_id}/select", response_model=CampaignRead
)
def select_poster_version(
    campaign_id: str,
    version_id: str,
    user: Authenticated,
    db: Db,
) -> CampaignRead:
    campaign = find_campaign(db, campaign_id)
    require_editable(campaign)
    version = db.scalar(
        select(PosterVersion).where(
            PosterVersion.id == version_id,
            PosterVersion.campaign_id == campaign_id,
        )
    )
    if not version:
        raise HTTPException(status_code=404, detail="Poster version not found")
    try:
        read_poster_image(version.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail="Poster version PNG was not found") from exc

    if campaign.poster_file_path == version.file_path:
        return serialize(campaign)

    campaign.subject = version.subject
    campaign.body_html = version.body_html
    campaign.poster_file_path = version.file_path
    campaign.poster_content_json = version.content_json
    campaign.status = CampaignStatus.GENERATED
    campaign.approved_by = None
    campaign.scheduled_for = None
    campaign.error_message = None
    audit(
        db,
        campaign,
        "VERSION_SELECTED",
        user.email,
        f"Poster version {version.version_number} selected for sending",
    )
    db.commit()
    return serialize(campaign)


def poster_response(stored_path: str, filename: str) -> FileResponse:
    try:
        path = safe_poster_path(stored_path)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Stored poster path is invalid") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Poster PNG was not found")
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="awareness-{filename}.png"'},
    )


@router.get("/{campaign_id}/studio", response_model=CampaignStudioRead)
def get_campaign_studio(
    campaign_id: str, _: Authenticated, db: Db
) -> CampaignStudioRead:
    return serialize_studio(find_campaign(db, campaign_id))


def generate_revision(
    campaign: Campaign,
    prompt: str,
    user: Authenticated,
    db: Session,
) -> CampaignRead:
    require_editable(campaign)
    existing_content = campaign_content_from_json(campaign.poster_content_json)
    source_path = campaign.poster_file_path
    user_message = CampaignMessage(
        campaign_id=campaign.id,
        role="user",
        content=prompt,
        created_by=user.email,
    )
    db.add(user_message)
    # Revisions invalidate approval immediately so a scheduler cannot send the
    # previous version while Azure is still creating the replacement.
    campaign.status = CampaignStatus.DRAFT
    campaign.approved_by = None
    campaign.scheduled_for = None
    campaign.error_message = None
    db.commit()

    version_number = (
        db.scalar(
            select(func.max(PosterVersion.version_number)).where(
                PosterVersion.campaign_id == campaign.id
            )
        )
        or 0
    ) + 1
    try:
        content = generate_campaign_content(
            topic=campaign.topic,
            audience_name=campaign.audience_name,
            additional_prompt=campaign.additional_prompt,
            revision_prompt=prompt,
            existing_content=existing_content,
        )
        poster_path = build_poster_png(
            campaign_id=campaign.id,
            content=content,
            version_number=version_number,
            revision_prompt=prompt,
            source_path=source_path,
        )
    except Exception as exc:
        message = str(exc)[:2000]
        db.add(
            CampaignMessage(
                campaign_id=campaign.id,
                role="assistant",
                content=f"Generation failed: {message}",
            )
        )
        campaign.error_message = message
        campaign.status = (
            CampaignStatus.GENERATED if source_path else CampaignStatus.DRAFT
        )
        audit(db, campaign, "AI_FAILED", user.email, message[:1000])
        db.commit()
        raise HTTPException(
            status_code=502,
            detail=f"Content or poster generation failed: {message}",
        ) from exc

    content_json = json.dumps(campaign_content_to_dict(content))
    body_html = (
        f"<p>{escape(content.short_description)}</p>"
        "<p>The cybersecurity awareness poster is shown below.</p>"
    )
    version = PosterVersion(
        campaign_id=campaign.id,
        version_number=version_number,
        file_path=poster_path,
        prompt=prompt,
        subject=content.subject,
        body_html=body_html,
        content_json=content_json,
        created_by=user.email,
    )
    db.add(version)
    db.flush()
    db.add(
        CampaignMessage(
            campaign_id=campaign.id,
            role="assistant",
            content=f"Created poster version {version_number}.",
            poster_version_id=version.id,
        )
    )
    campaign.subject = content.subject
    campaign.body_html = body_html
    campaign.poster_file_path = poster_path
    campaign.poster_content_json = content_json
    campaign.status = CampaignStatus.GENERATED
    campaign.approved_by = None
    campaign.scheduled_for = None
    campaign.error_message = None
    audit(
        db,
        campaign,
        "GENERATED" if version_number == 1 else "REVISED",
        user.email,
        f"Version {version_number}: {Path(poster_path).name}",
    )
    db.commit()
    return serialize(campaign)


@router.post("/{campaign_id}/generate", response_model=CampaignRead)
def generate_campaign(
    campaign_id: str, user: Authenticated, db: Db
) -> CampaignRead:
    campaign = find_campaign(db, campaign_id)
    prompt = campaign.additional_prompt or "Create the first infographic poster."
    return generate_revision(campaign, prompt, user, db)


@router.post("/{campaign_id}/chat", response_model=CampaignRead)
def chat_campaign(
    campaign_id: str,
    payload: CampaignChatRequest,
    user: Authenticated,
    db: Db,
) -> CampaignRead:
    campaign = find_campaign(db, campaign_id)
    return generate_revision(campaign, payload.prompt, user, db)


@router.post("/{campaign_id}/approve", response_model=CampaignRead)
def approve_campaign(
    campaign_id: str, user: Authenticated, db: Db
) -> CampaignRead:
    campaign = find_campaign(db, campaign_id)
    if campaign.status != CampaignStatus.GENERATED:
        raise HTTPException(status_code=409, detail="Only generated campaigns can be approved")
    if not campaign.poster_file_path:
        raise HTTPException(status_code=409, detail="A poster PNG is required before approval")
    try:
        read_poster_image(campaign.poster_file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail="Poster PNG was not found") from exc
    campaign.status = CampaignStatus.APPROVED
    campaign.approved_by = user.email
    audit(db, campaign, "APPROVED", user.email)
    db.commit()
    return serialize(campaign)


@router.post("/{campaign_id}/unapprove", response_model=CampaignRead)
def unapprove_campaign(
    campaign_id: str, user: Authenticated, db: Db
) -> CampaignRead:
    campaign = find_campaign(db, campaign_id)
    if campaign.status not in {CampaignStatus.APPROVED, CampaignStatus.SCHEDULED}:
        raise HTTPException(status_code=409, detail="Campaign is not approved")
    campaign.status = CampaignStatus.GENERATED
    campaign.approved_by = None
    campaign.scheduled_for = None
    audit(db, campaign, "UNAPPROVED", user.email)
    db.commit()
    return serialize(campaign)


@router.post("/{campaign_id}/schedule", response_model=CampaignRead)
def schedule_campaign(
    campaign_id: str,
    payload: CampaignSchedule,
    user: Authenticated,
    db: Db,
) -> CampaignRead:
    campaign = find_campaign(db, campaign_id)
    if campaign.status != CampaignStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Only approved campaigns can be scheduled")
    scheduled_for = payload.scheduled_for
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
    if scheduled_for <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Schedule must be in the future")
    campaign.scheduled_for = scheduled_for
    campaign.status = CampaignStatus.SCHEDULED
    audit(db, campaign, "SCHEDULED", user.email, scheduled_for.isoformat())
    db.commit()
    return serialize(campaign)


@router.post("/{campaign_id}/send", response_model=CampaignRead)
def send_campaign(campaign_id: str, user: Authenticated, db: Db) -> CampaignRead:
    campaign = find_campaign(db, campaign_id)
    if campaign.status != CampaignStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Only approved campaigns can be sent")
    recipients = json.loads(campaign.recipient_emails_json)
    if not campaign.poster_file_path:
        raise HTTPException(status_code=409, detail="Campaign has no poster PNG")
    try:
        poster_image = read_poster_image(campaign.poster_file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail="Poster PNG was not found") from exc

    campaign.status = CampaignStatus.SENDING
    db.commit()
    try:
        send_campaign_email(
            subject=campaign.subject or "",
            body_html=campaign.body_html or "",
            recipients=recipients,
            poster_image=poster_image,
            poster_filename=Path(campaign.poster_file_path).name,
        )
        campaign.status = CampaignStatus.SENT
        campaign.sent_at = datetime.now(timezone.utc)
        campaign.error_message = None
        audit(db, campaign, "SENT", user.email)
        db.commit()
    except Exception as exc:
        campaign.status = CampaignStatus.FAILED
        campaign.error_message = str(exc)[:1000]
        audit(db, campaign, "SEND_FAILED", user.email, str(exc)[:1000])
        db.commit()
        raise HTTPException(status_code=502, detail=f"Mail send failed: {exc}") from exc
    return serialize(campaign)


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(campaign_id: str, _: Authenticated, db: Db) -> Response:
    campaign = find_campaign(db, campaign_id)
    if campaign.status in {
        CampaignStatus.SCHEDULED,
        CampaignStatus.SENDING,
    }:
        raise HTTPException(
            status_code=409,
            detail="Scheduled or sending campaigns cannot be deleted",
        )
    remove_campaign_posters(campaign.id)
    db.delete(campaign)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{campaign_id}/audit", response_model=list[AuditRead])
def get_audit(campaign_id: str, _: Authenticated, db: Db) -> list[AuditEvent]:
    find_campaign(db, campaign_id)
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.campaign_id == campaign_id)
            .order_by(AuditEvent.occurred_at)
        ).all()
    )
