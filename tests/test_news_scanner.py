"""Tests for news_scanner skill."""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "news-scanner" / "scripts"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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

SAMPLE_RSS_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Empty</title></channel></rss>"""

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


def _mock_urlopen(data: bytes):
    mock_resp = MagicMock()
    mock_resp.read.return_value = data
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# RSS Fetch
# ---------------------------------------------------------------------------


class TestFetchRSS:
    @patch("urllib.request.urlopen")
    def test_parse_rss_items(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(SAMPLE_RSS.encode())
        from news_scanner import fetch_rss
        articles = fetch_rss("TestFeed", "https://example.com/rss")
        assert len(articles) == 2
        assert articles[0]["title"] == "Bitcoin surges past $100k on ETF approval"
        assert articles[0]["source"] == "TestFeed"
        assert articles[0]["guid"] == "abc-123"

    @patch("urllib.request.urlopen")
    def test_parse_rss_datetime(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(SAMPLE_RSS.encode())
        from news_scanner import fetch_rss
        articles = fetch_rss("TestFeed", "https://example.com/rss")
        assert articles[0]["published_at"] is not None
        dt = datetime.fromisoformat(articles[0]["published_at"])
        assert dt.tzinfo is not None

    @patch("urllib.request.urlopen")
    def test_fetch_rss_failure_returns_empty(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Network error")
        from news_scanner import fetch_rss
        assert fetch_rss("TestFeed", "https://example.com/rss") == []

    @patch("urllib.request.urlopen")
    def test_fetch_rss_invalid_xml_returns_empty(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(b"<not valid xml{{{")
        from news_scanner import fetch_rss
        assert fetch_rss("TestFeed", "https://example.com/rss") == []

    @patch("urllib.request.urlopen")
    def test_fetch_rss_empty_feed_returns_empty(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(SAMPLE_RSS_EMPTY.encode())
        from news_scanner import fetch_rss
        assert fetch_rss("TestFeed", "https://example.com/rss") == []


# ---------------------------------------------------------------------------
# CryptoPanic Fetch
# ---------------------------------------------------------------------------


class TestFetchCryptoPanic:
    @patch.dict(os.environ, {"CRYPTOPANIC_API_KEY": "test-key"})
    @patch("urllib.request.urlopen")
    def test_fetch_with_key_parses_articles(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(SAMPLE_CP_RESPONSE)
        from news_scanner import fetch_cryptopanic
        articles = fetch_cryptopanic()
        assert len(articles) == 2
        assert articles[0]["coins"] == ["BTC"]
        assert articles[0]["votes"]["positive"] == 15

    @patch.dict(os.environ, {}, clear=True)
    def test_fetch_without_key_returns_empty(self):
        from news_scanner import fetch_cryptopanic
        assert fetch_cryptopanic() == []


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class TestCache:
    def test_save_and_load_cache(self, tmp_path):
        from news_scanner import _load_cache, _save_cache
        cache_file = tmp_path / "test.json"
        data = [{"title": "Test article"}]
        _save_cache(data, cache_file)
        loaded, ts = _load_cache(cache_file)
        assert loaded == data
        assert ts > 0

    def test_load_missing_returns_none(self, tmp_path):
        from news_scanner import _load_cache
        assert _load_cache(tmp_path / "nope.json") == (None, 0)

    def test_load_corrupted_returns_none(self, tmp_path):
        from news_scanner import _load_cache
        f = tmp_path / "bad.json"
        f.write_text("not json{{{")
        assert _load_cache(f) == (None, 0)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDedup:
    def test_url_canonical_strips_utm(self):
        from news_scanner import canonical_url
        url = "https://example.com/article?utm_source=rss&utm_medium=feed&id=123"
        assert canonical_url(url) == "https://example.com/article?id=123"

    def test_url_canonical_normalizes_case(self):
        from news_scanner import canonical_url
        assert canonical_url("HTTP://Example.COM/Path/") == "http://example.com/Path/"

    def test_dedup_by_url(self):
        from news_scanner import deduplicate
        articles = [
            {"title": "Bitcoin surges", "link": "https://ex.com/a?utm_source=rss", "guid": "", "_dt": None},
            {"title": "Bitcoin surges!", "link": "https://ex.com/a?utm_medium=x", "guid": "", "_dt": None},
        ]
        assert len(deduplicate(articles)) == 1

    def test_dedup_by_guid(self):
        from news_scanner import deduplicate
        articles = [
            {"title": "Article A", "link": "https://a.com/1", "guid": "guid-1", "_dt": None},
            {"title": "Article B", "link": "https://b.com/2", "guid": "guid-1", "_dt": None},
        ]
        assert len(deduplicate(articles)) == 1

    def test_dedup_by_fuzzy_title(self):
        from news_scanner import deduplicate
        articles = [
            {"title": "Bitcoin ETF Approval Sends Markets Higher After Long Wait For Regulatory Clarity", "link": "https://a.com/1", "guid": "g1", "_dt": None},
            {"title": "Bitcoin ETF Approval Sends Markets Soaring After Long Wait For Regulatory Clarity", "link": "https://b.com/2", "guid": "g2", "_dt": None},
        ]
        assert len(deduplicate(articles)) == 1

    def test_dedup_keeps_different_articles(self):
        from news_scanner import deduplicate
        articles = [
            {"title": "Bitcoin surges past resistance", "link": "https://a.com/1", "guid": "g1", "_dt": None},
            {"title": "Ethereum drops sharply on whale selling", "link": "https://b.com/2", "guid": "g2", "_dt": None},
        ]
        assert len(deduplicate(articles)) == 2

    def test_dedup_short_titles_stricter(self):
        from news_scanner import deduplicate
        # Short different titles should NOT be deduped
        articles = [
            {"title": "BTC up 5%", "link": "https://a.com/1", "guid": "g1", "_dt": None},
            {"title": "ETH up 5%", "link": "https://b.com/2", "guid": "g2", "_dt": None},
        ]
        assert len(deduplicate(articles)) == 2


# ---------------------------------------------------------------------------
# Coin Detection
# ---------------------------------------------------------------------------


class TestCoinDetection:
    def test_detects_bitcoin_by_name(self):
        from news_scanner import detect_coins
        assert "BTC" in detect_coins("Bitcoin surges past $100k")

    def test_detects_btc_symbol(self):
        from news_scanner import detect_coins
        assert "BTC" in detect_coins("BTC breaks resistance level")

    def test_detects_dollar_sol(self):
        from news_scanner import detect_coins
        assert "SOL" in detect_coins("$SOL breaks resistance level")

    def test_no_false_positive_solution(self):
        from news_scanner import detect_coins
        # "SOL" alone should not match in "solution" (case sensitive, no $ prefix)
        assert "SOL" not in detect_coins("The solution to scaling problems")

    def test_detects_solana_by_name(self):
        from news_scanner import detect_coins
        assert "SOL" in detect_coins("Solana network processes 1M TPS")

    def test_dot_not_matched_without_polkadot(self):
        from news_scanner import detect_coins
        assert "DOT" not in detect_coins("The DOT protocol update is live")

    def test_dot_matched_with_polkadot(self):
        from news_scanner import detect_coins
        assert "DOT" in detect_coins("Polkadot launches new parachain")

    def test_multiple_coins(self):
        from news_scanner import detect_coins
        coins = detect_coins("Bitcoin and Ethereum lead the rally while Solana catches up")
        assert "BTC" in coins and "ETH" in coins and "SOL" in coins


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------


class TestSentiment:
    def test_positive_sentiment(self):
        from news_scanner import score_article_sentiment
        assert score_article_sentiment("Bitcoin surges to new all-time high on ETF approval") > 0

    def test_negative_sentiment(self):
        from news_scanner import score_article_sentiment
        assert score_article_sentiment("Major crypto exchange hacked, millions stolen") < 0

    def test_negation_flips_positive(self):
        from news_scanner import score_article_sentiment
        # "not bullish" should be negative
        assert score_article_sentiment("Market outlook is not bullish") < 0

    def test_negation_scoped_to_clause(self):
        from news_scanner import score_article_sentiment
        # "Not bearish, but the market surges" — comma resets negation, surges counts positive
        score = score_article_sentiment("Not bearish, but the market surges")
        assert score > 0

    def test_booster_amplifies(self):
        from news_scanner import score_article_sentiment
        plain = score_article_sentiment("Bitcoin rally")
        boosted = score_article_sentiment("Bitcoin massive rally")
        assert boosted > plain

    def test_neutral_no_keywords(self):
        from news_scanner import score_article_sentiment
        assert score_article_sentiment("The weather is nice today") == 0

    def test_aggregate_sentiment(self):
        from news_scanner import compute_aggregate_sentiment
        articles = [
            {"_sentiment": 2},
            {"_sentiment": -2},
            {"_sentiment": 0},
        ]
        result = compute_aggregate_sentiment(articles)
        assert result["positive"] == 1
        assert result["negative"] == 1
        assert result["neutral"] == 1
        assert result["signal"] == "neutral"


# ---------------------------------------------------------------------------
# Time Window
# ---------------------------------------------------------------------------


class TestTimeWindow:
    def test_parse_hours(self):
        from news_scanner import parse_window
        assert parse_window("6h") == timedelta(hours=6)
        assert parse_window("24h") == timedelta(hours=24)

    def test_parse_days(self):
        from news_scanner import parse_window
        assert parse_window("7d") == timedelta(days=7)

    def test_parse_minutes(self):
        from news_scanner import parse_window
        assert parse_window("30m") == timedelta(minutes=30)

    def test_parse_weeks(self):
        from news_scanner import parse_window
        assert parse_window("1w") == timedelta(weeks=1)

    def test_parse_invalid_raises(self):
        from news_scanner import parse_window
        with pytest.raises(ValueError):
            parse_window("abc")


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


class TestConfidence:
    def test_high_agreement_high_confidence(self):
        from news_scanner import compute_confidence
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

    def test_few_directional_capped(self):
        from news_scanner import compute_confidence
        # Only 1 directional article — should cap at 35
        score = compute_confidence(5, 1, 0, 4, 3, True)
        assert score <= 35

    def test_cp_votes_boost(self):
        from news_scanner import compute_confidence
        without = compute_confidence(10, 7, 2, 1, 3, True, cp_votes=None)
        with_votes = compute_confidence(10, 7, 2, 1, 3, True, cp_votes={"positive": 20, "negative": 3})
        # CP votes should change confidence
        assert with_votes != without

    def test_confidence_always_in_range(self):
        from news_scanner import compute_confidence
        for n in range(0, 15):
            for p in range(0, n + 1):
                neg = n - p
                score = compute_confidence(n, p, neg, 0, 2, True)
                assert 0 <= score <= 100


# ---------------------------------------------------------------------------
# End-to-End
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @patch("urllib.request.urlopen")
    def test_main_outputs_valid_signal_json(self, mock_urlopen, capsys, tmp_path, monkeypatch):
        mock_urlopen.return_value = _mock_urlopen(SAMPLE_RSS.encode())

        import news_scanner
        monkeypatch.setattr(news_scanner, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(news_scanner, "CACHE_FILE", tmp_path / "articles.json")
        monkeypatch.setattr(news_scanner, "RSS_FEEDS", [("TestFeed", "https://example.com/rss")])

        sys.argv = ["news_scanner", "--window", "24h", "--sources", "rss"]
        news_scanner.main()

        output = json.loads(capsys.readouterr().out)
        assert output["schema"] == "signal/v1"
        assert output["signal"] in ("bullish", "bearish", "neutral")
        assert 0 <= output["confidence"] <= 100
        assert "count" in output["data"]
        assert "analytics" in output
        assert "confidence_components" in output["analytics"]
