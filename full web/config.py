import os

class Config:
    # Secret key for session security
    SECRET_KEY = os.environ.get("SECRET_KEY", "nutritracksecretkey")

    # MySQL Database Configuration
    MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
    MYSQL_USER = os.environ.get("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "A055FXXU10CXK1nkikk23")
    MYSQL_DB = os.environ.get("MYSQL_DB", "nutritrack")

    # Optional (recommended for better dictionary-style MySQL responses)
    MYSQL_CURSORCLASS = "DictCursor"
