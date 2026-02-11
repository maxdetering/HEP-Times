import requests
import feedparser
from datetime import datetime
from dateutil import parser
import urllib.parse
import re

ARXIV_API_URL = 'http://export.arxiv.org/api/query'

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

def fetch_arxiv_papers(query="cat:hep-ph OR cat:hep-th", max_results=10):
    """
    Generic fetcher for ArXiv papers.
    sorted by submission date descending.
    """
    params = {
        'search_query': query,
        'start': 0,
        'max_results': max_results,
        'sortBy': 'submittedDate',
        'sortOrder': 'descending',
    }
    
    query_string = urllib.parse.urlencode(params)
    url = f"{ARXIV_API_URL}?{query_string}"
    
    headers = {
        'User-Agent': 'HEP-Times/1.0 (Educational Project; mailto:student@example.com)'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
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
        
    print(f"Successfully fetched {len(papers)} papers for query: {query}")
    return papers

def fetch_latest_papers():
    # Backwards compatibility default
    return fetch_arxiv_papers(query='cat:hep-ph OR cat:hep-th', max_results=10)
    return papers
