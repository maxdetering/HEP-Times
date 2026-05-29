import requests
import feedparser
import time
from datetime import datetime
from dateutil import parser
import urllib.parse
import re

ARXIV_API_URL = 'https://export.arxiv.org/api/query'

# Simple in-memory cache: key -> (timestamp, data)
_cache = {}
_CACHE_TTL = 2 * 3600  # 2 hours — ArXiv updates once a day
_MIN_REQUEST_INTERVAL = 3  # seconds between ArXiv requests, per their guidelines
_last_request_time = 0

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

def fetch_arxiv_papers(query="cat:hep-ph OR cat:hep-th", max_results=10, primary_category_filter=None):
    """
    Generic fetcher for ArXiv papers.
    Fetches a larger batch to identify the latest daily release,
    then sorts that specific batch by submission time ascending (closest to deadline first).
    Results are cached for 2 hours to avoid hitting ArXiv rate limits.
    """
    global _last_request_time

    cache_key = f"{query}|{max_results}|{primary_category_filter}"
    now = time.time()

    if cache_key in _cache:
        cached_at, cached_data = _cache[cache_key]
        if now - cached_at < _CACHE_TTL:
            print(f"Cache hit for '{cache_key}'. Returning cached result.")
            return cached_data

    # Respect ArXiv's guideline: no more than 1 request per 3 seconds
    elapsed = now - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    # Fetch enough to cover a full day's batch. 150 covers all categories comfortably.
    fetch_limit = max(150, max_results * 5)

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
        'User-Agent': 'HEP-Times/1.0 (Educational Project; mailto:max@detering.de)'
    }

    # Retry with exponential backoff on 429 (rate limit) responses.
    for attempt in range(5):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            _last_request_time = time.time()
            if response.status_code == 429:
                wait = 30 * (2 ** attempt)
                print(f"Rate limited by ArXiv (attempt {attempt+1}). Waiting {wait}s...")
                time.sleep(wait)
                continue
            if response.status_code != 200:
                print(f"Error: ArXiv API returned status code {response.status_code}")
                return []
            break
        except requests.RequestException as e:
            print(f"Network error fetching from ArXiv: {e}")
            return []
    else:
        print("Exceeded retry limit after repeated 429 responses.")
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
    
    # Filter by primary category if requested.
    # Accepts a single string or a list of strings (any match passes).
    if primary_category_filter:
        filters = [primary_category_filter] if isinstance(primary_category_filter, str) else primary_category_filter
        latest_batch = [
            p for p in latest_batch
            if any(p['primary_category'].startswith(f) for f in filters)
        ]
    
    # Now sort THIS batch ascending (Earliest submission first -> "Increasing time after deadline")
    latest_batch.sort(key=lambda x: x['published'])
    
    # Slice the requested amount
    result = latest_batch[:max_results]
    
    print(f"Fetched {len(papers)} raw, found {len(latest_batch)} in latest 24h batch matching filter. Returning {len(result)}.")

    _cache[cache_key] = (time.time(), result)
    return result

def fetch_latest_papers():
    return fetch_arxiv_papers(query='cat:hep-ph OR cat:hep-th', max_results=10)
