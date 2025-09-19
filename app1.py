from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import mysql.connector
from mysql.connector import Error
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, time, timedelta
import json
from functools import wraps
from flask import Response
import csv
import io
import os

# Import centralized database configuration
from db_config import DBConfig

# Initialize the Flask app
app = Flask(__name__)
app.secret_key = DBConfig.SECRET_KEY
app.config.from_object(DBConfig)

# Database configuration - use centralized config
db_config = {
    'host': DBConfig.DB_HOST,
    'user': DBConfig.DB_USER,
    'password': DBConfig.DB_PASSWORD,
    'database': DBConfig.DB_NAME
}

def get_db_connection():
    """Establishes and returns a database connection using the centralized config."""
    try:
        conn = mysql.connector.connect(
            host=db_config['host'],
            user=db_config['user'],
            password=db_config['password'],
            database=db_config['database'],
            autocommit=False,
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci'
        )
        if conn.is_connected():
            return conn
        else:
            print("Failed to establish database connection")
            return None
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

def login_required(role=None):
    """
    Decorator to protect routes, enforcing login and role-based access.
    """
    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            if 'user_id' not in session:
                flash('Access denied. Please log in.', 'error')
                return redirect(url_for('login'))
            
            user_role = session.get('user_role')
            if role and user_role != role:
                flash(f'Access denied. You must be a {role}.', 'error')
                if user_role == 'faculty':
                    return redirect(url_for('faculty_dashboard'))
                elif user_role == 'hod':
                    return redirect(url_for('hod_dashboard'))
                elif user_role == 'CR':
                    return redirect(url_for('cr_dashboard'))
                else:
                    return redirect(url_for('login'))
            return fn(*args, **kwargs)
        return decorated_view
    return wrapper

@app.context_processor
def inject_now():
    """Injects the current datetime into all templates."""
    return {'now': datetime.now()}

# --- Authentication Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        if conn is None:
            flash('Database connection failed!', 'error')
            return render_template('login.html')

        cursor = conn.cursor(dictionary=True)
        user = None
        try:
            cursor.execute("""
                SELECT
                    u.user_id, u.email, u.password_hash, u.name, u.role,
                    s.section_id, s.name as section_name, b.year as batch_year, b.semester as batch_semester
                FROM users u
                LEFT JOIN sections s ON u.section_id = s.section_id
                LEFT JOIN batches b ON s.batch_id = b.batch_id
                WHERE u.email = %s
            """, (email,))
            user = cursor.fetchone()
        except Error as e:
            flash(f"Database error during login: {e}", 'error')
            return render_template('login.html')
        finally:
            cursor.close()
            conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['user_id']
            session['user_email'] = user['email']
            session['user_role'] = user['role']
            session['user_name'] = user['name']
            
            if user['role'] == 'CR':
                session['section_id'] = user['section_id']
                session['class_name'] = f"Year {user.get('batch_year', 'N/A')} - Semester {user.get('batch_semester', 'N/A')} - Section {user.get('section_name', 'N/A')}"
            
            flash(f"Logged in successfully as {user['name']}!", 'success')

            return redirect(url_for('indexes'))
        else:
            flash('Invalid email or password', 'error')

    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return jsonify({'redirect_url': url_for('login')}), 200

# --- General Routes ---
@app.route('/')
def indexes():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_role = session.get('user_role')
    if user_role == 'hod':
        return redirect(url_for('hod_dashboard'))
    elif user_role == 'faculty':
        return redirect(url_for('faculty_dashboard'))
    elif user_role == 'CR':
        return redirect(url_for('cr_dashboard'))
    else:
        flash('Dashboard not found for your role.', 'error')
        return redirect(url_for('login'))


# --- CR Dashboard Routes ---
@app.route('/cr_dashboard', methods=['GET', 'POST'])
@login_required('CR')
def cr_dashboard():
    """Enhanced CR dashboard with better functionality and UI."""
    cr_section_id = session.get('section_id')
    user_id = session.get('user_id')
    today = datetime.now().strftime('%A')
    current_time = datetime.now().time()

    connection = None
    try:
        connection = get_db_connection()
        if connection is None:
            flash("CRITICAL ERROR: Could not connect to the database. Please check your settings.", "danger")
            return render_template('error.html', message="Database Connection Failed. Check the terminal for more details.")

        cursor = connection.cursor(dictionary=True)

        # --- Fetch data for dropdowns ---
        cursor.execute("SELECT department_id, name FROM departments ORDER BY name;")
        departments = cursor.fetchall()
        cursor.execute("SELECT DISTINCT year FROM batches ORDER BY year;")
        years = cursor.fetchall()
        cursor.execute("SELECT DISTINCT semester FROM batches ORDER BY semester;")
        semesters = cursor.fetchall()

        # --- Initialize variables ---
        my_weekly_timetable = []
        subject_progress = []
        notifications = []
        cancellation_notifications = []
        selected_timetable = None
        selected_values = {}
        dashboard_stats = {}
        upcoming_classes = []
        free_periods_today = []
        my_semester = None

        if request.method == 'POST':
            dept_id = request.form.get('department')
            year = request.form.get('year')
            semester = request.form.get('semester')
            selected_values = {'dept_id': dept_id, 'year': year, 'semester': semester}

            cursor.execute("""
                SELECT DISTINCT
                    sec.name AS section_name,
                    tt.day_of_week,
                    ts.start_time, ts.end_time,
                    s.name AS subject_name,
                    u.name AS faculty_name,
                    r.room_number,
                    s.has_lab AS is_lab_session
                FROM timetable tt
                JOIN sections sec ON tt.section_id = sec.section_id
                JOIN batch_subjects bs ON tt.batch_subject_id = bs.batch_subject_id
                JOIN subjects s ON bs.subject_id = s.subject_id
                JOIN users u ON tt.faculty_id = u.user_id
                JOIN batches b ON sec.batch_id = b.batch_id
                JOIN batch_departments bd ON b.batch_id = bd.batch_id
                JOIN timeslots ts ON tt.timeslot_id = ts.timeslot_id
                LEFT JOIN rooms r ON tt.room_id = r.room_id
                WHERE bd.department_id = %s AND b.year = %s AND b.semester = %s AND tt.date IS NOT NULL
                ORDER BY sec.name, FIELD(tt.day_of_week, 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'), ts.start_time;
            """, (dept_id, year, semester))

            result = cursor.fetchall()
            selected_timetable = {}
            for row in result:
                if isinstance(row['start_time'], timedelta): row['start_time'] = (datetime.min + row['start_time']).strftime('%H:%M')
                if isinstance(row['end_time'], timedelta): row['end_time'] = (datetime.min + row['end_time']).strftime('%H:%M')
                section = row['section_name']
                if section not in selected_timetable: selected_timetable[section] = []
                selected_timetable[section].append(row)

        else:
            # This is the GET request block for the default view
            cursor.execute("""
                SELECT b.semester
                FROM sections s
                JOIN batches b ON s.batch_id = b.batch_id
                WHERE s.section_id = %s
            """, (cr_section_id,))
            cr_info = cursor.fetchone()
            my_semester = cr_info['semester'] if cr_info else None

            cursor.execute("""
                SELECT DISTINCT
                    tt.day_of_week,
                    ts.start_time, ts.end_time,
                    s.name AS subject_name,
                    u.name AS faculty_name,
                    r.room_number,
                    tt.is_lab_session,
                    tt.entry_id,
                    s.subject_id
                FROM timetable tt
                JOIN batch_subjects bs ON tt.batch_subject_id = bs.batch_subject_id
                JOIN subjects s ON bs.subject_id = s.subject_id
                JOIN users u ON tt.faculty_id = u.user_id
                JOIN timeslots ts ON tt.timeslot_id = ts.timeslot_id
                LEFT JOIN rooms r ON tt.room_id = r.room_id
                WHERE tt.section_id = %s AND tt.date IS NOT NULL
                ORDER BY FIELD(tt.day_of_week, 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'), ts.start_time;
            """, (cr_section_id,))

            my_weekly_timetable = cursor.fetchall()
            for entry in my_weekly_timetable:
                if isinstance(entry['start_time'], timedelta):
                    entry['start_time'] = (datetime.min + entry['start_time']).strftime('%H:%M')
                if isinstance(entry['end_time'], timedelta):
                    entry['end_time'] = (datetime.min + entry['end_time']).strftime('%H:%M')

            cursor.execute("""
                SELECT ts.start_time, ts.end_time, s.name AS subject_name,
                       u.name AS faculty_name, r.room_number
                FROM timetable tt
                JOIN batch_subjects bs ON tt.batch_subject_id = bs.batch_subject_id
                JOIN subjects s ON bs.subject_id = s.subject_id
                JOIN users u ON tt.faculty_id = u.user_id
                JOIN timeslots ts ON tt.timeslot_id = ts.timeslot_id
                LEFT JOIN rooms r ON tt.room_id = r.room_id
                WHERE tt.section_id = %s AND tt.day_of_week = %s AND ts.start_time > %s
                ORDER BY ts.start_time LIMIT 3;
            """, (cr_section_id, today, current_time))
            upcoming_classes = cursor.fetchall()
            for entry in upcoming_classes:
                if isinstance(entry['start_time'], timedelta):
                    entry['start_time'] = (datetime.min + entry['start_time']).strftime('%H:%M')
                if isinstance(entry['end_time'], timedelta):
                    entry['end_time'] = (datetime.min + entry['end_time']).strftime('%H:%M')

            cursor.execute("""
                SELECT
                    COUNT(DISTINCT bs.subject_id) as total_subjects,
                    COUNT(DISTINCT tt.entry_id) as total_classes_week,
                    COUNT(DISTINCT CASE WHEN tt.day_of_week = %s THEN tt.entry_id END) as classes_today
                FROM timetable tt
                JOIN batch_subjects bs ON tt.batch_subject_id = bs.batch_subject_id
                WHERE tt.section_id = %s;
            """, (today, cr_section_id))
            stats = cursor.fetchone()
            dashboard_stats = stats if stats else {'total_subjects': 0, 'total_classes_week': 0, 'classes_today': 0}

            try:
                cursor.execute("""
                    SELECT s.name as subject_name,
                           COALESCE(sp.planned_sessions, 0) as planned_sessions,
                           COALESCE(sp.completed_sessions, 0) as completed_sessions,
                           COALESCE(sp.completion_percentage, 0) as completion_percentage,
                           u.name as faculty_name
                    FROM subject_progress sp
                    JOIN batch_subjects bs ON sp.batch_subject_id = bs.batch_subject_id
                    JOIN subjects s ON bs.subject_id = s.subject_id
                    LEFT JOIN users u ON sp.faculty_id = u.user_id
                    WHERE sp.section_id = %s;
                """, (cr_section_id,))
                subject_progress = cursor.fetchall()
            except mysql.connector.Error:
                subject_progress = []

            try:
                cursor.execute("""
                    SELECT notification_id, message, timestamp, type, seen as is_read
                    FROM notifications
                    WHERE user_id = %s
                    ORDER BY timestamp DESC LIMIT 10;
                """, (user_id,))
                notifications = cursor.fetchall()
            except mysql.connector.Error:
                notifications = []

            try:
                cursor.execute("""
                    SELECT c.reason, c.timestamp, s.name AS subject_name, u.name AS faculty_name
                    FROM cancellations c
                    JOIN timetable tt ON c.timetable_id = tt.entry_id
                    JOIN batch_subjects bs ON tt.batch_subject_id = bs.batch_subject_id
                    JOIN subjects s ON bs.subject_id = s.subject_id
                    JOIN users u ON tt.faculty_id = u.user_id
                    WHERE tt.section_id = %s
                    ORDER BY c.timestamp DESC LIMIT 5;
                """, (cr_section_id,))
                cancellation_notifications = cursor.fetchall()
            except mysql.connector.Error:
                cancellation_notifications = []

            try:
                cursor.execute("""
                    SELECT ts.start_time, ts.end_time
                    FROM timeslots ts
                    WHERE ts.day_of_week = %s
                    AND NOT EXISTS (
                        SELECT 1 FROM timetable tt
                        WHERE tt.section_id = %s
                        AND tt.day_of_week = ts.day_of_week
                        AND tt.timeslot_id = ts.timeslot_id
                    )
                    ORDER BY ts.start_time;
                """, (today, cr_section_id))
                free_periods_today = cursor.fetchall()
                for period in free_periods_today:
                    if isinstance(period['start_time'], timedelta):
                        period['start_time'] = (datetime.min + period['start_time']).strftime('%H:%M')
                    if isinstance(period['end_time'], timedelta):
                        period['end_time'] = (datetime.min + period['end_time']).strftime('%H:%M')
            except mysql.connector.Error as err:
                print(f"Error fetching free periods: {err}")
                free_periods_today = []

        return render_template('cr_dashboard.html',
                               departments=departments, years=years, semesters=semesters,
                               selected_timetable=selected_timetable, selected_values=selected_values,
                               my_weekly_timetable=my_weekly_timetable, subject_progress=subject_progress,
                               notifications=notifications, cancellation_notifications=cancellation_notifications,
                               today=today, dashboard_stats=dashboard_stats, upcoming_classes=upcoming_classes,
                               free_periods_today=free_periods_today, my_semester=my_semester)

    except mysql.connector.Error as err:
        flash(f"Database query failed: {err}", 'danger')
        print(f"Error details: {err}")
        return render_template('error.html', message=f"A database query failed: {err}")
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()

@app.route('/request_free_period', methods=['POST'])
@login_required('CR')
def request_free_period():
    """Handle free period requests from CR."""
    user_id = session.get('user_id')

    data = request.get_json()
    period_time = data.get('period_time')
    reason = data.get('reason', 'Free period request')
    date_requested = data.get('date', datetime.now().strftime('%Y-%m-%d'))

    connection = None
    try:
        connection = get_db_connection()
        if connection is None:
            return jsonify({'success': False, 'message': 'Database connection failed'})

        cursor = connection.cursor()

        # Find the HOD for the CR's department
        cursor.execute("""
            SELECT u_hod.user_id FROM users u_cr
            JOIN departments d ON u_cr.department_id = d.department_id
            JOIN users u_hod ON d.department_id = u_hod.department_id
            WHERE u_cr.user_id = %s AND u_hod.role = 'hod'
        """, (user_id,))
        hod_user_id_row = cursor.fetchone()
        
        if hod_user_id_row:
            hod_user_id = hod_user_id_row[0]
            cursor.execute("""
                INSERT INTO notifications (user_id, message, type, seen)
                VALUES (%s, %s, 'free_period_request', 0)
            """, (hod_user_id, f"Section {session.get('class_name')} requested a free period for {period_time} on {date_requested}. Reason: {reason}"))
            connection.commit()
            return jsonify({'success': True, 'message': 'Free period request sent to HOD successfully'})
        else:
            return jsonify({'success': False, 'message': 'Could not find a HOD for your department to notify.'})

    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'Database error: {err}'})
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()


@app.route('/mark_notification_read/<int:notification_id>', methods=['POST'])
@login_required()
def mark_notification_read(notification_id):
    """Mark a notification as read."""
    connection = None
    try:
        connection = get_db_connection()
        if connection is None:
            return jsonify({'success': False, 'message': 'Database connection failed'})

        cursor = connection.cursor()
        cursor.execute("UPDATE notifications SET seen = 1 WHERE notification_id = %s AND user_id = %s", (notification_id, session['user_id']))
        connection.commit()

        return jsonify({'success': True})

    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'Database error: {err}'})
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()


@app.route('/api/get_sections')
@login_required('CR')
def get_sections():
    dept_id = request.args.get('department_id')
    year = request.args.get('year')
    semester = request.args.get('semester')

    if not all([dept_id, year, semester]):
        return jsonify({'error': 'Missing required parameters'}), 400

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT sec.section_id, sec.name
            FROM sections sec
            JOIN batches b ON sec.batch_id = b.batch_id
            JOIN batch_departments bd ON b.batch_id = bd.batch_id
            WHERE bd.department_id = %s AND b.year = %s AND b.semester = %s
            ORDER BY sec.name;
        """
        cursor.execute(query, (dept_id, year, semester))
        sections = cursor.fetchall()
        return jsonify(sections)
    except mysql.connector.Error as err:
        print(f"API Error in get_sections: {err}")
        return jsonify({'error': str(err)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

# --- Faculty Dashboard Routes ---
@app.route('/faculty_dashboard')
@login_required('faculty')
def faculty_dashboard():
    faculty_id = session['user_id']

    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return render_template('dashboard.html', notifications=[], substitute_requests=[], lecture_completion=[], faculty_timetable=[], faculty_list=[], current_user_name=session['user_name'])

    cursor = conn.cursor(dictionary=True)
    
    # Initialize variables before the try block
    notifications = []
    substitute_requests = []
    lecture_completion = []
    all_timetable_entries = []
    faculty_list = []

    try:
        cursor.execute("SELECT message, timestamp, seen AS is_read FROM notifications WHERE user_id = %s ORDER BY timestamp DESC LIMIT 5", (faculty_id,))
        notifications = cursor.fetchall()

        cursor.execute("""
            SELECT
                sr.request_id,
                c.reason AS cancellation_reason,
                u.name AS requested_by_faculty,
                s.name AS subject_name,
                sec.name AS section_name,
                t.date AS class_date,
                ts.start_time,
                ts.end_time,
                sr.status
            FROM substitute_requests sr
            JOIN cancellations c ON sr.cancellation_id = c.cancellation_id
            JOIN timetable t ON c.timetable_id = t.entry_id
            JOIN users u ON c.canceled_by = u.user_id
            JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            JOIN sections sec ON t.section_id = sec.section_id
            JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
            WHERE sr.requested_to = %s
            ORDER BY sr.responded_at IS NULL DESC, c.timestamp DESC
        """, (faculty_id,))
        substitute_requests = cursor.fetchall()

        cursor.execute("""
            SELECT
                s.name AS subject_name,
                sec.name AS section_name,
                t.date AS class_date,
                ts.start_time,
                ts.end_time,
                'completed' AS status
            FROM timetable t
            JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            JOIN sections sec ON t.section_id = sec.section_id
            JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
            WHERE t.faculty_id = %s AND t.is_completed = 1
            ORDER BY t.date DESC
            LIMIT 5
        """, (faculty_id,))
        lecture_completion = cursor.fetchall()

        cursor.execute("""
            SELECT
                t.entry_id,
                t.date AS entry_date,
                t.day_of_week,
                ts.start_time,
                ts.end_time,
                s.name AS subject_name,
                sec.name AS section_name,
                r.room_number,
                t.is_cancelled,
                t.is_completed
            FROM timetable t
            JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            JOIN sections sec ON t.section_id = sec.section_id
            JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
            LEFT JOIN rooms r ON t.room_id = r.room_id
            WHERE t.faculty_id = %s
            ORDER BY t.date, ts.start_time
        """, (faculty_id,))

        for entry in cursor.fetchall():
            entry['start_time'] = str(entry['start_time'])
            entry['end_time'] = str(entry['end_time'])
            entry['entry_date'] = str(entry['entry_date'])

            if entry['is_completed']:
                entry['type'] = 'completed'
            elif entry['is_cancelled']:
                entry['type'] = 'cancelled'
            else:
                entry['type'] = 'scheduled'

            if entry['type'] == 'cancelled':
                reason_cursor = conn.cursor(dictionary=True)
                reason_cursor.execute("SELECT reason FROM cancellations WHERE timetable_id = %s", (entry['entry_id'],))
                reason_row = reason_cursor.fetchone()
                if reason_row:
                    entry['status_reason'] = reason_row['reason']
                reason_cursor.close()

            all_timetable_entries.append(entry)

        cursor.execute("SELECT user_id AS faculty_id, name AS faculty_name FROM users WHERE role = 'faculty' AND user_id != %s ORDER BY name", (faculty_id,))
        faculty_list = cursor.fetchall()

    except Error as e:
        flash(f"Error fetching dashboard data: {e}", 'error')
    finally:
        cursor.close()
        conn.close()

    return render_template('dashboard.html',
                           current_user_name=session['user_name'],
                           notifications=notifications,
                           substitute_requests=substitute_requests,
                           lecture_completion=lecture_completion,
                           faculty_timetable=all_timetable_entries,
                           faculty_list=faculty_list)

@app.route('/api/faculty/list')
@login_required('faculty')
def get_faculty_list():
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500

    cursor = conn.cursor(dictionary=True)
    faculty_list = []
    try:
        cursor.execute("SELECT user_id AS faculty_id, name AS faculty_name FROM users WHERE role = 'faculty' AND user_id != %s ORDER BY name", (session['user_id'],))
        faculty_list = cursor.fetchall()
        return jsonify(faculty_list)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/faculty/current/cancel_class', methods=['POST'])
@login_required('faculty')
def cancel_class():
    data = request.json
    timetable_entry_id = data.get('timetable_entry_id')
    reason = data.get('reason')

    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500

    cursor = conn.cursor()
    try:
        cursor.execute("SELECT entry_id FROM timetable WHERE entry_id = %s AND faculty_id = %s", (timetable_entry_id, session['user_id']))
        if not cursor.fetchone():
            return jsonify({'error': 'Unauthorized to cancel this class.'}), 403

        cursor.execute("INSERT INTO cancellations (timetable_id, reason, canceled_by) VALUES (%s, %s, %s)", (timetable_entry_id, reason, session['user_id']))
        cursor.execute("UPDATE timetable SET is_cancelled = 1, modified_at = NOW() WHERE entry_id = %s", (timetable_entry_id,))

        conn.commit()
        return jsonify({'message': 'Class canceled successfully.'}), 200
    except Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/faculty/current/update_lecture_status', methods=['POST'])
@login_required('faculty')
def update_lecture_status():
    data = request.json
    timetable_entry_id = data.get('timetable_entry_id')
    status = data.get('status')

    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500

    cursor = conn.cursor()
    try:
        # Check if the faculty is authorized to update this lecture.
        cursor.execute("SELECT faculty_id FROM timetable WHERE entry_id = %s", (timetable_entry_id,))
        record = cursor.fetchone()
        if record is None or record[0] != session['user_id']:
            return jsonify({'error': 'Unauthorized to update this lecture.'}), 403

        if status == 'completed':
            cursor.execute("UPDATE timetable SET is_completed = 1, is_cancelled = 0, is_rescheduled = 0, modified_at = NOW() WHERE entry_id = %s AND faculty_id = %s", (timetable_entry_id, session['user_id']))
            message = "Lecture marked as completed."
        elif status == 'pending':
            cursor.execute("UPDATE timetable SET is_completed = 0, is_cancelled = 0, is_rescheduled = 0, modified_at = NOW() WHERE entry_id = %s AND faculty_id = %s", (timetable_entry_id, session['user_id']))
            message = "Lecture status reset to scheduled."
        else:
            return jsonify({'error': 'Invalid status provided.'}), 400

        conn.commit()
        return jsonify({'message': message}), 200
    except Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/faculty/current/request_substitute', methods=['POST'])
@login_required('faculty')
def request_substitute():
    data = request.json
    timetable_entry_id = data.get('timetable_entry_id')
    requested_to_faculty_id = data.get('requested_to_faculty_id')
    reason = data.get('reason')

    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500

    cursor = conn.cursor()
    try:
        # Ensure the faculty member is the one assigned to the class.
        cursor.execute("SELECT faculty_id FROM timetable WHERE entry_id = %s", (timetable_entry_id,))
        class_faculty_id = cursor.fetchone()
        if class_faculty_id is None or class_faculty_id[0] != session['user_id']:
            return jsonify({'error': 'You are not authorized to request a substitute for this class.'}), 403

        cursor.execute("SELECT cancellation_id FROM cancellations WHERE timetable_id = %s AND canceled_by = %s", (timetable_entry_id, session['user_id']))
        cancellation = cursor.fetchone()

        if not cancellation:
            cursor.execute("INSERT INTO cancellations (timetable_id, reason, canceled_by) VALUES (%s, %s, %s)", (timetable_entry_id, reason, session['user_id']))
            conn.commit()
            cancellation_id = cursor.lastrowid
        else:
            cancellation_id = cancellation[0]

        cursor.execute("SELECT request_id FROM substitute_requests WHERE cancellation_id = %s AND requested_to = %s AND status = 'pending'", (cancellation_id, requested_to_faculty_id))
        if cursor.fetchone():
            return jsonify({'error': 'A pending request to this faculty member already exists.'}), 409

        cursor.execute("INSERT INTO substitute_requests (cancellation_id, requested_to, status) VALUES (%s, %s, 'pending')", (cancellation_id, requested_to_faculty_id))

        notification_message = f"Substitute request from {session['user_name']} for a class on {datetime.date.today()}. Reason: {reason}"
        cursor.execute("INSERT INTO notifications (user_id, type, message) VALUES (%s, 'substitute_request', %s)", (requested_to_faculty_id, notification_message))

        conn.commit()
        return jsonify({'message': 'Substitute request sent successfully.'}), 200
    except Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/faculty/current/respond_substitute/<int:request_id>', methods=['POST'])
@login_required('faculty')
def respond_to_substitute(request_id):
    data = request.json
    status = data.get('status')

    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        if status not in ['accepted', 'rejected']:
            return jsonify({'error': 'Invalid status provided.'}), 400

        cursor.execute("SELECT * FROM substitute_requests WHERE request_id = %s AND requested_to = %s AND status = 'pending'", (request_id, session['user_id']))
        request_data = cursor.fetchone()

        if not request_data:
            return jsonify({'error': 'Substitute request not found or already responded to.'}), 404

        cursor.execute("UPDATE substitute_requests SET status = %s, responded_at = NOW() WHERE request_id = %s", (status, request_id))

        if status == 'accepted':
            cursor.execute("SELECT timetable_id FROM cancellations WHERE cancellation_id = %s", (request_data['cancellation_id'],))
            cancellation_info = cursor.fetchone()
            if cancellation_info:
                timetable_id = cancellation_info['timetable_id']

                cursor.execute("SELECT canceled_by FROM cancellations WHERE cancellation_id = %s", (request_data['cancellation_id'],))
                original_faculty_id = cursor.fetchone()['canceled_by']

                cursor.execute("UPDATE timetable SET faculty_id = %s, is_rescheduled = 1, is_cancelled = 0 WHERE entry_id = %s", (session['user_id'], timetable_id))

                notification_message = f"Your substitute request has been accepted by {session['user_name']}."
                cursor.execute("INSERT INTO notifications (user_id, type, message) VALUES (%s, 'substitute_accepted', %s)", (original_faculty_id, notification_message))

        elif status == 'rejected':
            cursor.execute("SELECT canceled_by FROM cancellations WHERE cancellation_id = %s", (request_data['cancellation_id'],))
            original_faculty_id = cursor.fetchone()['canceled_by']

            notification_message = f"Your substitute request has been rejected by {session['user_name']}."
            cursor.execute("INSERT INTO notifications (user_id, type, message) VALUES (%s, 'substitute_rejected', %s)", (original_faculty_id, notification_message))

        conn.commit()
        return jsonify({'message': f"Request {status} successfully."}), 200
    except Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# --- HOD Dashboard Routes ---
@app.route('/hod_dashboard')
@login_required('hod')
def hod_dashboard():
    return render_template('hod_dashboard.html', user_name=session['user_name'])

@app.route('/api/hod/options/years')
@login_required('hod')
def get_years():
    conn = get_db_connection()
    if conn is None:
        return jsonify([])
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT DISTINCT year FROM batches ORDER BY year;")
        years = [{'year_id': row['year'], 'year_name': row['year']} for row in cursor.fetchall()]
        return jsonify(years)
    except Error as e:
        print(f"Error fetching years: {e}")
        return jsonify([])
    finally:
        cursor.close()
        conn.close()

@app.route('/api/hod/options/semesters')
@login_required('hod')
def get_semesters():
    conn = get_db_connection()
    if conn is None:
        return jsonify([])
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT DISTINCT semester FROM batches ORDER BY semester;")
        semesters = cursor.fetchall()
        return jsonify(semesters)
    except Error as e:
        print(f"Error fetching semesters: {e}")
        return jsonify([])
    finally:
        cursor.close()
        conn.close()

@app.route('/api/hod/options/faculty')
@login_required('hod')
def get_faculty():
    conn = get_db_connection()
    if conn is None:
        return jsonify([])
    cursor = conn.cursor(dictionary=True)
    try:
        hod_user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (hod_user_id,))
        dept_info = cursor.fetchone()

        if dept_info and dept_info['department_id']:
            dept_id = dept_info['department_id']
            cursor.execute("SELECT user_id AS faculty_id, name AS faculty_name FROM users WHERE role = 'faculty' AND department_id = %s ORDER BY name", (dept_id,))
        else:
            cursor.execute("SELECT user_id AS faculty_id, name AS faculty_name FROM users WHERE role = 'faculty' ORDER BY name")

        faculty = cursor.fetchall()
        return jsonify(faculty)
    except Error as e:
        print(f"Error fetching faculty list: {e}")
        return jsonify([])
    finally:
        cursor.close()
        conn.close()

@app.route('/api/hod/department/progress')
@login_required('hod')
def get_department_progress():
    conn = get_db_connection()
    if conn is None:
        return jsonify([])

    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (user_id,))
        hod_department_id_row = cursor.fetchone()

        if not hod_department_id_row:
            cursor.execute("""
                SELECT
                    sp.planned_sessions,
                    sp.completed_sessions,
                    s.name AS subject_name,
                    b.semester,
                    d.name as department_name
                FROM subject_progress sp
                JOIN batch_subjects bs ON sp.batch_subject_id = bs.batch_subject_id
                JOIN subjects s ON bs.subject_id = s.subject_id
                JOIN sections sec ON sp.section_id = sec.section_id
                JOIN batches b ON sec.batch_id = b.batch_id
                JOIN batch_departments bd ON b.batch_id = bd.batch_id
                JOIN departments d ON bd.department_id = d.department_id
                GROUP BY sp.batch_subject_id, d.name
            """)
        else:
            hod_department_id = hod_department_id_row['department_id']
            cursor.execute("""
                SELECT
                    sp.planned_sessions,
                    sp.completed_sessions,
                    s.name AS subject_name,
                    b.semester,
                    d.name as department_name
                FROM subject_progress sp
                JOIN sections sec ON sp.section_id = sec.section_id
                JOIN batches b ON sec.batch_id = b.batch_id
                JOIN batch_departments bd ON b.batch_id = bd.batch_id
                JOIN batch_subjects bs ON sp.batch_subject_id = bs.batch_subject_id
                JOIN subjects s ON bs.subject_id = s.subject_id
                JOIN departments d ON bd.department_id = d.department_id
                WHERE bd.department_id = %s
                GROUP BY sp.batch_subject_id, d.name
            """, (hod_department_id,))

        progress_data = cursor.fetchall()

        for item in progress_data:
            item['completion_percentage'] = (item['completed_sessions'] / item['planned_sessions'] * 100) if item['planned_sessions'] > 0 else 0

        return jsonify(progress_data)
    except Error as e:
        print(f"Error fetching HOD progress data: {e}")
        return jsonify([])
    finally:
        cursor.close()
        conn.close()

@app.route('/api/hod/department/lagging_subjects')
@login_required('hod')
def get_lagging_subjects():
    conn = get_db_connection()
    if conn is None:
        return jsonify([])

    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (user_id,))
        hod_department_id_row = cursor.fetchone()

        if not hod_department_id_row:
            return jsonify([])

        hod_department_id = hod_department_id_row['department_id']

        cursor.execute("""
            SELECT
                s.name AS subject_name,
                sec.name AS section_name,
                sp.planned_sessions AS total_sessions,
                sp.completed_sessions
            FROM subject_progress sp
            JOIN sections sec ON sp.section_id = sec.section_id
            JOIN batch_departments bd ON sec.batch_id = bd.batch_id
            JOIN batch_subjects bs ON sp.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            WHERE bd.department_id = %s
            AND (sp.completed_sessions / sp.planned_sessions) * 100 < 50
            ORDER BY (sp.completed_sessions / sp.planned_sessions) ASC
        """, (hod_department_id,))

        lagging_subjects = cursor.fetchall()

        for subject in lagging_subjects:
            subject['completion_percentage'] = (subject['completed_sessions'] / subject['total_sessions'] * 100) if subject['total_sessions'] > 0 else 0

        return jsonify(lagging_subjects)
    except Error as e:
        print(f"Error fetching lagging subjects: {e}")
        return jsonify([])
    finally:
        cursor.close()
        conn.close()

@app.route('/api/hod/department/timetable')
@login_required('hod')
def get_department_timetable():
    conn = get_db_connection()
    if conn is None:
        return jsonify([])

    cursor = conn.cursor(dictionary=True)
    try:
        year = request.args.get('year')
        semester = request.args.get('semester')
        faculty_id = request.args.get('faculty_id')

        user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (user_id,))
        hod_department_id_row = cursor.fetchone()

        if not hod_department_id_row:
            return jsonify([])
        
        hod_department_id = hod_department_id_row['department_id']

        query = """
            SELECT
                t.entry_id,
                t.date AS entry_date,
                t.day_of_week,
                ts.start_time,
                ts.end_time,
                s.name AS subject_name,
                u.name AS faculty_name,
                sec.name AS section_name,
                r.room_number AS classroom_name,
                t.is_cancelled
            FROM timetable t
            JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            JOIN users u ON t.faculty_id = u.user_id
            JOIN sections sec ON t.section_id = sec.section_id
            JOIN batches b ON sec.batch_id = b.batch_id
            JOIN batch_departments bd ON b.batch_id = bd.batch_id
            JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
            LEFT JOIN rooms r ON t.room_id = r.room_id
            WHERE bd.department_id = %s
        """
        params = [hod_department_id]

        if year:
            query += " AND b.year = %s"
            params.append(year)
        if semester:
            query += " AND b.semester = %s"
            params.append(semester)
        if faculty_id:
            query += " AND t.faculty_id = %s"
            params.append(faculty_id)

        query += " ORDER BY t.date, ts.start_time"

        cursor.execute(query, tuple(params))

        timetable_data = cursor.fetchall()

        for entry in timetable_data:
            entry['start_time'] = str(entry['start_time'])
            entry['end_time'] = str(entry['end_time'])
            entry['entry_date'] = str(entry['entry_date'])
            entry['type'] = 'cancelled' if entry['is_cancelled'] else 'scheduled'
            
            if entry['is_cancelled']:
                cancel_cursor = conn.cursor(dictionary=True)
                cancel_cursor.execute("SELECT reason FROM cancellations WHERE timetable_id = %s", (entry['entry_id'],))
                reason = cancel_cursor.fetchone()
                entry['status_reason'] = reason['reason'] if reason else 'N/A'
                cancel_cursor.close()

        return jsonify(timetable_data)
    except Error as e:
        print(f"Error fetching department timetable: {e}")
        return jsonify([])
    finally:
        cursor.close()
        conn.close()

@app.route('/api/hod/personal_timetable')
@login_required('hod')
def get_hod_personal_timetable():
    conn = get_db_connection()
    if conn is None:
        return jsonify([])

    cursor = conn.cursor(dictionary=True)

    try:
        user_id = session['user_id']

        cursor.execute("""
            SELECT
                t.entry_id,
                t.date AS entry_date,
                t.day_of_week,
                ts.start_time,
                ts.end_time,
                s.name AS subject_name,
                sec.name AS section_name,
                r.room_number AS classroom_name,
                t.is_cancelled
            FROM timetable t
            JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            JOIN sections sec ON t.section_id = sec.section_id
            JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
            LEFT JOIN rooms r ON t.room_id = r.room_id
            WHERE t.faculty_id = %s
            ORDER BY t.date, ts.start_time
        """, (user_id,))

        timetable_data = cursor.fetchall()

        for entry in timetable_data:
            entry['start_time'] = str(entry['start_time'])
            entry['end_time'] = str(entry['end_time'])
            entry['entry_date'] = str(entry['entry_date'])
            entry['type'] = 'cancelled' if entry['is_cancelled'] else 'scheduled'
            if entry['is_cancelled']:
                cancel_cursor = conn.cursor(dictionary=True)
                cancel_cursor.execute("SELECT reason FROM cancellations WHERE timetable_id = %s", (entry['entry_id'],))
                reason = cancel_cursor.fetchone()
                entry['status_reason'] = reason['reason'] if reason else 'N/A'
                cancel_cursor.close()

        return jsonify(timetable_data)
    except Error as e:
        print(f"Error fetching HOD personal timetable: {e}")
        return jsonify([])
    finally:
        cursor.close()
        conn.close()

# --- CSV Report Generation Routes ---
@app.route('/api/hod/reports/progress_csv')
@login_required('hod')
def download_progress_csv():
    conn = get_db_connection()
    if conn is None:
        return Response("Database connection failed", status=500)

    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (user_id,))
        hod_department_id_row = cursor.fetchone()

        if not hod_department_id_row:
            return Response("HOD department not found", status=404)

        hod_department_id = hod_department_id_row['department_id']

        cursor.execute("""
            SELECT
                s.name AS subject_name,
                sec.name AS section_name,
                b.semester,
                sp.planned_sessions,
                sp.completed_sessions
            FROM subject_progress sp
            JOIN sections sec ON sp.section_id = sec.section_id
            JOIN batches b ON sec.batch_id = b.batch_id
            JOIN batch_departments bd ON b.batch_id = bd.batch_id
            JOIN batch_subjects bs ON sp.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            WHERE bd.department_id = %s
            ORDER BY s.name, sec.name
        """, (hod_department_id,))

        data = cursor.fetchall()

        if not data:
            return Response("No data to generate report.", status=404)

        output = io.StringIO()
        fieldnames = ['subject_name', 'section_name', 'semester', 'planned_sessions', 'completed_sessions']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=department_progress_report.csv"}
        )
    except Error as e:
        print(f"Error generating CSV report: {e}")
        return Response("Error generating report", status=500)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/hod/reports/timetable_csv')
@login_required('hod')
def download_timetable_csv():
    conn = get_db_connection()
    if conn is None:
        return Response("Database connection failed", status=500)

    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (user_id,))
        hod_department_id_row = cursor.fetchone()

        if not hod_department_id_row:
            return Response("HOD department not found", status=404)
        
        hod_department_id = hod_department_id_row['department_id']

        cursor.execute("""
            SELECT
                t.date,
                t.day_of_week,
                ts.start_time,
                ts.end_time,
                s.name AS subject_name,
                u.name AS faculty_name,
                sec.name AS section_name,
                r.room_number AS classroom_name,
                t.is_cancelled
            FROM timetable t
            JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            JOIN users u ON t.faculty_id = u.user_id
            JOIN sections sec ON t.section_id = sec.section_id
            JOIN batches b ON sec.batch_id = b.batch_id
            JOIN batch_departments bd ON b.batch_id = bd.batch_id
            JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
            LEFT JOIN rooms r ON t.room_id = r.room_id
            WHERE bd.department_id = %s
            ORDER BY t.date, ts.start_time
        """, (hod_department_id,))

        data = cursor.fetchall()

        for row in data:
            row['start_time'] = str(row['start_time'])
            row['end_time'] = str(row['end_time'])
            row['date'] = str(row['date'])
            row['status'] = 'Cancelled' if row['is_cancelled'] else 'Scheduled'
            del row['is_cancelled']

        if not data:
            return Response("No data to generate report.", status=404)

        output = io.StringIO()
        fieldnames = ['date', 'day_of_week', 'start_time', 'end_time', 'subject_name', 'faculty_name', 'section_name', 'classroom_name', 'status']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=department_timetable_report.csv"}
        )
    except Error as e:
        print(f"Error generating CSV report: {e}")
        return Response("Error generating report", status=500)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/hod/reports/lagging_csv')
@login_required('hod')
def download_lagging_csv():
    conn = get_db_connection()
    if conn is None:
        return Response("Database connection failed", status=500)

    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (user_id,))
        hod_department_id_row = cursor.fetchone()

        if not hod_department_id_row:
            return Response("HOD department not found", status=404)
            
        hod_department_id = hod_department_id_row['department_id']

        cursor.execute("""
            SELECT
                s.name AS subject_name,
                sec.name AS section_name,
                sp.planned_sessions AS total_sessions,
                sp.completed_sessions
            FROM subject_progress sp
            JOIN sections sec ON sp.section_id = sec.section_id
            JOIN batch_departments bd ON sec.batch_id = bd.batch_id
            JOIN batch_subjects bs ON sp.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            WHERE bd.department_id = %s
            AND (sp.completed_sessions / sp.planned_sessions) * 100 < 50
            ORDER BY (sp.completed_sessions / sp.planned_sessions) ASC
        """, (hod_department_id,))

        data = cursor.fetchall()

        for row in data:
            row['completion_percentage'] = f"{round((row['completed_sessions'] / row['total_sessions']) * 100, 2) if row['total_sessions'] > 0 else 0}%"

        if not data:
            return Response("No data to generate report.", status=404)

        output = io.StringIO()
        fieldnames = ['subject_name', 'section_name', 'total_sessions', 'completed_sessions', 'completion_percentage']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=lagging_subjects_report.csv"}
        )
    except Error as e:
        print(f"Error generating CSV report: {e}")
        return Response("Error generating report", status=500)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/hod/reports/personal_timetable_csv')
@login_required('hod')
def download_hod_personal_timetable_csv():
    conn = get_db_connection()
    if conn is None:
        return Response("Database connection failed", status=500)

    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session['user_id']

        cursor.execute("""
            SELECT
                t.date AS entry_date,
                t.day_of_week,
                ts.start_time,
                ts.end_time,
                s.name AS subject_name,
                sec.name AS section_name,
                r.room_number AS classroom_name,
                t.is_cancelled
            FROM timetable t
            JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            JOIN sections sec ON t.section_id = sec.section_id
            JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
            LEFT JOIN rooms r ON t.room_id = r.room_id
            WHERE t.faculty_id = %s
            ORDER BY t.date, ts.start_time
        """, (user_id,))

        data = cursor.fetchall()

        for row in data:
            row['start_time'] = str(row['start_time'])
            row['end_time'] = str(row['end_time'])
            row['entry_date'] = str(row['entry_date'])
            row['status'] = 'Cancelled' if row['is_cancelled'] else 'Scheduled'
            del row['is_cancelled']

        if not data:
            return Response("No data to generate report.", status=404)

        output = io.StringIO()
        fieldnames = ['entry_date', 'day_of_week', 'start_time', 'end_time', 'subject_name', 'section_name', 'classroom_name', 'status']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=hod_personal_timetable.csv"}
        )
    except Error as e:
        print(f"Error generating CSV report: {e}")
        return Response("Error generating report", status=500)
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)