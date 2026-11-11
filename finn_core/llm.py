"""JSON calls to free-tier Gemini models. The key is read from the environment or .env and never printed."""

import json
import os
import time
from pathlib import Path

import requests

FLASH_LITE = "gemini-3.5-flash-lite"
FLASH_LITE_FALLBACK = "gemini-2.5-flash-lite"
# Stronger Flash for the one-line verdict. The free tier allows 20 requests a day.
FLASH = "gemini-3.6-flash"
FLASH_FALLBACKS = ("gemini-3-flash-preview",)
# Groq's free plan, from the rate-limit table on 11 Nov 2026. Llama 3.1 and 3.3
# are listed as enterprise on the models page, so they are not used here.
GROQ_EXTRACTION = ("openai/gpt-oss-20b", "qwen/qwen3.8-27b")
GROQ_VERIFY = ("openai/gpt-oss-120b", "openai/gpt-oss-20b")
LIMIT_MESSAGE = "daily free-tier limit reached; cached companies still work"


class QuotaError(RuntimeError):
    """Every configured free-tier provider returned 429."""

    code = "daily_limit"


def generate_json(
    prompt: str,
    schema: dict,
    models: tuple[str, ...] | None = None,
    timeout: int = 40,
    attempts: int = 2,
    groq_models: tuple[str, ...] | None = None,
) -> tuple[dict, dict]:
    """Gemini first. Groq runs only after a Gemini 429. A day cap on every provider raises QuotaError."""
    key = api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is missing")
    last_error = "no model call"
    saw_daily = False
    for model in models or (FLASH_LITE,):
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
                if response.status_code == 429 and _daily_limit(response):
                    saw_daily = True
                    break
            if attempt + 1 < attempts and not saw_daily:
                time.sleep(delay)
                delay *= 2
    if saw_daily and groq_models:
        groq_key = _named_key("GROQ_API_KEY")
        if groq_key:
            for model in groq_models:
                response = _groq_post(groq_key, model, prompt, timeout)
                if response is not None and response.status_code == 200:
                    return _parse_groq(response, model)
                if response is not None and response.status_code == 429:
                    saw_daily = True
                    last_error = f"{model} HTTP 429"
                    continue
                last_error = f"{model} request failed" if response is None else f"{model} HTTP {response.status_code}"
    if saw_daily:
        raise QuotaError(LIMIT_MESSAGE)
    raise RuntimeError(last_error)


def _parse_body(response, model: str) -> tuple[dict, dict]:
    body = response.json()
    meta = body.get("usageMetadata") or {}
    usage = {
        "model": model,
        "provider": "gemini",
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


def _daily_limit(response) -> bool:
    text = (response.text or "").lower()
    return "per day" in text or "daily" in text or "tpd" in text


def _groq_post(key: str, model: str, prompt: str, timeout: int):
    try:
        return requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": 0,
                "max_completion_tokens": 2048,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt + "\n\nRespond with one JSON object."}],
            },
            timeout=timeout,
        )
    except requests.RequestException:
        return None


def _parse_groq(response, model: str) -> tuple[dict, dict]:
    body = response.json()
    meta = body.get("usage") or {}
    usage = {
        "model": model,
        "provider": "groq",
        "input_tokens": int(meta.get("prompt_tokens") or 0),
        "output_tokens": int(meta.get("completion_tokens") or 0),
        "total_tokens": int(meta.get("total_tokens") or 0),
    }
    choice = ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    text = choice.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    try:
        return json.loads(text), usage
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"model returned non-json: {exc}") from exc


def api_key() -> str:
    return _named_key("GEMINI_API_KEY")


def _named_key(name: str) -> str:
    found = os.environ.get(name, "").strip().strip('"').strip("'")
    if found:
        return found
    for candidate in (Path(".env"), Path(__file__).resolve().parents[1] / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""
