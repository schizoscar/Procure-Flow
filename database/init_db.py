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
            stock_availability TEXT,
            cert TEXT,
            lead_time TEXT,
            warranty TEXT,
            cert_file_id INTEGER,
            ono_width INTEGER,
            ono_length INTEGER,
            ono_thickness INTEGER,
            payment_terms TEXT,
            ono BOOLEAN DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks (id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
            FOREIGN KEY (pr_item_id) REFERENCES pr_items (id)
        )
    ''')

    # File assets table (store PDFs in DB)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS file_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            supplier_id INTEGER,
            pr_item_id INTEGER,
            filename TEXT NOT NULL,
            mime_type TEXT,
            data BLOB NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks (id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
            FOREIGN KEY (pr_item_id) REFERENCES pr_items (id)
        )
    ''')


    # Category Items table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS category_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(category_id, name),
            FOREIGN KEY (category_id) REFERENCES categories (id)
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
    ensure_column('task_suppliers', 'reply_token', 'TEXT')
    ensure_column('task_suppliers', 'quotation_file_id', 'INTEGER')
    ensure_column('task_suppliers', 'quote_form_token', 'TEXT')
    # pr_items dimension columns
    ensure_column('pr_items', 'width', 'INTEGER')
    ensure_column('pr_items', 'length', 'INTEGER')
    ensure_column('pr_items', 'thickness', 'INTEGER')
    ensure_column('pr_items', 'diameter', 'INTEGER')
    ensure_column('pr_items', 'dim_a', 'INTEGER')
    ensure_column('pr_items', 'dim_b', 'INTEGER')
    ensure_column('pr_items', 'uom_qty', 'TEXT')
    ensure_column('pr_items', 'uom', 'TEXT')
    ensure_column('pr_items', 'payment_terms', 'TEXT')
    ensure_column('pr_items', 'our_remarks', 'TEXT')
    # supplier_quotes columns
    ensure_column('supplier_quotes', 'payment_terms', 'TEXT')
    ensure_column('supplier_quotes', 'ono', 'BOOLEAN')
    ensure_column('supplier_quotes', 'ono_width', 'INTEGER')
    ensure_column('supplier_quotes', 'ono_length', 'INTEGER')
    ensure_column('supplier_quotes', 'ono_thickness', 'INTEGER')
    ensure_column('supplier_quotes', 'ono_dim_a', 'INTEGER')
    ensure_column('supplier_quotes', 'ono_dim_b', 'INTEGER')
    ensure_column('supplier_quotes', 'ono_diameter', 'INTEGER')
    ensure_column('supplier_quotes', 'ono_uom_qty', 'TEXT')
    ensure_column('supplier_quotes', 'ono_uom', 'TEXT')
    ensure_column('supplier_quotes', 'ono_brand', 'TEXT')
    ensure_column('supplier_quotes', 'lead_time', 'TEXT')
    ensure_column('supplier_quotes', 'warranty', 'TEXT')
    ensure_column('supplier_quotes', 'stock_availability', 'TEXT')
    ensure_column('supplier_quotes', 'cert', 'TEXT')
    ensure_column('supplier_quotes', 'cert_file_id', 'INTEGER')
    ensure_column('supplier_quotes', 'notes', 'TEXT')


    # Migrate existing numeric total_price into stock_availability (text) if present
    cursor.execute("PRAGMA table_info(supplier_quotes)")
    cols = [c[1] for c in cursor.fetchall()]
    if 'total_price' in cols and 'stock_availability' in cols:
        try:
            cursor.execute("UPDATE supplier_quotes SET stock_availability = CAST(total_price AS TEXT) WHERE stock_availability IS NULL")
        except Exception:
            pass
    

    # Insert default admin user
    admin_password = generate_password_hash("admin123")
    cursor.execute('''
        INSERT OR IGNORE INTO users (username, password_hash, email, role)
        VALUES (?, ?, ?, ?)
    ''', ('admin', admin_password, 'admin@company.com', 'admin'))
    

    # ============== uncomment on initial setup ==============
    '''
    # Insert default categories
    default_categories = [
        'Angle Bar', 'Bolts, Fasteners', 'Calibration Services', 'Casting Services',
        'Chemical Products', 'Construction Materials, Grout, Epoxy',
        'Construction Services', 'Galvanizing Services',
        'Hardware, Consumable Products', 'Hydraulic Equipments, Services',
        'Logistic Services', 'Lubricant Products', 'Measuring Instruments & Equipments',
        'PTFE', 'Paint Coating', 'Rebar', 'Rubber Products',
        'Stainless Steel', 'Steel Plates', 'Welding Equipments, Machinery, Tools',
        'Office Supplies'
    ]
    for category in default_categories:
        cursor.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (category,))

    # Default item names per category
    category_items_map = {
        'Steel Plates': [
            'Steel Plates',
            'Round Bar',
            'Flat Bar',
            'I-Beam'
        ],
        'Stainless Steel': [
            'Stainless Steel Plates',
            'Brass Flat Bar'
        ],
        'Bolts, Fasteners': [
            'Bolts',
            'Nuts',
            'Washers',
            'Stud Bar'
        ],
        'PTFE': [
            'Plain PTFE',
            'Etched PTFE',
            'Dimpled PTFE',
            'Etched PTFE Tape',
            'UHMW-PE'
        ],
        'Rubber Products': [
            'Compression Seals',
            'Rubber Seals',
            'Nylon Cord',
            'SMR 20 CV',
            'SMR 20',
            'Customised Reclaimed Rubber',
            'S40 V',
            'Skim Block'
        ],
        'Paint Coating': [
            'Paint Coating',
            'Trichloroethylene',
            'Chemlok',
            'Megum'
        ],
        'Chemical Products': [
            'Flexsys-Santoflex 77PD',
            'Carbon Black 330',
            'Carbon Black N220',
            'Toulene',
            'Tuladan Oil',
            'Stearic Acid',
            'TMTD',
            'CBS',
            'PVI',
            'MBTS',
            'TMQ',
            'H3236 WAX',
            'Sulphur',
            '6PPD',
            'ETU',
            'OPDA',
            'CLAY',
            'DFR 903'
        ],
        'Lubricant Products': [
            'Silicon Grease for PTFE',
            'Hydraulic Oil',
            'Engine Oil',
            'Compressor Oil'
        ],
        'Casting Services': [
            'Steel Casting'
        ],
        'Measuring Instruments & Equipments': [
            'Measuring Instruments',
            'PLC'
        ],
        'Welding Equipments, Machinery, Tools': [
            'Machineries',
            'Motors',
            'Welding Machine',
            'Lathe Machine',
            'Milling Machine',
            'CNC Lathing Machine',
            'Laser Cutting Machine',
            'Rubber Moulding Press',
            'Grinder',
            'Handrill',
            'Cutting Tools',
            'Grinding Disc',
            'Cutting Disc',
            'Drill Bits',
            'Machine Taps',
            'Blower',
            'Grout Pump'
        ],
        'Construction Materials, Grout, Epoxy': [
            'Non Shrink Grout',
            'Construction Epoxy'
        ],
        'Calibration Services': [
            'Calibration Services for Measuring Instruments & Equipments'
        ],
        'Galvanizing Services': [
            'Steel Plates Galvanizing Services'
        ],
        'Hardware, Consumable Products': [
            'Miscellaneous Hardware',
            'Tools'
        ],
        'Hydraulic Equipments, Services': [
            'Hydraulic Jacks',
            'Manifold',
            'Hose',
            'Pressure Gauge'
        ],
        'Logistic Services': [
            'Logistic Services',
            'Delivery Services'
        ],
        'Office Supplies': [
            'Stationery Products',
            'Printing Services'
        ],
        'Angle Bar': [
            'Angle Bar'
        ],
        'Rebar': [
            'Rebar'
        ],
    }

    for cat_name, items in category_items_map.items():
        cursor.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (cat_name,))
        cursor.execute('SELECT id FROM categories WHERE name = ?', (cat_name,))
        row = cursor.fetchone()
        if not row:
            continue
        cat_id = row[0]

        for item_name in items:
            cursor.execute(
                'INSERT OR IGNORE INTO category_items (category_id, name) VALUES (?, ?)',
                (cat_id, item_name)
            )
    '''


    conn.commit()
    conn.close()
    print("Database initialization completed.")

if __name__ == '__main__':
    init_database()


