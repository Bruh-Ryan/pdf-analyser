import requests
import sqlite3

def verify_step3():
    base_url = "http://127.0.0.1:5000"
    
    # 1. Trigger URL extraction again to save to DB
    print("Triggering URL processing...")
    try:
        data = {'url': 'http://example.com'}
        response = requests.post(base_url, data=data) 
        # Should redirect to /companies
        if response.history and response.url.endswith('/companies'):
             print("SUCCESS: Redirected to /companies after processing.")
        else:
             print(f"INFO: Response URL: {response.url}, Status: {response.status_code}")
    except Exception as e:
        print(f"ERROR: {e}")

    # 2. Check Database content
    print("\nChecking Database content...")
    try:
        conn = sqlite3.connect('demo.db')
        cursor = conn.cursor()
        rows = cursor.execute("SELECT company_name, source_type FROM companies").fetchall()
        conn.close()
        
        if len(rows) > 0:
            print(f"SUCCESS: Found {len(rows)} records in DB.")
            for row in rows:
                print(f" - {row}")
        else:
            print("FAILURE: No records found in DB.")

    except Exception as e:
        print(f"ERROR checking DB: {e}")

if __name__ == "__main__":
    verify_step3()
