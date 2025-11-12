from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from bs4 import BeautifulSoup

META_KEYS = {
    "og:title": "caption",
    "og:description": "caption",
    "twitter:title": "caption",
    "twitter:description": "caption",
    "og:image": "img",
    "og:image:url": "img",
    "og:url": "url",
}

REEL_ID_RE = re.compile(r"/reel/(\d+)", re.IGNORECASE)
PLAY_COUNT_RE = re.compile(r'(?i)\b([\d,.]+)\s*(plays|views)\b')
LIKES_RE = re.compile(r'(?i)\b([\d,.]+)\s*(likes?)\b')
COMMENTS_RE = re.compile(r'(?i)\b([\d,.]+)\s*(comments?)\b')
SHARES_RE = re.compile(r'(?i)\b([\d,.]+)\s*(shares?)\b')
DURATION_RE = re.compile(r'(?i)\b([\d.,]+)\s*(s|sec|seconds)\b')
DATETIME_RE = re.compile(r'(?i)\b(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2})?))?')

def _num(s: str) -> str:
    s = s.replace(",", "").strip()
    # Handle compact forms like 1.2K or 3M
    m = re.match(r"^([0-9]*\.?[0-9]+)\s*([KkMmBb])?$", s)
    if not m:
        return s
    n = float(m.group(1))
    suf = (m.group(2) or "").lower()
    mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(suf, 1)
    return str(int(n * mult))

def _extract_meta(soup: BeautifulSoup, out: Dict[str, Any]) -> None:
    for tag in soup.find_all("meta"):
        prop = tag.get("property") or tag.get("name")
        if not prop:
            continue
        prop = prop.strip()
        if prop in META_KEYS and tag.get("content"):
            key = META_KEYS[prop]
            out.setdefault(key, tag["content"].strip())

def _extract_structured_data(soup: BeautifulSoup, out: Dict[str, Any]) -> None:
    # Parse JSON-LD if present
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            _json_to_out(data, out)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    _json_to_out(item, out)

def _json_to_out(data: Dict[str, Any], out: Dict[str, Any]) -> None:
    # Best-effort picks from common schemas
    if "uploadDate" in data:
        out.setdefault("reelDateTime", data["uploadDate"])
    if "datePublished" in data:
        out.setdefault("reelDate", data["datePublished"])
    if "thumbnailUrl" in data:
        if isinstance(data["thumbnailUrl"], list) and data["thumbnailUrl"]:
            out.setdefault("img", data["thumbnailUrl"][0])
        elif isinstance(data["thumbnailUrl"], str):
            out.setdefault("img", data["thumbnailUrl"])
    if "name" in data:
        out.setdefault("caption", data["name"])
    if "headline" in data:
        out.setdefault("caption", data["headline"])
    if "author" in data and isinstance(data["author"], dict):
        out.setdefault("ownerUsername", data["author"].get("name"))

def _scan_text_for_metrics(text: str, out: Dict[str, Any]) -> None:
    if "playCount" not in out:
        m = PLAY_COUNT_RE.search(text)
        if m:
            out["playCount"] = _num(m.group(1))
    if "likesCount" not in out:
        m = LIKES_RE.search(text)
        if m:
            out["likesCount"] = _num(m.group(1))
    if "commentsCount" not in out:
        m = COMMENTS_RE.search(text)
        if m:
            out["commentsCount"] = _num(m.group(1))
    if "sharesCount" not in out:
        m = SHARES_RE.search(text)
        if m:
            out["sharesCount"] = _num(m.group(1))
    if "reelDuration" not in out:
        m = DURATION_RE.search(text)
        if m:
            out["reelDuration"] = m.group(1)

def _extract_owner_from_path(url: str) -> Optional[str]:
    # Try to infer owner/page name from path segments
    # Examples: https://www.facebook.com/Formula1/reel/123 ... -> owner = Formula1
    m = REEL_ID_RE.search(url)
    if not m:
        return None
    try:
        path = url.split("facebook.com/", 1)[1]
        parts = [p for p in path.split("/") if p]
        # Find the segment before 'reel'
        if "reel" in parts:
            idx = parts.index("reel")
            if idx > 0:
                return parts[idx - 1]
    except Exception:
        return None
    return None

def parse_reel_html(html: str, url: str) -> Dict[str, Any]:
    """
    Best-effort parser that extracts reel metrics and metadata from a single reel HTML page.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: Dict[str, Any] = {
        "url": url,
    }

    # Reel ID
    m = REEL_ID_RE.search(url)
    if m:
        out["reelId"] = m.group(1)

    # Owner username inferred from URL path if not otherwise available
    owner = _extract_owner_from_path(url)
    if owner:
        out["ownerUsername"] = owner

    _extract_meta(soup, out)
    _extract_structured_data(soup, out)

    # Scan raw text for metrics
    body_text = soup.get_text(separator=" ", strip=True)
    _scan_text_for_metrics(body_text, out)

    # Attempt to read publication datetime from data-ft or similar attributes
    # (Facebook often embeds timestamps in JSON in script tags)
    for script in soup.find_all("script"):
        if not script.string:
            continue
        text = script.string
        # search for ISO date
        m = DATETIME_RE.search(text)
        if m:
            if m.group(2):
                out.setdefault("reelDateTime", f"{m.group(1)} {m.group(2)}")
            else:
                out.setdefault("reelDate", m.group(1))
        # opportunistic counters
        _scan_text_for_metrics(text, out)

        # Attempt owner from JSON blobs
        if "page_name" in text and "ownerUsername" not in out:
            m2 = re.search(r'"page_name"\s*:\s*"([^"]+)"', text)
            if m2:
                out["ownerUsername"] = m2.group(1)

        if "music" not in out:
            m3 = re.search(r'"music[^"]*"\s*:\s*"([^"]+)"', text)
            if m3:
                out["music"] = m3.group(1)

    # Ensure keys exist for downstream schema
    out.setdefault("caption", None)
    out.setdefault("playCount", None)
    out.setdefault("likesCount", None)
    out.setdefault("commentsCount", None)
    out.setdefault("sharesCount", None)
    out.setdefault("reelDuration", None)
    out.setdefault("music", None)
    out.setdefault("reelDate", None)
    out.setdefault("reelDateTime", None)
    out.setdefault("img", None)

    return out