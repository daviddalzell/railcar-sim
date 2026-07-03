# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

import base64
import json
import os
import random
import shutil
import subprocess
import time
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path

MAX_IMAGE_PX = 1024  # longest side cap before sending to any vision API

CAR_TYPES = [
    "boxcar", "flatcar", "gondola", "tank car", "hopper",
    "covered hopper", "refrigerator car", "caboose", "passenger car", "other",
]

PROMPT = """Analyze this image of a model railroad car and extract the following information.
Return ONLY a JSON object with these fields (no markdown, no explanation):

{
  "car_type": "<one of: boxcar, flatcar, gondola, tank car, hopper, covered hopper, refrigerator car, caboose, passenger car, other>",
  "color": "<primary color of the car body>",
  "car_number": "<the numeric or alphanumeric road number stenciled on the car side, or empty string if not visible>",
  "reporting_marks": "<the railroad owner initials stenciled on the car, e.g. UP, BNSF, SP, CN — or empty string if not visible>"
}

If you cannot determine a value, use an empty string. For car_type, always pick the closest match from the list."""

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _is_retryable(exc: Exception) -> bool:
    """Return True if this exception is a transient provider error worth retrying."""
    try:
        import anthropic
        retryable = [anthropic.RateLimitError, anthropic.InternalServerError]
        # OverloadedError (529) was removed in newer SDK versions; use APIStatusError fallback
        if hasattr(anthropic, "OverloadedError"):
            retryable.append(anthropic.OverloadedError)
        if isinstance(exc, tuple(retryable)):
            return True
        if isinstance(exc, anthropic.APIStatusError) and exc.status_code in (429, 529, 500):
            return True
    except ImportError:
        pass
    try:
        import openai
        if isinstance(exc, (openai.RateLimitError, openai.InternalServerError)):
            return True
    except ImportError:
        pass
    try:
        from google.genai import errors as _ge
        if isinstance(exc, _ge.APIError):
            code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            if code in (429, 500, 503):
                return True
    except ImportError:
        pass
    return False


def call_with_retry(fn, max_attempts: int | None = None, base_delay: float | None = None):
    """Call fn() retrying transient AI errors with exponential backoff + jitter.

    Retryable: 429 rate-limit, 529 Anthropic overload, 503 unavailable, 500 server error.
    Non-retryable (fail fast): 400 bad request, 401 auth, 403 permission, 404 not found.
    Configurable via AI_MAX_RETRIES and AI_RETRY_BASE_DELAY env vars.
    """
    attempts = max_attempts or int(os.environ.get("AI_MAX_RETRIES", "3"))
    delay    = base_delay   or float(os.environ.get("AI_RETRY_BASE_DELAY", "1.0"))
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if not _is_retryable(exc):
                raise
            last_exc = exc
            if attempt < attempts - 1:
                wait = delay * (2 ** attempt) * (0.5 + random.random() * 0.5)
                time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def _load_image(image_path: str, max_px: int = 0) -> tuple[str, str]:
    """Return (base64_data, media_type) for the given image file.
    If max_px > 0, resize so the longest side is at most max_px before encoding."""
    if max_px > 0:
        try:
            from PIL import Image as _Image
            import io as _io
            with _Image.open(image_path) as img:
                img.thumbnail((max_px, max_px), _Image.LANCZOS)
                buf = _io.BytesIO()
                img.convert("RGB").save(buf, "JPEG", quality=95, subsampling=0)
                data = buf.getvalue()
                return base64.standard_b64encode(data).decode("utf-8"), "image/jpeg"
        except Exception:
            pass  # fall through to raw read
    data = Path(image_path).read_bytes()
    b64 = base64.standard_b64encode(data).decode("utf-8")
    media_type = _MEDIA_TYPES.get(Path(image_path).suffix.lower(), "image/jpeg")
    return b64, media_type


def _parse_json_response(raw: str) -> dict:
    """Strip optional markdown fences and parse JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _normalize(data: dict) -> dict:
    return {
        "car_type": data.get("car_type", "other"),
        "color": data.get("color", ""),
        "car_number": data.get("car_number", ""),
        "reporting_marks": data.get("reporting_marks", ""),
    }


# ── Abstract base ─────────────────────────────────────────────────────────────

class VisionProvider(ABC):
    def __init__(self, api_key: str | None = None):
        self._api_key = api_key

    @abstractmethod
    def analyze(self, image_path: str) -> dict: ...

    @abstractmethod
    def is_available(self) -> bool: ...


# ── Anthropic ─────────────────────────────────────────────────────────────────

class AnthropicVisionProvider(VisionProvider):
    def _key(self) -> str | None:
        return self._api_key or os.environ.get("ANTHROPIC_API_KEY")

    def is_available(self) -> bool:
        return bool(self._key())

    def analyze(self, image_path: str) -> dict:
        import anthropic
        api_key = self._key()
        if not api_key:
            raise RuntimeError("No Anthropic API key configured")

        b64, media_type = _load_image(image_path, max_px=MAX_IMAGE_PX)
        client = anthropic.Anthropic(api_key=api_key)
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

        message = call_with_retry(lambda: client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": PROMPT},
                ],
            }],
        ))
        return _normalize(_parse_json_response(message.content[0].text))


# ── OpenAI ────────────────────────────────────────────────────────────────────

class OpenAIVisionProvider(VisionProvider):
    def _key(self) -> str | None:
        return self._api_key or os.environ.get("OPENAI_API_KEY")

    def is_available(self) -> bool:
        return bool(self._key())

    def analyze(self, image_path: str) -> dict:
        import openai
        api_key = self._key()
        if not api_key:
            raise RuntimeError("No OpenAI API key configured")

        b64, media_type = _load_image(image_path, max_px=MAX_IMAGE_PX)
        client = openai.OpenAI(api_key=api_key)
        model = os.environ.get("OPENAI_MODEL", "gpt-4o")

        response = call_with_retry(lambda: client.chat.completions.create(
            model=model,
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
                    {"type": "text", "text": PROMPT},
                ],
            }],
        ))
        return _normalize(_parse_json_response(response.choices[0].message.content))


# ── Ollama (open-source, local) ───────────────────────────────────────────────

class OllamaVisionProvider(VisionProvider):
    def _server_root(self) -> str:
        base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        return base.rstrip("/").removesuffix("/v1")

    def _is_running(self) -> bool:
        try:
            urllib.request.urlopen(self._server_root(), timeout=2)
            return True
        except Exception:
            return False

    def is_available(self) -> bool:
        return self._is_running()

    def _ollama_bin(self) -> str | None:
        found = shutil.which("ollama")
        if found:
            return found
        for candidate in [
            "/Applications/Ollama.app/Contents/Resources/ollama",
            "/usr/local/bin/ollama",
            "/opt/homebrew/bin/ollama",
        ]:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return None

    def ensure_ready(self):
        model = os.environ.get("OLLAMA_MODEL", "llava")

        bin_path = self._ollama_bin()
        if not bin_path:
            raise RuntimeError(
                "ollama binary not found. Install from https://ollama.com"
            )

        if not self._is_running():
            print("Ollama: starting daemon...")
            subprocess.Popen(
                [bin_path, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(20):
                time.sleep(0.5)
                if self._is_running():
                    break
            else:
                raise RuntimeError("Ollama daemon failed to start within 10 seconds")
            print("Ollama: daemon ready.")

        result = subprocess.run([bin_path, "list"], capture_output=True, text=True)
        if model not in result.stdout:
            print(f"Ollama: pulling model '{model}' (this may take a few minutes)...")
            subprocess.run([bin_path, "pull", model], check=True)
            print(f"Ollama: model '{model}' ready.")

    def analyze(self, image_path: str) -> dict:
        import openai
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        model = os.environ.get("OLLAMA_MODEL", "llava")

        max_px = int(os.environ.get("OLLAMA_MAX_IMAGE_PX", "1080"))
        b64, media_type = _load_image(image_path, max_px=max_px)
        client = openai.OpenAI(api_key="ollama", base_url=base_url)

        num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
        response = call_with_retry(lambda: client.chat.completions.create(
            model=model,
            max_tokens=512,
            extra_body={"options": {"num_ctx": num_ctx}},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
                    {"type": "text", "text": PROMPT},
                ],
            }],
        ))
        return _normalize(_parse_json_response(response.choices[0].message.content))


# ── Gemini ────────────────────────────────────────────────────────────────────

class GeminiVisionProvider(VisionProvider):
    def _key(self) -> str | None:
        return self._api_key or os.environ.get("GEMINI_API_KEY")

    def is_available(self) -> bool:
        return bool(self._key())

    def analyze(self, image_path: str) -> dict:
        from google import genai
        from google.genai import types

        api_key = self._key()
        model_name = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")

        client = genai.Client(api_key=api_key)
        b64, media_type = _load_image(image_path, max_px=MAX_IMAGE_PX)
        image_bytes = base64.b64decode(b64)

        response = call_with_retry(lambda: client.models.generate_content(
            model=model_name,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=media_type),
                PROMPT,
            ],
        ))
        return _normalize(_parse_json_response(response.text))


# ── Factory ───────────────────────────────────────────────────────────────────

_PROVIDERS: dict[str, type[VisionProvider]] = {
    "anthropic": AnthropicVisionProvider,
    "openai": OpenAIVisionProvider,
    "ollama": OllamaVisionProvider,
    "gemini": GeminiVisionProvider,
}


def get_provider(tenant=None) -> VisionProvider:
    if tenant and getattr(tenant, "vision_provider", None):
        name = tenant.vision_provider
    else:
        name = os.environ.get("VISION_PROVIDER", "anthropic")
    cls = _PROVIDERS.get(name)
    if not cls:
        raise ValueError(f"Unknown VISION_PROVIDER '{name}'. Valid options: {list(_PROVIDERS)}")
    api_key = getattr(tenant, f"{name}_api_key", None) if tenant else None
    return cls(api_key=api_key)


def analyze_car_photo(image_path: str, tenant=None) -> dict:
    return get_provider(tenant).analyze(image_path)


def _text_complete(prompt: str, tenant=None) -> str:
    """Run a text-only prompt using the configured provider, with optional tenant key override."""
    if tenant and getattr(tenant, "vision_provider", None):
        provider = tenant.vision_provider
    else:
        provider = os.environ.get("VISION_PROVIDER", "anthropic")

    def _key(name: str) -> str | None:
        if tenant:
            k = getattr(tenant, f"{name}_api_key", None)
            if k:
                return k
        return os.environ.get(f"{name.upper()}_API_KEY")

    if provider == "anthropic":
        import anthropic
        api_key = _key("anthropic")
        if not api_key:
            raise RuntimeError("No Anthropic API key configured")
        client = anthropic.Anthropic(api_key=api_key)
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        msg = call_with_retry(lambda: client.messages.create(
            model=model, max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        ))
        return msg.content[0].text

    if provider == "openai":
        import openai
        api_key = _key("openai")
        if not api_key:
            raise RuntimeError("No OpenAI API key configured")
        client = openai.OpenAI(api_key=api_key)
        model = os.environ.get("OPENAI_MODEL", "gpt-4o")
        resp = call_with_retry(lambda: client.chat.completions.create(
            model=model, max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        ))
        return resp.choices[0].message.content

    if provider == "ollama":
        import openai
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        model = os.environ.get("OLLAMA_MODEL", "llava")
        client = openai.OpenAI(api_key="ollama", base_url=base_url)
        resp = call_with_retry(lambda: client.chat.completions.create(
            model=model, max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        ))
        return resp.choices[0].message.content

    if provider == "gemini":
        from google import genai
        api_key = _key("gemini")
        if not api_key:
            raise RuntimeError("No Gemini API key configured")
        model_name = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
        client = genai.Client(api_key=api_key)
        resp = call_with_retry(lambda: client.models.generate_content(model=model_name, contents=[prompt]))
        return resp.text

    raise ValueError(f"Unknown VISION_PROVIDER '{provider}'")


def suggest_commodity_car_type(commodity: str, existing_map: dict[str, str], tenant=None) -> dict:
    """Return AI-suggested car type for a commodity, constrained to CAR_TYPES."""
    car_types_str = ", ".join(CAR_TYPES)
    existing_str = (
        "; ".join(f"{c} → {t}" for c, t in existing_map.items())
    ) if existing_map else "none yet"

    prompt = f"""You are a model railroad operations expert.

The user wants to add a commodity-to-car-type mapping for their layout.

Commodity: "{commodity}"

Existing mappings on this layout: {existing_str}

What is the correct car type for this commodity?

Valid car types (pick exactly one): {car_types_str}

Return ONLY a JSON object with no markdown, no explanation:
{{
  "car_type": "<one of the valid car types above>"
}}"""

    return _parse_json_response(_text_complete(prompt, tenant))


def suggest_industry(description: str, existing_industries: list[str], known_commodities: list[str] | None = None, tenant=None) -> dict:
    """Return AI-suggested commodities, accepted_car_types, and industry_role for a new industry."""
    car_types_str = ", ".join(CAR_TYPES)
    existing_str = (", ".join(existing_industries)) if existing_industries else "none yet"
    known_str = (", ".join(known_commodities)) if known_commodities else "none yet"

    prompt = f"""You are a model railroad operations expert. A user is adding a new industry to their layout.

Industry name / description: "{description}"

Existing industries on this layout: {existing_str}

Known commodities already in this layout's commodity map: {known_str}
Prefer using these exact commodity names when they are a close match for what this industry handles. Only introduce a new commodity name if none of the known ones fit.

Suggest realistic railroad commodities, car types, and role for this industry.

Valid car types (use only these): {car_types_str}
Valid industry_role values: consumer, producer, transload

Return ONLY a JSON object with these fields (no markdown, no explanation):
{{
  "industry_role": "<consumer, producer, or transload>",
  "inbound_commodities": "<comma-separated commodities this industry RECEIVES, or empty string if producer>",
  "inbound_car_types": "<comma-separated car types for inbound traffic, or empty string if producer>",
  "outbound_commodities": "<comma-separated commodities this industry SHIPS, or empty string if consumer>",
  "outbound_car_types": "<comma-separated car types for outbound traffic, or empty string if consumer>"
}}

consumer = receives loaded cars only (e.g. factory consuming raw materials)
producer = ships loaded cars only (e.g. mine, grain elevator)
transload = both receives AND ships, potentially different commodities each direction (e.g. grain elevator receives grain, ships flour)"""

    return _parse_json_response(_text_complete(prompt, tenant))
