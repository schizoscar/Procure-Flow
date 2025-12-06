# app.py
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_file
import sqlite3
import re
from datetime import datetime
import json
from werkzeug.security import generate_password_hash, check_password_hash
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import requests
import io
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('APP_SECRET_KEY', 'procure-flow-secret-key-2024')

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
    'sender_email': os.getenv('SMTP_SENDER', 'scarletsumirepoh@gmail.com'),
    'sender_password': os.getenv('SMTP_PASSWORD', 'ydaf mpur dpmk gsav')
}
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
SENDGRID_SENDER = os.getenv('SENDGRID_SENDER', EMAIL_CONFIG['sender_email'])

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
            <strong>Specification:</strong> {item['specification'] or 'N/A'}<br>
            <strong>Brand:</strong> {item['brand'] or 'N/A'}<br>
            <strong>Quantity:</strong> {item['quantity']}<br>
            <strong>Category:</strong> {item['item_category']}
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
            <li>Unit price and total price</li>
            <li>Delivery timeline</li>
            <li>Warranty information</li>
            <li>Payment terms</li>
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
                'specification': request.form[f'items[{item_index}][specification]'],
                'brand': request.form[f'items[{item_index}][brand]'],
                'balance_stock': request.form.get(f'items[{item_index}][balance_stock]', 0) or 0,
                'quantity': request.form[f'items[{item_index}][quantity]'],
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
        
        # Add PR items
        for item_data in items:
            conn.execute('''
                INSERT INTO pr_items (task_id, item_name, specification, brand, balance_stock, quantity, item_category)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                task_id_to_use,
                item_data['item_name'],
                item_data['specification'],
                item_data['brand'],
                item_data['balance_stock'],
                item_data['quantity'],
                item_data['item_category']
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
            
            if send_procurement_email(
                supplier['email'],
                supplier['name'],
                pr_items,
                task['task_name'],
                assigned_item_ids,
                final_email_content,
                final_email_subject
            ):
                success_count += 1
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
            else:
                conn.execute(
                    '''
                    INSERT INTO email_logs (task_id, supplier_id, email_type, subject, body, status, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (task_id, supplier['id'], 'initial', final_email_subject, final_email_content, 'failed', 'send_failed')
                )
        
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

            if send_procurement_email(
                supplier['email'],
                supplier['name'],
                pr_items,
                task['task_name'],
                assigned_item_ids,
                body,
                subject
            ):
                sent += 1
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
            else:
                conn.execute(
                    '''
                    INSERT INTO email_logs (task_id, supplier_id, email_type, subject, body, status, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (task_id, supplier['id'], 'followup', subject, body, 'failed', 'send_failed')
                )

        conn.commit()
        flash(f'Follow-up emails sent: {sent}/{len(pending_suppliers)}', 'success')
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

    conn.close()
    return render_template('responses.html', task=task, suppliers=suppliers)

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

    if request.method == 'POST':
        # Replace existing quotes for this supplier/task
        conn.execute('DELETE FROM supplier_quotes WHERE task_id = ? AND supplier_id = ?', (task_id, supplier_id))

        for item in pr_items:
            uid = str(item['id'])
            unit_price = request.form.get(f'unit_price_{uid}') or None
            total_price = request.form.get(f'total_price_{uid}') or None
            lead_time = request.form.get(f'lead_time_{uid}') or None
            notes = request.form.get(f'notes_{uid}') or None

            if any([unit_price, total_price, lead_time, notes]):
                conn.execute(
                    '''
                    INSERT INTO supplier_quotes (task_id, supplier_id, pr_item_id, unit_price, total_price, lead_time, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (task_id, supplier_id, item['id'], unit_price, total_price, lead_time, notes)
                )

        # Mark replied when quotes captured
        conn.execute(
            'UPDATE task_suppliers SET replied_at = COALESCE(replied_at, CURRENT_TIMESTAMP) WHERE task_id = ? AND supplier_id = ?',
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
                           quotes_map=quotes_map)

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
        SELECT q.*, s.name as supplier_name
        FROM supplier_quotes q
        JOIN suppliers s ON q.supplier_id = s.id
        WHERE q.task_id = ?
    ''', (task_id,)).fetchall()
    conn.close()

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Comparison"

    headers = [
        "Item Name", "Specification", "Brand", "Quantity", "Category",
        "Supplier", "Unit Price", "Total Price", "Lead Time", "Notes", "Best Price"
    ]
    ws.append(headers)

    # Determine best total per item
    best_totals = {}
    for q in quotes:
        if q['total_price'] is None:
            continue
        pid = q['pr_item_id']
        if pid not in best_totals or (q['total_price'] < best_totals[pid]):
            best_totals[pid] = q['total_price']

    for item in pr_items:
        item_quotes = [q for q in quotes if q['pr_item_id'] == item['id']]
        if not item_quotes:
            ws.append([
                item['item_name'], item['specification'], item['brand'],
                item['quantity'], item['item_category'],
                "", "", "", "", "", ""
            ])
            continue

        for q in item_quotes:
            is_best = ""
            if q['total_price'] is not None and item['id'] in best_totals and q['total_price'] == best_totals[item['id']]:
                is_best = "BEST"
            ws.append([
                item['item_name'],
                item['specification'],
                item['brand'],
                item['quantity'],
                item['item_category'],
                q['supplier_name'],
                q['unit_price'] if q['unit_price'] is not None else "",
                q['total_price'] if q['total_price'] is not None else "",
                q['lead_time'] or "",
                q['notes'] or "",
                is_best
            ])

    bold = Font(bold=True)
    for cell in ws[1]:
        cell.font = bold
    fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    for row in ws.iter_rows(min_row=2, min_col=11, max_col=11):
        for cell in row:
            if cell.value == "BEST":
                cell.fill = fill

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    from flask import send_file
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
def send_procurement_email(supplier_email, supplier_name, pr_items, task_name, assigned_item_ids=None, custom_content=None, subject=None):
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
        else:
            items_html = "<ul>"
            for item in supplier_items:
                items_html += f"""
                <li>
                    <strong>Item:</strong> {item['item_name']}<br>
                    <strong>Specification:</strong> {item['specification'] or 'N/A'}<br>
                    <strong>Brand:</strong> {item['brand'] or 'N/A'}<br>
                    <strong>Quantity:</strong> {item['quantity']}<br>
                    <strong>Category:</strong> {item['item_category']}
                </li>
                """
            items_html += "</ul>"
            
            body = f"""
            <html>
            <body>
                <h2>Procurement Inquiry</h2>
                <p>Dear {supplier_name},</p>
                
                <p>We are inquiring about the following items for procurement:</p>
                
                {items_html}
                
                <p>Please provide us with your quotation including:</p>
                <ul>
                    <li>Unit price and total price</li>
                    <li>Delivery timeline</li>
                    <li>Warranty information</li>
                    <li>Payment terms</li>
                </ul>
                
                <p>We look forward to your prompt response.</p>
                
                <p>Best regards,<br>
                Procurement Department</p>
            </body>
            </html>
            """

        # Prefer SendGrid if configured
        sendgrid_attempted = False
        if SENDGRID_API_KEY and SENDGRID_SENDER:
            sendgrid_attempted = True
            resp = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {SENDGRID_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "personalizations": [{
                        "to": [{"email": supplier_email, "name": supplier_name}],
                        "subject": subject
                    }],
                    "from": {"email": SENDGRID_SENDER, "name": "Procurement"},
                    "content": [{"type": "text/html", "value": body}]
                },
                timeout=10
            )
            if 200 <= resp.status_code < 300:
                return True
            else:
                print(f"SendGrid failed with status {resp.status_code}: {resp.text}; falling back to SMTP if configured")

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
    app.run(host='0.0.0.0', port=5000, debug=True)




