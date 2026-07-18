import hashlib
import threading
import time
import requests
import feedparser
from datetime import datetime
from dateutil import parser
import urllib.parse
import re

from django.core.cache import cache

ARXIV_API_URL = 'http://export.arxiv.org/api/query'

# The five primary-category families served by this site. Any paper whose
# primary category doesn't fall under one of these is dropped, even if it
# was returned because it's cross-listed into a requested category.
ALLOWED_CATEGORIES = ('hep-ph', 'hep-th', 'hep-lat', 'gr-qc', 'astro-ph')

CACHE_TTL_SECONDS = 15 * 60

# arXiv asks API clients to space consecutive requests by at least 3 seconds.
MIN_REQUEST_INTERVAL = 3.0
MAX_RETRIES = 2

_last_request_lock = threading.Lock()
_last_request_time = 0.0


def clean_latex_text(text):
    """
    Parses a string and replaces common LaTeX text-mode commands with HTML,
    while attempting to preserve MathJax-formatted math (delimited by $...$).
    """
    if not text:
        return ""

    # Split text by math delimiters ($$ or $)
    # basic regex to capture math blocks.
    # Warning: does not handle escaped dollars \$ perfectly.
    parts = re.split(r'(\$\$?.*?\$\$?)', text)

    cleaned_parts = []
    for part in parts:
        # If the part looks like a math block, extract it as is
        if part.startswith('$'):
            cleaned_parts.append(part)
        else:
            # Process text commands
            # \textsc
            part = re.sub(r'\\textsc\{(.*?)\}', r'<span style="font-variant: small-caps;">\1</span>', part)
            # \textbf
            part = re.sub(r'\\textbf\{(.*?)\}', r'<b>\1</b>', part)
            # \textit
            part = re.sub(r'\\textit\{(.*?)\}', r'<i>\1</i>', part)
            # \texttt
            part = re.sub(r'\\texttt\{(.*?)\}', r'<code>\1</code>', part)
            # \emph
            part = re.sub(r'\\emph\{(.*?)\}', r'<em>\1</em>', part)

            cleaned_parts.append(part)

    return "".join(cleaned_parts)


def _primary_category_allowed(primary_category, filter_prefix=None):
    """
    Checks a paper's primary category against the requested filter, or
    against the site-wide allowlist when no specific filter is given.
    This is what keeps cross-listed papers (e.g. primary category hep-ex,
    cross-listed into hep-ph) out of pages that didn't ask for them.
    """
    if filter_prefix:
        return primary_category.startswith(filter_prefix)
    return any(primary_category.startswith(cat) for cat in ALLOWED_CATEGORIES)


def _throttled_get(url, headers, timeout):
    """
    Fetches a URL with a bounded retry for transient errors/rate limiting,
    while ensuring consecutive requests are spaced at least
    MIN_REQUEST_INTERVAL seconds apart, per arXiv's API guidance.
    """
    global _last_request_time

    backoff = 1.0
    response = None

    for attempt in range(MAX_RETRIES + 1):
        with _last_request_lock:
            wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_time)
            if wait > 0:
                time.sleep(wait)
            _last_request_time = time.monotonic()

        try:
            response = requests.get(url, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            if attempt < MAX_RETRIES:
                print(f"Network error fetching from ArXiv (attempt {attempt + 1}): {e}")
                time.sleep(backoff)
                backoff *= 2
                continue
            raise

        if response.status_code == 429 or response.status_code >= 500:
            if attempt < MAX_RETRIES:
                print(f"ArXiv returned status {response.status_code} (attempt {attempt + 1}), retrying")
                time.sleep(backoff)
                backoff *= 2
                continue

        return response

    return response


def _cache_key(query, max_results, primary_category_filter):
    raw = f"{query}|{max_results}|{primary_category_filter}"
    digest = hashlib.md5(raw.encode('utf-8')).hexdigest()
    return f"arxiv:papers:{digest}"


def fetch_arxiv_papers(query="cat:hep-ph OR cat:hep-th", max_results=10, primary_category_filter=None):
    """
    Generic fetcher for ArXiv papers.
    Fetches a modest multiple of the requested amount to identify the latest
    daily release and to absorb cross-listed entries dropped by the category
    allowlist, then sorts that batch by submission time ascending (closest to
    deadline first). Results are cached briefly to avoid repeated arXiv calls
    from normal page browsing.
    """
    cache_key = _cache_key(query, max_results, primary_category_filter)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Fetch a modest multiple of what's needed (not a flat minimum of 100)
    # to leave room for the 24h "latest batch" cut and allowlist filtering.
    fetch_limit = max_results * 3

    params = {
        'search_query': query,
        'start': 0,
        'max_results': fetch_limit,
        'sortBy': 'submittedDate',
        'sortOrder': 'descending',
    }

    query_string = urllib.parse.urlencode(params)
    url = f"{ARXIV_API_URL}?{query_string}"

    headers = {
        'User-Agent': 'HEP-Times/1.0 (Educational Project; mailto:student@example.com)'
    }

    try:
        response = _throttled_get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"Error: ArXiv API returned status code {response.status_code}")
            return []
    except requests.RequestException as e:
        print(f"Network error fetching from ArXiv: {e}")
        return []

    feed = feedparser.parse(response.content)

    if not feed.entries:
        print("Warning: No entries found in feed.")
        if 'bozo_exception' in feed:
            print(f"Feedparser exception: {feed.bozo_exception}")

    papers = []

    # Process entries into a structured list first
    for entry in feed.entries:
        try:
            # Extract authors
            authors = [author.name for author in entry.authors]

            # Extract ID (remove version for clean link if needed, but entry.id usually has it)
            paper_id = entry.id.split('/abs/')[-1]
            pdf_link = entry.link.replace('/abs/', '/pdf/')

            # Parse date
            published_dt = parser.parse(entry.published)

            # Clean abstract (remove newlines usually formatted weirdly in arxiv feed)
            summary = entry.summary.replace('\n', ' ').strip()
            summary = clean_latex_text(summary)

            title = entry.title.replace('\n', ' ')
            title = clean_latex_text(title)

            # Handle category safely
            if 'arxiv_primary_category' in entry:
                primary_category = entry.arxiv_primary_category['term']
            elif 'tags' in entry and len(entry.tags) > 0:
                primary_category = entry.tags[0]['term']
            else:
                primary_category = 'Unknown'

            paper = {
                'title': title,
                'authors': authors,
                'authors_str': ', '.join(authors),
                'abstract': summary,
                'link': entry.link,
                'pdf_link': pdf_link,
                'published': published_dt,
                'id': paper_id,
                'primary_category': primary_category
            }
            papers.append(paper)
        except Exception as e:
            print(f"Error parsing entry: {e}")
            continue

    if not papers:
        cache.set(cache_key, [], CACHE_TTL_SECONDS)
        return []

    # Filter for only the "latest batch".
    # ArXiv releases happen once a day.
    # The fetched list (descending) contains today's papers, then yesterday's, etc.
    # We want to identify the latest group and cut off the rest.
    # Strategy: Sort descending (already is, mostly), find the largest time gap to identify batch boundary?
    # Or just group by "ArXiv Day" (Deadline is 14:00 ET / 19:00 UTC).

    # Let's use the simplest heuristic: Sort by published descending.
    # The latest papers are at the top.
    # We iterate and stop when we hit a gap > 4 hours (arbitrary, but submissions usually slow down or stop at cutoff?).
    # Actually, submission is continuous. The "Published" date is what matters.
    # But ArXiv API "published" is the submission time...

    # Actually, ArXiv API returns results sorted by submission time.
    # We want the *latest* contiguous block of papers roughly from the last 24h.
    # Let's find the most recent paper's date.
    papers.sort(key=lambda x: x['published'], reverse=True) # Ensure strictly descending
    latest_ts = papers[0]['published']

    # Filter papers within 24 hours of the latest paper
    # (Assuming papers are released daily, the "new" batch spans 24h ending at the latest submission)
    cutoff_time = latest_ts.timestamp() - (24 * 3600)

    latest_batch = [p for p in papers if p['published'].timestamp() > cutoff_time]

    # Filter by category: honor an explicit filter if given, otherwise fall
    # back to the site-wide allowlist so cross-listed papers whose primary
    # category is outside our five families don't leak in.
    latest_batch = [
        p for p in latest_batch
        if _primary_category_allowed(p['primary_category'], primary_category_filter)
    ]

    # Now sort THIS batch ascending (Earliest submission first -> "Increasing time after deadline")
    latest_batch.sort(key=lambda x: x['published'])

    # Slice the requested amount
    result = latest_batch[:max_results]

    print(f"Fetched {len(papers)} raw, found {len(latest_batch)} in latest 24h batch matching filter. Returning {len(result)}.")

    cache.set(cache_key, result, CACHE_TTL_SECONDS)
    return result

def fetch_latest_papers():
    # Backwards compatibility default
    return fetch_arxiv_papers(query='cat:hep-ph OR cat:hep-th', max_results=10)
