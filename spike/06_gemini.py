"""List models visible to GEMINI_API_KEY and make one small generateContent call.

The key is read from the repo-root .env and is never printed.
Free-tier notes below are taken from the official pages fetched for this spike:
https://ai.google.dev/gemini-api/docs/pricing (page says last updated 2026-10-30 UTC)
https://ai.google.dev/gemini-api/docs/rate-limits
https://ai.google.dev/gemini-api/docs/gemini-3
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DOCS = """
Official docs (not from memory):

Rate limits page: limits are RPM, input TPM, and RPD, applied per project.
RPD resets at midnight Pacific time. Free-tier spend cap is N/A.
Preview and experimental models are more restricted.
The page does NOT publish a current model-by-model RPM/TPM/RPD table.
It says the numbers depend on tier and are viewed in Google AI Studio,
and that specified rate limits are not guaranteed.

Pricing page, Standard column, input price "Free of charge"
(text models relevant to FINN):
  gemini-3.8-flash, gemini-3.6-flash, gemini-3.5-flash-lite,
  gemini-3.1-flash-lite, gemini-3-flash-preview,
  gemini-2.5-pro, gemini-2.5-flash, gemini-2.5-flash-lite,
  gemini-embedding-2, gemini-embedding-001.
Standard input "Not available" (no free tier): gemini-4-argon,
  gemini-3.1-pro-preview, gemini-omni-1.1-flash, image models
  (gemini-3-pro-image, gemini-3.1 flash image, nano-banana-2.1).

Numeric free-tier figures that ARE on the pricing page are grounding caps,
not generation caps: Gemini 2.5 Flash and Flash-Lite Google Search is free
up to 500 RPD shared between them; Maps grounding is 500 RPD.
Gemini 3 Search grounding is "Not available" on the free tier.

Gemini 3 FAQ: gemini-3-flash-preview has a Gemini API free tier.
gemini-3.1-pro-preview has no API free tier (AI Studio trial only).
"""

# Cheapest text models the pricing page marks free, newest first.
PREFER = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
)


def redact(text: str, secret: str) -> str:
    cleaned = text.replace(secret, "[REDACTED]")
    return cleaned.replace(requests.utils.quote(secret, safe=""), "[REDACTED]")


def main() -> None:
    load_dotenv(ROOT / ".env")
    key = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    if not key:
        sys.exit("GEMINI_API_KEY is missing")
    print(DOCS)
    headers = {"x-goog-api-key": key}
    names: list[str] = []
    page_token = ""
    while True:
        params = {"pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        response = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers=headers,
            params=params,
            timeout=30,
        )
        print(f"listModels HTTP {response.status_code}")
        if response.status_code != 200:
            print(redact(response.text[:500], key))
            return
        payload = response.json()
        for model in payload.get("models") or []:
            name = str(model.get("name", "")).removeprefix("models/")
            methods = ",".join(model.get("supportedGenerationMethods") or [])
            names.append(name)
            if "generateContent" in methods:
                print(f"  {name}  methods={methods}")
        page_token = payload.get("nextPageToken") or ""
        if not page_token:
            break
    chosen = next((name for name in PREFER if name in names), "")
    print(f"\nmodels_visible {len(names)}")
    print(f"chosen_for_one_call {chosen or 'NONE'}")
    if not chosen:
        print("No preferred free text model in the key's model list. No generate call made.")
        return
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{chosen}:generateContent",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "contents": [{"role": "user", "parts": [{"text": "Reply with the single word ok."}]}],
            "generationConfig": {"maxOutputTokens": 128, "temperature": 1.0},
        },
        timeout=60,
    )
    print(f"generateContent HTTP {response.status_code} model {chosen}")
    interesting = {
        k: v
        for k, v in response.headers.items()
        if "rate" in k.lower() or "quota" in k.lower() or k.lower().startswith("x-")
    }
    if interesting:
        print("rate headers", {k: v for k, v in interesting.items()})
    body = redact(response.text, key)
    if response.status_code != 200:
        print(body[:800])
        return
    payload = response.json()
    texts = []
    for candidate in payload.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            if part.get("text"):
                texts.append(part["text"])
    print("reply:", " ".join(texts).strip())
    print("usage:", payload.get("usageMetadata"))


if __name__ == "__main__":
    main()
