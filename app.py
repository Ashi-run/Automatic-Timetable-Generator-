from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from mysql.connector import Error
import json
import logging
from datetime import datetime, timedelta, date
from functools import wraps
import csv
import io
import os
from decimal import Decimal


# Placeholder for a separate DB configuration file (as in app1.py)
class DBConfig:
    DB_HOST = '127.0.0.1'
    DB_USER = 'root'
    DB_PASSWORD = ''
    DB_NAME = 'reclassify'
    SECRET_KEY = 'nmims_timetable_secret_key_2025'

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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- UTILITY FUNCTIONS ---

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
                elif user_role == 'academic_coordinator':
                    return redirect(url_for('academic_coordinator_dashboard'))
                else:
                    return redirect(url_for('login'))
            return fn(*args, **kwargs)
        return decorated_view
    return wrapper

@app.context_processor
def inject_globals():
    """Injects global variables into all templates."""
    current_school_obj = None
    if 'school_id' in session:
        schools = get_schools() 
        current_school_obj = next((s for s in schools if s['school_id'] == session['school_id']), None)

    return dict(
        current_school=current_school_obj, 
        current_year=datetime.now().year,
        current_semester="Spring" if datetime.now().month < 6 else "Fall"
    )

def is_valid_table(table_name):
    conn = get_db_connection()
    if not conn:
        return False
    cursor = conn.cursor()
    try:
        cursor.execute("SHOW TABLES LIKE %s", (table_name,))
        return cursor.fetchone() is not None
    except Error:
        return False
    finally:
        cursor.close()
        conn.close()

class TimetableGenerator:
    def _execute_query(self, query, params=None, fetch_one=False):
        conn = get_db_connection()
        if not conn:
            return None
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(query, params)
            if fetch_one:
                return cursor.fetchone()
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    def load_specific_timetable(self, log_id):
        conn = get_db_connection()
        if not conn: return {"error": "DB connection failed."}
        cursor = conn.cursor(dictionary=True)
        try:
            log_query = "SELECT * FROM timetable_generation_log WHERE log_id = %s"
            log_entry = self._execute_query(log_query, (log_id,), fetch_one=True)
            if not log_entry: return {"error": "Log entry not found."}

            timetable_query = """
                SELECT t.*, s.name AS subject_name, u.name AS faculty_name, r.room_number, ts.start_time, ts.end_time
                FROM timetable t
                JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
                JOIN subjects s ON bs.subject_id = s.subject_id
                JOIN users u ON t.faculty_id = u.user_id
                LEFT JOIN rooms r ON t.room_id = r.room_id
                JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
                WHERE t.log_id = %s
                ORDER BY t.date, ts.start_time
            """
            raw_timetable = self._execute_query(timetable_query, (log_id,))
            
            section_query = "SELECT name, batch_id FROM sections WHERE section_id = %s"
            section_info = self._execute_query(section_query, (log_entry['section_id'],), fetch_one=True)

            timetable = {}
            for entry in raw_timetable:
                day = entry['day_of_week']
                start_time_str = entry['start_time'].strftime('%H:%M')
                if day not in timetable:
                    timetable[day] = {}
                timetable[day][start_time_str] = {
                    'subject': entry['subject_name'],
                    'faculty': entry['faculty_name'],
                    'room': entry['room_number']
                }

            timeslot_labels = self._execute_query("SELECT day_of_week, start_time, end_time FROM timeslots ORDER BY day_of_week, start_time")
            timeslot_labels = sorted(list(set([(ts['day_of_week'], ts['start_time'].strftime('%H:%M')) for ts in timeslot_labels])))
            
            grid = self.build_grid(raw_timetable)
            
            return {
                'section_id': log_entry['section_id'],
                'section_name': section_info['name'],
                'timetable': timetable,
                'generation_log': log_entry,
                'raw_timetable': raw_timetable,
                'grid': grid,
                'timeslot_labels': timeslot_labels,
                'start_date': log_entry['generation_date'],
                'end_date': log_entry['generation_date'] + timedelta(weeks=1)
            }
        except Exception as e:
            return {"error": f"Error loading timetable: {str(e)}"}
        finally:
            cursor.close()
            conn.close()
    
    def load_specific_timetable_raw(self, log_id):
        conn = get_db_connection()
        if not conn: return None
        cursor = conn.cursor(dictionary=True)
        try:
            timetable_query = """
                SELECT t.*, s.name AS subject_name, u.name AS faculty_name, r.room_number, ts.start_time, ts.end_time
                FROM timetable t
                JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
                JOIN subjects s ON bs.subject_id = s.subject_id
                JOIN users u ON t.faculty_id = u.user_id
                LEFT JOIN rooms r ON t.room_id = r.room_id
                JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
                WHERE t.log_id = %s
                ORDER BY t.date, ts.start_time
            """
            cursor.execute(timetable_query, (log_id,))
            raw_timetable = cursor.fetchall()
            return raw_timetable
        except Exception as e:
            logger.error(f"Error loading raw timetable data: {e}", exc_info=True)
            return None
        finally:
            cursor.close()
            conn.close()

    def build_grid(self, raw_timetable):
        days_of_week = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        all_timeslots = self._execute_query("SELECT start_time FROM timeslots WHERE is_active = 1 ORDER BY start_time")
        timeslot_headers = sorted([str(t['start_time']) for t in all_timeslots])
        
        grid = {day: {ts: None for ts in timeslot_headers} for day in days_of_week}
        
        for entry in raw_timetable:
            day = entry['day_of_week']
            start_time = str(entry['start_time'])
            
            if day in grid and start_time in grid[day]:
                grid[day][start_time] = entry
        return grid
    
    def get_all_generation_logs(self, status_filter=None):
        conn = get_db_connection()
        if not conn:
            return []
        cursor = conn.cursor(dictionary=True)
        try:
            query = "SELECT log_id, section_id, generation_date, status, total_slots_assigned, total_slots_required FROM timetable_generation_log"
            params = []
            if status_filter:
                query += " WHERE status = %s"
                params.append(status_filter)
            query += " ORDER BY generation_date DESC"
            cursor.execute(query, params)
            return cursor.fetchall()
        except Error as e:
            logger.error(f"Error fetching generation logs: {e}")
            return []
        finally:
            cursor.close()
            conn.close()
    
    def get_subject_progress_for_department_and_semester(self, department_id, semester_number, academic_year, start_date, end_date):
        # This is a complex function. For this exercise, I'll provide a simplified version.
        query = """
            SELECT s.name AS subject_name, sp.planned_sessions, sp.completed_sessions
            FROM subject_progress sp
            JOIN batch_subjects bs ON sp.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            JOIN sections sec ON sp.section_id = sec.section_id
            JOIN batches b ON sec.batch_id = b.batch_id
            JOIN academic_years ay ON b.academic_year_id = ay.year_id
            JOIN batch_departments bd ON b.batch_id = bd.batch_id
            WHERE bd.department_id = %s AND b.semester = %s AND ay.year_name = %s
        """
        params = (department_id, semester_number, academic_year)
        return self._execute_query(query, params)

def generate_timetable_wrapper(section_id, start_date, semester_weeks):
    # This is a mock-up of the generation process
    generator = TimetableGenerator()
    generation_date = datetime.now()
    log_id = int(generation_date.timestamp()) # Mock log_id
    
    # Mock data to simulate successful generation
    mock_log = {
        'log_id': log_id,
        'section_id': section_id,
        'generation_date': generation_date,
        'status': 'Success',
        'constraints_violated': [],
        'total_slots_assigned': 20, # Mock values
        'total_slots_required': 20, # Mock values
        'generation_time_seconds': 5.0
    }
    
    # Mock timetable data
    mock_timetable = [
        {'day_of_week': 'Monday', 'start_time': datetime.strptime('09:00', '%H:%M').time(), 'subject_name': 'Calculus', 'faculty_name': 'Dr. V. Vidyasagar', 'room_number': 'LH-101'},
        {'day_of_week': 'Tuesday', 'start_time': datetime.strptime('10:00', '%H:%M').time(), 'subject_name': 'Physics', 'faculty_name': 'Dr. Rahul Koshti', 'room_number': 'Lab 6'},
    ]

    if section_id == 10:
         mock_log['status'] = 'Partial'
         mock_log['constraints_violated'] = ["Failed to assign session for Calculus"]
         mock_log['total_slots_assigned'] = 15
    
    result = {
        'generation_log': mock_log,
        'section_id': section_id,
        'section_name': f"Section {section_id}",
        'timetable': {}, # Simplified as the template uses 'grid'
        'raw_timetable': mock_timetable,
        'grid': generator.build_grid(mock_timetable),
        'timeslot_labels': sorted(list(set([str(t['start_time']) for t in mock_timetable]))),
        'start_date': start_date,
        'end_date': start_date + timedelta(weeks=semester_weeks)
    }

    if mock_log['status'] != 'Success':
        result['error'] = f"Timetable generation was {mock_log['status'].lower()}."

    return result

def get_schools():
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT school_id, name, abbrevation FROM schools ORDER BY name")
        schools = cursor.fetchall()
        cursor.close()
        conn.close()
        return schools
    return []

def get_departments_by_school(school_id):
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT department_id, name FROM departments WHERE school_id = %s ORDER BY name", (school_id,))
        departments = cursor.fetchall()
        cursor.close()
        conn.close()
        return departments
    return []

def get_academic_years():
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT year_id, year_name, is_current FROM academic_years ORDER BY start_year DESC")
        years = cursor.fetchall()
        cursor.close()
        conn.close()
        return years
    return []

def get_semesters_by_year(year_id):
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT b.semester
            FROM batches b
            WHERE b.academic_year_id = %s
            GROUP BY b.semester
            ORDER BY b.semester
        """, (year_id,))
        semesters = cursor.fetchall()
        cursor.close()
        conn.close()
        return [s['semester'] for s in semesters]
    return []

def get_sections_by_filters(school_id, dept_id, year_id, semester):
    conn = get_db_connection()
    if not conn: return []
    cursor = conn.cursor(dictionary=True)
    
    query = """
        SELECT
            sec.section_id,
            sec.name AS section_name,
            d.name AS department_name,
            ay.year_name AS academic_year,
            ay.year_id AS academic_year_id,
            b.semester,
            b.year AS academic_year_int
        FROM sections sec
        JOIN batches b ON sec.batch_id = b.batch_id
        JOIN academic_years ay ON b.academic_year_id = ay.year_id
        JOIN batch_departments bd ON b.batch_id = bd.batch_id
        JOIN departments d ON bd.department_id = d.department_id
        WHERE d.school_id = %s
    """
    params = [school_id]
    
    if dept_id:
        query += " AND d.department_id = %s"
        params.append(dept_id)
    if year_id:
        query += " AND ay.year_id = %s"
        params.append(year_id)
    if semester:
        query += " AND b.semester = %s"
        params.append(semester)

    query += " ORDER BY d.name, ay.year_name, b.semester, sec.name"
    
    try:
        cursor.execute(query, tuple(params))
        sections = cursor.fetchall()
    except Error as e:
        logger.error(f"Error fetching sections: {e}")
        sections = []
    finally:
        cursor.close()
        conn.close()
    
    return sections

def get_semester_dates_by_school(school_id):
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT semester_number, academic_year, start_date, end_date FROM semester_config WHERE is_active = 1 LIMIT 1")
        semester_info = cursor.fetchone()
        cursor.close()
        conn.close()
        return semester_info
    return None

def generate_csv_output(all_timetables_raw_data):
    output = io.StringIO()
    writer = csv.writer(output)
    
    header = ['Section', 'Department', 'Academic Year', 'Semester', 'Date', 'Day', 'Start Time', 'End Time', 'Subject', 'Faculty', 'Room', 'Status']
    writer.writerow(header)
    
    for timetable in all_timetables_raw_data:
        section_name = timetable['section_name']
        department = timetable['department']
        academic_year_int = timetable['academic_year_int']
        semester_int = timetable['semester_int']
        
        for entry in timetable['raw_timetable']:
            is_cancelled = entry.get('is_cancelled', 0) == 1
            status = 'Cancelled' if is_cancelled else 'Scheduled'
            
            row = [
                section_name,
                department,
                academic_year_int,
                semester_int,
                str(entry.get('date', '')),
                entry.get('day_of_week', ''),
                str(entry.get('start_time', '')),
                str(entry.get('end_time', '')),
                entry.get('subject_name', ''),
                entry.get('faculty_name', ''),
                entry.get('room_number', ''),
                status
            ]
            writer.writerow(row)
    
    return output.getvalue()


# --- Consolidated Routes ---

@app.route('/')
def index1():
    if 'user_id' in session:
        user_role = session.get('user_role')
        if user_role == 'academic_coordinator':
            return redirect(url_for('academic_coordinator_dashboard'))
        elif user_role == 'hod':
            return redirect(url_for('hod_dashboard'))
        elif user_role == 'faculty':
            return redirect(url_for('faculty_dashboard'))
        elif user_role == 'CR':
            return redirect(url_for('cr_dashboard'))
    return redirect(url_for('login'))

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

            return redirect(url_for('index1'))
        else:
            flash('Invalid email or password', 'error')

    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return jsonify({'redirect_url': url_for('login')}), 200

# --- Academic Coordinator Dashboard Routes ---
@app.route("/academic_coordinator_dashboard")
@login_required('academic_coordinator')
def academic_coordinator_dashboard():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index1'))
    cursor = conn.cursor(dictionary=True)
    
    table_count = 0
    try:
        cursor.execute("SHOW TABLES")
        table_count = len(cursor.fetchall())
    except Error as e:
        logger.error(f"Error fetching table count: {e}")
        flash(f"Error fetching table count: {e}", 'error')
        
    cursor.close()
    conn.close()
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    return render_template('index1.html', database=db_config['database'], table_count=table_count, current_time=current_time)

# Missing route for fetching faculty assignments with filters.
@app.route('/api/get_faculty_assignments_by_filters')
@login_required('academic_coordinator')
def get_faculty_assignments_by_filters():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT fs.*, u.name as faculty_name, b.year as batch_year, b.semester,
               s.name as subject_name, s.subject_code, sec.name as section_name, sub.name as subsection_name
        FROM faculty_subjects fs
        JOIN users u ON fs.faculty_id = u.user_id
        JOIN batch_subjects bs ON fs.batch_subject_id = bs.batch_subject_id
        JOIN subjects s ON bs.subject_id = s.subject_id
        JOIN sections sec ON fs.section_id = sec.section_id
        JOIN batches b ON bs.batch_id = b.batch_id
        LEFT JOIN subsections sub ON fs.subsection_id = sub.subsection_id
        WHERE 1=1
    """
    params = []
    department_id = request.args.get('department_id')
    academic_year_id = request.args.get('academic_year_id')
    batch_id = request.args.get('batch_id')
    semester = request.args.get('semester')
    section_id = request.args.get('section_id')

    if department_id:
        query += " AND bs.batch_id IN (SELECT batch_id FROM batch_departments WHERE department_id = %s)"
        params.append(department_id)
    if academic_year_id:
        query += " AND b.academic_year_id = %s"
        params.append(academic_year_id)
    if batch_id:
        query += " AND b.batch_id = %s"
        params.append(batch_id)
    if semester:
        query += " AND b.semester = %s"
        params.append(semester)
    if section_id:
        query += " AND fs.section_id = %s"
        params.append(section_id)

    query += " ORDER BY u.name, b.year, b.semester"
    try:
        cursor.execute(query, tuple(params))
        return jsonify(cursor.fetchall())
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# Missing route for fetching batches by department.
@app.route('/api/get_batches_by_department/<int:department_id>')
@login_required('academic_coordinator')
def get_batches_by_department(department_id):
    conn = get_db_connection()
    if conn is None: return jsonify([])
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT b.batch_id, CONCAT(b.year, ' (Sem ', b.semester, ')') AS display_name, b.semester
        FROM batches b
        JOIN batch_departments bd ON b.batch_id = bd.batch_id
        WHERE bd.department_id = %s
        ORDER BY b.year, b.semester
    """
    cursor.execute(query, (department_id,))
    batches = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(batches)

@app.route('/api/get_batches_by_academic_year/<int:year_id>')
@login_required('academic_coordinator')
def get_batches_by_academic_year(year_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT batch_id, CONCAT(year, ' (Sem ', semester, ')') AS display_name, semester
        FROM batches
        WHERE academic_year_id = %s
        ORDER BY year, semester
    """
    try:
        cursor.execute(query, (year_id,))
        return jsonify(cursor.fetchall())
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# Missing route for fetching batches by both academic year and department.
@app.route('/api/get_batches_by_academic_year_and_department/<int:year_id>/<int:department_id>')
@login_required('academic_coordinator')
def get_batches_by_academic_year_and_department(year_id, department_id):
    conn = get_db_connection()
    if conn is None: return jsonify([])
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT b.batch_id, CONCAT(b.year, ' (Sem ', b.semester, ')') AS display_name, b.semester
        FROM batches b
        JOIN batch_departments bd ON b.batch_id = bd.batch_id
        WHERE b.academic_year_id = %s AND bd.department_id = %s
        ORDER BY b.year, b.semester
    """
    cursor.execute(query, (year_id, department_id))
    batches = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(batches)

# Missing route for fetching sections by batch.
@app.route('/api/get_sections_by_batch/<int:batch_id>')
@login_required('academic_coordinator')
def get_sections_by_batch(batch_id):
    conn = get_db_connection()
    if conn is None: return jsonify([])
    cursor = conn.cursor(dictionary=True)
    query = "SELECT section_id, name FROM sections WHERE batch_id = %s ORDER BY name"
    cursor.execute(query, (batch_id,))
    sections = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(sections)

# Missing route for fetching subsections by section.
@app.route('/api/get_subsections_by_section/<int:section_id>')
@login_required('academic_coordinator')
def get_subsections_by_section(section_id):
    conn = get_db_connection()
    if conn is None: return jsonify([])
    cursor = conn.cursor(dictionary=True)
    query = "SELECT subsection_id, name FROM subsections WHERE section_id = %s ORDER BY name"
    cursor.execute(query, (section_id,))
    subsections = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(subsections)

# Missing route for fetching subjects for a specific batch and semester.
@app.route('/api/get_batch_subjects_by_batch_and_semester/<int:batch_id>/<int:semester>')
@login_required('academic_coordinator')
def get_batch_subjects_by_batch_and_semester(batch_id, semester):
    conn = get_db_connection()
    if conn is None: return jsonify([])
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT bs.batch_subject_id, s.subject_id, s.name as subject_name, s.subject_code
        FROM batch_subjects bs
        JOIN subjects s ON bs.subject_id = s.subject_id
        WHERE bs.batch_id = %s AND bs.semester = %s
        ORDER BY s.name
    """
    cursor.execute(query, (batch_id, semester))
    subjects = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(subjects)

# Missing route for filtering batch-subject mappings.
@app.route('/api/get_batch_subject_mappings_by_filters')
@login_required('academic_coordinator')
def get_batch_subject_mappings_by_filters():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    
    query = """
        SELECT bsm.batch_subject_id, b.year AS batch_year, bsm.semester, s.subject_code, s.name AS subject_name
        FROM batch_subjects bsm
        JOIN batches b ON bsm.batch_id = b.batch_id
        JOIN subjects s ON bsm.subject_id = s.subject_id
        WHERE 1=1
    """
    params = []
    
    academic_year_id = request.args.get('academic_year_id')
    batch_id = request.args.get('batch_id')
    semester = request.args.get('semester')

    if academic_year_id:
        query += " AND b.academic_year_id = %s"
        params.append(academic_year_id)
    if batch_id:
        query += " AND bsm.batch_id = %s"
        params.append(batch_id)
    if semester:
        query += " AND bsm.semester = %s"
        params.append(semester)

    query += " ORDER BY b.year, b.semester, s.name"
    
    try:
        cursor.execute(query, tuple(params))
        return jsonify(cursor.fetchall())
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# --- Timetable Generation Dashboard Routes ---
@app.route("/timetable_viewer")
@login_required('academic_coordinator')
def enhanced_dashboard():
    try:
        coordinator_school_id = int(request.args.get('school_id', session.get('school_id', 1)))
        
        schools = get_schools()
        current_school = next((s for s in schools if s['school_id'] == coordinator_school_id), None)
        
        if not current_school:
            flash("Invalid school selected", "error")
            return redirect(url_for('academic_coordinator_dashboard'))
        
        session['school_id'] = coordinator_school_id
        session['school_name'] = current_school['name']
        session['school_abbr'] = current_school['abbrevation']
        
        departments = get_departments_by_school(coordinator_school_id)
        academic_years = get_academic_years()
        
        return render_template("timetable_viewer.html",
                               schools=schools,
                               current_school=current_school,
                               departments=departments,
                               academic_years=academic_years)
    except Exception as e:
        logger.error(f"Enhanced Dashboard route error: {str(e)}", exc_info=True)
        flash(f"System error loading dashboard: {str(e)}", "error")
        return render_template("error.html")


@app.route("/generation_logs")
@login_required('academic_coordinator')
def generation_logs():
    """Route to display a list of all successful timetable generation logs."""
    try:
        generator = TimetableGenerator()
        logs = generator.get_all_generation_logs()
        
        if not logs:
            flash("No timetable generation logs found.", "info")
            
        return render_template("generation_logs.html", logs=logs)
    except Exception as e:
        logger.error(f"Error fetching generation logs: {str(e)}", exc_info=True)
        flash(f"An error occurred while loading logs: {str(e)}", "error")
        return redirect(url_for('academic_coordinator_dashboard'))

@app.route("/view_generated_timetable/<int:log_id>")
@login_required('academic_coordinator')
def view_generated_timetable(log_id):
    """Route to view a specific timetable using its log_id."""
    try:
        generator = TimetableGenerator()
        timetable_data = generator.load_specific_timetable(log_id)
        
        if not timetable_data or (isinstance(timetable_data, dict) and "error" in timetable_data):
            error_message = timetable_data.get('error', f"No timetable found for log ID: {log_id}") if isinstance(timetable_data, dict) else f"No timetable found for log ID: {log_id}"
            flash(error_message, "error")
            return redirect(url_for('generation_logs'))

        log_entry = timetable_data['generation_log']
        total_slots = log_entry.get('total_slots_required', 0)
        assigned_slots = log_entry.get('total_slots_assigned', 0)
        success_rate = (assigned_slots / total_slots * 100) if total_slots > 0 else 0
        
        display_data = {
            'status': log_entry['status'] if log_entry else 'Unknown',
            'section_id': timetable_data['section_id'],
            'section_name': timetable_data['section_name'],
            'timetable': timetable_data['timetable'],
            'generation_log': {
                'constraints_violated': json.loads(log_entry.get('constraints_violated', '[]')),
                'total_slots_assigned': assigned_slots,
                'total_slots_required': total_slots,
                'generation_status': log_entry.get('status', 'Unknown')
            },
            'raw_timetable': timetable_data.get('raw_timetable', []),
            'grid': timetable_data['grid'],
            'timeslot_labels': sorted(list(set([t['start_time'].strftime('%H:%M') for t in timetable_data['raw_timetable']]))) if timetable_data['raw_timetable'] else [],
            'generation_seconds': log_entry.get('generation_time_seconds', 0),
            'generated_at': log_entry['generation_date'].strftime("%Y-%m-%d %H:%M:%S") if log_entry.get('generation_date') else "N/A",
            'start_date': timetable_data.get('start_date'),
            'end_date': timetable_data.get('end_date')
        }

        return render_template("timetable_display.html",
                               timetable_data=display_data,
                               section_id=timetable_data['section_id'],
                               success_rate=success_rate,
                               display_constraints=True,
                               is_generation_result=False,
                               view_mode=True)
    except Exception as e:
        logger.error(f"Error viewing specific timetable log {log_id}: {str(e)}", exc_info=True)
        flash(f"Error loading timetable: {str(e)}", "error")
        return redirect(url_for('generation_logs'))

@app.route("/bulk_generate", methods=['GET'])
@login_required('academic_coordinator')
def bulk_generate():
    """
    Route to handle bulk timetable generation for all sections
    within the selected department, year, and semester.
    """
    try:
        school_id = request.args.get('school_id', type=int)
        department_id = request.args.get('department_id', type=int)
        year_id = request.args.get('year_id')
        semester = request.args.get('semester')

        if year_id: year_id = int(year_id)
        if semester: semester = int(semester)

        if not all([school_id, department_id]):
            flash("Please select at least School and Department for bulk generation.", "error")
            return redirect(url_for('academic_coordinator_dashboard'))

        sections_to_generate = get_sections_by_filters(
            school_id=school_id,
            dept_id=department_id,
            year_id=year_id,
            semester=semester
        )

        if not sections_to_generate:
            flash("No sections found for the selected filters to perform bulk generation.", "warning")
            return redirect(url_for('academic_coordinator_dashboard'))

        semester_info = get_semester_dates_by_school(school_id)
        if not semester_info:
            flash("Semester configuration not found for your school. Cannot perform bulk generation.", "error")
            return redirect(url_for('academic_coordinator_dashboard'))

        semester_start_date = semester_info['start_date']
        
        results = []
        for section in sections_to_generate:
            section_id = section['section_id']
            section_name = section['section_name']
            department_name = section['department_name']
            academic_year_val = section.get('academic_year')
            semester_val = section.get('semester')

            logger.info(f"Starting bulk generation for section: {section_name} (ID: {section_id})")
            
            try:
                generation_result = generate_timetable_wrapper(section_id, start_date=semester_start_date, semester_weeks=1)
                
                if 'generation_log' not in generation_result:
                     generation_result['generation_log'] = {
                        'total_slots_required': 0,
                        'total_slots_assigned': 0,
                        'constraints_violated': [generation_result.get('error', 'Unknown error during bulk generation.')],
                        'generation_status': 'Failed'
                    }

                if 'log_id' not in generation_result:
                    generation_result['log_id'] = None
                    generation_result['generation_log']['generation_status'] = 'Failed'
                    generation_result['generation_log']['constraints_violated'].append("Failed to retrieve generation log ID.")

                results.append({
                    'section_id': section_id,
                    'section_name': section_name,
                    'department_name': department_name,
                    'academic_year': academic_year_val,
                    'semester': semester_val,
                    'status': generation_result['generation_log']['generation_status'],
                    'error': generation_result.get('error'),
                    'details': {
                        'total_slots_assigned': generation_result['generation_log'].get('total_slots_assigned', 0),
                        'total_slots_required': generation_result['generation_log'].get('total_slots_required', 0),
                        'constraints_violated': generation_result['generation_log'].get('constraints_violated', [])
                    },
                    'log_id': generation_result.get('log_id')
                })

            except Exception as e:
                logger.error(f"Error during bulk generation for section {section_id}: {str(e)}", exc_info=True)
                results.append({
                    'section_id': section_id,
                    'section_name': section_name,
                    'department_name': department_name,
                    'academic_year': academic_year_val,
                    'semester': semester_val,
                    'status': 'Failed',
                    'error': f"System error: {str(e)}",
                    'details': {'total_slots_assigned': 0, 'total_slots_required': 0, 'constraints_violated': []},
                    'log_id': None
                })
        
        flash(f"Bulk generation completed for {len(sections_to_generate)} sections. See results below.", "info")
        return render_template("bulk_results.html", results=results)

    except Exception as e:
        logger.error(f"Error in bulk_generate route: {str(e)}", exc_info=True)
        flash(f"An unexpected error occurred during bulk generation: {str(e)}", "error")
        return redirect(url_for('academic_coordinator_dashboard'))
    
@app.route('/api/get_rooms_by_type/<string:room_type>')
def get_rooms_by_type(room_type):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    query = "SELECT room_id, room_number FROM rooms WHERE room_type = %s ORDER BY room_number"
    try:
        cursor.execute(query, (room_type,))
        rooms = cursor.fetchall()
        return jsonify(rooms)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/fetch_room_timetable_data')
def fetch_room_timetable_data():
    """
    Fetches timetable data for all rooms to populate the usage tables.
    Returns a JSON object containing the timetable entries.
    """
    conn = get_db_connection()
    if conn is None:
        # If the database connection fails, return a 500 error
        return jsonify({'error': 'Database connection failed!'}), 500
    
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT
            t.day_of_week,
            ts.start_time,
            ts.end_time,
            r.room_number,
            s.name AS subject_name,
            u.name AS faculty_name,
            sec.name AS section_name
        FROM timetable t
        JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
        LEFT JOIN rooms r ON t.room_id = r.room_id
        JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
        JOIN subjects s ON bs.subject_id = s.subject_id
        JOIN users u ON t.faculty_id = u.user_id
        JOIN sections sec ON t.section_id = sec.section_id
        WHERE t.is_cancelled = 0 AND t.is_completed = 0
        ORDER BY r.room_number, t.day_of_week, ts.start_time
    """
    try:
        cursor.execute(query)
        data = cursor.fetchall()
        # The database returns time objects, which are not directly JSON serializable.
        # This loop converts them to strings.
        for row in data:
            if row['start_time']:
                row['start_time'] = str(row['start_time'])
            if row['end_time']:
                row['end_time'] = str(row['end_time'])
        return jsonify(data)
    except Error as e:
        # If a database error occurs, return an error message as JSON
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/export_timetables_csv")
@login_required('academic_coordinator')
def export_timetables_csv():
    """
    Exports timetables for selected filters (or whole department) to a CSV file.
    """
    try:
        school_id = request.args.get('school_id', type=int)
        department_id = request.args.get('department_id', type=int)
        year_id = request.args.get('year_id')
        semester = request.args.get('semester')

        if year_id: year_id = int(year_id)
        if semester: semester = int(semester)

        if not all([school_id, department_id]):
            flash("Please select at least School and Department to export timetables.", "error")
            return redirect(url_for('academic_coordinator_dashboard'))

        sections_to_export = get_sections_by_filters(
            school_id=school_id,
            dept_id=department_id,
            year_id=year_id,
            semester=semester
        )

        if not sections_to_export:
            flash("No sections found for the selected filters to export.", "warning")
            return redirect(url_for('academic_coordinator_dashboard'))

        all_timetables_raw_data = []
        generator = TimetableGenerator()

        for section in sections_to_export:
            section_id = section['section_id']
            latest_log_query = """
                SELECT log_id FROM timetable_generation_log
                WHERE section_id = %s AND status = 'Success'
                ORDER BY generation_date DESC
                LIMIT 1
            """
            latest_log_entry = generator._execute_query(latest_log_query, (section_id,), fetch_one=True)

            if latest_log_entry:
                log_id = latest_log_entry['log_id']
                raw_data = generator.load_specific_timetable_raw(log_id)
                if raw_data:
                    all_timetables_raw_data.append({
                        'section_name': section['section_name'],
                        'department': section['department_name'],
                        'academic_year_int': section.get('academic_year_int'),
                        'semester_int': section.get('semester'),
                        'raw_timetable': raw_data
                    })
                else:
                    logger.warning(f"No raw timetable data found for section {section_id} (log_id: {log_id}) for CSV export.")
            else:
                logger.warning(f"No successful generation log found for section {section_id} for CSV export.")

        if not all_timetables_raw_data:
            flash("No generated timetables found for the selected criteria to export.", "warning")
            return redirect(url_for('academic_coordinator_dashboard'))

        csv_output = generate_csv_output(all_timetables_raw_data)

        response = Response(csv_output, mimetype="text/csv")
        filename_parts = [session.get('school_abbr', 'Timetable')]
        if department_id:
            dept_name = next((d['name'] for d in get_departments_by_school(school_id) if d['department_id'] == department_id), 'Dept')
            filename_parts.append(dept_name.replace(" ", "_"))
        if year_id:
            year_name = next((y['year_name'] for y in get_academic_years() if y['year_id'] == year_id), 'Year')
            filename_parts.append(year_name.replace(" ", "_"))
        if semester:
            filename_parts.append(f"Sem_{semester}")
        
        filename = "_".join(filename_parts) + "_Timetables.csv"
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        return response

    except Exception as e:
        logger.error(f"Error during CSV export: {str(e)}", exc_info=True)
        flash(f"An unexpected error occurred during CSV export: {str(e)}", "error")
        return redirect(url_for('academic_coordinator_dashboard'))


# --- CR Dashboard Routes ---
@app.route('/cr_dashboard', methods=['GET', 'POST'])
@login_required('CR')
def cr_dashboard():
    cr_section_id = session.get('section_id')
    user_id = session.get('user_id')
    today = datetime.now().strftime('%A')
    current_time = datetime.now().time()

    connection = None
    try:
        connection = get_db_connection()
        if connection is None:
            flash("CRITICAL ERROR: Could not connect to the database.", "danger")
            return render_template('error.html', message="Database Connection Failed.")

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
        if cursor: cursor.close()
        if connection and connection.is_connected(): connection.close()


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
    notifications = []
    substitute_requests = []
    lecture_completion = []
    all_timetable_entries = []
    faculty_list = []
    try:
        cursor.execute("SELECT message, timestamp, seen AS is_read FROM notifications WHERE user_id = %s ORDER BY timestamp DESC LIMIT 5", (faculty_id,))
        notifications = cursor.fetchall()
        cursor.execute("""
            SELECT sr.request_id, c.reason AS cancellation_reason, u.name AS requested_by_faculty,
                   s.name AS subject_name, sec.name AS section_name, t.date AS class_date,
                   ts.start_time, ts.end_time, sr.status
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
            SELECT s.name AS subject_name, sec.name AS section_name, t.date AS class_date,
                   ts.start_time, ts.end_time, 'completed' AS status
            FROM timetable t
            JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            JOIN sections sec ON t.section_id = sec.section_id
            JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
            WHERE t.faculty_id = %s AND t.is_completed = 1
            ORDER BY t.date DESC LIMIT 5
        """, (faculty_id,))
        lecture_completion = cursor.fetchall()
        cursor.execute("""
            SELECT t.entry_id, t.date AS entry_date, t.day_of_week, ts.start_time, ts.end_time,
                   s.name AS subject_name, sec.name AS section_name, r.room_number,
                   t.is_cancelled, t.is_completed
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
            if entry['is_completed']: entry['type'] = 'completed'
            elif entry['is_cancelled']: entry['type'] = 'cancelled'
            else: entry['type'] = 'scheduled'
            if entry['type'] == 'cancelled':
                reason_cursor = conn.cursor(dictionary=True)
                reason_cursor.execute("SELECT reason FROM cancellations WHERE timetable_id = %s", (entry['entry_id'],))
                reason_row = reason_cursor.fetchone()
                if reason_row: entry['status_reason'] = reason_row['reason']
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
    if conn is None: return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    faculty_list = []
    try:
        cursor.execute("SELECT user_id AS faculty_id, name AS faculty_name FROM users WHERE role = 'faculty' AND user_id != %s ORDER BY name", (session['user_id'],))
        faculty_list = cursor.fetchall()
        return jsonify(faculty_list)
    except Error as e: return jsonify({'error': str(e)}), 500
    finally: cursor.close(); conn.close()

@app.route('/api/faculty/current/cancel_class', methods=['POST'])
@login_required('faculty')
def cancel_class():
    data = request.json
    timetable_entry_id = data.get('timetable_entry_id'); reason = data.get('reason')
    conn = get_db_connection()
    if conn is None: return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT entry_id FROM timetable WHERE entry_id = %s AND faculty_id = %s", (timetable_entry_id, session['user_id']))
        if not cursor.fetchone(): return jsonify({'error': 'Unauthorized to cancel this class.'}), 403
        cursor.execute("INSERT INTO cancellations (timetable_id, reason, canceled_by) VALUES (%s, %s, %s)", (timetable_entry_id, reason, session['user_id']))
        cursor.execute("UPDATE timetable SET is_cancelled = 1, modified_at = NOW() WHERE entry_id = %s", (timetable_entry_id,))
        conn.commit(); return jsonify({'message': 'Class canceled successfully.'}), 200
    except Error as e: conn.rollback(); return jsonify({'error': str(e)}), 500
    finally: cursor.close(); conn.close()

@app.route('/api/faculty/current/update_lecture_status', methods=['POST'])
@login_required('faculty')
def update_lecture_status():
    data = request.json
    timetable_entry_id = data.get('timetable_entry_id'); status = data.get('status')
    conn = get_db_connection()
    if conn is None: return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT faculty_id FROM timetable WHERE entry_id = %s", (timetable_entry_id,))
        record = cursor.fetchone()
        if record is None or record[0] != session['user_id']: return jsonify({'error': 'Unauthorized to update this lecture.'}), 403
        if status == 'completed':
            cursor.execute("UPDATE timetable SET is_completed = 1, is_cancelled = 0, is_rescheduled = 0, modified_at = NOW() WHERE entry_id = %s AND faculty_id = %s", (timetable_entry_id, session['user_id']))
            message = "Lecture marked as completed."
        elif status == 'pending':
            cursor.execute("UPDATE timetable SET is_completed = 0, is_cancelled = 0, is_rescheduled = 0, modified_at = NOW() WHERE entry_id = %s AND faculty_id = %s", (timetable_entry_id, session['user_id']))
            message = "Lecture status reset to scheduled."
        else: return jsonify({'error': 'Invalid status provided.'}), 400
        conn.commit(); return jsonify({'message': message}), 200
    except Error as e: conn.rollback(); return jsonify({'error': str(e)}), 500
    finally: cursor.close(); conn.close()

@app.route('/api/faculty/current/request_substitute', methods=['POST'])
@login_required('faculty')
def request_substitute():
    data = request.json
    timetable_entry_id = data.get('timetable_entry_id'); requested_to_faculty_id = data.get('requested_to_faculty_id'); reason = data.get('reason')
    conn = get_db_connection()
    if conn is None: return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT faculty_id FROM timetable WHERE entry_id = %s", (timetable_entry_id,))
        class_faculty_id = cursor.fetchone()
        if class_faculty_id is None or class_faculty_id[0] != session['user_id']: return jsonify({'error': 'You are not authorized to request a substitute for this class.'}), 403
        cursor.execute("SELECT cancellation_id FROM cancellations WHERE timetable_id = %s AND canceled_by = %s", (timetable_entry_id, session['user_id']))
        cancellation = cursor.fetchone()
        if not cancellation:
            cursor.execute("INSERT INTO cancellations (timetable_id, reason, canceled_by) VALUES (%s, %s, %s)", (timetable_entry_id, reason, session['user_id']))
            conn.commit()
            cancellation_id = cursor.lastrowid
        else: cancellation_id = cancellation[0]
        cursor.execute("SELECT request_id FROM substitute_requests WHERE cancellation_id = %s AND requested_to = %s AND status = 'pending'", (cancellation_id, requested_to_faculty_id))
        if cursor.fetchone(): return jsonify({'error': 'A pending request to this faculty member already exists.'}), 409
        cursor.execute("INSERT INTO substitute_requests (cancellation_id, requested_to, status) VALUES (%s, %s, 'pending')", (cancellation_id, requested_to_faculty_id))
        notification_message = f"Substitute request from {session['user_name']} for a class on {datetime.date.today()}. Reason: {reason}"
        cursor.execute("INSERT INTO notifications (user_id, type, message) VALUES (%s, 'substitute_request', %s)", (requested_to_faculty_id, notification_message))
        conn.commit(); return jsonify({'message': 'Substitute request sent successfully.'}), 200
    except Error as e: conn.rollback(); return jsonify({'error': str(e)}), 500
    finally: cursor.close(); conn.close()

@app.route('/api/faculty/current/respond_substitute/<int:request_id>', methods=['POST'])
@login_required('faculty')
def respond_to_substitute(request_id):
    data = request.json
    status = data.get('status')
    conn = get_db_connection()
    if conn is None: return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        if status not in ['accepted', 'rejected']: return jsonify({'error': 'Invalid status provided.'}), 400
        cursor.execute("SELECT * FROM substitute_requests WHERE request_id = %s AND requested_to = %s AND status = 'pending'", (request_id, session['user_id']))
        request_data = cursor.fetchone()
        if not request_data: return jsonify({'error': 'Substitute request not found or already responded to.'}), 404
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
        conn.commit(); return jsonify({'message': f"Request {status} successfully."}), 200
    except Error as e: conn.rollback(); return jsonify({'error': str(e)}), 500
    finally: cursor.close(); conn.close()


# --- HOD Dashboard Routes ---
@app.route('/hod_dashboard')
@login_required('hod')
def hod_dashboard():
    return render_template('hod_dashboard.html', user_name=session['user_name'])

@app.route('/api/hod/options/years')
@login_required('hod')
def get_years():
    conn = get_db_connection();
    if conn is None: return jsonify([])
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT DISTINCT year FROM batches ORDER BY year;")
        years = [{'year_id': row['year'], 'year_name': row['year']} for row in cursor.fetchall()]
        return jsonify(years)
    except Error as e:
        print(f"Error fetching years: {e}"); return jsonify([])
    finally: cursor.close(); conn.close()

@app.route('/api/hod/options/semesters')
@login_required('hod')
def get_semesters():
    conn = get_db_connection()
    if conn is None: return jsonify([])
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT DISTINCT semester FROM batches ORDER BY semester;")
        semesters = cursor.fetchall()
        return jsonify(semesters)
    except Error as e:
        print(f"Error fetching semesters: {e}"); return jsonify([])
    finally: cursor.close(); conn.close()

@app.route('/api/hod/options/faculty')
@login_required('hod')
def get_faculty():
    conn = get_db_connection()
    if conn is None: return jsonify([])
    cursor = conn.cursor(dictionary=True)
    try:
        hod_user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (hod_user_id,))
        dept_info = cursor.fetchone()
        if dept_info and dept_info['department_id']:
            dept_id = dept_info['department_id']
            cursor.execute("SELECT user_id AS faculty_id, name AS faculty_name FROM users WHERE role = 'faculty' AND department_id = %s ORDER BY name", (dept_id,))
        else: cursor.execute("SELECT user_id AS faculty_id, name AS faculty_name FROM users WHERE role = 'faculty' ORDER BY name")
        faculty = cursor.fetchall()
        return jsonify(faculty)
    except Error as e:
        print(f"Error fetching faculty list: {e}"); return jsonify([])
    finally: cursor.close(); conn.close()

@app.route('/api/hod/department/progress')
@login_required('hod')
def get_department_progress():
    conn = get_db_connection()
    if conn is None: return jsonify([])
    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (user_id,))
        hod_department_id_row = cursor.fetchone()
        if not hod_department_id_row:
            cursor.execute("""
                SELECT sp.planned_sessions, sp.completed_sessions, s.name AS subject_name, b.semester, d.name as department_name
                FROM subject_progress sp JOIN batch_subjects bs ON sp.batch_subject_id = bs.batch_subject_id
                JOIN subjects s ON bs.subject_id = s.subject_id JOIN sections sec ON sp.section_id = sec.section_id
                JOIN batches b ON sec.batch_id = b.batch_id JOIN batch_departments bd ON b.batch_id = bd.batch_id
                JOIN departments d ON bd.department_id = d.department_id GROUP BY sp.batch_subject_id, d.name
            """)
        else:
            hod_department_id = hod_department_id_row['department_id']
            cursor.execute("""
                SELECT sp.planned_sessions, sp.completed_sessions, s.name AS subject_name, b.semester, d.name as department_name
                FROM subject_progress sp JOIN sections sec ON sp.section_id = sec.section_id
                JOIN batches b ON sec.batch_id = b.batch_id JOIN batch_departments bd ON b.batch_id = bd.batch_id
                JOIN batch_subjects bs ON sp.batch_subject_id = bs.batch_subject_id JOIN subjects s ON bs.subject_id = s.subject_id
                JOIN departments d ON bd.department_id = d.department_id WHERE bd.department_id = %s GROUP BY sp.batch_subject_id, d.name
            """, (hod_department_id,))
        progress_data = cursor.fetchall()
        for item in progress_data:
            item['completion_percentage'] = (item['completed_sessions'] / item['planned_sessions'] * 100) if item['planned_sessions'] > 0 else 0
        return jsonify(progress_data)
    except Error as e:
        print(f"Error fetching HOD progress data: {e}"); return jsonify([])
    finally: cursor.close(); conn.close()

@app.route('/api/hod/department/lagging_subjects')
@login_required('hod')
def get_lagging_subjects():
    conn = get_db_connection()
    if conn is None: return jsonify([])
    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (user_id,))
        hod_department_id_row = cursor.fetchone()
        if not hod_department_id_row: return jsonify([])
        hod_department_id = hod_department_id_row['department_id']
        cursor.execute("""
            SELECT s.name AS subject_name, sec.name AS section_name, sp.planned_sessions AS total_sessions, sp.completed_sessions
            FROM subject_progress sp JOIN sections sec ON sp.section_id = sec.section_id
            JOIN batch_departments bd ON sec.batch_id = bd.batch_id JOIN batch_subjects bs ON sp.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id WHERE bd.department_id = %s
            AND (sp.completed_sessions / sp.planned_sessions) * 100 < 50
            ORDER BY (sp.completed_sessions / sp.planned_sessions) ASC
        """, (hod_department_id,))
        lagging_subjects = cursor.fetchall()
        for subject in lagging_subjects:
            subject['completion_percentage'] = (subject['completed_sessions'] / subject['total_sessions'] * 100) if subject['total_sessions'] > 0 else 0
        return jsonify(lagging_subjects)
    except Error as e:
        print(f"Error fetching lagging subjects: {e}"); return jsonify([])
    finally: cursor.close(); conn.close()

@app.route('/api/hod/department/timetable')
@login_required('hod')
def get_department_timetable():
    conn = get_db_connection()
    if conn is None: return jsonify([])
    cursor = conn.cursor(dictionary=True)
    try:
        year = request.args.get('year'); semester = request.args.get('semester'); faculty_id = request.args.get('faculty_id')
        user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (user_id,))
        hod_department_id_row = cursor.fetchone()
        if not hod_department_id_row: return jsonify([])
        hod_department_id = hod_department_id_row['department_id']
        query = """
            SELECT t.entry_id, t.date AS entry_date, t.day_of_week, ts.start_time, ts.end_time, s.name AS subject_name,
            u.name AS faculty_name, sec.name AS section_name, r.room_number AS classroom_name, t.is_cancelled
            FROM timetable t JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id JOIN subjects s ON bs.subject_id = s.subject_id
            JOIN users u ON t.faculty_id = u.user_id JOIN sections sec ON t.section_id = sec.section_id
            JOIN batches b ON sec.batch_id = b.batch_id JOIN batch_departments bd ON b.batch_id = bd.batch_id
            JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id LEFT JOIN rooms r ON t.room_id = r.room_id WHERE bd.department_id = %s
        """
        params = [hod_department_id]
        if year: query += " AND b.year = %s"; params.append(year)
        if semester: query += " AND b.semester = %s"; params.append(semester)
        if faculty_id: query += " AND t.faculty_id = %s"; params.append(faculty_id)
        query += " ORDER BY t.date, ts.start_time"
        cursor.execute(query, tuple(params))
        timetable_data = cursor.fetchall()
        for entry in timetable_data:
            entry['start_time'] = str(entry['start_time']); entry['end_time'] = str(entry['end_time'])
            entry['entry_date'] = str(entry['entry_date']); entry['type'] = 'cancelled' if entry['is_cancelled'] else 'scheduled'
            if entry['is_cancelled']:
                cancel_cursor = conn.cursor(dictionary=True)
                cancel_cursor.execute("SELECT reason FROM cancellations WHERE timetable_id = %s", (entry['entry_id'],))
                reason = cancel_cursor.fetchone()
                entry['status_reason'] = reason['reason'] if reason else 'N/A'
                cancel_cursor.close()
        return jsonify(timetable_data)
    except Error as e:
        print(f"Error fetching department timetable: {e}"); return jsonify([])
    finally: cursor.close(); conn.close()

@app.route('/api/hod/personal_timetable')
@login_required('hod')
def get_hod_personal_timetable():
    conn = get_db_connection()
    if conn is None: return jsonify([])
    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session['user_id']
        cursor.execute("""
            SELECT t.entry_id, t.date AS entry_date, t.day_of_week, ts.start_time, ts.end_time, s.name AS subject_name,
            sec.name AS section_name, r.room_number AS classroom_name, t.is_cancelled
            FROM timetable t JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id JOIN sections sec ON t.section_id = sec.section_id
            JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id LEFT JOIN rooms r ON t.room_id = r.room_id
            WHERE t.faculty_id = %s ORDER BY t.date, ts.start_time
        """, (user_id,))
        timetable_data = cursor.fetchall()
        for entry in timetable_data:
            entry['start_time'] = str(entry['start_time']); entry['end_time'] = str(entry['end_time'])
            entry['entry_date'] = str(entry['entry_date']); entry['type'] = 'cancelled' if entry['is_cancelled'] else 'scheduled'
            if entry['is_cancelled']:
                cancel_cursor = conn.cursor(dictionary=True)
                cancel_cursor.execute("SELECT reason FROM cancellations WHERE timetable_id = %s", (entry['entry_id'],))
                reason = cancel_cursor.fetchone()
                entry['status_reason'] = reason['reason'] if reason else 'N/A'
                cancel_cursor.close()
        return jsonify(timetable_data)
    except Error as e:
        print(f"Error fetching HOD personal timetable: {e}"); return jsonify([])
    finally: cursor.close(); conn.close()

@app.route('/api/hod/reports/progress_csv')
@login_required('hod')
def download_progress_csv():
    conn = get_db_connection()
    if conn is None: return Response("Database connection failed", status=500)
    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (user_id,))
        hod_department_id_row = cursor.fetchone()
        if not hod_department_id_row: return Response("HOD department not found", status=404)
        hod_department_id = hod_department_id_row['department_id']
        cursor.execute("""
            SELECT s.name AS subject_name, sec.name AS section_name, b.semester, sp.planned_sessions, sp.completed_sessions
            FROM subject_progress sp JOIN sections sec ON sp.section_id = sec.section_id
            JOIN batches b ON sec.batch_id = b.batch_id JOIN batch_departments bd ON b.batch_id = bd.batch_id
            JOIN batch_subjects bs ON sp.batch_subject_id = bs.batch_subject_id JOIN subjects s ON bs.subject_id = s.subject_id
            WHERE bd.department_id = %s ORDER BY s.name, sec.name
        """, (hod_department_id,))
        data = cursor.fetchall()
        if not data: return Response("No data to generate report.", status=404)
        output = io.StringIO(); fieldnames = ['subject_name', 'section_name', 'semester', 'planned_sessions', 'completed_sessions']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader(); writer.writerows(data)
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=department_progress_report.csv"})
    except Error as e:
        print(f"Error generating CSV report: {e}"); return Response("Error generating report", status=500)
    finally: cursor.close(); conn.close()

@app.route('/api/hod/reports/timetable_csv')
@login_required('hod')
def download_timetable_csv():
    conn = get_db_connection()
    if conn is None: return Response("Database connection failed", status=500)
    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (user_id,))
        hod_department_id_row = cursor.fetchone()
        if not hod_department_id_row: return Response("HOD department not found", status=404)
        hod_department_id = hod_department_id_row['department_id']
        cursor.execute("""
            SELECT t.date, t.day_of_week, ts.start_time, ts.end_time, s.name AS subject_name, u.name AS faculty_name,
            sec.name AS section_name, r.room_number AS classroom_name, t.is_cancelled
            FROM timetable t JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id JOIN users u ON t.faculty_id = u.user_id
            JOIN sections sec ON t.section_id = sec.section_id JOIN batches b ON sec.batch_id = b.batch_id
            JOIN batch_departments bd ON b.batch_id = bd.batch_id JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
            LEFT JOIN rooms r ON t.room_id = r.room_id WHERE bd.department_id = %s ORDER BY t.date, ts.start_time
        """, (hod_department_id,))
        data = cursor.fetchall()
        for row in data:
            row['start_time'] = str(row['start_time']); row['end_time'] = str(row['end_time']); row['date'] = str(row['date'])
            row['status'] = 'Cancelled' if row['is_cancelled'] else 'Scheduled'; del row['is_cancelled']
        if not data: return Response("No data to generate report.", status=404)
        output = io.StringIO(); fieldnames = ['date', 'day_of_week', 'start_time', 'end_time', 'subject_name', 'faculty_name', 'section_name', 'classroom_name', 'status']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader(); writer.writerows(data)
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=department_timetable_report.csv"})
    except Error as e:
        print(f"Error generating CSV report: {e}"); return Response("Error generating report", status=500)
    finally: cursor.close(); conn.close()

@app.route('/api/hod/reports/lagging_csv')
@login_required('hod')
def download_lagging_csv():
    conn = get_db_connection()
    if conn is None: return Response("Database connection failed", status=500)
    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session['user_id']
        cursor.execute("SELECT department_id FROM users WHERE user_id = %s", (user_id,))
        hod_department_id_row = cursor.fetchone()
        if not hod_department_id_row: return Response("HOD department not found", status=404)
        hod_department_id = hod_department_id_row['department_id']
        cursor.execute("""
            SELECT s.name AS subject_name, sec.name AS section_name, sp.planned_sessions AS total_sessions, sp.completed_sessions
            FROM subject_progress sp JOIN sections sec ON sp.section_id = sec.section_id
            JOIN batch_departments bd ON sec.batch_id = bd.batch_id JOIN batch_subjects bs ON sp.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id WHERE bd.department_id = %s
            AND (sp.completed_sessions / sp.planned_sessions) * 100 < 50
            ORDER BY (sp.completed_sessions / sp.planned_sessions) ASC
        """, (hod_department_id,))
        data = cursor.fetchall()
        for row in data:
            row['completion_percentage'] = f"{round((row['completed_sessions'] / row['total_sessions']) * 100, 2) if row['total_sessions'] > 0 else 0}%"
        if not data: return Response("No data to generate report.", status=404)
        output = io.StringIO(); fieldnames = ['subject_name', 'section_name', 'total_sessions', 'completed_sessions', 'completion_percentage']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader(); writer.writerows(data)
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=lagging_subjects_report.csv"})
    except Error as e:
        print(f"Error generating CSV report: {e}"); return Response("Error generating report", status=500)
    finally: cursor.close(); conn.close()

@app.route('/api/hod/reports/personal_timetable_csv')
@login_required('hod')
def download_hod_personal_timetable_csv():
    conn = get_db_connection()
    if conn is None: return Response("Database connection failed", status=500)
    cursor = conn.cursor(dictionary=True)
    try:
        user_id = session['user_id']
        cursor.execute("""
            SELECT t.date AS entry_date, t.day_of_week, ts.start_time, ts.end_time, s.name AS subject_name,
            sec.name AS section_name, r.room_number AS classroom_name, t.is_cancelled
            FROM timetable t JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id JOIN sections sec ON t.section_id = sec.section_id
            JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id LEFT JOIN rooms r ON t.room_id = r.room_id
            WHERE t.faculty_id = %s ORDER BY t.date, ts.start_time
        """, (user_id,))
        data = cursor.fetchall()
        for row in data:
            row['start_time'] = str(row['start_time']); row['end_time'] = str(row['end_time']); row['entry_date'] = str(row['entry_date'])
            row['status'] = 'Cancelled' if row['is_cancelled'] else 'Scheduled'; del row['is_cancelled']
        if not data: return Response("No data to generate report.", status=404)
        output = io.StringIO(); fieldnames = ['entry_date', 'day_of_week', 'start_time', 'end_time', 'subject_name', 'section_name', 'classroom_name', 'status']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader(); writer.writerows(data)
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=hod_personal_timetable.csv"})
    except Error as e:
        print(f"Error generating CSV report: {e}"); return Response("Error generating report", status=500)
    finally: cursor.close(); conn.close()
    
# --- Generic Management Pages (Academic Coordinator) ---
@app.route('/subjects_management')
def subjects_management():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index1'))
    cursor = conn.cursor(dictionary=True)
    
    departments = []
    academic_years = []
    subjects = []
    lab_rooms = []

    try:
        cursor.execute("SELECT department_id, name FROM departments ORDER BY name")
        departments = cursor.fetchall()
        cursor.execute("SELECT year_id, year_name FROM academic_years ORDER BY year_name DESC")
        academic_years = cursor.fetchall()
        
        cursor.execute("""
            SELECT 
                s.subject_id, s.subject_code, s.name, s.credits, 
                s.theory_sessions_per_week, s.lab_sessions_per_week, 
                s.lab_duration_hours, s.is_lab_continuous, s.has_lab, s.exam_type,
                r.room_number AS preferred_lab_room_number, s.preferred_lab_room_id
            FROM subjects s
            LEFT JOIN rooms r ON s.preferred_lab_room_id = r.room_id
            ORDER BY s.name
        """)
        subjects = cursor.fetchall()

        cursor.execute("SELECT room_id, room_number FROM rooms WHERE room_type = 'Lab' ORDER BY room_number")
        lab_rooms = cursor.fetchall()

    except Error as e:
        flash(f"Error fetching subjects data: {e}", 'error')
    finally:
        cursor.close()
        conn.close()
    return render_template('subjects_management.html', 
                           subjects=subjects,
                           departments=departments,
                           academic_years=academic_years,
                           lab_rooms=lab_rooms)
                           
@app.route('/faculty_assignments')
def faculty_assignments():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index1'))
    cursor = conn.cursor(dictionary=True)
    
    faculties = []
    batches = [] 
    departments = []
    academic_years = []
    subjects_for_add = [] 
    schools = []
    
    try:
        cursor.execute("SELECT user_id, name FROM users WHERE role = 'faculty' ORDER BY name")
        faculties = cursor.fetchall()
        cursor.execute("SELECT batch_id, year, semester, academic_year_id FROM batches ORDER BY year, semester")
        batches = cursor.fetchall()
        cursor.execute("SELECT department_id, name FROM departments ORDER BY name")
        departments = cursor.fetchall()
        cursor.execute("SELECT year_id, year_name FROM academic_years ORDER BY year_name DESC")
        academic_years = cursor.fetchall()
        cursor.execute("SELECT subject_id, name, subject_code FROM subjects ORDER BY name")
        subjects_for_add = cursor.fetchall()
        cursor.execute("SELECT school_id, name FROM schools ORDER BY name")
        schools = cursor.fetchall()
        
    except Error as e:
        flash(f"Error fetching faculty assignment filter data: {e}", 'error')
    finally:
        cursor.close()
        conn.close()

    return render_template('faculty_assignments.html',
                           faculties=faculties,
                           batches=batches, 
                           departments=departments,
                           academic_years=academic_years,
                           subjects_for_add=subjects_for_add,
                           schools=schools)

@app.route('/batches_sections_management')
def batches_sections_management():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index1'))
    cursor = conn.cursor(dictionary=True)
    
    batches = []
    sections = []
    academic_years = []
    theory_rooms = []

    try:
        cursor.execute("SELECT year_id, year_name, is_current FROM academic_years ORDER BY year_name DESC")
        academic_years = cursor.fetchall()

        cursor.execute("""
            SELECT b.*, ay.year_name AS academic_year_name
            FROM batches b
            LEFT JOIN academic_years ay ON b.academic_year_id = ay.year_id
            ORDER BY b.year, b.semester
        """)
        batches = cursor.fetchall()

        cursor.execute("""
            SELECT sec.*, b.year AS batch_year, b.semester AS batch_semester, r.room_number AS theory_room_number
            FROM sections sec
            JOIN batches b ON sec.batch_id = b.batch_id
            LEFT JOIN rooms r ON sec.theory_room_id = r.room_id
            ORDER BY b.year, b.semester, sec.name
        """)
        sections = cursor.fetchall()

        # Fetch all lecture rooms for the dropdown
        cursor.execute("SELECT room_id, room_number, room_type FROM rooms WHERE room_type = 'Lecture' ORDER BY room_number")
        theory_rooms = cursor.fetchall()

    except Error as e:
        flash(f"Error fetching batches and sections data: {e}", 'error')
    finally:
        cursor.close()
        conn.close()
    
    return render_template('batches_sections_management.html',
                           batches=batches,
                           sections=sections,
                           academic_years=academic_years,
                           theory_rooms=theory_rooms)

@app.route('/batch_subject_mapping_management')
def batch_subject_mapping_management():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index1'))
    cursor = conn.cursor(dictionary=True)

    batches = []
    subjects = []
    mappings = [] # This will be loaded via AJAX
    academic_years = []

    try:
        cursor.execute("SELECT batch_id, year, semester FROM batches ORDER BY year, semester")
        batches = cursor.fetchall()
        cursor.execute("SELECT subject_id, name, subject_code, credits, has_lab FROM subjects ORDER BY name")
        subjects = cursor.fetchall()
        cursor.execute("SELECT year_id, year_name FROM academic_years ORDER BY year_name DESC")
        academic_years = cursor.fetchall()
        
        # Initial load of all mappings for the table
        cursor.execute("""
            SELECT bsm.batch_subject_id, bsm.batch_id, b.year AS batch_year, bsm.semester, bsm.subject_id, s.name AS subject_name, s.subject_code
            FROM batch_subjects bsm
            JOIN batches b ON bsm.batch_id = b.batch_id
            JOIN subjects s ON bsm.subject_id = s.subject_id
            ORDER BY b.year, b.semester, s.name
        """)
        mappings = cursor.fetchall()

    except Error as e:
        flash(f"Error fetching batch subject mapping data: {e}", 'error')
    finally:
        cursor.close()
        conn.close()
    return render_template('batch_subject_mapping_management.html',
                           batches=batches,
                           subjects=subjects,
                           mappings=mappings,
                           academic_years=academic_years)

@app.route('/departments_schools_management')
def departments_schools_management():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index1'))
    cursor = conn.cursor(dictionary=True)

    schools = []
    departments = []

    try:
        cursor.execute("SELECT school_id, name, abbrevation FROM schools ORDER BY name")
        schools = cursor.fetchall()
        cursor.execute("""
            SELECT d.*, s.name AS school_name, s.abbrevation AS school_abbr
            FROM departments d
            JOIN schools s ON d.school_id = s.school_id
            ORDER BY s.name, d.name
        """)
        departments = cursor.fetchall()
    except Error as e:
        flash(f"Error fetching schools and departments data: {e}", 'error')
    finally:
        cursor.close()
        conn.close()
    return render_template('departments_schools_management.html',
                           schools=schools,
                           departments=departments)

@app.route('/faculty_constraints_management')
def faculty_constraints_management():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index1'))
    cursor = conn.cursor(dictionary=True)

    faculties = []
    constraints = []

    try:
        cursor.execute("SELECT user_id, name FROM users WHERE role = 'faculty' ORDER BY name")
        faculties = cursor.fetchall()
        cursor.execute("""
            SELECT fc.*, u.name AS faculty_name
            FROM faculty_constraints fc
            JOIN users u ON fc.faculty_id = u.user_id
            ORDER BY u.name
        """)
        constraints = cursor.fetchall()
        for c in constraints:
            if c['available_days']:
                try:
                    c['available_days'] = json.loads(c['available_days'])
                except json.JSONDecodeError:
                    c['available_days'] = []
            else:
                c['available_days'] = []

    except Error as e:
        flash(f"Error fetching faculty constraints data: {e}", 'error')
    finally:
        cursor.close()
        conn.close()
    return render_template('faculty_constraints_management.html',
                           faculties=faculties,
                           constraints=constraints)

@app.route('/faculty_unavailability_management')
def faculty_unavailability_management():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index1'))
    cursor = conn.cursor(dictionary=True)

    faculties = []
    unavailabilities = []

    try:
        cursor.execute("SELECT user_id, name FROM users WHERE role = 'faculty' ORDER BY name")
        faculties = cursor.fetchall()
        cursor.execute("""
            SELECT fu.*, u.name AS faculty_name
            FROM faculty_unavailability fu
            JOIN users u ON fu.faculty_id = u.user_id
            ORDER BY u.name, fu.day_of_week, fu.start_time
        """)
        unavailabilities = cursor.fetchall()
    except Error as e:
        flash(f"Error fetching faculty unavailability data: {e}", 'error')
    finally:
        cursor.close()
        conn.close()
    return render_template('faculty_unavailability_management.html',
                           faculties=faculties,
                           unavailabilities=unavailabilities)
                           
@app.route('/rooms_resources_management')
def rooms_resources_management():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index1'))
    cursor = conn.cursor(dictionary=True)

    rooms = []
    room_unavailabilities = []

    try:
        cursor.execute("SELECT room_id, room_number, room_type, capacity, building, floor, is_active FROM rooms ORDER BY room_number")
        rooms = cursor.fetchall()
        cursor.execute("""
            SELECT ru.*, r.room_number
            FROM room_unavailability ru
            JOIN rooms r ON ru.room_id = r.room_id
            ORDER BY r.room_number, ru.date, ru.start_time
        """)
        room_unavailabilities = cursor.fetchall()
    except Error as e:
        flash(f"Error fetching room data: {e}", 'error')
    finally:
        cursor.close()
        conn.close()
    return render_template('rooms_resources_management.html',
                           rooms=rooms,
                           room_unavailabilities=room_unavailabilities)

@app.route('/holidays_management')
def holidays_management():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index1'))
    cursor = conn.cursor(dictionary=True)

    holidays = []

    try:
        cursor.execute("SELECT * FROM holidays ORDER BY date")
        holidays = cursor.fetchall()
    except Error as e:
        flash(f"Error fetching holiday data: {e}", 'error')
    finally:
        cursor.close()
        conn.close()
    return render_template('holidays_management.html', holidays=holidays)

@app.route('/timetable_viewer')
@login_required('academic_coordinator')
def timetable_viewer():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index1'))
    cursor = conn.cursor(dictionary=True)

    sections = []
    faculties = []
    rooms = []
    academic_years = []
    schools = []
    departments = []

    try:
        cursor.execute("SELECT school_id, name FROM schools ORDER BY name")
        schools = cursor.fetchall()
        cursor.execute("SELECT department_id, name FROM departments ORDER BY name")
        departments = cursor.fetchall()
        cursor.execute("SELECT section_id, name FROM sections ORDER BY name")
        sections = cursor.fetchall()
        cursor.execute("SELECT user_id, name FROM users WHERE role = 'faculty' ORDER BY name")
        faculties = cursor.fetchall()
        cursor.execute("SELECT room_id, room_number FROM rooms ORDER BY room_number")
        rooms = cursor.fetchall()
        cursor.execute("SELECT year_id, year_name FROM academic_years ORDER BY year_name DESC")
        academic_years = cursor.fetchall()

    except Error as e:
        flash(f"Error fetching filter data: {e}", 'error')
    finally:
        cursor.close()
        conn.close()

    return render_template('timetable_viewer.html',
                           sections=sections,
                           faculties=faculties,
                           rooms=rooms,
                           academic_years=academic_years,
                           schools=schools,
                           departments=departments)

# --- NEW ADD, EDIT, DELETE ROUTES ---
@app.route('/add/<table_name>', methods=['POST'])
def add_record(table_name):
    if not is_valid_table(table_name):
        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            flash('Invalid table name!', 'error')
            return redirect(url_for('index1'))
        return jsonify({'error': 'Invalid table name'}), 400

    conn = get_db_connection()
    if conn is None:
        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            flash('Database connection failed!', 'error')
            return redirect(request.referrer or url_for('index1'))
        return jsonify({'error': 'Database connection failed!'}), 500

    cursor = conn.cursor()
    try:
        cursor.execute(f"SHOW COLUMNS FROM {table_name}")
        db_columns_info = cursor.fetchall()
        db_columns = [col[0] for col in db_columns_info]
        
        cursor.execute(f"SHOW KEYS FROM {table_name} WHERE Key_name = 'PRIMARY'")
        pk_info = cursor.fetchone()
        primary_key_column = pk_info[4] if pk_info else None

        columns_to_insert = []
        values_to_insert = []
        
        # Loop through form data and build query
        for col_name in db_columns:
            if col_name == primary_key_column and any('auto_increment' in col_info[3].lower() for col_info in db_columns_info if col_info[0] == col_name):
                continue
            
            form_value = request.form.get(col_name)
            
            if col_name == 'available_days' and table_name == 'faculty_constraints':
                available_days_list = request.form.getlist('available_days')
                form_value = json.dumps(available_days_list)
                
            elif col_name in ['is_active', 'has_lab', 'is_current', 'affects_timetable', 'is_rescheduled', 'is_lab_session', 'seen', 'is_visiting_faculty', 'is_lab_continuous']:
                values_to_insert.append(1 if form_value == '1' else 0)
            elif col_name in ['credits', 'year', 'semester', 'start_year', 'end_year', 'capacity', 'floor', 'max_hours_per_week', 'max_hours_per_day', 'min_weekly_hours', 'max_weekly_hours', 'total_students', 'max_subsection_size', 'total_weeks', 'total_required', 'conducted', 'total_slots_assigned', 'total_slots_required', 'theory_sessions_per_week', 'lab_sessions_per_week', 'preferred_lab_room_id', 'theory_room_id', 'theory_sessions', 'lab_sessions']:
                try:
                    values_to_insert.append(int(form_value) if form_value else None)
                except (ValueError, TypeError):
                    values_to_insert.append(None)
            elif col_name in ['total_hours_assigned', 'completion_percentage', 'generation_time_seconds', 'lab_duration_hours']:
                try:
                    values_to_insert.append(Decimal(form_value) if form_value else None)
                except (ValueError, TypeError):
                    values_to_insert.append(None)
            elif col_name in ['assigned_date', 'start_date', 'end_date', 'date', 'week_start_date', 'generation_date', 'responded_at', 'modified_at', 'created_at', 'login_time', 'last_activity', 'timestamp']:
                values_to_insert.append(form_value if form_value else None)
            else:
                values_to_insert.append(form_value)
            
            columns_to_insert.append(col_name)

        if not columns_to_insert:
            if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
                flash(f"No valid columns to insert for {table_name}.", 'error')
                return redirect(request.referrer or url_for('index1'))
            return jsonify({'error': f"No valid columns to insert for {table_name}."}), 400

        placeholders = ', '.join(['%s' for _ in columns_to_insert])
        columns_list = ', '.join(columns_to_insert)
        
        query = f"INSERT INTO {table_name} ({columns_list}) VALUES ({placeholders})"
        
        cursor.execute(query, values_to_insert)
        conn.commit()
        
        success_message = f"Record added to {table_name} successfully!"
        if table_name == 'subjects':
            success_message = f"Subject '{request.form.get('name')}' added successfully!<br>Auto-assigned sessions:<br>- Theory: {request.form.get('theory_sessions_per_week')} sessions/week<br>- Lab: {request.form.get('lab_sessions_per_week')} sessions/week"
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'message': success_message}), 200
        else:
            flash(success_message, 'success')
            return redirect(request.referrer or url_for('index1'))

    except Error as e:
        conn.rollback()
        error_message = str(e)
        if "foreign key constraint" in error_message.lower():
            error_message = "Foreign key constraint violation. Please ensure the referenced record exists in the related table."
        if "duplicate entry" in error_message.lower():
            error_message = "Duplicate entry found. The record you are trying to add already exists."
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': f"Error adding record to {table_name}: {error_message}"}), 500
        else:
            flash(f"Error adding record to {table_name}: {error_message}", 'error')
            return redirect(request.referrer or url_for('index1'))

    except ValueError as e:
        conn.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': f"Data type conversion error: {e}. Please check your input format."}), 400
        else:
            flash(f"Data type conversion error: {e}. Please check your input format.", 'error')
            return redirect(request.referrer or url_for('index1'))
    finally:
        cursor.close()
        conn.close()

@app.route('/edit_row/<table_name>', methods=['POST'])
def edit_row(table_name):
    if not is_valid_table(table_name):
        flash('Invalid table name!', 'error')
        return redirect(url_for('index1'))

    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(request.referrer or url_for('index1'))

    cursor = conn.cursor()
    try:
        primary_key = request.form.get('primary_key')
        primary_value = request.form.get('primary_value')

        if not primary_key or not primary_value:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Primary key or value missing for update!'}), 400
            else:
                flash('Primary key or value missing for update!', 'error')
                return redirect(request.referrer or url_for('table_view', table_name=table_name))

        cursor.execute(f"SHOW COLUMNS FROM {table_name}")
        db_columns = [col[0] for col in cursor.fetchall()]

        set_clauses = []
        values = []
        form_data = request.form

        # UPDATED LOGIC FOR SUBJECTS TABLE
        if table_name == 'subjects':
            for col_name in ['name', 'subject_code', 'credits', 'theory_sessions_per_week', 'lab_sessions_per_week', 'lab_duration_hours', 'is_lab_continuous', 'has_lab', 'exam_type', 'preferred_lab_room_id']:
                if col_name in form_data:
                    form_value = form_data.get(col_name)
                    if col_name in ['has_lab', 'is_lab_continuous']:
                        values.append(1 if form_value == '1' else 0)
                    elif col_name in ['credits', 'theory_sessions_per_week', 'lab_sessions_per_week', 'preferred_lab_room_id']:
                        try:
                            values.append(int(form_value) if form_value else None)
                        except (ValueError, TypeError):
                            values.append(None)
                    elif col_name in ['lab_duration_hours']:
                        try:
                            values.append(Decimal(form_value) if form_value else None)
                        except (ValueError, TypeError):
                            values.append(None)
                    else:
                        values.append(form_value)
                    set_clauses.append(f"{col_name} = %s")

        elif table_name == 'sections':
            for col_name in ['batch_id', 'name', 'theory_room_id']:
                if col_name in form_data:
                    form_value = form_data.get(col_name)
                    if col_name in ['batch_id', 'theory_room_id']:
                        try:
                            values.append(int(form_value) if form_value else None)
                        except (ValueError, TypeError):
                            values.append(None)
                    else:
                        values.append(form_value)
                    set_clauses.append(f"{col_name} = %s")
        else:
            # General loop for all other tables
            for col in db_columns:
                if col == primary_key:
                    continue

                form_value = form_data.get(col)

                if col in ['is_active', 'has_lab', 'is_current', 'affects_timetable', 'is_rescheduled', 'is_lab_session', 'seen', 'is_visiting_faculty']:
                    values.append(1 if form_value == '1' else 0)
                elif col in ['credits', 'year', 'semester', 'start_year', 'end_year', 'capacity', 'floor', 'max_hours_per_week', 'max_hours_per_day', 'min_weekly_hours', 'max_weekly_hours', 'total_students', 'max_subsection_size', 'total_weeks', 'total_required', 'conducted', 'total_slots_assigned', 'total_slots_required', 'theory_sessions_per_week', 'lab_sessions_per_week', 'preferred_lab_room_id', 'theory_room_id']:
                    try:
                        values.append(int(form_value) if form_value else None)
                    except (ValueError, TypeError):
                        values.append(None)
                elif col in ['total_hours_assigned', 'completion_percentage', 'generation_time_seconds', 'lab_duration_hours']:
                    try:
                        values.append(Decimal(form_value) if form_value else None)
                    except (ValueError, TypeError):
                        values.append(None)
                elif col in ['assigned_date', 'start_date', 'end_date', 'date', 'week_start_date', 'generation_date', 'responded_at', 'modified_at', 'created_at', 'login_time', 'last_activity', 'timestamp']:
                    values.append(form_value if form_value else None)
                else:
                    values.append(form_value)
                
                set_clauses.append(f"{col} = %s")

        if not set_clauses:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'message': "No changes detected or valid columns to update."}), 200
            else:
                flash("No changes detected or valid columns to update.", 'info')
                return redirect(request.referrer or url_for('table_view', table_name=table_name))

        query = f"UPDATE {table_name} SET {', '.join(set_clauses)} WHERE {primary_key} = %s"
        values.append(primary_value)

        cursor.execute(query, values)
        conn.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'message': f"Record in {table_name} updated successfully!"}), 200
        else:
            flash(f"Record in {table_name} updated successfully!", 'success')
            return redirect(request.referrer or url_for('table_view', table_name=table_name))
    except Error as e:
        conn.rollback()
        error_message = str(e)
        if "foreign key constraint" in error_message.lower():
            error_message = "Foreign key constraint violation. Please ensure the referenced record exists in the related table."
        if "duplicate entry" in error_message.lower():
            error_message = "Duplicate entry found. The record you are trying to edit already exists."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': f"Error updating record in {table_name}: {error_message}"}), 500
        else:
            flash(f"Error updating record in {table_name}: {error_message}", 'error')
            return redirect(request.referrer or url_for('index1'))
    except ValueError as e:
        conn.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': f"Data type conversion error: {e}. Please check your input format."}), 400
        else:
            flash(f"Data type conversion error: {e}. Please check your input format.", 'error')
            return redirect(request.referrer or url_for('index1'))
    finally:
        cursor.close()
        conn.close()

@app.route('/delete/<table_name>')
def delete_record(table_name):
    # Retrieve parameters from the query string
    primary_key = request.args.get('primary_key')
    primary_value = request.args.get('primary_value')

    if not is_valid_table(table_name):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Invalid table name'}), 400
        flash('Invalid table name!', 'error')
        return redirect(url_for('tables'))

    if not primary_key or not primary_value:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Primary key or value missing!'}), 400
        flash('Primary key or value missing for delete!', 'error')
        return redirect(request.referrer or url_for('index1'))

    conn = get_db_connection()
    if conn is None:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Database connection failed!'}), 500
        flash('Database connection failed!', 'error')
        return redirect(url_for('index1'))

    cursor = conn.cursor()
    try:
        query = f"DELETE FROM {table_name} WHERE {primary_key} = %s"
        cursor.execute(query, (primary_value,))
        conn.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'message': f"Record in {table_name} deleted successfully!"}), 200
        flash(f"Record in {table_name} deleted successfully!", 'success')
    except Error as e:
        conn.rollback()
        error_message = f"Error deleting record from {table_name}: {e}"
        if "foreign key constraint" in str(e).lower():
            error_message = f"Cannot delete record from {table_name}. It is referenced by other tables."
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': error_message}), 500
        flash(error_message, 'error')
    finally:
        cursor.close()
        conn.close()
    
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return redirect(request.referrer or url_for('table_view', table_name=table_name))
    return '', 204

@app.route('/get_row/<table_name>')
def get_row(table_name):
    if not is_valid_table(table_name):
        return jsonify({'error': 'Invalid table name'}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500

    primary_key = request.args.get('primary_key')
    primary_value = request.args.get('primary_value')

    if not primary_key or not primary_value:
        return jsonify({'error': 'Primary key or value not provided'}), 400

    cursor = conn.cursor(dictionary=True)
    try:
        query = f"SELECT * FROM {table_name} WHERE {primary_key} = %s"
        cursor.execute(query, (primary_value,))
        row = cursor.fetchone()
        if row:
            for key, value in row.items():
                if isinstance(value, (date, datetime)):
                    row[key] = value.isoformat()
                elif isinstance(value, timedelta):
                    row[key] = str(value)
                elif isinstance(value, Decimal):
                    row[key] = str(value)
                elif isinstance(value, bytes):
                    try:
                        row[key] = value.decode('utf-8')
                    except UnicodeDecodeError:
                        row[key] = value.hex()
                elif key == 'available_days' and isinstance(value, str):
                    try:
                        row[key] = json.loads(value)
                    except json.JSONDecodeError:
                        row[key] = []
                elif key.endswith('_id') and isinstance(value, int):
                    row[key] = str(value)
            return jsonify(row)
        else:
            return jsonify({'error': 'Row not found'}), 404
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/get_select_options/<fk_column_name>/<fk_table_name>')
def get_select_options(fk_column_name, fk_table_name):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        # Define a mapping for how to display options for different tables
        display_mappings = {
            'batches': {'id_col': 'batch_id', 'name_col': 'CONCAT(year, " (Sem ", semester, ")")'},
            'academic_years': {'id_col': 'year_id', 'name_col': 'year_name'},
            'rooms': {'id_col': 'room_id', 'name_col': 'room_number'},
            'subjects': {'id_col': 'subject_id', 'name_col': 'CONCAT(subject_code, " - ", name)'},
            # Add other tables as needed
        }

        mapping = display_mappings.get(fk_table_name)
        if mapping:
            query = f"SELECT {mapping['id_col']} AS id, {mapping['name_col']} AS name FROM {fk_table_name} ORDER BY {mapping['name_col']}"
            cursor.execute(query)
        else:
            # Fallback if no specific mapping exists
            query = f"SELECT DISTINCT {fk_column_name} AS id, {fk_column_name} AS name FROM {fk_table_name} ORDER BY {fk_column_name}"
            cursor.execute(query)
        
        options = cursor.fetchall()
        return jsonify(options)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# --- NEW API Endpoints for Credit Rules ---
@app.route('/api/get_credit_rules', methods=['GET'])
def get_credit_rules():
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT credits, theory_sessions, lab_sessions FROM credit_session_rules ORDER BY credits")
        rules = cursor.fetchall()
        return jsonify(rules)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/save_credit_rules', methods=['POST'])
def save_credit_rules():
    data = request.get_json()
    rules = data.get('rules')
    if not rules:
        return jsonify({'error': 'No rules provided'}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor()
    
    try:
        for rule in rules:
            credits = rule['credits']
            theory_sessions = rule['theory_sessions']
            lab_sessions = rule['lab_sessions']
            cursor.execute("""
                INSERT INTO credit_session_rules (credits, theory_sessions, lab_sessions)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                theory_sessions = VALUES(theory_sessions),
                lab_sessions = VALUES(lab_sessions)
            """, (credits, theory_sessions, lab_sessions))
        conn.commit()
        return jsonify({'message': 'Credit rules saved successfully!'}), 200
    except Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/tables')
def tables():
    """Generic route to view all tables (Admin only)."""
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index1'))

    cursor = conn.cursor()
    cursor.execute("SHOW TABLES")
    tables_list = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return render_template('tables.html', tables=tables_list)

@app.route('/table/<table_name>')
def table_view(table_name):
    """Generic route to view and perform CRUD on any specific table (Admin only)."""
    if not is_valid_table(table_name):
        flash('Invalid table name!', 'error')
        return redirect(url_for('tables'))

    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('tables'))

    cursor = conn.cursor(dictionary=True) # Ensure this is a dictionary cursor
    rows = []
    columns = []
    primary_keys = []
    referenced_tables = {}

    try:
        cursor.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()
        if cursor.description:
            columns = [desc[0] for desc in cursor.description]

        cursor.execute(f"SHOW KEYS FROM {table_name} WHERE Key_name = 'PRIMARY'")
        pk_rows = cursor.fetchall()
        primary_keys = [row['Column_name'] for row in pk_rows]
        if not primary_keys and table_name == 'user_roles':
             primary_keys = ['user_id', 'role']
        elif not primary_keys:
            if columns:
                primary_keys = [columns[0]]
            else:
                primary_keys = []

        # Fetch foreign keys for dropdown population
        temp_cursor = conn.cursor() 
        temp_cursor.execute("""
            SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND REFERENCED_TABLE_NAME IS NOT NULL
        """, (db_config['database'], table_name))
        foreign_key_details = temp_cursor.fetchall()
        temp_cursor.close()

        for fk in foreign_key_details:
            fk_column_name = fk[0]
            ref_table = fk[1]
            ref_col = fk[2]
            try:
                ref_cursor = conn.cursor(dictionary=True)
                if ref_table == 'users':
                    ref_cursor.execute("SELECT user_id AS id, name FROM users ORDER BY name")
                elif ref_table == 'batches':
                    ref_cursor.execute("SELECT batch_id AS id, CONCAT(year, ' (Sem ', semester, ')') AS name FROM batches ORDER BY year, semester")
                elif ref_table == 'subjects':
                    ref_cursor.execute("SELECT subject_id AS id, CONCAT(subject_code, ' - ', name) AS name FROM subjects ORDER BY name")
                elif ref_table == 'sections':
                    ref_cursor.execute("SELECT section_id AS id, name FROM sections ORDER BY name")
                elif ref_table == 'subsections':
                    ref_cursor.execute("SELECT subsection_id AS id, name FROM subsections ORDER BY name")
                elif ref_table == 'rooms':
                    ref_cursor.execute("SELECT room_id AS id, room_number AS name FROM rooms ORDER BY room_number")
                elif ref_table == 'academic_years':
                    ref_cursor.execute("SELECT year_id AS id, year_name AS name FROM academic_years ORDER BY year_name DESC")
                elif ref_table == 'schools':
                    ref_cursor.execute("SELECT school_id AS id, name FROM schools ORDER BY name")
                elif ref_table == 'departments':
                    ref_cursor.execute("SELECT department_id AS id, name FROM departments ORDER BY name")
                elif ref_table == 'batch_subjects':
                    ref_cursor.execute("""
                        SELECT bs.batch_subject_id AS id, CONCAT(s.subject_code, ' - ', s.name, ' (Sem ', b.semester, ')') as name
                        FROM batch_subjects bs
                        JOIN subjects s ON bs.subject_id = s.subject_id
                        JOIN batches b ON bs.batch_id = b.batch_id
                        ORDER BY s.name
                    """)
                elif ref_table == 'timeslots':
                    ref_cursor.execute("SELECT timeslot_id AS id, CONCAT(day_of_week, ' ', start_time, '-', end_time) AS name FROM timeslots ORDER BY day_of_week, start_time")
                else:
                    ref_cursor.execute(f"SELECT DISTINCT {ref_col} AS id, {ref_col} AS name FROM {ref_table} ORDER BY {ref_col}")
                
                values_for_select = ref_cursor.fetchall()
                referenced_tables[fk_column_name] = {'table': ref_table, 'values': values_for_select}
                ref_cursor.close()
            except Error as e:
                print(f"Warning: Could not fetch referenced values for {fk_column_name} from {ref_table}. Error: {e}")

    except Error as e:
        flash(f"Error fetching data from {table_name}: {e}", 'error')
        rows = []
        columns = []
        primary_keys = []
        referenced_tables = {}
    finally:
        cursor.close()
        conn.close()
    return render_template('table_view.html', table_name=table_name, rows=rows, columns=columns,
                           primary_keys=primary_keys, referenced_tables=referenced_tables)
                           
@app.route("/api/schools")
def api_schools():
    try:
        schools = get_schools()
        return jsonify(schools)
    except Exception as e:
        logger.error(f"Error fetching schools: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/api/departments/<int:school_id>")
def api_departments(school_id):
    try:
        departments = get_departments_by_school(school_id)
        logger.debug(f"Departments for school {school_id}: {departments}")
        return jsonify(departments)
    except Exception as e:
        logger.error(f"Department load error: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/api/academic_years")
def api_academic_years():
    try:
        years = get_academic_years()
        return jsonify(years)
    except Exception as e:
        logger.error(f"Error fetching academic years: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/api/semesters/<int:year_id>")
def api_semesters(year_id):
    try:
        semesters = get_semesters_by_year(year_id)
        return jsonify(semesters)
    except Exception as e:
        logger.error(f"Error fetching semesters for year {year_id}: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/api/sections")
def api_sections():
    try:
        school_id = request.args.get('school_id')
        dept_id = request.args.get('department_id')
        year_id = request.args.get('year_id')
        semester = request.args.get('semester')
        
        sections = get_sections_by_filters(
            school_id=school_id,
            dept_id=dept_id,
            year_id=year_id,
            semester=semester
        )
        return jsonify(sections)
    except Exception as e:
        logger.error(f"Error fetching sections: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500
        
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    logger.error(f"500 Error: {str(e)}", exc_info=True)
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
