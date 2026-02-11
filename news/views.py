from django.shortcuts import render
from .utils import fetch_arxiv_papers, fetch_latest_papers
from datetime import datetime

# Page Number to Category Mapping
# Page 1: Front Page (Mixed latest)
# Page 2: hep-ph
# Page 3: hep-th
# Page 4: hep-lat
# Page 5: gr-qc
# Page 6: astro-ph
PAGE_MAPPING = {
    1: {'name': 'Front Page', 'query': 'cat:hep-ph OR cat:hep-th', 'limit': 10},
    2: {'name': 'Phenomenology (hep-ph)', 'query': 'cat:hep-ph', 'limit': 20},
    3: {'name': 'Theory (hep-th)', 'query': 'cat:hep-th', 'limit': 20},
    4: {'name': 'Lattice (hep-lat)', 'query': 'cat:hep-lat', 'limit': 20},
    5: {'name': 'GR & QC (gr-qc)', 'query': 'cat:gr-qc', 'limit': 20},
    6: {'name': 'Astrophysics (astro-ph)', 'query': 'cat:astro-ph', 'limit': 20},
}

def index(request, page_num=1):
    # Default to page 1 if not exists or out of range
    if page_num not in PAGE_MAPPING:
        page_num = 1
        
    page_config = PAGE_MAPPING[page_num]
    
    # Fetch papers
    papers = fetch_arxiv_papers(query=page_config['query'], max_results=page_config['limit'])
    
    headline_paper = None
    other_papers = []
    
    # On the front page (Page 1), we do the special headline layout
    if page_num == 1:
        if papers:
            headline_paper = papers[0]
            other_papers = papers[1:]
    else:
        # On rubric pages, list all in the grid.
        other_papers = papers
        
    # Generate page links [1, 2, 3, 4, 5, 6]
    page_links = sorted(PAGE_MAPPING.keys())

    context = {
        'headline_paper': headline_paper,
        'other_papers': other_papers,
        'today': datetime.now(),
        'current_page': page_num,
        'page_title': page_config['name'],
        'page_links': page_links,
        'page_mapping': PAGE_MAPPING, # To access names if needed in template
    }
    return render(request, 'news/index.html', context)
