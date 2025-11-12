import argparse
import json
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dateutil import tz
from tqdm import tqdm

from extractors.reel_parser import parse_reel_html
from extractors.proxy_manager import ProxyManager
from extractors.utils_date import normalize_datetime
from outputs.exporter import Exporter

FB_REEL_PATH_RE = re.compile(r"/reel/\d+/?", re.IGNORECASE)

def setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def build_session(user_agent: Optional[str] = None, timeout: int = 20, proxies: Optional[Dict[str, str]] = None) -> requests.Session:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    sess.timeout = timeout  # type: ignore[attr-defined]
    if proxies:
        sess.proxies.update(proxies)
    return sess

def find_reel_links_from_page_html(base_url: str, html: str, limit: Optional[int]) -> List[str]:
    """
    Extract reel links from a Facebook page HTML by scanning for '/reel/<id>' paths.
    """
    soup = BeautifulSoup(html, "html.parser")
    links: List[str] = []

    # Gather anchors
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if FB_REEL_PATH_RE.search(href):
            full = urljoin(base_url, href)
            links.append(full)

    # Also search raw html in case anchors are obfuscated
    for m in FB_REEL_PATH_RE.finditer(html):
        full = urljoin(base_url, m.group(0))
        links.append(full)

    # Deduplicate preserving order
    seen = set()
    uniq = []
    for u in links:
        if u not in seen:
            seen.add(u)
            uniq.append(u)

    if limit is not None:
        uniq = uniq[:max(0, int(limit))]
    return uniq

def fetch_url(session: requests.Session, url: str, timeout: int) -> Optional[str]:
    try:
        resp = session.get(url, timeout=timeout)
        if resp.status_code >= 400:
            logging.warning("HTTP %s for %s", resp.status_code, url)
            return None
        return resp.text
    except requests.RequestException as e:
        logging.warning("Request error for %s: %s", url, e)
        return None

def scrape_page(session: requests.Session, page_url: str, max_reels: Optional[int]) -> List[Dict[str, Any]]:
    """
    Given a public page URL, fetch its HTML, discover reel links, then fetch and parse each reel.
    """
    logging.info("Fetching page: %s", page_url)
    page_html = fetch_url(session, page_url, getattr(session, "timeout", 20))
    if not page_html:
        return []

    reel_links = find_reel_links_from_page_html(page_url, page_html, max_reels)
    logging.info("Found %d candidate reels on %s", len(reel_links), page_url)

    results: List[Dict[str, Any]] = []
    for link in tqdm(reel_links, desc="Reels", leave=False):
        html = fetch_url(session, link, getattr(session, "timeout", 20))
        if not html:
            continue
        try:
            record = parse_reel_html(html, link)
            # Enrich with normalized dates if present
            if record.get("reelDateTime"):
                record["reelDateTime"] = normalize_datetime(record["reelDateTime"])
            elif record.get("reelDate"):
                record["reelDate"] = normalize_datetime(record["reelDate"], date_only=True)
            results.append(record)
        except Exception as e:
            logging.debug("Parse failure for %s: %s", link, e)
            continue
    return results

def validate_page_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.scheme and parsed.netloc)

def run(
    input_path: str,
    settings_path: Optional[str],
    output_path: Optional[str],
    verbosity: int,
) -> int:
    setup_logging(verbosity)

    # Load settings (with defaults)
    settings = {
        "userAgent": None,
        "timeoutSec": 25,
        "useProxies": False,
        "proxies": [],  # list of strings or dicts
        "output": {
            "format": "json",  # json|csv|excel|html
            "path": "data/output.json",
        },
        "maxReelsPerPage": None,
        "timezone": "Asia/Karachi",
    }
    if settings_path and os.path.exists(settings_path):
        user_settings = load_json(settings_path)
        # Shallow merge (simple override)
        for k, v in user_settings.items():
            settings[k] = v

    # Output configuration
    if output_path:
        settings["output"]["path"] = output_path  # type: ignore[index]

    # Prepare session + proxies
    pm = ProxyManager(settings.get("proxies", [])) if settings.get("useProxies") else None
    proxies = pm.get_requests_proxies() if pm else None
    session = build_session(
        user_agent=settings.get("userAgent"),
        timeout=settings.get("timeoutSec", 25),
        proxies=proxies,
    )

    # Timezone for normalization
    os.environ["SCRAPER_TZ"] = settings.get("timezone") or "Asia/Karachi"

    # Read input
    if not os.path.exists(input_path):
        logging.error("Input file not found: %s", input_path)
        return 1
    inputs = load_json(input_path)

    # Inputs may be list of page URLs or objects with {url, maxReels}
    targets: List[Dict[str, Any]] = []
    if isinstance(inputs, list):
        for item in inputs:
            if isinstance(item, str):
                targets.append({"url": item, "maxReels": settings.get("maxReelsPerPage")})
            elif isinstance(item, dict) and item.get("url"):
                targets.append({"url": item["url"], "maxReels": item.get("maxReels", settings.get("maxReelsPerPage"))})
    elif isinstance(inputs, dict) and "pages" in inputs:
        for p in inputs["pages"]:
            if isinstance(p, str):
                targets.append({"url": p, "maxReels": settings.get("maxReelsPerPage")})
            elif isinstance(p, dict) and p.get("url"):
                targets.append({"url": p["url"], "maxReels": p.get("maxReels", settings.get("maxReelsPerPage"))})

    # Validate and scrape
    all_records: List[Dict[str, Any]] = []
    for target in targets:
        url = target["url"]
        if not validate_page_url(url):
            logging.warning("Skipping invalid URL: %s", url)
            continue
        page_records = scrape_page(session, url, target.get("maxReels"))
        all_records.extend(page_records)

    # Export
    out_cfg = settings["output"]  # type: ignore[assignment]
    exporter = Exporter()
    out_path = out_cfg.get("path", "data/output.json")
    fmt = out_cfg.get("format", "json").lower()
    logging.info("Exporting %d records to %s (%s)", len(all_records), out_path, fmt)

    if fmt == "json":
        exporter.to_json(all_records, out_path)
    elif fmt == "csv":
        exporter.to_csv(all_records, out_path)
    elif fmt == "excel":
        exporter.to_excel(all_records, out_path)
    elif fmt == "html":
        exporter.to_html(all_records, out_path, title="Facebook Reel Scraper Results")
    else:
        logging.warning("Unknown format '%s', defaulting to JSON", fmt)
        exporter.to_json(all_records, out_path)

    # Also persist a sample to data/output_sample.json for convenience when running without network
    sample_path = os.path.join("data", "output_sample.json")
    try:
        if not os.path.exists(sample_path):
            save_json(sample_path, all_records[:2] if all_records else [])
    except Exception:
        pass

    print(f"✅ Done. Exported {len(all_records)} records to: {out_path}")
    return 0

def main() -> None:
    parser = argparse.ArgumentParser(description="Facebook Reel Scraper (public pages only)")
    parser.add_argument("--input", "-i", default="data/sample_input.json", help="Path to input JSON file")
    parser.add_argument("--settings", "-s", default=None, help="Path to settings JSON file (optional)")
    parser.add_argument("--output", "-o", default=None, help="Override output file path (optional)")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv)")
    args = parser.parse_args()

    code = run(args.input, args.settings, args.output, args.verbose)
    sys.exit(code)

if __name__ == "__main__":
    main()