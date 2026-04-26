import sqlite3
import os

def init_db():
    db_path = os.path.join(os.path.dirname(__file__), 'sentinel.db')
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')

    print(f"Initializing database at {db_path}...")
    
    with open(schema_path, 'r') as f:
        schema_script = f.read()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.executescript(schema_script)
    conn.commit()
    conn.close()
    
    print("Database initialized successfully.")

if __name__ == '__main__':
    init_db()
