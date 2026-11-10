"""JSON calls to free-tier Gemini models. The key is read from the environment or .env and never printed."""

import json
import os
import time
from pathlib import Path

import requests

FLASH_LITE = "gemini-3.5-flash-lite"
FLASH_LITE_FALLBACK = "gemini-2.5-flash-lite"
# Stronger Flash for the one-line verdict. gemini-3.8-flash is listed but timed out
# on a short call (90s). gemini-2.5-flash returned 404. gemini-3.6-flash answered.
FLASH = "gemini-3.6-flash"
FLASH_FALLBACKS = ("gemini-3.5-flash", "gemini-3.8-flash")


def generate_json(
    prompt: str,
    schema: dict,
    models: tuple[str, ...] | None = None,
    timeout: int = 40,
    attempts: int = 2,
) -> tuple[dict, dict]:
    """Call Flash models in order. 404, 429, 503, and timeouts are retried with backoff."""
    key = api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is missing")
    last_error = "no model call"
    for model in models or (FLASH_LITE, FLASH_LITE_FALLBACK):
        delay = 2
        for attempt in range(max(1, attempts)):
            response = _post(key, model, prompt, schema, timeout)
            if response is not None and response.status_code == 200:
                return _parse_body(response, model)
            if response is None:
                last_error = f"{model} request failed"
            elif response.status_code == 404:
                last_error = f"{model} not found"
            else:
                last_error = f"{model} HTTP {response.status_code}"
            if attempt + 1 < attempts:
                time.sleep(delay)
                delay *= 2
    raise RuntimeError(last_error)


def _parse_body(response, model: str) -> tuple[dict, dict]:
    body = response.json()
    meta = body.get("usageMetadata") or {}
    usage = {
        "model": model,
        "input_tokens": int(meta.get("promptTokenCount") or 0),
        "output_tokens": int(meta.get("candidatesTokenCount") or 0),
        "total_tokens": int(meta.get("totalTokenCount") or 0),
    }
    texts = []
    for candidate in body.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            if part.get("text"):
                texts.append(part["text"])
    try:
        return json.loads("".join(texts)), usage
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"model returned non-json: {exc}") from exc


def _post(key: str, model: str, prompt: str, schema: dict, timeout: int = 40):
    try:
        return requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                    "responseSchema": schema,
                },
            },
            timeout=timeout,
        )
    except requests.RequestException:
        return None


def api_key() -> str:
    found = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    if found:
        return found
    for candidate in (Path(".env"), Path(__file__).resolve().parents[1] / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""
