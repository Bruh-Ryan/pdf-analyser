import os
import secrets
import sqlite3
import requests
import pdfplumber
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from huggingface_hub import InferenceClient

app = Flask(__name__)
# Generate a secret key if not set (fine for demo reset on deploy)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(16))

# Vercel has read-only filesystem, use /tmp for temp storage
# Note: Data in /tmp is ephemeral and will be lost on redeploy/cold start
TEMP_DIR = '/tmp'
app.config['UPLOAD_FOLDER'] = os.path.join(TEMP_DIR, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload setup
app.config['DB_PATH'] = os.path.join(TEMP_DIR, 'demo.db')

# Hugging Face Setup
# Use a lightweight model for speed
HF_MODEL = "sshleifer/distilbart-cnn-12-6"
hf_token = os.environ.get('HF_TOKEN')
try:
    hf_client = InferenceClient(model=HF_MODEL, token=hf_token)
except Exception as e:
    print(f"Warning: Could not initialize HF Client: {e}")
    hf_client = None

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'pdf'}

def init_db():
    conn = sqlite3.connect(app.config['DB_PATH'])
    c = conn.cursor()
    # Ensure columns exist (including summary)
    c.execute('''
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_location TEXT NOT NULL,
            raw_text TEXT,
            summary TEXT,
            extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def get_db_connection():
    # Ensure DB exists before connecting (since /tmp can be wiped)
    if not os.path.exists(app.config['DB_PATH']):
        init_db()
    conn = sqlite3.connect(app.config['DB_PATH'])
    conn.row_factory = sqlite3.Row
    return conn

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def summarize_text(text):
    if not text or not hf_client:
        return None
    
    try:
        # Truncate text to avoid token limits (rough approx 1024 tokens)
        # Taking first 3000 chars is usually safe for distilbart
        input_text = text[:3000]
        
        summary = hf_client.summarization(input_text)
        # API returns a list of specific object or dict, usually [{'summary_text': '...'}]
        if summary and isinstance(summary, list) and 'summary_text' in summary[0]:
             return summary[0]['summary_text']
        elif summary and hasattr(summary, 'summary_text'):
             return summary.summary_text
        return None
    except Exception as e:
        print(f"Summarization failed: {e}")
        return None

def extract_text_from_pdf(pdf_path):
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
    except Exception as e:
        print(f"Error extracting PDF: {e}")
        return None
    return text

def extract_text_from_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
            
        text = soup.get_text()
        
        # Break into lines and remove leading and trailing space on each
        lines = (line.strip() for line in text.splitlines())
        # Break multi-headlines into a line each
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        # Drop blank lines
        text = '\n'.join(chunk for chunk in chunks if chunk)
        return text
    except Exception as e:
        print(f"Error fetching URL: {e}")
        return None

def save_company(name, source_type, source_location, text, summary=None):
    conn = get_db_connection()
    conn.execute('INSERT INTO companies (company_name, source_type, source_location, raw_text, summary) VALUES (?, ?, ?, ?, ?)',
                 (name, source_type, source_location, text, summary))
    conn.commit()
    conn.close()

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        custom_name = request.form.get('custom_name')
        
        # Check if the post request has the file part
        if 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                flash('No selected file')
                return redirect(request.url)
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                
                # Extract text
                text = extract_text_from_pdf(filepath)
                if text:
                    # Use custom name if provided, else filename
                    company_name = custom_name if custom_name else filename
                    
                    # Generate Summary
                    summary = summarize_text(text)
                    
                    # Save to DB
                    save_company(company_name, 'PDF', filename, text, summary)
                    msg = f'Successfully processed {company_name}'
                    if not summary:
                        msg += ' (Summary unavailable)'
                    flash(msg, 'success')
                    return redirect(url_for('companies'))
                else:
                    flash('Could not extract text from PDF', 'error')
                    return redirect(request.url)
        
        # Check for URL submission
        url = request.form.get('url')
        if url:
            text = extract_text_from_url(url)
            if text:
                 # Use custom name if provided, else use parse
                 company_name = custom_name
                 if not company_name:
                     from urllib.parse import urlparse
                     company_name = urlparse(url).netloc

                 # Generate Summary
                 summary = summarize_text(text)

                 save_company(company_name, 'URL', url, text, summary)
                 msg = f'Successfully processed {company_name}'
                 if not summary:
                     msg += ' (Summary unavailable)'
                 flash(msg, 'success')
                 return redirect(url_for('companies'))
            else:
                flash(f'Could not fetch content from {url}', 'error')
                return redirect(request.url)
            
    return render_template('index.html')

@app.route('/companies')
def companies():
    query = request.args.get('q')
    conn = get_db_connection()
    if query:
        # Simple search
        sql = "SELECT * FROM companies WHERE company_name LIKE ? OR raw_text LIKE ? ORDER BY id DESC"
        args = (f'%{query}%', f'%{query}%')
        companies = conn.execute(sql, args).fetchall()
    else:
        companies = conn.execute('SELECT * FROM companies ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('list.html', companies=companies)

@app.route('/company/<int:id>')
def company_detail(id):
    conn = get_db_connection()
    company = conn.execute('SELECT * FROM companies WHERE id = ?', (id,)).fetchone()
    conn.close()
    if company is None:
        return "Company not found", 404
    return render_template('detail.html', company=company)

# Required for Vercel
app = app

if __name__ == '__main__':
    app.run(debug=True, port=5000)
