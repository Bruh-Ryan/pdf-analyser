import os
import secrets
import sqlite3
import requests
import fitz  
import google.generativeai as genai
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from io import BytesIO
import base64
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# Generate a secret key if not set (fine for demo reset on deploy)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(16))

# Vercel has read-only filesystem, use /tmp for temp storage
# Note: Data in /tmp is ephemeral and will be lost on redeploy/cold start
TEMP_DIR = '/tmp'
app.config['UPLOAD_FOLDER'] = os.path.join(TEMP_DIR, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload setup
app.config['DB_PATH'] = os.path.join(TEMP_DIR, 'demo.db')

# Gemini Setup - HARDCODED FOR TESTING
GEMINI_API_KEY = 'AIzaSyB8NuS1DcdGhk9OYQsgPWuysP_mJBjsP94'

try:
    print(f"Configuring Gemini with key: {GEMINI_API_KEY[:5]}...")
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.0-flash')
    print("Gemini model configured successfully!")
except Exception as e:
    print(f"Error configuring Gemini: {e}")
    model = None

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
                'apikey': 'K81894572788957', 
                'base64Image': f"data:image/png;base64,{img_base64}",
                'language': 'eng',
                'isOverlayRequired': False,
                'detectOrientation': True,
                'scale': True,
                'OCREngine': 2, # Engine 2 is more accurate
            }
            
            response = requests.post(url, data=payload, timeout=30)
            
            # Check if request was successful
            if response.status_code != 200:
                print(f"OCR.space API returned status {response.status_code}: {response.text}")
                continue
                
            # Parse JSON response
            try:
                result = response.json()
            except Exception as json_error:
                print(f"Failed to parse OCR.space response as JSON: {json_error}")
                print(f"Response text: {response.text[:200]}")
                continue

            if result.get('IsErroredOnProcessing'):
                print(f"OCR Error on page {page_num}: {result.get('ErrorMessage')}")
                continue
                
            parsed_results = result.get('ParsedResults')
            if parsed_results and isinstance(parsed_results, list):
                page_text = parsed_results[0].get('ParsedText', '')
                full_text += page_text + "\n"
            else:
                print(f"No parsed results for page {page_num}")
                
        if not full_text.strip():
            return None, "OCR could not extract text (image quality too low?)"
            
        return full_text, None

    except Exception as e:
        print(f"OCR Failed: {e}")
        return None, f"OCR Failed: {str(e)}"

def extract_text_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        
        # If very little text, assume it's scanned and try OCR
        if len(text.strip()) < 50:
            print("Text too short, attempting OCR fallback...")
            ocr_text, error = extract_text_via_ocr(pdf_path)
            if ocr_text:
                return ocr_text, None
            # If OCR fails, return original tiny text (better than nothing) or error
            if not text.strip():
                return None, error or "Empty PDF and OCR failed"
        
        return text, None
    except Exception as e:
        return None, str(e)

def extract_text_from_url(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove scripts and styles
        for script in soup(["script", "style"]):
            script.decompose()
            
        text = soup.get_text()
        
        # Break multi-headlines into a line each
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

def perform_deep_analysis(filepath):
    """
    Uploads the file to Gemini and requests a detailed analysis
    """
    if not model:
        return None

    try:
        # Upload the file to Gemini
        print(f"Uploading file to Gemini: {filepath}")
        uploaded_file = genai.upload_file(filepath)
        
        # Generate content with the file and prompt
        prompt = """
        Analyze this document thoroughly. Provide:
        1. Key Financial Data (if any)
        2. Main Risks or Challenges
        3. Strategic Opportunities
        4. A final conclusion on the document's outlook.
        """
        
        response = model.generate_content([prompt, uploaded_file])
        return response.text
        
    except Exception as e:
        print(f"Deep analysis failed: {e}")
        return None

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
