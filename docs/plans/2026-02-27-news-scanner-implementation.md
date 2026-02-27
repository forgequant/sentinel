# news-scanner v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the news-scanner skill for sentinel plugin — a robust, stdlib-only Python script that aggregates crypto news from RSS feeds (+ optional CryptoPanic), with 3-stage deduplication, hybrid sentiment scoring, regex-based coin detection, and weighted confidence.

**Architecture:** Single file `news_scanner.py` with logical sections: fetch → cache → dedup → coins → sentiment → scoring → cli. Uses SignalOutput v1 inline. All stdlib — no external dependencies. PEP 723 inline metadata for `uv run`.

**Tech Stack:** Python 3.12+, stdlib only (argparse, json, urllib.request, xml.etree.ElementTree, re, difflib, email.utils, dataclasses, pathlib)

**Design:** See `docs/plans/2026-02-27-news-scanner-design.md`

---

### Task 1: Test infrastructure + RSS fetch

**Files:**
- Create: `skills/news-scanner/scripts/news_scanner.py`
- Create: `tests/test_news_scanner.py`

**Step 1: Write test file with RSS fetch tests**

```python
# tests/test_news_scanner.py
"""Tests for news_scanner skill."""
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "news-scanner" / "scripts"))

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>TestFeed</title>
<item>
  <title>Bitcoin surges past $100k on ETF approval</title>
  <link>https://example.com/btc-surges</link>
  <guid isPermaLink="false">abc-123</guid>
  <pubDate>Thu, 27 Feb 2026 10:00:00 +0000</pubDate>
  <description>Bitcoin has surged past the $100k mark.</description>
</item>
<item>
  <title>Solana network faces outage concerns</title>
  <link>https://example.com/sol-outage?utm_source=rss&amp;utm_medium=feed</link>
  <guid isPermaLink="false">def-456</guid>
  <pubDate>Thu, 27 Feb 2026 08:00:00 +0000</pubDate>
  <description>The Solana network experienced issues.</description>
</item>
</channel>
</rss>"""


class TestFetchRSS:
    @patch("urllib.request.urlopen")
    def test_parse_rss_items(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_RSS.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from news_scanner import fetch_rss
        articles = fetch_rss("TestFeed", "https://example.com/rss")
        assert len(articles) == 2
        assert articles[0]["title"] == "Bitcoin surges past $100k on ETF approval"
        assert articles[0]["source"] == "TestFeed"
        assert articles[0]["guid"] == "abc-123"

    @patch("urllib.request.urlopen")
    def test_parse_rss_datetime(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_RSS.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from news_scanner import fetch_rss
        articles = fetch_rss("TestFeed", "https://example.com/rss")
        assert articles[0]["published_at"] is not None
        # Should be a valid ISO timestamp
        dt = datetime.fromisoformat(articles[0]["published_at"])
        assert dt.tzinfo is not None

    @patch("urllib.request.urlopen")
    def test_fetch_rss_failure_returns_empty(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Network error")

        from news_scanner import fetch_rss
        articles = fetch_rss("TestFeed", "https://example.com/rss")
        assert articles == []
```

**Step 2: Run tests — expect FAIL (module not found)**

**Step 3: Write minimal news_scanner.py with RSS fetch**

```python
# skills/news-scanner/scripts/news_scanner.py
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
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

# -- Protocols (inline) --

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


# -- Constants --

RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
]

CACHE_DIR = Path.home() / ".cache" / "crucible" / "news-scanner"
CACHE_TTL = 15 * 60  # 15 minutes
STALE_WINDOW = 2 * 3600  # 2 hours
FETCH_TIMEOUT = 10


# -- Fetch --

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

    articles = []
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
```

**Step 4: Run tests — expect 3 PASS**

**Step 5: Commit**
```bash
git add skills/news-scanner/scripts/news_scanner.py tests/test_news_scanner.py
git commit -m "feat(news-scanner): RSS fetch with datetime parsing"
```

---

### Task 2: CryptoPanic fetch + cache

**Step 1: Write CryptoPanic + cache tests**

```python
SAMPLE_CP_RESPONSE = json.dumps({
    "results": [
        {
            "title": "Bitcoin ETF sees record inflows",
            "published_at": "2026-02-27T09:00:00Z",
            "url": "https://cryptopanic.com/news/123",
            "source": {"title": "CoinDesk"},
            "currencies": [{"code": "BTC"}],
            "votes": {"positive": 15, "negative": 3, "important": 5},
        },
        {
            "title": "Ethereum faces selling pressure",
            "published_at": "2026-02-27T07:00:00Z",
            "url": "https://cryptopanic.com/news/456",
            "source": {"title": "Decrypt"},
            "currencies": [{"code": "ETH"}],
            "votes": {"positive": 2, "negative": 10, "important": 3},
        },
    ]
}).encode()


class TestFetchCryptoPanic:
    @patch.dict(os.environ, {"CRYPTOPANIC_API_KEY": "test-key"})
    @patch("urllib.request.urlopen")
    def test_fetch_with_key_parses_articles(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_CP_RESPONSE
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from news_scanner import fetch_cryptopanic
        articles = fetch_cryptopanic()
        assert len(articles) == 2
        assert articles[0]["coins"] == ["BTC"]
        assert articles[0]["votes"]["positive"] == 15

    @patch.dict(os.environ, {}, clear=True)
    def test_fetch_without_key_returns_empty(self):
        from news_scanner import fetch_cryptopanic
        articles = fetch_cryptopanic()
        assert articles == []


class TestCache:
    def test_save_and_load_cache(self, tmp_path):
        from news_scanner import _save_cache, _load_cache
        cache_file = tmp_path / "test.json"
        data = [{"title": "Test"}]
        _save_cache(data, cache_file)
        loaded, ts = _load_cache(cache_file)
        assert loaded == data
        assert ts > 0

    def test_load_missing_returns_none(self, tmp_path):
        from news_scanner import _load_cache
        assert _load_cache(tmp_path / "nope.json") == (None, 0)
```

**Step 2: Run — expect FAIL**

**Step 3: Implement CryptoPanic fetch + cache**

```python
# CryptoPanic fetch
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

    articles = []
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


# Cache (same pattern as feargreed)
def _save_cache(data: list[dict], path: Path = CACHE_DIR / "articles.json") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    # Strip non-serializable fields
    clean = [{k: v for k, v in a.items() if not k.startswith("_")} for a in data]
    payload = {"timestamp": time.time(), "data": clean}
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    tmp.rename(path)


def _load_cache(path: Path = CACHE_DIR / "articles.json") -> tuple[list[dict] | None, float]:
    try:
        payload = json.loads(path.read_text())
        return payload["data"], payload["timestamp"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return None, 0
```

**Step 4: Run — expect PASS**

**Step 5: Commit**
```bash
git add -A && git commit -m "feat(news-scanner): CryptoPanic fetch + article cache"
```

---

### Task 3: Deduplication (3-stage)

**Step 1: Write dedup tests**

```python
class TestDedup:
    def test_url_canonical_strips_utm(self):
        from news_scanner import canonical_url
        url = "https://example.com/article?utm_source=rss&utm_medium=feed&id=123"
        assert canonical_url(url) == "https://example.com/article?id=123"

    def test_url_canonical_normalizes(self):
        from news_scanner import canonical_url
        assert canonical_url("HTTP://Example.COM/Path/") == "http://example.com/Path/"

    def test_dedup_by_url(self):
        from news_scanner import deduplicate
        articles = [
            {"title": "Bitcoin surges", "link": "https://ex.com/a?utm_source=rss", "guid": None, "_dt": None},
            {"title": "Bitcoin surges!", "link": "https://ex.com/a?utm_medium=x", "guid": None, "_dt": None},
        ]
        result = deduplicate(articles)
        assert len(result) == 1

    def test_dedup_by_guid(self):
        from news_scanner import deduplicate
        articles = [
            {"title": "Article A", "link": "https://a.com/1", "guid": "guid-1", "_dt": None},
            {"title": "Article B", "link": "https://b.com/2", "guid": "guid-1", "_dt": None},
        ]
        result = deduplicate(articles)
        assert len(result) == 1

    def test_dedup_by_fuzzy_title(self):
        from news_scanner import deduplicate
        articles = [
            {"title": "Bitcoin ETF Approval Sends Markets Higher", "link": "https://a.com/1", "guid": "g1", "_dt": None},
            {"title": "Bitcoin ETF Approval Sends Markets Soaring", "link": "https://b.com/2", "guid": "g2", "_dt": None},
        ]
        result = deduplicate(articles)
        assert len(result) == 1

    def test_dedup_keeps_different_articles(self):
        from news_scanner import deduplicate
        articles = [
            {"title": "Bitcoin surges", "link": "https://a.com/1", "guid": "g1", "_dt": None},
            {"title": "Ethereum drops sharply", "link": "https://b.com/2", "guid": "g2", "_dt": None},
        ]
        result = deduplicate(articles)
        assert len(result) == 2
```

**Step 2: Run — expect FAIL**

**Step 3: Implement deduplication**

```python
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                     "utm_content", "fbclid", "gclid", "ref"}

def canonical_url(url: str) -> str:
    """Normalize URL: lowercase host, strip tracking params."""
    p = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if k.lower() not in _TRACKING_PARAMS]
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path,
                                    urllib.parse.urlencode(q), ""))

DEDUP_TITLE_THRESHOLD = 0.90

def deduplicate(articles: list[dict]) -> list[dict]:
    """3-stage dedup: canonical URL → guid → fuzzy title."""
    seen_urls: set[str] = set()
    seen_guids: set[str] = set()
    seen_titles: list[str] = []
    result = []

    for a in articles:
        # Stage 1: URL
        curl = canonical_url(a.get("link", ""))
        if curl and curl in seen_urls:
            continue

        # Stage 2: GUID
        guid = a.get("guid", "")
        if guid and guid in seen_guids:
            continue

        # Stage 3: Fuzzy title
        norm_title = _normalize_title(a.get("title", ""))
        if norm_title and any(
            difflib.SequenceMatcher(None, norm_title, t).ratio() >= DEDUP_TITLE_THRESHOLD
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


def _normalize_title(title: str) -> str:
    return re.sub(r'\s+', ' ', title.lower().strip())
```

**Step 4: Run — expect PASS**

**Step 5: Commit**
```bash
git add -A && git commit -m "feat(news-scanner): 3-stage dedup (URL + guid + fuzzy title)"
```

---

### Task 4: Coin detection + sentiment scoring

**Step 1: Write coin + sentiment tests**

```python
class TestCoinDetection:
    def test_detects_bitcoin_by_name(self):
        from news_scanner import detect_coins
        assert "BTC" in detect_coins("Bitcoin surges past $100k")

    def test_detects_symbol_with_dollar(self):
        from news_scanner import detect_coins
        assert "ETH" in detect_coins("$ETH breaks resistance level")

    def test_no_false_positive_solution(self):
        from news_scanner import detect_coins
        assert "SOL" not in detect_coins("The solution to scaling problems")

    def test_detects_solana_by_name(self):
        from news_scanner import detect_coins
        assert "SOL" in detect_coins("Solana network processes 1M TPS")

    def test_multiple_coins(self):
        from news_scanner import detect_coins
        coins = detect_coins("Bitcoin and Ethereum lead the rally while Solana catches up")
        assert "BTC" in coins and "ETH" in coins and "SOL" in coins


class TestSentiment:
    def test_positive_sentiment(self):
        from news_scanner import score_article_sentiment
        assert score_article_sentiment("Bitcoin surges to new all-time high on ETF approval") > 0

    def test_negative_sentiment(self):
        from news_scanner import score_article_sentiment
        assert score_article_sentiment("Major crypto exchange hacked, millions stolen") < 0

    def test_negation_flips(self):
        from news_scanner import score_article_sentiment
        assert score_article_sentiment("Bitcoin rally fails to materialize") <= 0

    def test_neutral_no_keywords(self):
        from news_scanner import score_article_sentiment
        assert score_article_sentiment("The weather is nice today") == 0

    def test_aggregate_sentiment(self):
        from news_scanner import compute_aggregate_sentiment
        articles = [
            {"title": "Bitcoin surges on ETF approval", "_sentiment": 2},
            {"title": "Markets crash after hack", "_sentiment": -2},
            {"title": "Ethereum update released", "_sentiment": 0},
        ]
        result = compute_aggregate_sentiment(articles)
        assert result["positive"] == 1
        assert result["negative"] == 1
        assert result["neutral"] == 1
        assert result["signal"] == "neutral"
```

**Step 2: Run — expect FAIL**

**Step 3: Implement coin detection + sentiment**

```python
# -- Coin Detection --

# (name_pattern, symbol, case_sensitive)
COIN_PATTERNS: list[tuple[str, str]] = [
    (r"\bbitcoin\b", "BTC"), (r"(?<![A-Za-z])BTC(?![A-Za-z])", "BTC"),
    (r"\bethereum\b", "ETH"), (r"\bether\b", "ETH"), (r"(?<![A-Za-z])ETH(?![A-Za-z])", "ETH"),
    (r"\bsolana\b", "SOL"), (r"(?<![A-Za-z])\$SOL(?![A-Za-z])", "SOL"),
    (r"\bripple\b", "XRP"), (r"(?<![A-Za-z])XRP(?![A-Za-z])", "XRP"),
    (r"\bcardano\b", "ADA"), (r"(?<![A-Za-z])ADA(?![A-Za-z])", "ADA"),
    (r"\bdogecoin\b", "DOGE"), (r"(?<![A-Za-z])DOGE(?![A-Za-z])", "DOGE"),
    (r"\bavalanche\b", "AVAX"), (r"(?<![A-Za-z])AVAX(?![A-Za-z])", "AVAX"),
    (r"\bpolygon\b", "MATIC"), (r"(?<![A-Za-z])MATIC(?![A-Za-z])", "MATIC"),
    (r"\bpolkadot\b", "DOT"),  # DOT only via full name — too ambiguous as symbol
    (r"\bchainlink\b", "LINK"), (r"(?<![A-Za-z])LINK(?![A-Za-z])", "LINK"),
    (r"\blitecoin\b", "LTC"), (r"(?<![A-Za-z])LTC(?![A-Za-z])", "LTC"),
    (r"\btron\b", "TRX"), (r"(?<![A-Za-z])TRX(?![A-Za-z])", "TRX"),
    (r"(?<![A-Za-z])SUI(?![A-Za-z])", "SUI"),
    (r"(?<![A-Za-z])PEPE(?![A-Za-z])", "PEPE"),
    (r"\barbitrum\b", "ARB"), (r"(?<![A-Za-z])ARB(?![A-Za-z])", "ARB"),
    (r"\boptimism\b", "OP"),  # OP only via full name
    (r"\buniswap\b", "UNI"), (r"(?<![A-Za-z])UNI(?![A-Za-z])", "UNI"),
    (r"\baave\b", "AAVE"), (r"(?<![A-Za-z])AAVE(?![A-Za-z])", "AAVE"),
    (r"\bnear\b", "NEAR"), (r"(?<![A-Za-z])NEAR(?![A-Za-z])", "NEAR"),
    (r"\baptos\b", "APT"), (r"(?<![A-Za-z])APT(?![A-Za-z])", "APT"),
    (r"\bton\b", "TON"), (r"(?<![A-Za-z])TON(?![A-Za-z])", "TON"),
    (r"\bcosmos\b", "ATOM"), (r"(?<![A-Za-z])ATOM(?![A-Za-z])", "ATOM"),
    (r"\bfilecoin\b", "FIL"), (r"(?<![A-Za-z])FIL(?![A-Za-z])", "FIL"),
    (r"\brender\b", "RNDR"), (r"(?<![A-Za-z])RNDR(?![A-Za-z])", "RNDR"),
    (r"\binjective\b", "INJ"), (r"(?<![A-Za-z])INJ(?![A-Za-z])", "INJ"),
    (r"(?<![A-Za-z])BNB(?![A-Za-z])", "BNB"),
    (r"\bstacks\b", "STX"), (r"(?<![A-Za-z])STX(?![A-Za-z])", "STX"),
]

# Compile once
_COIN_RE = [(re.compile(pat, re.IGNORECASE if pat.startswith(r"\b") else 0), sym) for pat, sym in COIN_PATTERNS]


def detect_coins(text: str) -> list[str]:
    """Detect coin symbols mentioned in text."""
    found: set[str] = set()
    for pattern, symbol in _COIN_RE:
        if pattern.search(text):
            found.add(symbol)
    return sorted(found)


# -- Sentiment --

POSITIVE_WORDS = ["rally", "surge", "bullish", "approval", "launch", "soar", "gain",
                  "partnership", "breakthrough", "adoption"]
NEGATIVE_WORDS = ["crash", "hack", "ban", "dump", "bearish", "plunge", "exploit",
                  "lawsuit", "delisting", "fraud"]
NEGATION_WORDS = {"not", "no", "never", "fails", "unlikely", "denies", "without"}
BOOSTER_WORDS = {"extreme", "massive", "major", "historic", "record"}

import math

def score_article_sentiment(text: str) -> float:
    """Score a single article text. Returns float: positive=bullish, negative=bearish."""
    words = text.lower().split()
    score = 0.0
    negated = False

    for i, w in enumerate(words):
        clean = re.sub(r'[^a-z]', '', w)
        if clean in NEGATION_WORDS:
            negated = True
            continue

        multiplier = 1.5 if clean in BOOSTER_WORDS else 1.0

        if clean in POSITIVE_WORDS:
            score += (-1.0 if negated else 1.0) * multiplier
            negated = False
        elif clean in NEGATIVE_WORDS:
            score += (1.0 if negated else -1.0) * multiplier
            negated = False
        else:
            # Reset negation after 2 non-keyword words
            if negated and i > 0:
                negated = False

    return score


def compute_aggregate_sentiment(articles: list[dict]) -> dict:
    """Aggregate per-article sentiment into signal."""
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
```

**Step 4: Run — expect PASS**

**Step 5: Commit**
```bash
git add -A && git commit -m "feat(news-scanner): coin detection (30 coins) + sentiment with negation"
```

---

### Task 5: Confidence scoring + time window parsing

**Step 1: Write confidence + time window tests**

```python
class TestTimeWindow:
    def test_parse_hours(self):
        from news_scanner import parse_window
        assert parse_window("6h") == timedelta(hours=6)
        assert parse_window("24h") == timedelta(hours=24)

    def test_parse_days(self):
        from news_scanner import parse_window
        assert parse_window("7d") == timedelta(days=7)
        assert parse_window("2d") == timedelta(days=2)

    def test_parse_minutes(self):
        from news_scanner import parse_window
        assert parse_window("30m") == timedelta(minutes=30)

    def test_parse_invalid_raises(self):
        from news_scanner import parse_window
        with pytest.raises(ValueError):
            parse_window("abc")


class TestConfidence:
    def test_high_agreement_high_confidence(self):
        from news_scanner import compute_confidence
        # 8 bullish, 1 bearish, 1 neutral = high agreement
        score = compute_confidence(
            n_articles=10, n_positive=8, n_negative=1, n_neutral=1,
            n_sources=3, data_fresh=True,
        )
        assert score >= 60

    def test_mixed_low_confidence(self):
        from news_scanner import compute_confidence
        score = compute_confidence(
            n_articles=4, n_positive=2, n_negative=2, n_neutral=0,
            n_sources=1, data_fresh=True,
        )
        assert score <= 50

    def test_stale_data_penalty(self):
        from news_scanner import compute_confidence
        fresh = compute_confidence(8, 6, 1, 1, 3, True)
        stale = compute_confidence(8, 6, 1, 1, 3, False)
        assert stale < fresh

    def test_confidence_always_in_range(self):
        from news_scanner import compute_confidence
        for n in range(0, 20):
            for p in range(0, n + 1):
                neg = n - p
                score = compute_confidence(n, p, neg, 0, 2, True)
                assert 0 <= score <= 100
```

**Step 2: Run — expect FAIL**

**Step 3: Implement confidence + time window**

```python
# -- Time Window --

_WINDOW_RE = re.compile(r'^(\d+)(m|h|d|w)$')

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


# -- Confidence --

def compute_confidence(
    n_articles: int,
    n_positive: int,
    n_negative: int,
    n_neutral: int,
    n_sources: int,
    data_fresh: bool,
) -> int:
    """Weighted confidence: agreement 35% + coverage 25% + diversity 25% + quality 15%."""
    directional = n_positive + n_negative
    agreement = abs(n_positive - n_negative) / max(1, directional) if directional > 0 else 0

    coverage = min(1.0, n_articles / 10)
    diversity = min(1.0, n_sources / 4)
    quality = 1.0 if data_fresh else 0.5

    raw = 0.35 * agreement + 0.25 * coverage + 0.25 * diversity + 0.15 * quality
    confidence = round(15 + 85 * raw)

    # Force low confidence if too few directional articles
    if directional < 2:
        confidence = min(confidence, 35)

    return max(0, min(100, confidence))
```

**Step 4: Run — expect PASS**

**Step 5: Commit**
```bash
git add -A && git commit -m "feat(news-scanner): confidence scoring + time window parsing"
```

---

### Task 6: CLI + main() + end-to-end

**Step 1: Write CLI + E2E tests**

```python
class TestEndToEnd:
    @patch("urllib.request.urlopen")
    def test_main_outputs_valid_signal_json(self, mock_urlopen, capsys, tmp_path, monkeypatch):
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_RSS.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        import news_scanner
        monkeypatch.setattr(news_scanner, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(news_scanner, "RSS_FEEDS", [("TestFeed", "https://example.com/rss")])

        sys.argv = ["news_scanner", "--window", "24h", "--sources", "rss"]
        news_scanner.main()

        output = json.loads(capsys.readouterr().out)
        assert output["schema"] == "signal/v1"
        assert output["signal"] in ("bullish", "bearish", "neutral")
        assert 0 <= output["confidence"] <= 100
        assert "count" in output["data"]
        assert "analytics" in output
```

**Step 2: Run — expect FAIL**

**Step 3: Implement main()**

```python
# -- CLI --

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Crypto news scanner — sentiment signal", prog="news-scanner")
    p.add_argument("--window", default="24h", help="Time window (e.g. 6h, 24h, 7d)")
    p.add_argument("--coins", default="", help="Filter by coin symbols (comma-separated, e.g. BTC,ETH)")
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
    alert_keywords = [k.strip().lower() for k in args.keywords.split(",") if k.strip()]

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
        # Try cache
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

    # Detect coins per article
    for a in articles:
        if "coins" not in a or not a["coins"]:
            a["coins"] = detect_coins(a.get("title", "") + " " + a.get("description", ""))

    # Filter by coin
    if coin_filter:
        articles = [a for a in articles if any(c in a.get("coins", []) for c in coin_filter)]

    # Score sentiment per article
    for a in articles:
        a["_sentiment"] = score_article_sentiment(a.get("title", "") + " " + a.get("description", ""))

    # Detect alert keywords
    all_alerts: set[str] = set()
    default_alerts = ["sec", "etf", "hack", "ban", "approval", "regulation", "lawsuit",
                      "exploit", "delisting"]
    check_keywords = alert_keywords if alert_keywords else default_alerts
    for a in articles:
        lower = (a.get("title", "") + " " + a.get("description", "")).lower()
        hits = [kw for kw in check_keywords if kw in lower]
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

    # Confidence
    confidence = compute_confidence(
        n_articles=len(articles),
        n_positive=sentiment["positive"],
        n_negative=sentiment["negative"],
        n_neutral=sentiment["neutral"],
        n_sources=len(set(a.get("source", "") for a in articles)),
        data_fresh=data_fresh,
    )

    # Cache successful fetch
    if data_fresh:
        _save_cache(articles)

    # Build output articles (strip internal fields)
    output_articles = []
    for a in sorted(articles, key=lambda x: x.get("_dt") or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        output_articles.append({k: v for k, v in a.items() if not k.startswith("_")})

    signal = sentiment["signal"]
    reasoning = (
        f"News: {sentiment['positive']} bullish / {sentiment['negative']} bearish / "
        f"{sentiment['neutral']} neutral across {len(articles)} articles from {len(sources_used)} sources"
    )
    if not data_fresh:
        reasoning += " [STALE — using cache]"

    n_src = len(set(a.get("source", "") for a in articles))
    directional = sentiment["positive"] + sentiment["negative"]
    agreement_val = abs(sentiment["positive"] - sentiment["negative"]) / max(1, directional) if directional > 0 else 0

    out = SignalOutput(
        signal=signal,
        confidence=confidence,
        reasoning=reasoning,
        data={
            "count": len(output_articles),
            "articles": output_articles[:20],  # cap at 20 for output size
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
                "source_diversity": round(min(1.0, n_src / 4), 2),
                "data_quality": 1.0 if data_fresh else 0.5,
            },
            "effective_sample_size": len(articles),
            "duplicate_rate": duplicate_rate,
        },
    )

    # Human summary
    out.summary(
        f"  News Scanner: {len(articles)} articles from {', '.join(sources_used)}\n"
        f"  Sentiment: {signal} | Agreement: {agreement_val:.0%} | Confidence: {confidence}/100\n"
        f"  Trending: {', '.join(trending[:5]) or 'none'}\n"
        f"  Alerts: {', '.join(sorted(all_alerts)) or 'none'}"
    )
    out.emit()


if __name__ == "__main__":
    main()
```

**Step 4: Run all tests — expect ALL PASS**

**Step 5: Commit**
```bash
git add -A && git commit -m "feat(news-scanner): complete skill — CLI, scoring, end-to-end"
```

---

### Task 7: Smoke test with live RSS

**Step 1: Run against live feeds**
```bash
uv run skills/news-scanner/scripts/news_scanner.py --window 24h --sources rss
```

**Step 2: Run with coin filter**
```bash
uv run skills/news-scanner/scripts/news_scanner.py --window 7d --coins BTC,ETH --sources rss
```

**Step 3: Run all tests final**
```bash
python3 -m pytest tests/test_news_scanner.py -v --tb=short
```

**Step 4: Commit**
```bash
git add -A && git commit -m "test(news-scanner): all tests passing, live smoke verified"
```

---

---

### Codex Feedback (incorporated)

**Rating: 6.5/10 → revised below.**

Changes from Codex review:
1. **+8 edge case tests**: RSS parse failures, cache corruption, dedup short titles, coin disambiguation
2. **CryptoPanic votes in confidence**: conditional component when available (replaces part of quality weight)
3. **Adaptive dedup threshold**: 0.87 for titles >60 chars, 0.92 for short titles, plus token overlap
4. **Scoped negation**: punctuation boundaries (comma, period, dash) reset negation window

### Additional tests to add across tasks:

**Task 1 extras:**
```python
def test_fetch_rss_invalid_xml_returns_empty(self):
    # Mock response with invalid XML
    ...
    assert articles == []

def test_fetch_rss_empty_feed_returns_empty(self):
    # Mock valid XML but no <item> elements
    ...
    assert articles == []
```

**Task 2 extras:**
```python
def test_load_corrupted_cache_returns_none(self, tmp_path):
    # Write garbage to cache file
    (tmp_path / "test.json").write_text("not json{{{")
    assert _load_cache(tmp_path / "test.json") == (None, 0)
```

**Task 3 extras:**
```python
def test_dedup_short_titles_stricter_threshold(self):
    # Short similar titles should NOT be deduped if they're different articles
    articles = [
        {"title": "BTC up 5%", ...},
        {"title": "ETH up 5%", ...},
    ]
    assert len(deduplicate(articles)) == 2

def test_dedup_long_titles_looser_threshold(self):
    # Long titles with minor rewording should be deduped
    ...
```

**Task 4 extras:**
```python
def test_negation_scoped_to_clause(self):
    # "Not bullish, but the market surges" — "surges" should NOT be negated
    assert score_article_sentiment("Not bullish, but the market surges") > 0

def test_coin_dot_not_matched_without_polkadot(self):
    assert "DOT" not in detect_coins("The DOT protocol update is live")
```

**Task 5 extras:**
```python
def test_confidence_with_cryptopanic_votes(self):
    # When votes available, confidence should be higher
    ...
```

### Revised confidence formula:

```python
def compute_confidence(..., cp_votes: dict | None = None) -> int:
    # Base weights
    agreement_w, coverage_w, diversity_w, quality_w = 0.35, 0.25, 0.25, 0.15

    # If CryptoPanic votes available, inject social credence
    if cp_votes and (cp_votes.get("positive", 0) + cp_votes.get("negative", 0)) >= 5:
        social = cp_votes["positive"] / max(1, cp_votes["positive"] + cp_votes["negative"])
        # Redistribute: take 0.10 from quality
        quality_w = 0.05
        social_w = 0.10
        raw = agreement_w * agreement + coverage_w * coverage + diversity_w * diversity + quality_w * quality + social_w * social
    else:
        raw = agreement_w * agreement + coverage_w * coverage + diversity_w * diversity + quality_w * quality
    ...
```

### Revised dedup:

```python
def _dedup_threshold(title: str) -> float:
    """Adaptive threshold: stricter for short titles, looser for long."""
    return 0.87 if len(title) > 60 else 0.92
```

### Revised negation:

```python
CLAUSE_BOUNDARIES = {",", ".", ";", "—", "–", "-", "but", "however", "although", "yet"}

def score_article_sentiment(text: str) -> float:
    words = text.lower().split()
    score = 0.0
    negated = False
    for w in words:
        clean = re.sub(r'[^a-z,.\-;]', '', w)
        if clean in CLAUSE_BOUNDARIES or "," in w or "." in w:
            negated = False  # reset at clause boundary
            continue
        ...
```

---

## Summary (revised)

| Task | What | Tests |
|------|------|-------|
| 1 | RSS fetch + datetime parsing | 5 |
| 2 | CryptoPanic fetch + cache | 5 |
| 3 | 3-stage adaptive dedup | 7 |
| 4 | Coin detection (30) + scoped sentiment | 11 |
| 5 | Confidence scoring (with CP votes) + time window | 8 |
| 6 | CLI + main + end-to-end | 1 |
| 7 | Smoke test (live RSS) | manual |

**Total: ~37 tests, 1 file (~420 lines), stdlib only, 7 commits.**
