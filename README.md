# Company Data Processing System MVP

A minimal Flask application to extract, store, and retrieve text from PDFs and URLs.

## Features
- **Upload**: Accepts PDF files or URL inputs.
- **Extraction**:
  - Extracts text from PDFs using `pdfplumber`.
  - Scrapes text from URLs using `requests` and `BeautifulSoup`.
- **Storage**: Persists extracted data in a local SQLite database (`demo.db`).
- **Retrieval**: Lists stored companies and allows searching by keyword.
- **Detail View**: Displays full extracted text for review.

## Tech Stack
- Python 3
- Flask
- SQLite
- pdfplumber, requests, beautifulsoup4

## Setup Instructions

1.  **Clone/Navigate to directory**:
    ```bash
    cd /Users/ryan/demo-project
    ```

2.  **Install Dependencies**:
    ```bash
    pip install flask pdfplumber requests beautifulsoup4 reportlab
    ```
    *(Note: `reportlab` is only needed if you want to generate test PDFs via `generate_pdf.py`)*

3.  **Initialize Database**:
    ```bash
    python3 init_db.py
    ```

4.  **Run Application**:
    ```bash
    python3 app.py
    ```
    The app will be available at [http://127.0.0.1:5000](http://127.0.0.1:5000).

## Usage Flow
1.  Go to Homepage.
2.  Upload a PDF or enter a URL.
3.  The system automatically extracts text and saves it to the database.
4.  You are redirected to the Company List.
5.  Use the search bar to find specific content.
6.  Click "View Details" to see the full text.

## Structure
- `app.py`: Main application logic.
- `init_db.py`: Database initialization script.
- `templates/`: HTML templates (`layout.html`, `index.html`, `list.html`, `detail.html`).
- `uploads/`: Temporary storage for uploaded files.
- `demo.db`: SQLite database file.
