from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime
import json

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# Association table for supplier categories
supplier_categories = db.Table('supplier_categories',
    db.Column('supplier_id', db.Integer, db.ForeignKey('suppliers.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('categories.id'), primary_key=True)
)

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Relationships
    tasks = db.relationship('Task', backref='creator', lazy=True)

class Supplier(db.Model):
    __tablename__ = 'suppliers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    contact_name = db.Column(db.String(200))
    email = db.Column(db.String(120), nullable=False)
    contact_number = db.Column(db.String(50))
    address = db.Column(db.Text)
    products_services = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    categories = db.relationship('Category', secondary=supplier_categories, backref='suppliers')
    task_suppliers = db.relationship('TaskSupplier', backref='supplier', lazy=True)
    quotes = db.relationship('SupplierQuote', backref='supplier', lazy=True)

class Category(db.Model):
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    
    # Relationships
    items = db.relationship('CategoryItem', backref='category', lazy=True)

class CategoryItem(db.Model):
    __tablename__ = 'category_items'
    
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)

class Task(db.Model):
    __tablename__ = 'tasks'
    
    id = db.Column(db.Integer, primary_key=True)
    task_name = db.Column(db.String(500), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(50), default='purchase_requisition')
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Relationships
    pr_items = db.relationship('PRItem', backref='task', lazy=True, cascade='all, delete-orphan')
    task_suppliers = db.relationship('TaskSupplier', backref='task', lazy=True, cascade='all, delete-orphan')
    quotes = db.relationship('SupplierQuote', backref='task', lazy=True, cascade='all, delete-orphan')
    email_logs = db.relationship('EmailLog', backref='task', lazy=True, cascade='all, delete-orphan')
    file_assets = db.relationship('FileAsset', backref='task', lazy=True, cascade='all, delete-orphan')

class PRItem(db.Model):
    __tablename__ = 'pr_items'
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    item_category = db.Column(db.String(100), nullable=False)
    item_name = db.Column(db.String(500), nullable=False)
    brand = db.Column(db.String(200))
    quantity = db.Column(db.Integer, nullable=False)
    payment_terms = db.Column(db.String(100))
    
    # Dimensions for different categories
    width = db.Column(db.Integer)
    length = db.Column(db.Integer)
    thickness = db.Column(db.Integer)
    dim_a = db.Column(db.Integer)
    dim_b = db.Column(db.Integer)
    diameter = db.Column(db.Integer)
    
    # For "Other" categories
    uom_qty = db.Column(db.String(100))
    uom = db.Column(db.String(50))
    
    our_remarks = db.Column(db.Text)
    
    # Relationships
    quotes = db.relationship('SupplierQuote', backref='pr_item', lazy=True, cascade='all, delete-orphan')

class TaskSupplier(db.Model):
    __tablename__ = 'task_suppliers'
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    is_selected = db.Column(db.Boolean, default=False)
    assigned_items = db.Column(db.Text)  # JSON string of item IDs
    initial_sent_at = db.Column(db.DateTime)
    followup_sent_at = db.Column(db.DateTime)
    replied_at = db.Column(db.DateTime)
    quote_form_token = db.Column(db.String(500))
    quotation_file_id = db.Column(db.Integer, db.ForeignKey('file_assets.id'))
    
    # Relationships
    quotation_file = db.relationship('FileAsset', foreign_keys=[quotation_file_id])

class SupplierQuote(db.Model):
    __tablename__ = 'supplier_quotes'
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    pr_item_id = db.Column(db.Integer, db.ForeignKey('pr_items.id'), nullable=False)
    
    unit_price = db.Column(db.Numeric(10, 2))
    stock_availability = db.Column(db.String(200))
    lead_time = db.Column(db.Integer)
    warranty = db.Column(db.String(200))
    payment_terms = db.Column(db.String(100))
    notes = db.Column(db.Text)
    
    # O.N.O. fields
    ono = db.Column(db.Boolean, default=False)
    ono_width = db.Column(db.Integer)
    ono_length = db.Column(db.Integer)
    ono_thickness = db.Column(db.Integer)
    ono_dim_a = db.Column(db.Integer)
    ono_dim_b = db.Column(db.Integer)
    ono_diameter = db.Column(db.Integer)
    ono_uom = db.Column(db.String(50))
    ono_uom_qty = db.Column(db.String(100))
    ono_brand = db.Column(db.String(200))
    
    # Certificate file
    cert_file_id = db.Column(db.Integer, db.ForeignKey('file_assets.id'))
    
    # Relationships
    cert_file = db.relationship('FileAsset', foreign_keys=[cert_file_id])

class FileAsset(db.Model):
    __tablename__ = 'file_assets'
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'))
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'))
    pr_item_id = db.Column(db.Integer, db.ForeignKey('pr_items.id'))
    filename = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(100))
    data = db.Column(db.LargeBinary)
    created_at = db.Column(db.DateTime, default=datetime.now)

class EmailLog(db.Model):
    __tablename__ = 'email_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    email_type = db.Column(db.String(50))  # 'initial', 'followup', 'reply', 'supplier_form'
    subject = db.Column(db.String(500))
    body = db.Column(db.Text)
    status = db.Column(db.String(50))  # 'sent', 'failed', 'received'
    error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)