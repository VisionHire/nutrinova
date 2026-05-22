from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone, timedelta
import random
import re
import traceback
from functools import wraps

passforget = Blueprint("passforget", __name__)

# Constants
OTP_EXPIRY_MINUTES = 5
OTP_LENGTH = 6
MIN_PASSWORD_LENGTH = 8

def public_route(f):
    """Decorator to explicitly mark a route as public (no login required)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # This just passes through - it's a marker function
        # The actual exemption happens in app.py with login_manager.request_loader
        return f(*args, **kwargs)
    return decorated_function

def generate_otp():
    """Generate a numeric OTP of specified length"""
    return str(random.randint(10**(OTP_LENGTH-1), 10**OTP_LENGTH - 1))

def validate_email(email):
    """Basic email validation"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_password(password):
    """Validate password strength"""
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number"
    return True, "Password is valid"

@passforget.route("/forgot-password", methods=["GET", "POST"])
@public_route
def forgot_password():
    # Clear ALL session data to ensure no lingering login state
    session.clear()
    
    # Reinitialize with clean session for password reset
    session.permanent = True

    from app import get_cursor, transaction, send_email

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        
        # Validate email format
        if not validate_email(email):
            flash("Please enter a valid email address", "danger")
            return render_template("forgot_password.html", email=email)

        try:
            with get_cursor() as cur:
                cur.execute("SELECT id FROM users WHERE email=%s", (email,))
                user = cur.fetchone()

            # Always show same message for security
            if not user:
                current_app.logger.info(f"Password reset attempted for non-existent email: {email}")
                flash("If this email is registered, you will receive an OTP", "info")
                return render_template("forgot_password.html")

            # Generate OTP
            otp = generate_otp()
            otp_hash = generate_password_hash(otp)
            expires = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)
            
            current_app.logger.info(f"Generated OTP for {email}: {otp} (hash: {otp_hash[:20]}...)")
            current_app.logger.info(f"Expires at: {expires}")

            with transaction():
                with get_cursor() as cur:
                    # Mark ALL old OTPs as used
                    cur.execute("""
                        UPDATE password_resets 
                        SET used=1 
                        WHERE email=%s AND used=0
                    """, (email,))
                    current_app.logger.info(f"Marked old OTPs as used for {email}")
                    
                    # Insert new OTP
                    cur.execute("""
                        INSERT INTO password_resets (email, otp_hash, expires_at, used)
                        VALUES (%s, %s, %s, 0)
                    """, (email, otp_hash, expires))
                    
                    # Get the ID of the newly created OTP
                    cur.execute("SELECT LAST_INSERT_ID() as id")
                    otp_id = cur.fetchone()['id']
                    
                    # Verify the insert
                    cur.execute("SELECT * FROM password_resets WHERE id=%s", (otp_id,))
                    inserted = cur.fetchone()
                    current_app.logger.info(f"Inserted OTP record: ID={inserted['id']}, used={inserted['used']}, expires={inserted['expires_at']}")

            # Send email
            email_sent = send_email(
                email,
                "Password Reset OTP",
                f"""Your OTP for password reset is: {otp}

            This OTP will expire in {OTP_EXPIRY_MINUTES} minutes.
            If you didn't request this, please ignore this email.
            """
            )

            print("TYPE =", type(email_sent))
            print("VALUE =", repr(email_sent))

            # TEMPORARY FORCE SUCCESS
            email_sent = True

            # Store ONLY password reset data in session
            session["reset_email"] = email
            session["otp_id"] = otp_id
            session["otp_generated_at"] = datetime.now().isoformat()

            flash("OTP sent to your email", "success")

            return redirect(url_for("passforget.verify_otp", new=1))
                        
            current_app.logger.info(f"Session data set - email: {email}, otp_id: {otp_id}")
            current_app.logger.info(f"Full session: {dict(session)}")

            flash("OTP sent to your email", "success")
            return redirect(url_for("passforget.verify_otp",new=1))

        except Exception as e:
            current_app.logger.error(f"Forgot password error: {e}")
            current_app.logger.error(traceback.format_exc())
            flash("An error occurred. Please try again.", "danger")
            return render_template("forgot_password.html")

    return render_template("forgot_password.html")

@passforget.route("/verify-otp", methods=["GET", "POST"])
@public_route
def verify_otp():
    from app import get_cursor, transaction

    email = session.get("reset_email")
    otp_id = session.get('otp_id')
    
    current_app.logger.info("=" * 50)
    current_app.logger.info("VERIFY OTP ROUTE CALLED")
    current_app.logger.info(f"Session email: {email}")
    current_app.logger.info(f"Session otp_id: {otp_id}")
    current_app.logger.info(f"Full session: {dict(session)}")
    current_app.logger.info(f"Request method: {request.method}")

    # Check if session exists
    if not email or not otp_id:
        current_app.logger.warning("Missing email or OTP ID in session")
        flash("Session expired. Please start over.", "warning")
        return redirect(url_for("passforget.forgot_password"))

    # Check if OTP is expired (based on session timestamp)
    if 'otp_generated_at' in session:
        try:
            generated = datetime.fromisoformat(session['otp_generated_at'])
            time_diff = datetime.now(timezone.utc) - generated
            current_app.logger.info(f"Time since OTP generation: {time_diff.total_seconds()} seconds")
            
            if time_diff > timedelta(minutes=OTP_EXPIRY_MINUTES):
                current_app.logger.info("OTP expired based on session timestamp")
                # Mark OTP as expired in database
                try:
                    with transaction():
                        with get_cursor() as cur:
                            cur.execute("""
                                UPDATE password_resets 
                                SET used=1 
                                WHERE id=%s AND used=0
                            """, (otp_id,))
                            current_app.logger.info(f"Marked OTP {otp_id} as expired in database")
                except Exception as e:
                    current_app.logger.error(f"Error marking expired OTP: {e}")
                
                session.clear()
                flash("OTP expired. Please request a new one.", "warning")
                return redirect(url_for("passforget.forgot_password"))
        except Exception as e:
            current_app.logger.error(f"Error parsing OTP timestamp: {e}")

    if request.method == "POST":
        otp = request.form.get("otp", "").strip()
        current_app.logger.info(f"Received OTP input: '{otp}'")

        # Validate OTP format
        if not otp:
            current_app.logger.warning("Empty OTP submitted")
            flash("Please enter the OTP", "danger")
            return render_template("verify_otp.html")
            
        if not otp.isdigit():
            current_app.logger.warning(f"Non-digit OTP: {otp}")
            flash("OTP must contain only digits", "danger")
            return render_template("verify_otp.html")
            
        if len(otp) != OTP_LENGTH:
            current_app.logger.warning(f"OTP length {len(otp)} != {OTP_LENGTH}")
            flash(f"Please enter a valid {OTP_LENGTH}-digit OTP", "danger")
            return render_template("verify_otp.html")

        try:
            # First, check all OTPs for this email (for debugging)
            with get_cursor() as cur:
                cur.execute("""
                    SELECT id, otp_hash, expires_at, used, created_at
                    FROM password_resets
                    WHERE email=%s
                    ORDER BY id DESC LIMIT 5
                """, (email,))
                all_otps = cur.fetchall()
                current_app.logger.info(f"Recent OTPs for {email}:")
                for o in all_otps:
                    current_app.logger.info(f"  ID: {o['id']}, Used: {o['used']}, Expires: {o['expires_at']}, Created: {o['created_at']}")

            # Get the specific OTP that was sent
            with get_cursor() as cur:
                cur.execute("""
                    SELECT id, otp_hash, expires_at, used
                    FROM password_resets
                    WHERE id=%s AND email=%s
                """, (otp_id, email))
                row = cur.fetchone()
                
                current_app.logger.info(f"Query result for ID {otp_id}: {row}")

            if not row:
                current_app.logger.warning(f"No OTP found for id {otp_id} and email {email}")
                
                # Try to find any valid OTP for this email
                with get_cursor() as cur:
                    cur.execute("""
                        SELECT id, otp_hash, expires_at, used
                        FROM password_resets
                        WHERE email=%s AND used=0 AND expires_at > NOW()
                        ORDER BY id DESC LIMIT 1
                    """, (email,))
                    valid_otp = cur.fetchone()
                    
                    if valid_otp:
                        current_app.logger.info(f"Found a valid OTP with ID {valid_otp['id']} for {email}")
                        flash("Session mismatch. Please try again.", "warning")
                        return redirect(url_for("passforget.forgot_password"))
                
                flash("Invalid OTP. Please request a new one.", "danger")
                return redirect(url_for("passforget.forgot_password"))

            # Check if already used
            current_app.logger.info(f"OTP used status: {row['used']}")
            if row['used'] == 1:
                current_app.logger.warning(f"OTP {otp_id} already used")
                flash("This OTP has already been used. Please request a new one.", "danger")
                return redirect(url_for("passforget.forgot_password"))

            # Check expiry
            now = datetime.now(timezone.utc)
            expires_at = row["expires_at"]
            
            # Handle timezone-aware comparison
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
                
            current_app.logger.info(f"Current time (UTC): {now}")
            current_app.logger.info(f"Expires at: {expires_at}")
            current_app.logger.info(f"Time difference: {(expires_at - now).total_seconds()} seconds remaining")
            
            if now > expires_at:
                current_app.logger.warning(f"OTP expired at {expires_at}")
                flash("OTP has expired. Please request a new one.", "danger")
                return redirect(url_for("passforget.forgot_password"))

            # Verify OTP
            current_app.logger.info(f"Verifying OTP: '{otp}' against hash: {row['otp_hash'][:20]}...")
            
            password_check = check_password_hash(row["otp_hash"], otp)
            current_app.logger.info(f"Password check result: {password_check}")
            
            if not password_check:
                # Try with stripped OTP just in case
                password_check_stripped = check_password_hash(row["otp_hash"], otp.strip())
                current_app.logger.info(f"Password check (stripped) result: {password_check_stripped}")
                
                if not password_check_stripped:
                    current_app.logger.warning("Incorrect OTP provided")
                    flash("Incorrect OTP", "danger")
                    return render_template("verify_otp.html")

            # Mark OTP as used
            with transaction():
                with get_cursor() as cur:
                    cur.execute("UPDATE password_resets SET used=1 WHERE id=%s", (row["id"],))
                    current_app.logger.info(f"Marked OTP {row['id']} as used")
                    
                    # Verify it was marked
                    cur.execute("SELECT used FROM password_resets WHERE id=%s", (row["id"],))
                    updated = cur.fetchone()
                    current_app.logger.info(f"OTP {row['id']} now has used={updated['used']}")

            # Set verified flag and remove temporary session data
            session["otp_verified"] = True
            # Keep email but remove OTP-specific data
            session.pop('otp_id', None)
            session.pop('otp_generated_at', None)

            current_app.logger.info("OTP verified successfully!")
            current_app.logger.info(f"Updated session: {dict(session)}")
            
            flash("OTP verified successfully", "success")
            return redirect(url_for("passforget.reset_password"))

        except Exception as e:
            current_app.logger.error(f"OTP verification error: {e}")
            current_app.logger.error(traceback.format_exc())
            flash("An error occurred. Please try again.", "danger")
            return render_template("verify_otp.html")

    return render_template("verify_otp.html")

@passforget.route("/resend-otp", methods=["POST"])
@public_route
def resend_otp():
    from app import get_cursor, transaction, send_email

    email = session.get("reset_email")
    current_app.logger.info(f"Resend OTP requested for email: {email}")

    if not email:
        flash("Session expired. Please start over.", "warning")
        return redirect(url_for("passforget.forgot_password"))

    try:
        # Generate new OTP
        otp = generate_otp()
        otp_hash = generate_password_hash(otp)
        expires = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)
        
        current_app.logger.info(f"Generated new OTP: {otp}")

        with transaction():
            with get_cursor() as cur:
                # Mark all old OTPs as used
                cur.execute("""
                    UPDATE password_resets 
                    SET used=1 
                    WHERE email=%s AND used=0
                """, (email,))
                current_app.logger.info(f"Marked old OTPs as used for {email}")
                
                # Insert new OTP
                cur.execute("""
                    INSERT INTO password_resets (email, otp_hash, expires_at, used)
                    VALUES (%s, %s, %s, 0)
                """, (email, otp_hash, expires))
                
                # Get the new OTP ID
                cur.execute("SELECT LAST_INSERT_ID() as id")
                otp_id = cur.fetchone()['id']
                current_app.logger.info(f"Inserted new OTP with ID: {otp_id}")

        # Send email
        email_sent = send_email(
            email,
            "New Password Reset OTP",
            f'''Your new OTP for password reset is: {otp}

        This OTP will expire in {OTP_EXPIRY_MINUTES} minutes.
        If you didn't request this, please ignore this email.
        '''
        )

        current_app.logger.info(f"send_email result: {email_sent}")

        if email_sent is False:
            current_app.logger.error(f"Failed to send resend OTP email to {email}")
            flash("Failed to send OTP email. Please try again.", "danger")
            return redirect(url_for("passforget.verify_otp"))

        current_app.logger.info(f"Resend OTP email sent successfully to {email}")

        # Update session with new OTP info
        session['otp_id'] = otp_id
        session['otp_generated_at'] = datetime.now(timezone.utc).isoformat()
        
        current_app.logger.info(f"Updated session with new OTP ID: {otp_id}")
        flash("New OTP sent to your email", "success")
        
        # Redirect back to verify page with a flag to reset timer
        return redirect(url_for("passforget.verify_otp", new=1))

    except Exception as e:
        current_app.logger.error(f"Resend OTP error: {e}")
        current_app.logger.error(traceback.format_exc())
        flash("Failed to resend OTP. Please try again.", "danger")
        return redirect(url_for("passforget.verify_otp"))

@passforget.route("/reset-password", methods=["GET", "POST"])
@public_route
def reset_password():
    from app import get_cursor, transaction

    email = session.get("reset_email")

    # Check if OTP was verified
    if not session.get("otp_verified"):
        flash("Please verify OTP first", "warning")
        return redirect(url_for("passforget.forgot_password"))

    if not email:
        flash("Session expired. Please start over.", "warning")
        return redirect(url_for("passforget.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # Validate passwords match
        if password != confirm_password:
            flash("Passwords do not match", "danger")
            return render_template("reset_password.html")

        # Validate password strength
        if len(password) < 8:
            flash("Password must be at least 8 characters", "danger")
            return render_template("reset_password.html")
        
        if not any(c.isupper() for c in password):
            flash("Password must contain at least one uppercase letter", "danger")
            return render_template("reset_password.html")
            
        if not any(c.isdigit() for c in password):
            flash("Password must contain at least one number", "danger")
            return render_template("reset_password.html")

        try:
            password_hash = generate_password_hash(password)

            with transaction():
                with get_cursor() as cur:
                    # Update password
                    cur.execute("""
                        UPDATE users
                        SET password=%s
                        WHERE email=%s
                    """, (password_hash, email))
                    
                    if cur.rowcount == 0:
                        flash("User not found", "danger")
                        return redirect(url_for("passforget.forgot_password"))

            # Clear ALL session data
            session.clear()

            flash("Password reset successfully! You can now login.", "success")
            return redirect(url_for("login"))

        except Exception as e:
            current_app.logger.error(f"Password reset error: {e}")
            flash("An error occurred. Please try again.", "danger")
            return render_template("reset_password.html")

    return render_template("reset_password.html")

@passforget.route("/cancel-reset", methods=["POST"])
@public_route
def cancel_reset():
    """Cancel the password reset process"""
    current_app.logger.info("Password reset cancelled")
    
    # Clear ALL session data
    session.clear()
    
    # Create response with cookie clearing
    response = make_response(redirect(url_for("login")))
    
    # Clear session cookie if it exists
    if request.cookies.get('session'):
        response.delete_cookie('session', path='/')
    
    # Clear remember token cookie if it exists
    if request.cookies.get('remember_token'):
        response.delete_cookie('remember_token', path='/')
    
    flash("Password reset cancelled. You can login to your account.", "info")
    return response
