# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Crypto news scanner: RSS + optional CryptoPanic with sentiment scoring.

Part of the Crucible Sentinel plugin.
Sources: CoinDesk, CoinTelegraph, Decrypt.co, CryptoSlate RSS (+ CryptoPanic with key)
"""

from __future__ import annotations

import argparse
import difflib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Protocols (inline — mirrors lib/protocols.py)
# ---------------------------------------------------------------------------


@dataclass
class SignalOutput:
    signal: str
    confidence: int
    reasoning: str
    data: dict[str, Any] = field(default_factory=dict)
    analytics: dict[str, Any] = field(default_factory=dict)
    schema: str = "signal/v1"

    def emit(self) -> None:
        print(json.dumps(asdict(self), ensure_ascii=False))

    def summary(self, text: str) -> None:
        print(text, file=sys.stderr)


@dataclass
class ErrorOutput:
    error: str
    details: str = ""
    schema: str = "error/v1"

    def emit(self) -> None:
        print(json.dumps(asdict(self), ensure_ascii=False))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
]

CACHE_DIR = Path.home() / ".cache" / "crucible" / "news-scanner"
CACHE_FILE = CACHE_DIR / "articles.json"
CACHE_TTL = 15 * 60  # 15 minutes
STALE_WINDOW = 2 * 3600  # 2 hours
FETCH_TIMEOUT = 10

# ---------------------------------------------------------------------------
# Fetch — RSS
# ---------------------------------------------------------------------------


def fetch_rss(source_name: str, feed_url: str) -> list[dict]:
    """Fetch and parse an RSS feed. Returns list of article dicts."""
    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "news-scanner/0.2"})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            xml_data = resp.read()
    except Exception as e:
        print(f"  RSS {source_name}: {e}", file=sys.stderr)
        return []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        print(f"  RSS {source_name} parse error: {e}", file=sys.stderr)
        return []

    articles: list[dict] = []
    items = root.findall(".//item")
    if not items:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//atom:entry", ns)

    for item in items:
        title = _text(item, "title")
        link = _text(item, "link") or _attr(item, "link", "href")
        guid = _text(item, "guid")
        pub_str = _text(item, "pubDate") or _text(item, "{http://www.w3.org/2005/Atom}updated")
        description = _text(item, "description")

        dt = _parse_datetime(pub_str) if pub_str else None

        articles.append({
            "title": title,
            "source": source_name,
            "link": link,
            "guid": guid,
            "published_at": dt.isoformat() if dt else None,
            "description": description,
            "_dt": dt,
            "_source_type": "rss",
        })
    return articles


def _text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _attr(el: ET.Element, tag: str, attr: str) -> str:
    child = el.find(tag)
    return (child.get(attr, "") or "").strip() if child is not None else ""


def _parse_datetime(dt_str: str) -> datetime | None:
    """Parse RSS datetime to UTC-aware datetime."""
    # Try email.utils first (handles RFC 2822)
    try:
        dt = parsedate_to_datetime(dt_str.strip())
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        pass
    # Try ISO formats
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(dt_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Fetch — CryptoPanic
# ---------------------------------------------------------------------------


def fetch_cryptopanic() -> list[dict]:
    """Fetch from CryptoPanic API. Requires CRYPTOPANIC_API_KEY env var."""
    api_key = os.environ.get("CRYPTOPANIC_API_KEY", "")
    if not api_key:
        return []

    url = f"https://cryptopanic.com/api/free/v1/posts/?auth_token={api_key}&kind=news&public=true"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "news-scanner/0.2"})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"  CryptoPanic: {e}", file=sys.stderr)
        return []

    articles: list[dict] = []
    for post in data.get("results", []):
        coins_raw = post.get("currencies") or []
        coins = [c["code"] for c in coins_raw if c.get("code")]
        pub = post.get("published_at", "")
        dt = _parse_datetime(pub) if pub else None
        votes = post.get("votes") or {}

        articles.append({
            "title": post.get("title", ""),
            "source": post.get("source", {}).get("title", "CryptoPanic"),
            "link": post.get("url", ""),
            "guid": None,
            "published_at": dt.isoformat() if dt else None,
            "description": "",
            "coins": coins,
            "votes": {
                "positive": votes.get("positive", 0),
                "negative": votes.get("negative", 0),
                "important": votes.get("important", 0),
            },
            "_dt": dt,
            "_source_type": "cryptopanic",
        })
    return articles


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _save_cache(data: list[dict], path: Path = CACHE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    clean = [{k: v for k, v in a.items() if not k.startswith("_")} for a in data]
    payload = {"timestamp": time.time(), "data": clean}
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    tmp.rename(path)


def _load_cache(path: Path = CACHE_FILE) -> tuple[list[dict] | None, float]:
    try:
        payload = json.loads(path.read_text())
        return payload["data"], payload["timestamp"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return None, 0


# ---------------------------------------------------------------------------
# Deduplication (3-stage, adaptive threshold)
# ---------------------------------------------------------------------------

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term",
    "utm_content", "fbclid", "gclid", "ref",
}


def canonical_url(url: str) -> str:
    """Normalize URL: lowercase host, strip tracking params."""
    if not url:
        return ""
    p = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if k.lower() not in _TRACKING_PARAMS]
    return urllib.parse.urlunsplit((
        p.scheme.lower(), p.netloc.lower(), p.path,
        urllib.parse.urlencode(q), "",
    ))


def _dedup_threshold(title: str) -> float:
    """Adaptive threshold: stricter for short titles, looser for long."""
    return 0.87 if len(title) > 60 else 0.92


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.lower().strip())


def deduplicate(articles: list[dict]) -> list[dict]:
    """3-stage dedup: canonical URL -> guid -> adaptive fuzzy title."""
    seen_urls: set[str] = set()
    seen_guids: set[str] = set()
    seen_titles: list[str] = []
    result: list[dict] = []

    for a in articles:
        # Stage 1: URL
        curl = canonical_url(a.get("link", ""))
        if curl and curl in seen_urls:
            continue

        # Stage 2: GUID
        guid = a.get("guid") or ""
        if guid and guid in seen_guids:
            continue

        # Stage 3: Fuzzy title (adaptive threshold)
        norm_title = _normalize_title(a.get("title", ""))
        if norm_title:
            threshold = _dedup_threshold(norm_title)
            if any(
                difflib.SequenceMatcher(None, norm_title, t).ratio() >= threshold
                for t in seen_titles
            ):
                continue

        if curl:
            seen_urls.add(curl)
        if guid:
            seen_guids.add(guid)
        if norm_title:
            seen_titles.append(norm_title)
        result.append(a)

    return result


# ---------------------------------------------------------------------------
# Coin Detection (30 coins, regex word-boundary)
# ---------------------------------------------------------------------------

# (regex_pattern, symbol) — case-insensitive for \b patterns, case-sensitive for symbol-only
COIN_PATTERNS: list[tuple[str, str, int]] = [
    # Bitcoin
    (r"\bbitcoin\b", "BTC", re.IGNORECASE),
    (r"(?<![A-Za-z])BTC(?![A-Za-z])", "BTC", 0),
    # Ethereum
    (r"\bethereum\b", "ETH", re.IGNORECASE),
    (r"\bether\b", "ETH", re.IGNORECASE),
    (r"(?<![A-Za-z])ETH(?![A-Za-z])", "ETH", 0),
    # Solana — symbol only with $ prefix or full name
    (r"\bsolana\b", "SOL", re.IGNORECASE),
    (r"(?<![A-Za-z])\$SOL(?![A-Za-z])", "SOL", 0),
    # XRP
    (r"\bripple\b", "XRP", re.IGNORECASE),
    (r"(?<![A-Za-z])XRP(?![A-Za-z])", "XRP", 0),
    # BNB
    (r"(?<![A-Za-z])BNB(?![A-Za-z])", "BNB", 0),
    # Cardano
    (r"\bcardano\b", "ADA", re.IGNORECASE),
    (r"(?<![A-Za-z])ADA(?![A-Za-z])", "ADA", 0),
    # Dogecoin
    (r"\bdogecoin\b", "DOGE", re.IGNORECASE),
    (r"(?<![A-Za-z])DOGE(?![A-Za-z])", "DOGE", 0),
    # Avalanche
    (r"\bavalanche\b", "AVAX", re.IGNORECASE),
    (r"(?<![A-Za-z])AVAX(?![A-Za-z])", "AVAX", 0),
    # Polygon
    (r"\bpolygon\b", "MATIC", re.IGNORECASE),
    (r"(?<![A-Za-z])MATIC(?![A-Za-z])", "MATIC", 0),
    # Polkadot — only full name (DOT too ambiguous)
    (r"\bpolkadot\b", "DOT", re.IGNORECASE),
    # Chainlink
    (r"\bchainlink\b", "LINK", re.IGNORECASE),
    (r"(?<![A-Za-z])LINK(?![A-Za-z])", "LINK", 0),
    # Litecoin
    (r"\blitecoin\b", "LTC", re.IGNORECASE),
    (r"(?<![A-Za-z])LTC(?![A-Za-z])", "LTC", 0),
    # TRON
    (r"\btron\b", "TRX", re.IGNORECASE),
    (r"(?<![A-Za-z])TRX(?![A-Za-z])", "TRX", 0),
    # SUI
    (r"(?<![A-Za-z])SUI(?![A-Za-z])", "SUI", 0),
    # PEPE
    (r"(?<![A-Za-z])PEPE(?![A-Za-z])", "PEPE", 0),
    # Arbitrum
    (r"\barbitrum\b", "ARB", re.IGNORECASE),
    (r"(?<![A-Za-z])ARB(?![A-Za-z])", "ARB", 0),
    # Optimism — only full name (OP too ambiguous)
    (r"\boptimism\b", "OP", re.IGNORECASE),
    # Uniswap
    (r"\buniswap\b", "UNI", re.IGNORECASE),
    (r"(?<![A-Za-z])UNI(?![A-Za-z])", "UNI", 0),
    # AAVE
    (r"\baave\b", "AAVE", re.IGNORECASE),
    # NEAR
    (r"\bnear protocol\b", "NEAR", re.IGNORECASE),
    (r"(?<![A-Za-z])NEAR(?![A-Za-z])", "NEAR", 0),
    # Aptos
    (r"\baptos\b", "APT", re.IGNORECASE),
    (r"(?<![A-Za-z])APT(?![A-Za-z])", "APT", 0),
    # TON
    (r"\btoncoin\b", "TON", re.IGNORECASE),
    (r"(?<![A-Za-z])TON(?![A-Za-z])", "TON", 0),
    # Cosmos
    (r"\bcosmos\b", "ATOM", re.IGNORECASE),
    (r"(?<![A-Za-z])ATOM(?![A-Za-z])", "ATOM", 0),
    # Filecoin
    (r"\bfilecoin\b", "FIL", re.IGNORECASE),
    (r"(?<![A-Za-z])FIL(?![A-Za-z])", "FIL", 0),
    # Render
    (r"\brender\b", "RNDR", re.IGNORECASE),
    (r"(?<![A-Za-z])RNDR(?![A-Za-z])", "RNDR", 0),
    # Injective
    (r"\binjective\b", "INJ", re.IGNORECASE),
    (r"(?<![A-Za-z])INJ(?![A-Za-z])", "INJ", 0),
    # Stacks
    (r"\bstacks\b", "STX", re.IGNORECASE),
    (r"(?<![A-Za-z])STX(?![A-Za-z])", "STX", 0),
]

# Pre-compile all patterns
_COIN_RE = [(re.compile(pat, flags), sym) for pat, sym, flags in COIN_PATTERNS]


def detect_coins(text: str) -> list[str]:
    """Detect coin symbols mentioned in text."""
    found: set[str] = set()
    for pattern, symbol in _COIN_RE:
        if pattern.search(text):
            found.add(symbol)
    return sorted(found)


# ---------------------------------------------------------------------------
# Sentiment (scoped negation + boosters)
# ---------------------------------------------------------------------------

POSITIVE_WORDS = frozenset([
    "rally", "surge", "bullish", "approval", "launch", "soar", "gain",
    "partnership", "breakthrough", "adoption",
])
NEGATIVE_WORDS = frozenset([
    "crash", "hack", "ban", "dump", "bearish", "plunge", "exploit",
    "lawsuit", "delisting", "fraud",
])
NEGATION_WORDS = frozenset(["not", "no", "never", "fails", "unlikely", "denies", "without"])
BOOSTER_WORDS = frozenset(["extreme", "massive", "major", "historic", "record"])
CLAUSE_BOUNDARIES = frozenset(["but", "however", "although", "yet", "despite"])


def _stem(word: str) -> str:
    """Simple suffix stripping for common English inflections."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[: -len(suffix)]
    return word


def score_article_sentiment(text: str) -> float:
    """Score a single article text. Positive=bullish, negative=bearish, 0=neutral."""
    tokens = text.lower().split()
    score = 0.0
    negated = False
    boost_next = False

    for token in tokens:
        clean = re.sub(r"[^a-z]", "", token)
        has_boundary_punct = "," in token or "." in token or ";" in token

        # Check clause boundary words
        if clean in CLAUSE_BOUNDARIES:
            negated = False
            boost_next = False
            continue

        # Check negation
        if clean in NEGATION_WORDS:
            negated = True
            continue

        # Check booster (carry forward to next sentiment word)
        if clean in BOOSTER_WORDS:
            boost_next = True
            continue

        # Score sentiment words (check both raw and stemmed forms)
        stemmed = _stem(clean)
        multiplier = 1.5 if boost_next else 1.0

        if clean in POSITIVE_WORDS or stemmed in POSITIVE_WORDS:
            score += (-1.0 if negated else 1.0) * multiplier
            negated = False
            boost_next = False
        elif clean in NEGATIVE_WORDS or stemmed in NEGATIVE_WORDS:
            score += (1.0 if negated else -1.0) * multiplier
            negated = False
            boost_next = False

        # Reset negation after clause boundary punctuation (AFTER scoring)
        if has_boundary_punct:
            negated = False

    return score


def compute_aggregate_sentiment(articles: list[dict]) -> dict:
    """Aggregate per-article sentiment into overall signal."""
    pos = neg = neut = 0
    for a in articles:
        s = a.get("_sentiment", 0)
        if s > 0:
            pos += 1
        elif s < 0:
            neg += 1
        else:
            neut += 1

    if pos > neg:
        signal = "bullish"
    elif neg > pos:
        signal = "bearish"
    else:
        signal = "neutral"

    return {"positive": pos, "negative": neg, "neutral": neut, "signal": signal}


# ---------------------------------------------------------------------------
# Time Window
# ---------------------------------------------------------------------------

_WINDOW_RE = re.compile(r"^(\d+)(m|h|d|w)$")


def parse_window(window: str) -> timedelta:
    """Parse window string like '6h', '7d', '30m' to timedelta."""
    m = _WINDOW_RE.match(window.strip().lower())
    if not m:
        raise ValueError(f"Invalid window format: '{window}'. Use e.g. 6h, 24h, 7d, 30m")
    n, unit = int(m.group(1)), m.group(2)
    if unit == "m":
        return timedelta(minutes=n)
    if unit == "h":
        return timedelta(hours=n)
    if unit == "d":
        return timedelta(days=n)
    if unit == "w":
        return timedelta(weeks=n)
    raise ValueError(f"Unknown unit: {unit}")


# ---------------------------------------------------------------------------
# Confidence Scoring
# ---------------------------------------------------------------------------


def compute_confidence(
    n_articles: int,
    n_positive: int,
    n_negative: int,
    n_neutral: int,
    n_sources: int,
    data_fresh: bool,
    cp_votes: dict[str, int] | None = None,
) -> int:
    """Weighted confidence: agreement + coverage + diversity + quality (+ social if CP)."""
    directional = n_positive + n_negative
    agreement = abs(n_positive - n_negative) / max(1, directional) if directional > 0 else 0.0
    coverage = min(1.0, n_articles / 10)
    diversity = min(1.0, n_sources / 4)
    quality = 1.0 if data_fresh else 0.5

    # Weight distribution
    w_agreement, w_coverage, w_diversity, w_quality = 0.35, 0.25, 0.25, 0.15

    # If CryptoPanic votes available with enough data, inject social signal
    if cp_votes:
        total_votes = cp_votes.get("positive", 0) + cp_votes.get("negative", 0)
        if total_votes >= 5:
            social = cp_votes["positive"] / max(1, total_votes)
            w_quality = 0.05
            raw = (w_agreement * agreement + w_coverage * coverage
                   + w_diversity * diversity + w_quality * quality + 0.10 * social)
        else:
            raw = (w_agreement * agreement + w_coverage * coverage
                   + w_diversity * diversity + w_quality * quality)
    else:
        raw = (w_agreement * agreement + w_coverage * coverage
               + w_diversity * diversity + w_quality * quality)

    confidence = round(15 + 85 * raw)

    # Force low confidence if too few directional articles
    if directional < 2:
        confidence = min(confidence, 35)

    return max(0, min(100, confidence))


# ---------------------------------------------------------------------------
# Alert Keywords
# ---------------------------------------------------------------------------

DEFAULT_ALERTS = ["sec", "etf", "hack", "ban", "approval", "regulation",
                  "lawsuit", "exploit", "delisting"]


def detect_alerts(text: str, keywords: list[str] | None = None) -> list[str]:
    """Detect alert keywords in text."""
    check = keywords if keywords else DEFAULT_ALERTS
    lower = text.lower()
    return [kw for kw in check if kw in lower]


# ---------------------------------------------------------------------------
# CLI + Main
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Crypto news scanner — sentiment signal",
        prog="news-scanner",
    )
    p.add_argument("--window", default="24h", help="Time window (e.g. 6h, 24h, 7d, 30m)")
    p.add_argument("--coins", default="", help="Filter by coin symbols (comma-separated)")
    p.add_argument("--keywords", default="", help="Alert keywords (comma-separated)")
    p.add_argument("--sources", choices=["all", "rss", "cryptopanic"], default="all",
                   help="Source selection")
    return p


def main() -> None:
    args = build_parser().parse_args()

    try:
        window_td = parse_window(args.window)
    except ValueError as e:
        ErrorOutput(error=str(e)).emit()
        return

    cutoff = datetime.now(timezone.utc) - window_td
    coin_filter = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    alert_keywords = [k.strip().lower() for k in args.keywords.split(",") if k.strip()] or None

    # Fetch from sources
    all_articles: list[dict] = []
    sources_used: list[str] = []
    data_fresh = True

    if args.sources in ("all", "rss"):
        for name, url in RSS_FEEDS:
            fetched = fetch_rss(name, url)
            if fetched:
                all_articles.extend(fetched)
                sources_used.append(name)

    if args.sources in ("all", "cryptopanic"):
        cp_articles = fetch_cryptopanic()
        if cp_articles:
            all_articles.extend(cp_articles)
            sources_used.append("CryptoPanic")

    if not all_articles:
        cached, ts = _load_cache()
        if cached and (time.time() - ts) < STALE_WINDOW:
            all_articles = cached
            data_fresh = False
        else:
            ErrorOutput(error="No articles fetched and no valid cache").emit()
            return

    # Dedup
    before_dedup = len(all_articles)
    articles = deduplicate(all_articles)
    duplicate_rate = round(1 - len(articles) / max(1, before_dedup), 2)

    # Filter by time window
    articles = [a for a in articles if a.get("_dt") is None or a["_dt"] >= cutoff]

    # Detect coins per article (if not already set by CryptoPanic)
    for a in articles:
        if not a.get("coins"):
            a["coins"] = detect_coins(
                a.get("title", "") + " " + a.get("description", "")
            )

    # Filter by coin
    if coin_filter:
        articles = [a for a in articles if any(c in a.get("coins", []) for c in coin_filter)]

    # Score sentiment per article
    for a in articles:
        a["_sentiment"] = score_article_sentiment(
            a.get("title", "") + " " + a.get("description", "")
        )

    # Detect alert keywords per article
    all_alerts: set[str] = set()
    for a in articles:
        text = a.get("title", "") + " " + a.get("description", "")
        hits = detect_alerts(text, alert_keywords)
        a["alert_keywords"] = hits
        all_alerts.update(hits)

    # Aggregate sentiment
    sentiment = compute_aggregate_sentiment(articles)

    # Trending coins
    coin_counts: dict[str, int] = {}
    for a in articles:
        for c in a.get("coins", []):
            coin_counts[c] = coin_counts.get(c, 0) + 1
    trending = sorted(coin_counts, key=lambda c: coin_counts[c], reverse=True)[:10]

    # Aggregate CryptoPanic votes if available
    cp_votes: dict[str, int] | None = None
    cp_articles = [a for a in articles if a.get("_source_type") == "cryptopanic" and a.get("votes")]
    if cp_articles:
        cp_votes = {"positive": 0, "negative": 0}
        for a in cp_articles:
            v = a["votes"]
            cp_votes["positive"] += v.get("positive", 0)
            cp_votes["negative"] += v.get("negative", 0)

    # Confidence
    n_sources = len(set(a.get("source", "") for a in articles))
    confidence = compute_confidence(
        n_articles=len(articles),
        n_positive=sentiment["positive"],
        n_negative=sentiment["negative"],
        n_neutral=sentiment["neutral"],
        n_sources=n_sources,
        data_fresh=data_fresh,
        cp_votes=cp_votes,
    )

    # Cache successful fresh fetch
    if data_fresh:
        _save_cache(articles)

    # Build output articles (strip internal fields, sort by date desc)
    output_articles = []
    for a in sorted(
        articles,
        key=lambda x: x.get("_dt") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    ):
        output_articles.append({k: v for k, v in a.items() if not k.startswith("_")})

    signal = sentiment["signal"]
    directional = sentiment["positive"] + sentiment["negative"]
    agreement_val = (
        abs(sentiment["positive"] - sentiment["negative"]) / max(1, directional)
        if directional > 0
        else 0.0
    )

    reasoning = (
        f"News: {sentiment['positive']} bullish / {sentiment['negative']} bearish / "
        f"{sentiment['neutral']} neutral across {len(articles)} articles "
        f"from {len(sources_used)} sources"
    )
    if not data_fresh:
        reasoning += " [STALE — using cache]"

    out = SignalOutput(
        signal=signal,
        confidence=confidence,
        reasoning=reasoning,
        data={
            "count": len(output_articles),
            "articles": output_articles[:20],
            "trending_coins": trending,
            "alert_keywords": sorted(all_alerts),
            "sentiment": sentiment,
            "sources_used": sources_used,
            "data_fresh": data_fresh,
        },
        analytics={
            "confidence_components": {
                "agreement": round(agreement_val, 2),
                "coverage": round(min(1.0, len(articles) / 10), 2),
                "source_diversity": round(min(1.0, n_sources / 4), 2),
                "data_quality": 1.0 if data_fresh else 0.5,
            },
            "effective_sample_size": len(articles),
            "duplicate_rate": duplicate_rate,
        },
    )

    out.summary(
        f"  News Scanner: {len(articles)} articles from {', '.join(sources_used)}\n"
        f"  Sentiment: {signal} | Agreement: {agreement_val:.0%} | Confidence: {confidence}/100\n"
        f"  Trending: {', '.join(trending[:5]) or 'none'}\n"
        f"  Alerts: {', '.join(sorted(all_alerts)) or 'none'}"
    )
    out.emit()


if __name__ == "__main__":
    main()
