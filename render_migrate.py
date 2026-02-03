# render_migrate.py
import os
import sys

print("Starting Render migration process...")
print(f"Current directory: {os.getcwd()}")

# Check if we're on Render
is_render = os.getenv('RENDER') == 'true'
print(f"On Render: {is_render}")

# Check if SQLite database exists
sqlite_db_path = 'database/procure_flow.db'
if os.path.exists(sqlite_db_path):
    print(f"✅ Found SQLite database: {sqlite_db_path}")
    print(f"File size: {os.path.getsize(sqlite_db_path)} bytes")
else:
    print(f"❌ SQLite database not found at: {sqlite_db_path}")
    print("Please make sure the SQLite database file is committed to Git.")
    sys.exit(1)

try:
    # Import and run migration
    from migrate_sqlite_to_postgres import migrate_all_data
    print("\nRunning migration...")
    migrate_all_data()
    print("\n✅ Migration completed successfully!")
    
except Exception as e:
    print(f"❌ Migration failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)