# check_columns.py
import sqlite3

conn = sqlite3.connect('database/procure_flow.db')
cursor = conn.cursor()

# Check the exact structure of task_suppliers table
cursor.execute("PRAGMA table_info(task_suppliers)")
columns = cursor.fetchall()

print("Columns in task_suppliers table:")
for col in columns:
    print(f"  {col[1]} ({col[2]})")

conn.close()
