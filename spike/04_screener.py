"""Public screener.in company pages: annual-report and concall links.

No login cookie. One HTML page per ticker, consolidated first.
"""

import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

TICKERS = ["RELIANCE", "MARICO", "CGPOWER"]
PAUSE_S = 2.5
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-IN,en;q=0.9",
}


def fetch(session: requests.Session, symbol: str) -> tuple[str, requests.Response]:
    for suffix in ("consolidated", ""):
        url = f"https://www.screener.in/company/{symbol}/" + (suffix + "/" if suffix else "")
        response = session.get(url, timeout=30, allow_redirects=True)
        print(f"GET {response.url} HTTP {response.status_code} bytes {len(response.content)}")
        if response.status_code == 200 and b"documents" in response.content.lower():
            return response.url, response
        if response.status_code == 200 and suffix == "":
            return response.url, response
        time.sleep(PAUSE_S)
    return url, response


def section_blocks(soup: BeautifulSoup) -> list[tuple[str, object]]:
    blocks = []
    for block in soup.select("div.documents"):
        heading = block.find(["h2", "h3"])
        title = heading.get_text(" ", strip=True) if heading else ""
        blocks.append((title, block))
    return blocks


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    for symbol in TICKERS:
        print(f"\n=== {symbol} ===")
        page_url, response = fetch(session, symbol)
        if response.status_code in (401, 403, 429):
            print("BLOCKED")
            time.sleep(PAUSE_S)
            continue
        if response.status_code != 200:
            print(response.text[:160].replace("\n", " "))
            time.sleep(PAUSE_S)
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        blocks = section_blocks(soup)
        print("document sections:", [title for title, _ in blocks] or "NONE")
        if not blocks:
            headings = [h.get_text(" ", strip=True) for h in soup.find_all(["h2", "h3"])]
            print("page headings:", headings[:20])
        for title, block in blocks:
            lowered = title.lower()
            if "annual" not in lowered and "concall" not in lowered and "transcript" not in lowered:
                continue
            items = block.select("li") or [block]
            print(f"-- {title} ({len(block.select('a[href]'))} links)")
            limit = 4 if "concall" in lowered or "transcript" in lowered else 5
            for li in items[:limit]:
                label_bits = []
                for child in li.children:
                    if getattr(child, "name", None) == "a":
                        continue
                    text = child.get_text(" ", strip=True) if hasattr(child, "get_text") else str(child).strip()
                    if text:
                        label_bits.append(text)
                label = " ".join(label_bits)[:80]
                links = []
                for anchor in li.find_all("a", href=True):
                    links.append(f"{anchor.get_text(' ', strip=True)} -> {urljoin(page_url, anchor['href'])}")
                print(f"  {label}")
                for link in links:
                    print(f"    {link}")
            extra = len(items) - limit
            if extra > 0:
                print(f"  ... {extra} older rows not printed")
        time.sleep(PAUSE_S)


if __name__ == "__main__":
    main()
