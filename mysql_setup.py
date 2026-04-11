"""
MySQL Setup Script - Run this FIRST to create database and grant permissions
Uses root credentials to set up tower_bot database and Claude user permissions.
"""
import mysql.connector

# Root credentials
ROOT_USER = "root"  
ROOT_PASSWORD = "qT9bDq7V84fnLWjCP2HW1!"
MYSQL_HOST = "localhost"

# Bot user credentials
BOT_USER = "Claude"
BOT_PASSWORD = "WXdCPJmeDfaQALaktzF6!"
MYSQL_DB = "tower_bot"


def setup_database():
    """Create database and grant permissions using root."""
    print("="*60)
    print("MySQL Database Setup (using root)")
    print("="*60)
    
    try:
        # Connect as root
        print("\n1. Connecting as root...")
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=ROOT_USER,
            password=ROOT_PASSWORD
        )
        cursor = conn.cursor()
        print("   ✓ Connected as root")
        
        # Create database if not exists
        print("\n2. Creating database 'tower_bot'...")
        cursor.execute("CREATE DATABASE IF NOT EXISTS tower_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        print("   ✓ Database 'tower_bot' created/verified")
        
        # Check if Claude user exists
        print("\n3. Setting up 'Claude' user...")
        cursor.execute("SELECT User FROM mysql.user WHERE User = 'Claude'")
        user_exists = cursor.fetchone()
        
        if not user_exists:
            # Create user
            cursor.execute(f"CREATE USER 'Claude'@'localhost' IDENTIFIED BY '{BOT_PASSWORD}'")
            cursor.execute(f"CREATE USER 'Claude'@'%' IDENTIFIED BY '{BOT_PASSWORD}'")
            print("   ✓ User 'Claude' created")
        else:
            print("   ✓ User 'Claude' already exists")
        
        # Grant all privileges on tower_bot
        print("\n4. Granting privileges...")
        cursor.execute("GRANT ALL PRIVILEGES ON tower_bot.* TO 'Claude'@'localhost'")
        cursor.execute("GRANT ALL PRIVILEGES ON tower_bot.* TO 'Claude'@'%'")
        cursor.execute("FLUSH PRIVILEGES")
        print("   ✓ Full privileges granted on tower_bot")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        # Test connection as Claude
        print("\n5. Testing connection as 'Claude'...")
        test_conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=BOT_USER,
            password=BOT_PASSWORD,
            database=MYSQL_DB
        )
        test_cursor = test_conn.cursor()
        test_cursor.execute("SELECT 1")
        test_cursor.fetchone()
        test_cursor.close()
        test_conn.close()
        print("   ✓ Claude user can connect to tower_bot!")
        
        print("\n" + "="*60)
        print("DATABASE SETUP COMPLETE!")
        print("="*60)
        print("\nNow run: python sql_refactor_setup.py")
        return True
        
    except mysql.connector.Error as e:
        print(f"\n✗ MySQL error: {e}")
        print("\nTroubleshooting:")
        print("  - Make sure MySQL is running")
        print("  - Check root password is correct")
        print("  - Try connecting with: mysql -u root -p")
        return False


if __name__ == "__main__":
    setup_database()
