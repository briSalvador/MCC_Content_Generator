import json
from dataclasses import asdict, dataclass
from functools import lru_cache

import bleach
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import OpenAI

from app.config import get_settings


CONTENT_RULES = """
Create content for a one-page cybersecurity infographic poster.

Return one JSON object containing:
- subject: concise email subject, maximum 100 characters
- short_description: plain-text email introduction, maximum 50 words
- poster_title: maximum 8 words
- poster_subtitle: maximum 20 words
- background_prompt: visual direction for a subtle full-page portrait background
- layout_accent: one of red, teal, blue, orange, or purple
- key_points: four to eight concise infographic sections; use as many as necessary
  to retain important information without repetition
  - heading: a short section heading, maximum 5 words
  - caption: one clear supporting explanation or action, maximum 20 words
  - illustration_prompt: one simple visual concept representing only this action
- call_to_action: one short final instruction

Rules:
- Write for non-technical company employees in a calm, practical tone.
- Follow useful creative direction while preserving accuracy, safety, and privacy.
- Never request passwords, OTP codes, personal information, or credentials.
- Do not invent company policy, statistics, incidents, contacts, or URLs.
- Never include employee names or recipient addresses.
- Prefer several short heading-and-caption sections over a few long paragraphs.
- Make the background subtle, low contrast, and clear behind all text.
- The background prompt must not request written text or logos.
- Each key point needs a distinct, icon-like illustration concept.
- Illustration concepts must exclude words, letters, numbers, logos, and watermarks.
- Return valid JSON only.
""".strip()

CAMPAIGN_CONTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "short_description": {"type": "string"},
        "poster_title": {"type": "string"},
        "poster_subtitle": {"type": "string"},
        "background_prompt": {"type": "string"},
        "layout_accent": {
            "type": "string",
            "enum": ["red", "teal", "blue", "orange", "purple"],
        },
        "key_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "caption": {"type": "string"},
                    "illustration_prompt": {"type": "string"},
                },
                "required": ["heading", "caption", "illustration_prompt"],
                "additionalProperties": False,
            },
            "minItems": 4,
            "maxItems": 8,
        },
        "call_to_action": {"type": "string"},
    },
    "required": [
        "subject",
        "short_description",
        "poster_title",
        "poster_subtitle",
        "background_prompt",
        "layout_accent",
        "key_points",
        "call_to_action",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class CampaignKeyPoint:
    heading: str
    caption: str
    illustration_prompt: str


@dataclass(frozen=True)
class CampaignContent:
    subject: str
    short_description: str
    poster_title: str
    poster_subtitle: str
    background_prompt: str
    layout_accent: str
    key_points: list[CampaignKeyPoint]
    call_to_action: str


def clean_text(value: object, maximum_length: int) -> str:
    cleaned = bleach.clean(str(value or ""), tags=set(), strip=True)
    return " ".join(cleaned.split())[:maximum_length].strip()


def parse_campaign_content(payload: dict[str, object]) -> CampaignContent:
    raw_points = payload.get("key_points")
    if not isinstance(raw_points, list) or not 4 <= len(raw_points) <= 8:
        raise RuntimeError("Azure OpenAI must return four to eight key points")

    points: list[CampaignKeyPoint] = []
    for raw_point in raw_points:
        if not isinstance(raw_point, dict):
            raise RuntimeError("Every key point must contain a heading and caption")
        points.append(
            CampaignKeyPoint(
                heading=clean_text(raw_point.get("heading"), 80),
                caption=clean_text(raw_point.get("caption"), 180),
                illustration_prompt=clean_text(raw_point.get("illustration_prompt"), 500),
            )
        )

    accent = clean_text(payload.get("layout_accent"), 20).lower()
    if accent not in {"red", "teal", "blue", "orange", "purple"}:
        raise RuntimeError("Azure OpenAI returned an unsupported layout accent")
    content = CampaignContent(
        subject=clean_text(payload.get("subject"), 100),
        short_description=clean_text(payload.get("short_description"), 500),
        poster_title=clean_text(payload.get("poster_title"), 100),
        poster_subtitle=clean_text(payload.get("poster_subtitle"), 200),
        background_prompt=clean_text(payload.get("background_prompt"), 800),
        layout_accent=accent,
        key_points=points,
        call_to_action=clean_text(payload.get("call_to_action"), 180),
    )
    required = [
        content.subject,
        content.short_description,
        content.poster_title,
        content.poster_subtitle,
        content.background_prompt,
        content.call_to_action,
        *(p.heading for p in points),
        *(p.caption for p in points),
        *(p.illustration_prompt for p in points),
    ]
    if not all(required):
        raise RuntimeError("Azure OpenAI response is missing required poster content")
    return content


def campaign_content_to_dict(content: CampaignContent) -> dict[str, object]:
    return asdict(content)


def campaign_content_from_json(value: str | None) -> CampaignContent | None:
    if not value:
        return None
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Stored poster content is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Stored poster content is invalid")
    return parse_campaign_content(payload)


def mock_campaign_content(topic: str) -> CampaignContent:
    return CampaignContent(
        subject=f"Security reminder: {topic}"[:100],
        short_description=f"Review this practical awareness poster about {topic}.",
        poster_title=topic.title()[:100],
        poster_subtitle="Pause, verify, and report suspicious activity",
        background_prompt="Subtle cybersecurity network paths and shield patterns",
        layout_accent="red",
        key_points=[
            CampaignKeyPoint("Pause First", "Stop before acting on urgent requests.", "A raised hand and alert"),
            CampaignKeyPoint("Verify the Sender", "Confirm requests through an official channel.", "A verified contact and message"),
            CampaignKeyPoint("Inspect Carefully", "Check links and attachments before opening.", "A magnifier inspecting a link"),
            CampaignKeyPoint("Protect Credentials", "Never share passwords or verification codes.", "A shield protecting a password"),
        ],
        call_to_action="Stop. Verify. Report.",
    )


@lru_cache
def azure_openai_client() -> OpenAI:
    settings = get_settings()
    endpoint = settings.azure_openai_endpoint.strip().rstrip("/")
    if not endpoint:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT is required")
    if settings.azure_openai_api_key:
        api_key = settings.azure_openai_api_key
    else:
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        api_key = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
    return OpenAI(
        base_url=f"{endpoint}/openai/v1/",
        api_key=api_key,
        timeout=settings.azure_openai_timeout_seconds,
        max_retries=2,
    )


def generate_campaign_content(
    topic: str,
    audience_name: str,
    additional_prompt: str = "",
    revision_prompt: str = "",
    existing_content: CampaignContent | None = None,
) -> CampaignContent:
    settings = get_settings()
    if settings.mock_ai_services:
        content = mock_campaign_content(topic)
        if revision_prompt:
            return CampaignContent(
                subject=content.subject,
                short_description=content.short_description,
                poster_title=content.poster_title,
                poster_subtitle=clean_text(revision_prompt, 200),
                background_prompt=content.background_prompt,
                layout_accent=content.layout_accent,
                key_points=content.key_points,
                call_to_action=content.call_to_action,
            )
        return content
    if not settings.azure_openai_text_deployment:
        raise RuntimeError("AZURE_OPENAI_TEXT_DEPLOYMENT is required")

    request = {
        "topic": clean_text(topic, 200),
        "audience_label": clean_text(audience_name, 200),
        "initial_creative_direction": clean_text(additional_prompt, 2000),
        "latest_revision_instruction": clean_text(revision_prompt, 4000),
        "current_poster_specification": (
            campaign_content_to_dict(existing_content) if existing_content else None
        ),
    }
    mode = (
        "Revise the current specification using the latest instruction. Return the "
        "complete specification, including unchanged fields."
        if existing_content
        else "Create the first complete poster specification."
    )
    try:
        response = azure_openai_client().chat.completions.create(
            model=settings.azure_openai_text_deployment,
            messages=[
                {"role": "system", "content": f"{CONTENT_RULES}\n{mode}"},
                {"role": "user", "content": json.dumps(request)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "campaign_content",
                    "strict": True,
                    "schema": CAMPAIGN_CONTENT_SCHEMA,
                },
            },
        )
        raw = response.choices[0].message.content
        if not raw:
            raise RuntimeError("Azure OpenAI returned an empty content response")
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Azure OpenAI returned invalid JSON") from exc
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"Azure OpenAI text generation failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Azure OpenAI returned an invalid content object")
    return parse_campaign_content(payload)
