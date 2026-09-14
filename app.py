"""
Daily Tasker - Flask Application
=================================
A personal task management application with daily tracking, progress monitoring,
and PDF export capabilities.

Version: 1.0.0 (Production Ready)
License: MIT
"""

# ====================
# Imports
# ====================
import os
import sqlite3
from datetime import date, datetime, timedelta

from flask import (
    Flask, render_template, redirect, url_for,
    request, send_file, flash, abort, jsonify
)
from flask_login import (
    LoginManager, login_user, login_required,
    logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import event
from sqlalchemy.engine import Engine
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from pdf.pdf_generator import (
    generate_year_pdf, generate_month_pdf, generate_week_pdf
)

from models import db, User, Task, DailyTask, Category, ShareToken, Badge

from utils.task_routes import (
    soft_delete_task_route,
    restore_task_route,
    permanently_delete_task_route,
    get_deleted_tasks_route,
    update_retention_settings_route,
    cleanup_expired_deleted_tasks
)

# Utility Helpers
from utils.badges import award_badges
from utils.streaks import compute_current_streak
from utils.tasks import ensure_daily_tasks
from utils.dashboard_stats import get_dashboard_stats
from utils.email import send_daily_reminders


# ====================
# Flask App Configuration
# ====================
app = Flask(__name__)

# CRITICAL: SECRET_KEY must be set via environment variable in production
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if os.environ.get("FLASK_ENV") == "production":
        raise ValueError("SECRET_KEY environment variable must be set in production!")
    else:
        # Only use fallback in development
        SECRET_KEY = "dev-secret-key-change-in-production"
        print("⚠️  WARNING: Using development SECRET_KEY. Set SECRET_KEY environment variable for production!")

app.config["SECRET_KEY"] = SECRET_KEY

# Database configuration - PostgreSQL for production, SQLite for development
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    # Fix for Heroku/Railway postgres:// vs postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    print("✅ Using PostgreSQL database")
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///tasker.db"
    print("⚠️  Using SQLite database (development only)")

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False # Turns off tracking of changes in objects e.g. user.name = "Bob"

db.init_app(app) # Attaching db to app.py


# ====================
# Rate Limiting Configuration
# ====================
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["2000 per day", "300 per hour"],  # Increased for normal usage,
    storage_uri="memory://"
)


# ====================
# Security Headers
# ====================
@app.after_request
def set_security_headers(response):
    """Add security headers to all responses."""
    response.headers['X-Content-Type-Options'] = 'nosniff' # Dont guess file types
    response.headers['X-Frame-Options'] = 'DENY' # Dont embed my side in iframes
    response.headers['X-XSS-Protection'] = '1; mode=block' # Block suspicious scripts
    
    # Only set HSTS in production with HTTPS
    if not app.debug and request.is_secure: # Only use secure connections https(in production)
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    return response


# ====================
# SQLite Foreign Keys Support
# ====================
@event.listens_for(Engine, "connect") # Run this function every time a new database connection is made
def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """
    Enable foreign key constraints in SQLite.
    Required for CASCADE deletions to work properly.
    """
    if isinstance(dbapi_connection, sqlite3.Connection): # Make sure its a sqlite3(db) connection
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()


# ====================
# Login Manager Setup
# ====================
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = ""  # Disable default login message
login_manager.login_message_category = "info"
login_manager.init_app(app)


@login_manager.user_loader # Runs on every loading on the page 
def load_user(user_id):
    """Load user by ID for Flask-Login."""
    return User.query.get(int(user_id))


# ====================
# Input Validation Helpers
# ====================
import re
import html

def is_valid_email(email):
    """Validate email format."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def sanitize_input(text, max_length=None):
    """Sanitize user input to prevent XSS."""
    if not text:
        return ""
    
    text = text.strip()
    
    if max_length and len(text) > max_length:
        text = text[:max_length]
    
    # Escape HTML to prevent XSS
    text = html.escape(text)
    
    return text


# ====================
# Background Scheduler for Email Reminders
# ====================
scheduler = BackgroundScheduler()


def scheduled_reminders():
    """Background job to send daily email reminders."""
    with app.app_context():
        try:
            send_daily_reminders()
        except Exception as e:
            print(f"Error sending reminders: {e}")


scheduler.add_job(
    scheduled_reminders,
    trigger="interval",
    minutes=1,  # Check every minute
    id="daily_reminders",
    replace_existing=True
)

scheduler.add_job(
    cleanup_expired_deleted_tasks,
    trigger="interval",
    hours=24,
    id="cleanup_deleted_tasks",
    replace_existing=True
)


def start_scheduler():
    """Start the scheduler only once, not in every gunicorn worker."""
    if not scheduler.running:
        scheduler.start()
        print("✅ Scheduler started")


# ====================
# Authentication Routes
# ====================
@app.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def register():
    """
    User registration endpoint.
    Creates a new user account with default categories.
    """
    if request.method == "POST":
        name = sanitize_input(request.form.get("name", ""), max_length=100)
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        # Validate input
        if not name or not email or not password:
            flash("All fields are required.")
            return render_template("register.html")

        # Validate email format
        if not is_valid_email(email):
            flash("Invalid email format.")
            return render_template("register.html")

        # Validate password strength
        if len(password) < 8:
            flash("Password must be at least 8 characters long.")
            return render_template("register.html")

        # Check if user already exists
        if User.query.filter_by(email=email).first():
            flash("Email already registered.")
            return render_template("register.html")

        # Create new user
        hashed = generate_password_hash(password, method='pbkdf2:sha256')
        user = User(
            name=name, 
            email=email, 
            password_hash=hashed,
            theme='theme-light'  # Default theme
        )
        db.session.add(user)
        db.session.commit()

        # Create default categories
        default_categories = ["Work", "Personal", "Health & Fitness", "Learning"]
        for cat_name in default_categories:
            category = Category(name=cat_name, user_id=user.id)
            db.session.add(category)
        
        db.session.commit()

        login_user(user)
        flash("Account created successfully!")
        return redirect(url_for("dashboard"))
    
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    """
    User login endpoint.
    Authenticates user credentials and creates session.
    """
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password are required.")
            return render_template("login.html")

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password.")
    
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    """User logout endpoint."""
    logout_user()
    flash("Logged out successfully.")
    return redirect(url_for("login"))


# ====================
# Dashboard Route
# ====================
@app.route("/")
@login_required
def dashboard():
    """
    Main dashboard view with date navigation.
    Supports arrow navigation + History modal for specific dates.
    """
    # Parse date from query params or use today
    date_str = request.args.get("date")
    selected_date = (
        datetime.strptime(date_str, "%Y-%m-%d").date()
        if date_str else date.today()
    )

    # Ensure daily tasks exist for this date
    ensure_daily_tasks(current_user.id, selected_date)

    # Get ALL categories
    categories = Category.query.filter_by(user_id=current_user.id).all()

    # Get daily tasks for selected date
    daily_tasks_list = DailyTask.query.filter_by(
        user_id=current_user.id,
        date=selected_date
    ).order_by(DailyTask.category_name, DailyTask.task_title).all()
    
    # Group by category_name
    tasks_by_category_name = {}
    for dt in daily_tasks_list:
        cat_name = dt.category_name
        if cat_name not in tasks_by_category_name:
            tasks_by_category_name[cat_name] = []
        tasks_by_category_name[cat_name].append(dt)

    # Create daily_tasks dict
    daily_tasks_dict = {
        dt.id: dt
        for dt in daily_tasks_list
    }

    # Calculate statistics
    stats = get_dashboard_stats(current_user.id, selected_date)
    badges = Badge.query.filter_by(user_id=current_user.id).all()
    current_streak = compute_current_streak(current_user.id, selected_date)

    return render_template(
        "dashboard.html",
        tasks_by_category=tasks_by_category_name,
        daily_tasks=daily_tasks_dict,
        selected_date=selected_date,
        timedelta=timedelta,
        categories=categories,
        daily_percent=stats["daily_percent"],
        weekly_percent=stats["weekly_percent"],
        monthly_stats={
            "completed": stats["monthly_completed"],
            "percent": stats["monthly_percent"],
        },
        badges=badges,
        current_streak=current_streak,
        date=date,
        user_theme=current_user.theme
    )


# ====================
# Task Management Routes
# ====================
@app.route("/add-task", methods=["POST"])
@login_required
@limiter.limit("50 per minute")  
def add_task():
    """
    Create a new task.
    Adds a task to the user's task list under a specific category.
    """
    title = sanitize_input(request.form.get("title", ""), max_length=200)
    category_id = request.form.get("category_id", type=int)
    duration = sanitize_input(request.form.get("duration", ""), max_length=50)

    if not title or not category_id:
        flash("Task title and category are required.")
        return redirect(url_for("dashboard"))

    # Verify category belongs to user
    category = Category.query.filter_by(
        id=category_id,
        user_id=current_user.id
    ).first()

    if not category:
        flash("Invalid category.")
        return redirect(url_for("dashboard"))

    # Create task
    task = Task(
        title=title,
        duration=duration if duration else None,
        user_id=current_user.id,
        category_id=category.id
    )
    db.session.add(task)
    db.session.commit()

    flash(f"Task '{title}' added successfully!")
    return redirect(url_for("dashboard"))


@app.route("/update-daily-tasks", methods=["POST"])
@login_required
def update_daily_tasks():
    """
    Update daily task completion status or delete tasks.
    Handles both marking tasks as complete and deleting tasks.
    """
    
    selected_date_str = request.form.get("selected_date")
    selected_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
    
    action = request.form.get("action")
    
    if action == "save":
        # Now we get DailyTask IDs (not Task IDs)
        completed_daily_task_ids = set(request.form.getlist("completed_tasks"))
        
        # Get all daily tasks for this date
        daily_tasks = DailyTask.query.filter_by(
            user_id=current_user.id,
            date=selected_date
        ).all()
        
        # Update completion status using DailyTask.id
        for dt in daily_tasks:
            dt.completed = str(dt.id) in completed_daily_task_ids
        
        db.session.commit()

        # Award badge
        streak = compute_current_streak(current_user.id, selected_date)
        total_completed = DailyTask.query.filter_by(
            user_id=current_user.id, completed=True
        ).count()
        weekly_pct = get_dashboard_stats(current_user.id, selected_date)["weekly_percent"]

        award_badges(current_user.id, {
            "total_completed": total_completed,
            "current_streak": streak,
            "weekly_percent": weekly_pct
        })

        flash("Progress saved!")
    
    return redirect(url_for("dashboard", date=selected_date))

@app.route("/task/soft-delete", methods=["POST"])
@login_required
def soft_delete_task():
    return soft_delete_task_route()

@app.route("/task/restore", methods=["POST"])
@login_required
def restore_task():
    return restore_task_route()

@app.route("/task/permanent-delete", methods=["POST"])
@login_required
def permanently_delete_task():
    return permanently_delete_task_route()

@app.route("/tasks/deleted", methods=["GET"])
@login_required
def get_deleted_tasks():
    return get_deleted_tasks_route()

@app.route("/settings/retention", methods=["POST"])
@login_required
def update_retention_settings():
    return update_retention_settings_route()


# Keep the History modal routes as well
@app.route("/history/<date_str>")
@login_required
def view_history_date(date_str):
    """
    View a specific historical date via History modal.
    """
    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date format")
        return redirect(url_for("dashboard"))
    
    # Can't view future dates
    if selected_date > date.today():
        flash("Cannot view future dates")
        return redirect(url_for("dashboard"))
    
    # Ensure daily tasks exist
    ensure_daily_tasks(current_user.id, selected_date)
    
    # Get daily tasks
    daily_tasks_list = DailyTask.query.filter_by(
        user_id=current_user.id,
        date=selected_date
    ).order_by(DailyTask.category_name, DailyTask.task_title).all()
    
    # Group by category
    tasks_by_category_name = {}
    for dt in daily_tasks_list:
        cat_name = dt.category_name
        if cat_name not in tasks_by_category_name:
            tasks_by_category_name[cat_name] = []
        tasks_by_category_name[cat_name].append(dt)
    
    return jsonify({
        'date': selected_date.strftime('%Y-%m-%d'),
        'date_display': selected_date.strftime('%B %d, %Y'),
        'tasks_by_category': {
            cat_name: [
                {
                    'id': dt.id,
                    'task_id': dt.task_id,
                    'title': dt.task_title,
                    'duration': dt.task_duration,
                    'completed': dt.completed
                }
                for dt in tasks
            ]
            for cat_name, tasks in tasks_by_category_name.items()
        }
    })


# Delete task from dashboard (handles both today and past dates)
@app.route("/task/delete-from-date", methods=["POST"])
@login_required
def delete_task_from_dashboard():
    """Delete a task from the dashboard."""
    
    task_id = request.form.get("task_id", type=int)
    date_str = request.form.get("date")
    
    if not task_id or not date_str:
        flash("Invalid request")
        return redirect(url_for("dashboard"))
    
    try:
        deletion_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date")
        return redirect(url_for("dashboard"))
    
    task = Task.query.filter_by(
        id=task_id,
        user_id=current_user.id
    ).first()
    
    if not task:
        flash("Task not found")
        return redirect(url_for("dashboard", date=date_str))
    
    task_title = task.title
    
    # Soft delete
    if deletion_date >= date.today():
        task.soft_delete()
    else:
        deletion_datetime = datetime.combine(deletion_date, datetime.min.time())
        task.deleted_at = deletion_datetime
    
    # CRITICAL: Delete ALL DailyTask records from deletion_date onward
    future_dailies = DailyTask.query.filter(
        DailyTask.task_id == task_id,
        DailyTask.user_id == current_user.id,
        DailyTask.date >= deletion_date
    ).all()
    
    for daily in future_dailies:
        db.session.delete(daily)
    
    db.session.commit()
    
    if deletion_date >= date.today():
        flash(f"Task '{task_title}' removed. Restore from Recently Deleted.")
    else:
        flash(f"Task '{task_title}' removed from {deletion_date.strftime('%B %d, %Y')} onward.")
    
    return redirect(url_for("dashboard", date=date_str))


@app.route("/history/delete-task-from-date", methods=["POST"])
@login_required
def delete_task_from_history():
    """Delete task from ONE specific date only."""
    
    task_id = request.form.get("task_id", type=int)
    date_str = request.form.get("date")
    
    if not task_id or not date_str:
        flash("Invalid request")
        return redirect(url_for("dashboard"))
    
    try:
        deletion_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date")
        return redirect(url_for("dashboard"))
    
    task = Task.query.filter_by(id=task_id, user_id=current_user.id).first()
    if not task:
        flash("Task not found")
        return redirect(url_for("dashboard"))
    
    # Delete ONLY this date (not onward!)
    daily_task = DailyTask.query.filter_by(
        task_id=task_id,
        user_id=current_user.id,
        date=deletion_date
    ).first()
    
    if daily_task:
        db.session.delete(daily_task)
        db.session.commit()
        flash(f"Task '{task.title}' removed from {deletion_date.strftime('%B %d, %Y')}.")
    
    return redirect(url_for("dashboard", date=date_str))

# ====================
# Category Management Routes
# ====================
@app.route("/categories/add", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def add_category():
    """
    Create a new category.
    Categories help organize tasks into groups.
    """
    name = sanitize_input(request.form.get("name", ""), max_length=50)

    if not name:
        flash("Category name is required.")
        return redirect(url_for("dashboard"))

    # Check if category already exists
    exists = Category.query.filter_by(
        user_id=current_user.id,
        name=name
    ).first()

    if exists:
        flash("Category already exists.")
        return redirect(url_for("dashboard"))

    # Create new category
    category = Category(name=name, user_id=current_user.id)
    db.session.add(category)
    db.session.commit()

    flash(f"Category '{name}' created!")
    return redirect(url_for("dashboard"))


@app.route("/categories/delete", methods=["POST"])
@login_required
def delete_category():
    """
    Delete a category and all its associated tasks.
    WARNING: This will permanently delete all tasks in the category.
    """
    category_id = request.form.get("category_id", type=int)

    if not category_id:
        flash("Invalid category.")
        return redirect(url_for("dashboard"))

    # Verify category belongs to user
    category = Category.query.filter_by(
        id=category_id,
        user_id=current_user.id
    ).first()

    if not category:
        flash("Category not found.")
        return redirect(url_for("dashboard"))

    category_name = category.name
    
    # Delete all tasks in this category first
    Task.query.filter_by(
        category_id=category_id,
        user_id=current_user.id
    ).delete()

    # Delete the category
    db.session.delete(category)
    db.session.commit()

    flash(f"Category '{category_name}' and all its tasks deleted.")
    return redirect(url_for("dashboard"))


# ====================
# PDF Export Routes
# ====================
@app.route("/export/pdf")
@login_required
def export_pdf():
    """
    Export yearly task report as PDF.
    Generates a PDF with all tasks and completion status for the current year.
    """
    year = date.today().year
    filename = f"dailyTasker_{current_user.id}_{year}.pdf"

    category_ids = request.args.getlist("category_ids", type=int)

    generate_year_pdf(
        filename=filename,
        user_id=current_user.id,
        year=year,
        category_ids=category_ids if category_ids else None,
        db=db,
        Task=Task,
        DailyTask=DailyTask
    )

    return send_file(
        filename,
        as_attachment=True,
        download_name=filename
    )


@app.route("/export/pdf/month/<int:year>/<int:month>")
@login_required
def export_month_pdf(year, month):
    """
    Export monthly task report as PDF.
    Generates a PDF for a specific month.
    """
    filename = f"dailyTasker_{current_user.id}_{year}_{month}.pdf"

    category_ids = request.args.getlist("category_ids", type=int)

    generate_month_pdf(
        filename=filename,
        user_id=current_user.id,
        year=year,
        month=month,
        category_ids=category_ids if category_ids else None,
        db=db,
        Task=Task,
        DailyTask=DailyTask
    )

    return send_file(
        filename,
        as_attachment=True,
        download_name=filename
    )


@app.route("/export/pdf/week/<start_date>")
@login_required
def export_week_pdf(start_date):
    """
    Export weekly task report as PDF.
    Generates a PDF for a specific week starting from start_date.
    """
    start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    filename = f"dailyTasker_{current_user.id}_week_{start_date}.pdf"

    category_ids = request.args.getlist("category_ids", type=int)

    generate_week_pdf(
        filename=filename,
        user_id=current_user.id,
        start_date=start_date,
        category_ids=category_ids if category_ids else None,
        db=db,
        Task=Task,
        DailyTask=DailyTask
    )

    return send_file(
        filename,
        as_attachment=True,
        download_name=filename
    )


# ====================
# PDF Sharing Routes
# ====================
@app.route("/share/pdf/<pdf_type>")
@login_required
def create_share_link(pdf_type):
    """
    Create a shareable link for PDF exports.
    Generates a time-limited token for sharing PDFs with others.
    
    Args:
        pdf_type: Type of PDF (year, month, or week)
    """
    expires_in = int(request.args.get("expires", 7))
    today = date.today()

    kwargs = {}
    if pdf_type == "year":
        kwargs["year"] = today.year
    elif pdf_type == "month":
        kwargs["year"] = today.year
        kwargs["month"] = today.month
    elif pdf_type == "week":
        # Start of current week (Monday)
        kwargs["start_date"] = today - timedelta(days=today.weekday())
    else:
        flash("Invalid PDF type requested")
        return redirect(url_for("dashboard"))

    # Generate the token
    token_obj = ShareToken.create(
        user_id=current_user.id,
        pdf_type=pdf_type,
        expires_in_days=expires_in,
        **kwargs
    )

    db.session.add(token_obj)
    db.session.commit()

    # Generate the full share URL
    share_url = url_for("shared_pdf", token=token_obj.token, _external=True)
    
    # Render a page showing the link instead of just flashing
    return render_template(
        "share_link.html",
        share_url=share_url,
        pdf_type=pdf_type,
        expires_in=expires_in
    )


@app.route("/shared/pdf/<token>")
def shared_pdf(token):
    """
    Access a shared PDF via token.
    Public endpoint for accessing shared PDFs without login.
    """
    share = ShareToken.query.filter_by(token=token).first_or_404()

    # Check if token has expired
    if share.expires_at < datetime.utcnow():
        abort(410, "This share link has expired")

    filename = f"shared_{token}.pdf"

    # Generate appropriate PDF based on type
    if share.pdf_type == "year":
        generate_year_pdf(
            filename,
            share.user_id,
            share.year,
            category_ids=None,
            db=db,
            Task=Task,
            DailyTask=DailyTask
        )
    elif share.pdf_type == "month":
        if not share.month or not share.year:
            abort(400, "Month or year not set in token")
        generate_month_pdf(
            filename,
            share.user_id,
            share.year,
            share.month,
            category_ids=None,
            db=db,
            Task=Task,
            DailyTask=DailyTask
        )
    elif share.pdf_type == "week":
        if not share.start_date:
            abort(400, "Start date not set in token")
        generate_week_pdf(
            filename,
            share.user_id,
            share.start_date,
            category_ids=None,
            db=db,
            Task=Task,
            DailyTask=DailyTask
        )

    return send_file(filename, as_attachment=True)


# ====================
# Settings Routes
# ====================
@app.route("/settings")
@login_required
def settings():
    """Display user settings page."""
    return render_template("settings.html")


@app.route("/profile/update", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def update_profile():
    """
    Update user profile (name, email, password).
    Allows users to change their account information.
    """
    name = sanitize_input(request.form.get("name", ""), max_length=100)
    email = request.form.get("email", "").strip().lower()
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    
    # Validate name and email
    if not name or not email:
        flash("Name and email are required.")
        return redirect(url_for("dashboard"))
    
    if not is_valid_email(email):
        flash("Invalid email format.")
        return redirect(url_for("dashboard"))
    
    # Check if email is already taken by another user
    existing_user = User.query.filter(
        User.email == email,
        User.id != current_user.id
    ).first()
    if existing_user:
        flash("Email already in use by another account.")
        return redirect(url_for("dashboard"))
    
    # Update name and email
    current_user.name = name
    current_user.email = email
    
    # Handle password change if requested
    if current_password or new_password or confirm_password:
        # All password fields must be filled
        if not (current_password and new_password and confirm_password):
            flash("To change password, fill in all password fields.")
            return redirect(url_for("dashboard"))
        
        # Verify current password
        if not check_password_hash(current_user.password_hash, current_password):
            flash("Current password is incorrect.")
            return redirect(url_for("dashboard"))
        
        # Validate new password
        if len(new_password) < 8:
            flash("New password must be at least 8 characters.")
            return redirect(url_for("dashboard"))
        
        # Check passwords match
        if new_password != confirm_password:
            flash("New passwords don't match.")
            return redirect(url_for("dashboard"))
        
        # Update password
        current_user.password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
        flash("Profile and password updated successfully!")
    else:
        flash("Profile updated successfully!")
    
    db.session.commit()
    return redirect(url_for("dashboard"))


@app.route("/update-reminders", methods=["POST"])
@login_required
def update_reminders():
    """
    Update email reminder settings.
    Allows users to enable/disable daily reminders and set reminder time.
    """
    # Checkbox only exists if checked
    current_user.reminders_enabled = "enabled" in request.form

    time_value = request.form.get("time")
    if time_value:
        try:
            # Handle both HH:MM and HH:MM:SS formats
            if len(time_value.split(':')) == 3:
                # HH:MM:SS format
                current_user.reminder_time = datetime.strptime(
                    time_value, "%H:%M:%S"
                ).time()
            else:
                # HH:MM format
                current_user.reminder_time = datetime.strptime(
                    time_value, "%H:%M"
                ).time()
        except ValueError as e:
            flash(f"Invalid time format: {e}")
            return redirect(url_for("dashboard"))
    else:
        current_user.reminder_time = None

    db.session.commit()
    flash("Reminder settings updated!")
    return redirect(url_for("dashboard"))


@app.route("/update-theme", methods=["POST"])
@login_required
def update_theme():
    """
    Update user's theme preference.
    Saves theme to database for cross-device sync.
    """
    theme = request.form.get("theme", "theme-light")
    
    # Validate theme
    if theme not in ["theme-light", "theme-dark"]:
        return {"success": False, "error": "Invalid theme"}, 400
    
    # Update user's theme in database
    current_user.theme = theme
    db.session.commit()
    
    return {"success": True, "theme": theme}, 200


# ====================
# Error Handlers
# ====================
@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    flash("Page not found.")
    return redirect(url_for("dashboard"))


@app.errorhandler(429)
def ratelimit_handler(e):
    """Handle rate limit errors."""
    flash("Too many requests. Please slow down and try again later.")
    return redirect(url_for("login")), 429


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    db.session.rollback()
    flash("An error occurred. Please try again.")
    return redirect(url_for("dashboard"))


# ====================
# Application Startup
# ====================

# Initialize database tables (runs even with gunicorn)
with app.app_context():
    db.create_all()

# Start background scheduler (runs even with gunicorn)
start_scheduler()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    
    # Start background scheduler
    start_scheduler()
    
    # Run application
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_ENV") != "production"
    )