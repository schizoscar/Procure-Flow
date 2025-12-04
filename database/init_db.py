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
            brand TEXT,
            balance_stock INTEGER,
            quantity INTEGER NOT NULL,
            item_category TEXT NOT NULL,
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
            FOREIGN KEY (task_id) REFERENCES tasks (id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
        )
    ''')
    

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



