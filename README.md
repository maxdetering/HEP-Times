# HEP Times

A Django-based newspaper website that fetches the latest papers from the arXiv `hep-ph` (High Energy Physics - Phenomenology) and `hep-th` (High Energy Physics - Theory) categories.

## Features

- **Newspaper Design**: Presents papers in a classic newspaper layout.
- **Latest Content**: Fetches the top 10 most recent submissions from arXiv.
- **Auto-generated**: The landing page is generated dynamically.

## Installation

1.  **Clone the repository**
2.  **Create a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
4.  **Run the server**:
    ```bash
    python manage.py runserver
    ```
5.  **Visit**: `http://127.0.0.1:8000/`

## Configuration

- The logic for fetching papers is in `news/utils.py`.
- The templates are in `news/templates/news/`.
- Styling is in `news/static/news/style.css`.
