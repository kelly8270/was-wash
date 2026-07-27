from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from functools import wraps
from datetime import datetime, timedelta
import sqlite3
import hashlib
import os
import re
import json
import time
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)

# Admin seed credentials
ADMIN_EMAIL = 'kelvinkgichuki@gmail.com'
ADMIN_PASSWORD = 'Kelly@8270'

# Configuration - persist JWT secret so tokens survive restarts
secret_path = os.path.join(os.path.dirname(__file__), '.jwt_secret')
if os.path.exists(secret_path):
    with open(secret_path, 'r') as f:
        jwt_secret = f.read().strip()
else:
    jwt_secret = os.urandom(32).hex()
    try:
        # write file with restricted permissions where possible
        with open(secret_path, 'w') as f:
            f.write(jwt_secret)
        try:
            os.chmod(secret_path, 0o600)
        except Exception:
            pass
    except Exception:
        # fallback to in-memory secret if file cannot be written
        pass

app.config['JWT_SECRET_KEY'] = jwt_secret
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=7)
jwt = JWTManager(app)

DATABASE = os.path.join(os.path.dirname(__file__), 'earnings.db')
FRONTEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))
LOGIN_ATTEMPTS = {}
LOGIN_ATTEMPT_LIMIT = 5
LOGIN_ATTEMPT_WINDOW_SECONDS = 15 * 60

def ensure_column_exists(conn, table_name, column_name, column_type, unique=False):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        columns.append(column_name)
    if unique and column_name in columns:
        cursor.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table_name}_{column_name} ON {table_name}({column_name})")

# ===== DATABASE SETUP =====
def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT NOT NULL,
            gender TEXT,
            age INTEGER,
            total_deposited REAL DEFAULT 0,
            total_earned REAL DEFAULT 0,
            available_balance REAL DEFAULT 0,
            daily_earnings REAL DEFAULT 0,
            last_login_date DATE,
            referral_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    ensure_column_exists(conn, 'users', 'referral_code', 'TEXT', unique=True)
    ensure_column_exists(conn, 'users', 'last_login_date', 'DATE')
    ensure_column_exists(conn, 'users', 'last_login_at', 'TIMESTAMP')
    ensure_column_exists(conn, 'users', 'is_admin', 'INTEGER DEFAULT 0')
    ensure_column_exists(conn, 'users', 'gender', 'TEXT')
    ensure_column_exists(conn, 'users', 'age', 'INTEGER')
    ensure_column_exists(conn, 'users', 'agree_terms', 'INTEGER DEFAULT 0')
    ensure_column_exists(conn, 'users', 'agree_terms_at', 'TIMESTAMP')

    # Ensure admin user exists
    c.execute('SELECT id FROM users WHERE email = ?', (ADMIN_EMAIL,))
    if c.fetchone():
        c.execute('UPDATE users SET password = ?, is_admin = 1 WHERE email = ?',
                  (hash_password(ADMIN_PASSWORD), ADMIN_EMAIL))
    else:
        c.execute('INSERT INTO users (name, email, password, phone, is_admin) VALUES (?, ?, ?, ?, 1)',
                  ('Admin', ADMIN_EMAIL, hash_password(ADMIN_PASSWORD), '0000000000'))

    # Referrals table
    c.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL,
            reward_amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            deposit_id INTEGER,
            awarded_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (referrer_id) REFERENCES users(id),
            FOREIGN KEY (referred_id) REFERENCES users(id),
            FOREIGN KEY (deposit_id) REFERENCES deposits(id),
            UNIQUE(referrer_id, referred_id)
        )
    ''')
    ensure_column_exists(conn, 'referrals', 'status', 'TEXT')
    ensure_column_exists(conn, 'referrals', 'deposit_id', 'INTEGER')
    ensure_column_exists(conn, 'referrals', 'awarded_at', 'TIMESTAMP')

    # Deposits table
    c.execute('''
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            mpesa_code TEXT NOT NULL,
            mpesa_number TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Earnings table (daily claims)
    c.execute('''
        CREATE TABLE IF NOT EXISTS earnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, date)
        )
    ''')

    # Activity rewards table - once per activity per user per day after login
    c.execute('''
        CREATE TABLE IF NOT EXISTS activity_rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            activity TEXT NOT NULL,
            reward_amount REAL NOT NULL,
            date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, activity, date)
        )
    ''')
    
    # Withdrawals table
    c.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            phone TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # Investments table
    c.execute('''
        CREATE TABLE IF NOT EXISTS investments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            package_name TEXT,
            image TEXT,
            status TEXT DEFAULT 'active',
            start_date TIMESTAMP,
            maturity_date TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # Surveys table - store one-time survey completions and answers
    c.execute('''
        CREATE TABLE IF NOT EXISTS surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            answers TEXT NOT NULL,
            reward_amount REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id)
        )
    ''')

    # Ratings table - allow one rating per user and store comments
    c.execute('''
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT,
            reward_amount REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id)
        )
    ''')

    # Ad completions table - one-time ad watch reward
    c.execute('''
        CREATE TABLE IF NOT EXISTS ad_completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reward_amount REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id)
        )
    ''')

    # Messages table - transaction/support messages from users
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            admin_response TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # Ensure existing users have referral codes
    c.execute("SELECT id FROM users WHERE referral_code IS NULL OR referral_code = ''")
    for row in c.fetchall():
        user_id = row[0]
        c.execute('UPDATE users SET referral_code = ? WHERE id = ?', (f'REF{user_id}', user_id))
    
    conn.commit()
    conn.close()

def table_exists(conn, table_name):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cursor.fetchone() is not None


def get_db():
    if not os.path.exists(DATABASE):
        init_db()
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    if not table_exists(conn, 'users'):
        conn.close()
        init_db()
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
    return conn

# ===== HELPERS =====
def hash_password(password):
    # Use Werkzeug's secure PBKDF2 hashing
    return generate_password_hash(password)

def validate_password(password):
    if len(password) < 8:
        return 'Password must be at least 8 characters long.'
    if not re.search(r'[A-Z]', password):
        return 'Password must include at least one uppercase letter.'
    if not re.search(r'[a-z]', password):
        return 'Password must include at least one lowercase letter.'
    if not re.search(r'\d', password):
        return 'Password must include at least one number.'
    if not re.search(r'[!@#$%^&*(),.?":{}|<>\[\]\\/;\'`~_-]', password):
        return 'Password must include at least one special character.'
    return None


def validate_email(email):
    pattern = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
    return bool(re.fullmatch(pattern, email))


def validate_phone(phone):
    cleaned = re.sub(r'\D', '', phone)
    return len(cleaned) >= 10 and len(cleaned) <= 15


def is_login_recent(last_login_at):
    if not last_login_at:
        return False
    try:
        last_login = datetime.fromisoformat(last_login_at)
    except Exception:
        return False
    return datetime.now() - last_login <= timedelta(hours=24)


def check_login_rate_limit(email, ip_address):
    key = f'{ip_address}:{email.lower()}'
    now = time.time()
    attempts = LOGIN_ATTEMPTS.get(key, [])
    attempts = [attempt for attempt in attempts if now - attempt < LOGIN_ATTEMPT_WINDOW_SECONDS]
    if len(attempts) >= LOGIN_ATTEMPT_LIMIT:
        LOGIN_ATTEMPTS[key] = attempts
        return True
    attempts.append(now)
    LOGIN_ATTEMPTS[key] = attempts
    return False


def clear_login_rate_limit(email, ip_address):
    key = f'{ip_address}:{email.lower()}'
    LOGIN_ATTEMPTS.pop(key, None)


def calculate_daily_earnings(deposit_amount):
    """Calculate 10% daily earnings"""
    return deposit_amount * 0.10


def is_admin_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT is_admin FROM users WHERE id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    return bool(row and row['is_admin'] == 1)


def admin_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user_id = get_jwt_identity()
        if not is_admin_user(user_id):
            return jsonify({'error': 'Admin access required'}), 403
        return fn(*args, **kwargs)
    return wrapper

# ===== AUTH ROUTES =====
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid request data'}), 400

    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    phone = data.get('phone', '').strip()
    gender = data.get('gender', '').strip()
    age_raw = data.get('age')
    age = None
    referrer_code = data.get('referrer_code', '').strip()
    agree_terms = data.get('agree_terms', False)
    
    if not all([name, email, password, phone]):
        return jsonify({'error': 'All fields are required'}), 400

    if not agree_terms:
        return jsonify({'error': 'You must accept the Terms and Conditions to register'}), 400

    if not validate_email(email):
        return jsonify({'error': 'Invalid email format'}), 400

    if not validate_phone(phone):
        return jsonify({'error': 'Please provide a valid mobile number'}), 400

    password_error = validate_password(password)
    if password_error:
        return jsonify({'error': password_error}), 400

    if age_raw not in (None, ''):
        try:
            age = int(age_raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'Age must be a whole number'}), 400
        if age < 1 or age > 120:
            return jsonify({'error': 'Age must be between 1 and 120'}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT id FROM users WHERE email = ?', (email,))
    if c.fetchone():
        conn.close()
        return jsonify({'error': 'Email already registered'}), 409

    c.execute('SELECT id FROM users WHERE phone = ?', (phone,))
    if c.fetchone():
        conn.close()
        return jsonify({'error': 'This mobile number is already registered'}), 409
    
    # Create user
    hashed_pw = hash_password(password)
    now = datetime.now().isoformat()
    c.execute('''
        INSERT INTO users (name, email, password, phone, gender, age, agree_terms, agree_terms_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, email, hashed_pw, phone, gender or None, age, 1, now))
    
    user_id = c.lastrowid
    referral_code = f'REF{user_id}'
    c.execute('UPDATE users SET referral_code = ? WHERE id = ?', (referral_code, user_id))

    if referrer_code:
        c.execute('SELECT id FROM users WHERE referral_code = ?', (referrer_code,))
        referrer = c.fetchone()
        if referrer and referrer['id'] != user_id:
            c.execute('SELECT id FROM referrals WHERE referrer_id = ? AND referred_id = ?', (referrer['id'], user_id))
            if not c.fetchone():
                reward_amount = 100
                c.execute('''
                    INSERT INTO referrals (referrer_id, referred_id, reward_amount)
                    VALUES (?, ?, ?)
                ''', (referrer['id'], user_id, reward_amount))

    conn.commit()
    conn.close()
    
    token = create_access_token(identity=str(user_id))
    return jsonify({
        'message': 'User registered successfully',
        'token': token,
        'user': {'id': user_id, 'name': name, 'email': email, 'referral_code': referral_code, 'gender': gender or None, 'age': age}
    }), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid request data'}), 400

    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()

    if check_login_rate_limit(email, ip_address):
        return jsonify({'error': 'Too many login attempts. Please try again later.'}), 429
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT * FROM users WHERE email = ?', (email,))
    user = c.fetchone()

    if not user or not check_password_hash(user['password'], password):
        conn.close()
        return jsonify({'error': 'Invalid email or password'}), 401

    clear_login_rate_limit(email, ip_address)
    
    # Auto-grant daily login reward
    today = datetime.now().date()
    now_iso = datetime.now().isoformat()
    last_login = user['last_login_date']
    daily_login_bonus = 100  # KSH 100 daily login reward
    
    if last_login != str(today):
        # First login of the day, grant reward
        new_balance = user['available_balance'] + daily_login_bonus
        c.execute('''
            UPDATE users 
            SET available_balance = ?, last_login_date = ?, last_login_at = ?
            WHERE id = ?
        ''', (new_balance, today, now_iso, user['id']))
        conn.commit()
    else:
        c.execute('''
            UPDATE users
            SET last_login_at = ?
            WHERE id = ?
        ''', (now_iso, user['id']))
        conn.commit()
    
    conn.close()
    
    token = create_access_token(identity=str(user['id']))
    return jsonify({
        'token': token,
        'user': {
            'id': user['id'],
            'name': user['name'],
            'email': user['email'],
            'phone': user['phone'],
            'referral_code': user['referral_code'],
            'gender': user['gender'],
            'age': user['age']
        }
    }), 200

# ===== DEPOSIT ROUTES =====
@app.route('/api/deposit', methods=['POST'])
@jwt_required()
def create_deposit():
    user_id = get_jwt_identity()
    data = request.get_json()
    amount = data.get('amount')
    mpesa_code = data.get('mpesa_code', '').strip().upper()
    mpesa_number = data.get('mpesa_number', '').strip()
    
    valid_amounts = [2000, 5000, 8000, 12000, 15000]
    if amount not in valid_amounts:
        return jsonify({'error': 'Invalid deposit amount'}), 400
    
    if not mpesa_code or len(mpesa_code) < 6:
        return jsonify({'error': 'Invalid M-Pesa code'}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    # Check for duplicate code
    c.execute('SELECT id FROM deposits WHERE mpesa_code = ?', (mpesa_code,))
    if c.fetchone():
        conn.close()
        return jsonify({'error': 'This M-Pesa code has already been used'}), 409
    
    c.execute('''
        INSERT INTO deposits (user_id, amount, mpesa_code, mpesa_number)
        VALUES (?, ?, ?, ?)
    ''', (user_id, amount, mpesa_code, mpesa_number))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'message': 'Deposit request submitted, waiting for admin confirmation.',
        'amount': amount,
        'status': 'pending'
    }), 200


@app.route('/api/invest', methods=['POST'])
@jwt_required()
def create_investment():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    try:
        amount = float(data.get('amount', 0))
    except Exception:
        return jsonify({'error': 'Invalid amount'}), 400
    package = data.get('package', '').strip()
    image = data.get('image', '').strip()

    if amount <= 0:
        return jsonify({'error': 'Amount must be greater than zero'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT available_balance FROM users WHERE id = ?', (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'User not found'}), 404
    if row['available_balance'] < amount:
        conn.close()
        return jsonify({'error': 'Insufficient balance to invest'}), 400

    now = datetime.now()
    maturity = now + timedelta(days=60)

    # Deduct user balance and create investment
    c.execute('UPDATE users SET available_balance = available_balance - ? WHERE id = ?', (amount, user_id))
    c.execute('''
        INSERT INTO investments (user_id, amount, package_name, image, status, start_date, maturity_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, amount, package or None, image or None, 'active', now.isoformat(), maturity.isoformat()))
    inv_id = c.lastrowid
    conn.commit()
    conn.close()

    return jsonify({'message': 'Investment created', 'investment_id': inv_id, 'maturity_date': maturity.isoformat()}), 201


@app.route('/api/user/investments', methods=['GET'])
@jwt_required()
def get_user_investments():
    user_id = get_jwt_identity()
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM investments WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(rows), 200


@app.route('/api/user/investments/withdraw', methods=['POST'])
@jwt_required()
def withdraw_investment():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    inv_id = data.get('investment_id')
    if not inv_id:
        return jsonify({'error': 'Investment id required'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM investments WHERE id = ? AND user_id = ?', (inv_id, user_id))
    inv = c.fetchone()
    if not inv:
        conn.close()
        return jsonify({'error': 'Investment not found'}), 404
    if inv['status'] != 'active':
        conn.close()
        return jsonify({'error': 'Investment already withdrawn or closed'}), 400

    try:
        maturity = datetime.fromisoformat(inv['maturity_date'])
    except Exception:
        conn.close()
        return jsonify({'error': 'Invalid maturity date'}), 500

    if datetime.now() < maturity:
        conn.close()
        return jsonify({'error': 'Investment not yet matured'}), 400

    # Mark withdrawn and credit user's available balance
    c.execute('UPDATE investments SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', ('withdrawn', inv_id))
    c.execute('UPDATE users SET available_balance = available_balance + ? WHERE id = ?', (inv['amount'], user_id))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Investment withdrawn and amount credited to available balance'}), 200

@app.route('/api/messages', methods=['POST'])
@jwt_required()
def send_message():
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid request data'}), 400

    subject = data.get('subject', '').strip()
    body = data.get('body', '').strip()
    if not subject or not body:
        return jsonify({'error': 'Subject and message body are required'}), 400

    user_id = get_jwt_identity()
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO messages (user_id, subject, body) VALUES (?, ?, ?)',
              (user_id, subject, body))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Message submitted successfully', 'status': 'pending'}), 201

# ===== DASHBOARD =====
@app.route('/api/user/dashboard', methods=['GET'])
@jwt_required()
def get_dashboard():
    user_id = get_jwt_identity()
    today = datetime.now().date()
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    
    # Check if earnings already claimed today
    c.execute('SELECT * FROM earnings WHERE user_id = ? AND date = ?', (user_id, today))
    today_earnings = c.fetchone()

    c.execute('SELECT activity FROM activity_rewards WHERE user_id = ? AND date = ?', (user_id, today))
    completed_activities = {row['activity']: True for row in c.fetchall()}
    
    c.execute('SELECT COUNT(*) AS pending_count FROM deposits WHERE user_id = ? AND status = ?', (user_id, 'pending'))
    pending_count = c.fetchone()['pending_count']
    
    c.execute('SELECT id, subject, body, status, admin_response, created_at, updated_at FROM messages WHERE user_id = ? ORDER BY created_at DESC LIMIT 5',
              (user_id,))
    messages = [dict(row) for row in c.fetchall()]
    conn.close()
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({
        'name': user['name'],
        'email': user['email'],
        'phone': user['phone'],
        'gender': user['gender'],
        'age': user['age'],
        'total_deposited': user['total_deposited'],
        'daily_earnings': user['daily_earnings'],
        'total_earned': user['total_earned'],
        'available_balance': user['available_balance'],
        'referral_code': user['referral_code'],
        'pending_deposit_count': pending_count,
        'task_status': {
            'ad': bool(completed_activities.get('ad')),
            'survey': bool(completed_activities.get('survey'))
        },
        'messages': messages
    }), 200

# ===== CLAIM EARNINGS =====
@app.route('/api/user/deposits', methods=['GET'])
@jwt_required()
def get_user_deposits():
    user_id = get_jwt_identity()
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT id, amount, mpesa_code, mpesa_number, status, created_at
        FROM deposits
        WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (user_id,))
    deposits = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify({'deposits': deposits}), 200

@app.route('/api/user/pending-requests', methods=['GET'])
@jwt_required()
def get_user_pending_requests():
    user_id = get_jwt_identity()
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT id, amount, mpesa_code, status, created_at
        FROM deposits
        WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (user_id,))
    deposits = [dict(row) for row in c.fetchall()]

    c.execute('''
        SELECT id, subject, body, status, admin_response, created_at
        FROM messages
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 5
    ''', (user_id,))
    messages = [dict(row) for row in c.fetchall()]
    conn.close()

    return jsonify({
        'deposits': deposits,
        'messages': messages,
        'pending_deposit_count': sum(1 for deposit in deposits if deposit['status'] == 'pending')
    }), 200

@app.route('/api/admin/confirm-deposit', methods=['POST'])
@admin_required
def confirm_deposit():
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid request data'}), 400

    deposit_id = data.get('deposit_id')
    if not deposit_id:
        return jsonify({'error': 'Deposit id is required'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM deposits WHERE id = ?', (deposit_id,))
    deposit = c.fetchone()
    if not deposit:
        conn.close()
        return jsonify({'error': 'Deposit not found'}), 404
    if deposit['status'] != 'pending':
        conn.close()
        return jsonify({'error': 'Deposit is not pending'}), 400

    c.execute('SELECT total_deposited, available_balance FROM users WHERE id = ?', (deposit['user_id'],))
    user = c.fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404

    daily_earnings = calculate_daily_earnings(deposit['amount'])
    new_balance = user['available_balance'] + deposit['amount']
    new_total_deposited = user['total_deposited'] + deposit['amount']
    c.execute('''
        UPDATE users
        SET total_deposited = ?,
            daily_earnings = ?,
            available_balance = ?
        WHERE id = ?
    ''', (new_total_deposited, daily_earnings, new_balance, deposit['user_id']))

    c.execute('UPDATE deposits SET status = ? WHERE id = ?', ('approved', deposit_id))

    c.execute('SELECT * FROM referrals WHERE referred_id = ? AND status = ?', (deposit['user_id'], 'pending'))
    referral = c.fetchone()
    if referral:
        c.execute('UPDATE users SET available_balance = available_balance + ?, total_earned = total_earned + ? WHERE id = ?',
                  (referral['reward_amount'], referral['reward_amount'], referral['referrer_id']))
        c.execute('''
            UPDATE referrals
            SET status = ?, awarded_at = CURRENT_TIMESTAMP, deposit_id = ?
            WHERE id = ?
        ''', ('completed', deposit_id, referral['id']))

    conn.commit()
    conn.close()

    return jsonify({'message': 'Deposit approved', 'new_balance': new_balance}), 200


@app.route('/api/survey/submit', methods=['POST'])
@jwt_required()
def submit_survey():
    user_id = get_jwt_identity()
    data = request.get_json()
    if not data or not isinstance(data, dict) or 'answers' not in data:
        return jsonify({'error': 'Invalid request data'}), 400

    conn = get_db()
    c = conn.cursor()

    c.execute('SELECT last_login_at FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    if not user or not is_login_recent(user['last_login_at']):
        conn.close()
        return jsonify({'error': 'Please login again before earning rewards'}), 400

    today = datetime.now().date()
    c.execute('SELECT id FROM activity_rewards WHERE user_id = ? AND activity = ? AND date = ?',
              (user_id, 'survey', today))
    if c.fetchone():
        conn.close()
        return jsonify({'error': 'Survey reward already claimed for today'}), 400

    answers_json = json.dumps(data.get('answers'))
    reward_amount = 100  # fixed reward for completing the survey

    c.execute('SELECT id FROM surveys WHERE user_id = ?', (user_id,))
    existing_survey = c.fetchone()
    if existing_survey:
        c.execute('UPDATE surveys SET answers = ?, reward_amount = ? WHERE user_id = ?',
                  (answers_json, reward_amount, user_id))
    else:
        c.execute('INSERT INTO surveys (user_id, answers, reward_amount) VALUES (?, ?, ?)',
                  (user_id, answers_json, reward_amount))

    c.execute('INSERT INTO activity_rewards (user_id, activity, reward_amount, date) VALUES (?, ?, ?, ?)',
              (user_id, 'survey', reward_amount, today))

    c.execute('UPDATE users SET available_balance = available_balance + ?, total_earned = total_earned + ? WHERE id = ?',
              (reward_amount, reward_amount, user_id))

    conn.commit()
    conn.close()

    return jsonify({'message': 'Survey completed', 'reward': reward_amount}), 200

@app.route('/api/ad/complete', methods=['POST'])
@jwt_required()
def complete_ad():
    user_id = get_jwt_identity()
    conn = get_db()
    c = conn.cursor()

    c.execute('SELECT last_login_at FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    if not user or not is_login_recent(user['last_login_at']):
        conn.close()
        return jsonify({'error': 'Please login again before earning rewards'}), 400

    today = datetime.now().date()
    c.execute('SELECT id FROM activity_rewards WHERE user_id = ? AND activity = ? AND date = ?',
              (user_id, 'ad', today))
    if c.fetchone():
        conn.close()
        return jsonify({'error': 'Ad reward already claimed for today'}), 400

    reward_amount = 100
    c.execute('INSERT INTO activity_rewards (user_id, activity, reward_amount, date) VALUES (?, ?, ?, ?)',
              (user_id, 'ad', reward_amount, today))
    c.execute('UPDATE users SET available_balance = available_balance + ?, total_earned = total_earned + ? WHERE id = ?',
              (reward_amount, reward_amount, user_id))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Ad completed', 'reward': reward_amount}), 200


@app.route('/api/rating/submit', methods=['POST'])
@jwt_required()
def submit_rating():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    rating = int(data.get('rating', 0)) if data.get('rating') is not None else 0
    comment = data.get('comment', '').strip()

    if rating < 1 or rating > 5:
        return jsonify({'error': 'Invalid rating value'}), 400

    conn = get_db()
    c = conn.cursor()
    # Prevent multiple ratings per user
    c.execute('SELECT id FROM ratings WHERE user_id = ?', (user_id,))
    if c.fetchone():
        conn.close()
        return jsonify({'error': 'Rating already submitted'}), 400

    # Reward only when rating is greater than 3
    reward_amount = 100 if rating > 3 else 0
    c.execute('INSERT INTO ratings (user_id, rating, comment, reward_amount) VALUES (?, ?, ?, ?)',
              (user_id, rating, comment, reward_amount))
    if reward_amount > 0:
        c.execute('UPDATE users SET available_balance = available_balance + ?, total_earned = total_earned + ? WHERE id = ?',
                  (reward_amount, reward_amount, user_id))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Rating submitted', 'reward': reward_amount}), 200

@app.route('/api/claim-earnings', methods=['POST'])
@jwt_required()
def claim_earnings():
    user_id = get_jwt_identity()
    today = datetime.now().date()
    
    conn = get_db()
    c = conn.cursor()
    
    # Check if already claimed today
    c.execute('SELECT id FROM earnings WHERE user_id = ? AND date = ?', (user_id, today))
    if c.fetchone():
        conn.close()
        return jsonify({'error': 'You have already claimed earnings for today'}), 400
    
    # Get user's daily earnings rate
    c.execute('SELECT daily_earnings, available_balance FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    
    if not user or user['daily_earnings'] <= 0:
        conn.close()
        return jsonify({'error': 'No active deposit found'}), 400
    
    daily_amount = user['daily_earnings']
    new_balance = user['available_balance'] + daily_amount
    
    # Record earnings
    c.execute('''
        INSERT INTO earnings (user_id, amount, date)
        VALUES (?, ?, ?)
    ''', (user_id, daily_amount, today))
    
    # Update user totals
    c.execute('''
        UPDATE users 
        SET total_earned = total_earned + ?,
            available_balance = ?
        WHERE id = ?
    ''', (daily_amount, new_balance, user_id))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'message': 'Earnings claimed successfully',
        'amount_earned': daily_amount,
        'new_balance': new_balance
    }), 200

# ===== WITHDRAWAL =====
@app.route('/api/withdraw', methods=['POST'])
@jwt_required()
def withdraw():
    user_id = get_jwt_identity()
    data = request.get_json()
    amount = data.get('amount')
    phone = data.get('phone', '').strip()
    
    if not amount or amount < 100:
        return jsonify({'error': 'Minimum withdrawal is KSH 100'}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT available_balance FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    
    if not user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404
    
    if user['available_balance'] < amount:
        conn.close()
        return jsonify({'error': 'Insufficient balance'}), 400
    
    # Create withdrawal request
    c.execute('''
        INSERT INTO withdrawals (user_id, amount, phone)
        VALUES (?, ?, ?)
    ''', (user_id, amount, phone))
    
    # Deduct from balance
    new_balance = user['available_balance'] - amount
    c.execute('UPDATE users SET available_balance = ? WHERE id = ?', (new_balance, user_id))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'message': 'Withdrawal request submitted',
        'amount': amount,
        'new_balance': new_balance
    }), 200

# ===== ADMIN ROUTES (for managing deposits/withdrawals) =====
@app.route('/api/admin/users', methods=['GET'])
@admin_required
def get_all_users():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT u.id, u.name, u.email, u.phone, u.gender, u.age, u.referral_code, u.total_deposited, u.total_earned,
               u.available_balance, u.daily_earnings, u.created_at,
               SUM(CASE WHEN d.status = 'pending' THEN 1 ELSE 0 END) AS pending_deposits,
               SUM(CASE WHEN w.status = 'pending' THEN 1 ELSE 0 END) AS pending_withdrawals
        FROM users u
        LEFT JOIN deposits d ON d.user_id = u.id
        LEFT JOIN withdrawals w ON w.user_id = u.id
        GROUP BY u.id
        ORDER BY u.created_at DESC
    ''')
    users = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(users), 200

@app.route('/api/admin/deposits', methods=['GET'])
@admin_required
def get_pending_deposits():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT d.*, u.name AS user_name, u.email AS user_email, u.phone AS user_phone, u.referral_code AS user_referral_code,
               r.reward_amount,
               ru.name AS referrer_name,
               ru.email AS referrer_email
        FROM deposits d
        JOIN users u ON d.user_id = u.id
        LEFT JOIN referrals r ON r.referred_id = d.user_id AND r.status = 'pending'
        LEFT JOIN users ru ON r.referrer_id = ru.id
        WHERE d.status = 'pending'
    ''')
    deposits = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(deposits), 200

@app.route('/api/admin/withdrawals', methods=['GET'])
@admin_required
def get_pending_withdrawals():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT w.*, u.name, u.email 
        FROM withdrawals w 
        JOIN users u ON w.user_id = u.id 
        WHERE w.status = 'pending'
    ''')
    withdrawals = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(withdrawals), 200

@app.route('/api/admin/withdrawals/action', methods=['POST'])
@admin_required
def action_withdrawal():
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid request data'}), 400

    withdrawal_id = data.get('withdrawal_id')
    action = data.get('action')
    if not withdrawal_id or action not in ['approve', 'decline']:
        return jsonify({'error': 'Withdrawal id and valid action are required'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM withdrawals WHERE id = ?', (withdrawal_id,))
    withdrawal = c.fetchone()
    if not withdrawal:
        conn.close()
        return jsonify({'error': 'Withdrawal request not found'}), 404
    if withdrawal['status'] != 'pending':
        conn.close()
        return jsonify({'error': 'Withdrawal already processed'}), 400

    try:
        if action == 'approve':
            c.execute('UPDATE withdrawals SET status = ? WHERE id = ?', ('approved', withdrawal_id))
        else:
            c.execute('UPDATE withdrawals SET status = ? WHERE id = ?', ('declined', withdrawal_id))
            c.execute('UPDATE users SET available_balance = available_balance + ? WHERE id = ?',
                      (withdrawal['amount'], withdrawal['user_id']))
        conn.commit()
        conn.close()
        message = 'Withdrawal approved' if action == 'approve' else 'Withdrawal declined and amount refunded'
        return jsonify({'message': message}), 200
    except sqlite3.OperationalError as exc:
        conn.rollback()
        conn.close()
        return jsonify({'error': f'Unable to process withdrawal: {exc}'}), 500

@app.route('/api/admin/messages', methods=['GET'])
@admin_required
def get_admin_messages():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT m.*, u.name AS user_name, u.email AS user_email, u.phone AS user_phone
        FROM messages m
        JOIN users u ON m.user_id = u.id
        ORDER BY m.created_at DESC
    ''')
    messages = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(messages), 200

@app.route('/api/admin/messages/action', methods=['POST'])
@admin_required
def action_admin_message():
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid request data'}), 400

    message_id = data.get('message_id')
    action = data.get('action')
    admin_response = data.get('admin_response', '').strip()
    if not message_id or action not in ['accept', 'decline']:
        return jsonify({'error': 'Message id and valid action are required'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM messages WHERE id = ?', (message_id,))
    message = c.fetchone()
    if not message:
        conn.close()
        return jsonify({'error': 'Message not found'}), 404
    if message['status'] != 'pending':
        conn.close()
        return jsonify({'error': 'Message already processed'}), 400

    new_status = 'accepted' if action == 'accept' else 'declined'
    c.execute('UPDATE messages SET status = ?, admin_response = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
              (new_status, admin_response, message_id))
    conn.commit()
    conn.close()
    return jsonify({'message': f'Message {new_status} successfully'}), 200

@app.route('/api/admin/referrals', methods=['GET'])
@admin_required
def get_admin_referrals():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT r.*, ref.name AS referrer_name, ref.email AS referrer_email,
               referred.name AS referred_name, referred.email AS referred_email,
               d.deposit_status
        FROM referrals r
        JOIN users ref ON r.referrer_id = ref.id
        JOIN users referred ON r.referred_id = referred.id
        LEFT JOIN (
            SELECT user_id, status AS deposit_status
            FROM deposits
            WHERE id IN (
                SELECT MAX(id) FROM deposits GROUP BY user_id
            )
        ) d ON d.user_id = referred.id
        ORDER BY r.created_at DESC
    ''')
    referrals = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(referrals), 200

@app.route('/api/admin/referrals/verify', methods=['POST'])
@admin_required
def verify_referral():
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({'error': 'Invalid request data'}), 400

    referral_id = data.get('referral_id')
    if not referral_id:
        return jsonify({'error': 'Referral id is required'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM referrals WHERE id = ?', (referral_id,))
    referral = c.fetchone()
    if not referral:
        conn.close()
        return jsonify({'error': 'Referral not found'}), 404
    if referral['status'] == 'completed':
        conn.close()
        return jsonify({'error': 'Referral already verified'}), 400

    c.execute('UPDATE referrals SET status = ?, awarded_at = CURRENT_TIMESTAMP WHERE id = ?',
              ('completed', referral_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Referral verified successfully'}), 200

@app.route('/api/admin/activities', methods=['GET'])
@admin_required
def get_admin_activities():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT u.id AS user_id, u.name AS user_name, u.email AS user_email,
               ar.activity, ar.reward_amount, ar.date, ar.created_at
        FROM activity_rewards ar
        JOIN users u ON ar.user_id = u.id
        ORDER BY ar.created_at DESC
    ''')
    activities = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(activities), 200

@app.route('/', methods=['GET'])
def home():
    return send_from_directory(FRONTEND_DIR, 'index.html')

@app.route('/<path:filename>', methods=['GET'])
def serve_file(filename):
    return send_from_directory(FRONTEND_DIR, filename)

# ===== RUN =====
if __name__ == '__main__':
    init_db()
    print("Database initialized!")
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)