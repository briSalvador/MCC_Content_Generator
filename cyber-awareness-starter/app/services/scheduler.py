import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import AuditEvent, Campaign, CampaignStatus
from app.services.graph import send_campaign_email
from app.services.poster import read_poster_image


logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="UTC")


def process_due_campaigns() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        due = db.scalars(
            select(Campaign).where(
                Campaign.status == CampaignStatus.SCHEDULED,
                Campaign.scheduled_for <= now,
            )
        ).all()
        for campaign in due:
            try:
                campaign.status = CampaignStatus.SENDING
                db.commit()
                recipients = json.loads(campaign.recipient_emails_json)
                if not campaign.poster_file_path:
                    raise RuntimeError("Scheduled campaign has no poster PNG")
                poster_image = read_poster_image(campaign.poster_file_path)
                send_campaign_email(
                    subject=campaign.subject or "",
                    body_html=campaign.body_html or "",
                    recipients=recipients,
                    poster_image=poster_image,
                    poster_filename=Path(campaign.poster_file_path).name,
                )
                campaign.status = CampaignStatus.SENT
                campaign.sent_at = now
                campaign.error_message = None
                db.add(AuditEvent(campaign_id=campaign.id, action="SENT", actor="scheduler"))
                db.commit()
            except Exception as exc:  # keep the worker alive; details are recorded for operators
                logger.exception("Scheduled campaign %s failed", campaign.id)
                campaign.status = CampaignStatus.FAILED
                campaign.error_message = str(exc)[:1000]
                db.add(
                    AuditEvent(
                        campaign_id=campaign.id,
                        action="SEND_FAILED",
                        actor="scheduler",
                        details=str(exc)[:1000],
                    )
                )
                db.commit()


def start_scheduler() -> None:
    settings = get_settings()
    if settings.scheduler_enabled and not scheduler.running:
        scheduler.add_job(
            process_due_campaigns,
            "interval",
            seconds=settings.scheduler_interval_seconds,
            id="campaign-dispatch",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
