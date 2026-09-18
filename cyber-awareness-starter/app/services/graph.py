import base64
from pathlib import Path
from urllib.parse import quote

import httpx
from azure.identity import DefaultAzureCredential

from app.config import get_settings


GRAPH_SCOPE = "https://graph.microsoft.com/.default"
GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
POSTER_CONTENT_ID = "cyber-awareness-poster"


def build_email_payload(
    subject: str,
    body_html: str,
    recipients: list[str],
    poster_image: bytes,
    poster_filename: str,
    sender_mailbox: str,
) -> dict[str, object]:
    inline_poster = (
        '<div style="margin:24px 0;text-align:center">'
        f'<img src="cid:{POSTER_CONTENT_ID}" alt="Cybersecurity awareness poster" '
        'width="794" style="display:block;width:100%;max-width:794px;'
        'height:auto;margin:0 auto;border:0">'
        "</div>"
    )
    return {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": f"{body_html}{inline_poster}",
            },
            "toRecipients": [
                {"emailAddress": {"address": sender_mailbox}}
            ],
            "bccRecipients": [
                {"emailAddress": {"address": recipient}} for recipient in recipients
            ],
            "attachments": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": Path(poster_filename).name,
                    "contentType": "image/png",
                    "contentBytes": base64.b64encode(poster_image).decode("ascii"),
                    "contentId": POSTER_CONTENT_ID,
                    "isInline": True,
                }
            ],
        },
        "saveToSentItems": True,
    }


def send_campaign_email(
    subject: str,
    body_html: str,
    recipients: list[str],
    poster_image: bytes,
    poster_filename: str,
) -> str:
    settings = get_settings()
    if not recipients:
        raise ValueError("At least one recipient is required")
    if len(recipients) > settings.max_recipients_per_campaign:
        raise ValueError("Recipient count exceeds configured campaign limit")
    if not poster_image:
        raise ValueError("Poster PNG is required")
    if len(poster_image) > settings.max_poster_image_bytes:
        raise ValueError("Poster PNG exceeds the configured attachment limit")
    if settings.mock_email_service:
        return "mock-accepted"
    if not settings.graph_sender_mailbox:
        raise RuntimeError("GRAPH_SENDER_MAILBOX is required")

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    token = credential.get_token(GRAPH_SCOPE).token
    sender = quote(settings.graph_sender_mailbox, safe="")

    payload = build_email_payload(
        subject=subject,
        body_html=body_html,
        recipients=recipients,
        poster_image=poster_image,
        poster_filename=poster_filename,
        sender_mailbox=settings.graph_sender_mailbox,
    )
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{GRAPH_ROOT}/users/{sender}/sendMail",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
    if response.status_code != 202:
        raise RuntimeError(
            f"Graph sendMail failed ({response.status_code}): {response.text[:500]}"
        )
    return "graph-accepted"
