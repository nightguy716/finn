"""Download one results-filing PDF and one concall transcript; print 40 lines.

Uses the public Screener page for the transcript link and the public BSE
announcements JSON for a results filing. Files stay in the OS temp dir and
are removed after extraction.
"""

import re
import time
from datetime import date, timedelta
from html import unescape
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

PAUSE_S = 2.0
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*,application/pdf",
    "Accept-Language": "en-IN,en;q=0.9",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
}
HTML_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-IN,en;q=0.9",
}


def first_lines(text: str, n: int = 40) -> str:
    lines = text.splitlines()
    return "\n".join(lines[:n])


def extract(path: Path) -> tuple[int, int, str]:
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    text = "\n".join(pages)
    return len(reader.pages), len(text.strip()), text


def download(session: requests.Session, url: str, dest: Path) -> None:
    response = session.get(url, timeout=60)
    response.raise_for_status()
    dest.write_bytes(response.content)
    print(f"downloaded {len(response.content)} bytes content-type {response.headers.get('content-type')} -> {dest.name}")
    if not response.content.startswith(b"%PDF"):
        print(f"not a PDF. First bytes: {response.content[:24]!r}")


def direct_bse_pdf(session: requests.Session, url: str) -> str:
    if "Pname=" not in url:
        return url
    filename = url.split("Pname=", 1)[1].split("&", 1)[0]
    for prefix in (
        "https://www.bseindia.com/xml-data/corpfiling/AttachLive/",
        "https://www.bseindia.com/xml-data/corpfiling/AttachHis/",
    ):
        candidate = prefix + filename
        probe = session.get(candidate, headers={"Range": "bytes=0-15"}, timeout=30)
        is_pdf = probe.status_code in (200, 206) and probe.content.startswith(b"%PDF")
        print(f"resolve {probe.status_code} pdf {is_pdf} {prefix}")
        if is_pdf:
            return candidate
        time.sleep(PAUSE_S)
    return url


def transcript_url(session: requests.Session) -> str:
    page = session.get("https://www.screener.in/company/RELIANCE/consolidated/", headers=HTML_HEADERS, timeout=30)
    print(f"screener HTTP {page.status_code}")
    page.raise_for_status()
    soup = BeautifulSoup(page.text, "html.parser")
    for block in soup.select("div.documents"):
        heading = block.find(["h2", "h3"])
        title = heading.get_text(" ", strip=True).lower() if heading else ""
        if "concall" not in title:
            continue
        for anchor in block.find_all("a", href=True):
            if anchor.get_text(" ", strip=True).lower() == "transcript":
                found = urljoin(page.url, anchor["href"])
                return direct_bse_pdf(session, found)
    return ""


def reliance_scrip(session: requests.Session) -> str:
    response = session.get(
        "https://api.bseindia.com/BseIndiaAPI/api/PeerSmartSearch/w",
        params={"Type": "SS", "text": "RELIANCE"},
        timeout=30,
    )
    print(f"scrip lookup HTTP {response.status_code}")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, str):
        print("unexpected scrip payload")
        return ""
    for code, name, span in re.findall(
        r"liclick\('(\d+)','([^']*)'\).*?<span>(.*?)</span>", payload, flags=re.S
    ):
        plain = re.sub(r"<[^>]+>", " ", unescape(span)).replace("\xa0", " ")
        symbol = plain.split()[0] if plain.split() else ""
        if symbol.upper() == "RELIANCE":
            print(f"scrip {code} {unescape(name)}")
            return code
    print("no exact RELIANCE scrip")
    return ""


def results_pdf(session: requests.Session, code: str) -> str:
    start = date.today() - timedelta(days=120)
    end = date.today()
    print(f"results search {start.isoformat()} .. {end.isoformat()} scrip {code}")
    for page in range(1, 8):
        response = session.get(
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
            params={
                "pageno": page,
                "strCat": "-1",
                "strPrevDate": start.strftime("%Y%m%d"),
                "strScrip": code,
                "strSearch": "P",
                "strToDate": end.strftime("%Y%m%d"),
                "strType": "C",
                "subcategory": "-1",
            },
            timeout=30,
        )
        print(f"bse page {page} HTTP {response.status_code}")
        if response.status_code != 200:
            print(response.text[:160].replace("\n", " "))
            return ""
        table = response.json().get("Table") or []
        if not table:
            return ""
        print("categories:", sorted({str(row.get("CATEGORYNAME") or "") for row in table}))
        for row in table:
            category = str(row.get("CATEGORYNAME") or "")
            headline = str(row.get("NEWSSUB") or "")
            filename = str(row.get("ATTACHMENTNAME") or "")
            if filename and category.lower() == "result":
                print(f"results filing: {headline}")
                for prefix in (
                    "https://www.bseindia.com/xml-data/corpfiling/AttachLive/",
                    "https://www.bseindia.com/xml-data/corpfiling/AttachHis/",
                ):
                    url = prefix + filename
                    probe = session.get(url, headers={"Range": "bytes=0-15"}, timeout=30)
                    print(f"pdf probe {probe.status_code} {prefix}")
                    if probe.status_code in (200, 206) and (probe.content.startswith(b"%PDF") or "pdf" in probe.headers.get("content-type", "")):
                        return url
                    time.sleep(PAUSE_S)
                return ""
        time.sleep(PAUSE_S)
    return ""


def report(label: str, path: Path) -> None:
    print(f"\n----- {label} -----")
    try:
        pages, chars, text = extract(path)
    except Exception as exc:
        print(f"TEXT EXTRACTION FAILED: {type(exc).__name__}: {exc}")
        return
    print(f"pages {pages} extracted_chars {chars}")
    if chars < 200:
        print("TEXT EXTRACTION FAILED: almost no text (likely a scanned/image PDF).")
    print(first_lines(text))


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    transcript = transcript_url(session)
    print(f"transcript url: {transcript or 'NONE'}")
    time.sleep(PAUSE_S)
    code = reliance_scrip(session)
    time.sleep(PAUSE_S)
    results = results_pdf(session, code) if code else ""
    print(f"results url: {results or 'NONE'}")
    with TemporaryDirectory(prefix="finn-spike-") as tmp:
        root = Path(tmp)
        if transcript:
            path = root / "transcript.pdf"
            download(session, transcript, path)
            if path.exists() and path.read_bytes()[:4] == b"%PDF":
                report("CONCALL TRANSCRIPT", path)
            time.sleep(PAUSE_S)
        else:
            print("no transcript link found")
        if results:
            path = root / "results.pdf"
            download(session, results, path)
            if path.exists() and path.read_bytes()[:4] == b"%PDF":
                report("QUARTERLY RESULTS", path)
        else:
            print("no results PDF found")


if __name__ == "__main__":
    main()
