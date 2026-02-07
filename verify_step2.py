import requests

def verify_extraction():
    base_url = "http://127.0.0.1:5000"
    
    # 1. Test URL Extraction
    print("Testing URL Extraction...")
    try:
        data = {'url': 'http://example.com'}
        response = requests.post(base_url, data=data)
        if response.status_code == 200 and "Example Domain" in response.text:
            print("SUCCESS: URL Extraction works.")
        else:
            print(f"FAILURE: URL Extraction failed. Status: {response.status_code}")
    except Exception as e:
        print(f"ERROR testing URL: {e}")

    # 2. Test PDF Upload
    print("\nTesting PDF Upload...")
    try:
        files = {'file': open('sample.pdf', 'rb')}
        response = requests.post(base_url, files=files)
        if response.status_code == 200 and "Hello, this is a test PDF" in response.text:
            print("SUCCESS: PDF Extraction works.")
        else:
             print(f"FAILURE: PDF Extraction failed. Status: {response.status_code}")
    except Exception as e:
        print(f"ERROR testing PDF: {e}")

if __name__ == "__main__":
    verify_extraction()
