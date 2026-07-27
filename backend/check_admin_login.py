from app import app, ADMIN_EMAIL, ADMIN_PASSWORD, init_db


def run_check():
    client = app.test_client()

    # Attempt admin login
    resp = client.post('/api/login', json={'email': ADMIN_EMAIL, 'password': ADMIN_PASSWORD})
    print('Login status:', resp.status_code)
    try:
        data = resp.get_json()
    except Exception:
        data = None
    print('Login response:', data)

    if resp.status_code != 200:
        print('Admin login failed; cannot verify admin dashboard.')
        return 1

    token = data.get('token')
    headers = {'Authorization': f'Bearer {token}'}

    # Fetch admin users
    resp2 = client.get('/api/admin/users', headers=headers)
    print('Admin users status:', resp2.status_code)
    try:
        users = resp2.get_json()
    except Exception:
        users = None
    if isinstance(users, list):
        print('Number of users returned:', len(users))
        if len(users) > 0:
            print('First user:', users[0])
    else:
        print('Admin users response:', users)

    return 0


if __name__ == '__main__':
    try:
        init_db()
    except Exception as e:
        print('init_db error (may be safe if DB already initialized):', e)
    raise SystemExit(run_check())
