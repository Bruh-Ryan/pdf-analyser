import os
import secrets
import sqlite3
import requests
import fitz  # PyMuPDF
import google.generativeai as genai
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from io import BytesIO
import base64

app = Flask(__name__)
# Generate a secret key if not set (fine for demo reset on deploy)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(16))

# Vercel has read-only filesystem, use /tmp for temp storage
# Note: Data in /tmp is ephemeral and will be lost on redeploy/cold start
TEMP_DIR = '/tmp'
app.config['UPLOAD_FOLDER'] = os.path.join(TEMP_DIR, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload setup
app.config['DB_PATH'] = os.path.join(TEMP_DIR, 'demo.db')

# Gemini Setup
# User provided key - prioritizing env var but falling back to hardcoded for demo
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', 'AIzaSyA7VUHQA0mNblXG10qEM9WGuf3k0LJVEdI')

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Use flash model for speed and cost
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"Error configuring Gemini: {e}")
        model = None
else:
    model = None
    print("Warning: GEMINI_API_KEY not found. AI features will be disabled.")

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
            deep_analysis TEXT,
            extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    try:
        c.execute('ALTER TABLE companies ADD COLUMN summary TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        c.execute('ALTER TABLE companies ADD COLUMN deep_analysis TEXT')
    except sqlite3.OperationalError:
        pass
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
    if not text or not model:
        return None
    
    try:
        # Gemini handles large context well, but safe limit is good practice
        # Verify text is not too short
        if len(text) < 50:
            return "Text too short to summarize."

        prompt = f"Please provide a concise summary of the following company information:\n\n{text[:30000]}"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Summarization failed: {e}")
        return None

def extract_text_via_ocr(pdf_path):
    """
    Fallback for Scanned PDFs using OCR.space Cloud API
    Free tier: 25,000 requests/month, no system dependencies needed
    """
    full_text = ""
    try:
        print("Scanned PDF detected. Attempting OCR with OCR.space API...")
        
        # OCR.space API endpoint
        url = "https://api.ocr.space/parse/image"
        
        # Open PDF and convert pages to images
        doc = fitz.open(pdf_path)
        
        # Process first 5 pages for demo (free tier has limits)
        for page_num in range(min(5, len(doc))):
            page = doc[page_num]
            
            # Render page to image (PNG format, 300 DPI for good OCR)
            pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))
            img_bytes = pix.tobytes("png")
            
            # Encode image to base64 for API
            img_base64 = base64.b64encode(img_bytes).decode()
            
            # Call OCR.space API
            payload = {
                'base64Image': f"data:image/png;base64,{img_base64}",
                'language': 'eng',
                'isOverlayRequired': False,
                'detectOrientation': True,
                'scale': True,
                'OCREngine': 2,  # Engine 2 is more accurate
            }
            
            response = requests.post(url, data=payload, timeout=30)
            result = response.json()
            
            # Extract text from response
            if result.get('ParsedResults'):
                page_text = result['ParsedResults'][0].get('ParsedText', '')
                if page_text.strip():
                    full_text += page_text + "\n"
            
            # Check for API errors
            if result.get('IsErroredOnProcessing'):
                error_msg = result.get('ErrorMessage', ['Unknown error'])[0]
                print(f"OCR.space error on page {page_num + 1}: {error_msg}")
        
        doc.close()
        
        if full_text.strip():
            return full_text, None
        else:
            return None, "No text could be extracted from the scanned PDF"
            
    except Exception as e:
        print(f"OCR.space API failed: {e}")
        return None, f"OCR Failed: {e}"

def perform_deep_analysis(pdf_path):
    """
    Perform deep analysis of PDF content using Gemini
    Note: Disabled visual analysis due to API compatibility issues
    """
    if not model:
        return None
    
    try:
        # Extract text first
        text, error = extract_text_from_pdf(pdf_path)
        if not text:
            return None
        
        # Use Gemini for text-based deep analysis only
        prompt = f"""
Analyze this document and provide:
1. Key topics and themes
2. Important data points, numbers, or statistics mentioned
3. Main insights or conclusions
4. What questions does this document answer?

Document content:
{text[:10000]}

Be specific and concise.
"""
        response = model.generate_content(prompt)
        
        if response.text:
            return response.text
        else:
            return None
            
    except Exception as e:
        print(f"Deep analysis failed: {e}")
        return None

def extract_text_from_pdf(pdf_path):
    """
    Extract text from PDF using PyMuPDF (fitz)
    Falls back to OCR.space API for scanned PDFs
    """
    text = ""
    try:
        # Open PDF with PyMuPDF
        doc = fitz.open(pdf_path)
        
        if len(doc) == 0:
            return None, "Empty PDF file"
        
        # 1. Try Standard Text Extraction with PyMuPDF
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text()
            if page_text:
                text += page_text + "\n"
        
        doc.close()
        
        # 2. Check if text is sufficient (OCR fallback for scanned PDFs)
        if not text.strip() or len(text.strip()) < 100:
            print("Text too sparse, attempting OCR.space API...")
            ocr_text, ocr_error = extract_text_via_ocr(pdf_path)
            if ocr_text:
                text = ocr_text
            elif not text.strip():  # Only return error if we still have no text
                error_msg = f"Scanned PDF detected. OCR failed: {ocr_error}" if ocr_error else "Scanned PDF detected. OCR yielded no text."
                return None, error_msg

    except Exception as e:
        print(f"Error extracting PDF: {e}")
        return None, str(e)
    
    return text, None

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
                text, error = extract_text_from_pdf(filepath)
                
                if text:
                    # Use custom name if provided, else filename
                    company_name = custom_name if custom_name else filename
                    
                    # Generate Summary
                    summary = summarize_text(text)
                    
                    # Save to DB
                    save_company(company_name, 'PDF', filename, text, summary)
                    msg = f'Successfully processed {company_name}'
                    if not summary:
                        msg += ' (AI Summary unavailable - check API key)'
                    flash(msg, 'success')
                    return redirect(url_for('companies'))
                else:
                    msg = f"Failed to process PDF: {error}" if error else "Could not extract text"
                    flash(msg, 'error')
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

@app.route('/analyze/<int:id>', methods=['POST'])
def deep_analyze(id):
    conn = get_db_connection()
    company = conn.execute('SELECT * FROM companies WHERE id = ?', (id,)).fetchone()
    
    if company is None:
        flash('Company not found', 'error')
        return redirect(url_for('companies'))
    
    # If already has deep analysis, return it
    if company['deep_analysis']:
        flash('Analysis already exists!', 'info')
        return redirect(url_for('company_detail', id=id))
    
    # Perform deep analysis for PDFs only
    if company['source_type'] == 'PDF':
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], company['source_location'])
        
        if os.path.exists(filepath):
            analysis = perform_deep_analysis(filepath)
            
            if analysis:
                # Update the record with deep analysis
                conn = get_db_connection()
                conn.execute('UPDATE companies SET deep_analysis = ? WHERE id = ?', (analysis, id))
                conn.commit()
                conn.close()
                flash('Deep analysis complete!', 'success')
            else:
                flash('Deep analysis failed. Please try again later.', 'error')
        else:
            flash('PDF file not found. File may have been deleted.', 'error')
    else:
        flash('Deep analysis is only available for PDFs', 'warning')
    
    return redirect(url_for('company_detail', id=id))

# Required for Vercel
app = app

if __name__ == '__main__':
    app.run(debug=True, port=5000)
