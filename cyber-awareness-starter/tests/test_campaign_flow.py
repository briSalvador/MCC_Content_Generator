import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Campaign
from app.security import CurrentUser, get_current_user
from app.services.scheduler import process_due_campaigns


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_campaign_requires_generation_and_approval_before_send() -> None:
    with TestClient(app) as client:
        signed_in = client.get("/api/auth/me")
        assert signed_in.status_code == 200
        assert signed_in.json()["development_bypass"] is True

        created = client.post(
            "/api/campaigns",
            json={
                "topic": "MFA fatigue",
                "audience_name": "Pilot group",
                "additional_prompt": "Use construction-themed safety visuals.",
                "recipient_emails": ["pilot@example.com"],
            },
        )
        assert created.status_code == 201
        campaign = created.json()
        assert campaign["status"] == "DRAFT"
        assert campaign["created_by"] == "developer@example.com"
        assert campaign["additional_prompt"] == "Use construction-themed safety visuals."

        blocked = client.post(f"/api/campaigns/{campaign['id']}/send")
        assert blocked.status_code == 409

        generated = client.post(f"/api/campaigns/{campaign['id']}/generate")
        assert generated.status_code == 200
        assert generated.json()["status"] == "GENERATED"
        assert generated.json()["poster_url"] == f"/api/campaigns/{campaign['id']}/poster"

        poster = client.get(generated.json()["poster_url"])
        assert poster.status_code == 200
        assert poster.headers["content-type"] == "image/png"
        assert poster.content.startswith(b"\x89PNG")

        revised = client.post(
            f"/api/campaigns/{campaign['id']}/chat",
            json={"prompt": "Use a shorter subtitle and four centered cards."},
        )
        assert revised.status_code == 200
        studio = client.get(f"/api/campaigns/{campaign['id']}/studio").json()
        assert len(studio["versions"]) == 2
        assert [message["role"] for message in studio["messages"]] == [
            "user", "assistant", "user", "assistant"
        ]
        first_version = client.get(studio["versions"][0]["poster_url"])
        assert first_version.status_code == 200

        selected = client.post(
            f"/api/campaigns/{campaign['id']}/versions/"
            f"{studio['versions'][0]['id']}/select"
        )
        assert selected.status_code == 200
        assert selected.json()["status"] == "GENERATED"
        selected_studio = client.get(
            f"/api/campaigns/{campaign['id']}/studio"
        ).json()
        assert selected_studio["versions"][0]["selected_for_sending"] is True
        assert selected_studio["versions"][1]["selected_for_sending"] is False
        assert client.get(selected.json()["poster_url"]).content == first_version.content

        recipients = client.patch(
            f"/api/campaigns/{campaign['id']}/recipients",
            json={
                "recipient_emails": [
                    "new.one@example.com",
                    "new.two@example.com",
                ]
            },
        )
        assert recipients.status_code == 200
        assert recipients.json()["recipient_emails"] == [
            "new.one@example.com",
            "new.two@example.com",
        ]
        assert recipients.json()["recipient_count"] == 2

        approved = client.post(f"/api/campaigns/{campaign['id']}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "APPROVED"

        unapproved = client.post(f"/api/campaigns/{campaign['id']}/unapprove")
        assert unapproved.status_code == 200
        assert unapproved.json()["status"] == "GENERATED"
        assert unapproved.json()["approved_by"] is None

        reapproved = client.post(f"/api/campaigns/{campaign['id']}/approve")
        assert reapproved.status_code == 200

        sent = client.post(f"/api/campaigns/{campaign['id']}/send")
        assert sent.status_code == 200
        assert sent.json()["status"] == "SENT"

        blocked_edit = client.patch(
            f"/api/campaigns/{campaign['id']}",
            json={"topic": "Changed after send"},
        )
        assert blocked_edit.status_code == 405

        blocked_revision = client.post(
            f"/api/campaigns/{campaign['id']}/chat",
            json={"prompt": "Change the color"},
        )
        assert blocked_revision.status_code == 409

        blocked_recipients = client.patch(
            f"/api/campaigns/{campaign['id']}/recipients",
            json={"recipient_emails": ["after-send@example.com"]},
        )
        assert blocked_recipients.status_code == 409

        deleted = client.delete(f"/api/campaigns/{campaign['id']}")
        assert deleted.status_code == 204
        assert client.get(f"/api/campaigns/{campaign['id']}").status_code == 404


def test_draft_campaign_can_be_deleted() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/campaigns",
            json={
                "topic": "Suspicious QR codes",
                "audience_name": "Pilot group",
                "recipient_emails": ["pilot@example.com"],
            },
        ).json()

        deleted = client.delete(f"/api/campaigns/{created['id']}")
        assert deleted.status_code == 204
        assert client.get(f"/api/campaigns/{created['id']}").status_code == 404


def test_created_by_comes_from_authenticated_user() -> None:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        subject="megawide-user-object-id",
        email="user@megawide.com.ph",
        name="Megawide User",
    )
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/campaigns",
                json={
                    "topic": "Phishing awareness",
                    "audience_name": "Pilot group",
                    "recipient_emails": ["pilot@example.com"],
                },
            )
        assert created.status_code == 201
        assert created.json()["created_by"] == "user@megawide.com.ph"
    finally:
        app.dependency_overrides.clear()


def test_deleting_generated_campaign_removes_poster() -> None:
    with TestClient(app) as client:
        campaign = client.post(
            "/api/campaigns",
            json={
                "topic": "Password safety",
                "audience_name": "Pilot group",
                "recipient_emails": ["pilot@example.com"],
            },
        ).json()
        generated = client.post(f"/api/campaigns/{campaign['id']}/generate")
        assert generated.status_code == 200

        poster_path = (
            Path(os.environ["POSTER_STORAGE_PATH"])
            / f"{campaign['id']}-v0001.png"
        )
        assert poster_path.is_file()

        deleted = client.delete(f"/api/campaigns/{campaign['id']}")
        assert deleted.status_code == 204
        assert not poster_path.exists()


def test_campaign_details_cannot_be_edited_after_creation() -> None:
    with TestClient(app) as client:
        campaign = client.post(
            "/api/campaigns",
            json={
                "topic": "Password safety",
                "audience_name": "Pilot group",
                "recipient_emails": ["pilot@example.com"],
            },
        ).json()
        client.post(f"/api/campaigns/{campaign['id']}/generate")
        recipient_edit = client.patch(
            f"/api/campaigns/{campaign['id']}",
            json={"recipient_emails": ["new@example.com"]},
        )
        assert recipient_edit.status_code == 405

        content_edit = client.patch(
            f"/api/campaigns/{campaign['id']}",
            json={"topic": "Password manager safety"},
        )
        assert content_edit.status_code == 405

        approved = client.post(f"/api/campaigns/{campaign['id']}/approve")
        assert approved.status_code == 200

        revision = client.post(
            f"/api/campaigns/{campaign['id']}/chat",
            json={"prompt": "Make the poster use more red."},
        )
        assert revision.status_code == 200
        assert revision.json()["status"] == "GENERATED"
        assert revision.json()["approved_by"] is None


def test_recipient_or_version_change_clears_approval_and_schedule() -> None:
    with TestClient(app) as client:
        campaign = client.post(
            "/api/campaigns",
            json={
                "topic": "Business email compromise",
                "audience_name": "Finance pilot",
                "recipient_emails": ["finance@example.com"],
            },
        ).json()
        client.post(f"/api/campaigns/{campaign['id']}/generate")
        client.post(
            f"/api/campaigns/{campaign['id']}/chat",
            json={"prompt": "Create a second visual version."},
        )
        studio = client.get(f"/api/campaigns/{campaign['id']}/studio").json()
        assert studio["versions"][1]["selected_for_sending"] is True

        approved = client.post(f"/api/campaigns/{campaign['id']}/approve")
        assert approved.status_code == 200
        changed_recipients = client.patch(
            f"/api/campaigns/{campaign['id']}/recipients",
            json={"recipient_emails": ["finance2@example.com"]},
        )
        assert changed_recipients.status_code == 200
        assert changed_recipients.json()["status"] == "GENERATED"
        assert changed_recipients.json()["approved_by"] is None

        client.post(f"/api/campaigns/{campaign['id']}/approve")
        selected = client.post(
            f"/api/campaigns/{campaign['id']}/versions/"
            f"{studio['versions'][0]['id']}/select"
        )
        assert selected.status_code == 200
        assert selected.json()["status"] == "GENERATED"
        assert selected.json()["approved_by"] is None


def test_approved_campaign_can_be_scheduled_and_sent_by_worker() -> None:
    with TestClient(app) as client:
        campaign = client.post(
            "/api/campaigns",
            json={
                "topic": "Secure file sharing",
                "audience_name": "All employees",
                "recipient_emails": ["employee@example.com"],
            },
        ).json()
        client.post(f"/api/campaigns/{campaign['id']}/generate")
        client.post(f"/api/campaigns/{campaign['id']}/approve")

        future = datetime.now(timezone.utc) + timedelta(hours=1)
        scheduled = client.post(
            f"/api/campaigns/{campaign['id']}/schedule",
            json={"scheduled_for": future.isoformat()},
        )
        assert scheduled.status_code == 200
        assert scheduled.json()["status"] == "SCHEDULED"
        assert scheduled.json()["scheduled_for"] is not None

        protected_delete = client.delete(f"/api/campaigns/{campaign['id']}")
        assert protected_delete.status_code == 409

        with SessionLocal() as db:
            stored = db.get(Campaign, campaign["id"])
            assert stored is not None
            stored.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)
            db.commit()

        process_due_campaigns()

        sent = client.get(f"/api/campaigns/{campaign['id']}")
        assert sent.status_code == 200
        assert sent.json()["status"] == "SENT"
        assert sent.json()["sent_at"] is not None

        deleted = client.delete(f"/api/campaigns/{campaign['id']}")
        assert deleted.status_code == 204
