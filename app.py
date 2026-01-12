# app.py
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_file, abort
import sqlite3
import re
from datetime import datetime
import json
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import requests
import io
from dotenv import load_dotenv
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import threading
import time
from itsdangerous import URLSafeSerializer, BadSignature
import uuid
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
import certifi
from urllib.parse import urljoin
import logging
from werkzeug.exceptions import HTTPException


load_dotenv()

app = Flask(__name__)
secret = os.getenv("APP_SECRET_KEY")
if not secret:
    raise RuntimeError("APP_SECRET_KEY is not set")
app.secret_key = secret

# File upload configuration
UPLOADS_DIR = os.path.join('uploads', 'certificates')
ALLOWED_EXTENSIONS = {'pdf'}  # PDF only
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
app.config["PUBLIC_BASE_URL"] = PUBLIC_BASE_URL

# Ensure uploads directory exists
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Basic logging setup (works for dev + prod)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_uploaded_file(conn, file_obj, task_id, supplier_id, pr_item_id):
    """
    Store uploaded file into DB (SQLite) and return file_assets.id
    """
    filename = secure_filename(file_obj.filename or "document.pdf")
    mime_type = file_obj.mimetype or "application/pdf"
    data = file_obj.read()  # bytes

    cur = conn.execute(
        """
        INSERT INTO file_assets (task_id, supplier_id, pr_item_id, filename, mime_type, data)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task_id, supplier_id, pr_item_id, filename, mime_type, data)
    )
    return cur.lastrowid

def public_url(endpoint: str, **values) -> str:
    """
    Build a fully-qualified URL using PUBLIC_BASE_URL (preferred),
    otherwise fall back to Flask's _external=True behavior.
    """
    base = app.config.get("PUBLIC_BASE_URL")
    if base:
        # build path only, then prefix with base
        path = url_for(endpoint, _external=False, **values)
        return f"{base}{path}"
    # fallback (will be localhost if you run locally)
    return url_for(endpoint, _external=True, **values)

def public_url_for(endpoint: str, **values) -> str:
    """
    Builds a public absolute URL.
    - If PUBLIC_BASE_URL is set (recommended), it forces that domain.
    - Otherwise falls back to Flask's _external=True (local dev).
    """
    # Always generate a path first
    path = url_for(endpoint, **values)  # e.g. "/file/12"
    if PUBLIC_BASE_URL:
        return urljoin(PUBLIC_BASE_URL + "/", path.lstrip("/"))
    return url_for(endpoint, _external=True, **values)

@app.route('/file/<int:file_id>')
def serve_file(file_id):
    """Serve a file from the database."""
    conn = get_db_connection()
    file_asset = conn.execute('SELECT * FROM file_assets WHERE id = ?', (file_id,)).fetchone()
    conn.close()
    
    if not file_asset:
        return "File not found", 404
        
    return send_file(
        io.BytesIO(file_asset['data']),
        mimetype=file_asset['mime_type'],
        download_name=file_asset['filename'],
        as_attachment=False # Open in browser
    )

def get_quote_serializer():
    return URLSafeSerializer(app.secret_key, salt="supplier-quote")

def get_reset_serializer():
    return URLSafeSerializer(app.secret_key, salt="password-reset")

def make_reset_token(user_id: int, email: str) -> str:
    return get_reset_serializer().dumps({"user_id": user_id, "email": email})

def verify_reset_token(token: str):
    return get_reset_serializer().loads(token)  # we’ll enforce expiry via our own timestamp check if desired

def generate_temp_password(length: int = 10) -> str:
    # simple temp password: letters+digits (no symbols to avoid email copy issues)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(alphabet[uuid.uuid4().int % len(alphabet)] for _ in range(length))

def init_database_on_startup():
    """Ensure the SQLite database exists with expected tables."""
    conn = None
    try:
        import database.init_db
        database.init_db.init_database()

        db_path = os.path.join('database', 'procure_flow.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [table[0] for table in cursor.fetchall()]
        app.logger.info("Database initialized. Tables=%s", tables)
    except Exception as e:
        app.logger.exception("Database initialization failed")
    finally:
        if conn:
            conn.close()

# Call the initialization function
init_database_on_startup()

# Email Configuration
EMAIL_CONFIG = {
    'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
    'smtp_port': int(os.getenv('SMTP_PORT', '587')),
    'sender_email': os.getenv('SMTP_SENDER'),
    'sender_password': os.getenv('SMTP_PASSWORD')
}
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
SENDGRID_SENDER = os.environ.get("SENDGRID_SENDER", "")

# IMAP configuration (for inbox polling)
IMAP_SERVER = os.getenv('IMAP_SERVER', 'imap.gmail.com')
IMAP_PORT = int(os.getenv('IMAP_PORT', '993'))
IMAP_USERNAME = os.getenv('IMAP_USERNAME', EMAIL_CONFIG['sender_email'])
IMAP_PASSWORD = os.getenv('IMAP_PASSWORD', EMAIL_CONFIG['sender_password'])

ENABLE_DEBUG_ROUTES = os.getenv("ENABLE_DEBUG_ROUTES", "0") == "1"

# Database connection helper
def get_db_connection():
    """Return SQLite connection with row factory."""
    db_path = os.path.join('database', 'procure_flow.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

# Validation functions
def validate_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_phone(phone):
    # Malaysian phone number validation
    pattern = r'^(\+?6?01)[0-46-9]-*[0-9]{7,8}$'
    return re.match(pattern, phone.replace(' ', '').replace('-', '')) is not None

def validate_password(password):
    # At least 5 letters and 1 number
    if len(password) < 6:
        return False
    if not any(char.isdigit() for char in password):
        return False
    if not any(char.isalpha() for char in password):
        return False
    return True

def generate_email_content(pr_items, task_name):
    items_html = """
    <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; width: 100%; border: 1px solid #ddd; font-family: Arial, sans-serif;">
        <thead style="background-color: #f2f2f2;">
            <tr>
                <th style="text-align: center; width: 5%;">No.</th>
                <th style="text-align: left;">Description</th>
                <th style="text-align: left;">Specification</th>
                <th style="text-align: left;">Brand/Model</th>
                <th style="text-align: center; width: 10%;">Qty</th>
                <th style="text-align: left;">Remark</th>
            </tr>
        </thead>
        <tbody>
    """
    
    for idx, item in enumerate(pr_items, 1):
        item = dict(item) if item is not None else {}
        category = (item.get('item_category') or '').strip()

        # Build Specification (Dimensions)
        spec = ''
        if category in ['Steel Plates', 'Stainless Steel']:
            w = item.get('width') or ''
            l = item.get('length') or ''
            thk = item.get('thickness') or ''
            if w or l or thk:
                spec = f"{w} x {l} x {thk} mm (W x L x Thk)"
        elif category == 'Angle Bar':
            a = item.get('dim_a') or ''
            b = item.get('dim_b') or ''
            l = item.get('length') or ''
            thk = item.get('thickness') or ''
            if a or b or l or thk:
                spec = f"{a} x {b} x {l} x {thk} mm (A x B x L x Thk)"
        elif category in ['Rebar', 'Bolts, Fasteners']:
            d = item.get('diameter') or ''
            l = item.get('length') or ''
            if d or l:
                spec = f"{d} x {l} mm (D x L)"
        else:
            uom = item.get('uom') or ''
            uom_qty = item.get('uom_qty') or ''
            if uom_qty and uom:
                spec = f"{uom_qty} {uom}"
            elif uom_qty:
                spec = f"Qty: {uom_qty}"
            elif uom:
                spec = f"UOM: {uom}"
        
        # Fallback to direct spec field if dynamic dim is empty, or append?
        # User image shows "Specification" column often having sizes. try to use 'specification' field if dims are empty?
        # Actually in pr_items we have 'specification' column.
        original_spec = item.get('specification') or ''
        if spec and original_spec:
            final_spec = f"{spec}<br><small>{original_spec}</small>"
        elif spec:
            final_spec = spec
        else:
            final_spec = original_spec or 'N/A'

        items_html += f"""
            <tr>
                <td style="text-align: center;">{idx}</td>
                <td>{item['item_name']}</td>
                <td>{final_spec}</td>
                <td>{item.get('brand') or ''}</td>
                <td style="text-align: center;">{item['quantity']}</td>
                <td></td> <!-- Empty Remark for now, as in image -->
            </tr>
        """

    items_html += "</tbody></table>"
    
    return f"""
    <html>
    <body>
        <h2>Procurement Inquiry</h2>
        <p>Dear {{supplier_name}}{{contact_person}},</p>
        
        <p>We are inquiring about the following items for procurement:</p>
        
        {items_html}
        
        <p>Please provide us with your quotation including:</p>
        <ul>
            <li>Payment Terms (Days)</li>
            <li>Unit Price (RM)</li>
            <li>Delivery Lead Timeline (Days)</li>
            <li>Stock Availability</li>
            <li>Warranty (If Applicable)</li>
            <li>Mill Certificate / Certificate of Analysis (COA)</li>
        </ul>
        
        <p>We look forward to your prompt response.</p>
        
        <p>Best regards,<br>
        Procurement Department</p>
    </body>
    </html>
    """

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    """Main dashboard showing recent tasks and stats."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Get recent tasks (for admin, all tasks; for user, only their tasks)
    if session.get('role') == 'admin':
        recent_tasks = conn.execute('''
            SELECT t.*,
                (SELECT COUNT(*) FROM pr_items WHERE task_id = t.id) AS item_count
            FROM tasks t
            ORDER BY t.created_at DESC
            LIMIT 10
        ''').fetchall()
    else:
        recent_tasks = conn.execute('''
            SELECT t.*,
                (SELECT COUNT(*) FROM pr_items WHERE task_id = t.id) AS item_count
            FROM tasks t
            WHERE t.user_id = ?
            ORDER BY t.created_at DESC
            LIMIT 10
        ''', (session['user_id'],)).fetchall()

    
    # Get stats for admin dashboard
    stats = None
    if session.get('role') == 'admin':
        stats = {
            'total_tasks': conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],
            'active_tasks': conn.execute("SELECT COUNT(*) FROM tasks WHERE status NOT IN ('completed', 'cancelled')").fetchone()[0],
            'total_suppliers': conn.execute('SELECT COUNT(*) FROM suppliers WHERE is_active = 1').fetchone()[0]
        }
    
    conn.close()
    return render_template('dashboard.html', recent_tasks=recent_tasks, stats=stats)

@app.route('/purchase-requisitions')
def purchase_requisitions():
    """Show saved Purchase Requisitions that haven't been sent to suppliers yet."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Get PRs with status 'purchase_requisition' (saved but not yet in supplier selection)
    if session.get('role') == 'admin':
        prs = conn.execute('''
            SELECT t.*, u.username,
                   (SELECT COUNT(*) FROM pr_items WHERE task_id = t.id) as item_count
            FROM tasks t
            LEFT JOIN users u ON t.user_id = u.id
            WHERE t.status = 'purchase_requisition'
            ORDER BY t.created_at DESC
        ''').fetchall()
    else:
        prs = conn.execute('''
            SELECT t.*, 
                   (SELECT COUNT(*) FROM pr_items WHERE task_id = t.id) as item_count
            FROM tasks t
            WHERE t.user_id = ? AND t.status = 'purchase_requisition'
            ORDER BY t.created_at DESC
        ''', (session['user_id'],)).fetchall()
    
    conn.close()
    return render_template('purchase_requisitions.html', prs=prs)


@app.route('/uploads/certificates/<path:filepath>')
def download_certificate(filepath):
    """Serve uploaded certificate files."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        file_path = os.path.join(UPLOADS_DIR, filepath)
        # Prevent directory traversal
        if not os.path.abspath(file_path).startswith(os.path.abspath(UPLOADS_DIR)):
            return "Access denied", 403
        
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            return "File not found", 404
    except Exception as e:
        print(f"Error serving certificate: {e}")
        return "Error accessing file", 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute(
            'SELECT * FROM users WHERE username = ?', (username,)
        ).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials', 'error')
    
    return render_template('login.html')

@app.route('/create-user', methods=['GET', 'POST'])
def create_user():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        email_addr = request.form['email'].strip().lower()
        password = (request.form.get('password') or "").strip()
        role = request.form['role']

        # Validation
        if not validate_email(email_addr):
            flash('Invalid email format', 'error')
            return render_template('create_user.html')

        # If password empty, generate temp password
        is_temp_password = False
        if not password:
            password = generate_temp_password(10)
            is_temp_password = True

        if not validate_password(password):
            flash('Password must contain at least 5 letters and 1 number', 'error')
            return render_template('create_user.html')

        password_hash = generate_password_hash(password)

        conn = get_db_connection()
        try:
            cur = conn.execute(
                'INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)',
                (username, password_hash, email_addr, role)
            )
            new_user_id = cur.lastrowid
            conn.commit()

            # Build reset link
            token = make_reset_token(new_user_id, email_addr)
            reset_link = public_url_for("reset_password", token=token)

            # Email login details + reset link
            subject = "Your Procure-Flow account details"
            html = f"""
            <html><body>
            <p>Hello {username},</p>
            <p>An account has been created for you in Procure-Flow.</p>

            <p><strong>Login details:</strong><br>
            Username: <code>{username}</code><br>
            Email: <code>{email_addr}</code><br>
            Password: <code>{password}</code></p>

            <p><strong>Reset your password now (recommended):</strong><br>
            <a href="{reset_link}">{reset_link}</a></p>

            <p>If you did not expect this email, please contact the administrator.</p>
            </body></html>
            """

            email_ok = send_email_html(email_addr, subject, html, to_name=username)
            if email_ok:
                flash('User created successfully and email sent.', 'success')
            else:
                flash('User created, but failed to send email. Please verify email settings.', 'error')

            return redirect(url_for('index'))

        except sqlite3.IntegrityError:
            conn.rollback()
            flash('Username already exists', 'error')
        finally:
            conn.close()

    return render_template('create_user.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email_addr = (request.form.get('email') or '').strip().lower()
        if not validate_email(email_addr):
            flash("Please enter a valid email address.", "error")
            return render_template("forgot_password.html")

        conn = get_db_connection()
        try:
            user = conn.execute('SELECT id, username, email FROM users WHERE LOWER(email) = ?', (email_addr,)).fetchone()
            # Always respond success to avoid account enumeration
            if user:
                token = make_reset_token(user['id'], user['email'])
                reset_link = public_url_for("reset_password", token=token)

                subject = "Reset your Procure-Flow password"
                html = f"""
                <html><body>
                <p>Hello {user['username']},</p>
                <p>Click the link below to reset your password:</p>
                <p><a href="{reset_link}">{reset_link}</a></p>
                <p>If you did not request this, you can ignore this email.</p>
                </body></html>
                """
                send_email_html(user['email'], subject, html, to_name=user['username'])

            flash("If an account exists for that email, a reset link has been sent.", "success")
            return redirect(url_for("login"))
        finally:
            conn.close()

    return render_template("forgot_password.html")

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # Optional expiry control:
    # If you want expiry, embed created_at in token payload and check it.
    try:
        data = get_reset_serializer().loads(token)
        user_id = data.get("user_id")
        email_addr = (data.get("email") or "").lower()
        if not user_id or not email_addr:
            return render_template("errors/400.html"), 400
    except BadSignature:
        return render_template("errors/400.html"), 400

    conn = get_db_connection()
    try:
        user = conn.execute('SELECT id, username, email FROM users WHERE id = ? AND LOWER(email) = ?', (user_id, email_addr)).fetchone()
        if not user:
            return render_template("errors/404.html"), 404

        if request.method == 'POST':
            new_password = (request.form.get("password") or "").strip()
            confirm = (request.form.get("confirm_password") or "").strip()

            if new_password != confirm:
                flash("Passwords do not match.", "error")
                return render_template("reset_password.html", username=user["username"])

            if not validate_password(new_password):
                flash("Password must contain at least 5 letters and 1 number.", "error")
                return render_template("reset_password.html", username=user["username"])

            new_hash = generate_password_hash(new_password)
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
            conn.commit()

            flash("Password reset successful. Please log in.", "success")
            return redirect(url_for("login"))

        return render_template("reset_password.html", username=user["username"])
    finally:
        conn.close()

@app.route('/new-task', methods=['GET', 'POST'])
@app.route('/edit-task/<int:task_id>', methods=['GET', 'POST'])
def new_task(task_id=None):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    
    # Fetch category items for autocomplete
    cat_items_data = conn.execute('''
        SELECT c.name as cat_name, ci.name as item_name
        FROM category_items ci
        JOIN categories c ON ci.category_id = c.id
        ORDER BY ci.name
    ''').fetchall()
    
    category_items_map = {}
    for row in cat_items_data:
        cat = row['cat_name']
        if cat not in category_items_map:
            category_items_map[cat] = []
        category_items_map[cat].append(row['item_name'])
    
    if task_id:
        # Editing existing task - verify ownership
        task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
        if not task or (session['role'] != 'admin' and task['user_id'] != session['user_id']):
            flash('Task not found or access denied', 'error')
            conn.close()
            return redirect(url_for('task_list'))
        
        # Get existing items
        existing_items = conn.execute(
            'SELECT * FROM pr_items WHERE task_id = ?', (task_id,)
        ).fetchall()
    else:
        task = None
        existing_items = []
    
    if request.method == 'POST':
        project_ref = request.form['project_reference']
        global_category = request.form['global_category']
        
        # Format task name
        task_name = f"{project_ref} - {global_category}"
        
        items = []
        
        # Process items from form
        item_index = 0
        while f'items[{item_index}][item_name]' in request.form:
            items.append({
                'item_category': global_category, # Use global category
                'item_name': request.form[f'items[{item_index}][item_name]'],
                'brand': request.form.get(f'items[{item_index}][brand]') or None,
                'quantity': request.form.get(f'items[{item_index}][quantity]') or None,
                'payment_terms': request.form.get(f'items[{item_index}][payment_terms]') or None,
                # Steel Plates dimensions
                'width': request.form.get(f'items[{item_index}][width]') or None,
                'length': request.form.get(f'items[{item_index}][length]') or None,
                'thickness': request.form.get(f'items[{item_index}][thickness]') or None,
                # Angle Bar dimensions
                'dim_a': request.form.get(f'items[{item_index}][dim_a]') or None,
                'dim_b': request.form.get(f'items[{item_index}][dim_b]') or None,
                # Bolts/Rebar dimensions
                'diameter': request.form.get(f'items[{item_index}][diameter]') or None,
                # Other UOM
                'uom_qty': request.form.get(f'items[{item_index}][uom_qty]') or None,
                'uom': request.form.get(f'items[{item_index}][uom]') or None,

            })
            item_index += 1
        
        if task_id:
            # Update existing task
            conn.execute('UPDATE tasks SET task_name = ? WHERE id = ?', (task_name, task_id))
            # Delete existing items and add new ones
            conn.execute('DELETE FROM pr_items WHERE task_id = ?', (task_id,))
            task_id_to_use = task_id
            flash('Task updated successfully!', 'success')
        else:
            # Create new task
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO tasks (task_name, user_id, status) VALUES (?, ?, ?)',
                (task_name, session['user_id'], 'purchase_requisition')
            )
            task_id_to_use = cursor.lastrowid
            flash('Purchase Requisition saved successfully!', 'success')
        
        # Add PR items with all dimension fields
        for item_data in items:
            conn.execute('''
                INSERT INTO pr_items (task_id, item_category, item_name, brand, quantity, payment_terms,
                                      width, length, thickness, dim_a, dim_b, diameter, uom_qty, uom)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task_id_to_use,
                item_data['item_category'],
                item_data['item_name'],
                item_data['brand'],
                item_data['quantity'],
                item_data['payment_terms'],
                item_data.get('width'),
                item_data.get('length'),
                item_data.get('thickness'),
                item_data.get('dim_a'),
                item_data.get('dim_b'),
                item_data.get('diameter'),
                item_data.get('uom_qty'),
                item_data.get('uom')
            ))
        
        conn.commit()
        conn.close()
        
        # Redirect to dashboard instead of supplier selection
        return redirect(url_for('dashboard'))
    
    conn.close()
    return render_template('pr_form.html', 
                         categories=categories, 
                         task=task, 
                         existing_items=existing_items,
                         is_edit=bool(task_id),
                         category_items_map=category_items_map)

@app.route('/task/<int:task_id>/edit')
def edit_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Verify task ownership
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task or (session['role'] != 'admin' and task['user_id'] != session['user_id']):
        flash('Task not found or access denied', 'error')
        conn.close()
        return redirect(url_for('task_list'))
    
    conn.close()
    
    # Redirect based on current status
    if task['status'] == 'purchase_requisition':
        return redirect(url_for('new_task', task_id=task_id))
    elif task['status'] == 'select_suppliers':
        return redirect(url_for('supplier_selection', task_id=task_id))
    elif task['status'] == 'generate_email':
        return redirect(url_for('email_preview', task_id=task_id))
    elif task['status'] == 'confirm_email':
        return redirect(url_for('email_confirmation', task_id=task_id))
    else:
        return redirect(url_for('task_list'))

"""
@app.route('/task/<int:task_id>/email', methods=['GET', 'POST'])
def email_generation(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Verify task ownership
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task or (session['role'] != 'admin' and task['user_id'] != session['user_id']):
        flash('Task not found or access denied', 'error')
        conn.close()
        return redirect(url_for('task_list'))
    
    # Get selected suppliers with their assigned items
    selected_suppliers = conn.execute('''
        SELECT s.*, ts.assigned_items 
        FROM suppliers s
        JOIN task_suppliers ts ON s.id = ts.supplier_id
        WHERE ts.task_id = ? AND ts.is_selected = 1
    ''', (task_id,)).fetchall()
    
    pr_items = conn.execute(
        'SELECT * FROM pr_items WHERE task_id = ?', (task_id,)
    ).fetchall()
    
    if request.method == 'POST':
        # Store email content in session for the next step
        email_content = request.form.get('email_content', '')
        session['email_content'] = email_content
        
        conn.close()
        return redirect(url_for('email_preview', task_id=task_id))
    
    # Group suppliers by their assigned items to create unique email templates
    email_templates = {}
    for supplier in selected_suppliers:
        assigned_item_ids = None
        if supplier['assigned_items']:
            try:
                assigned_item_ids = json.loads(supplier['assigned_items'])
            except:
                assigned_item_ids = None
        
        # Create a key based on the assigned items
        if assigned_item_ids:
            key = tuple(sorted(assigned_item_ids))
        else:
            key = 'all'
        
        if key not in email_templates:
            email_templates[key] = {
                'suppliers': [],
                'items': assigned_item_ids if assigned_item_ids else [item['id'] for item in pr_items]
            }
        
        email_templates[key]['suppliers'].append(supplier)
    
    # Generate default email content for the first template
    default_template_key = next(iter(email_templates.keys()))
    default_items = [item for item in pr_items if not email_templates[default_template_key]['items'] or item['id'] in email_templates[default_template_key]['items']]
    default_email_content = generate_email_content(default_items, task['task_name'])
    
    conn.close()
    
    return render_template('email_generation.html',
                         task=task,
                         email_templates=email_templates,
                         pr_items=pr_items,
                         default_email_content=default_email_content)
"""

@app.route('/task/<int:task_id>/email-preview', methods=['GET', 'POST'])
def email_preview(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Verify task ownership
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task or (session['role'] != 'admin' and task['user_id'] != session['user_id']):
        flash('Task not found or access denied', 'error')
        return redirect(url_for('task_list'))
    
    # Get selected suppliers with their assigned items
    selected_suppliers = conn.execute('''
        SELECT s.*, ts.assigned_items 
        FROM suppliers s
        JOIN task_suppliers ts ON s.id = ts.supplier_id
        WHERE ts.task_id = ? AND ts.is_selected = 1
    ''', (task_id,)).fetchall()
    
    pr_items = conn.execute(
        'SELECT * FROM pr_items WHERE task_id = ?', (task_id,)
    ).fetchall()
    
    subject_key = f"email_subject_{task_id}"
    content_key = f"email_content_{task_id}"

    # Initialize email_subject here, outside the POST block
    email_subject = session.get(subject_key, f"Procurement Inquiry - {task['task_name']}")
    
    if request.method == 'POST':
        action = request.form.get('action')
        email_content = request.form.get('email_content', '')
        email_subject = request.form.get('email_subject', email_subject)  # Use form value or existing
        
        if action == 'update_preview':
            # Just update the preview with new content
            session[content_key] = email_content
            session[subject_key] = email_subject
            flash('Preview updated!', 'success')
            
        elif action == 'send_emails':
            # Store final email content and proceed to confirmation
            session['final_email_content'] = email_content
            session['final_email_subject'] = email_subject
            conn.close()
            return redirect(url_for('email_confirmation', task_id=task_id))
    
    # Group suppliers by email template (based on assigned items)
    email_templates = {}
    for supplier in selected_suppliers:
        assigned_item_ids = None
        if supplier['assigned_items']:
            try:
                assigned_item_ids = json.loads(supplier['assigned_items'])
            except:
                assigned_item_ids = None
        
        # Create a key based on the assigned items
        if assigned_item_ids:
            key = tuple(sorted(assigned_item_ids))
        else:
            key = 'all'
        
        if key not in email_templates:
            # Use session content if available, otherwise generate default
            email_content = session.get(content_key, '')
            if not email_content:
                email_content = generate_email_content(
                    [item for item in pr_items if not assigned_item_ids or item['id'] in assigned_item_ids],
                    task['task_name']
                )
            
            email_templates[key] = {
                'suppliers': [],
                'items': assigned_item_ids if assigned_item_ids else [item['id'] for item in pr_items],
                'email_content': email_content
            }
        
        email_templates[key]['suppliers'].append(supplier)
    
    conn.close()
    
    return render_template('email_preview.html',
                         task=task,
                         email_templates=email_templates,
                         pr_items=pr_items,
                         email_subject=email_subject)

@app.route('/task/<int:task_id>/confirm-email', methods=['GET', 'POST'])
def email_confirmation(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Verify task ownership
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task or (session['role'] != 'admin' and task['user_id'] != session['user_id']):
        flash('Task not found or access denied', 'error')
        conn.close()
        return redirect(url_for('task_list'))
    
    # Get selected suppliers with their assigned items
    selected_suppliers = conn.execute('''
        SELECT s.*, ts.assigned_items 
        FROM suppliers s
        JOIN task_suppliers ts ON s.id = ts.supplier_id
        WHERE ts.task_id = ? AND ts.is_selected = 1
    ''', (task_id,)).fetchall()
    
    pr_items = conn.execute(
        'SELECT * FROM pr_items WHERE task_id = ?', (task_id,)
    ).fetchall()

    # Mark task as in email generation stage
    if task['status'] != 'confirm_email':
        conn.execute('UPDATE tasks SET status = ? WHERE id = ?', ('generate_email', task_id))
        conn.commit()
    
    if request.method == 'POST':
        final_email_content = session.get('final_email_content', '')
        final_email_subject = session.get('final_email_subject', f"Procurement Inquiry - {task['task_name']}")
        
        # Send emails to all selected suppliers with their assigned items
        success_count = 0
        for supplier in selected_suppliers:
            assigned_item_ids = None
            quote_form_link = get_or_create_quote_form_link(conn, task_id, supplier['id'])

            if supplier['assigned_items']:
                try:
                    assigned_item_ids = json.loads(supplier['assigned_items'])
                except:
                    assigned_item_ids = None
            
            sent_ok = send_procurement_email(
                supplier['email'],
                supplier['name'],
                pr_items,
                task['task_name'],
                assigned_item_ids,
                final_email_content,
                final_email_subject,
                supplier.get('contact_name') if isinstance(supplier, dict) else supplier['contact_name'],
                quote_form_link=quote_form_link
            )
            if sent_ok:
                success_count += 1
                try:
                    conn.execute(
                        'UPDATE task_suppliers SET initial_sent_at = COALESCE(initial_sent_at, CURRENT_TIMESTAMP) WHERE task_id = ? AND supplier_id = ?',
                        (task_id, supplier['id'])
                    )
                    conn.execute(
                        '''
                        INSERT INTO email_logs (task_id, supplier_id, email_type, subject, body, status)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ''',
                        (task_id, supplier['id'], 'initial', final_email_subject, final_email_content, 'sent')
                    )
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"Logging/flag update failed for supplier {supplier['id']}: {e}")
            else:
                try:
                    conn.execute(
                        '''
                        INSERT INTO email_logs (task_id, supplier_id, email_type, subject, body, status, error)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (task_id, supplier['id'], 'initial', final_email_subject, final_email_content, 'failed', 'send_failed')
                    )
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"Failed to log failed email for supplier {supplier['id']}: {e}")
        
        # Update task status
        conn.execute(
            'UPDATE tasks SET status = ? WHERE id = ?',
            ('confirm_email', task_id)
        )
        conn.commit()
        conn.close()
        
        # Clean up session data
        session.pop('email_content', None)
        session.pop('final_email_content', None)
        session.pop('final_email_subject', None)
        
        flash(f'Emails sent successfully! {success_count}/{len(selected_suppliers)} emails delivered.', 'success')
        return redirect(url_for('task_list'))
    
    conn.close()
    
    return render_template('email_confirmation.html',
                         task=task,
                         suppliers=selected_suppliers,
                         pr_items=pr_items)

@app.route('/task-list')
def task_list():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()

    if session['role'] == 'admin':
        # Admin sees all tasks
        all_tasks = conn.execute('''
            SELECT t.*,
                u.username,
                (SELECT COUNT(*) FROM pr_items WHERE task_id = t.id) AS item_count
            FROM tasks t
            LEFT JOIN users u ON u.id = t.user_id
            ORDER BY t.created_at DESC
        ''').fetchall()

        my_tasks = conn.execute('''
            SELECT t.*,
                (SELECT COUNT(*) FROM pr_items WHERE task_id = t.id) AS item_count
            FROM tasks t
            WHERE t.user_id = ?
            ORDER BY t.created_at DESC
        ''', (session['user_id'],)).fetchall()
        
        conn.close()
        return render_template('task_list.html', all_tasks=all_tasks, my_tasks=my_tasks)
    else:
        # Regular users see only their tasks
        my_tasks = conn.execute('''
            SELECT t.*,
                (SELECT COUNT(*) FROM pr_items WHERE task_id = t.id) AS item_count
            FROM tasks t
            WHERE t.user_id = ?
            ORDER BY t.created_at DESC
        ''', (session['user_id'],)).fetchall()

        conn.close()
        return render_template('task_list.html', my_tasks=my_tasks)

@app.route('/task/<int:task_id>/follow-up', methods=['GET', 'POST'])
def follow_up(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()

    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task or (session['role'] != 'admin' and task['user_id'] != session['user_id']):
        flash('Task not found or access denied', 'error')
        conn.close()
        return redirect(url_for('task_list'))

    suppliers = conn.execute('''
        SELECT s.*, ts.assigned_items, ts.initial_sent_at, ts.followup_sent_at, ts.replied_at
        FROM suppliers s
        JOIN task_suppliers ts ON s.id = ts.supplier_id
        WHERE ts.task_id = ? AND ts.is_selected = 1
    ''', (task_id,)).fetchall()

    pr_items = conn.execute(
        'SELECT * FROM pr_items WHERE task_id = ?', (task_id,)
    ).fetchall()

    # Suppliers eligible for follow-up: initial sent, not replied
    pending_suppliers = [s for s in suppliers if s['initial_sent_at'] and not s['replied_at']]

    default_body = session.get('followup_email_content') or """
    <p>Dear {supplier_name},</p>
    <p>This is a friendly follow-up regarding our procurement inquiry.</p>
    <p>Please share your quotation, lead time, and warranty terms at your earliest convenience.</p>
    <p>Thank you.</p>
    """
    default_subject = session.get('followup_email_subject') or f"Follow-up: Procurement Inquiry - {task['task_name']}"

    if request.method == 'POST':
        body = request.form.get('email_content', default_body)
        subject = request.form.get('email_subject', default_subject)

        sent = 0
        for supplier in pending_suppliers:
            assigned_item_ids = None
            quote_form_link = get_or_create_quote_form_link(conn, task_id, supplier['id'])

            if supplier['assigned_items']:
                try:
                    assigned_item_ids = json.loads(supplier['assigned_items'])
                except:
                    assigned_item_ids = None

            sent_ok = send_procurement_email(
                supplier['email'],
                supplier['name'],
                pr_items,
                task['task_name'],
                assigned_item_ids,
                body,
                subject,
                supplier.get('contact_name') if isinstance(supplier, dict) else supplier['contact_name'],
                quote_form_link=quote_form_link
            )
            if sent_ok:
                sent += 1
                try:
                    conn.execute(
                        'UPDATE task_suppliers SET followup_sent_at = CURRENT_TIMESTAMP WHERE task_id = ? AND supplier_id = ?',
                        (task_id, supplier['id'])
                    )
                    conn.execute(
                        '''
                        INSERT INTO email_logs (task_id, supplier_id, email_type, subject, body, status)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ''',
                        (task_id, supplier['id'], 'followup', subject, body, 'sent')
                    )
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"Logging follow-up failed for supplier {supplier['id']}: {e}")
            else:
                try:
                    conn.execute(
                        '''
                        INSERT INTO email_logs (task_id, supplier_id, email_type, subject, body, status, error)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (task_id, supplier['id'], 'followup', subject, body, 'failed', 'send_failed')
                    )
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"Failed to log failed follow-up for supplier {supplier['id']}: {e}")

        conn.commit()
        flash(f'Follow-up emails sent: {sent}/{len(pending_suppliers)}', 'success')
        conn.close()
        return redirect(url_for('task_responses', task_id=task_id))

    conn.close()
    return render_template('follow_up.html',
                           task=task,
                           pending_suppliers=pending_suppliers,
                           email_subject=default_subject,
                           email_content=default_body)

@app.route('/task/<int:task_id>/responses', methods=['GET', 'POST'])
def task_responses(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task or (session['role'] != 'admin' and task['user_id'] != session['user_id']):
        flash('Task not found or access denied', 'error')
        conn.close()
        return redirect(url_for('task_list'))

    if request.method == 'POST':
        action = request.form.get('action')
        supplier_id = request.form.get('supplier_id')
        if action == 'mark_replied' and supplier_id:
            conn.execute(
                'UPDATE task_suppliers SET replied_at = CURRENT_TIMESTAMP WHERE task_id = ? AND supplier_id = ?',
                (task_id, supplier_id)
            )
        elif action == 'mark_pending' and supplier_id:
            conn.execute(
                'UPDATE task_suppliers SET replied_at = NULL WHERE task_id = ? AND supplier_id = ?',
                (task_id, supplier_id)
            )
        conn.commit()

    suppliers = conn.execute('''
        SELECT s.*, ts.assigned_items, ts.initial_sent_at, ts.followup_sent_at, ts.replied_at, ts.quote_form_token
        FROM suppliers s
        JOIN task_suppliers ts ON s.id = ts.supplier_id
        WHERE ts.task_id = ? AND ts.is_selected = 1
    ''', (task_id,)).fetchall()

    form_links = {}
    for s in suppliers:
        token = s['quote_form_token']
        if not token:
            token = get_quote_serializer().dumps({'task_id': task_id, 'supplier_id': s['id']})
            conn.execute(
                "UPDATE task_suppliers SET quote_form_token = ? WHERE task_id = ? AND supplier_id = ?",
                (token, task_id, s['id'])
            )
            conn.commit()

        form_links[s['id']] = public_url_for('supplier_quote_form', token=token)

    conn.close()
    return render_template('responses.html', task=task, suppliers=suppliers, form_links=form_links)

def get_or_create_quote_form_link(conn, task_id, supplier_id):
    row = conn.execute(
        "SELECT quote_form_token FROM task_suppliers WHERE task_id=? AND supplier_id=?",
        (task_id, supplier_id)
    ).fetchone()

    token = row["quote_form_token"] if row else None
    if not token:
        token = get_quote_serializer().dumps({'task_id': task_id, 'supplier_id': supplier_id})
        conn.execute(
            "UPDATE task_suppliers SET quote_form_token=? WHERE task_id=? AND supplier_id=?",
            (token, task_id, supplier_id)
        )
        conn.commit()

    # IMPORTANT: use public_url instead of url_for(..., _external=True)
    return public_url_for("supplier_quote_form", token=token)

@app.route('/task/<int:task_id>/quotes/<int:supplier_id>', methods=['GET', 'POST'])
def capture_quotes(task_id, supplier_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    def form_last_nonempty(key: str):
        vals = request.form.getlist(key)
        for v in reversed(vals):
            if v is None:
                continue
            s = str(v).strip()
            if s != "":
                return s
        return None

    conn = get_db_connection()
    try:
        task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
        supplier = conn.execute('SELECT * FROM suppliers WHERE id = ?', (supplier_id,)).fetchone()

        if not task or not supplier or (session['role'] != 'admin' and task['user_id'] != session['user_id']):
            flash('Task or supplier not found, or access denied.', 'error')
            return redirect(url_for('task_list'))

        pr_items = conn.execute(
            'SELECT * FROM pr_items WHERE task_id = ?',
            (task_id,)
        ).fetchall()

        def load_existing_quotes():
            existing = conn.execute(
                'SELECT * FROM supplier_quotes WHERE task_id = ? AND supplier_id = ?',
                (task_id, supplier_id)
            ).fetchall()
            quotes_map_local = {q['pr_item_id']: q for q in existing}

            payment_terms_default_local = ''
            if existing:
                try:
                    payment_terms_default_local = existing[0]['payment_terms'] or ''
                except Exception:
                    payment_terms_default_local = ''
            return quotes_map_local, payment_terms_default_local

        quotes_map, payment_terms_default = load_existing_quotes()

        if request.method == 'POST':
            app.logger.info('capture_quotes POST received for task %s supplier %s', task_id, supplier_id)

            try:
                # 1) clear old quotes for this supplier+task
                conn.execute(
                    'DELETE FROM supplier_quotes WHERE task_id = ? AND supplier_id = ?',
                    (task_id, supplier_id)
                )

                payment_terms_global = request.form.get('payment_terms') or None

                # 2) insert new
                for item in pr_items:
                    uid = str(item['id'])
                    app.logger.debug("Processing pr_item_id=%s uid=%s", item["id"], uid)

                    unit_price = request.form.get(f'unit_price_{uid}') or None
                    stock_availability = request.form.get(f'stock_availability_{uid}') or None
                    lead_time = request.form.get(f'lead_time_{uid}') or None
                    warranty = request.form.get(f'warranty_{uid}') or None
                    notes = request.form.get(f'notes_{uid}') or None
                    ono = 1 if request.form.get(f"ono_{uid}") else 0

                    ono_width = request.form.get(f'ono_width_{uid}') or None
                    ono_length = form_last_nonempty(f'ono_length_{uid}')
                    ono_thickness = request.form.get(f'ono_thickness_{uid}') or None
                    ono_dim_a = request.form.get(f'ono_dim_a_{uid}') or None
                    ono_dim_b = request.form.get(f'ono_dim_b_{uid}') or None
                    ono_diameter = request.form.get(f'ono_diameter_{uid}') or None
                    ono_uom = request.form.get(f'ono_uom_{uid}') or None
                    ono_uom_qty = request.form.get(f'ono_uom_qty_{uid}') or None

                    cert_file_id = None
                    file_key = f'cert_{uid}'
                    if file_key in request.files:
                        cert_file = request.files[file_key]
                        if cert_file and cert_file.filename:
                            cert_file_id = save_uploaded_file(conn, cert_file, task_id, supplier_id, item['id'])

                    has_any_input = any([
                        unit_price, stock_availability, lead_time, warranty, notes,
                        cert_file_id,
                        ono_width, ono_length, ono_thickness,
                        ono_dim_a, ono_dim_b,
                        ono_diameter,
                        ono_uom, ono_uom_qty
                    ]) or (ono == 1)

                    if has_any_input:
                        conn.execute(
                            """
                            INSERT INTO supplier_quotes (
                                task_id, supplier_id, pr_item_id,
                                unit_price, stock_availability,
                                cert_file_id,
                                lead_time, warranty, payment_terms, ono,
                                ono_width, ono_length, ono_thickness,
                                ono_dim_a, ono_dim_b,
                                ono_diameter,
                                ono_uom,
                                ono_uom_qty,
                                notes
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                task_id, supplier_id, item['id'],
                                unit_price, stock_availability,
                                cert_file_id,
                                lead_time, warranty, payment_terms_global, ono,
                                ono_width, ono_length, ono_thickness,
                                ono_dim_a, ono_dim_b,
                                ono_diameter,
                                ono_uom,
                                ono_uom_qty,
                                notes
                            )
                        )

                # 3) mark replied
                conn.execute(
                    'UPDATE task_suppliers SET replied_at = CURRENT_TIMESTAMP WHERE task_id = ? AND supplier_id = ?',
                    (task_id, supplier_id)
                )

                conn.commit()
                flash('Quotes saved.', 'success')
                return redirect(url_for('task_responses', task_id=task_id))

            except sqlite3.Error:
                conn.rollback()
                app.logger.exception("DB error while saving quotes (task_id=%s supplier_id=%s)", task_id, supplier_id)
                flash("We couldn't save the quotes due to a database issue. Please try again.", "error")

            except Exception:
                conn.rollback()
                app.logger.exception("Unhandled error while saving quotes (task_id=%s supplier_id=%s)", task_id, supplier_id)
                flash("Something went wrong while saving. Please try again.", "error")

            # If we reach here: POST failed, re-load what’s currently in DB (after rollback)
            quotes_map, payment_terms_default = load_existing_quotes()

        # GET or failed POST -> show form
        return render_template(
            'quotes_form.html',
            task=task,
            supplier=supplier,
            pr_items=pr_items,
            quotes_map=quotes_map,
            payment_terms_default=payment_terms_default
        )

    finally:
        conn.close()

@app.route('/supplier/quote-form/<token>', methods=['GET', 'POST'])
def supplier_quote_form(token):
    try:
        data = get_quote_serializer().loads(token)
        task_id = data.get('task_id')
        supplier_id = data.get('supplier_id')
    except BadSignature:
        # Better: render_template("errors/400.html", message="Invalid or expired link"), 400
        return "Invalid or expired link", 400

    conn = get_db_connection()
    try:
        task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
        supplier = conn.execute('SELECT * FROM suppliers WHERE id = ?', (supplier_id,)).fetchone()
        if not task or not supplier:
            # Better: render_template("errors/404.html", message="Task or supplier not found"), 404
            return "Task or supplier not found", 404

        def form_last_nonempty(key: str):
            vals = request.form.getlist(key)
            for v in reversed(vals):
                if v is None:
                    continue
                s = str(v).strip()
                if s != "":
                    return s
            return None

        ts_row = conn.execute(
            'SELECT assigned_items FROM task_suppliers WHERE task_id = ? AND supplier_id = ?',
            (task_id, supplier_id)
        ).fetchone()

        assigned_ids = None
        if ts_row and ts_row['assigned_items']:
            try:
                assigned_ids = [int(x) for x in json.loads(ts_row['assigned_items'])]
            except Exception:
                assigned_ids = None

        pr_items = conn.execute(
            'SELECT * FROM pr_items WHERE task_id = ?',
            (task_id,)
        ).fetchall()

        if assigned_ids:
            pr_items = [item for item in pr_items if item['id'] in assigned_ids]

        if request.method == 'POST':
            try:
                # 1) clear old
                conn.execute(
                    'DELETE FROM supplier_quotes WHERE task_id = ? AND supplier_id = ?',
                    (task_id, supplier_id)
                )

                payment_terms_global = request.form.get('payment_terms') or None

                # Handle Master Quotation File
                quotation_file = request.files.get('quotation_file')
                if quotation_file and quotation_file.filename:
                    # Save file (pr_item_id is None for general task files)
                    q_file_id = save_uploaded_file(conn, quotation_file, task_id, supplier_id, None)
                    if q_file_id:
                        conn.execute(
                            'UPDATE task_suppliers SET quotation_file_id = ? WHERE task_id = ? AND supplier_id = ?',
                            (q_file_id, task_id, supplier_id)
                        )

                # 2) insert new
                for item in pr_items:
                    uid = str(item['id'])

                    unit_price = request.form.get(f'unit_price_{uid}') or None
                    stock_availability = request.form.get(f'stock_availability_{uid}') or None
                    lead_time = request.form.get(f'lead_time_{uid}') or None
                    warranty = request.form.get(f'warranty_{uid}') or None
                    notes = request.form.get(f'notes_{uid}') or None
                    ono = 1 if request.form.get(f"ono_{uid}") else 0

                    # O.N.O. alternate dimensions
                    ono_width = request.form.get(f'ono_width_{uid}') or None
                    ono_length = form_last_nonempty(f'ono_length_{uid}')
                    ono_thickness = request.form.get(f'ono_thickness_{uid}') or None
                    ono_dim_a = request.form.get(f'ono_dim_a_{uid}') or None
                    ono_dim_b = request.form.get(f'ono_dim_b_{uid}') or None
                    ono_diameter = request.form.get(f'ono_diameter_{uid}') or None
                    ono_uom = request.form.get(f'ono_uom_{uid}') or None
                    ono_uom_qty = request.form.get(f'ono_uom_qty_{uid}') or None

                    # Handle certificate file upload
                    cert_file_id = None
                    if f'cert_{uid}' in request.files:
                        cert_file = request.files[f'cert_{uid}']
                        if cert_file and cert_file.filename:
                            # optional: validate allowed extension here (pdf only)
                            # if not allowed_file(cert_file.filename): raise ValueError("Only PDF allowed")
                            cert_file_id = save_uploaded_file(conn, cert_file, task_id, supplier_id, item['id'])

                    # Save row if ANY meaningful input exists, OR ONO checked
                    has_any_input = any([
                        unit_price, stock_availability, lead_time, warranty, notes,
                        cert_file_id,
                        ono_width, ono_length, ono_thickness,
                        ono_dim_a, ono_dim_b, ono_diameter,
                        ono_uom, ono_uom_qty
                    ]) or (ono == 1)

                    if has_any_input:
                        conn.execute(
                            """
                            INSERT INTO supplier_quotes (
                                task_id, supplier_id, pr_item_id,
                                unit_price, stock_availability,
                                cert_file_id,
                                lead_time, warranty, payment_terms, ono,
                                ono_width, ono_length, ono_thickness,
                                ono_dim_a, ono_dim_b,
                                ono_diameter,
                                ono_uom,
                                ono_uom_qty,
                                notes
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                task_id, supplier_id, item['id'],
                                unit_price, stock_availability,
                                cert_file_id,
                                lead_time, warranty, payment_terms_global, ono,
                                ono_width, ono_length, ono_thickness,
                                ono_dim_a, ono_dim_b,
                                ono_diameter,
                                ono_uom,
                                ono_uom_qty,
                                notes
                            )
                        )

                # 3) mark replied + log
                conn.execute(
                    'UPDATE task_suppliers SET replied_at = COALESCE(replied_at, CURRENT_TIMESTAMP) WHERE task_id = ? AND supplier_id = ?',
                    (task_id, supplier_id)
                )

                conn.execute(
                    '''
                    INSERT INTO email_logs (task_id, supplier_id, email_type, subject, body, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (task_id, supplier_id, 'supplier_form', f'Quote submitted by {supplier["name"]}', None, 'received')
                )

                conn.commit()
                return render_template('supplier_form_success.html', supplier=supplier, task=task)

            except sqlite3.Error:
                conn.rollback()
                app.logger.exception("DB error while saving supplier form (task_id=%s supplier_id=%s)", task_id, supplier_id)
                # Show supplier-friendly message on the same page
                flash("We couldn't save your quotation due to a system issue. Please try again.", "error")
                # fall through to re-render the form

            except Exception:
                conn.rollback()
                app.logger.exception("Unexpected error while saving supplier form (task_id=%s supplier_id=%s)", task_id, supplier_id)
                flash("Something went wrong while submitting your quotation. Please review and try again.", "error")
                # fall through to re-render the form

        # GET or POST failure -> show form again
        return render_template(
            'supplier_public_quote.html',
            task=task,
            supplier=supplier,
            pr_items=pr_items
        )

    finally:
        conn.close()

@app.route('/debug/quotes/<int:task_id>/<int:supplier_id>', methods=['GET'])
def debug_quotes(task_id, supplier_id):
    """Return JSON dump of supplier_quotes for debugging (task+supplier)."""
    if 'user_id' not in session:
        return jsonify({'error': 'login required'}), 403

    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM supplier_quotes WHERE task_id = ? AND supplier_id = ?', (task_id, supplier_id)).fetchall()
    conn.close()
    quotes = [dict(r) for r in rows]
    return jsonify(quotes)

@app.route('/task/<int:task_id>/export-comparison')
def export_comparison(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    BASE_COLS = 9  # 3 fixed cols + 4 dimension cols + quantity + weight
    SUPPLIER_START_COL = BASE_COLS + 1  # 10

    conn = get_db_connection()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task or (session['role'] != 'admin' and task['user_id'] != session['user_id']):
        flash('Task not found or access denied', 'error')
        conn.close()
        return redirect(url_for('task_list'))

    pr_items = conn.execute('SELECT * FROM pr_items WHERE task_id = ?', (task_id,)).fetchall()
    pr_items = [dict(r) for r in pr_items]
    quotes = conn.execute('''
        SELECT q.*, s.name as supplier_name, ts.replied_at as replied_at
        FROM supplier_quotes q
        JOIN suppliers s ON q.supplier_id = s.id
        LEFT JOIN task_suppliers ts ON ts.supplier_id = q.supplier_id AND ts.task_id = q.task_id
        WHERE q.task_id = ?
    ''', (task_id,)).fetchall()
    conn.close()

    def to_float(x):
        try:
            if x is None or x == "":
                return None
            return float(x)
        except (ValueError, TypeError):
            return None

    def lead_time_to_days(v):
        """Convert common lead time text into comparable 'days' number."""
        if v is None:
            return None
        s = str(v).strip().lower()
        if not s:
            return None

        # treat ready stock / immediate as 0 days (best)
        if "ready" in s or "immediate" in s or "instock" in s or "in stock" in s:
            return 0.0

        m = re.search(r"(\d+(\.\d+)?)", s)
        if not m:
            return None
        num = float(m.group(1))

        if "week" in s:
            return num * 7.0
        if "month" in s:
            return num * 30.0
        if "day" in s:
            return num

        # If user typed plain "7" assume days
        return num

    def _norm(x):
        """Normalize dimension cell value to a clean string for Excel + grouping."""
        if x is None:
            return ""
        s = str(x).strip()
        return "" if s.lower() in ("none", "null") else s

    def _num(x):
        """Convert dimension to float if possible."""
        try:
            s = _norm(x)
            return None if s == "" else float(s)
        except Exception:
            return None

    def dims_for_row(category, base_dim_display, q):
        """
        Return dims tuple (d1,d2,d3,d4) for this quote row.
        If q is ONO and has overrides, use them; otherwise fall back to base dims.
        """
        d1, d2, d3, d4 = base_dim_display

        if not q or q.get("ono") != 1:
            return (_norm(d1), _norm(d2), _norm(d3), _norm(d4))

        if category in ["Steel Plates", "Stainless Steel"]:
            w = _norm(q.get("ono_width")) or _norm(d1)
            L = _norm(q.get("ono_length")) or _norm(d3)
            thk = _norm(q.get("ono_thickness")) or _norm(d4)
            return (w, "", L, thk)

        if category == "Angle Bar":
            a = _norm(q.get("ono_dim_a")) or _norm(d1)
            b = _norm(q.get("ono_dim_b")) or _norm(d2)
            L = _norm(q.get("ono_length")) or _norm(d3)
            thk = _norm(q.get("ono_thickness")) or _norm(d4)
            return (a, b, L, thk)

        if category in ["Rebar", "Bolts, Fasteners"]:
            d = _norm(q.get("ono_diameter")) or _norm(d1)
            L = _norm(q.get("ono_length")) or _norm(d3)
            return (d, "", L, "")

        # other categories
        uq = _norm(q.get("ono_uom_qty")) or _norm(d1)
        uom = _norm(q.get("ono_uom")) or _norm(d2)
        return (uq, uom, "", "")

    def weight_for_dims(category, dims, base_weight):
        """
        Compute weight for the row dims. If cannot compute, return base_weight.
        """
        if category in ["Steel Plates", "Stainless Steel"]:
            w = _num(dims[0]); L = _num(dims[2]); thk = _num(dims[3])
            if w and L and thk:
                return round((w * L * thk * 7.85) / 1_000_000, 2)

        elif category in ["Rebar", "Bolts, Fasteners"]:
            d = _num(dims[0]); L = _num(dims[2])
            if d and L:
                import math
                return round((math.pi / 4) * (d ** 2) * L * 7.85 * 0.000001, 2)

        elif category == "Angle Bar":
            a = _num(dims[0]); b = _num(dims[1]); L = _num(dims[2]); thk = _num(dims[3])
            if a and b and L and thk:
                return round((L * thk * (a + b - thk) * 7.85) / 1_000_000, 2)

        return base_weight

    SUPPLIER_BLOCK_COLS = 7
    OFF_RATE  = 0
    OFF_PRICE = 1
    OFF_TOTAL = 2
    OFF_LEAD  = 3
    OFF_STOCK = 4
    OFF_COA   = 5
    OFF_REMARKS = 6

    suppliers = {}  # supplier_id -> supplier_name
    supplier_terms = {}  # supplier_id -> set(payment_terms)

    for q in quotes:
        sid = q['supplier_id']
        suppliers.setdefault(sid, q['supplier_name'])

        pt = (q['payment_terms'] or "").strip()
        if pt:
            supplier_terms.setdefault(sid, set()).add(pt)

    suppliers_list = sorted(suppliers.items(), key=lambda x: x[1])  # (sid, name)

    def supplier_header_label(supplier_id, supplier_name):
        terms = supplier_terms.get(supplier_id, set())
        if not terms:
            return supplier_name
        if len(terms) == 1:
            return f"{supplier_name} ({next(iter(terms))})"
        return f"{supplier_name} (Multiple)"

    wb = Workbook()
    ws = wb.active
    ws.title = "Comparison"

    row1 = [
        "Item Name (O.N.O.)",
        "Brand/Specification",
        "Category",
        "Dimensions (mm)", "", "", "",   # 4 cols for dimensions
        "Quantity",
        "Weight (Kg)"
    ]
    for supplier_id, supplier_name in suppliers_list:
        row1.extend([supplier_header_label(supplier_id, supplier_name)] + [""] * (SUPPLIER_BLOCK_COLS - 1))
    ws.append(row1)

    # Determine dynamic dimension headers based on PR category
    dim_headers = ["W/A/D/UOM", "B", "L", "Thk"] # Default fallback
    if pr_items:
        cat = pr_items[0].get('item_category', '')
        if cat in ["Steel Plates", "Stainless Steel"]:
            dim_headers = ["Width", "", "Length", "Thk"]
        elif cat == "Angle Bar":
            dim_headers = ["A", "B", "Length", "Thk"]
        elif cat in ["Rebar", "Bolts, Fasteners"]:
            dim_headers = ["Dia", "", "Length", ""]
        else:
            # Check if it uses UOM logic (category not in specific list)
            dim_headers = ["Qty", "UOM", "", ""]

    row2 = [
        "", "", "",
        dim_headers[0],
        dim_headers[1],
        dim_headers[2],
        dim_headers[3],
        "", ""
    ]
    for supplier_id, supplier_name in suppliers_list:
        row2.extend([
            "Rate (RM/Kg)",
            "Quoted Price (RM)",
            "Total Amount Quoted (RM)",
            "Delivery Lead Time (Days)",
            "Stock Availability",
            "COA",
            "Remarks"
        ])
    ws.append(row2)

    bold = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center")

    # ---- Header styling (Row 1–2) ----
    header_fill = PatternFill(fill_type="solid", fgColor="8DB4E2")  # dark blue
    header_font = Font(bold=True, color="0000FF")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Make sure we color all header cells across the full table width
    max_col = ws.max_column

    for r in (1, 2):
        for c in range(1, max_col + 1):
            cell = ws.cell(row=r, column=c)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_align


    # Merge and center Item Name, Brand, Category (cols 1-3)
    for col in range(1, 4):
        ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)
        cell = ws.cell(row=1, column=col)
        cell.font = bold
        cell.alignment = center

    # Merge and center Dimensions (now cols 4-7)
    ws.merge_cells(start_row=1, start_column=4, end_row=1, end_column=7)
    cell = ws.cell(row=1, column=4)
    cell.font = bold
    cell.alignment = center

    # Center dim headers row2 (cols 4-7)
    for col in range(4, 8):
        c = ws.cell(row=2, column=col)
        c.font = bold
        c.alignment = center

    # Merge and center Quantity and Weight (now cols 8-9)
    for col in range(8, 10):
        ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)
        c = ws.cell(row=1, column=col)
        c.font = bold
        c.alignment = center

    # Merge and center each supplier header (8 columns each)
    col_idx = SUPPLIER_START_COL
    for supplier_id, supplier_name in suppliers_list:
        ws.merge_cells(start_row=1, start_column=col_idx, end_row=1, end_column=col_idx + (SUPPLIER_BLOCK_COLS - 1))
        c = ws.cell(row=1, column=col_idx)
        c.font = bold
        c.alignment = center
        col_idx += SUPPLIER_BLOCK_COLS

    # Format row 2 as bold and centered
    for cell in ws[2]:
        cell.font = bold
        cell.alignment = center

    best_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")   # light green
    total_fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid") # light gray

    quotes_by_item = {}
    for q in quotes:
        item_id = q['pr_item_id']
        quotes_by_item.setdefault(item_id, {})
        quotes_by_item[item_id][q['supplier_id']] = dict(q)

    cert_links = {}  # (row, col) -> url
    supplier_total_amounts = {sid: 0.0 for sid, _ in suppliers_list}

    current_row = 3
    for item in pr_items:
        category = (item['item_category'] or '').strip()
        w = item['width'] or None
        l = item['length'] or None
        thk = item['thickness'] or None
        dim_a = item['dim_a'] or None
        dim_b = item['dim_b'] or None
        diameter = item['diameter'] or None
        uom_qty = item['uom_qty'] or None
        uom = item['uom'] or None

        # Calculate weight based on category
        weight = ""
        weight_formula_applied = False
        
        # Steel Plates / Stainless Steel: (W * L * Thk * 7.85) / 1,000,000
        if category in ['Steel Plates', 'Stainless Steel']:
            if w and l and thk:
                try:
                    w_val = float(w)
                    l_val = float(l)
                    thk_val = float(thk)
                    weight = round((w_val * l_val * thk_val * 7.85) / 1000000, 2)
                    weight_formula_applied = True
                except (ValueError, TypeError):
                    weight = ""
        
        # Rebar / Bolts, Fasteners: (π/4) * D² * L * 7.85 * 10⁻⁶
        elif category in ['Rebar', 'Bolts, Fasteners']:
            if diameter and l:
                try:
                    import math
                    d_val = float(diameter)
                    l_val = float(l)
                    weight = round((math.pi / 4) * (d_val ** 2) * l_val * 7.85 * 0.000001, 2)
                    weight_formula_applied = True
                except (ValueError, TypeError):
                    weight = ""
        
        # Angle Bar: (L * Thk * (A + B - Thk) * 7.85) / 1,000,000
        elif category == 'Angle Bar':
            if l and thk and dim_a and dim_b:
                try:
                    l_val = float(l)
                    thk_val = float(thk)
                    a_val = float(dim_a)
                    b_val = float(dim_b)
                    weight = round((l_val * thk_val * (a_val + b_val - thk_val) * 7.85) / 1000000, 2)
                    weight_formula_applied = True
                except (ValueError, TypeError):
                    weight = ""
        
        # For "Other" categories, no weight calculation
        else:
            weight = "N/A"

        # Build dimension display for this item
        # dim_display order = [Dim1, Dim2, Dim3, Dim4]
        # Dim1 = W/A/D/UOMQty, Dim2 = B, Dim3 = L, Dim4 = Thk
        base_dim_display = ["", "", "", ""]
        if category in ["Steel Plates", "Stainless Steel"]:
            w = item.get('width') or ''
            l = item.get('length') or ''
            thk = item.get('thickness') or ''
            base_dim_display = [w, "", l, thk]
        elif category == "Angle Bar":
  
            base_dim_display = [a, b, l, thk]
        elif category in ["Rebar", "Bolts, Fasteners"]:
            d = item.get('diameter') or ''
            l = item.get('length') or ''
            base_dim_display = [d, "", l, ""]
        else:
            uom = item.get('uom') or ''
            uom_qty = item.get('uom_qty') or ''
            base_dim_display = [uom_qty, "", "", ""]

        item_quotes_map = quotes_by_item.get(item['id'], {})
        
        metric_candidates = {
            "rate": [],
            "price": [],
            "total": [],
            "lead": []
        }

        # ---------------------------------------------------------
        # Group quotes by "Dimension Key"
        # Key: (is_ono, (dim1, dim2, dim3, dim4))
        #   - Standard Quote: (False, base_dim_display)
        #   - O.N.O Quote:    (True, (d1, d2, d3... from ono cols))
        # ---------------------------------------------------------
        
        # Structure: key -> { supplier_id: quote }
        grouped_quotes = {}
        
        # Ensure the "Standard" group always exists
        standard_key = (False, tuple(base_dim_display))
        grouped_quotes[standard_key] = {} 
        
        # Distribute quotes into groups
        # Normalize standard dims so grouping is consistent
        standard_dims = tuple(_norm(x) for x in base_dim_display)
        standard_key = (False, standard_dims)
        grouped_quotes = {standard_key: {}}

        # Distribute quotes into groups (STANDARD vs ONO with fallback)
        for supplier_id, supplier_name in suppliers_list:
            q = item_quotes_map.get(supplier_id)
            if not q:
                continue

            if q.get("ono") == 1:
                # ✅ this applies ONO dims but falls back to base dims when ONO fields are blank
                eff_dims = dims_for_row(category, base_dim_display, q)   # returns 4-tuple of strings
                key = (True, tuple(eff_dims))
                grouped_quotes.setdefault(key, {})[supplier_id] = q
            else:
                grouped_quotes[standard_key][supplier_id] = q


        # ---------------------------------------------------------
        # Render Rows
        # ---------------------------------------------------------
        def sort_keys(k):
            is_ono, dims = k
            return (is_ono, dims)
            
        sorted_keys = sorted(grouped_quotes.keys(), key=sort_keys)
        
        for key in sorted_keys:
            is_ono, dims = key
            quotes_for_row_map = grouped_quotes[key]
            
            # Skip empty O.N.O rows
            if is_ono and not quotes_for_row_map:
                continue

            # Construct Label
            row_label = f"{item['item_name']} (O.N.O)" if is_ono else item['item_name']

            row = [
                row_label,
                item["brand"] or "",
                category,
                dims[0], dims[1], dims[2], dims[3],
                item["quantity"] or "",
                weight
            ]
            
            # Fill supplier columns
            # Metric candidates for highlighting *within this row*
            row_metric_candidates = {
                "rate": [],
                "price": [],
                "total": [],
                "lead": []
            }

            col_idx = SUPPLIER_START_COL
            for supplier_id, supplier_name in suppliers_list:
                q = quotes_for_row_map.get(supplier_id)
                
                # Logic: Quotes are already pre-filtered by the group key
                # So we just render 'q' if it exists.
                
                should_include = True # effectively always true if q exists in this map
                if q:
                    # q is guaranteed to match the row type thanks to grouping logic
                    pass
                
                if q and should_include:
                    cert_display = ""
                    cert_url = None
                    
                    # Handle File Asset ID (New) or Legacy Path
                    if q.get('cert_file_id'):
                        cert_display = "PDF"
                        # Generate full URL pointing to /file/<id>
                        cert_url = public_url_for("serve_file", file_id=q["cert_file_id"])
                    elif q.get('cert'):
                        # Legacy fallback
                        val = str(q['cert'])
                        if val.isdigit():
                            cert_display = "PDF"
                            cert_url = public_url_for("serve_file", file_id=q["cert_file_id"])
                        else:
                            # Old path style
                            cert_display = "PDF"
                            # Note: Local paths won't open in Excel, but preserving legacy behavior
                            cert_url = val 

                    unit_price = q['unit_price'] if q['unit_price'] is not None else ""
                    unit_price_val = to_float(unit_price)

                    qty_val = to_float(item['quantity'])
                    weight_val = to_float(weight)

                    rate_val = ""
                    if unit_price_val is not None and weight_val not in (None, 0):
                        rate_val = round(unit_price_val / weight_val, 4)

                    total_amount_val = ""
                    if unit_price_val is not None and qty_val is not None:
                        total_amount_val = round(unit_price_val * qty_val, 2)
                        if not is_ono: # Only sum standard quotes to total? Or sum lowest? 
                            # Logic: If multiple rows exist for same item, usually you pick one.
                            # For the "Total Amount" line at bottom, simplistic summation might be misleading if we have split rows.
                            # Strategy: We accumulate totals based on "Standard" quotes only for the summary?
                            # Or we sum everything? Let's sum everything for now, user can interpret.
                            supplier_total_amounts[supplier_id] += float(total_amount_val)

                    row.extend([
                        rate_val,
                        unit_price,
                        total_amount_val,
                        q.get('lead_time') or "",
                        q.get('stock_availability') or "",
                        cert_display,
                        q.get('notes') or ""
                    ])

                    if cert_url:
                        cert_links[(current_row, col_idx + OFF_COA)] = cert_url

                    # highlight candidates
                    row_metric_candidates["rate"].append((col_idx + OFF_RATE, to_float(rate_val)))
                    row_metric_candidates["price"].append((col_idx + OFF_PRICE, unit_price_val))
                    row_metric_candidates["total"].append((col_idx + OFF_TOTAL, to_float(total_amount_val)))
                    row_metric_candidates["lead"].append((col_idx + OFF_LEAD, lead_time_to_days(q.get('lead_time'))))

                    col_idx += SUPPLIER_BLOCK_COLS
                else:
                    # No quote from this supplier OR quote belongs to the other row type
                    row.extend([""] * SUPPLIER_BLOCK_COLS)
                    col_idx += SUPPLIER_BLOCK_COLS

            ws.append(row)

            # Apply per-row best highlighting (lowest wins)
            for key in ["rate", "price", "total", "lead"]:
                vals = [(col, v) for (col, v) in row_metric_candidates[key] if v is not None]
                if not vals:
                    continue
                best_val = min(v for _, v in vals)
                for col, v in vals:
                    if v == best_val:
                        ws.cell(row=current_row, column=col).fill = best_fill

            current_row += 1 
    
    # After rows loop
    totals_row = current_row
    ws.merge_cells(start_row=totals_row, start_column=1, end_row=totals_row, end_column=BASE_COLS)
    label_cell = ws.cell(row=totals_row, column=1)
    label_cell.value = "TOTAL (RM)"
    label_cell.font = Font(bold=True)
    label_cell.alignment = Alignment(horizontal="right", vertical="center")
    label_cell.fill = total_fill

    total_cells = []  # (col, value)
    for i, (sid, _sname) in enumerate(suppliers_list):
        total_col = SUPPLIER_START_COL + i * SUPPLIER_BLOCK_COLS + OFF_TOTAL
        c = ws.cell(row=totals_row, column=total_col)
        val = supplier_total_amounts.get(sid, 0.0)

        if val and val != 0.0:
            c.value = round(val, 2)
            c.number_format = '#,##0.00'
            total_cells.append((total_col, float(c.value)))
        else:
            c.value = ""

        c.font = Font(bold=True)
        c.fill = total_fill
        c.alignment = Alignment(horizontal="center", vertical="center")

    # Highlight best (lowest) total
    if total_cells:
        best_total = min(v for _, v in total_cells)
        for col, v in total_cells:
            if v == best_total:
                ws.cell(row=totals_row, column=col).fill = best_fill

    thin_side = Side(border_style="thin", color="000000")
    table_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    max_col = ws.max_column
    max_row = ws.max_row
    col_max_length = [0] * (max_col + 1)

    for r in range(1, max_row + 1):
        max_lines = 1
        for c in range(1, max_col + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = table_border
            cell.alignment = Alignment(
                horizontal=(cell.alignment.horizontal or "left"),
                vertical="center",
                wrap_text=True
            )

            value = cell.value if cell.value is not None else ""
            text = str(value)
            col_max_length[c] = max(col_max_length[c], len(text))

            lines = text.count("\n") + 1
            max_lines = max(max_lines, lines)

        ws.row_dimensions[r].height = max(15, max_lines * 15)

    # Add COA hyperlinks
    for (row, col), url in cert_links.items():
        cell = ws.cell(row=row, column=col)
        cell.hyperlink = url
        cell.font = Font(underline="single")

    # Column widths
    for c in range(1, max_col + 1):
        col_letter = get_column_letter(c)
        width = int(col_max_length[c] * 1.2) + 2
        ws.column_dimensions[col_letter].width = max(8, min(60, width))

    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 20

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"comparison_task_{task_id}.xlsx",
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.route('/suppliers')
def suppliers():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    suppliers_list = conn.execute('''
        SELECT s.*, GROUP_CONCAT(c.name) as categories
        FROM suppliers s
        LEFT JOIN supplier_categories sc ON s.id = sc.supplier_id
        LEFT JOIN categories c ON sc.category_id = c.id
        WHERE s.is_active = 1
        GROUP BY s.id
    ''').fetchall()
    
    categories = conn.execute('SELECT * FROM categories').fetchall()
    conn.close()
    
    return render_template('supplier_list.html', 
                         suppliers=suppliers_list, 
                         categories=categories,
                         user_role=session['role'])

@app.route('/edit-supplier/<int:supplier_id>', methods=['GET', 'POST'])
def edit_supplier(supplier_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('suppliers'))
    
    conn = get_db_connection()
    
    if request.method == 'POST':
        name = request.form['name']
        contact_name = request.form['contact_name']
        email = request.form['email']
        contact_number = request.form['contact_number']
        address = request.form['address']
        products_services = request.form['products_services']
        selected_categories = request.form.getlist('categories')
        
        # Update supplier
        conn.execute('''
            UPDATE suppliers 
            SET name=?, contact_name=?, email=?, contact_number=?, address=?, products_services=?
            WHERE id=?
        ''', (name, contact_name, email, contact_number, address, products_services, supplier_id))
        
        # Update categories
        conn.execute('DELETE FROM supplier_categories WHERE supplier_id = ?', (supplier_id,))
        for category_id in selected_categories:
            conn.execute(
                'INSERT INTO supplier_categories (supplier_id, category_id) VALUES (?, ?)',
                (supplier_id, category_id)
            )
        
        conn.commit()
        conn.close()
        flash('Supplier updated successfully!', 'success')
        return redirect(url_for('suppliers'))
    
    supplier = conn.execute('SELECT * FROM suppliers WHERE id = ?', (supplier_id,)).fetchone()
    categories = conn.execute('SELECT * FROM categories').fetchall()
    supplier_categories = conn.execute(
        'SELECT category_id FROM supplier_categories WHERE supplier_id = ?', 
        (supplier_id,)
    ).fetchall()
    supplier_category_ids = [sc['category_id'] for sc in supplier_categories]
    
    conn.close()
    
    return render_template('edit_supplier.html', 
                         supplier=supplier, 
                         categories=categories,
                         supplier_category_ids=supplier_category_ids)

@app.route('/add-supplier', methods=['GET', 'POST'])
def add_supplier():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('suppliers'))
    
    conn = get_db_connection()
    
    if request.method == 'POST':
        name = request.form['name']
        contact_name = request.form['contact_name']
        email = request.form['email']
        contact_number = request.form['contact_number']
        address = request.form['address']
        products_services = request.form['products_services']
        selected_categories = request.form.getlist('categories')
        
        # Validate email
        if not validate_email(email):
            flash('Invalid email format', 'error')
            return render_template('edit_supplier.html', categories=conn.execute('SELECT * FROM categories').fetchall())
        
        # Validate phone
        if contact_number and not validate_phone(contact_number):
            flash('Invalid phone number format', 'error')
            return render_template('edit_supplier.html', categories=conn.execute('SELECT * FROM categories').fetchall())

        # Check for duplicate supplier (Name or Email)
        existing = conn.execute('SELECT id, name FROM suppliers WHERE name = ? OR email = ?', (name, email)).fetchone()
        if existing:
            flash(f'Supplier already exists (Name: {existing["name"]}). Duplicate entry prevented.', 'error')
            return render_template('edit_supplier.html', categories=conn.execute('SELECT * FROM categories').fetchall())
        
        # Add supplier
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO suppliers (name, contact_name, email, contact_number, address, products_services)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, contact_name, email, contact_number, address, products_services))
        
        supplier_id = cursor.lastrowid
        
        # Add categories
        for category_id in selected_categories:
            conn.execute(
                'INSERT INTO supplier_categories (supplier_id, category_id) VALUES (?, ?)',
                (supplier_id, category_id)
            )
        
        conn.commit()
        conn.close()
        flash('Supplier added successfully!', 'success')
        return redirect(url_for('suppliers'))
    
    categories = conn.execute('SELECT * FROM categories').fetchall()
    conn.close()
    
    return render_template('edit_supplier.html', categories=categories)

@app.route('/delete-task/<int:task_id>')
def delete_task(task_id):
    if 'user_id' not in session:
        flash('Access denied', 'error')
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Verify task ownership
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task or (session['role'] != 'admin' and task['user_id'] != session['user_id']):
        flash('Task not found or access denied', 'error')
        return redirect(url_for('task_list'))
    
    # Delete task and related records
    conn.execute('DELETE FROM pr_items WHERE task_id = ?', (task_id,))
    conn.execute('DELETE FROM task_suppliers WHERE task_id = ?', (task_id,))
    conn.execute('DELETE FROM email_logs WHERE task_id = ?', (task_id,))
    conn.execute('DELETE FROM supplier_quotes WHERE task_id = ?', (task_id,))
    conn.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    
    conn.commit()
    conn.close()
    flash('Task deleted successfully!', 'success')
    return redirect(url_for('task_list'))

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('login'))

def _send_email_via_sendgrid(to_email: str, to_name: str, subject: str, html_body: str) -> bool:
    """
    Send via SendGrid. Returns True on success; False if not configured or failed.
    """
    if not (SENDGRID_API_KEY and SENDGRID_SENDER):
        return False

    try:
        # Often fixes Windows/proxy TLS issues
        os.environ["SSL_CERT_FILE"] = certifi.where()

        sg = SendGridAPIClient(SENDGRID_API_KEY)
        message = Mail(
            from_email=Email(SENDGRID_SENDER, "Procurement Department"),
            to_emails=To(to_email, to_name or ""),
            subject=subject,
            html_content=html_body,
        )
        app.logger.info("Sending email via SendGrid to=%s subject=%s", to_email, subject)
        resp = sg.send(message)
        return 200 <= resp.status_code < 300
    except Exception:
        app.logger.exception("SendGrid send failed")
        return False


def _send_email_via_smtp(to_email: str, subject: str, html_body: str) -> bool:
    """
    Send via SMTP. Returns True on success, False on failure.
    """
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG['sender_email']
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(html_body, 'html'))

        app.logger.info("Sending email via SMTP to=%s subject=%s", to_email, subject)

        server = smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'])
        server.starttls()
        server.login(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['sender_password'])
        server.send_message(msg)
        server.quit()
        return True
    except Exception:
        app.logger.exception("SMTP send failed")
        return False


def send_email_html(to_email: str, subject: str, html_body: str, to_name: str = "") -> bool:
    """
    Unified reusable email sender:
    - Try SendGrid first (if configured)
    - Fall back to SMTP
    """
    if _send_email_via_sendgrid(to_email, to_name, subject, html_body):
        return True
    return _send_email_via_smtp(to_email, subject, html_body)


# Email sending function
def send_procurement_email(supplier_email, supplier_name, pr_items, task_name, assigned_item_ids=None, custom_content=None, subject=None, supplier_contact=None, quote_form_link=None):
    try:
        # Filter items for this specific supplier
        if assigned_item_ids:
            assigned_ids = [int(item_id) for item_id in assigned_item_ids]
            supplier_items = [item for item in pr_items if item['id'] in assigned_ids]
        else:
            supplier_items = pr_items
        
        if not supplier_items:
            print(f"No items assigned to {supplier_name}, skipping email")
            return False
        
        subject = subject or f"Procurement Inquiry - {task_name}"
        
        if custom_content:
            body = custom_content.replace('{supplier_name}', supplier_name)
            # Replace contact person placeholder if present
            if supplier_contact:
                body = body.replace('{contact_person}', supplier_contact)
            else:
                body = body.replace('{contact_person}', '')

            if quote_form_link:
                quote_html = f'<p><strong>Quotation Form Link:</strong> <a href="{quote_form_link}">{quote_form_link}</a></p>'

                # If user put a placeholder in the template, replace it
                if '{quote_form_link}' in body:
                    body = body.replace('{quote_form_link}', quote_form_link)
                # Otherwise, try to insert nicely before </body>
                elif '</body>' in body:
                    body = body.replace('</body>', quote_html + '</body>')
                else:
                    body += quote_html
        else:
            items_html = "<ul>"
            for item in supplier_items:
                item = dict(item)

                category = (item.get('item_category') or '').strip()
                dims = "N/A"
                if category in ['Steel Plates', 'Stainless Steel']:
                    w = item.get('width') or ''
                    l = item.get('length') or ''
                    thk = item.get('thickness') or ''
                    if w or l or thk:
                        dims = f"{w}mm x {l}mm x {thk}mm"
                elif category == 'Angle Bar':
                    a = item.get('dim_a') or ''
                    b = item.get('dim_b') or ''
                    l = item.get('length') or ''
                    thk = item.get('thickness') or ''
                    if a or b or l or thk:
                        dims = f"A={a}mm, B={b}mm, L={l}mm, Thk={thk}mm"
                elif category in ['Rebar', 'Bolts, Fasteners']:
                    d = item.get('diameter') or ''
                    l = item.get('length') or ''
                    if d or l:
                        dims = f"D={d}mm, L={l}mm"
                else:
                    uom = item.get('uom') or ''
                    uom_qty = item.get('uom_qty') or ''
                    if uom_qty and uom:
                        dims = f"{uom_qty} {uom}"
                    elif uom_qty:
                        dims = f"Qty: {uom_qty}"
                    elif uom:
                        dims = f"UOM: {uom}"

            items_html += f"""
            <li>
                <strong>Item:</strong> {item['item_name']}<br>
                <strong>Dimensions:</strong> {dims}<br>
                <strong>Brand / Specification:</strong> {item.get('brand') or 'N/A'}<br>
                <strong>Quantity:</strong> {item.get('quantity')}<br>
            </li>
            """

            items_html += "</ul>"
            
            body = f"""
            <html>
            <body>
                <h2>Procurement Inquiry</h2>
                <p>Dear {(supplier_name.strip() + ' from ' + supplier_contact.strip()) if (supplier_contact and supplier_contact.strip()) else (supplier_name.strip() if supplier_name else '')},</p>
                
                <p>We are inquiring about the following items for procurement:</p>
                
                {items_html}
                
                <p>Please provide us with your quotation including:</p>
                <ul>
                    <li>Payment terms</li>
                    <li>Unit Price (RM))</li>
                    <li>Delivery Lead Timeline</li>
                    <li>Stock Availability</li>
                    <li>Warranty (If Applicable)</li>
                    <li>Mill Certificate / Certificate of Analysis (COA)</li>
                </ul>

                <p>Please fill in the quotation in the link below:</p>
                <p>Supplier form: </p>
                <p>↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓</p>
                {quote_form_link}
                <p>↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑</p>
                
                <p>We look forward to your prompt response.</p>
                
                <p>Best regards,<br>
                Procurement Department</p>
            </body>
            </html>
            """

        ok = send_email_html(
            to_email=supplier_email,
            to_name=supplier_name or "",
            subject=subject,
            html_body=body
        )
        return ok

    except Exception:
        app.logger.exception("Email sending failed")
        return False



@app.route('/task/<int:task_id>/suppliers', methods=['GET', 'POST'])
def supplier_selection(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Verify task ownership
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task or (session['role'] != 'admin' and task['user_id'] != session['user_id']):
        flash('Task not found or access denied', 'error')
        return redirect(url_for('task_list'))
    
    if request.method == 'POST':
        # Process supplier-item assignments
        selected_suppliers = request.form.getlist('suppliers')
        item_assignments = {}
        
        # Process which items go to which suppliers
        for key, value in request.form.items():
            if key.startswith('supplier_') and key.endswith('_items'):
                supplier_id = key.replace('supplier_', '').replace('_items', '')
                assigned_items = request.form.getlist(key)
                if assigned_items:
                    item_assignments[supplier_id] = assigned_items
        
        # Clear existing selections
        conn.execute('DELETE FROM task_suppliers WHERE task_id = ?', (task_id,))
        
        # Add supplier selections with assigned items
        # Add supplier selections with assigned items
        for supplier_id in selected_suppliers:
            assignment_type = request.form.get(f'assignment_type_{supplier_id}')
            
            if assignment_type == 'specific':
                # Get specific items for this supplier
                # If no items checked, getlist returns [], which dumps to "[]"
                # This correctly represents "Specific items: None" instead of "All items"
                assigned_items = request.form.getlist(f'supplier_{supplier_id}_items')
                items_json = json.dumps(assigned_items)
            else:
                # 'all' compatible items -> NULL in database
                items_json = None
                
            conn.execute(
                'INSERT INTO task_suppliers (task_id, supplier_id, is_selected, assigned_items) VALUES (?, ?, ?, ?)',
                (task_id, supplier_id, True, items_json)
            )
        
        # Update task status
        conn.execute(
            'UPDATE tasks SET status = ? WHERE id = ?',
            ('select_suppliers', task_id)
        )
        
        conn.commit()
        conn.close()
        flash('Suppliers and item assignments saved successfully!', 'success')
        return redirect(url_for('email_preview', task_id=task_id))
    
    # Get PR items
    pr_items = conn.execute(
        'SELECT * FROM pr_items WHERE task_id = ?', (task_id,)
    ).fetchall()
    
    # Get unique categories from PR items
    categories = list(set([item['item_category'] for item in pr_items]))
    
    # Get suppliers that match ANY of the categories
    if categories:
        placeholders = ','.join('?' * len(categories))
        suppliers = conn.execute(f'''
            SELECT DISTINCT s.*, GROUP_CONCAT(c.name) as supplier_categories
            FROM suppliers s
            JOIN supplier_categories sc ON s.id = sc.supplier_id
            JOIN categories c ON sc.category_id = c.id
            WHERE c.name IN ({placeholders}) AND s.is_active = 1
            GROUP BY s.id
        ''', categories).fetchall()
    else:
        suppliers = []
    
    # Get already selected suppliers and their assigned items
    selected_data = conn.execute(
        'SELECT supplier_id, assigned_items FROM task_suppliers WHERE task_id = ? AND is_selected = 1',
        (task_id,)
    ).fetchall()
    
    selected_supplier_ids = []
    item_assignments = {}
    
    for data in selected_data:
        supplier_id = str(data['supplier_id'])
        selected_supplier_ids.append(supplier_id)
        if data['assigned_items']:
            try:
                assigned_items = json.loads(data['assigned_items'])
                item_assignments[supplier_id] = assigned_items
            except:
                item_assignments[supplier_id] = []
    
    conn.close()
    
    return render_template('supplier_selection.html', 
                         task=task, 
                         suppliers=suppliers, 
                         pr_items=pr_items,
                         selected_supplier_ids=selected_supplier_ids,
                         categories=categories,
                         item_assignments=item_assignments)

# Add route to delete supplier
@app.route('/delete-supplier/<int:supplier_id>')
def delete_supplier(supplier_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('suppliers'))
    
    conn = get_db_connection()
    
    # Soft delete by setting is_active to 0
    conn.execute('UPDATE suppliers SET is_active = 0 WHERE id = ?', (supplier_id,))
    conn.commit()
    conn.close()
    
    flash('Supplier deleted successfully!', 'success')
    return redirect(url_for('suppliers'))

# Add route for categories management (admin only)
@app.route('/categories')
def categories():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    categories_list = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    
    return render_template('categories.html', categories=categories_list)

@app.route('/add-category', methods=['POST'])
def add_category():
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'error': 'Access denied'}), 403
    
    name = request.form.get('name')
    if not name:
        flash('Category name is required', 'error')
        return redirect(url_for('categories'))
    
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO categories (name) VALUES (?)', (name,))
        conn.commit()
        flash('Category added successfully!', 'success')
    except sqlite3.IntegrityError:
        flash('Category already exists', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('categories'))

@app.route('/delete-category/<int:category_id>')
def delete_category(category_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('categories'))
    
    conn = get_db_connection()
    
    # Check if category is used by any suppliers
    suppliers_count = conn.execute(
        'SELECT COUNT(*) FROM supplier_categories WHERE category_id = ?', 
        (category_id,)
    ).fetchone()[0]
    
    if suppliers_count > 0:
        flash('Cannot delete category: it is being used by suppliers', 'error')
    else:
        conn.execute('DELETE FROM categories WHERE id = ?', (category_id,))
        conn.commit()
        flash('Category deleted successfully!', 'success')
    
    conn.close()
    return redirect(url_for('categories'))

@app.route('/category/<int:category_id>/items')
def category_items(category_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    category = conn.execute('SELECT * FROM categories WHERE id = ?', (category_id,)).fetchone()
    if not category:
        conn.close()
        flash('Category not found', 'error')
        return redirect(url_for('categories'))
        
    items = conn.execute('SELECT * FROM category_items WHERE category_id = ? ORDER BY name', (category_id,)).fetchall()
    conn.close()
    return render_template('category_items.html', category=category, items=items)

@app.route('/category/<int:category_id>/add-item', methods=['POST'])
def add_category_item(category_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('index'))
    
    name = request.form.get('name')
    if name:
        conn = get_db_connection()
        conn.execute('INSERT INTO category_items (category_id, name) VALUES (?, ?)', (category_id, name))
        conn.commit()
        conn.close()
        flash('Item added successfully', 'success')
    
    return redirect(url_for('category_items', category_id=category_id))

@app.route('/delete-category-item/<int:item_id>')
def delete_category_item(item_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    item = conn.execute('SELECT category_id FROM category_items WHERE id = ?', (item_id,)).fetchone()
    if item:
        category_id = item['category_id']
        conn.execute('DELETE FROM category_items WHERE id = ?', (item_id,))
        conn.commit()
        conn.close()
        flash('Item deleted successfully', 'success')
        return redirect(url_for('category_items', category_id=category_id))
    
    conn.close()
    return redirect(url_for('categories'))

def parse_reply_fields(body_text):
    """
    Try to extract:
      - unit price
      - total price
      - delivery timeline / lead time
      - warranty info
      - payment terms
    from a reasonably structured reply.

    Expected style (case-insensitive, flexible about spaces):
        Unit price: ...
        Total price: ...
        Delivery timeline: ...
        Warranty information: ...
        Payment terms: ...
    """
    # Normalize line endings a bit
    text = body_text.replace('\r\n', '\n').replace('\r', '\n')

    def extract(pattern):
        """
        Return the first capture group for regex `pattern` in text,
        or None if not found.
        """
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            return None
        return m.group(1).strip()

    unit_price = extract(r"unit\s+price\s*[:\-]\s*([^\n\r]+)")
    stock_availability = extract(r"total\s+price\s*[:\-]\s*([^\n\r]+)")
    lead_time = extract(r"(?:delivery\s+timeline|lead\s+time)\s*[:\-]\s*([^\n\r]+)")
    warranty = extract(r"warranty\s+information\s*[:\-]\s*([^\n\r]+)")
    payment_terms = extract(r"payment\s+terms\s*[:\-]\s*([^\n\r]+)")

    return {
        "unit_price": unit_price,
        "stock_availability": stock_availability,
        "lead_time": lead_time,
        "warranty": warranty,
        "payment_terms": payment_terms,
    }

# INBOUND_SECRET = os.environ.get("INBOUND_SECRET", "")  # set this in your env

# @app.route("/webhooks/sendgrid/inbound/<secret>", methods=["POST"])
# def sendgrid_inbound(secret):
#     # simple security so random people can’t POST fake replies
#     if not INBOUND_SECRET or secret != INBOUND_SECRET:
#         abort(403)

#     # SendGrid fields (multipart/form-data)
#     from_addr = request.form.get("from", "")
#     subject = request.form.get("subject", "")
#     raw_headers = request.form.get("headers", "")

#     # prefer text; fallback html
#     body_text = request.form.get("text") or ""
#     if not body_text:
#         body_text = request.form.get("html") or ""

#     # OPTIONAL: attachments are in request.files; you can ignore for now
#     # e.g. request.files.get("attachment1"), etc.

#     result = process_inbound_supplier_reply(
#         subject=subject,
#         from_addr=from_addr,
#         body_text=body_text,
#         raw_headers=raw_headers
#     )

#     return ("OK", 200)

def get_email_body(msg):
    """Extract text/plain part (or fallback) from an email.message.Message."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in disp:
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="ignore")
        # Fallback: no text/plain found
        for part in msg.walk():
            if part.get_content_type().startswith("text/"):
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="ignore")
        return ""
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            return msg.get_payload(decode=True).decode(charset, errors="ignore")
        except Exception:
            return str(msg.get_payload())

# def check_inbox_and_mark_replies():
#     """
#     Connect to the inbox via IMAP, find unread emails,
#     match them by sender email to suppliers, and mark
#     task_suppliers.replied_at for any pending tasks.
#     Returns number of suppliers/tasks updated.
#     """
#     processed = 0

#     print("=== IMAP CHECK START ===")
#     print("IMAP_SERVER:", IMAP_SERVER)
#     print("IMAP_USERNAME:", IMAP_USERNAME)


#     # 1. Connect to IMAP
#     try:
#         mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
#         mail.login(IMAP_USERNAME, IMAP_PASSWORD)
#     except Exception as e:
#         print(f"[IMAP] Login failed: {e}")
#         return 0

#     try:
#         mail.select("INBOX")
#         status, messages = mail.search(None, '(UNSEEN)')
#         if status != "OK":
#             print("[IMAP] Search failed")
#             mail.logout()
#             return 0

#         conn = get_db_connection()

#         for num in messages[0].split():
#             status, data = mail.fetch(num, "(RFC822)")
#             if status != "OK":
#                 continue

#             raw_email = data[0][1]
#             msg = email.message_from_bytes(raw_email)

#             # Decode subject (not essential for matching, but useful for logs)
#             raw_subject = msg.get("Subject", "")
#             decoded = decode_header(raw_subject)
#             subject_parts = []
#             for part, enc in decoded:
#                 if isinstance(part, bytes):
#                     subject_parts.append(part.decode(enc or "utf-8", errors="ignore"))
#                 else:
#                     subject_parts.append(part)
#             subject = "".join(subject_parts)

#             from_addr = email.utils.parseaddr(msg.get("From"))[1].strip().lower()
#             print(f"[IMAP] New email from {from_addr} subject={subject!r}")

#             # ----- FIND SUPPLIER BY EMAIL -----
#             supplier = conn.execute(
#                 "SELECT id FROM suppliers WHERE LOWER(email) = ?",
#                 (from_addr,)
#             ).fetchone()

#             if not supplier:
#                 # Not from a known supplier; mark seen & skip
#                 # mail.store(num, '+FLAGS', '\\Seen')
#                 continue

#             supplier_id = supplier['id']

#             # ----- FIND MATCHING TASKS FOR THIS SUPPLIER BY SUBJECT -----
#             # Only match tasks where the subject contains the task_name
#             # Email subjects are typically "Re: Procurement Inquiry - {task_name}" or similar
            
#             # First, get all task_names for this supplier
#             all_supplier_tasks = conn.execute(
#                 """
#                 SELECT ts.task_id, t.task_name 
#                 FROM task_suppliers ts
#                 JOIN tasks t ON ts.task_id = t.id
#                 WHERE ts.supplier_id = ?
#                 """,
#                 (supplier_id,)
#             ).fetchall()
            
#             if not all_supplier_tasks:
#                 # No tasks for this supplier; leave unread
#                 print(f"[IMAP] No tasks found for supplier {supplier_id}, leaving email unread")
#                 continue
            
#             # Check if subject matches any task_name
#             matched_tasks = []
#             for task_row in all_supplier_tasks:
#                 task_name = task_row['task_name']
#                 # Check if task_name appears in subject (case-insensitive)
#                 if task_name.lower() in subject.lower():
#                     matched_tasks.append(task_row)
#                     print(f"[IMAP] Subject matched task: {task_name}")
            
#             if not matched_tasks:
#                 # Subject doesn't match any known task - leave email UNREAD
#                 print(f"[IMAP] Subject '{subject}' doesn't match any task for supplier {supplier_id}, leaving unread")
#                 continue
            
#             # Only process matched tasks (not all tasks for this supplier)
#             pending_rows = matched_tasks

#             # Parse Date header -> replied_at timestamp string
#             raw_date = msg.get("Date")
#             reply_dt_str = None
#             if raw_date:
#                 try:
#                     dt = parsedate_to_datetime(raw_date)
#                     dt = dt.replace(tzinfo=None)  # store naive local-ish time
#                     reply_dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
#                 except Exception as e:
#                     print(f"[IMAP] Failed to parse Date header {raw_date!r}: {e}")

#             if not reply_dt_str:
#                 # Fallback to current time
#                 now = datetime.now()
#                 reply_dt_str = now.strftime("%Y-%m-%d %H:%M:%S")

#             body_text = get_email_body(msg)
#             print(body_text)

#             # ✨ NEW: try to parse structured quote from body
#             parsed = parse_reply_fields(body_text)
#             print("[IMAP PARSE FIELDS]", parsed)

#             try:
#                 # For each pending task for this supplier, mark replied_at
#                 for row in pending_rows:
#                     task_id = row['task_id']

#                     # 1) Mark replied_at (update every time a reply is seen)
#                     conn.execute(
#                         '''
#                         UPDATE task_suppliers
#                         SET replied_at = ?
#                         WHERE task_id = ? AND supplier_id = ?
#                         ''',
#                         (reply_dt_str, task_id, supplier_id)
#                     )

#                     # 2) Log the reply (same as before)
#                     conn.execute(
#                         '''
#                         INSERT INTO email_logs (task_id, supplier_id, email_type, subject, body, status)
#                         VALUES (?, ?, ?, ?, ?, ?)
#                         ''',
#                         (task_id, supplier_id, 'reply', subject, body_text, 'received')
#                     )

#                     # 3) If we successfully parsed anything, auto-populate supplier_quotes
#                     if parsed and any(parsed.values()):
#                         # Check if there are already quotes; don't overwrite user's manual input
#                         existing = conn.execute(
#                             '''
#                             SELECT 1 FROM supplier_quotes
#                             WHERE task_id = ? AND supplier_id = ?
#                             LIMIT 1
#                             ''',
#                             (task_id, supplier_id)
#                         ).fetchone()

#                         if not existing:
#                             # Get all PR items for this task
#                             pr_items = conn.execute(
#                                 'SELECT id FROM pr_items WHERE task_id = ?',
#                                 (task_id,)
#                             ).fetchall()

#                             # Build a notes field from warranty + payment terms
#                             notes_parts = []
#                             if parsed.get("warranty"):
#                                 notes_parts.append(f"Warranty: {parsed['warranty']}")
#                             if parsed.get("payment_terms"):
#                                 notes_parts.append(f"Payment terms: {parsed['payment_terms']}")
#                             notes = "\n".join(notes_parts) if notes_parts else None

#                             for item in pr_items:
#                                 pr_item_id = item['id']
#                                 conn.execute(
#                                     '''
#                                     INSERT INTO supplier_quotes
#                                         (task_id, supplier_id, pr_item_id,
#                                          unit_price, stock_availability, lead_time, payment_terms, ono, notes)
#                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
#                                     ''',
#                                     (
#                                         task_id,
#                                         supplier_id,
#                                         pr_item_id,
#                                         parsed.get("unit_price"),
#                                         parsed.get("stock_availability"),
#                                         parsed.get("lead_time"),
#                                         parsed.get("payment_terms"),
#                                         0,
#                                         notes
#                                     )
#                                 )

#                             print(f"[IMAP] Auto-captured quotes for task_id={task_id}, supplier_id={supplier_id}")

#                     processed += 1
#                     print(f"[IMAP] Marked replied: task_id={task_id}, supplier_id={supplier_id}, at {reply_dt_str}")

#                 conn.commit()
#             except Exception as e:
#                 print(f"[IMAP] DB update failed for supplier {supplier_id}: {e}")
#                 conn.rollback()


#             # Mark this email as seen so we don't process it again
#             mail.store(num, '+FLAGS', '\\Seen')

#         conn.close()
#     finally:
#         try:
#             mail.logout()
#         except Exception:
#             pass

#     return processed

# Do not run inbox checks at import time. This was causing side-effects
# during the Flask debug reloader (multiple Python processes) and could
# result in older code/state appearing to run. Use the admin route
# `/admin/check-replies` or a scheduled job to trigger inbox checks.
# print(check_inbox_and_mark_replies())
    
# @app.route('/admin/check-replies')
# def admin_check_replies():
#     if 'user_id' not in session or session.get('role') != 'admin':
#         flash('Access denied', 'error')
#         return redirect(url_for('index'))

#     processed = check_inbox_and_mark_replies()
#     flash(f'Inbox checked. Auto-marked {processed} reply entries.', 'success')
#     return redirect(url_for('task_list'))
    

# ==================================== DEBUG ====================================
# Add this route to your app.py temporarily
@app.route('/debug-db')
def debug_db():
    if not ENABLE_DEBUG_ROUTES:
        abort(404)
    if 'user_id' not in session or session.get('role') != 'admin':
        abort(403)

    conn = get_db_connection()
    
    # Check all tables
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    
    result = "<h1>Database Debug Info</h1>"
    result += f"<p>Tables found: {[table[0] for table in tables]}</p>"
    
    # Check each table's structure and content
    for table in tables:
        table_name = table[0]
        result += f"<h2>Table: {table_name}</h2>"
        
        # Get table structure
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        result += f"<p>Columns: {[col[1] for col in columns]}</p>"
        
        # Get table content
        cursor.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()
        result += f"<p>Row count: {len(rows)}</p>"
        if rows:
            result += "<ul>"
            for row in rows:
                result += f"<li>{row}</li>"
            result += "</ul>"
    
    conn.close()
    return result

@app.route('/debug-info')
def debug_info():
    if not ENABLE_DEBUG_ROUTES:
        abort(404)
    if 'user_id' not in session or session.get('role') != 'admin':
        abort(403)

    import os
    import sqlite3
    
    current_dir = os.getcwd()
    db_path = os.path.join(current_dir, 'database', 'procure_flow.db')
    
    info = f"""
    <h1>Debug Information</h1>
    <p>Current directory: {current_dir}</p>
    <p>Database path: {db_path}</p>
    <p>Database exists: {os.path.exists(db_path)}</p>
    """
    
    if os.path.exists(db_path):
        info += f"<p>Database size: {os.path.getsize(db_path)} bytes</p>"
        
        # Check tables and row counts
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        info += "<h2>Tables and Row Counts:</h2>"
        for table in tables:
            table_name = table[0]
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            info += f"<p>{table_name}: {count} rows</p>"
        
        conn.close()
    
    return info

@app.route('/db-location')
def db_location():
    if not ENABLE_DEBUG_ROUTES:
        abort(404)
    if 'user_id' not in session or session.get('role') != 'admin':
        abort(403)

    import os
    import sqlite3
    
    current_dir = os.getcwd()
    db_path = os.path.abspath(os.path.join('database', 'procure_flow.db'))
    
    info = f"""
    <h1>Database Location</h1>
    <p><strong>Current working directory:</strong> {current_dir}</p>
    <p><strong>Database absolute path:</strong> {db_path}</p>
    <p><strong>Database exists:</strong> {os.path.exists(db_path)}</p>
    """
    
    if os.path.exists(db_path):
        # Show file properties
        import datetime
        stat = os.stat(db_path)
        modified_time = datetime.datetime.fromtimestamp(stat.st_mtime)
        
        info += f"""
        <p><strong>Database size:</strong> {stat.st_size} bytes</p>
        <p><strong>Last modified:</strong> {modified_time}</p>
        <p><strong>Full path to open in DB Browser:</strong></p>
        <code>{db_path}</code>
        """
    
    return info
# ==================================== END OF DEBUG ====================================

@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template("errors/403.html"), 403

@app.errorhandler(400)
def bad_request(e):
    return render_template("errors/400.html"), 400

@app.errorhandler(500)
def server_error(e):
    # Log the real error internally
    app.logger.exception("500 Server Error")
    return render_template("errors/500.html"), 500

@app.errorhandler(Exception)
def unhandled_exception(e):
    # Let HTTP errors pass through (404, 403, etc.)
    if isinstance(e, HTTPException):
        return e
    app.logger.exception("Unhandled exception")
    return render_template("errors/500.html"), 500

if __name__ == '__main__':
    debug_mode = os.getenv("FLASK_DEBUG", "0") == "1"
    host = os.getenv("FLASK_HOST", "127.0.0.1")   # safer default than 0.0.0.0
    port = int(os.getenv("PORT", "5000"))

    app.run(host=host, port=port, debug=debug_mode)
