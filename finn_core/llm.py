"""One Flash-Lite JSON call. The key is read from the environment or .env and never printed."""

import json
import os
from pathlib import Path

import requests

FLASH_LITE = "gemini-3.5-flash-lite"
FLASH_LITE_FALLBACK = "gemini-2.5-flash-lite"


def generate_json(prompt: str, schema: dict) -> tuple[dict, dict]:
    key = api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is missing")
    last_error = "no model call"
    for model in (FLASH_LITE, FLASH_LITE_FALLBACK):
        response = requests.post(
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
            timeout=90,
        )
        if response.status_code == 404:
            last_error = "model not found"
            continue
        if response.status_code != 200:
            last_error = f"HTTP {response.status_code}"
            continue
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
    raise RuntimeError(last_error)


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
