import requests
import sqlite3

def verify_step4():
    base_url = "http://127.0.0.1:5000"
    
    # 1. Check if Detail page exists for ID 1 (assuming data exists from previous steps)
    # If DB was empty, we need to add something first.
    # Let's clean DB and add one entry to be sure or just add new one.
    
    print("Adding a test entry...")
    # Manually insert if needed or just upload?
    # Uploading is better integration test.
    try:
        data = {'url': 'http://example.com'}
        requests.post(base_url, data=data)
    except:
        pass

    # GetAll to find an ID
    conn = sqlite3.connect('demo.db')
    cursor = conn.cursor()
    row = cursor.execute("SELECT id FROM companies LIMIT 1").fetchone()
    conn.close()
    
    if row:
        id = row[0]
        print(f"Testing Detail Page for ID {id}...")
        try:
            resp = requests.get(f"{base_url}/company/{id}")
            if resp.status_code == 200 and "Extracted Text" in resp.text:
                print("SUCCESS: Detail page works.")
            else:
                print(f"FAILURE: Detail page status {resp.status_code}")
        except Exception as e:
            print(f"ERROR detail page: {e}")
    else:
        print("WARNING: No data in DB to test detail page.")

    # 2. Test Search
    print("Testing Search...")
    try:
        resp = requests.get(f"{base_url}/companies?q=Example")
        if resp.status_code == 200 and "Example" in resp.text:
             # It should find the company added above (Example Domain)
             print("SUCCESS: Search works.")
        else:
             print("FAILURE: Search did not return expected results.")
    except Exception as e:
        print(f"ERROR search: {e}")

if __name__ == "__main__":
    verify_step4()
