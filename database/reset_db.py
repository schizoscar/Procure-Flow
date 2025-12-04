# reset_db.py
import os
import sqlite3

def reset_database():
    # Use the database folder path
    db_path = os.path.join('database', 'procure_flow.db')
    
    # Delete the database file if it exists
    if os.path.exists(db_path):
        os.remove(db_path)
        print("Deleted old database file")
    
    # Ensure database directory exists
    os.makedirs('database', exist_ok=True)
    
    # Recreate database with proper structure in database folder
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create all tables with the new schema
    tables_sql = [
        '''CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''',
        
        '''CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''',
        
        '''CREATE TABLE suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact_name TEXT,
            email TEXT NOT NULL,
            contact_number TEXT,
            address TEXT,
            products_services TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''',
        
        '''CREATE TABLE supplier_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER,
            category_id INTEGER,
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
            FOREIGN KEY (category_id) REFERENCES categories (id)
        )''',
        
        '''CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name TEXT NOT NULL,
            user_id INTEGER,
            status TEXT DEFAULT 'purchase_requisition',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )''',
        
        '''CREATE TABLE pr_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            item_name TEXT NOT NULL,
            specification TEXT,
            brand TEXT,
            balance_stock INTEGER,
            quantity INTEGER NOT NULL,
            item_category TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks (id)
        )''',
        
        '''CREATE TABLE task_suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            supplier_id INTEGER,
            is_selected BOOLEAN DEFAULT TRUE,
            assigned_items TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks (id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
        )'''
    ]
    
    for sql in tables_sql:
        cursor.execute(sql)
        print(f"✅ Created table: {sql.split(' ')[2]}")
    
    # Add default data
    from werkzeug.security import generate_password_hash
    
    # Default admin user
    admin_password = generate_password_hash("admin123")
    cursor.execute(
        'INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)',
        ('admin', admin_password, 'admin@company.com', 'admin')
    )
    
    # Default categories
    default_categories = ['Bolts, Fasteners', 'Calibration Services', 'Casting Services', 'Chemical Products', 'Construction', 'Construction Materials, Grout, Epoxy', 'Construction Services', 'Electronics', 'Galvanizing Services', 
'Hardware, Consumable Products', 'Hydraulic Equipments, Services', 'IT Equipment', 'Logistic Services', 'Lubricant Products', 'Measuring Instruments & Equipments', 'Mechanical', 'Office Supplies', 'PTFE', 'Paint Coating', 'Rubber Products', 'Stainless Steel', 'Steel Plates', 'Welding Equipments, Machinery, Tools']
    for category in default_categories:
        cursor.execute('INSERT INTO categories (name) VALUES (?)', (category,))
    
    # Insert default admin user
    admin_password = generate_password_hash("admin123")  # Change this in production
    cursor.execute('''
        INSERT OR IGNORE INTO users (username, password_hash, email, role)
        VALUES (?, ?, ?, ?)
    ''', ('admin', admin_password, 'admin@company.com', 'admin'))
    
    conn.commit()
    conn.close()
    
    print("Database reset completed successfully!")
    print("You can now open procure_flow.db in DB Browser")

if __name__ == '__main__':
    reset_database()

