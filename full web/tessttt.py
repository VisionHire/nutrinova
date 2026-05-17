import mysql.connector

try:
    # 🔹 Change these details according to your setup
    connection = mysql.connector.connect(
        host="localhost",          # MySQL server (usually localhost)
        user="root",               # your MySQL username
        password="A055FXXU10CXK1nkikk23",   # your MySQL password
        database="nutritrack"      # your database name
    )

    # ✅ Check if connected
    if connection.is_connected():
        db_info = connection.get_server_info()
        print(f"✅ Successfully connected to MySQL Server version {db_info}")
        cursor = connection.cursor()
        cursor.execute("SELECT DATABASE();")
        record = cursor.fetchone()
        print(f"📂 You're connected to database: {record[0]}")

except mysql.connector.Error as err:
    print(f"❌ Error while connecting to MySQL: {err}")

finally:
    # 🔒 Always close connection
    if 'connection' in locals() and connection.is_connected():
        connection.close()
        print("🔒 MySQL connection closed.")
