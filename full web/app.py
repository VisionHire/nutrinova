import os
import json
import tempfile
import shutil
import time
import hashlib
import hmac
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from functools import wraps
from contextlib import closing
from typing import Optional, Dict, Any, List, Tuple, Union
import uuid

import MySQLdb
import MySQLdb.cursors
from MySQLdb import IntegrityError
from datetime import timezone

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, make_response, session, current_app, g,
    send_from_directory          # moved duplicate import here
)

from flask_mysqldb import MySQL

from flask_login import (
    LoginManager, login_user, login_required,
    logout_user, current_user, UserMixin
)

from flask_wtf.csrf import CSRFProtect, generate_csrf

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import BadRequest

from dotenv import load_dotenv

from pathlib import Path

from passforget import passforget

import click

from convert_image import convert_images_if_needed

from nutrition_dashboard import nutrition_bp

# --------------------------------------------------
# LOAD .env (single, clean block)
# --------------------------------------------------
env_path = Path(".env")
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
    print(f"Loaded .env from: {env_path}")
else:
    load_dotenv(override=True)
    print("Loaded .env from current directory")

# Razorpay imports
import razorpay
from razorpay.errors import SignatureVerificationError

# --------------------------------------------------
# APP INIT WITH PRODUCTION CONFIGURATION
# --------------------------------------------------

app = Flask(__name__, instance_relative_config=True)

app.register_blueprint(passforget)

app.register_blueprint(nutrition_bp, url_prefix='/nutrition')

# Handle proxy headers for production (important for HTTPS)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# --------------------------------------------------
# SECRET KEY MANAGEMENT (IMPROVED)
# --------------------------------------------------

SECRET_FILE = os.path.join(app.instance_path, "secret.key")
ENV = os.getenv('FLASK_ENV', 'development').lower()  # Default to development
IS_PRODUCTION = ENV == 'production'

# Ensure instance path exists
os.makedirs(app.instance_path, exist_ok=True)

# Generate or load secret key with proper permissions
if os.getenv('SECRET_KEY'):
    # Use SECRET_KEY from environment if provided
    app.secret_key = os.getenv('SECRET_KEY').encode('utf-8')
    app.logger.info("Using SECRET_KEY from environment")
elif not os.path.exists(SECRET_FILE):
    with open(SECRET_FILE, "wb") as f:
        key = os.urandom(32)
        f.write(key)
    # Set restrictive permissions on secret file (Unix only)
    try:
        os.chmod(SECRET_FILE, 0o600)
    except:
        pass  # Windows compatibility
    app.secret_key = key
    app.logger.info(f"Generated new secret key at {SECRET_FILE}")
else:
    with open(SECRET_FILE, "rb") as f:
        app.secret_key = f.read()
    app.logger.info(f"Loaded secret key from {SECRET_FILE}")

# Additional secret key for signing
app.config['SECRET_KEY_SIGN'] = hashlib.sha256(app.secret_key).hexdigest()

# --------------------------------------------------
# SECURITY SETTINGS (HARDENED) - FIXED FOR NGORK
# --------------------------------------------------

# Determine secure cookie setting from env or auto-detect
SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'auto').lower()

app.config.update(
    # Session security
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=None if SESSION_COOKIE_SECURE == 'auto' else (SESSION_COOKIE_SECURE == 'true'),
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_NAME='session',  # Fixed: removed __Secure- prefix for compatibility
    
    # Remember me cookie security
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SECURE=None if SESSION_COOKIE_SECURE == 'auto' else (SESSION_COOKIE_SECURE == 'true'),
    REMEMBER_COOKIE_DURATION=timedelta(days=14),
    REMEMBER_COOKIE_SAMESITE='Lax',
    REMEMBER_COOKIE_NAME='remember_token',  # Fixed: removed __Secure- prefix
    
    # CSRF protection
    WTF_CSRF_ENABLED=True,
    WTF_CSRF_TIME_LIMIT=3600,  # 1 hour
    WTF_CSRF_SSL_STRICT=IS_PRODUCTION,
    WTF_CSRF_CHECK_DEFAULT=True,
    WTF_CSRF_METHODS=['POST', 'PUT', 'PATCH', 'DELETE'],
    WTF_CSRF_FIELD_NAME='csrf_token',  # Explicitly set field name
    
    # Other security headers
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    SESSION_REFRESH_EACH_REQUEST=True,
    
    # Session settings
    SESSION_PERMANENT=True,
    SESSION_USE_SIGNER=True,
    SESSION_KEY_PREFIX='session:',
    
    # Cookie domain - critical for ngrok/localhost
    SESSION_COOKIE_DOMAIN=None,  # Fixed: set to None for localhost/ngrok
)

# --------------------------------------------------
# DATABASE CONFIG (with connection pooling) - CHANGED TO NUTRITRACK
# --------------------------------------------------

app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
if not app.config['MYSQL_PASSWORD']:
    raise RuntimeError("MYSQL_PASSWORD environment variable is required")
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'nutritrack')  # Changed from nutrition_planner to nutritrack
app.config['MYSQL_PORT'] = int(os.getenv('MYSQL_PORT', 3306))
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

# Add connection pool settings
app.config['MYSQL_POOL_SIZE'] = 10
app.config['MYSQL_POOL_NAME'] = 'mysql_pool'
app.config['MYSQL_AUTOCOMMIT'] = False

mysql = MySQL(app)

# --------------------------------------------------
# REDIS FOR CACHE AND RATE LIMITING (optional)
# --------------------------------------------------

# Try to use Redis for production rate limiting, fall back to memory
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
USE_REDIS = False
RATE_LIMIT_STORAGE = "memory://"

if IS_PRODUCTION:
    try:
        import redis
        redis_client = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        redis_client.ping()  # Test connection
        RATE_LIMIT_STORAGE = REDIS_URL
        USE_REDIS = True
        app.logger.info("Redis connected successfully for rate limiting")
    except Exception as e:
        app.logger.warning(f"Redis unavailable, falling back to memory storage: {e}")
        RATE_LIMIT_STORAGE = "memory://"
else:
    RATE_LIMIT_STORAGE = "memory://"
    app.logger.info("Using memory storage for rate limiting (development mode)")

# --------------------------------------------------
# RAZORPAY CONFIG (with validation)
# --------------------------------------------------

# Pre-computed dummy hash for timing attack prevention
DUMMY_PASSWORD_HASH = generate_password_hash("dummy_constant_string_for_timing_attacks", method='pbkdf2:sha256:150000')

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

# Validate Razorpay config
RAZORPAY_CONFIGURED = bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)

if IS_PRODUCTION and not RAZORPAY_CONFIGURED:
    app.logger.error("Razorpay credentials missing in production! Payment features will be disabled.")
elif not RAZORPAY_CONFIGURED:
    app.logger.warning("Razorpay credentials not configured. Payment features will be disabled.")

app.config["RAZORPAY_KEY_ID"] = RAZORPAY_KEY_ID
app.config["RAZORPAY_KEY_SECRET"] = RAZORPAY_KEY_SECRET
app.config["RAZORPAY_WEBHOOK_SECRET"] = RAZORPAY_WEBHOOK_SECRET

# Initialize Razorpay client if configured
razorpay_client = None
if RAZORPAY_CONFIGURED:
    try:
        razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        app.logger.info("Razorpay client initialized successfully")
    except Exception as e:
        app.logger.error(f"Failed to initialize Razorpay client: {e}")

# --------------------------------------------------
# SUBSCRIPTION PLANS
# --------------------------------------------------

app.config["SUBSCRIPTION_PLANS"] = {
    "premium_monthly": {
        "name": "Premium Monthly",
        "amount": 19900,  # ₹9.99 (in paise)
        "currency": "INR",
        "days": 30,
        "description": "Monthly premium access"
    },
    "premium_yearly": {
        "name": "Premium Yearly",
        "amount": 169900,  # ₹99.99 (in paise)
        "currency": "INR",
        "days": 365,
        "description": "Yearly premium access (save 16%)"
    }
}  

# --------------------------------------------------
# JSON CONFIGURATION WITH CACHING
# --------------------------------------------------

JSON_PATH = os.path.join(app.root_path, "static", "data", "foods.json")
BACKUP_DIR = os.path.join(app.root_path, "static", "data", "backups")
MAX_BACKUPS = 20  # Increased from 10
JSON_CACHE_TIMEOUT = 300  # 5 minutes cache for foods.json

# --------------------------------------------------
# CSRF PROTECTION (with exemptions where needed)
# --------------------------------------------------

csrf = CSRFProtect(app)

# List of routes that should be exempt from CSRF (API endpoints, webhooks)
CSRF_EXEMPT_ROUTES = [
    'razorpay_webhook',
    'razorpay_success',
    'api_get_nutrition_data',  # GET endpoints don't need CSRF
    'foods_json',  # GET endpoint
    'subscription_status',  # GET endpoint
    'meal_planner_data',  # GET endpoint
    'meal_tracker_data',  # GET endpoint
    'api_list_saved_meals',  # GET endpoint
]

# --------------------------------------------------
# RATE LIMITER
# --------------------------------------------------

def get_limiter_key():
    """Custom key function for rate limiter"""
    if current_user.is_authenticated:
        return f"user:{current_user.id}"
    return get_remote_address()

limiter = Limiter(
    key_func=get_limiter_key,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=RATE_LIMIT_STORAGE,
    strategy="fixed-window"  # More reliable than moving window
)

# --------------------------------------------------
# LOGGING (ENHANCED FOR PRODUCTION)
# --------------------------------------------------

if not os.path.exists("logs"):
    os.mkdir("logs")

# Main application log
file_handler = RotatingFileHandler(
    "logs/app.log",
    maxBytes=10485760,  # 10MB
    backupCount=30
)
file_handler.setFormatter(
    logging.Formatter('%(asctime)s %(levelname)s [%(name)s] %(module)s:%(lineno)d - %(message)s')
)
file_handler.setLevel(logging.INFO)

# Error log separate for monitoring
error_handler = RotatingFileHandler(
    "logs/error.log",
    maxBytes=10485760,
    backupCount=30
)
error_handler.setFormatter(
    logging.Formatter('%(asctime)s %(levelname)s [%(name)s] %(module)s:%(lineno)d - %(message)s')
)
error_handler.setLevel(logging.ERROR)

app.logger.addHandler(file_handler)
app.logger.addHandler(error_handler)
app.logger.setLevel(logging.INFO)

# --------------------------------------------------
# LOGIN MANAGER - FIXED SESSION PROTECTION
# --------------------------------------------------

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "info"
login_manager.refresh_view = "login"
login_manager.needs_refresh_message = "Please reauthenticate to access this page."
login_manager.needs_refresh_message_category = "info"
# Fixed: Use basic protection in development, strong in production
if IS_PRODUCTION:
    login_manager.session_protection = "strong"
else:
    login_manager.session_protection = "basic"  # Changed from "strong" for ngrok
login_manager.init_app(app)


# In app.py, after login_manager initialization
@login_manager.request_loader
def load_user_from_request(request):
    """Allow anonymous access to password reset routes"""
    # Check if the requested endpoint is from passforget blueprint
    if request.endpoint and request.endpoint.startswith('passforget.'):
        return None  # Allow anonymous access
    return None

# --------------------------------------------------
# DATABASE CURSOR HELPER (with transaction safety)
# --------------------------------------------------

def get_cursor():
    """Get database cursor with automatic DictCursor"""
    return closing(mysql.connection.cursor(MySQLdb.cursors.DictCursor))

class TransactionContext:
    """Transaction context manager for atomic operations"""
    def __init__(self, connection):
        self.connection = connection
    
    def __enter__(self):
        return self.connection
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.connection.rollback()
            app.logger.error(f"Transaction rolled back: {exc_val}")
            return False
        else:
            try:
                self.connection.commit()
            except Exception as e:
                self.connection.rollback()
                app.logger.error(f"Commit failed, rolled back: {e}")
                raise
        return True

def transaction():
    """Get transaction context manager"""
    return TransactionContext(mysql.connection)


import smtplib
from email.mime.text import MIMEText
import os

def send_email(to_email, subject, body):
    """
    Send email with proper error handling and return boolean status
    """
    smtp_server = os.getenv("MAIL_SERVER")
    smtp_port = int(os.getenv("MAIL_PORT", 587))
    smtp_user = os.getenv("MAIL_USERNAME")
    smtp_password = os.getenv("MAIL_PASSWORD")
    mail_from = os.getenv("MAIL_FROM")

    # Validate configuration
    if not all([smtp_server, smtp_user, smtp_password, mail_from]):
        app.logger.error("Email configuration incomplete. Check MAIL_* environment variables.")
        return False

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = to_email

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        app.logger.info(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        app.logger.error(f"Email sending failed to {to_email}: {e}")
        return False


# --------------------------------------------------
# JSON CACHING SYSTEM (PERFORMANCE IMPROVEMENT)
# --------------------------------------------------

# FIX: Cache foods.json to prevent repeated disk I/O
_foods_cache = None
_foods_cache_timestamp = 0

def invalidate_foods_cache():
    """Invalidate the foods cache (call after updates)"""
    global _foods_cache, _foods_cache_timestamp
    _foods_cache = None
    _foods_cache_timestamp = 0

def _list_foods_backups():
    """Return sorted list of backup file paths (oldest -> newest)."""
    if not os.path.isdir(BACKUP_DIR):
        return []
    try:
        files = []
        for name in os.listdir(BACKUP_DIR):
            if name.startswith("foods_") and name.endswith(".json"):
                files.append(os.path.join(BACKUP_DIR, name))
        return sorted(files)
    except Exception as e:
        app.logger.error(f"Error listing backups: {e}")
        return []

def backup_foods_json():
    """Create timestamped backup of foods.json with validation"""
    try:
        if not os.path.exists(JSON_PATH):
            return False
        
        # Validate current JSON before backup
        try:
            with open(JSON_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    app.logger.error("Current foods.json is not a valid dict, skipping backup")
                    return False
        except Exception as e:
            app.logger.error(f"Current foods.json is invalid, skipping backup: {e}")
            return False
        
        os.makedirs(BACKUP_DIR, exist_ok=True)

        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_name = f"foods_{ts}.json"
        backup_path = os.path.join(BACKUP_DIR, backup_name)

        shutil.copy2(JSON_PATH, backup_path)
        
        # Prune old backups
        backups = _list_foods_backups()
        if len(backups) > MAX_BACKUPS:
            for old in backups[:len(backups) - MAX_BACKUPS]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        
        return True
    except Exception as e:
        app.logger.error(f"Failed to backup foods.json: {e}")
        return False

def restore_foods_json_from_backup():
    """Try to restore foods.json from the latest backup."""
    try:
        backups = _list_foods_backups()
        if not backups:
            return False
        latest = backups[-1]
        os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
        shutil.copy2(latest, JSON_PATH)
        app.logger.warning(f"foods.json restored from backup: {latest}")
        invalidate_foods_cache()
        return True
    except Exception as e:
        app.logger.error(f"Failed to restore foods.json from backup: {e}")
        return False

# PERFORMANCE IMPROVEMENT: Cached JSON loading
def load_foods_json(force_reload=False):
    """
    Load foods.json with caching to prevent repeated disk I/O.
    Uses time-based cache invalidation.
    """
    global _foods_cache, _foods_cache_timestamp
    
    now = time.time()
    
    # Return cached version if still valid
    if not force_reload and _foods_cache is not None:
        if now - _foods_cache_timestamp < JSON_CACHE_TIMEOUT:
            return _foods_cache.copy()  # Return copy to prevent mutation
    
    # Try current file
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _foods_cache = data
                    _foods_cache_timestamp = now
                    return data.copy()
        except Exception as e:
            app.logger.error(f"Error loading foods.json, will try backup: {e}")

    # Try restore from backup
    if restore_foods_json_from_backup():
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _foods_cache = data
                    _foods_cache_timestamp = now
                    return data.copy()
        except Exception as e:
            app.logger.error(f"Error loading restored foods.json: {e}")

    # Last fallback: rebuild from DB
    try:
        if foods_to_jsonfile(force=True):
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _foods_cache = data
                    _foods_cache_timestamp = now
                    return data.copy()
    except Exception as e:
        app.logger.error(f"Failed to rebuild foods.json from DB: {e}")
    
    return {}

# --------------------------------------------------
# USER MODEL (IMPROVED)
# --------------------------------------------------

def ensure_utc(dt):
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

class User(UserMixin):
    """Enhanced User model with better property handling"""
    
    def __init__(
        self,
        id: int,
        name: str,
        email: str,
        membership: str,
        is_admin: bool,
        subscription_id: Optional[str] = None,
        subscription_status: Optional[str] = None,
        subscription_end: Optional[datetime] = None,
        grace_period_end: Optional[datetime] = None,
        razorpay_customer_id: Optional[str] = None,
        razorpay_subscription_id: Optional[str] = None
    ):
        self.id = id
        self.name = name
        self.email = email
        self.membership = membership
        self.is_admin = bool(is_admin)
        self.subscription_id = subscription_id
        self.subscription_status = subscription_status
        self.subscription_end = subscription_end
        self.grace_period_end = grace_period_end
        self.razorpay_customer_id = razorpay_customer_id
        self.razorpay_subscription_id = razorpay_subscription_id

    @property
    def is_premium(self) -> bool:
        """Check if user has active premium access with expiration check"""
        if self.is_admin:
            return True

        if self.membership != "Premium":
            return False

        if self.subscription_status not in ["active", "trialing"]:
            return False

        if self.subscription_end:
            end = self.subscription_end.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > end:
                return False        

        return True
    
    @property
    def subscription_expired(self) -> bool:
        if not self.subscription_end:
            return False
        end = self.subscription_end.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > end
    
    def get_id(self):
        """Override to ensure string ID"""
        return str(self.id)

# --------------------------------------------------
# LOAD USER (IMPROVED WITH DEBUGGING)
# --------------------------------------------------

@login_manager.user_loader
def load_user(user_id: str):
    """Load user from database with all fields"""
    # Add debugging for ngrok issues
    app.logger.debug(f"Loading user {user_id} from session")
    app.logger.debug(f"Request scheme: {request.scheme}")
    app.logger.debug(f"X-Forwarded-Proto: {request.headers.get('X-Forwarded-Proto')}")
    app.logger.debug(f"Session contents: {dict(session)}")
    
    try:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id, name, email, membership, is_admin,
                       razorpay_subscription_id,
                       razorpay_subscription_status,
                       subscription_end_date,
                       grace_period_end,
                       razorpay_customer_id
                FROM users
                WHERE id = %s
                """,
                (user_id,)
            )
            row = cur.fetchone()

        if row:
            app.logger.debug(f"User {user_id} loaded successfully")
            return User(
                row["id"],
                row["name"],
                row["email"],
                row["membership"],
                row["is_admin"],
                row["razorpay_subscription_id"],
                row["razorpay_subscription_status"],
                row["subscription_end_date"],
                row["grace_period_end"],
                row["razorpay_customer_id"]
            )
        else:
            app.logger.debug(f"User {user_id} not found in database")
    except Exception as e:
        app.logger.error(f"Error loading user {user_id}: {e}")
    
    return None

# --------------------------------------------------
# ADMIN DECORATOR (IMPROVED)
# --------------------------------------------------

def admin_required(f):
    """Decorator for routes that require admin access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        
        if not current_user.is_admin:
            flash("You don't have permission to access this page.", "danger")
            return redirect(url_for('profile'))
        
        return f(*args, **kwargs)
    return decorated_function

# --------------------------------------------------
# PREMIUM CHECK DECORATOR (IMPROVED)
# --------------------------------------------------

def premium_required(f):
    """Decorator for routes that require premium access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        
        # Check premium status (this will auto-downgrade if expired)
        if not current_user.is_premium:
            # Auto-downgrade if needed
            if current_user.membership == 'Premium' and current_user.subscription_expired:
                try:
                    with transaction():
                        with get_cursor() as cur:
                            cur.execute("""
                                UPDATE users 
                                SET membership = 'Free', 
                                    razorpay_subscription_status = 'expired'
                                WHERE id = %s
                            """, (current_user.id,))
                    flash("Your premium subscription has expired. Please renew to continue.", "warning")
                except Exception as e:
                    app.logger.error(f"Error auto-downgrading user {current_user.id}: {e}")
            
            flash("This feature requires an active premium subscription.", "warning")
            return redirect(url_for('plans'))
        
        return f(*args, **kwargs)
    return decorated_function

# --------------------------------------------------
# AFTER REQUEST HELPER
# --------------------------------------------------

from flask import after_this_request

from urllib.parse import urlparse, urljoin

def is_safe_url(target):
    """Check if redirect target is safe (prevents open redirect vulnerabilities)"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

# --------------------------------------------------
# BEFORE REQUEST - SECURITY HEADERS & DYNAMIC COOKIE SECURE
# --------------------------------------------------

@app.before_request
def before_request():
    """Setup before each request"""
    # Make session permanent
    session.permanent = True
    
    # Dynamically set secure cookie based on connection if in auto mode
    if app.config['SESSION_COOKIE_SECURE'] is None:
        # Auto-detect HTTPS (check both Flask's is_secure and X-Forwarded-Proto)
        is_secure = request.is_secure or request.headers.get('X-Forwarded-Proto', 'http') == 'https'
        # Set the secure flag for this request only by modifying session cookie options
        app.logger.debug(f"Dynamic secure cookie set to: {is_secure} for request")
    
    # No manual CSRF token handling - let Flask-WTF handle it

# --------------------------------------------------
# AFTER REQUEST - SECURITY HEADERS
# --------------------------------------------------

@app.after_request
def add_security_headers(response):
    """Add security headers to all responses"""
    # Prevent caching of authenticated pages
    if request.endpoint in ['profile', 'admin', 'meal_planner', 'meal_tracker', 'calorie_tracker', 'nutrition_analyzer', 'meal_entry', 'nutrition_report']:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    
    if IS_PRODUCTION:
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Basic Content Security Policy
        csp = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://code.jquery.com https://checkout.razorpay.com; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "connect-src 'self'"
        )
        response.headers['Content-Security-Policy'] = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
    "https://cdn.jsdelivr.net "
    "https://code.jquery.com "
    "https://checkout.razorpay.com "
    "https://static.cloudflareinsights.com; "
    
    "style-src 'self' 'unsafe-inline' "
    "https://cdn.jsdelivr.net "
    "https://fonts.googleapis.com; "

    "font-src 'self' https://fonts.gstatic.com data:; "

    "img-src 'self' data: https:; "

    "frame-src 'self' https://checkout.razorpay.com; "

    "connect-src 'self' "
    "https://api.razorpay.com "
    "https://checkout.razorpay.com; "
)
    
    return response

# --------------------------------------------------
# DATABASE SCHEMA UPDATES (IMPROVED)
# --------------------------------------------------

def init_database():
    """Initialize database schema with proper error handling"""
    try:
        with transaction():
            with get_cursor() as cur:
                # Check if users table exists
                cur.execute("SHOW TABLES LIKE 'users'")
                if not cur.fetchone():
                    # Create users table
                    cur.execute("""
                        CREATE TABLE users (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            name VARCHAR(100) NOT NULL,
                            email VARCHAR(100) UNIQUE NOT NULL,
                            password VARCHAR(255) NOT NULL,
                            membership VARCHAR(50) DEFAULT 'Free',
                            is_admin BOOLEAN DEFAULT FALSE,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            INDEX idx_email (email)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """)
                    app.logger.info("Created users table")
                
                # Check and add Razorpay subscription columns to users table
                columns_to_check = [
                    ('razorpay_customer_id', "VARCHAR(255)"),
                    ('razorpay_subscription_id', "VARCHAR(255)"),
                    ('razorpay_subscription_status', "VARCHAR(50) DEFAULT 'inactive'"),
                    ('subscription_end_date', "DATETIME"),
                    ('grace_period_end', "DATETIME"),
                    ('razorpay_order_id', "VARCHAR(255)"),
                    ('razorpay_payment_id', "VARCHAR(255)"),
                ]
                
                for col_name, col_def in columns_to_check:
                    cur.execute("""
                        SELECT COUNT(*) FROM information_schema.columns 
                        WHERE table_name = 'users' AND column_name = %s
                    """, (col_name,))
                    if cur.fetchone()['COUNT(*)'] == 0:
                        cur.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
                        app.logger.info(f"Added column {col_name} to users table")

                # Create foods table if not exists
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS foods (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255) UNIQUE NOT NULL,
                        calories FLOAT DEFAULT 0,
                        protein FLOAT DEFAULT 0,
                        carbohydrates FLOAT DEFAULT 0,
                        fats FLOAT DEFAULT 0,
                        saturated_fats FLOAT DEFAULT 0,
                        omega_3 FLOAT DEFAULT 0,
                        omega_6 FLOAT DEFAULT 0,
                        fiber FLOAT DEFAULT 0,
                        water FLOAT DEFAULT 0,
                        vitamins TEXT,
                        minerals TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_name (name)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)

                # Create Razorpay transactions table with improved schema
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS razorpay_transactions (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        order_id VARCHAR(100) UNIQUE NOT NULL,
                        payment_id VARCHAR(100),
                        user_id INT NOT NULL,
                        amount DECIMAL(10,2),
                        plan_type VARCHAR(50),
                        status VARCHAR(50) DEFAULT 'created',
                        payment_response JSON,
                        webhook_response JSON,
                        ip_address VARCHAR(45),
                        user_agent TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        INDEX idx_order_id (order_id),
                        INDEX idx_payment_id (payment_id),
                        INDEX idx_user_id (user_id),
                        INDEX idx_status (status),
                        INDEX idx_created (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                
                # Create payment history table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS payment_history (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        razorpay_payment_id VARCHAR(255),
                        razorpay_order_id VARCHAR(255),
                        amount DECIMAL(10,2),
                        currency VARCHAR(3),
                        status VARCHAR(50),
                        payment_method VARCHAR(50),
                        failure_reason TEXT,
                        metadata JSON,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        INDEX idx_user_id (user_id),
                        INDEX idx_payment_id (razorpay_payment_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                
                # Create meal_logs table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS meal_logs (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        date DATE NOT NULL,
                        meal_type ENUM('Breakfast','Lunch','Dinner','Snacks') NOT NULL,
                        food_name VARCHAR(255) NOT NULL,
                        calories FLOAT DEFAULT 0,
                        protein FLOAT DEFAULT 0,
                        carbs FLOAT DEFAULT 0,
                        fats FLOAT DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        INDEX idx_user_date (user_id, date)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)

                # Create meals table (saved meals header)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS meals (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        meal_type VARCHAR(50) NOT NULL,
                        date DATE NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        INDEX idx_user_date (user_id, date)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)

                # Create meal_items table (saved meal details)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS meal_items (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        meal_id INT NOT NULL,
                        food_name VARCHAR(255) NOT NULL,
                        weight FLOAT DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (meal_id) REFERENCES meals(id) ON DELETE CASCADE,
                        INDEX idx_meal_id (meal_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                
                app.logger.info("Database schema initialized successfully")
                
    except Exception as e:
        app.logger.error(f"Database initialization error: {e}")
        raise

# Initialize database on startup
with app.app_context():
    try:
        init_database()
    except Exception as e:
        app.logger.error(f"Failed to initialize database: {e}")

# --------------------------------------------------
# CONVERT DB TO JSON (IMPROVED)
# --------------------------------------------------

def foods_to_jsonfile(force=False) -> bool:
    """
    Convert foods table into static/data/foods.json with atomic write + fsync.
    Returns True if successful, False otherwise.
    """
    if not force and os.path.exists(JSON_PATH):
        return True

    try:
        os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)

        with get_cursor() as cur:
            cur.execute("""
                SELECT name, calories, protein, carbohydrates, fats, saturated_fats,
                       omega_3, omega_6, fiber, water, vitamins, minerals
                FROM foods
            """)
            rows = cur.fetchall()

        def safe_parse(text):
            if not text:
                return {}
            if isinstance(text, dict):
                return text
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass
            # Fallback to comma parsing
            result = {}
            if isinstance(text, str):
                for part in text.split(","):
                    if ":" in part:
                        k, v = part.split(":", 1)
                        result[k.strip()] = v.strip()
            return result

        foods = {}
        for r in rows:
            name = r["name"].strip().lower()
            if not name:
                continue
                
            vitamins = safe_parse(r["vitamins"])
            minerals = safe_parse(r["minerals"])
            
            foods[name] = {
                "macronutrients": {
                    "calories": float(r.get("calories") or 0),
                    "protein": float(r.get("protein") or 0),
                    "carbohydrate": float(r.get("carbohydrates") or 0),
                    "total_fats": float(r.get("fats") or 0),
                    "saturated_fats": float(r.get("saturated_fats") or 0),
                    "omega_3": float(r.get("omega_3") or 0),
                    "omega_6": float(r.get("omega_6") or 0),
                    "fiber": float(r.get("fiber") or 0),
                    "water": float(r.get("water") or 0),
                },
                "vitamins": vitamins,
                "minerals_and_trace": minerals,
            }

        # Atomic write
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix="foods_", suffix=".json", dir=os.path.dirname(JSON_PATH)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(foods, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            
            shutil.move(tmp_path, JSON_PATH)

            # Sync directory (skip on Windows)
            try:
                dir_fd = os.open(os.path.dirname(JSON_PATH), os.O_DIRECTORY)
                os.fsync(dir_fd)
                os.close(dir_fd)
            except (AttributeError, OSError):
                pass  # Directory syncing not supported on Windows
            
            # Invalidate cache
            invalidate_foods_cache()
            return True
            
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
                
    except Exception as e:
        app.logger.error(f"foods_to_jsonfile failed: {e}")
        return False

# --------------------------------------------------
# SAFE UPDATE FOOD JSON (IMPROVED)
# --------------------------------------------------

def safe_update_food_json(new_food: Dict[str, Any]) -> bool:
    """
    Safely merge a single food into foods.json with atomic write.
    Returns True if successful.
    """
    try:
        os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)

        # Start from current JSON master
        foods = load_foods_json(force_reload=True)
        if not isinstance(foods, dict):
            foods = {}

        def to_float(v):
            try:
                return float(v or 0)
            except Exception:
                return 0.0

        key = (new_food.get("name") or "").strip().lower()
        if not key:
            return False

        # Parse vitamins/minerals
        vitamins_raw = new_food.get("vitamins")
        minerals_raw = new_food.get("minerals")

        if isinstance(vitamins_raw, str) and vitamins_raw.strip():
            try:
                vitamins = json.loads(vitamins_raw)
                if not isinstance(vitamins, dict):
                    vitamins = {}
            except Exception:
                vitamins = {}
        else:
            vitamins = vitamins_raw or {}

        if isinstance(minerals_raw, str) and minerals_raw.strip():
            try:
                minerals = json.loads(minerals_raw)
                if not isinstance(minerals, dict):
                    minerals = {}
            except Exception:
                minerals = {}
        else:
            minerals = minerals_raw or {}

        foods[key] = {
            "macronutrients": {
                "calories": to_float(new_food.get("calories")),
                "protein": to_float(new_food.get("protein")),
                "carbohydrate": to_float(new_food.get("carbohydrates")),
                "total_fats": to_float(new_food.get("fats")),
                "saturated_fats": to_float(new_food.get("saturated_fats")),
                "omega_3": to_float(new_food.get("omega_3")),
                "omega_6": to_float(new_food.get("omega_6")),
                "fiber": to_float(new_food.get("fiber")),
                "water": to_float(new_food.get("water")),
            },
            "vitamins": vitamins,
            "minerals_and_trace": minerals,
        }

        # Create backup before write
        backup_foods_json()

        # Atomic write
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix="foods_", suffix=".json", dir=os.path.dirname(JSON_PATH)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(foods, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            
            shutil.move(tmp_path, JSON_PATH)

            # Sync directory (skip on Windows)
            try:
                dir_fd = os.open(os.path.dirname(JSON_PATH), os.O_DIRECTORY)
                os.fsync(dir_fd)
                os.close(dir_fd)
            except (AttributeError, OSError):
                pass  # Directory syncing not supported on Windows
            
            # Invalidate cache
            invalidate_foods_cache()
            return True
            
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
                
    except Exception as e:
        app.logger.error(f"safe_update_food_json failed: {e}")
        return False

# --------------------------------------------------
# RAZORPAY HELPER FUNCTIONS
# --------------------------------------------------

def is_razorpay_configured() -> bool:
    """Check if Razorpay is properly configured"""
    return bool(razorpay_client and app.config.get('RAZORPAY_KEY_ID') and app.config.get('RAZORPAY_KEY_SECRET'))

def create_razorpay_order(amount: int, currency: str = "INR", receipt: str = None) -> Dict:
    """Create a Razorpay order"""
    if not razorpay_client:
        raise Exception("Razorpay client not configured")
    
    data = {
        "amount": amount,
        "currency": currency,
        "receipt": receipt or str(uuid.uuid4()),
        "payment_capture": 1  # Auto-capture payment
    }
    
    return razorpay_client.order.create(data)

def verify_razorpay_payment(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify Razorpay payment signature"""
    if not razorpay_client:
        raise Exception("Razorpay client not configured")
    
    params_dict = {
        'razorpay_order_id': order_id,
        'razorpay_payment_id': payment_id,
        'razorpay_signature': signature
    }
    
    try:
        razorpay_client.utility.verify_payment_signature(params_dict)
        return True
    except SignatureVerificationError:
        return False

# --------------------------------------------------
# CSRF PROTECTION DECORATOR (using Flask-WTF's built-in)
# --------------------------------------------------

# Using @csrf.exempt directly from Flask-WTF
# No custom decorator needed

# --------------------------------------------------
# PUBLIC ROUTES
# --------------------------------------------------

@app.route("/testdb")
def testdb():
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT 1")
        return "DB Connected"
    except Exception as e:
        return str(e)


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route('/how-it-works')
def how_it_works():
    return render_template('how_it_works.html')

@app.route('/legal')
def legal():
    return render_template('legal.html')

@app.route('/robots.txt')
def robots():
    return send_from_directory('static', 'robots.txt')

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('static', 'sitemap.xml')

@app.route('/nutrition-info')
def nutrition_info():
    return render_template('nutrition_system_info.html')

# --------------------------------------------------
# AUTH ROUTES (IMPROVED) - FIXED REDIRECTS
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        
        # Validation
        if len(name) < 2 or len(name) > 50:
            flash("Name must be between 2 and 50 characters", "danger")
            return render_template("register.html")
        if not email or '@' not in email or len(email) > 100:
            flash("Valid email required", "danger")
            return render_template("register.html")
        if len(password) < 8:
            flash("Password must be at least 8 characters", "danger")
            return render_template("register.html")
        
        password_hash = generate_password_hash(password, method='pbkdf2:sha256:150000')
        
        try:
            # Insert and commit immediately
            with get_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users(name, email, password, membership, is_admin)
                    VALUES(%s, %s, %s, 'Free', 0)
                    """,
                    (name, email, password_hash)
                )
                user_id = cur.lastrowid
                mysql.connection.commit()   # commit the insert
            
            # Fetch the user by ID (separate cursor, no transaction)
            with get_cursor() as cur:
                cur.execute(
                    "SELECT id, name, email, membership, is_admin FROM users WHERE id = %s",
                    (user_id,)
                )
                row = cur.fetchone()
        except IntegrityError:
            flash("Email already registered", "warning")
            return render_template("register.html")
        except Exception as e:
            app.logger.error(f"Registration error: {e}")
            flash("Registration failed. Please try again.", "danger")
            return render_template("register.html")

        if row:
            user = User(
                id=row["id"],
                name=row["name"],
                email=row["email"],
                membership=row["membership"],
                is_admin=bool(row["is_admin"]),
                subscription_id=None,
                subscription_status=None,
                subscription_end=None,
                grace_period_end=None,
                razorpay_customer_id=None,
                razorpay_subscription_id=None
            )
            login_user(user, remember=True)
            app.logger.info(f"New user registered: {email}")
            # Simple redirect – no _external, no _scheme
            return redirect(url_for("plans"))
        else:
            flash("Registration failed. Please try again.", "danger")
            return render_template("register.html")
    
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember", False) == "on"
        
        if not email or not password:
            flash("Email and password required", "danger")
            return render_template("login.html")
        
        try:
            with get_cursor() as cur:
                cur.execute(
                    """SELECT id, name, email, password, membership, is_admin,
                              razorpay_subscription_id, razorpay_subscription_status, 
                              subscription_end_date, grace_period_end,
                              razorpay_customer_id
                       FROM users WHERE email = %s""",
                    (email,)
                )
                row = cur.fetchone()
        except Exception as e:
            app.logger.error(f"Login query error: {e}")
            flash("Login failed. Please try again.", "danger")
            return render_template("login.html")
        
        # Constant time check to prevent timing attacks
        if row:
            password_valid = check_password_hash(row["password"], password)
        else:
            # Dummy hash check to maintain constant time
            check_password_hash(DUMMY_PASSWORD_HASH, "dummy")
            password_valid = False
        
        time.sleep(0.05)  # Additional constant delay
        
        if password_valid:
            user = User(
                row["id"],
                row["name"],
                row["email"],
                row["membership"],
                row["is_admin"],
                row["razorpay_subscription_id"],
                row["razorpay_subscription_status"],
                row["subscription_end_date"],
                row["grace_period_end"],
                row["razorpay_customer_id"]
            )
            
            # Log in the user
            login_user(user, remember=remember)
            app.logger.info(f"User logged in: {email}")
            
            # Force session to be saved
            session.permanent = True
            session.modified = True
            
            # Get current scheme for redirects
            scheme = request.scheme
            
            # Handle next parameter
            next_page = request.args.get('next')
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            
            # Determine redirect based on user type
            if user.is_admin:
                return redirect(url_for('admin', _external=True, _scheme=scheme))
            else:
                return redirect(url_for('profile', _external=True, _scheme=scheme))
        
        flash("Incorrect email or password", "danger")
        
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    app.logger.info(f"User logged out: {current_user.email}")
    logout_user()
    session.clear()
    # Clear session cookie
    response = make_response(redirect(url_for("login")))
    response.delete_cookie(app.config['SESSION_COOKIE_NAME'])
    return response

# --------------------------------------------------
# PROFILE / PLANS
# --------------------------------------------------

@app.route("/profile")
@login_required
def profile():
    # Verify user is actually authenticated
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    return render_template("profile.html")

@app.route("/plans")
@login_required
def plans():
    """Show subscription plans with user's current plan highlighted"""
    plans = app.config['SUBSCRIPTION_PLANS']
    razorpay_configured = is_razorpay_configured()
    razorpay_key_id = app.config['RAZORPAY_KEY_ID'] if razorpay_configured else None

    # Default to free
    user_plan = 'free'

    if current_user.is_authenticated:
        if current_user.membership == 'Free':
            user_plan = 'free'
        else:
            # Premium member – try to get actual plan type from last successful transaction
            try:
                with get_cursor() as cur:
                    cur.execute("""
                        SELECT plan_type FROM razorpay_transactions
                        WHERE user_id = %s AND status = 'paid'
                        ORDER BY id DESC LIMIT 1
                    """, (current_user.id,))
                    row = cur.fetchone()
                    if row and row['plan_type'] in ('monthly', 'yearly'):
                        user_plan = row['plan_type']
                    else:
                        # Admin‑upgraded user (no transaction) – default to yearly
                        user_plan = 'yearly'
            except Exception as e:
                app.logger.error(f"Error fetching user plan: {e}")
                user_plan = 'yearly'  # safe fallback

    return render_template("plans.html",
                          plans=plans,
                          razorpay_configured=razorpay_configured,
                          razorpay_key_id=razorpay_key_id,
                          user_plan=user_plan)

# --------------------------------------------------
# RAZORPAY PAYMENT ROUTES
# --------------------------------------------------

@app.route("/razorpay/create-order", methods=["POST"])
@login_required
@limiter.limit("5 per minute")
def razorpay_create_order():
    """Create Razorpay order for subscription"""
    # Check if Razorpay is configured
    if not is_razorpay_configured():
        app.logger.error("Razorpay not configured but create-order called")
        return jsonify({'error': 'Payment system not configured'}), 503
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request data'}), 400
            
        plan_type = data.get('plan_type')
        
        # Get plan details
        plans = app.config['SUBSCRIPTION_PLANS']
        plan_key = f'premium_{plan_type}'
        plan = plans.get(plan_key)
        
        if not plan:
            return jsonify({'error': 'Invalid plan'}), 400
        
        # Generate receipt ID
        receipt = f"rcpt_{current_user.id}_{int(time.time())}"
        
        # Create Razorpay order
        order_data = create_razorpay_order(
            amount=plan['amount'],
            currency=plan['currency'],
            receipt=receipt
        )
        
        # Store order in database
        with transaction():
            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO razorpay_transactions 
                    (order_id, user_id, amount, plan_type, status, ip_address, user_agent, created_at)
                    VALUES (%s, %s, %s, %s, 'created', %s, %s, NOW())
                """, (
                    order_data['id'],
                    current_user.id,
                    plan['amount'],
                    plan_type,
                    request.remote_addr,
                    request.user_agent.string[:255] if request.user_agent else None
                ))
                
                # Store order_id in users table for reference
                cur.execute("""
                    UPDATE users SET razorpay_order_id = %s WHERE id = %s
                """, (order_data['id'], current_user.id))
        
        app.logger.info(f"Razorpay order created: {order_data['id']} for user {current_user.id}")
        
        return jsonify({
            'status': 'success',
            'order_id': order_data['id'],
            'amount': order_data['amount'],
            'currency': order_data['currency'],
            'key_id': app.config['RAZORPAY_KEY_ID'],
            'name': 'NutriNova Premium',
            'description': plan['name'],
            'prefill': {
                'name': current_user.name,
                'email': current_user.email
            },
            'theme': {
                'color': '#4CAF50'
            }
        })
        
    except Exception as e:
        app.logger.error(f"Razorpay order creation error: {e}")
        return jsonify({'error': 'Failed to create order'}), 500

@app.route("/razorpay/success", methods=["POST"])
@login_required
@csrf.exempt
@limiter.limit("10 per minute")
def razorpay_success():
    """Handle successful payment"""
    # Check if Razorpay is configured
    if not is_razorpay_configured():
        app.logger.error("Razorpay not configured but success callback received")
        flash("Payment system not configured", "danger")
        return redirect(url_for('plans'))
    
    try:
        # Get response parameters
        razorpay_payment_id = request.form.get('razorpay_payment_id')
        razorpay_order_id = request.form.get('razorpay_order_id')
        razorpay_signature = request.form.get('razorpay_signature')
        
        if not all([razorpay_payment_id, razorpay_order_id, razorpay_signature]):
            app.logger.error("Razorpay success: Missing required fields")
            flash("Invalid payment response", "danger")
            return redirect(url_for('plans'))
        
        # Verify signature (SECURITY)
        if not verify_razorpay_payment(razorpay_order_id, razorpay_payment_id, razorpay_signature):
            app.logger.error(f"Signature verification failed for order {razorpay_order_id}")
            flash("Payment verification failed", "danger")
            return redirect(url_for('plans'))
        
        # Use transaction to prevent race conditions
        with transaction():
            with get_cursor() as cur:
                # Lock the transaction row
                cur.execute(
                    "SELECT status, user_id, plan_type FROM razorpay_transactions WHERE order_id = %s FOR UPDATE",
                    (razorpay_order_id,)
                )
                trans = cur.fetchone()
                
                if not trans:
                    app.logger.error(f"Transaction not found: {razorpay_order_id}")
                    flash("Transaction not found", "danger")
                    return redirect(url_for('plans'))
                
                # Verify the transaction belongs to the current user
                if trans['user_id'] != current_user.id:
                    app.logger.warning(f"User {current_user.id} attempted to access transaction {razorpay_order_id} belonging to user {trans['user_id']}")
                    flash("Unauthorized access to payment transaction", "danger")
                    return redirect(url_for('plans'))
                
                if trans['status'] == 'paid':
                    app.logger.warning(f"Duplicate success callback for order {razorpay_order_id}")
                    flash("Payment already processed", "info")
                    return redirect(url_for('profile'))
                
                # Update transaction
                cur.execute("""
                    UPDATE razorpay_transactions 
                    SET status = 'paid', payment_id = %s, payment_response = %s 
                    WHERE order_id = %s
                """, (razorpay_payment_id, json.dumps(request.form.to_dict()), razorpay_order_id))
                
                # Get user and plan details
                user_id = trans['user_id']
                plan_type = trans['plan_type']
                
                if user_id and plan_type:
                    # Calculate subscription end date
                    plans = app.config['SUBSCRIPTION_PLANS']
                    plan = plans.get(f'premium_{plan_type}')
                    days = plan['days'] if plan else 30
                    end_date = datetime.now(timezone.utc) + timedelta(days=days)
                    
                    # Update user
                    cur.execute("""
                        UPDATE users 
                        SET membership = 'Premium',
                            razorpay_subscription_status = 'active',
                            razorpay_subscription_id = %s,
                            razorpay_payment_id = %s,
                            subscription_end_date = %s
                        WHERE id = %s
                    """, (razorpay_order_id, razorpay_payment_id, end_date, user_id))
                    
                    # Record in payment history
                    cur.execute("""
                        INSERT INTO payment_history 
                        (user_id, razorpay_payment_id, razorpay_order_id, amount, currency, status, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        user_id,
                        razorpay_payment_id,
                        razorpay_order_id,
                        float(plan['amount']) / 100,
                        'INR',
                        'success',
                        json.dumps({
                            'payment_id': razorpay_payment_id,
                            'order_id': razorpay_order_id
                        })
                    ))
        
        app.logger.info(f"Payment successful: order {razorpay_order_id}, payment {razorpay_payment_id} for user {user_id}")
        flash("🎉 Payment successful! Your premium subscription is now active.", "success")
        return redirect(url_for('profile'))
        
    except Exception as e:
        app.logger.error(f"Razorpay success error: {e}")
        flash("Payment processing error", "danger")
        return redirect(url_for('plans'))

@app.route("/razorpay/failure", methods=["POST"])
@csrf.exempt
def razorpay_failure():
    """Handle failed payment"""
    # Check if Razorpay is configured
    if not is_razorpay_configured():
        app.logger.error("Razorpay not configured but failure callback received")
        flash("Payment system not configured", "danger")
        return redirect(url_for('plans'))
    
    try:
        razorpay_order_id = request.form.get('razorpay_order_id')
        error_code = request.form.get('error[code]', 'unknown')
        error_description = request.form.get('error[description]', 'Payment failed')
        
        if not razorpay_order_id:
            app.logger.error("Razorpay failure: Missing order_id")
            flash("Invalid payment response", "danger")
            return redirect(url_for('plans'))
        
        # Update transaction status
        with transaction():
            with get_cursor() as cur:
                cur.execute("""
                    UPDATE razorpay_transactions 
                    SET status = 'failed' 
                    WHERE order_id = %s
                """, (razorpay_order_id,))
        
        app.logger.info(f"Payment failed: order {razorpay_order_id}, error: {error_code}")
        flash(f"Payment failed: {error_description}", "danger")
        return redirect(url_for('plans'))
        
    except Exception as e:
        app.logger.error(f"Razorpay failure error: {e}")
        flash("Error processing payment failure", "danger")
        return redirect(url_for('plans'))

@app.route("/razorpay/webhook", methods=["POST"])
@csrf.exempt
@limiter.limit("20 per minute")
def razorpay_webhook():
    """Handle Razorpay webhook for payment updates"""
    # Check if Razorpay is configured
    if not is_razorpay_configured():
        app.logger.error("Razorpay not configured but webhook received")
        return jsonify({"status": "not configured"}), 503
    
    try:
        # Verify webhook signature
        webhook_secret = app.config.get('RAZORPAY_WEBHOOK_SECRET')
        if webhook_secret:
            signature = request.headers.get('X-Razorpay-Signature')
            if not signature:
                app.logger.warning("Webhook missing signature")
                return jsonify({"status": "unauthorized"}), 401
            
            # Verify signature
            try:
                razorpay_client.utility.verify_webhook_signature(
                    request.get_data(),
                    signature,
                    webhook_secret
                )
            except Exception as e:
                app.logger.warning(f"Webhook signature verification failed: {e}")
                return jsonify({"status": "unauthorized"}), 401
        
        # Get webhook data
        data = request.get_json()
        if not data:
            return jsonify({"status": "invalid"}), 400
        
        event = data.get('event')
        payload = data.get('payload', {})
        
        app.logger.info(f"Webhook received: {event}")
        
        # Handle different event types
        if event == 'payment.captured':
            payment = payload.get('payment', {}).get('entity', {})
            order_id = payment.get('order_id')
            payment_id = payment.get('id')
            
            if order_id and payment_id:
                with transaction():
                    with get_cursor() as cur:
                        # Update transaction
                        cur.execute("""
                            UPDATE razorpay_transactions 
                            SET status = 'paid', 
                                payment_id = %s,
                                webhook_response = %s 
                            WHERE order_id = %s AND status != 'paid'
                        """, (payment_id, json.dumps(data), order_id))
                        
                        if cur.rowcount > 0:
                            # Get transaction details
                            cur.execute(
                                "SELECT user_id, plan_type FROM razorpay_transactions WHERE order_id = %s",
                                (order_id,)
                            )
                            trans = cur.fetchone()
                            
                            if trans:
                                user_id = trans['user_id']
                                plan_type = trans['plan_type']
                                
                                # Get plan details
                                plans = app.config['SUBSCRIPTION_PLANS']
                                plan = plans.get(f'premium_{plan_type}')
                                days = plan['days'] if plan else 30
                                end_date = datetime.now(timezone.utc) + timedelta(days=days)
                                
                                # Update user
                                cur.execute("""
                                    UPDATE users 
                                    SET membership = 'Premium',
                                        razorpay_subscription_status = 'active',
                                        razorpay_subscription_id = %s,
                                        razorpay_payment_id = %s,
                                        subscription_end_date = %s
                                    WHERE id = %s
                                """, (order_id, payment_id, end_date, user_id))
                                
                                app.logger.info(f"Webhook processed: order {order_id} for user {user_id}")
        
        return jsonify({'status': 'success'}), 200
        
    except Exception as e:
        app.logger.error(f"Webhook error: {e}")
        return jsonify({'status': 'error'}), 500

# --------------------------------------------------
# SUBSCRIPTION MANAGEMENT
# --------------------------------------------------

@app.route("/subscription-status")
@login_required
def subscription_status():
    """Check subscription status (for AJAX calls)"""
    return jsonify({
        'is_premium': current_user.is_premium,
        'membership': current_user.membership,
        'subscription_status': current_user.subscription_status,
        'subscription_end': current_user.subscription_end.isoformat() if current_user.subscription_end else None
    })

@app.route("/cancel-subscription", methods=["POST"])
@login_required
def cancel_subscription():
    """Cancel user's subscription (set to expire at period end)"""
    if not current_user.razorpay_subscription_id:
        flash("No active subscription found", "warning")
        return redirect(url_for("profile"))
    
    try:
        with transaction():
            with get_cursor() as cur:
                cur.execute("""
                    UPDATE users 
                    SET razorpay_subscription_status = 'cancelled'
                    WHERE id = %s
                """, (current_user.id,))
        
        app.logger.info(f"Subscription cancelled for user {current_user.id}")
        flash("Your subscription has been cancelled and will end at the current billing period.", "info")
        
    except Exception as e:
        app.logger.error(f"Error cancelling subscription: {e}")
        flash("Error cancelling subscription", "danger")
    
    return redirect(url_for("profile"))

# --------------------------------------------------
# MEAL PLANNER ROUTES
# --------------------------------------------------

@app.route("/meal-planner")
@login_required
@premium_required
def meal_planner():
    return render_template("meal_planner.html")

@app.route("/meal-planner/add", methods=["POST"])
@login_required
@premium_required
@csrf.exempt
def meal_planner_add():
    """Add a planned meal (not yet eaten)."""
    try:
        # Parse request
        if request.is_json:
            data = request.get_json()
            meal_type = data.get("meal_type")
            food_name = data.get("food_name", "").strip()
            weight = float(data.get("weight", 0))
        else:
            meal_type = request.form.get("meal_type")
            food_name = request.form.get("food_name", "").strip()
            weight = float(request.form.get("weight", 0))

        if not meal_type or not food_name or weight <= 0:
            return jsonify({"error": "Missing required fields"}), 400

        # Load food data
        foods = load_foods_json()
        food_key = food_name.lower().strip()
        food_data = foods.get(food_key)
        if not food_data:
            # Try fuzzy matching (optional)
            return jsonify({"error": f"Food '{food_name}' not found in database"}), 404

        # Calculate macros based on weight
        factor = weight / 100.0
        macros = food_data.get("macronutrients", {})
        calories = macros.get("calories", 0) * factor
        protein = macros.get("protein", 0) * factor
        carbs = macros.get("carbohydrate", 0) * factor
        fats = macros.get("total_fats", 0) * factor

        # Insert into meal_plans as 'planned'
        with transaction():
            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO meal_plans
                    (user_id, date, meal_type, food_name, weight, calories, protein, carbs, fats, status)
                    VALUES (%s, CURDATE(), %s, %s, %s, %s, %s, %s, %s, 'planned')
                """, (
                    current_user.id,
                    meal_type,
                    food_name,
                    weight,
                    calories,
                    protein,
                    carbs,
                    fats
                ))

        app.logger.info(f"Planned meal added: {meal_type} - {food_name} ({weight}g) for user {current_user.id}")
        return jsonify({"status": "success", "message": "Meal added to plan"}), 201

    except Exception as e:
        app.logger.error(f"Error adding planned meal: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/meal-planner/data")
@login_required
@premium_required
def meal_planner_data():
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT id, meal_type, food_name, calories
                FROM meal_plans
                WHERE user_id = %s AND date = CURDATE() AND status = 'planned'
                ORDER BY FIELD(meal_type, 'Breakfast','Lunch','Dinner','Snacks')
            """, (current_user.id,))
            rows = cur.fetchall()

        return jsonify([
            {
                "id": r["id"],
                "meal_type": r["meal_type"],
                "food_name": r["food_name"],
                "calories": float(r["calories"] or 0)
            }
            for r in rows
        ])
    except Exception as e:
        app.logger.error(f"Error fetching meal data: {e}")
        return jsonify({"error": "Server error"}), 500

@app.route("/foods-json")
@login_required
def foods_json():
    """Serve foods.json with caching headers"""
    data = load_foods_json()
    resp = make_response(jsonify(data))
    
    # Cache control - short cache for development, longer for production
    if IS_PRODUCTION:
        resp.headers["Cache-Control"] = "public, max-age=300"  # 5 minutes
    else:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    
    return resp

@app.route("/meal-planner/delete/<int:meal_id>", methods=["POST"])
@login_required
@premium_required
@csrf.exempt
def meal_planner_delete(meal_id):
    try:
        with transaction():
            with get_cursor() as cur:
                cur.execute(
                    "DELETE FROM meal_plans WHERE id = %s AND user_id = %s AND status = 'planned'",
                    (meal_id, current_user.id)
                )
                if cur.rowcount == 0:
                    return jsonify({"error": "Meal not found"}), 404

        return jsonify({"status": "success"})

    except Exception as e:
        app.logger.error(f"Error deleting meal: {e}")
        return jsonify({"error": str(e)}), 500

# --------------------------------------------------
# MEAL TRACKER ROUTES
# --------------------------------------------------

@app.route("/meal-tracker")
@login_required
@premium_required
def meal_tracker():
    return render_template("meal_tracker.html")

@app.route("/meal-tracker/data")
@login_required
@premium_required
def meal_tracker_data():
    try:
        days_range = request.args.get("range")
        selected_date = request.args.get("date")

        with get_cursor() as cur:
            if days_range:
                try:
                    days = int(days_range)
                    if days <= 0 or days > 365:
                        days = 30
                except ValueError:
                    days = 30
                    
                cur.execute("""
                    SELECT DATE(date) AS date, SUM(calories) AS total
                    FROM meal_logs
                    WHERE user_id = %s AND date >= (CURDATE() - INTERVAL %s DAY)
                    GROUP BY DATE(date)
                    ORDER BY DATE(date)
                """, (current_user.id, days))
                rows = cur.fetchall()
                return jsonify([
                    {"date": str(r["date"]), "total": float(r["total"] or 0)}
                    for r in rows
                ])

            if selected_date:
                cur.execute("""
                    SELECT meal_type, food_name, calories
                    FROM meal_logs
                    WHERE user_id = %s AND date = %s
                    ORDER BY FIELD(meal_type, 'Breakfast','Lunch','Dinner','Snacks')
                """, (current_user.id, selected_date))
            else:
                cur.execute("""
                    SELECT meal_type, food_name, calories
                    FROM meal_logs
                    WHERE user_id = %s AND date = CURDATE()
                    ORDER BY FIELD(meal_type, 'Breakfast','Lunch','Dinner','Snacks')
                """, (current_user.id,))

            rows = cur.fetchall()

        return jsonify([
            {
                "meal_type": r["meal_type"],
                "food_name": r["food_name"],
                "calories": float(r["calories"] or 0)
            }
            for r in rows
        ])
    except Exception as e:
        app.logger.error(f"Error fetching tracker data: {e}")
        return jsonify({"error": "Server error"}), 500

# --------------------------------------------------
# CALORIE TRACKER & NUTRITION
# --------------------------------------------------

@app.route("/calorie-tracker")
@login_required
@premium_required
def calorie_tracker():
    return render_template("calorie_tracker.html")

@app.route("/nutrition-analyzer")
@login_required
@premium_required
def nutrition_analyzer():
    return render_template("nutrition_analyzer.html")

@app.route("/calculate_calories", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
@csrf.exempt
def calculate_calories():
    """Calculate calories based on food name and weight"""
    try:
        # Check if it's JSON
        if not request.is_json:
            app.logger.error(f"Request is not JSON. Content-Type: {request.content_type}")
            return jsonify({"error": "Content-Type must be application/json"}), 400
        
        # Get JSON data
        data = request.get_json()
        app.logger.info(f"Received calculate_calories data: {data}")
        
        if not data:
            return jsonify({"error": "No JSON data received"}), 400
        
        # Extract and validate fields
        food_name = data.get("food_name", "").strip()
        if not food_name:
            return jsonify({"error": "Missing food_name field"}), 400
            
        try:
            weight = float(data.get("weight", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid weight value - must be a number"}), 400

        if weight <= 0:
            return jsonify({"error": "Weight must be greater than 0"}), 400

        # Load food data
        foods = load_foods_json()
        food_key = food_name.lower().strip()
        
        # Try exact match first
        if food_key not in foods:
            # Try case-insensitive match
            found = False
            for key in foods.keys():
                if key.lower() == food_key:
                    food_key = key
                    found = True
                    break
            
            if not found:
                # Try partial match for suggestions
                matching_foods = [f for f in foods.keys() if food_key in f.lower()]
                if matching_foods:
                    return jsonify({
                        "error": f"Food '{food_name}' not found. Did you mean: {', '.join(matching_foods[:3])}?"
                    }), 404
                return jsonify({"error": f"Food '{food_name}' not found in database"}), 404

        # Get nutritional data
        food = foods[food_key]
        macros = food.get("macronutrients", {})
        
        if not macros:
            return jsonify({"error": f"No nutritional data found for '{food_name}'"}), 404

        # Calculate based on weight (per 100g)
        calories_per_100g = float(macros.get("calories", 0))
        protein_per_100g = float(macros.get("protein", 0))
        carbs_per_100g = float(macros.get("carbohydrate", 0))
        fats_per_100g = float(macros.get("total_fats", 0))

        factor = weight / 100.0
        total_calories = calories_per_100g * factor
        total_protein = protein_per_100g * factor
        total_carbs = carbs_per_100g * factor
        total_fats = fats_per_100g * factor

        result = {
            "status": "success",
            "food_name": food_key.title(),
            "weight": weight,
            "total_calories": round(total_calories, 2),
            "protein": round(total_protein, 2),
            "carbs": round(total_carbs, 2),
            "fats": round(total_fats, 2),
            "per_100g": {
                "calories": round(calories_per_100g, 2),
                "protein": round(protein_per_100g, 2),
                "carbs": round(carbs_per_100g, 2),
                "fats": round(fats_per_100g, 2)
            }
        }

        app.logger.info(f"Calculated calories for {food_key}: {result}")
        return jsonify(result), 200

    except Exception as e:
        app.logger.error(f"Error in calculate_calories: {str(e)}", exc_info=True)
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/meal-entry")
@login_required
@premium_required
def meal_entry():
    return render_template("meal_entry.html")

@app.route("/nutrition-report")
@login_required
@premium_required
def nutrition_report():
    return render_template("nutrition_report.html", current_user_name=current_user.name)

@app.route("/api/get_nutrition_data", methods=["GET"])
@login_required
def api_get_nutrition_data():
    """API endpoint for nutrition data"""
    data = load_foods_json()

    # Ensure all required macros are present
    required_macros = [
        "calories", "protein", "carbohydrate", "total_fats",
        "saturated_fats", "omega_3", "omega_6", "fiber", "water"
    ]
    
    for k, v in data.items():
        m = v.get("macronutrients", {}) or {}
        for macro in required_macros:
            m.setdefault(macro, 0.0)
        v["macronutrients"] = m
        v["vitamins"] = v.get("vitamins", {}) or {}
        v["minerals_and_trace"] = v.get("minerals_and_trace", {}) or {}
        data[k] = v

    resp = make_response(jsonify(data))
    
    # Cache control
    if IS_PRODUCTION:
        resp.headers["Cache-Control"] = "public, max-age=300"
    else:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    
    return resp

# --------------------------------------------------
# SAVED MEALS API
# --------------------------------------------------

@app.route("/api/saved-meals", methods=["GET"])
@login_required
@premium_required
def api_list_saved_meals():
    try:
        days = request.args.get("days", default=30, type=int)
        if days <= 0 or days > 365:
            days = 30

        with get_cursor() as cur:
            cur.execute("""
                SELECT 
                    m.id AS meal_id,
                    m.meal_type,
                    m.date,
                    i.id AS item_id,
                    i.food_name,
                    i.weight
                FROM meals m
                LEFT JOIN meal_items i ON i.meal_id = m.id
                WHERE m.user_id = %s
                  AND m.date >= (CURDATE() - INTERVAL %s DAY)
                ORDER BY m.date DESC, m.id DESC, i.id ASC
            """, (current_user.id, days))
            rows = cur.fetchall()

        meals = {}
        for r in rows:
            mid = r["meal_id"]
            if mid not in meals:
                meals[mid] = {
                    "id": mid,
                    "meal_type": r["meal_type"],
                    "date": r["date"].isoformat() if r["date"] else None,
                    "items": []
                }
            if r["item_id"] is not None:
                meals[mid]["items"].append({
                    "id": r["item_id"],
                    "name": r["food_name"],
                    "weight": float(r["weight"] or 0)
                })

        return jsonify(list(meals.values()))
        
    except Exception as e:
        app.logger.error(f"Error listing saved meals: {e}")
        return jsonify({"error": "Server error"}), 500

@app.route("/api/saved-meals", methods=["POST"])
@login_required
@premium_required
@csrf.exempt
def api_save_meal():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    meal_type = (data or {}).get("meal_type", "").strip() or "Other"
    items = (data or {}).get("items") or []

    if not items:
        return jsonify({"error": "No items provided"}), 400

    # Validate and clean items
    clean_items = []
    for it in items:
        name = (it.get("name") or "").strip()
        try:
            weight = float(it.get("weight") or 0)
        except (TypeError, ValueError):
            weight = 0
        if not name or weight <= 0:
            continue
        clean_items.append({"name": name, "weight": weight})

    if not clean_items:
        return jsonify({"error": "No valid items"}), 400

    try:
        with transaction():
            with get_cursor() as cur:
                cur.execute(
                    "INSERT INTO meals (user_id, meal_type, date) VALUES (%s, %s, CURDATE())",
                    (current_user.id, meal_type)
                )
                meal_id = cur.lastrowid

                cur.executemany(
                    "INSERT INTO meal_items (meal_id, food_name, weight) VALUES (%s, %s, %s)",
                    [(meal_id, it["name"], it["weight"]) for it in clean_items]
                )

        return jsonify({"status": "success", "meal_id": meal_id}), 201

    except Exception as e:
        app.logger.error(f"Error saving meal: {e}")
        return jsonify({"error": "Server error"}), 500

@app.route("/api/saved-meals/<int:meal_id>", methods=["DELETE"])
@login_required
@premium_required
@csrf.exempt
def api_delete_meal(meal_id):
    try:
        with transaction():
            with get_cursor() as cur:
                cur.execute(
                    "DELETE FROM meals WHERE id = %s AND user_id = %s",
                    (meal_id, current_user.id)
                )
                affected = cur.rowcount

        if affected == 0:
            return jsonify({"error": "Not found"}), 404

        return jsonify({"status": "success"}), 200

    except Exception as e:
        app.logger.error(f"Error deleting meal: {e}")
        return jsonify({"error": "Server error"}), 500

# --------------------------------------------------
# ADMIN DASHBOARD (CSRF PROTECTED)
# --------------------------------------------------

@app.route("/admin")
@login_required
@admin_required
def admin():
    try:
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM users")
            total_users = cur.fetchone()["total"]

            cur.execute("SELECT COUNT(*) AS premium FROM users WHERE membership='Premium'")
            premium_users = cur.fetchone()["premium"]

            cur.execute("SELECT COUNT(*) AS free FROM users WHERE membership='Free'")
            free_users = cur.fetchone()["free"]

            cur.execute("SELECT id, name, email, membership, is_admin FROM users ORDER BY id DESC LIMIT 100")
            users = cur.fetchall()

            cur.execute("""
                SELECT id, name, calories, protein, carbohydrates, fats, vitamins, minerals
                FROM foods ORDER BY name
            """)
            foods = cur.fetchall()

        return render_template(
            "admin.html",
            total_users=total_users,
            premium_users=premium_users,
            free_users=free_users,
            users=users,
            foods=foods
        )
        
    except Exception as e:
        app.logger.error(f"Admin dashboard error: {e}")
        flash("Error loading admin dashboard", "danger")
        return redirect(url_for('profile'))

# --------------------------------------------------
# ADMIN FOOD MANAGEMENT (CSRF PROTECTED)
# --------------------------------------------------

@app.route("/admin/food/add", methods=["POST"])
@login_required
@admin_required
def admin_food_add():
    # CSRF check already handled by Flask-WTF globally
    data = request.form

    # Validation
    name = data.get("name", "").strip()
    if not name or len(name) > 100:
        flash("Invalid food name", "danger")
        return redirect(url_for("admin"))

    try:
        with transaction():
            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO foods 
                    (name, calories, protein, carbohydrates, fats, saturated_fats,
                     omega_3, omega_6, fiber, water, vitamins, minerals)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    name,
                    data.get("calories", 0),
                    data.get("protein", 0),
                    data.get("carbohydrates", 0),
                    data.get("fats", 0),
                    data.get("saturated_fats", 0),
                    data.get("omega_3", 0),
                    data.get("omega_6", 0),
                    data.get("fiber", 0),
                    data.get("water", 0),
                    data.get("vitamins", "{}"),
                    data.get("minerals", "{}")
                ))
    except IntegrityError:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"status": "duplicate", "message": "This food already exists."}), 409
        flash("This food already exists.", "warning")
        return redirect(url_for("admin"))
    except Exception as e:
        app.logger.error(f"Error adding food: {e}")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"status": "error", "message": str(e)}), 400
        flash(f"Error adding food", "danger")
        return redirect(url_for("admin"))

    # Update JSON
    new_food = {
        "name": name,
        "calories": data.get("calories", 0),
        "protein": data.get("protein", 0),
        "carbohydrates": data.get("carbohydrates", 0),
        "fats": data.get("fats", 0),
        "saturated_fats": data.get("saturated_fats", 0),
        "omega_3": data.get("omega_3", 0),
        "omega_6": data.get("omega_6", 0),
        "fiber": data.get("fiber", 0),
        "water": data.get("water", 0),
        "vitamins": data.get("vitamins", "{}"),
        "minerals": data.get("minerals", "{}"),
    }
    
    if not safe_update_food_json(new_food):
        flash("Food saved in DB but JSON update failed. Check logs.", "warning")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"status": "success"})
    
    flash("Food added successfully!", "success")
    return redirect(url_for("admin"))

@app.route("/admin/food/delete/<int:food_id>", methods=["POST"])
@login_required
@admin_required
def admin_food_delete(food_id):
    # CSRF check handled by Flask-WTF
    
    food_name = None
    
    try:
        with transaction():
            with get_cursor() as cur:
                # Get food name before deletion
                cur.execute("SELECT name FROM foods WHERE id = %s", (food_id,))
                row = cur.fetchone()
                
                if not row:
                    flash("Food not found", "warning")
                    return redirect(url_for("admin"))
                
                food_name = (row["name"] or "").strip().lower()
                
                # Delete from database
                cur.execute("DELETE FROM foods WHERE id = %s", (food_id,))
        
        # Update JSON
        if food_name:
            foods = load_foods_json(force_reload=True)
            if food_name in foods:
                del foods[food_name]
                
                # Atomic JSON update
                backup_foods_json()
                tmp_fd, tmp_path = tempfile.mkstemp(
                    prefix="foods_", suffix=".json", dir=os.path.dirname(JSON_PATH)
                )
                try:
                    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                        json.dump(foods, f, indent=2, ensure_ascii=False)
                        f.flush()
                        os.fsync(f.fileno())
                    shutil.move(tmp_path, JSON_PATH)
                    
                    # Sync directory (skip on Windows)
                    try:
                        dir_fd = os.open(os.path.dirname(JSON_PATH), os.O_DIRECTORY)
                        os.fsync(dir_fd)
                        os.close(dir_fd)
                    except (AttributeError, OSError):
                        pass  # Directory syncing not supported on Windows
                    
                    invalidate_foods_cache()
                except Exception as e:
                    app.logger.error(f"Error updating foods.json on delete: {e}")
                finally:
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass

        flash("Food deleted successfully!", "success")
        
    except Exception as e:
        app.logger.error(f"Error deleting food {food_id}: {e}")
        flash("Error deleting food", "danger")
    
    return redirect(url_for("admin"))

@app.route("/admin/food/update/<int:food_id>", methods=["POST"])
@login_required
@admin_required
def admin_food_update(food_id):
    # CSRF check handled by Flask-WTF
    data = request.form

    try:
        with transaction():
            with get_cursor() as cur:
                cur.execute("""
                    UPDATE foods
                    SET name = %s, calories = %s, protein = %s, carbohydrates = %s, fats = %s,
                        saturated_fats = %s, omega_3 = %s, omega_6 = %s, fiber = %s, water = %s,
                        vitamins = %s, minerals = %s
                    WHERE id = %s
                """, (
                    data.get("name"),
                    data.get("calories", 0),
                    data.get("protein", 0),
                    data.get("carbohydrates", 0),
                    data.get("fats", 0),
                    data.get("saturated_fats", 0),
                    data.get("omega_3", 0),
                    data.get("omega_6", 0),
                    data.get("fiber", 0),
                    data.get("water", 0),
                    data.get("vitamins", "{}"),
                    data.get("minerals", "{}"),
                    food_id
                ))
    except Exception as e:
        app.logger.error(f"Error updating food {food_id}: {e}")
        flash(f"Error updating food", "danger")
        return redirect(url_for("admin"))

    # Update JSON
    updated_food = {
        "name": data.get("name"),
        "calories": data.get("calories", 0),
        "protein": data.get("protein", 0),
        "carbohydrates": data.get("carbohydrates", 0),
        "fats": data.get("fats", 0),
        "saturated_fats": data.get("saturated_fats", 0),
        "omega_3": data.get("omega_3", 0),
        "omega_6": data.get("omega_6", 0),
        "fiber": data.get("fiber", 0),
        "water": data.get("water", 0),
        "vitamins": data.get("vitamins", "{}"),
        "minerals": data.get("minerals", "{}"),
    }
    
    if not safe_update_food_json(updated_food):
        flash("Food updated in DB but JSON update failed. Check logs.", "warning")
    else:
        flash("Food updated successfully!", "success")

    return redirect(url_for("admin"))

@app.route("/admin/user/upgrade/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def admin_user_upgrade(user_id):
    """Admin manually upgrades a user to Premium"""

    try:
        # Give 1 year premium by default
        end_date = datetime.now(timezone.utc) + timedelta(days=365)

        with transaction():
            with get_cursor() as cur:

                # Verify user exists
                cur.execute("SELECT id, email FROM users WHERE id = %s", (user_id,))
                user = cur.fetchone()

                if not user:
                    flash("User not found.", "warning")
                    return redirect(url_for("admin"))

                # Upgrade user
                cur.execute("""
                    UPDATE users
                    SET membership = 'Premium',
                        razorpay_subscription_status = 'active',
                        subscription_end_date = %s,
                        razorpay_subscription_id = 'admin_granted'
                    WHERE id = %s
                """, (end_date, user_id))

        app.logger.info(f"Admin {current_user.id} upgraded user {user_id} to Premium")

        flash("✅ User upgraded to Premium successfully.", "success")

    except Exception as e:
        app.logger.error(f"Admin upgrade failed for user {user_id}: {e}")
        flash("❌ Failed to upgrade user.", "danger")

    return redirect(url_for("admin"))

# --------------------------------------------------
# CLI COMMANDS
# --------------------------------------------------

@app.cli.command('check-expired-subscriptions')
def check_expired_subscriptions():
    """Background task to check and downgrade expired subscriptions"""
    with app.app_context():
        now = datetime.now(timezone.utc)
        downgraded_count = 0
        
        try:
            with transaction():
                with get_cursor() as cur:
                    # Find all expired premium subscriptions
                    cur.execute("""
                        SELECT id, email, name FROM users 
                        WHERE membership = 'Premium' 
                        AND subscription_end_date < %s
                        AND razorpay_subscription_status IN ('active', 'past_due')
                    """, (now,))

                    expired_users = cur.fetchall()

                    for user in expired_users:
                        # Immediate downgrade
                        cur.execute("""
                            UPDATE users 
                            SET membership = 'Free', 
                                razorpay_subscription_status = 'expired'
                            WHERE id = %s
                        """, (user['id'],))

                        downgraded_count += 1
                        app.logger.info(f"User {user['email']} auto-downgraded due to expiration")

            print(f"Checked and downgraded {downgraded_count} expired subscriptions")
            
        except Exception as e:
            app.logger.error(f"Error in subscription check: {e}")
            print(f"Error: {e}")

@app.cli.command('rebuild-foods-json')
def rebuild_foods_json():
    """Rebuild foods.json from database"""
    with app.app_context():
        if foods_to_jsonfile(force=True):
            print("Foods.json rebuilt successfully")
        else:
            print("Failed to rebuild foods.json")

@app.cli.command('create-admin')
def create_admin():
    """Create an admin user (interactive)"""
    with app.app_context():
        email = input("Enter admin email: ").strip().lower()
        
        with get_cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            user = cur.fetchone()
            
            if not user:
                print("User not found!")
                return
            
            cur.execute("UPDATE users SET is_admin = 1 WHERE id = %s", (user['id'],))
            mysql.connection.commit()
            
        print(f"User {email} is now an admin")

@app.cli.command('convert-images')
def convert_images_command():
    """Convert PNG images to WebP (run manually when needed)."""
    with app.app_context():
        convert_images_if_needed()
        click.echo('Image conversion completed.')

# --------------------------------------------------
# ERROR HANDLERS (ENHANCED)
# --------------------------------------------------

@app.errorhandler(404)
def page_not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "Not found"}), 404
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    app.logger.error(f"Internal server error: {e}")
    if request.path.startswith('/api/'):
        return jsonify({"error": "Internal server error"}), 500
    return render_template('500.html'), 500

@app.errorhandler(429)
def ratelimit_handler(e):
    app.logger.warning(f"Rate limit exceeded for {request.remote_addr}")
    if request.path.startswith('/api/'):
        return jsonify({"error": "Rate limit exceeded", "retry_after": e.description}), 429
    flash("Too many requests. Please try again later.", "warning")
    return redirect(url_for('index'))

@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "Forbidden"}), 403
    flash("Access forbidden", "danger")
    return redirect(url_for('index'))

@app.errorhandler(401)
def unauthorized(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "Unauthorized"}), 401
    flash("Please log in to access this page", "warning")
    return redirect(url_for('login'))

# --------------------------------------------------
# HEALTH CHECK ENDPOINT (for production)
# --------------------------------------------------

@app.route("/health")
def health_check():
    """Health check endpoint for load balancers"""
    try:
        # Test database connection
        with get_cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        
        # Check if JSON file exists
        json_ok = os.path.exists(JSON_PATH)
        
        # Check Razorpay configuration
        razorpay_ok = is_razorpay_configured()
        
        return jsonify({
            "status": "healthy",
            "database": "ok",
            "json_file": "ok" if json_ok else "missing",
            "razorpay": "configured" if razorpay_ok else "not configured",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200
    except Exception as e:
        app.logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 500

# --------------------------------------------------
# TEMPLATE CONTEXT PROCESSOR
# --------------------------------------------------

@app.context_processor
def utility_processor():
    """Add utility functions to template context"""
    return {
        'now': datetime.utcnow,
        'app_name': 'Nutrition Planner',
        'is_production': IS_PRODUCTION,
        'csrf_token': generate_csrf,  # Pass the function, not a lambda
        'razorpay_configured': is_razorpay_configured(),
        'razorpay_key_id': app.config['RAZORPAY_KEY_ID'] if is_razorpay_configured() else None
    }

# --------------------------------------------------
# APP START LOG
# --------------------------------------------------

app.logger.info("=" * 50)
app.logger.info("Application loaded successfully")
app.logger.info(f"Environment: {ENV.upper()}")
app.logger.info(f"Production mode: {IS_PRODUCTION}")
app.logger.info(f"App root: {app.root_path}")
app.logger.info(f"foods.json path: {JSON_PATH}")
app.logger.info(f"foods.json backups in: {BACKUP_DIR}")
app.logger.info(f"Rate limiting storage: {RATE_LIMIT_STORAGE}")
app.logger.info(f"Razorpay configured: {is_razorpay_configured()}")
app.logger.info(f"Session cookie secure mode: {app.config['SESSION_COOKIE_SECURE']}")
app.logger.info(f"Session protection: {'strong' if IS_PRODUCTION else 'basic'}")
if not is_razorpay_configured():
    app.logger.warning("Razorpay payment features are disabled")
app.logger.info("=" * 50)

# --------------------------------------------------
# RUN (with production warning)
# --------------------------------------------------

# Run image conversion at startup (only in main process)
if not os.environ.get('WERKZEUG_RUN_MAIN'):  # avoids double run in debug mode
    convert_images_if_needed()

if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("⚠️  WARNING: Running with built-in server")
    print("   For production, use Gunicorn:")
    print("   gunicorn -w 4 -b 0.0.0.0:8000 app:app")
    print("=" * 50 + "\n")
    
    # Development server
    debug_mode = not IS_PRODUCTION
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)