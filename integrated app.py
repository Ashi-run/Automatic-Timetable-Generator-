from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, Response
from advanced_timetable_logic import (
    generate_timetable_wrapper,
    get_schools,
    get_departments_by_school,
    get_academic_years,
    get_semesters_by_year,
    get_sections_by_filters,
    authenticate_coordinator,
    get_user_school,
    TimetableGenerator,
    get_semester_dates_by_school,
    get_subject_progress_for_department_and_semester,
    generate_csv_output
)
import json
from datetime import datetime, timedelta, date, time
import logging
import mysql.connector
from mysql.connector import Error
from decimal import Decimal

app = Flask(_name_)

app.secret_key = 'nmims_timetable_secret_key_2025'

# Database configuration
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'reclassify'
}

def get_db_connection():
    """Establishes and returns a database connection."""
    try:
        conn = mysql.connector.connect(**db_config)
        if conn.is_connected():
            return conn
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None
    return None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(_name_)

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

def setup_credit_rules_table():
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS credit_session_rules (
                    credits INT NOT NULL,
                    theory_sessions INT NOT NULL,
                    lab_sessions INT NOT NULL,
                    PRIMARY KEY (credits)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            conn.commit()
            print("credit_session_rules table is ready.")
        except Error as e:
            print(f"Error setting up credit_session_rules table: {e}")
        finally:
            cursor.close()
            conn.close()

setup_credit_rules_table()

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

@app.route('/add/<table_name>', methods=['POST'])
def add_record(table_name):
    if not is_valid_table(table_name):
        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            flash('Invalid table name!', 'error')
            return redirect(url_for('index'))
        return jsonify({'error': 'Invalid table name'}), 400

    conn = get_db_connection()
    if conn is None:
        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            flash('Database connection failed!', 'error')
            return redirect(request.referrer or url_for('index'))
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
        
        if table_name == 'subjects':
            credits = int(request.form.get('credits', 0))
            has_lab = request.form.get('has_lab', '0') == '1'
            lab_duration = float(request.form.get('lab_duration_hours', 2.0)) if has_lab else None
            is_lab_continuous = request.form.get('is_lab_continuous', '0') == '1' if has_lab else False
            exam_type = request.form.get('exam_type')
            preferred_lab_room_id = request.form.get('preferred_lab_room_id')

            rules_cursor = conn.cursor(dictionary=True)
            rules_cursor.execute("SELECT theory_sessions, lab_sessions FROM credit_session_rules WHERE credits = %s", (credits,))
            rule = rules_cursor.fetchone()
            rules_cursor.close()

            if rule:
                theory_sessions_per_week = rule['theory_sessions']
                lab_sessions_per_week = rule['lab_sessions'] if has_lab else 0
            else:
                theory_sessions_per_week = credits
                lab_sessions_per_week = 1 if has_lab else 0

            form_data_with_sessions = request.form.to_dict()
            form_data_with_sessions['theory_sessions_per_week'] = theory_sessions_per_week
            form_data_with_sessions['lab_sessions_per_week'] = lab_sessions_per_week
            form_data_with_sessions['lab_duration_hours'] = lab_duration
            form_data_with_sessions['is_lab_continuous'] = 1 if is_lab_continuous else 0
            form_data_with_sessions['exam_type'] = exam_type
            if has_lab and preferred_lab_room_id:
                form_data_with_sessions['preferred_lab_room_id'] = preferred_lab_room_id
            else:
                form_data_with_sessions['preferred_lab_room_id'] = None
            request.form = form_data_with_sessions
        
        if table_name == 'sections':
            theory_room_id = request.form.get('theory_room_id')
            form_data_with_room = request.form.to_dict()
            if theory_room_id:
                form_data_with_room['theory_room_id'] = theory_room_id
            else:
                form_data_with_room['theory_room_id'] = None
            request.form = form_data_with_room

        for col_name in db_columns:
            if col_name == primary_key_column and any('auto_increment' in col_info[3].lower() for col_info in db_columns_info if col_info[0] == col_name):
                continue
            
            form_value = request.form.get(col_name)
            
            if col_name == 'available_days' and table_name == 'faculty_constraints':
                available_days_list = request.form.getlist('available_days')
                form_value = json.dumps(available_days_list)
                
            elif col_name in ['is_active', 'has_lab', 'is_current', 'affects_timetable', 'is_rescheduled', 'is_lab_session', 'seen', 'is_visiting_faculty', 'is_lab_continuous']:
                values_to_insert.append(1 if form_value == '1' else 0)
            elif col_name in ['credits', 'year', 'semester', 'start_year', 'end_year', 'capacity', 'floor', 'max_hours_per_week', 'max_hours_per_day', 'min_weekly_hours', 'max_weekly_hours', 'total_students', 'max_subsection_size', 'total_weeks', 'total_required', 'conducted', 'total_slots_assigned', 'total_slots_required', 'theory_sessions_per_week', 'lab_sessions_per_week', 'preferred_lab_room_id', 'theory_room_id']:
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
                return redirect(request.referrer or url_for('index'))
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
            return redirect(request.referrer or url_for('index'))

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
            return redirect(request.referrer or url_for('index'))

    except ValueError as e:
        conn.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': f"Data type conversion error: {e}. Please check your input format."}), 400
        else:
            flash(f"Data type conversion error: {e}. Please check your input format.", 'error')
            return redirect(request.referrer or url_for('index'))
    finally:
        cursor.close()
        conn.close()

@app.route('/edit_row/<table_name>', methods=['POST'])
def edit_row(table_name):
    if not is_valid_table(table_name):
        flash('Invalid table name!', 'error')
        return redirect(url_for('index'))

    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(request.referrer or url_for('index'))

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
            return redirect(request.referrer or url_for('index'))
    except ValueError as e:
        conn.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': f"Data type conversion error: {e}. Please check your input format."}), 400
        else:
            flash(f"Data type conversion error: {e}. Please check your input format.", 'error')
            return redirect(request.referrer or url_for('index'))
    finally:
        cursor.close()
        conn.close()

@app.route('/delete/<table_name>')
def delete_record(table_name):
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
        return redirect(request.referrer or url_for('index'))

    conn = get_db_connection()
    if conn is None:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Database connection failed!'}), 500
        flash('Database connection failed!', 'error')
        return redirect(url_for('index'))

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
        display_mappings = {
            'batches': {'id_col': 'batch_id', 'name_col': 'CONCAT(year, " (Sem ", semester, ")")'},
            'academic_years': {'id_col': 'year_id', 'name_col': 'year_name'},
            'rooms': {'id_col': 'room_id', 'name_col': 'room_number'},
            'subjects': {'id_col': 'subject_id', 'name_col': 'CONCAT(subject_code, " - ", name)'},
        }

        mapping = display_mappings.get(fk_table_name)
        if mapping:
            query = f"SELECT {mapping['id_col']} AS id, {mapping['name_col']} AS name FROM {fk_table_name} ORDER BY {mapping['name_col']}"
            cursor.execute(query)
        else:
            query = f"SELECT DISTINCT {fk_column_name} AS id, {fk_column_name} AS name FROM {fk_table_name} ORDER BY {fk_column_name}"
            cursor.execute(query)
        
        options = cursor.fetchall()
        return jsonify(options)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/')
def index():
    conn = get_db_connection()
    table_count = 0
    if conn:
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")
        table_count = len(cursor.fetchall())
        cursor.close()
        conn.close()
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return render_template('index.html', database=db_config['database'], table_count=table_count, current_time=current_time)

@app.route('/tables')
def tables():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index'))

    cursor = conn.cursor()
    cursor.execute("SHOW TABLES")
    tables_list = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return render_template('tables.html', tables=tables_list)

@app.route('/table/<table_name>')
def table_view(table_name):
    if not is_valid_table(table_name):
        flash('Invalid table name!', 'error')
        return redirect(url_for('tables'))

    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('tables'))

    cursor = conn.cursor(dictionary=True)
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

@app.route('/subjects_management')
def subjects_management():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index'))
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
        return redirect(url_for('index'))
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
        return redirect(url_for('index'))
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
        return redirect(url_for('index'))
    cursor = conn.cursor(dictionary=True)

    batches = []
    subjects = []
    mappings = []
    academic_years = []

    try:
        cursor.execute("SELECT batch_id, year, semester FROM batches ORDER BY year, semester")
        batches = cursor.fetchall()
        cursor.execute("SELECT subject_id, name, subject_code, credits, has_lab FROM subjects ORDER BY name")
        subjects = cursor.fetchall()
        cursor.execute("SELECT year_id, year_name FROM academic_years ORDER BY year_name DESC")
        academic_years = cursor.fetchall()
        
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
        return redirect(url_for('index'))
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
        return redirect(url_for('index'))
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
        return redirect(url_for('index'))
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
        return redirect(url_for('index'))
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
        return redirect(url_for('index'))
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
def timetable_viewer():
    conn = get_db_connection()
    if conn is None:
        flash('Database connection failed!', 'error')
        return redirect(url_for('index'))
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

@app.route('/fetch_timetable_data', methods=['GET'])
def fetch_timetable_data():
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)

    section_id = request.args.get('section_id')
    faculty_id = request.args.get('faculty_id')
    room_id = request.args.get('room_id')
    
    query = """
        SELECT
            t.entry_id,
            t.day_of_week,
            ts.start_time,
            ts.end_time,
            sec.name AS section_name,
            sub.name AS subsection_name,
            u.name AS faculty_name,
            s.name AS subject_name,
            r.room_number,
            t.is_lab_session,
            t.date,
            t.week_number,
            t.is_rescheduled
        FROM timetable t
        JOIN sections sec ON t.section_id = sec.section_id
        LEFT JOIN subsections sub ON t.subsection_id = sub.subsection_id
        JOIN users u ON t.faculty_id = u.user_id
        JOIN batch_subjects bsub ON t.batch_subject_id = bsub.batch_subject_id
        JOIN subjects s ON bsub.subject_id = s.subject_id
        JOIN rooms r ON t.room_id = r.room_id
        LEFT JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
        WHERE 1=1
    """
    params = []

    if section_id:
        query += " AND t.section_id = %s"
        params.append(section_id)
    if faculty_id:
        query += " AND t.faculty_id = %s"
        params.append(faculty_id)
    if room_id:
        query += " AND t.room_id = %s"
        params.append(room_id)

    query += " ORDER BY t.day_of_week, ts.start_time, section_name, subsection_name"

    try:
        cursor.execute(query, params)
        timetable_entries = cursor.fetchall()

        for entry in timetable_entries:
            if 'start_time' in entry and entry['start_time']:
                entry['start_time'] = str(entry['start_time'])
            if 'end_time' in entry and entry['end_time']:
                entry['end_time'] = str(entry['end_time'])
            if 'date' in entry and entry['date']:
                entry['date'] = entry['date'].isoformat()
        return jsonify(timetable_entries)
    except Error as e:
        print(f"Error fetching timetable data: {e}")
        return jsonify({'error': f'Error fetching timetable data: {e}'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/fetch_room_timetable_data', methods=['GET'])
def fetch_room_timetable_data():
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        query = """
            SELECT
                t.day_of_week,
                ts.start_time,
                ts.end_time,
                r.room_number,
                sec.name AS section_name,
                s.name AS subject_name,
                u.name AS faculty_name
            FROM timetable t
            JOIN rooms r ON t.room_id = r.room_id
            JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
            JOIN sections sec ON t.section_id = sec.section_id
            JOIN batch_subjects bsub ON t.batch_subject_id = bsub.batch_subject_id
            JOIN subjects s ON bsub.subject_id = s.subject_id
            JOIN users u ON t.faculty_id = u.user_id
            ORDER BY r.room_number, t.day_of_week, ts.start_time;
        """
        cursor.execute(query)
        room_usage_data = cursor.fetchall()
        for entry in room_usage_data:
            if 'start_time' in entry and entry['start_time']:
                entry['start_time'] = str(entry['start_time'])
            if 'end_time' in entry and entry['end_time']:
                entry['end_time'] = str(entry['end_time'])
        return jsonify(room_usage_data)
    except Error as e:
        print(f"Error fetching room timetable data: {e}")
        return jsonify({'error': f'Error fetching room timetable data: {e}'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_rooms_by_type/<room_type>')
def get_rooms_by_type_api(room_type):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT room_id, room_number, room_type FROM rooms WHERE room_type = %s ORDER BY room_number", (room_type,))
        rooms = cursor.fetchall()
        return jsonify(rooms)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()
        
@app.route('/api/get_departments_by_school/<int:school_id>')
def get_departments_by_school_api(school_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT department_id, name FROM departments WHERE school_id = %s ORDER BY name", (school_id,))
        departments = cursor.fetchall()
        return jsonify(departments)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_all_departments')
def get_all_departments_api():
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT department_id, name FROM departments ORDER BY name")
        departments = cursor.fetchall()
        return jsonify(departments)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()
        
@app.route('/api/get_all_schools')
def get_all_schools_api():
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT school_id, name FROM schools ORDER BY name")
        schools = cursor.fetchall()
        return jsonify(schools)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_faculty_by_department/<int:department_id>')
def get_faculty_by_department_api(department_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT user_id, name FROM users WHERE role = 'faculty' AND department_id = %s ORDER BY name", (department_id,))
        faculties = cursor.fetchall()
        return jsonify(faculties)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_batches_by_academic_year/<int:academic_year_id>')
def get_batches_by_academic_year_api(academic_year_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT batch_id, CONCAT(year, ' (Sem ', semester, ')') AS display_name, semester FROM batches WHERE academic_year_id = %s ORDER BY year, semester", (academic_year_id,))
        batches = cursor.fetchall()
        return jsonify(batches)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()
        
@app.route('/api/get_batches_by_academic_year_and_department/<int:academic_year_id>/<int:department_id>')
def get_batches_by_academic_year_and_department_api(academic_year_id, department_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT DISTINCT b.batch_id, CONCAT(b.year, ' (Sem ', b.semester, ')') AS display_name, b.semester
            FROM batches b
            JOIN batch_departments bd ON b.batch_id = bd.batch_id
            WHERE b.academic_year_id = %s AND bd.department_id = %s
            ORDER BY b.year, b.semester
        """, (academic_year_id, department_id))
        batches = cursor.fetchall()
        return jsonify(batches)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_sections_by_batch/<int:batch_id>')
def get_sections_by_batch_api(batch_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT section_id, name FROM sections WHERE batch_id = %s ORDER BY name", (batch_id,))
        sections = cursor.fetchall()
        return jsonify(sections)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_subsections_by_section/<int:section_id>')
def get_subsections_by_section_api(section_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT subsection_id, name FROM subsections WHERE section_id = %s ORDER BY name", (section_id,))
        subsections = cursor.fetchall()
        return jsonify(subsections)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_batch_subjects_by_batch_and_semester/<int:batch_id>/<int:semester>')
def get_batch_subjects_by_batch_and_semester_api(batch_id, semester):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT bs.batch_subject_id, s.subject_id, s.name AS subject_name, s.subject_code, s.has_lab
            FROM batch_subjects bs
            JOIN subjects s ON bs.subject_id = s.subject_id
            WHERE bs.batch_id = %s AND bs.semester = %s
            ORDER BY s.name
        """, (batch_id, semester))
        batch_subjects = cursor.fetchall()
        return jsonify(batch_subjects)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_all_subjects')
def get_all_subjects_api():
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT subject_id, name, subject_code FROM subjects ORDER BY name")
        subjects = cursor.fetchall()
        return jsonify(subjects)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_all_academic_years')
def get_all_academic_years_api():
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT year_id AS id, year_name AS name FROM academic_years ORDER BY year_name DESC")
        academic_years = cursor.fetchall()
        return jsonify(academic_years)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_subjects_by_filters', methods=['GET'])
def get_subjects_by_filters_api():
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)

    department_id = request.args.get('department_id')
    academic_year_id = request.args.get('academic_year_id')
    batch_id = request.args.get('batch_id')
    semester = request.args.get('semester')

    query = "SELECT s.* FROM subjects s WHERE 1=1"
    params = []

    if department_id:
        query += """
            AND s.subject_id IN (
                SELECT bsm.subject_id FROM batch_subjects bsm
                JOIN batches b ON bsm.batch_id = b.batch_id
                JOIN batch_departments bd ON b.batch_id = bd.batch_id
                WHERE bd.department_id = %s
            )
        """
        params.append(department_id)
    
    if academic_year_id:
        query += """
            AND s.subject_id IN (
                SELECT bsm.subject_id FROM batch_subjects bsm
                JOIN batches b ON bsm.batch_id = b.batch_id
                WHERE b.academic_year_id = %s
            )
        """
        params.append(academic_year_id)

    if batch_id:
        query += """
            AND s.subject_id IN (
                SELECT bsm.subject_id FROM batch_subjects bsm
                WHERE bsm.batch_id = %s
            )
        """
        params.append(batch_id)

    if semester:
        query += """
            AND s.subject_id IN (
                SELECT bsm.subject_id FROM batch_subjects bsm
                WHERE bsm.semester = %s
            )
        """
        params.append(semester)
    
    query += " ORDER BY s.name"

    try:
        cursor.execute(query, params)
        subjects = cursor.fetchall()
        return jsonify(subjects)
    except Error as e:
        print(f"Error fetching filtered subjects: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_faculty_assignments_by_filters', methods=['GET'])
def get_faculty_assignments_by_filters_api():
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)

    department_id = request.args.get('department_id')
    academic_year_id = request.args.get('academic_year_id')
    batch_id = request.args.get('batch_id')
    semester = request.args.get('semester')
    section_id = request.args.get('section_id')
    
    query = """
        SELECT 
            fs.faculty_subject_id,
            u.user_id AS faculty_id,
            u.name AS faculty_name,
            b.batch_id,
            b.year AS batch_year,
            b.semester,
            s.subject_id,
            s.name AS subject_name,
            s.subject_code,
            sec.section_id,
            sec.name AS section_name,
            sub.subsection_id,
            sub.name AS subsection_name,
            bd.department_id
        FROM faculty_subjects fs
        JOIN users u ON fs.faculty_id = u.user_id
        JOIN batch_subjects bs ON fs.batch_subject_id = bs.batch_subject_id
        JOIN subjects s ON bs.subject_id = s.subject_id
        JOIN batches b ON bs.batch_id = b.batch_id
        LEFT JOIN sections sec ON fs.section_id = sec.section_id
        LEFT JOIN batch_departments bd ON b.batch_id = bd.batch_id
        LEFT JOIN subsections sub ON fs.subsection_id = sub.subsection_id
        WHERE 1=1
    """
    params = []

    if department_id:
        query += " AND bd.department_id = %s"
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
        query += " AND sec.section_id = %s"
        params.append(section_id)
    
    query += " ORDER BY b.year, b.semester, s.name, u.name, sec.name, sub.name"

    try:
        cursor.execute(query, params)
        assignments = cursor.fetchall()
        return jsonify(assignments)
    except Error as e:
        print(f"Error fetching filtered faculty assignments: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_batch_subject_mappings_by_filters', methods=['GET'])
def get_batch_subject_mappings_by_filters_api():
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)

    academic_year_id = request.args.get('academic_year_id')
    batch_id = request.args.get('batch_id')
    semester = request.args.get('semester')

    query = """
        SELECT bsm.batch_subject_id, bsm.batch_id, b.year AS batch_year, bsm.semester, bsm.subject_id, s.name AS subject_name, s.subject_code
        FROM batch_subjects bsm
        JOIN batches b ON bsm.batch_id = b.batch_id
        JOIN subjects s ON bsm.subject_id = s.subject_id
        WHERE 1=1
    """
    params = []

    if academic_year_id:
        query += " AND b.academic_year_id = %s"
        params.append(academic_year_id)

    if batch_id:
        query += " AND b.batch_id = %s"
        params.append(batch_id)

    if semester:
        query += " AND bsm.semester = %s"
        params.append(semester)
    
    query += " ORDER BY b.year, b.semester, s.name"

    try:
        cursor.execute(query, params)
        mappings = cursor.fetchall()
        return jsonify(mappings)
    except Error as e:
        print(f"Error fetching filtered batch subject mappings: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_semesters_by_batch/<int:batch_id>')
def get_semesters_by_batch_api(batch_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT DISTINCT semester FROM batches WHERE batch_id = %s ORDER BY semester", (batch_id,))
        semesters = [{'id': row['semester'], 'name': f"Semester {row['semester']}"} for row in cursor.fetchall()]
        return jsonify(semesters)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# New API endpoint for semesters filtered by year and department
@app.route('/api/semesters_by_year_and_department/<int:academic_year_id>/<int:department_id>')
def get_semesters_by_year_and_department_api(academic_year_id, department_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT DISTINCT b.semester
            FROM batches b
            JOIN batch_departments bd ON b.batch_id = bd.batch_id
            WHERE b.academic_year_id = %s AND bd.department_id = %s
            ORDER BY b.semester
        """, (academic_year_id, department_id))
        semesters = [{'semester': row['semester']} for row in cursor.fetchall()]
        return jsonify(semesters)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/get_sections_by_academic_year_and_batch/<int:academic_year_id>/<int:batch_id>')
def get_sections_by_academic_year_and_batch_api(academic_year_id, batch_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed!'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT sec.section_id, sec.name
            FROM sections sec
            JOIN batches b ON sec.batch_id = b.batch_id
            WHERE b.academic_year_id = %s AND b.batch_id = %s
            ORDER BY sec.name
        """, (academic_year_id, batch_id))
        sections = cursor.fetchall()
        return jsonify(sections)
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/get_batches_by_department/<int:department_id>')
def get_batches_by_department_api(department_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Databas