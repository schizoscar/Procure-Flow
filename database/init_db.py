# database/init_db.py
import sqlite3
from werkzeug.security import generate_password_hash
import os

def init_database():
    print("Initializing database...")
    
    # Ensure the database directory exists
    os.makedirs('database', exist_ok=True)
    
    # Use the correct database path in the database folder
    db_path = os.path.join('database', 'procure_flow.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Categories table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Suppliers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact_name TEXT,
            email TEXT NOT NULL,
            contact_number TEXT,
            address TEXT,
            products_services TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Supplier Categories junction table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS supplier_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER,
            category_id INTEGER,
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
            FOREIGN KEY (category_id) REFERENCES categories (id)
        )
    ''')
    
    # Tasks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name TEXT NOT NULL,
            user_id INTEGER,
            status TEXT DEFAULT 'purchase_requisition',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Purchase Requisition Items table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pr_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            item_name TEXT NOT NULL,
            specification TEXT,
            width INTEGER,
            length INTEGER,
            thickness INTEGER,
            brand TEXT,
            balance_stock INTEGER,
            quantity INTEGER NOT NULL,
            item_category TEXT NOT NULL,
            payment_terms TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks (id)
        )
    ''')
    
    # Task Suppliers junction table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS task_suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            supplier_id INTEGER,
            is_selected BOOLEAN DEFAULT TRUE,
            assigned_items TEXT,
            initial_sent_at TIMESTAMP,
            followup_sent_at TIMESTAMP,
            replied_at TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks (id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
        )
    ''')

    # Email logs per supplier per task
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            supplier_id INTEGER,
            email_type TEXT,
            subject TEXT,
            body TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT,
            error TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks (id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
        )
    ''')

    # Quotes captured per supplier per item
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS supplier_quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            supplier_id INTEGER NOT NULL,
            pr_item_id INTEGER NOT NULL,
            unit_price REAL,
            total_price REAL,
            lead_time TEXT,
            payment_terms TEXT,
            ono BOOLEAN DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks (id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
            FOREIGN KEY (pr_item_id) REFERENCES pr_items (id)
        )
    ''')

    # Backfill missing columns on existing task_suppliers table
    def ensure_column(table, column, col_type):
        cursor.execute(f"PRAGMA table_info({table})")
        cols = [col[1] for col in cursor.fetchall()]
        if column not in cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    ensure_column('task_suppliers', 'initial_sent_at', 'TIMESTAMP')
    ensure_column('task_suppliers', 'followup_sent_at', 'TIMESTAMP')
    ensure_column('task_suppliers', 'replied_at', 'TIMESTAMP')
    ensure_column('pr_items', 'width', 'INTEGER')
    ensure_column('pr_items', 'length', 'INTEGER')
    ensure_column('pr_items', 'thickness', 'INTEGER')
    ensure_column('pr_items', 'payment_terms', 'TEXT')
    ensure_column('supplier_quotes', 'payment_terms', 'TEXT')
    ensure_column('supplier_quotes', 'ono', 'BOOLEAN')
    

    # Insert default admin user
    admin_password = generate_password_hash("admin123")
    cursor.execute('''
        INSERT OR IGNORE INTO users (username, password_hash, email, role)
        VALUES (?, ?, ?, ?)
    ''', ('admin', admin_password, 'admin@company.com', 'admin'))
    

    # ============== uncomment on initial setup ==============
    '''
    # Insert some default categories
    default_categories = ['Bolts, Fasteners', 'Calibration Services', 'Casting Services', 'Chemical Products', 'Construction Materials, Grout, Epoxy', 'Construction Services', 'Galvanizing Services', 'Hardware, Consumable Products', 'Hydraulic Equipments, Services', 'Logistic Services', 'Lubricant Products', 'Measuring Instruments & Equipments', 'PTFE', 'Paint Coating', 'Rubber Products', 'Stainless Steel', 'Steel Plates', 'Welding Equipments, Machinery, Tools']
    for category in default_categories:
        cursor.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (category,))
    '''

    conn.commit()
    conn.close()
    print("Database initialization completed.")

if __name__ == '__main__':
    init_database()


