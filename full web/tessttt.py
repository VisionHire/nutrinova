import mysql.connector

try:
    
    connection = mysql.connector.connect(
        host="localhost",          
        user="root",               
        password="A055FXXU10CXK1nkikk23",  
        database="nutritrack"      
    )
    
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
    
    if 'connection' in locals() and connection.is_connected():
        connection.close()
        print("🔒 MySQL connection closed.")
