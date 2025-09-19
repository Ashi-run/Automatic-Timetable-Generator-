import mysql.connector
from mysql.connector import Error

class DBConfig:
    """
    Centralized database configuration and connection management for the application.
    """
    # Database credentials and configuration
    DB_HOST = 'localhost'
    DB_USER = 'root'
    DB_PASSWORD = ''  # Default empty password for XAMPP MySQL
    DB_NAME = 'reclassify'
    DB_PORT = 3306

    # Application secret key
    SECRET_KEY = 'nmims_timetable_secret_key_2025'

    @staticmethod
    def get_connection():
        """
        Establishes and returns a database connection.
        Includes proper error handling and connection parameters.
        """
        try:
            conn = mysql.connector.connect(
                host=DBConfig.DB_HOST,
                user=DBConfig.DB_USER,
                password=DBConfig.DB_PASSWORD,
                database=DBConfig.DB_NAME,
                port=DBConfig.DB_PORT,
                autocommit=False,
                charset='utf8mb4',
                collation='utf8mb4_unicode_ci'
            )
            if conn.is_connected():
                print("Database connection successful.")
                return conn
            else:
                print("Failed to establish database connection")
                return None
        except Error as e:
            print(f"CRITICAL: Error while connecting to MySQL: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None
    
    @staticmethod
    def test_connection():
        """
        Tests the database connection and returns True if successful, False otherwise.
        """
        conn = DBConfig.get_connection()
        if conn and conn.is_connected():
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.close()
                conn.close()
                return True
            except Error as e:
                print(f"Connection test failed: {e}")
                if conn:
                    conn.close()
                return False
        return False