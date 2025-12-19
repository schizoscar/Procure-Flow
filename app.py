# app.py
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_file
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


load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('APP_SECRET_KEY', 'procure-flow-secret-key-2024')

# File upload configuration
UPLOADS_DIR = os.path.join('uploads', 'certificates')
ALLOWED_EXTENSIONS = {'pdf'}  # PDF only
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# Ensure uploads directory exists
os.makedirs(UPLOADS_DIR, exist_ok=True)

def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_uploaded_file(file, task_id, supplier_id, item_id):
    """Save uploaded file and return relative path for database storage."""
    if not file or file.filename == '':
        return None
    
    if not allowed_file(file.filename):
        return None
    
    # Check file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    if file_size > MAX_FILE_SIZE:
        return None
    
    # Generate unique filename
    ext = secure_filename(file.filename).rsplit('.', 1)[1].lower()
    unique_filename = f"task_{task_id}_supplier_{supplier_id}_item_{item_id}_{uuid.uuid4().hex}.{ext}"
    
    # Create subdirectory for this task if needed
    task_dir = os.path.join(UPLOADS_DIR, str(task_id))
    os.makedirs(task_dir, exist_ok=True)
    
    # Save file
    file_path = os.path.join(task_dir, unique_filename)
    file.save(file_path)
    
    # Return relative path for database storage
    return f"/uploads/certificates/{task_id}/{unique_filename}"

def get_quote_serializer():
    return URLSafeSerializer(app.secret_key, salt="supplier-quote")

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
        print(f"Database initialized. Tables: {tables}")
    except Exception as e:
        print(f"Database initialization failed: {e}")
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
SENDGRID_API_KEY = None
SENDGRID_SENDER = None

# IMAP configuration (for inbox polling)
IMAP_SERVER = os.getenv('IMAP_SERVER', 'imap.gmail.com')
IMAP_PORT = int(os.getenv('IMAP_PORT', '993'))
IMAP_USERNAME = os.getenv('IMAP_USERNAME', EMAIL_CONFIG['sender_email'])
IMAP_PASSWORD = os.getenv('IMAP_PASSWORD', EMAIL_CONFIG['sender_password'])

# Poll interval in seconds. Set `IMAP_POLL_INTERVAL` env var to change.
# Setting to 0 disables automatic polling.
IMAP_POLL_INTERVAL = int(os.getenv('IMAP_POLL_INTERVAL', '60'))

print("=== DEBUG FROM APP STARTUP ===")
print("SMTP_SENDER env:", os.getenv('SMTP_SENDER'))
print("EMAIL_CONFIG sender_email:", EMAIL_CONFIG['sender_email'])
print("APP_SECRET_KEY env:", os.getenv('APP_SECRET_KEY'))

print("EMAIL_CONFIG sender_email:", IMAP_USERNAME)
print("EMAIL_CONFIG sender_email:", IMAP_PASSWORD)
print("EMAIL_CONFIG sender_email:", IMAP_SERVER)
print("=== END DEBUG ===")

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
    items_html = "<ul>"
    for item in pr_items:
        items_html += f"""
        <li>
            <strong>Item:</strong> {item['item_name']}<br>
            <strong>Dimensions:</strong> {item['specification'] or 'N/A'}<br>
            <strong>Brand / Specification:</strong> {item['brand'] or 'N/A'}<br>
            <strong>Quantity:</strong> {item['quantity']}<br>
        </li>
        """
    items_html += "</ul>"
    
    return f"""
    <html>
    <body>
        <h2>Procurement Inquiry</h2>
        <p>Dear {{supplier_name}},</p>
        
        <p>We are inquiring about the following items for procurement:</p>
        
        {items_html}
        
        <p>Please provide us with your quotation including:</p>
        <ul>
            <li>Payment Terms</li>
            <li>Unit Price (RM)</li>
            <li>Delivery Lead Timeline</li>
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
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']
        
        # Validation
        if not validate_email(email):
            flash('Invalid email format', 'error')
            return render_template('create_user.html')
        
        if not validate_password(password):
            flash('Password must contain at least 5 letters and 1 number', 'error')
            return render_template('create_user.html')
        
        password_hash = generate_password_hash(password)
        
        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)',
                (username, password_hash, email, role)
            )
            conn.commit()
            flash('User created successfully', 'success')
            return redirect(url_for('index'))
        except sqlite3.IntegrityError:
            flash('Username already exists', 'error')
        finally:
            conn.close()
    
    return render_template('create_user.html')

@app.route('/new-task', methods=['GET', 'POST'])
@app.route('/edit-task/<int:task_id>', methods=['GET', 'POST'])
def new_task(task_id=None):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    categories = conn.execute('SELECT * FROM categories').fetchall()
    
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
        task_name = request.form['task_name']
        items = []
        
        # Process items from form
        item_index = 0
        while f'items[{item_index}][item_name]' in request.form:
            items.append({
                'item_name': request.form[f'items[{item_index}][item_name]'],
                'specification': request.form.get(f'items[{item_index}][specification]') or None,
                'width': request.form.get(f'items[{item_index}][width]') or None,
                'length': request.form.get(f'items[{item_index}][length]') or None,
                'thickness': request.form.get(f'items[{item_index}][thickness]') or None,
                'payment_terms': request.form.get(f'items[{item_index}][payment_terms]') or None,
                'brand': request.form.get(f'items[{item_index}][brand]') or None,
                'quantity': request.form.get(f'items[{item_index}][quantity]') or None,
                'item_category': request.form[f'items[{item_index}][item_category]']
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
            flash('Task created successfully!', 'success')
        
        # Add PR items (store width/length/thickness if provided)
        for item_data in items:
            conn.execute('''
                INSERT INTO pr_items (task_id, item_name, item_category, brand, quantity, specification, width, length, thickness, payment_terms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task_id_to_use,
                item_data['item_name'],
                item_data['item_category'],
                item_data['brand'],
                item_data['quantity'],
                item_data['specification'],
                item_data.get('width'),
                item_data.get('length'),
                item_data.get('thickness'),
                item_data.get('payment_terms')
            ))
        
        conn.commit()
        conn.close()
        
        # ALWAYS go to next step after saving
        return redirect(url_for('supplier_selection', task_id=task_id_to_use))
    
    conn.close()
    return render_template('pr_form.html', 
                         categories=categories, 
                         task=task, 
                         existing_items=existing_items,
                         is_edit=bool(task_id))

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
    
    # Initialize email_subject here, outside the POST block
    email_subject = session.get('email_subject', f"Procurement Inquiry - {task['task_name']}")
    
    if request.method == 'POST':
        action = request.form.get('action')
        email_content = request.form.get('email_content', '')
        email_subject = request.form.get('email_subject', email_subject)  # Use form value or existing
        
        if action == 'update_preview':
            # Just update the preview with new content
            session['email_content'] = email_content
            session['email_subject'] = email_subject
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
            email_content = session.get('email_content')
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
                supplier.get('contact_name') if isinstance(supplier, dict) else supplier['contact_name']
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
            SELECT t.*, u.username 
            FROM tasks t 
            LEFT JOIN users u ON t.user_id = u.id 
            ORDER BY t.created_at DESC
        ''').fetchall()
        
        my_tasks = conn.execute('''
            SELECT * FROM tasks 
            WHERE user_id = ? 
            ORDER BY created_at DESC
        ''', (session['user_id'],)).fetchall()
        
        conn.close()
        return render_template('task_list.html', all_tasks=all_tasks, my_tasks=my_tasks)
    else:
        # Regular users see only their tasks
        my_tasks = conn.execute('''
            SELECT * FROM tasks 
            WHERE user_id = ? 
            ORDER BY created_at DESC
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
                supplier.get('contact_name') if isinstance(supplier, dict) else supplier['contact_name']
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
        SELECT s.*, ts.assigned_items, ts.initial_sent_at, ts.followup_sent_at, ts.replied_at
        FROM suppliers s
        JOIN task_suppliers ts ON s.id = ts.supplier_id
        WHERE ts.task_id = ? AND ts.is_selected = 1
    ''', (task_id,)).fetchall()

    form_links = {}
    for s in suppliers:
        token = get_quote_serializer().dumps({'task_id': task_id, 'supplier_id': s['id']})
        form_links[s['id']] = url_for('supplier_quote_form', token=token, _external=True)

    conn.close()
    return render_template('responses.html', task=task, suppliers=suppliers, form_links=form_links)

@app.route('/task/<int:task_id>/quotes/<int:supplier_id>', methods=['GET', 'POST'])
def capture_quotes(task_id, supplier_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    supplier = conn.execute('SELECT * FROM suppliers WHERE id = ?', (supplier_id,)).fetchone()
    if not task or not supplier or (session['role'] != 'admin' and task['user_id'] != session['user_id']):
        flash('Task or supplier not found, or access denied', 'error')
        conn.close()
        return redirect(url_for('task_list'))

    pr_items = conn.execute('SELECT * FROM pr_items WHERE task_id = ?', (task_id,)).fetchall()

    existing_quotes = conn.execute(
        'SELECT * FROM supplier_quotes WHERE task_id = ? AND supplier_id = ?',
        (task_id, supplier_id)
    ).fetchall()
    quotes_map = {(q['pr_item_id']): q for q in existing_quotes}
    # Determine existing payment terms (use first quote's payment_terms if present)
    payment_terms_default = ''
    if existing_quotes:
        try:
            payment_terms_default = existing_quotes[0]['payment_terms'] or ''
        except Exception:
            payment_terms_default = ''

    if request.method == 'POST':
        # Replace existing quotes for this supplier/task
        app.logger.info('capture_quotes POST received for task %s supplier %s', task_id, supplier_id)
        # Log raw form keys/values (useful to debug duplicate-value issues)
        try:
            app.logger.debug('Form data keys: %s', list(request.form.keys()))
            # For readability, convert to a normal dict (note: duplicates will be collapsed)
            app.logger.debug('Form data snapshot: %s', {k: request.form.get(k) for k in request.form.keys()})
        except Exception:
            pass

        conn.execute('DELETE FROM supplier_quotes WHERE task_id = ? AND supplier_id = ?', (task_id, supplier_id))
        # Single payment terms value for the whole submission
        payment_terms_global = request.form.get('payment_terms') or None

        for item in pr_items:
            uid = str(item['id'])
            unit_price = request.form.get(f'unit_price_{uid}') or None
            lead_time = request.form.get(f'lead_time_{uid}') or None
            notes = request.form.get(f'notes_{uid}') or None
            ono = 1 if request.form.get(f"ono_{uid}") else 0
            
            # Handle certificate file upload
            cert_path = None
            if f'cert_{uid}' in request.files:
                cert_file = request.files[f'cert_{uid}']
                if cert_file and cert_file.filename != '':
                    cert_path = save_uploaded_file(cert_file, task_id, supplier_id, item['id'])

            # Log each parsed item value before insert (payment_terms is global)
            app.logger.info('Captured quote values for item %s: unit_price=%s lead_time=%s payment_terms=%s ono=%s notes=%s cert=%s',
                            uid, unit_price, lead_time, payment_terms_global, ono, notes, cert_path)

            # Insert only when meaningful per-item data is present; apply global payment terms
            if any([unit_price, lead_time, notes, ono, cert_path]):
                conn.execute(
                    '''
                    INSERT INTO supplier_quotes (task_id, supplier_id, pr_item_id, unit_price, stock_availability, cert, lead_time, payment_terms, ono, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (task_id, supplier_id, item['id'], unit_price, None, cert_path, lead_time, payment_terms_global, ono, notes)
                )

        # Mark replied when quotes captured (always update to current time)
        conn.execute(
            'UPDATE task_suppliers SET replied_at = CURRENT_TIMESTAMP WHERE task_id = ? AND supplier_id = ?',
            (task_id, supplier_id)
        )
        conn.commit()
        conn.close()
        flash('Quotes saved.', 'success')
        return redirect(url_for('task_responses', task_id=task_id))

    conn.close()
    return render_template('quotes_form.html',
                           task=task,
                           supplier=supplier,
                           pr_items=pr_items,
                           quotes_map=quotes_map,
                           payment_terms_default=payment_terms_default)

@app.route('/supplier/quote-form/<token>', methods=['GET', 'POST'])
def supplier_quote_form(token):
    try:
        data = get_quote_serializer().loads(token)
        task_id = data.get('task_id')
        supplier_id = data.get('supplier_id')
    except BadSignature:
        return "Invalid or expired link", 400

    conn = get_db_connection()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    supplier = conn.execute('SELECT * FROM suppliers WHERE id = ?', (supplier_id,)).fetchone()
    if not task or not supplier:
        conn.close()
        return "Task or supplier not found", 404

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

    pr_items = conn.execute('SELECT * FROM pr_items WHERE task_id = ?', (task_id,)).fetchall()
    if assigned_ids:
        pr_items = [item for item in pr_items if item['id'] in assigned_ids]

    if request.method == 'POST':
        conn.execute('DELETE FROM supplier_quotes WHERE task_id = ? AND supplier_id = ?', (task_id, supplier_id))
        # Single payment terms value for the whole submission
        payment_terms_global = request.form.get('payment_terms') or None

        for item in pr_items:
            uid = str(item['id'])
            unit_price = request.form.get(f'unit_price_{uid}') or None
            stock_availability = request.form.get(f'stock_availability_{uid}') or None
            lead_time = request.form.get(f'lead_time_{uid}') or None
            notes = request.form.get(f'notes_{uid}') or None
            ono = 1 if request.form.get(f"ono_{uid}") else 0
            
            # Handle certificate file upload
            cert_path = None
            if f'cert_{uid}' in request.files:
                cert_file = request.files[f'cert_{uid}']
                if cert_file and cert_file.filename != '':
                    cert_path = save_uploaded_file(cert_file, task_id, supplier_id, item['id'])

            if any([unit_price, stock_availability, lead_time, notes, ono, cert_path]):
                conn.execute(
                    '''
                    INSERT INTO supplier_quotes (task_id, supplier_id, pr_item_id, unit_price, stock_availability, cert, lead_time, payment_terms, ono, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (task_id, supplier_id, item['id'], unit_price, stock_availability, cert_path, lead_time, payment_terms_global, ono, notes)
                )

        # mark replied and log
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
        conn.close()
        return render_template('supplier_form_success.html', supplier=supplier, task=task)

    conn.close()
    return render_template('supplier_public_quote.html',
                           task=task,
                           supplier=supplier,
                           pr_items=pr_items)


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

    conn = get_db_connection()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task or (session['role'] != 'admin' and task['user_id'] != session['user_id']):
        flash('Task not found or access denied', 'error')
        conn.close()
        return redirect(url_for('task_list'))

    pr_items = conn.execute('SELECT * FROM pr_items WHERE task_id = ?', (task_id,)).fetchall()
    quotes = conn.execute('''
        SELECT q.*, s.name as supplier_name, ts.replied_at as replied_at
        FROM supplier_quotes q
        JOIN suppliers s ON q.supplier_id = s.id
        LEFT JOIN task_suppliers ts ON ts.supplier_id = q.supplier_id AND ts.task_id = q.task_id
        WHERE q.task_id = ?
    ''', (task_id,)).fetchall()
    conn.close()

    # def parse_dimensions(spec_str):
    #     """Parse spec like '5x8.20mm' into (width, length, thickness)."""
    #     if not spec_str:
    #         return None, None, None
    #     spec_str = str(spec_str).lower().replace('mm', '').strip()
    #     parts = spec_str.split('x')
    #     w = parts[0].strip() if len(parts) > 0 else None

    #     l = None
    #     thk = None
    #     if len(parts) > 1:
    #         rhs = parts[1].strip().replace(' ', '')
    #         if '.' in rhs:
    #             l_thk = rhs.split('.')
    #         elif ',' in rhs:
    #             l_thk = rhs.split(',')
    #         else:
    #             l_thk = [rhs]
    #         l = l_thk[0].strip() if len(l_thk) > 0 else None
    #         thk = l_thk[1].strip() if len(l_thk) > 1 else None

    #     return w, l, thk

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

    SUPPLIER_BLOCK_COLS = 8
    OFF_RATE  = 0
    OFF_PRICE = 1
    OFF_TOTAL = 2
    OFF_LEAD  = 3
    OFF_STOCK = 4
    OFF_COA   = 5
    OFF_ONO   = 6
    OFF_REMARKS = 7

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

    row1 = ["Item Name", "Brand / Specification", "Category", "Dimensions", "", "", "Quantity", "Weight (in Kg)"]
    for supplier_id, supplier_name in suppliers_list:
        row1.extend([supplier_header_label(supplier_id, supplier_name)] + [""] * (SUPPLIER_BLOCK_COLS - 1))
    ws.append(row1)

    row2 = ["", "", "", "W (mm)", "L (mm)", "Thk (mm)", "", ""]
    for supplier_id, supplier_name in suppliers_list:
        row2.extend([
            "Rate (RM/Kg)",
            "Quoted Price (RM)",
            "Total Amount Quoted (RM)",
            "Delivery Lead Time",
            "Stock Availability",
            "COA",
            "O.N.O.",
            "Remarks"
        ])
    ws.append(row2)

    bold = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center")

    # Merge and center Item Name, Brand, Category (cols 1-3)
    for col in range(1, 4):
        ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)
        cell = ws.cell(row=1, column=col)
        cell.font = bold
        cell.alignment = center

    # Merge and center Dimensions (cols 4-6 row 1)
    ws.merge_cells(start_row=1, start_column=4, end_row=1, end_column=6)
    cell = ws.cell(row=1, column=4)
    cell.font = bold
    cell.alignment = center

    # Center W, L, Thk row2
    for col in range(4, 7):
        cell = ws.cell(row=2, column=col)
        cell.font = bold
        cell.alignment = center

    # Merge and center Quantity and Weight (cols 7-8)
    for col in range(7, 9):
        ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)
        cell = ws.cell(row=1, column=col)
        cell.font = bold
        cell.alignment = center

    # Merge and center each supplier header (8 columns each)
    col_idx = 9
    for supplier_id, supplier_name in suppliers_list:
        ws.merge_cells(start_row=1, start_column=col_idx, end_row=1, end_column=col_idx + (SUPPLIER_BLOCK_COLS - 1))
        cell = ws.cell(row=1, column=col_idx)
        cell.font = bold
        cell.alignment = center
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
        w = item['width'] or None
        l = item['length'] or None
        thk = item['thickness'] or None
        # if not (w and l and thk):
        #     parsed_w, parsed_l, parsed_thk = parse_dimensions(item['specification'])
        #     w = w or parsed_w
        #     l = l or parsed_l
        #     thk = thk or parsed_thk

        weight = ""
        if w and l and thk:
            try:
                w_val = float(w)
                l_val = float(l)
                thk_val = float(thk)
                weight = round((w_val * l_val * thk_val) * (12 * 25.4 * 12 * 25.4) / 1000 * 7.85 / 1000, 2)
            except (ValueError, TypeError):
                weight = ""

        row = [
            item['item_name'],
            item['brand'] or "",
            item['item_category'] or "",
            w or "",
            l or "",
            thk or "",
            item['quantity'] or "",
            weight
        ]

        metric_candidates = {
            "rate": [],
            "price": [],
            "total": [],
            "lead": []
        }

        col_idx = 9
        for supplier_id, supplier_name in suppliers_list:
            q = quotes_by_item.get(item['id'], {}).get(supplier_id)
            if q:
                ono_val = q.get('ono')
                ono_display = "✓" if ono_val else "✗"

                cert_display = ""
                cert_url = None
                if q.get('cert'):
                    cert_display = "PDF"
                    cert_url = q['cert']

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
                    supplier_total_amounts[supplier_id] += float(total_amount_val)

                row.extend([
                    rate_val,
                    unit_price,
                    total_amount_val,
                    q.get('lead_time') or "",
                    q.get('stock_availability') or "",
                    cert_display,
                    ono_display,
                    q.get('notes') or ""
                ])

                if cert_url:
                    cert_links[(current_row, col_idx + OFF_COA)] = cert_url

                # highlight candidates
                metric_candidates["rate"].append((col_idx + OFF_RATE, to_float(rate_val)))
                metric_candidates["price"].append((col_idx + OFF_PRICE, unit_price_val))
                metric_candidates["total"].append((col_idx + OFF_TOTAL, to_float(total_amount_val)))
                metric_candidates["lead"].append((col_idx + OFF_LEAD, lead_time_to_days(q.get('lead_time'))))

                col_idx += SUPPLIER_BLOCK_COLS
            else:
                row.extend([""] * SUPPLIER_BLOCK_COLS)
                col_idx += SUPPLIER_BLOCK_COLS

        ws.append(row)

        # Apply per-row best highlighting (lowest wins)
        for key in ["rate", "price", "total", "lead"]:
            vals = [(col, v) for (col, v) in metric_candidates[key] if v is not None]
            if not vals:
                continue
            best_val = min(v for _, v in vals)
            for col, v in vals:
                if v == best_val:
                    ws.cell(row=current_row, column=col).fill = best_fill

        current_row += 1

    totals_row = current_row
    ws.merge_cells(start_row=totals_row, start_column=1, end_row=totals_row, end_column=8)
    label_cell = ws.cell(row=totals_row, column=1)
    label_cell.value = "TOTAL"
    label_cell.font = Font(bold=True)
    label_cell.alignment = Alignment(horizontal="right", vertical="center")
    label_cell.fill = total_fill

    total_cells = []  # (col, value)
    for i, (sid, _sname) in enumerate(suppliers_list):
        total_col = 9 + i * SUPPLIER_BLOCK_COLS + OFF_TOTAL
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
        cell.style = "Hyperlink"

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
        
        print(f"Adding supplier: {name}, {email}")
        print(f"Categories selected: {selected_categories}")
        
        # Validate email
        if not validate_email(email):
            flash('Invalid email format', 'error')
            return render_template('edit_supplier.html', categories=conn.execute('SELECT * FROM categories').fetchall())
        
        # Validate phone
        if contact_number and not validate_phone(contact_number):
            flash('Invalid phone number format', 'error')
            return render_template('edit_supplier.html', categories=conn.execute('SELECT * FROM categories').fetchall())
        
        # Add supplier
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO suppliers (name, contact_name, email, contact_number, address, products_services)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, contact_name, email, contact_number, address, products_services))
        
        supplier_id = cursor.lastrowid
        print(f"Supplier added with ID: {supplier_id}")
        
        # Add categories
        for category_id in selected_categories:
            conn.execute(
                'INSERT INTO supplier_categories (supplier_id, category_id) VALUES (?, ?)',
                (supplier_id, category_id)
            )
            print(f"Added category {category_id} to supplier {supplier_id}")
        
        conn.commit()
        print("Changes committed to database")
        
        # Verify the supplier was added
        verify_supplier = conn.execute('SELECT * FROM suppliers WHERE id = ?', (supplier_id,)).fetchone()
        if verify_supplier:
            print(f"Verification: Supplier found in database - {verify_supplier['name']}")
        else:
            print("Verification: Supplier NOT found in database!")
        
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
                items_html += f"""
                <li>
                    <strong>Item:</strong> {item['item_name']}<br>
                    <strong>Dimensions:</strong> {item['specification'] or 'N/A'}<br>
                    <strong>Brand / Specification:</strong> {item['brand'] or 'N/A'}<br>
                    <strong>Quantity:</strong> {item['quantity']}<br>
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

                <p>Supplier form: {quote_form_link}</p>
                
                <p>We look forward to your prompt response.</p>
                
                <p>Best regards,<br>
                Procurement Department</p>
            </body>
            </html>
            """

        # Prefer SendGrid if configured
        # sendgrid_attempted = False
        # if SENDGRID_API_KEY and SENDGRID_SENDER:
        #     sendgrid_attempted = True
        #     resp = requests.post(
        #         "https://api.sendgrid.com/v3/mail/send",
        #         headers={
        #             "Authorization": f"Bearer {SENDGRID_API_KEY}",
        #             "Content-Type": "application/json"
        #         },
        #         json={
        #             "personalizations": [{
        #                 "to": [{"email": supplier_email, "name": supplier_name}],
        #                 "subject": subject
        #             }],
        #             "from": {"email": SENDGRID_SENDER, "name": "Procurement"},
        #             "content": [{"type": "text/html", "value": body}]
        #         },
        #         timeout=10
        #     )
        #     if 200 <= resp.status_code < 300:
        #         return True
        #     else:
        #         print(f"SendGrid failed with status {resp.status_code}: {resp.text}; falling back to SMTP if configured")

        # SMTP fallback
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG['sender_email']
        msg['To'] = supplier_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'])
        server.starttls()
        server.login(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['sender_password'])
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        print(f"Email sending failed: {e}")
        return False

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Get stats for admin
    stats = None
    if session['role'] == 'admin':
        stats = conn.execute('''
            SELECT 
                (SELECT COUNT(*) FROM tasks) as total_tasks,
                (SELECT COUNT(*) FROM tasks WHERE status != 'confirm_email') as active_tasks,
                (SELECT COUNT(*) FROM suppliers WHERE is_active = 1) as total_suppliers
        ''').fetchone()
    
    # Get recent tasks
    if session['role'] == 'admin':
        recent_tasks = conn.execute('''
            SELECT t.*, u.username 
            FROM tasks t 
            LEFT JOIN users u ON t.user_id = u.id 
            ORDER BY t.created_at DESC 
            LIMIT 5
        ''').fetchall()
    else:
        recent_tasks = conn.execute('''
            SELECT * FROM tasks 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT 5
        ''', (session['user_id'],)).fetchall()
    
    conn.close()
    
    return render_template('dashboard.html', stats=stats, recent_tasks=recent_tasks)

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
        for supplier_id in selected_suppliers:
            assigned_items = item_assignments.get(supplier_id, [])
            items_json = json.dumps(assigned_items) if assigned_items else None
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

def check_inbox_and_mark_replies():
    """
    Connect to the inbox via IMAP, find unread emails,
    match them by sender email to suppliers, and mark
    task_suppliers.replied_at for any pending tasks.
    Returns number of suppliers/tasks updated.
    """
    processed = 0

    print("=== IMAP CHECK START ===")
    print("IMAP_SERVER:", IMAP_SERVER)
    print("IMAP_USERNAME:", IMAP_USERNAME)


    # 1. Connect to IMAP
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(IMAP_USERNAME, IMAP_PASSWORD)
    except Exception as e:
        print(f"[IMAP] Login failed: {e}")
        return 0

    try:
        mail.select("INBOX")
        status, messages = mail.search(None, '(UNSEEN)')
        if status != "OK":
            print("[IMAP] Search failed")
            mail.logout()
            return 0

        conn = get_db_connection()

        for num in messages[0].split():
            status, data = mail.fetch(num, "(RFC822)")
            if status != "OK":
                continue

            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)

            # Decode subject (not essential for matching, but useful for logs)
            raw_subject = msg.get("Subject", "")
            decoded = decode_header(raw_subject)
            subject_parts = []
            for part, enc in decoded:
                if isinstance(part, bytes):
                    subject_parts.append(part.decode(enc or "utf-8", errors="ignore"))
                else:
                    subject_parts.append(part)
            subject = "".join(subject_parts)

            from_addr = email.utils.parseaddr(msg.get("From"))[1].strip().lower()
            print(f"[IMAP] New email from {from_addr} subject={subject!r}")

            # ----- FIND SUPPLIER BY EMAIL -----
            supplier = conn.execute(
                "SELECT id FROM suppliers WHERE LOWER(email) = ?",
                (from_addr,)
            ).fetchone()

            if not supplier:
                # Not from a known supplier; mark seen & skip
                # mail.store(num, '+FLAGS', '\\Seen')
                continue

            supplier_id = supplier['id']

            # ----- FIND ALL PENDING TASKS FOR THIS SUPPLIER -----
            # Find all tasks for this supplier. We will update replied_at on every reply
            # so do not filter by replied_at NULL here (Option A)
            pending_rows = conn.execute(
                """
                SELECT task_id FROM task_suppliers
                WHERE supplier_id = ?
                """,
                (supplier_id,)
            ).fetchall()

            if not pending_rows:
                # Nothing to update; leave unread
                continue

            # Parse Date header -> replied_at timestamp string
            raw_date = msg.get("Date")
            reply_dt_str = None
            if raw_date:
                try:
                    dt = parsedate_to_datetime(raw_date)
                    dt = dt.replace(tzinfo=None)  # store naive local-ish time
                    reply_dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception as e:
                    print(f"[IMAP] Failed to parse Date header {raw_date!r}: {e}")

            if not reply_dt_str:
                # Fallback to current time
                now = datetime.now()
                reply_dt_str = now.strftime("%Y-%m-%d %H:%M:%S")

            body_text = get_email_body(msg)
            print(body_text)

            # ✨ NEW: try to parse structured quote from body
            parsed = parse_reply_fields(body_text)
            print("[IMAP PARSE FIELDS]", parsed)

            try:
                # For each pending task for this supplier, mark replied_at
                for row in pending_rows:
                    task_id = row['task_id']

                    # 1) Mark replied_at (update every time a reply is seen)
                    conn.execute(
                        '''
                        UPDATE task_suppliers
                        SET replied_at = ?
                        WHERE task_id = ? AND supplier_id = ?
                        ''',
                        (reply_dt_str, task_id, supplier_id)
                    )

                    # 2) Log the reply (same as before)
                    conn.execute(
                        '''
                        INSERT INTO email_logs (task_id, supplier_id, email_type, subject, body, status)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ''',
                        (task_id, supplier_id, 'reply', subject, body_text, 'received')
                    )

                    # 3) If we successfully parsed anything, auto-populate supplier_quotes
                    if parsed and any(parsed.values()):
                        # Check if there are already quotes; don't overwrite user's manual input
                        existing = conn.execute(
                            '''
                            SELECT 1 FROM supplier_quotes
                            WHERE task_id = ? AND supplier_id = ?
                            LIMIT 1
                            ''',
                            (task_id, supplier_id)
                        ).fetchone()

                        if not existing:
                            # Get all PR items for this task
                            pr_items = conn.execute(
                                'SELECT id FROM pr_items WHERE task_id = ?',
                                (task_id,)
                            ).fetchall()

                            # Build a notes field from warranty + payment terms
                            notes_parts = []
                            if parsed.get("warranty"):
                                notes_parts.append(f"Warranty: {parsed['warranty']}")
                            if parsed.get("payment_terms"):
                                notes_parts.append(f"Payment terms: {parsed['payment_terms']}")
                            notes = "\n".join(notes_parts) if notes_parts else None

                            for item in pr_items:
                                pr_item_id = item['id']
                                conn.execute(
                                    '''
                                    INSERT INTO supplier_quotes
                                        (task_id, supplier_id, pr_item_id,
                                         unit_price, stock_availability, lead_time, payment_terms, ono, notes)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    ''',
                                    (
                                        task_id,
                                        supplier_id,
                                        pr_item_id,
                                        parsed.get("unit_price"),
                                        parsed.get("stock_availability"),
                                        parsed.get("lead_time"),
                                        parsed.get("payment_terms"),
                                        0,
                                        notes
                                    )
                                )

                            print(f"[IMAP] Auto-captured quotes for task_id={task_id}, supplier_id={supplier_id}")

                    processed += 1
                    print(f"[IMAP] Marked replied: task_id={task_id}, supplier_id={supplier_id}, at {reply_dt_str}")

                conn.commit()
            except Exception as e:
                print(f"[IMAP] DB update failed for supplier {supplier_id}: {e}")
                conn.rollback()


            # Mark this email as seen so we don't process it again
            mail.store(num, '+FLAGS', '\\Seen')

        conn.close()
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    return processed

# background polling helpers
def _inbox_polling_loop(interval):
    if interval <= 0:
        print(f"[IMAP Poll] Disabled (interval={interval})")
        return
    print(f"[IMAP Poll] Loop starting with interval={interval} seconds")
    while True:
        try:
            processed = check_inbox_and_mark_replies()
            if processed:
                print(f"[IMAP Poll] Processed {processed} replies")
        except Exception as e:
            print(f"[IMAP Poll] Error while polling: {e}")
        time.sleep(interval)

def start_inbox_polling(interval):
    t = threading.Thread(target=_inbox_polling_loop, args=(interval,), daemon=True, name="IMAPPoller")
    t.start()
    print(f"[IMAP Poll] Started background thread (daemon) polling every {interval} seconds")

# Do not run inbox checks at import time. This was causing side-effects
# during the Flask debug reloader (multiple Python processes) and could
# result in older code/state appearing to run. Use the admin route
# `/admin/check-replies` or a scheduled job to trigger inbox checks.
# print(check_inbox_and_mark_replies())
    
@app.route('/admin/check-replies')
def admin_check_replies():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('index'))

    processed = check_inbox_and_mark_replies()
    flash(f'Inbox checked. Auto-marked {processed} reply entries.', 'success')
    return redirect(url_for('task_list'))
    

# ==================================== DEBUG ====================================
# Add this route to your app.py temporarily
@app.route('/debug-db')
def debug_db():
    if 'user_id' not in session or session.get('role') != 'admin':
        return "Access denied", 403

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
    if 'user_id' not in session or session.get('role') != 'admin':
        return "Access denied", 403

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
    if 'user_id' not in session or session.get('role') != 'admin':
        return "Access denied", 403

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

if __name__ == '__main__':
    print("Starting Procure Flow...")
    print("Access the application at: http://localhost:5000")
    print("Default admin login: username='admin', password='admin123'")
    # Start the inbox poller only in the actual Flask child process when
    # the reloader is active. WERKZEUG_RUN_MAIN is set to 'true' in the
    # reloader's child process. This prevents duplicate polling threads.
    try:
        if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
            # Start polling in background if configured (interval > 0)
            if IMAP_POLL_INTERVAL > 0:
                start_inbox_polling(IMAP_POLL_INTERVAL)
    except Exception as e:
        print(f"[IMAP Poll] Failed to start poller: {e}")

    app.run(host='0.0.0.0', port=5000, debug=True)
