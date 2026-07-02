import requests
import sys

URL = 'http://localhost:5000/admin.html'
EXPECTED_MARKER = 'Admin Login'

if __name__ == '__main__':
    try:
        r = requests.get(URL, timeout=5)
    except Exception as e:
        print('ERROR: cannot fetch', URL, e)
        sys.exit(2)
    if r.status_code != 200:
        print('ERROR: status', r.status_code)
        sys.exit(2)
    text = r.text
    if EXPECTED_MARKER in text:
        print('OK: marker found in admin.html')
        sys.exit(0)
    else:
        print('ERROR: expected marker not found in admin.html')
        sys.exit(3)
