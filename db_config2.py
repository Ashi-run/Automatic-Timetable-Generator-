import mysql.connector

def get_connection():
    """Get MySQL connection"""
    try:
        conn = mysql.connector.connect(
        host="localhost",
        user="root",
        password="",  # default in XAMPP is blank
        database="reclassify"
        )
        return conn
    except mysql.connector.Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None
