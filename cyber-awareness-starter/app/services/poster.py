import base64
import hashlib
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from app.config import get_settings
from app.services.ai import CampaignContent, azure_openai_client


def poster_directory() -> Path:
    directory = Path(get_settings().poster_storage_path).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def build_full_poster_prompt(
    content: CampaignContent,
    revision_prompt: str = "",
) -> str:
    sections = "\n".join(
        f"{index}. {point.heading} — {point.caption}. Visual: {point.illustration_prompt}."
        for index, point in enumerate(content.key_points, start=1)
    )
    revision = (
        f"\nLATEST USER REVISION: {revision_prompt.strip()}"
        if revision_prompt.strip()
        else ""
    )
    return f"""
Create a finished portrait cybersecurity infographic poster, ready to email as a PNG.

Exact copy to show:
TITLE: {content.poster_title}
SUBTITLE: {content.poster_subtitle}
SECTION CARDS:
{sections}
CALL TO ACTION: {content.call_to_action}

Visual direction:
- polished corporate infographic, not a photograph and not a mockup
- centered, symmetrical composition with every card and visual precisely aligned
- use all available page space with balanced margins and minimal empty gaps
- show one clear icon or illustration for every section
- use the exact supplied wording; do not add, remove, or misspell any text
- make headings larger than captions and keep captions concise and readable
- use {content.layout_accent} as the main accent with white, charcoal, and light gray
- background: {content.background_prompt}
- background decoration must remain subtle, low contrast, and outside text areas
- no background lines, patterns, icons, or focal objects may cross behind text
- no QR codes, fake logos, watermarks, browser frames, device mockups, or extra text
- leave a clean small footer area for a real company logo overlay
{revision}
""".strip()


def _mock_poster(content: CampaignContent, revision_prompt: str) -> bytes:
    digest = hashlib.sha256(
        f"{content.poster_title}:{revision_prompt}".encode("utf-8")
    ).digest()
    accent = (220, 36 + digest[0] % 30, 42 + digest[1] % 30)
    image = Image.new("RGB", (1024, 1536), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((45, 45, 979, 1491), radius=54, outline=accent, width=18)
    draw.rectangle((45, 1290, 979, 1491), fill=accent)
    draw.text((512, 125), content.poster_title, fill="#151515", anchor="mm")
    draw.text((512, 175), content.poster_subtitle, fill="#555555", anchor="mm")
    columns = 2
    card_width, card_height = 420, 230
    for index, point in enumerate(content.key_points):
        row, column = divmod(index, columns)
        x = 72 + column * 455
        y = 260 + row * 265
        draw.rounded_rectangle(
            (x, y, x + card_width, y + card_height),
            radius=28,
            fill="#f5f6f8",
            outline="#dddddd",
            width=3,
        )
        draw.ellipse((x + 170, y + 25, x + 250, y + 105), fill=accent)
        draw.text((x + 210, y + 138), point.heading, fill="#151515", anchor="mm")
        draw.text((x + 210, y + 180), point.caption, fill="#555555", anchor="mm")
    draw.text((512, 1385), content.call_to_action, fill="white", anchor="mm")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _decode_image_result(result: object) -> bytes:
    data = getattr(result, "data", None)
    if not data:
        raise RuntimeError("Azure OpenAI returned no poster image")
    first = data[0]
    encoded = getattr(first, "b64_json", None)
    if encoded:
        return base64.b64decode(encoded)
    url = getattr(first, "url", None)
    if url:
        response = httpx.get(url, timeout=120)
        response.raise_for_status()
        return response.content
    raise RuntimeError("Azure OpenAI returned an unsupported image response")


def generate_azure_poster(
    content: CampaignContent,
    revision_prompt: str = "",
    source_path: str | None = None,
) -> bytes:
    settings = get_settings()
    if settings.mock_ai_services:
        return _mock_poster(content, revision_prompt)
    if not settings.azure_openai_image_deployment:
        raise RuntimeError("AZURE_OPENAI_IMAGE_DEPLOYMENT is required")

    prompt = build_full_poster_prompt(content, revision_prompt)
    client = azure_openai_client()
    try:
        if source_path:
            source = safe_poster_path(source_path)
            with source.open("rb") as image_file:
                result = client.images.edit(
                    model=settings.azure_openai_image_deployment,
                    image=image_file,
                    prompt=prompt,
                    size=settings.azure_openai_image_size,
                    quality=settings.azure_openai_image_quality,
                    output_format="png",
                )
        else:
            result = client.images.generate(
                model=settings.azure_openai_image_deployment,
                prompt=prompt,
                size=settings.azure_openai_image_size,
                quality=settings.azure_openai_image_quality,
                output_format="png",
            )
        return _decode_image_result(result)
    except Exception as exc:
        raise RuntimeError(f"Azure OpenAI poster generation failed: {exc}") from exc


def _add_company_logo(image: Image.Image) -> Image.Image:
    logo_path = Path(__file__).resolve().parent.parent / "static" / "megawide-logo.png"
    if not logo_path.is_file():
        return image
    with Image.open(logo_path) as raw_logo:
        logo = raw_logo.convert("RGBA")
        max_width = int(image.width * 0.34)
        max_height = int(image.height * 0.07)
        logo.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        x = (image.width - logo.width) // 2
        y = image.height - logo.height - int(image.height * 0.025)
        canvas = image.convert("RGBA")
        draw = ImageDraw.Draw(canvas)
        padding = 16
        draw.rounded_rectangle(
            (x - padding, y - padding, x + logo.width + padding, y + logo.height + padding),
            radius=14,
            fill=(255, 255, 255, 235),
        )
        canvas.alpha_composite(logo, (x, y))
        return canvas.convert("RGB")


def _save_optimized_png(image_bytes: bytes, path: Path, maximum_bytes: int) -> None:
    with Image.open(BytesIO(image_bytes)) as raw:
        image = _add_company_logo(raw.convert("RGB"))
        image.save(path, format="PNG", optimize=True)
        if path.stat().st_size > maximum_bytes:
            image.thumbnail((900, 1350), Image.Resampling.LANCZOS)
            image.save(path, format="PNG", optimize=True, compress_level=9)
        if path.stat().st_size > maximum_bytes:
            reduced = image.quantize(colors=192, method=Image.Quantize.MEDIANCUT)
            reduced.save(path, format="PNG", optimize=True, compress_level=9)
    if path.stat().st_size > maximum_bytes:
        raise RuntimeError(
            f"Generated poster is larger than {maximum_bytes // 1_000_000} MB"
        )


def build_poster_png(
    campaign_id: str,
    content: CampaignContent,
    version_number: int = 1,
    revision_prompt: str = "",
    source_path: str | None = None,
) -> str:
    path = poster_directory() / f"{campaign_id}-v{version_number:04d}.png"
    image_bytes = generate_azure_poster(content, revision_prompt, source_path)
    _save_optimized_png(image_bytes, path, get_settings().max_poster_image_bytes)
    return str(path)


def safe_poster_path(stored_path: str) -> Path:
    directory = poster_directory()
    path = Path(stored_path).resolve()
    if path.parent != directory or path.suffix.lower() != ".png":
        raise ValueError("Invalid poster file path")
    return path


def read_poster_image(stored_path: str) -> bytes:
    path = safe_poster_path(stored_path)
    if not path.is_file():
        raise FileNotFoundError("Poster image was not found")
    return path.read_bytes()


def remove_poster_files(stored_path: str | None) -> None:
    if not stored_path:
        return
    path = safe_poster_path(stored_path)
    path.unlink(missing_ok=True)


def remove_campaign_posters(campaign_id: str) -> None:
    safe_id = campaign_id.replace("/", "").replace("\\", "")
    for path in poster_directory().glob(f"{safe_id}-v*.png"):
        if path.parent == poster_directory():
            path.unlink(missing_ok=True)
    legacy = poster_directory() / f"{safe_id}.png"
    legacy.unlink(missing_ok=True)
    legacy.with_suffix(".html").unlink(missing_ok=True)
