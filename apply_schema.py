"""
Apply database schema to MySQL.
Run this after mysql_setup.py and sql_refactor_setup.py
"""
import os
import mysql.connector

MYSQL_USER = "Claude"
MYSQL_PASSWORD = "WXdCPJmeDfaQALaktzF6!"
MYSQL_HOST = "localhost"
MYSQL_DB = "tower_bot"

def apply_schema():
    """Apply the database schema."""
    schema_path = os.path.join(os.path.dirname(__file__), "database_schema.sql")
    
    if not os.path.exists(schema_path):
        print("✗ database_schema.sql not found!")
        print("  Run sql_refactor_setup.py first")
        return False
    
    print("="*60)
    print("Applying Database Schema")
    print("="*60)
    
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DB
        )
        cursor = conn.cursor()
        
        # Split by semicolon and handle multi-line statements
        statements = []
        current_stmt = []
        
        for line in schema_sql.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            
            current_stmt.append(line)
            
            if stripped.endswith(';'):
                full_stmt = '\n'.join(current_stmt).strip()
                if full_stmt:
                    statements.append(full_stmt)
                current_stmt = []
        
        if current_stmt:
            remaining = '\n'.join(current_stmt).strip()
            if remaining:
                statements.append(remaining)
        
        print(f"Found {len(statements)} SQL statements to execute")
        
        success = 0
        errors = 0
        
        for i, stmt in enumerate(statements):
            if not stmt:
                continue
            
            # Remove leading comment lines to get to the actual SQL
            lines = stmt.split('\n')
            sql_lines = []
            for line in lines:
                stripped_line = line.strip()
                # Skip pure comment lines at the START of a statement
                if stripped_line.startswith('--') and not sql_lines:
                    continue
                sql_lines.append(line)
            
            clean_stmt = '\n'.join(sql_lines).strip()
            
            if not clean_stmt:
                continue
            
            # Skip USE statement (we're already connected to the database)
            if clean_stmt.upper().startswith('USE '):
                print(f"  - Skipping USE statement (already connected)")
                continue
            
            # Skip pure comment statements
            if clean_stmt.startswith('--'):
                continue
                
            try:
                cursor.execute(clean_stmt)
                conn.commit()
                success += 1
                
                # Log what we did
                stmt_upper = clean_stmt.upper()
                if 'CREATE TABLE' in stmt_upper:
                    parts = clean_stmt.upper().split('CREATE TABLE')[1].split('(')[0]
                    table_name = parts.replace('IF NOT EXISTS', '').strip().lower()
                    print(f"  ✓ Created table: {table_name}")
                elif 'INSERT' in stmt_upper:
                    print(f"  ✓ Inserted default data")
                elif 'CREATE INDEX' in stmt_upper:
                    print(f"  ✓ Created index")
                else:
                    print(f"  ✓ Executed statement {i+1}")
                    
            except mysql.connector.Error as e:
                err_str = str(e).lower()
                if "already exists" in err_str:
                    print(f"  - Table already exists (skipped)")
                    success += 1
                elif "duplicate" in err_str:
                    print(f"  - Duplicate entry (skipped)")
                    success += 1
                else:
                    print(f"  ✗ Error on statement {i+1}: {e}")
                    print(f"    Statement: {clean_stmt[:150]}...")
                    errors += 1
        
        cursor.close()
        conn.close()
        
        print(f"\n✓ Schema applied: {success} statements successful, {errors} errors")
        
        # Verify tables
        print("\nVerifying tables...")
        conn2 = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DB
        )
        cursor2 = conn2.cursor()
        cursor2.execute("SHOW TABLES")
        tables = [t[0] for t in cursor2.fetchall()]
        cursor2.close()
        conn2.close()
        
        print(f"✓ Found {len(tables)} tables:")
        for t in tables:
            print(f"    - {t}")
        
        return len(tables) > 0
        
    except mysql.connector.Error as e:
        print(f"✗ MySQL error: {e}")
        return False


if __name__ == "__main__":
    success = apply_schema()
    if success:
        print("\n" + "="*60)
        print("DATABASE READY!")
        print("="*60)
        print("Tell Claude to continue with Phase 2 (data migration)")
    else:
        print("\n⚠ Schema application had issues. Check errors above.")
