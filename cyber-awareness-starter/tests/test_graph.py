import base64

from app.services.graph import POSTER_CONTENT_ID, build_email_payload


def test_email_payload_embeds_png_inline_and_keeps_recipients_in_bcc() -> None:
    poster = b"\x89PNG\r\n\x1a\nposter-data"

    payload = build_email_payload(
        subject="Security reminder",
        body_html="<p>Short description.</p>",
        recipients=["one@example.com", "two@example.com"],
        poster_image=poster,
        poster_filename="campaign.png",
        sender_mailbox="security@example.com",
    )

    message = payload["message"]
    assert f"cid:{POSTER_CONTENT_ID}" in message["body"]["content"]
    assert message["toRecipients"] == [
        {"emailAddress": {"address": "security@example.com"}}
    ]
    assert message["bccRecipients"] == [
        {"emailAddress": {"address": "one@example.com"}},
        {"emailAddress": {"address": "two@example.com"}},
    ]

    attachment = message["attachments"][0]
    assert attachment["contentType"] == "image/png"
    assert attachment["contentId"] == POSTER_CONTENT_ID
    assert attachment["isInline"] is True
    assert base64.b64decode(attachment["contentBytes"]) == poster
