"""
Static site build script for Netlify.
Fetches ArXiv papers for each section and renders them to HTML files in dist/.
"""
import os
import sys
import shutil
from pathlib import Path

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hep_times.settings')

import django
django.setup()

from django.template.loader import render_to_string
from django.test import RequestFactory
from datetime import datetime

from news.utils import fetch_and_partition_papers

PAGE_MAPPING = {
    1: {'name': 'Front Page',              'query': 'cat:hep-ph OR cat:hep-th', 'limit': 10, 'filter': ['hep-ph', 'hep-th']},
    2: {'name': 'Phenomenology (hep-ph)',  'query': 'cat:hep-ph',               'limit': 20, 'filter': 'hep-ph'},
    3: {'name': 'Theory (hep-th)',         'query': 'cat:hep-th',               'limit': 20, 'filter': 'hep-th'},
    4: {'name': 'Lattice (hep-lat)',       'query': 'cat:hep-lat',              'limit': 20, 'filter': 'hep-lat'},
    5: {'name': 'GR & QC (gr-qc)',         'query': 'cat:gr-qc',                'limit': 20, 'filter': 'gr-qc'},
    6: {'name': 'Astrophysics (astro-ph)', 'query': 'cat:astro-ph',             'limit': 20, 'filter': 'astro-ph'},
}

DIST = Path('dist')
PAGE_LINKS = sorted(PAGE_MAPPING.keys())

def page_url(page_num):
    return '/' if page_num == 1 else f'/page/{page_num}/'

def build_page(page_num, page_config, today, papers):
    print(f"  Rendering page {page_num}: {page_config['name']} ({len(papers)} papers)", flush=True)

    headline_paper = None
    other_papers = []
    if page_num == 1:
        if papers:
            headline_paper = papers[0]
            other_papers = papers[1:]
    else:
        other_papers = papers

    context = {
        'headline_paper': headline_paper,
        'other_papers': other_papers,
        'today': today,
        'current_page': page_num,
        'page_title': page_config['name'],
        'page_links': PAGE_LINKS,
        'page_mapping': PAGE_MAPPING,
        'page_url': page_url,   # passed for the static template
    }

    html = render_to_string('news/index_static.html', context)

    if page_num == 1:
        out_path = DIST / 'index.html'
    else:
        out_dir = DIST / 'page' / str(page_num)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / 'index.html'

    out_path.write_text(html, encoding='utf-8')
    print(f"  -> written to {out_path}", flush=True)

def copy_static():
    src = Path('news/static/news')
    dst = DIST / 'static' / 'news'
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        shutil.copy2(f, dst / f.name)
    print(f"  Static files copied to {dst}", flush=True)

def main():
    print("=== HEP Times static build ===", flush=True)
    DIST.mkdir(exist_ok=True)

    copy_static()

    today = datetime.now()
    pages = sorted(PAGE_MAPPING.items())

    # One combined arXiv request covers every page's category, instead of
    # one request per page — the build always renders all pages anyway.
    print("  Fetching combined batch for all pages...", flush=True)
    partitioned = fetch_and_partition_papers([cfg for _, cfg in pages])

    for (page_num, page_config), papers in zip(pages, partitioned):
        build_page(page_num, page_config, today, papers)

    print("=== Build complete ===", flush=True)

if __name__ == '__main__':
    main()
