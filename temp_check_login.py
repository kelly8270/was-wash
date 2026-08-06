import json
import urllib.request

data = json.dumps({'email': 'test@example.com', 'password': 'bad'}).encode()
req = urllib.request.Request('http://127.0.0.1:5001/api/login', data=data, headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req, timeout=10) as r:
    print('status', r.status)
    print(r.read().decode('utf-8', 'replace'))
