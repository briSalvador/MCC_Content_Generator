import base64
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.services import ai, poster


def generated_payload() -> dict[str, object]:
    return {
        "subject": "Security reminder: QR phishing",
        "short_description": "Review the poster before scanning QR codes.",
        "poster_title": "Check Before You Scan",
        "poster_subtitle": "Treat unexpected QR codes like suspicious links",
        "background_prompt": "Subtle QR security network with shield motifs",
        "layout_accent": "teal",
        "key_points": [
            {"heading": "Verify Source", "caption": "Check where the code came from.", "illustration_prompt": "A shield checking a QR tile"},
            {"heading": "Preview Destination", "caption": "Inspect the destination before opening.", "illustration_prompt": "A magnifier over a safe link"},
            {"heading": "Protect Credentials", "caption": "Never enter credentials on unexpected pages.", "illustration_prompt": "A shield guarding a login form"},
            {"heading": "Report It", "caption": "Report suspicious codes to security.", "illustration_prompt": "A warning sent to a shield"},
        ],
        "call_to_action": "Pause. Check. Report.",
    }


def test_azure_text_generation_uses_deployment_and_current_spec(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(generated_payload())))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(ai, "azure_openai_client", lambda: client)
    monkeypatch.setattr(
        ai,
        "get_settings",
        lambda: SimpleNamespace(mock_ai_services=False, azure_openai_text_deployment="gpt-4.1"),
    )

    existing = ai.parse_campaign_content(generated_payload())
    content = ai.generate_campaign_content(
        "QR phishing", "All employees", "Use teal", "Add one warning", existing
    )
    assert content.poster_title == "Check Before You Scan"
    assert captured["model"] == "gpt-4.1"
    request = json.loads(captured["messages"][1]["content"])
    assert request["latest_revision_instruction"] == "Add one warning"
    assert request["current_poster_specification"]["poster_title"] == content.poster_title


def test_full_poster_prompt_contains_exact_copy_and_revision() -> None:
    content = ai.parse_campaign_content(generated_payload())
    prompt = poster.build_full_poster_prompt(content, "Center all cards")
    assert content.poster_title in prompt
    assert all(point.heading in prompt and point.caption in prompt for point in content.key_points)
    assert "Center all cards" in prompt
    assert "background decoration must remain subtle" in prompt


def test_azure_image_generate_and_edit(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "source.png"
    Image.new("RGB", (32, 48), "white").save(output)
    encoded = base64.b64encode(output.read_bytes()).decode()
    calls: list[str] = []

    class Images:
        def generate(self, **_kwargs):
            calls.append("generate")
            return SimpleNamespace(data=[SimpleNamespace(b64_json=encoded)])

        def edit(self, **_kwargs):
            calls.append("edit")
            return SimpleNamespace(data=[SimpleNamespace(b64_json=encoded)])

    settings = SimpleNamespace(
        mock_ai_services=False,
        azure_openai_image_deployment="gpt-image-1",
        azure_openai_image_size="1024x1536",
        azure_openai_image_quality="high",
        poster_storage_path=str(tmp_path),
    )
    monkeypatch.setattr(poster, "get_settings", lambda: settings)
    monkeypatch.setattr(poster, "azure_openai_client", lambda: SimpleNamespace(images=Images()))
    content = ai.parse_campaign_content(generated_payload())

    poster.generate_azure_poster(content)
    poster.generate_azure_poster(content, "More red", str(output))
    assert calls == ["generate", "edit"]


def test_build_poster_saves_versioned_png(monkeypatch, tmp_path: Path) -> None:
    settings = SimpleNamespace(
        poster_storage_path=str(tmp_path),
        mock_ai_services=True,
        max_poster_image_bytes=2_500_000,
    )
    monkeypatch.setattr(poster, "get_settings", lambda: settings)
    content = ai.mock_campaign_content("Password safety")
    result = Path(poster.build_poster_png("campaign", content, version_number=3))
    assert result.name == "campaign-v0003.png"
    assert result.read_bytes().startswith(b"\x89PNG")
