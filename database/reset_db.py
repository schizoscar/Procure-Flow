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
            item_category TEXT NOT NULL,
            brand TEXT,
            quantity INTEGER NOT NULL,
            payment_terms TEXT,
            -- Steel Plates dimensions
            width INTEGER,
            length INTEGER,
            thickness INTEGER,
            -- Angle Bar dimensions
            dim_a INTEGER,
            dim_b INTEGER,
            -- Bolts/Rebar dimensions
            diameter INTEGER,
            -- Other category UOM
            uom_qty INTEGER,
            uom TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks (id)
        )''',
        
        '''CREATE TABLE task_suppliers (
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
        )''',
        
        '''CREATE TABLE email_logs (
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
        )''',
        
        '''CREATE TABLE supplier_quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            supplier_id INTEGER NOT NULL,
            pr_item_id INTEGER NOT NULL,

            unit_price REAL,
            stock_availability TEXT,
            cert TEXT,
            lead_time TEXT,
            warranty TEXT,
            payment_terms TEXT,

            ono BOOLEAN DEFAULT 0,

            -- O.N.O. dims for steel plates/stainless (W/L/Thk)
            ono_width INTEGER,
            ono_length INTEGER,
            ono_thickness INTEGER,

            -- O.N.O. dims for angle bar (A/B + L/Thk)
            ono_dim_a INTEGER,
            ono_dim_b INTEGER,

            -- O.N.O. dims for bolts/rebar (D + L)
            ono_diameter INTEGER,

            -- O.N.O. for other (UOM amount + UOM text)
            ono_uom_qty INTEGER,
            ono_uom TEXT,

            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (task_id) REFERENCES tasks (id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
            FOREIGN KEY (pr_item_id) REFERENCES pr_items (id)
        )''',
        '''CREATE TABLE IF NOT EXISTS email_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            supplier_id INTEGER NOT NULL,
            email_type TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks (id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
        )''',
        '''CREATE TABLE IF NOT EXISTS category_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(category_id, name),
            FOREIGN KEY (category_id) REFERENCES categories (id)
        )'''
    ]
    
    for sql in tables_sql:
        cursor.execute(sql)
        print(f"Created table: {sql.split(' ')[2]}")
    
    # Add default data
    from werkzeug.security import generate_password_hash
    
    # Default admin user
    admin_password = generate_password_hash("admin123")
    cursor.execute(
        'INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)',
        ('admin', admin_password, 'admin@company.com', 'admin')
    )
    
    # Default categories
    # ---------- Default item names per category ----------
    category_items_map = {
        # STEEL PLATES, ROUND BAR, ETC.
        'Steel Plates': [
            'Steel Plates',
            'Round Bar',
            'Flat Bar',
            'I-Beam'
        ],

        # STAINLESS STEEL, BRASS PRODUCTS, ETC.
        'Stainless Steel': [
            'Stainless Steel Plates',
            'Brass Flat Bar'
        ],

        # BOLTS, FASTENERS, ETC.
        'Bolts, Fasteners': [
            'Bolts',
            'Nuts',
            'Washers',
            'Stud Bar'
        ],

        # PTFE, ETC.
        'PTFE': [
            'Plain PTFE',
            'Etched PTFE',
            'Dimpled PTFE',
            'Etched PTFE Tape',
            'UHMW-PE'
        ],

        # RUBBER PRODUCTS, ETC.
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

        # PAINT COATING PRODUCTS, ETC.
        'Paint Coating': [
            'Paint Coating',
            'Trichloroethylene',
            'Chemlok',
            'Megum'
        ],

        # CHEMICAL PRODUCTS, ETC.
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

        # LUBRICANTS PRODUCTS, ETC.
        'Lubricant Products': [
            'Silicon Grease for PTFE',
            'Hydraulic Oil',
            'Engine Oil',
            'Compressor Oil'
        ],

        # CASTING SERVICES, ETC.
        'Casting Services': [
            'Steel Casting'
        ],

        # MEASURING INSTRUMENTS & EQUIPMENTS, ETC.
        'Measuring Instruments & Equipments': [
            'Measuring Instruments',
            'PLC'
        ],

        # MACHINERY & EQUIPMENTS, MACHINE TOOLS & ABRASIVES, CONSTRUCTION MACHINERY
        # (all mapped into your existing category name)
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

        # CONSTRUCTION MATERIALS, GROUT, ETC.
        'Construction Materials, Grout, Epoxy': [
            'Non Shrink Grout',
            'Construction Epoxy'
        ],

        # CALIBRATION SERVICES
        'Calibration Services': [
            'Calibration Services for Measuring Instruments & Equipments'
        ],

        # GALVANIZING SERVICES
        'Galvanizing Services': [
            'Steel Plates Galvanizing Services'
        ],

        # HARDWARE, CONSUMABLE PRODUCTS, ETC.
        'Hardware, Consumable Products': [
            'Miscellaneous Hardware',
            'Tools'
        ],

        # HYDRAULIC EQUIPMENTS, SERVICES, ETC.
        'Hydraulic Equipments, Services': [
            'Hydraulic Jacks',
            'Manifold',
            'Hose',
            'Pressure Gauge'
        ],

        # LOGISTIC SERVICES, ETC.
        'Logistic Services': [
            'Logistic Services',
            'Delivery Services'
        ],

        # STATIONERY, PRINTING SERVICES, ETC.
        # (mapped to Office Supplies since your categories include that)
        'Office Supplies': [
            'Stationery Products',
            'Printing Services'
        ],

        # Optional: Angle Bar default (you already have category)
        'Angle Bar': [
            'Angle Bar'
        ],

        # Optional: Rebar default (you already have category)
        'Rebar': [
            'Rebar'
        ],
    }

    # Ensure category exists, then insert items
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
    # ---------- end default items ----------

    
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
