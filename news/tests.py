from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from django.core.cache import cache
from django.test import TestCase

from news import utils


class FakeEntry(dict):
    """Mimics feedparser's dict-like FeedParserDict entries (supports both
    `entry['x']`/`'x' in entry` and `entry.x` attribute access)."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def _make_entry(primary_category, published, entry_id="1234.5678"):
    return FakeEntry(
        authors=[SimpleNamespace(name="A. Author")],
        id=f"http://arxiv.org/abs/{entry_id}",
        link=f"http://arxiv.org/abs/{entry_id}",
        published=published.isoformat(),
        summary="An abstract.",
        title="A title",
        arxiv_primary_category={'term': primary_category},
        tags=[{'term': primary_category}],
    )


class FetchArxivPapersTests(TestCase):
    def setUp(self):
        cache.clear()
        # Avoid real sleeping for the inter-request throttle/backoff in tests.
        self.sleep_patcher = patch('news.utils.time.sleep')
        self.sleep_patcher.start()
        self.addCleanup(self.sleep_patcher.stop)
        # Ensure the throttle doesn't think a request just happened.
        utils._last_request_time = 0.0

    def _mock_response(self, entries):
        feed = MagicMock()
        feed.entries = entries
        response = MagicMock()
        response.status_code = 200
        response.content = b""
        return response, feed

    @patch('news.utils.feedparser.parse')
    @patch('news.utils.requests.get')
    def test_request_sizing_no_flat_minimum(self, mock_get, mock_parse):
        response, feed = self._mock_response([])
        mock_get.return_value = response
        mock_parse.return_value = feed

        utils.fetch_arxiv_papers(query="cat:hep-ph", max_results=5)

        called_url = mock_get.call_args.args[0]
        self.assertIn("max_results=15", called_url)  # 5 * 3, not clamped to 100
        self.assertNotIn("max_results=100", called_url)

    @patch('news.utils.feedparser.parse')
    @patch('news.utils.requests.get')
    def test_allowlist_drops_cross_listed_papers_outside_family(self, mock_get, mock_parse):
        now = datetime.now(timezone.utc)
        entries = [
            _make_entry('hep-ph', now, "1"),
            # Cross-listed into hep-ph search results, but primary category
            # is outside the five allowed families -> must be dropped.
            _make_entry('cs.LG', now - timedelta(hours=1), "2"),
        ]
        response, feed = self._mock_response(entries)
        mock_get.return_value = response
        mock_parse.return_value = feed

        results = utils.fetch_arxiv_papers(query="cat:hep-ph", max_results=10, primary_category_filter=None)

        categories = [p['primary_category'] for p in results]
        self.assertIn('hep-ph', categories)
        self.assertNotIn('cs.LG', categories)

    @patch('news.utils.feedparser.parse')
    @patch('news.utils.requests.get')
    def test_explicit_filter_still_restricts_to_requested_family(self, mock_get, mock_parse):
        now = datetime.now(timezone.utc)
        entries = [
            _make_entry('hep-ph', now, "1"),
            _make_entry('hep-th', now - timedelta(hours=1), "2"),
        ]
        response, feed = self._mock_response(entries)
        mock_get.return_value = response
        mock_parse.return_value = feed

        results = utils.fetch_arxiv_papers(query="cat:hep-ph", max_results=10, primary_category_filter='hep-ph')

        categories = [p['primary_category'] for p in results]
        self.assertEqual(categories, ['hep-ph'])

    @patch('news.utils.feedparser.parse')
    @patch('news.utils.requests.get')
    def test_results_are_cached_between_calls(self, mock_get, mock_parse):
        now = datetime.now(timezone.utc)
        entries = [_make_entry('gr-qc', now, "1")]
        response, feed = self._mock_response(entries)
        mock_get.return_value = response
        mock_parse.return_value = feed

        utils.fetch_arxiv_papers(query="cat:gr-qc", max_results=10, primary_category_filter='gr-qc')
        utils.fetch_arxiv_papers(query="cat:gr-qc", max_results=10, primary_category_filter='gr-qc')

        self.assertEqual(mock_get.call_count, 1)

    @patch('news.utils.feedparser.parse')
    @patch('news.utils.requests.get')
    def test_different_queries_are_not_cached_together(self, mock_get, mock_parse):
        now = datetime.now(timezone.utc)
        entries = [_make_entry('hep-lat', now, "1")]
        response, feed = self._mock_response(entries)
        mock_get.return_value = response
        mock_parse.return_value = feed

        utils.fetch_arxiv_papers(query="cat:hep-lat", max_results=10, primary_category_filter='hep-lat')
        utils.fetch_arxiv_papers(query="cat:astro-ph", max_results=10, primary_category_filter='astro-ph')

        self.assertEqual(mock_get.call_count, 2)

    @patch('news.utils.requests.get')
    def test_retries_on_rate_limit_then_succeeds(self, mock_get):
        rate_limited = MagicMock(status_code=429)
        ok_response = MagicMock(status_code=200, content=b"")

        mock_get.side_effect = [rate_limited, ok_response]

        with patch('news.utils.feedparser.parse') as mock_parse:
            mock_parse.return_value = MagicMock(entries=[])
            utils.fetch_arxiv_papers(query="cat:hep-ph", max_results=5)

        self.assertEqual(mock_get.call_count, 2)

    @patch('news.utils.requests.get')
    def test_gives_up_after_max_retries(self, mock_get):
        rate_limited = MagicMock(status_code=429)
        mock_get.return_value = rate_limited

        with patch('news.utils.feedparser.parse') as mock_parse:
            mock_parse.return_value = MagicMock(entries=[])
            result = utils.fetch_arxiv_papers(query="cat:hep-ph", max_results=5)

        self.assertEqual(mock_get.call_count, utils.MAX_RETRIES + 1)
        self.assertEqual(result, [])
