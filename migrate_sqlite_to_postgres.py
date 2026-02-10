# migrate_sqlite_to_postgres.py
import sqlite3
import json
import os
import sys
from datetime import datetime
from flask import Flask
from werkzeug.security import generate_password_hash
from sqlalchemy import text, func, create_engine
from sqlalchemy.orm import sessionmaker

# Add the parent directory to path so we can import models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import db, User, Supplier, Category, CategoryItem, Task, PRItem, TaskSupplier, SupplierQuote, FileAsset, EmailLog

def create_postgres_app():
    app = Flask(__name__)

    pg_url = os.getenv("DATABASE_URL")
    if not pg_url:
        raise RuntimeError("DATABASE_URL must be set (PostgreSQL target)")

    if pg_url.startswith("postgres://"):
        pg_url = pg_url.replace("postgres://", "postgresql+pg8000://", 1)
    elif pg_url.startswith("postgresql://"):
        pg_url = pg_url.replace("postgresql://", "postgresql+pg8000://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = pg_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    return app


def parse_datetime(dt_str):
    """Parse datetime from SQLite format"""
    if not dt_str:
        return None
    try:
        # SQLite format: '2024-01-15 10:30:00'
        return datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    except:
        try:
            # ISO format
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except:
            print(f"Warning: Could not parse datetime: {dt_str}")
            return None

def fix_postgres_sequences(db_session):
    """Fix PostgreSQL sequences after migration."""
    print("\nFixing PostgreSQL sequences...")
    
    try:
        # Get max IDs and fix sequences
        tables = [
            ('users', User),
            ('suppliers', Supplier),
            ('categories', Category),
            ('category_items', CategoryItem),
            ('tasks', Task),
            ('pr_items', PRItem),
            ('task_suppliers', TaskSupplier),
            ('supplier_quotes', SupplierQuote),
            ('file_assets', FileAsset),
            ('email_logs', EmailLog),
        ]
        
        for table_name, model in tables:
            max_id = db_session.query(func.max(model.id)).scalar() or 0
            db_session.execute(
                text(f"SELECT setval('{table_name}_id_seq', :max_id + 1, false)"),
                {'max_id': max_id}
            )
            print(f"✅ Fixed {table_name}_id_seq (max: {max_id})")
        
        db_session.commit()
        print("🎉 All sequences fixed!")
        
    except Exception as e:
        print(f"⚠️ Could not fix sequences: {e}")
        db_session.rollback()

def migrate_all_data():
    """Complete migration from SQLite to SQLAlchemy models."""
    
    app = create_app()
    
    with app.app_context():
        print("Starting migration process...")
        
        # Check if SQLite database exists
        sqlite_db_path = 'database/procure_flow.db'
        if not os.path.exists(sqlite_db_path):
            print(f"❌ SQLite database not found at: {sqlite_db_path}")
            print("Please make sure the SQLite database file exists.")
            return
        
        sqlite_conn = sqlite3.connect("database/procure_flow.db")
        sqlite_conn.row_factory = sqlite3.Row
        
        # Test PostgreSQL connection
        try:
            db.session.execute(text('SELECT 1'))
            print("✅ PostgreSQL connection successful")
        except Exception as e:
            print(f"❌ PostgreSQL connection failed: {e}")
            sqlite_conn.close()
            return
        
        # Clear existing data (if any)
        print("\nClearing existing tables...")
        try:
            # Drop in reverse order to respect foreign keys
            db.session.execute(text('DROP TABLE IF EXISTS email_logs CASCADE'))
            db.session.execute(text('DROP TABLE IF EXISTS supplier_quotes CASCADE'))
            db.session.execute(text('DROP TABLE IF EXISTS task_suppliers CASCADE'))
            db.session.execute(text('DROP TABLE IF EXISTS file_assets CASCADE'))
            db.session.execute(text('DROP TABLE IF EXISTS pr_items CASCADE'))
            db.session.execute(text('DROP TABLE IF EXISTS tasks CASCADE'))
            db.session.execute(text('DROP TABLE IF EXISTS supplier_categories CASCADE'))
            db.session.execute(text('DROP TABLE IF EXISTS category_items CASCADE'))
            db.session.execute(text('DROP TABLE IF EXISTS suppliers CASCADE'))
            db.session.execute(text('DROP TABLE IF EXISTS categories CASCADE'))
            db.session.execute(text('DROP TABLE IF EXISTS users CASCADE'))
            db.session.commit()
            print("✅ Tables dropped")
        except Exception as e:
            print(f"⚠️  Could not drop tables (maybe they don't exist): {e}")
            db.session.rollback()
        
        # Create tables
        print("Creating tables...")
        db.create_all()
        print("✅ Tables created")
        
        # 1. Migrate Users
        print("\nMigrating users...")
        sqlite_users = sqlite_conn.execute('SELECT * FROM users').fetchall()
        for row in sqlite_users:
            user = User(
                id=row['id'],
                username=row['username'],
                email=row['email'],
                password_hash=row['password_hash'],
                role=row['role'],
                created_at=parse_datetime(row['created_at'])
            )
            db.session.add(user)
        db.session.commit()
        print(f"✅ Migrated {len(sqlite_users)} users")
        
        # 2. Migrate Categories
        print("\nMigrating categories...")
        sqlite_categories = sqlite_conn.execute('SELECT * FROM categories').fetchall()
        for row in sqlite_categories:
            category = Category(id=row['id'], name=row['name'])
            db.session.add(category)
        db.session.commit()
        print(f"✅ Migrated {len(sqlite_categories)} categories")
        
        # 3. Migrate Category Items
        print("\nMigrating category items...")
        sqlite_category_items = sqlite_conn.execute('SELECT * FROM category_items').fetchall()
        for row in sqlite_category_items:
            category_item = CategoryItem(
                id=row['id'],
                category_id=row['category_id'],
                name=row['name']
            )
            db.session.add(category_item)
        db.session.commit()
        print(f"✅ Migrated {len(sqlite_category_items)} category items")
        
        # 4. Migrate Suppliers
        print("\nMigrating suppliers...")
        sqlite_suppliers = sqlite_conn.execute('SELECT * FROM suppliers').fetchall()
        for row in sqlite_suppliers:
            supplier = Supplier(
                id=row['id'],
                name=row['name'],
                contact_name=row['contact_name'],
                email=row['email'],
                contact_number=row['contact_number'],
                address=row['address'],
                products_services=row['products_services'],
                is_active=bool(row['is_active']) if row['is_active'] is not None else True
            )
            db.session.add(supplier)
        db.session.commit()
        print(f"✅ Migrated {len(sqlite_suppliers)} suppliers")
        
        # 5. Migrate Supplier Categories (many-to-many)
        print("\nMigrating supplier categories...")
        try:
            sqlite_supplier_categories = sqlite_conn.execute('SELECT * FROM supplier_categories').fetchall()
            for row in sqlite_supplier_categories:
                supplier = db.session.get(Supplier, row['supplier_id'])
                category = db.session.get(Category, row['category_id'])
                if supplier and category:
                    supplier.categories.append(category)
            db.session.commit()
            print(f"✅ Migrated {len(sqlite_supplier_categories)} supplier-category relationships")
        except Exception as e:
            print(f"⚠️  Could not migrate supplier categories: {e}")
        
        # 6. Migrate Tasks
        print("\nMigrating tasks...")
        sqlite_tasks = sqlite_conn.execute('SELECT * FROM tasks').fetchall()
        for row in sqlite_tasks:
            task = Task(
                id=row['id'],
                task_name=row['task_name'],
                user_id=row['user_id'],
                status=row['status'],
                created_at=parse_datetime(row['created_at'])
            )
            db.session.add(task)
        db.session.commit()
        print(f"✅ Migrated {len(sqlite_tasks)} tasks")
        
        # 7. Migrate PR Items
        print("\nMigrating PR items...")
        sqlite_pr_items = sqlite_conn.execute('SELECT * FROM pr_items').fetchall()
        for row in sqlite_pr_items:
            pr_item = PRItem(
                id=row['id'],
                task_id=row['task_id'],
                item_category=row['item_category'],
                item_name=row['item_name'],
                brand=row['brand'],
                quantity=row['quantity'],
                payment_terms=row['payment_terms'],
                width=row['width'],
                length=row['length'],
                thickness=row['thickness'],
                dim_a=row['dim_a'],
                dim_b=row['dim_b'],
                diameter=row['diameter'],
                uom_qty=row['uom_qty'],
                uom=row['uom'],
                our_remarks=row['our_remarks']
            )
            db.session.add(pr_item)
        db.session.commit()
        print(f"✅ Migrated {len(sqlite_pr_items)} PR items")
        
        # 8. Migrate File Assets
        print("\nMigrating file assets...")
        try:
            sqlite_file_assets = sqlite_conn.execute('SELECT * FROM file_assets').fetchall()
            for row in sqlite_file_assets:
                file_asset = FileAsset(
                    id=row['id'],
                    task_id=row['task_id'],
                    supplier_id=row['supplier_id'],
                    pr_item_id=row['pr_item_id'],
                    filename=row['filename'],
                    mime_type=row['mime_type'],
                    data=row['data'],
                    created_at=parse_datetime(row['created_at'])
                )
                db.session.add(file_asset)
            db.session.commit()
            print(f"✅ Migrated {len(sqlite_file_assets)} file assets")
        except Exception as e:
            print(f"⚠️  Could not migrate file assets: {e}")
        
        # 9. Migrate Task Suppliers
        print("\nMigrating task suppliers...")
        sqlite_task_suppliers = sqlite_conn.execute('SELECT * FROM task_suppliers').fetchall()
        for row in sqlite_task_suppliers:
            # Parse assigned_items JSON
            assigned_items = None
            if row['assigned_items']:
                try:
                    assigned_items = json.loads(row['assigned_items'])
                except:
                    assigned_items = None
            
            task_supplier = TaskSupplier(
                id=row['id'],
                task_id=row['task_id'],
                supplier_id=row['supplier_id'],
                is_selected=bool(row['is_selected']) if row['is_selected'] is not None else False,
                assigned_items=json.dumps(assigned_items) if assigned_items else None,
                initial_sent_at=parse_datetime(row['initial_sent_at']),
                followup_sent_at=parse_datetime(row['followup_sent_at']),
                replied_at=parse_datetime(row['replied_at']),
                quote_form_token=row['quote_form_token'],
                quotation_file_id=row['quotation_file_id'] if row['quotation_file_id'] else None
            )
            db.session.add(task_supplier)
        db.session.commit()
        print(f"✅ Migrated {len(sqlite_task_suppliers)} task suppliers")
        
        # 10. Migrate Supplier Quotes
        print("\nMigrating supplier quotes...")
        sqlite_supplier_quotes = sqlite_conn.execute('SELECT * FROM supplier_quotes').fetchall()
        for row in sqlite_supplier_quotes:
            # Handle unit_price - SQLite might store as string
            unit_price = row['unit_price']
            if unit_price is not None:
                try:
                    unit_price = float(unit_price)
                except:
                    unit_price = None
            
            quote = SupplierQuote(
                id=row['id'],
                task_id=row['task_id'],
                supplier_id=row['supplier_id'],
                pr_item_id=row['pr_item_id'],
                unit_price=unit_price,
                stock_availability=row['stock_availability'],
                lead_time=row['lead_time'],
                warranty=row['warranty'],
                payment_terms=row['payment_terms'],
                notes=row['notes'],
                ono=bool(row['ono']) if row['ono'] is not None else False,
                ono_width=row['ono_width'],
                ono_length=row['ono_length'],
                ono_thickness=row['ono_thickness'],
                ono_dim_a=row['ono_dim_a'],
                ono_dim_b=row['ono_dim_b'],
                ono_diameter=row['ono_diameter'],
                ono_uom=row['ono_uom'],
                ono_uom_qty=row['ono_uom_qty'],
                ono_brand=row['ono_brand'],
                cert_file_id=row['cert_file_id'] if row['cert_file_id'] else None
            )
            db.session.add(quote)
        db.session.commit()
        print(f"✅ Migrated {len(sqlite_supplier_quotes)} supplier quotes")
        
        # 11. Migrate Email Logs
        print("\nMigrating email logs...")
        try:
            sqlite_email_logs = sqlite_conn.execute('SELECT * FROM email_logs').fetchall()
            for row in sqlite_email_logs:
                email_log = EmailLog(
                    id=row['id'],
                    task_id=row['task_id'],
                    supplier_id=row['supplier_id'],
                    email_type=row['email_type'],
                    subject=row['subject'],
                    body=row['body'],
                    status=row['status'],
                    error=row['error'],
                    created_at=parse_datetime(row['created_at'])
                )
                db.session.add(email_log)
            db.session.commit()
            print(f"✅ Migrated {len(sqlite_email_logs)} email logs")
        except Exception as e:
            print(f"⚠️  Could not migrate email logs: {e}")
        
        # Fix sequences BEFORE closing SQLite connection
        fix_postgres_sequences(db.session)
        
        print("\n" + "="*60)
        print("MIGRATION COMPLETE!")
        print("="*60)
        print(f"Summary:")
        print(f"- Users: {len(sqlite_users)}")
        print(f"- Suppliers: {len(sqlite_suppliers)}")
        print(f"- Categories: {len(sqlite_categories)}")
        print(f"- Tasks: {len(sqlite_tasks)}")
        print(f"- PR Items: {len(sqlite_pr_items)}")
        print(f"- Supplier Quotes: {len(sqlite_supplier_quotes)}")
        print("\n✅ Data successfully migrated to PostgreSQL!")
        
        # Close SQLite connection
        sqlite_conn.close()

if __name__ == '__main__':
    migrate_all_data()