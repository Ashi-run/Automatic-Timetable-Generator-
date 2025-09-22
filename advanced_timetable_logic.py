import random
import json
import re
import numpy as np
from datetime import datetime, timedelta, date, time
from collections import defaultdict
import logging
import mysql.connector
from mysql.connector import Error
from contextlib import contextmanager
import io
from itertools import groupby, cycle

class DBConfig:
    DB_HOST = '127.0.0.1'
    DB_USER = 'root'
    DB_PASSWORD = ''
    DB_NAME = 'reclassify'
    SECRET_KEY = 'nmims_timetable_secret_key_2025'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db_config = {
    'host': DBConfig.DB_HOST,
    'user': DBConfig.DB_USER,
    'password': DBConfig.DB_PASSWORD,
    'database': DBConfig.DB_NAME
}

def get_db_connection():
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

class TimetableGenerator:
    """
    Generates and manages timetables based on various constraints using a heuristic-based approach.
    """
    def __init__(self):
        logger.info("TimetableGenerator initialized with heuristic-based algorithm.")
        self.problem_data = {}
        # Penalty weights are no longer used by the heuristic, but are kept for logging purposes
        self.PENALTY_HARD = 1000
        self.PENALTY_MEDIUM = 50
        self.PENALTY_SOFT = 1

    def __del__(self):
        pass

    def _execute_query(self, query, params=None, fetch_one=False, dictionary_cursor=True):
        """Helper method to execute a SELECT query."""
        result = None
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor(dictionary=dictionary_cursor, buffered=True)
                try:
                    cursor.execute(query, params)
                    if fetch_one:
                        result = cursor.fetchone()
                    else:
                        result = cursor.fetchall()
                    while cursor.nextset():
                        pass
                finally:
                    cursor.close()
                return result
        except mysql.connector.Error as e:
            logger.error(f"Database error in _execute_query: {e}", exc_info=True)
            raise

    def _execute_dml(self, query, params=None, many=False):
        """Helper method to execute DML (INSERT, UPDATE, DELETE) queries."""
        lastrowid = None
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor(buffered=True)
                try:
                    if many:
                        cursor.executemany(query, params)
                    else:
                        cursor.execute(query, params)
                        lastrowid = cursor.lastrowid
                    while cursor.nextset():
                        pass
                    conn.commit()
                finally:
                    cursor.close()
                return lastrowid if not many else True
        except mysql.connector.Error as e:
            logger.error(f"Database error in _execute_dml: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error in _execute_dml: {e}", exc_info=True)
            return False

    def save_generation_log(self, section_id, log_data):
        """Save timetable generation log to the database and return the log_id."""
        query = """
            INSERT INTO timetable_generation_log
            (section_id, status, constraints_violated, total_slots_assigned, total_slots_required, generation_time_seconds)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        status = log_data.get('generation_status', 'Failed')
        constraints_violated = json.dumps(log_data.get('constraints_violated', []))
        total_slots_assigned = log_data.get('total_slots_assigned', 0)
        total_slots_required = log_data.get('total_slots_required', 0)
        generation_time_seconds = log_data.get('generation_time_seconds', 0)

        params = (
            section_id,
            status,
            constraints_violated,
            total_slots_assigned,
            total_slots_required,
            generation_time_seconds
        )
        try:
            log_id = self._execute_dml(query, params)
            if log_id:
                logger.info(f"Timetable generation log saved with log_id: {log_id}")
            else:
                logger.error("Failed to save timetable generation log.")
            return log_id
        except mysql.connector.Error:
            return None

    def save_timetable_to_db(self, log_id, timetable_data):
        """
        Save the generated timetable entries to the 'timetable' table, linked by log_id.
        This function *adds* new entries and *does not delete* previous timetables.
        """
        try:
            logger.info(f"Attempting to save timetable entries for log_id {log_id}")
            insert_data = []
            for entry in timetable_data['raw_timetable']:
                insert_data.append((
                    entry['section_id'],
                    entry['faculty_id'],
                    entry['batch_subject_id'],
                    entry['timeslot_id'],
                    entry['day_of_week'],
                    entry['room_id'],
                    entry['subsection_id'],
                    entry['week_number'],
                    entry['date'],
                    entry.get('is_rescheduled', 0),
                    entry.get('is_lab_session', 0),
                    log_id
                ))

            if insert_data:
                query = """
                    INSERT INTO timetable
                    (section_id, faculty_id, batch_subject_id, timeslot_id, day_of_week, room_id,
                     subsection_id, week_number, date, is_rescheduled, is_lab_session, log_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                self._execute_dml(query, insert_data, many=True)
                logger.info(f"Successfully saved timetable entries for log_id {log_id}")
            else:
                logger.info(f"No timetable entries to save for log_id {log_id}")
            return True
        except mysql.connector.Error:
            return False
        except Exception as e:
            logger.error(f"Unexpected error saving timetable for log_id {log_id}: {e}", exc_info=True)
            return False

    def delete_existing_timetable(self, section_id):
        """Deletes all existing timetable entries for a specific section."""
        query = "DELETE FROM timetable WHERE section_id = %s"
        try:
            self._execute_dml(query, (section_id,))
            logger.info(f"Successfully deleted all old timetable entries for section {section_id}.")
            return True
        except Exception as e:
            logger.error(f"Failed to delete old timetable for section {section_id}: {e}", exc_info=True)
            return False

    def _capture_completed_sessions(self, section_id):
        """
        Captures the count of completed sessions (entries with date <= today)
        and updates the `lecture_trackers` table.
        """
        logger.info(f"Capturing completed sessions for section {section_id} before deletion.")
        today = date.today()
        query = """
            SELECT batch_subject_id, COUNT(*) AS completed_count
            FROM timetable
            WHERE section_id = %s AND date <= %s
            GROUP BY batch_subject_id
        """
        completed_sessions = self._execute_query(query, (section_id, today))

        if not completed_sessions:
            logger.info(f"No completed sessions found for section {section_id} to track.")
            return
        
        for session in completed_sessions:
            batch_subject_id = session['batch_subject_id']
            completed_count = session['completed_count']

            check_query = """
                SELECT conducted FROM lecture_trackers
                WHERE section_id = %s AND batch_subject_id = %s
            """
            existing_entry = self._execute_query(check_query, (section_id, batch_subject_id), fetch_one=True)

            if existing_entry:
                update_query = """
                    UPDATE lecture_trackers SET conducted = %s WHERE section_id = %s AND batch_subject_id = %s
                """
                self._execute_dml(update_query, (completed_count, section_id, batch_subject_id))
                logger.info(f"Updated conducted count for batch_subject_id {batch_subject_id} in section {section_id} to {completed_count}.")
            else:
                insert_query = """
                    INSERT INTO lecture_trackers (section_id, batch_subject_id, total_required, conducted)
                    VALUES (%s, %s, %s, %s)
                """
                self._execute_dml(insert_query, (section_id, batch_subject_id, 0, completed_count))
                logger.info(f"Inserted new lecture tracker for batch_subject_id {batch_subject_id} in section {section_id} with count {completed_count}.")

    def get_faculty_constraints(self, faculty_id):
        """Retrieves specific constraints for a given faculty member."""
        query = "SELECT * FROM faculty_constraints WHERE faculty_id = %s"
        constraints = self._execute_query(query, (faculty_id,), fetch_one=True, dictionary_cursor=True)
        
        if not constraints:
            return {
                'max_hours_per_week': 20,
                'max_hours_per_day': 4,
                'is_visiting_faculty': False,
                'available_days': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'],
                'min_weekly_hours': 0,
                'max_weekly_hours': 20
            }

        available_days_raw = constraints.get('available_days')
        if isinstance(available_days_raw, bytes):
            try:
                available_days_raw = available_days_raw.decode('utf-8')
            except UnicodeDecodeError:
                logger.error(f"Failed to decode available_days for faculty {faculty_id}: {available_days_raw}")
                available_days_raw = None

        if available_days_raw:
            try:
                constraints['available_days'] = json.loads(available_days_raw)
                if not isinstance(constraints['available_days'], list):
                    constraints['available_days'] = None
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in available_days for faculty {faculty_id}: {available_days_raw}. Setting to None.")
                constraints['available_days'] = None
        else:
            constraints['available_days'] = None
        
        defaults = {
            'max_hours_per_week': 20,
            'max_hours_per_day': 4,
            'is_visiting_faculty': 0,
            'available_days': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'],
            'min_weekly_hours': 0,
            'max_weekly_hours': 20
        }
        for key, default_value in defaults.items():
            if key not in constraints or constraints[key] is None:
                constraints[key] = default_value
        return constraints

    def get_all_generation_logs(self, status_filter=None):
        """Retrieves a list of all timetable generation logs."""
        query = """
            SELECT tgl.log_id, tgl.generation_date, tgl.status,
                s.name as section_name, d.name as department_name, ay.year_name as academic_year,
                tgl.total_slots_assigned, tgl.total_slots_required, tgl.generation_time_seconds
            FROM timetable_generation_log tgl
            JOIN sections s ON tgl.section_id = s.section_id
            JOIN batches b ON s.batch_id = b.batch_id
            JOIN academic_years ay ON b.academic_year_id = ay.year_id
            JOIN batch_departments bd ON b.batch_id = bd.batch_id
            JOIN departments d ON bd.department_id = d.department_id
            JOIN schools sch ON d.school_id = sch.school_id
            WHERE tgl.log_id IN (
                SELECT MAX(log_id)
                FROM timetable_generation_log
                GROUP BY section_id
            )
        """
        params = []
        if status_filter:
            query += " AND tgl.status = %s"
            params.append(status_filter)

        query += " ORDER BY tgl.generation_date DESC"

        try:
            return self._execute_query(query, params, dictionary_cursor=True)
        except mysql.connector.Error as e:
            logger.error(f"Database error getting all generation logs: {e}", exc_info=True)
            return []

    def _translate_violation_messages(self, violations_list, all_timeslots_map=None):
        """
        FIX: Translates raw violation messages with numeric slots into human-readable format.
        """
        if all_timeslots_map is None:
            all_timeslots_map = {ts['timeslot_id']: ts for ts in self._execute_query("SELECT * FROM timeslots")}
        
        day_map = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday', 5: 'Saturday'}
        translated_violations = []

        for violation_str in violations_list:
            if not isinstance(violation_str, str):
                translated_violations.append(str(violation_str))
                continue
            
            match = re.search(r'at slot \((\d+), (\d+)\)', violation_str)
            if match:
                try:
                    day_idx = int(match.group(1))
                    ts_id = int(match.group(2))
                    
                    day_name = day_map.get(day_idx, 'Unknown Day')
                    timeslot_info = all_timeslots_map.get(ts_id)
                    
                    if timeslot_info:
                        start_time = (datetime.min + timeslot_info['start_time']).time().strftime('%I:%M %p')
                        end_time = (datetime.min + timeslot_info['end_time']).time().strftime('%I:%M %p')
                        time_str = f"{start_time} - {end_time}"
                        
                        readable_location = f"on {day_name} at {time_str}"
                        new_violation_str = violation_str.replace(match.group(0), readable_location)
                        translated_violations.append(new_violation_str)
                    else:
                        translated_violations.append(violation_str) # Append original if lookup fails
                except (ValueError, IndexError):
                     translated_violations.append(violation_str) # Append original on parsing error
            else:
                translated_violations.append(violation_str) # Append original if no slot pattern found
        return translated_violations
    
    def load_specific_timetable(self, log_id):
        """
        Loads a timetable and dynamically includes extra class rows only if they are used.
        """
        try:
            raw_timetable_data = self.load_specific_timetable_raw(log_id)
            if not raw_timetable_data:
                return {"error": f"No timetable found for log ID: {log_id}"}
            
            all_timeslot_ids_in_use = {entry['timeslot_id'] for entry in raw_timetable_data}
            
            query = """
                SELECT * FROM timeslots 
                WHERE is_active = 1 OR timeslot_id IN ({})
                ORDER BY start_time, day_of_week
            """.format(','.join(map(str, all_timeslot_ids_in_use)) if all_timeslot_ids_in_use else 'NULL')
            
            all_timeslots_for_grid = self._execute_query(query)
            
            if not all_timeslots_for_grid:
                return {"error": "No timeslots found. Cannot format timetable."}

            grid, timeslot_labels = self.format_timetable_grid(raw_timetable_data, all_timeslots_for_grid)
            
            timetable_by_day = self.format_timetable_by_day(raw_timetable_data)

            log_entry = self._execute_query("SELECT * FROM timetable_generation_log WHERE log_id = %s", (log_id,), fetch_one=True)
            if log_entry and log_entry.get('constraints_violated'):
                try:
                    violations_list = json.loads(log_entry['constraints_violated'])
                except (json.JSONDecodeError, TypeError):
                    violations_list = [str(log_entry['constraints_violated'])]
                
                # FIX: Translate messages when loading old logs
                log_entry['constraints_violated'] = self._translate_violation_messages(violations_list)

            return {
                'status': log_entry['status'] if log_entry else 'Unknown',
                'section_id': raw_timetable_data[0]['section_id'],
                'section_name': raw_timetable_data[0]['section_name'],
                'generation_log': log_entry,
                'grid': grid,
                'timetable': timetable_by_day, # FIX: Added the timetable_by_day dictionary here
                'timeslot_labels': timeslot_labels,
                'log_id': log_id,
                'raw_timetable': raw_timetable_data
            }
        except Exception as e:
            logger.error(f"Error loading specific timetable for log_id {log_id}: {str(e)}", exc_info=True)
            return {"error": f"Unexpected error: {str(e)}"}
           
    def load_specific_timetable_raw(self, log_id):
        """Loads a previously saved timetable for display using its log_id."""
        query = """
            SELECT t.*, ts.day_of_week, ts.start_time as timeslot_start_time, ts.end_time as timeslot_end_time,
                   s.subject_id, s.name AS subject_name, s.subject_code, s.has_lab AS is_lab_session,
                   u.name AS faculty_name, r.room_number, sec.name as section_name,
                   bs.batch_subject_id, b.year as academic_year_int, b.semester as semester_int
            FROM timetable t
            JOIN timeslots ts ON t.timeslot_id = ts.timeslot_id
            JOIN batch_subjects bs ON t.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            JOIN users u ON t.faculty_id = u.user_id
            LEFT JOIN rooms r ON t.room_id = r.room_id
            JOIN sections sec ON t.section_id = sec.section_id
            JOIN batches b ON sec.batch_id = b.batch_id
            WHERE t.log_id = %s
            ORDER BY t.date, ts.start_time
        """

        rows = self._execute_query(query, (log_id,), dictionary_cursor=True)
        if not rows:
            return []

        timetable_data_for_processing = []
        for row in rows:
            start_time_obj = row['timeslot_start_time']
            end_time_obj = row['timeslot_end_time']
            
            # This part correctly converts timedelta from the DB to datetime.time
            if isinstance(start_time_obj, timedelta):
                start_time_obj = (datetime.min + start_time_obj).time()
            
            if isinstance(end_time_obj, timedelta):
                end_time_obj = (datetime.min + end_time_obj).time()

            timetable_data_for_processing.append({
                'entry_id': row['entry_id'],
                'section_id': row['section_id'],
                'section_name': row['section_name'],
                'faculty_id': row['faculty_id'],
                'faculty_name': row['faculty_name'],
                'subject_id': row['subject_id'],
                'subject_name': row['subject_name'],
                'subject_code': row['subject_code'],
                'batch_subject_id': row['batch_subject_id'],
                'timeslot_id': row['timeslot_id'],
                'day_of_week': row['day_of_week'],
                'room_id': row['room_id'],
                'room_number': row.get('room_number', 'N/A'),
                'date': row['date'],
                'is_rescheduled': row.get('is_rescheduled', 0),
                'is_lab_session': row['is_lab_session'],
                'subsection_id': row.get('subsection_id'),
                'week_number': row['week_number'],
                'is_rescheduled': row['is_rescheduled'],
                'academic_year_int': row['academic_year_int'],
                'semester_int': row['semester_int'],
                'start_time': start_time_obj,
                'end_time': end_time_obj
            })
        return timetable_data_for_processing

    def format_timetable_by_day(self, timetable):
        """Organizes the raw timetable data into a dictionary grouped by day of the week."""
        days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        formatted = {day: [] for day in days_order}
        for session in timetable:
            day = session['day_of_week']
            formatted[day].append(session)
        for day in formatted:
            if formatted[day]:
                # Sort directly by the datetime.time object
                formatted[day].sort(key=lambda x: x['start_time'])
        return formatted

    def format_timetable_grid(self, timetable, timeslots):
        """
        Transforms the timetable data into a grid format suitable for display.
        """
        unique_timeslots = {}
        for slot in timeslots:
            start_time_obj = slot['start_time']
            end_time_obj = slot['end_time']
            if isinstance(start_time_obj, timedelta):
                start_time_obj = (datetime.min + start_time_obj).time()
            if isinstance(end_time_obj, timedelta):
                end_time_obj = (datetime.min + end_time_obj).time()
            
            start = start_time_obj.strftime('%H:%M')
            end = end_time_obj.strftime('%H:%M')
            unique_timeslots[(start, end)] = f"{start}-{end}"
            
        timeslot_labels = [f"{start}-{end}" for start, end in sorted(unique_timeslots.keys())]
        days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        grid = {day: {slot: None for slot in timeslot_labels} for day in days_order}
        
        # Sort the timetable entries using the consistent datetime.time objects
        timetable.sort(key=lambda x: (days_order.index(x['day_of_week']), x['start_time']))

        for session in timetable:
            day = session['day_of_week']
            start_time_str = session['start_time'].strftime('%H:%M')
            
            is_lab = session.get('is_lab_session', False)
            duration_hours = int((datetime.combine(date.today(), session['end_time']) - datetime.combine(date.today(), session['start_time'])).total_seconds() / 3600)
            
            current_time = session['start_time']
            for i in range(duration_hours):
                current_end_time = (datetime.combine(date.today(), current_time) + timedelta(hours=1)).time()
                time_key = f"{current_time.strftime('%H:%M')}-{current_end_time.strftime('%H:%M')}"
                
                # Only add the session details to the first hour of the block
                if i == 0:
                    grid[day][time_key] = {
                        'subject': session['subject_name'],
                        'faculty': session.get('faculty_name', 'Unassigned'),
                        'room': session.get('room_number', 'N/A'),
                        'is_lab': is_lab
                    }
                else:
                    # Mark subsequent slots as part of a merged class
                    grid[day][time_key] = {'is_merged_cell': True}
                
                current_time = current_end_time
        
        return grid, timeslot_labels

    def generate_timetable_for_section(self, section_id, start_date=None, semester_weeks=1):
        """
        Main function to generate a timetable using a heuristic-based approach.
        """
        generation_start = datetime.now()
        logger.info(f"Starting heuristic timetable generation for section {section_id}")
        
        try:
            self.delete_existing_timetable(section_id)
            data = self._fetch_problem_data(section_id)
            if "error" in data:
                return data
            
            self.problem_data = self._prepare_problem_data(data)
            if "error" in self.problem_data:
                return self.problem_data

            final_timetable = []
            violations = []
            
            # Keep track of occupied slots for all resources
            occupied_slots = {
                'section': defaultdict(list),
                'faculty': defaultdict(set),
                'room': defaultdict(set)
            }
            
            # Heuristic Logic: Prioritize subjects that are harder to schedule
            all_assignments = sorted(self.problem_data['assignments'], key=lambda x: (x['is_lab'], x['duration']), reverse=True)

            for assignment in all_assignments:
                # 1. Find a suitable room first based on assignment type
                room_id = self._select_room(assignment)

                if room_id is None:
                    violations.append(f"No suitable room could be found for subject {assignment['subject_name']}.")
                    continue
                
                # 2. Find a suitable time slot for the entire duration
                required_duration = int(assignment['duration'])
                available_slots = self._find_available_slot(assignment, room_id, occupied_slots)
                
                if not available_slots:
                    violations.append(f"No free time slot found for {assignment['subject_name']} with faculty {assignment['faculty_name']}.")
                    continue

                # Take the first available slot block
                slot_block = available_slots[0]

                # 3. Add to timetable and mark slots as occupied
                for day_idx, timeslot_id in slot_block:
                    timeslot_info = self.problem_data['all_timeslots'][timeslot_id]
                    day_of_week = self.problem_data['day_map_rev'][day_idx]

                    final_timetable.append({
                        'section_id': self.problem_data['section_id'],
                        'section_name': self.problem_data['section_info']['name'],
                        'faculty_id': assignment['faculty_id'],
                        'faculty_name': assignment['faculty_name'],
                        'subject_id': assignment['subject_id'],
                        'subject_name': assignment['subject_name'],
                        'subject_code': assignment['subject_code'],
                        'batch_subject_id': assignment['batch_subject_id'],
                        'timeslot_id': timeslot_info['timeslot_id'],
                        'day_of_week': day_of_week,
                        'room_id': room_id,
                        'room_number': self.problem_data['all_rooms'][room_id]['room_number'],
                        'subsection_id': None,
                        'week_number': 1,
                        'date': date.today(),
                        'is_rescheduled': 0,
                        'is_lab_session': assignment['is_lab'],
                        # Correcting this line to handle time objects directly
                        'start_time': timeslot_info['start_time'],
                        'end_time': timeslot_info['end_time']
                    })
                    
                    slot_key = (day_idx, timeslot_info['timeslot_id'])
                    occupied_slots['section'][slot_key].append('full')
                    occupied_slots['faculty'][assignment['faculty_id']].add(slot_key)
                    occupied_slots['room'][room_id].add(slot_key)

            # --- Finalize and save results ---
            generation_time = datetime.now() - generation_start
            generation_log = {
                'constraints_violated': violations,
                'total_slots_assigned': len(final_timetable),
                'total_slots_required': self.problem_data.get('total_assignments_to_schedule', 0),
                'generation_status': 'Partial' if violations else 'Success',
                'generation_time_seconds': generation_time.total_seconds()
            }
            
            log_id = self.save_generation_log(section_id, generation_log)
            self.save_timetable_to_db(log_id, {'raw_timetable': final_timetable})
            
            grid, timeslot_labels = self.format_timetable_grid(final_timetable, self.problem_data['all_timeslots'].values())
            
            return {
                'status': generation_log['generation_status'],
                'section_id': section_id,
                'section_name': data['section_info']['name'],
                'batch_id': data['section_info']['batch_id'],
                'department': data['section_info']['department_name'],
                'generation_log': generation_log,
                'raw_timetable': final_timetable,
                'grid': grid,
                'timeslot_labels': timeslot_labels,
                'generation_seconds': generation_time.total_seconds(),
                'generated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'start_date': start_date,
                'end_date': start_date + timedelta(days=6) if start_date else None,
                'log_id': log_id
            }

        except Exception as e:
            logger.error(f"Unexpected error in heuristic generation: {str(e)}", exc_info=True)
            return {"error": f"Unexpected error: {str(e)}"}     
    
    def _fetch_problem_data(self, section_id):
        """Fetches all data required for the scheduling problem."""
        section_info = self._execute_query("""
            SELECT s.section_id, s.name, s.batch_id, se.total_students, se.max_subsection_size,
                b.academic_year_id, b.semester, d.name as department_name, ay.year_name, s.theory_room_id
            FROM sections s
            LEFT JOIN section_enrollment se ON s.section_id = se.section_id
            JOIN batches b ON s.batch_id = b.batch_id
            JOIN batch_departments bd ON b.batch_id = bd.batch_id
            JOIN departments d ON bd.department_id = d.department_id
            JOIN academic_years ay ON b.academic_year_id = ay.year_id
            WHERE s.section_id = %s
        """, (section_id,), fetch_one=True)

        if not section_info:
            return {"error": f"Section ID {section_id} not found."}

        self.all_timeslots = self._execute_query("SELECT * FROM timeslots WHERE is_active = 1")
        self.all_rooms = self._execute_query("SELECT * FROM rooms WHERE is_active = 1")

        faculty_assignments = self._execute_query("""
            SELECT fs.*, bs.subject_id, s.name as subject_name, s.credits,
                s.theory_sessions_per_week, s.lab_sessions_per_week,
                u.name as faculty_name, s.subject_code, s.has_lab, s.lab_duration_hours,
                s.is_lab_continuous,
                bs.preferred_lab_room_id
            FROM faculty_subjects fs
            JOIN batch_subjects bs ON fs.batch_subject_id = bs.batch_subject_id
            JOIN subjects s ON bs.subject_id = s.subject_id
            JOIN users u ON fs.faculty_id = u.user_id
            WHERE fs.section_id = %s
        """, (section_id,))

        if not faculty_assignments:
            return {"error": f"No faculty assignments found for section {section_id}."}

        all_assigned_faculty_ids = {fa['faculty_id'] for fa in faculty_assignments}
        
        self.faculty_constraints = {}
        for faculty_id in all_assigned_faculty_ids:
            self.faculty_constraints[faculty_id] = self.get_faculty_constraints(faculty_id)

        faculty_unavailability_data = self._execute_query("SELECT * FROM faculty_unavailability")
        self.faculty_unavailability = defaultdict(list)
        for ua in faculty_unavailability_data:
            self.faculty_unavailability[(ua['faculty_id'], ua['day_of_week'])].append(ua)

        self.holidays = set()
        
        return {
            'section_info': section_info,
            'faculty_assignments': faculty_assignments,
            'all_timeslots': self.all_timeslots,
            'all_rooms': self.all_rooms,
            'all_rooms_list': self.all_rooms,
            'faculty_assignments_raw': {fa['faculty_subject_id']: fa for fa in faculty_assignments},
            'faculty_constraints': self.faculty_constraints,
            'faculty_unavailability': self.faculty_unavailability,
        }
    
    def _prepare_problem_data(self, data):
        """
        Prepares a list of all sessions to be scheduled, handling multiple faculty per subject.
        """
        assignments = []
        
        # Group assignments by subject and batch
        subject_groups = groupby(sorted(data['faculty_assignments'], key=lambda x: x['batch_subject_id']), 
                                 key=lambda x: x['batch_subject_id'])
        
        for batch_subject_id, group in subject_groups:
            assignments_for_subject = list(group)
            
            # Use the first entry to get subject-level details
            first_assignment = assignments_for_subject[0]
            
            # Create a cycling iterator for faculty assigned to this subject to distribute sessions
            faculty_cycle = cycle([(fa['faculty_id'], fa['faculty_name']) for fa in assignments_for_subject])
            
            # Use values from the database columns for session counts
            theory_sessions_per_week = first_assignment.get('theory_sessions_per_week', 0)
            lab_sessions_per_week = first_assignment.get('lab_sessions_per_week', 0)
            
            lab_duration_value = first_assignment.get('lab_duration_hours')
            lab_duration_hours = float(lab_duration_value) if lab_duration_value is not None else 1.0
            
            preferred_lab_room = first_assignment.get('preferred_lab_room_id')
            preferred_theory_room = data['section_info'].get('theory_room_id')
            is_continuous = first_assignment.get('is_lab_continuous', True)
            
            # Create theory sessions and assign them to faculty in a round-robin fashion
            for _ in range(theory_sessions_per_week):
                faculty_id, faculty_name = next(faculty_cycle)
                assignments.append({
                    'assignment_id': first_assignment['faculty_subject_id'], 'faculty_id': faculty_id,
                    'faculty_name': faculty_name,
                    'subject_id': first_assignment['subject_id'],
                    'subject_name': first_assignment['subject_name'],
                    'subject_code': first_assignment['subject_code'],
                    'batch_subject_id': batch_subject_id, 'is_lab': False,
                    'duration': 1, 'subsection_id': 'full',
                    'preferred_room_id': preferred_theory_room, 'is_lab_continuous': False
                })

            # Create lab sessions and assign them to faculty in a round-robin fashion
            for _ in range(lab_sessions_per_week):
                faculty_id, faculty_name = next(faculty_cycle)
                assignments.append({
                    'assignment_id': first_assignment['faculty_subject_id'], 'faculty_id': faculty_id,
                    'faculty_name': faculty_name,
                    'subject_id': first_assignment['subject_id'],
                    'subject_name': first_assignment['subject_name'],
                    'subject_code': first_assignment['subject_code'],
                    'batch_subject_id': batch_subject_id, 'is_lab': True,
                    'duration': lab_duration_hours, 'subsection_id': 'full',
                    'preferred_room_id': preferred_lab_room, 'is_lab_continuous': is_continuous
                })
        
        if not assignments:
             return {"error": "No sessions could be generated from faculty assignments. Check subject session counts in the database."}

        # Shuffle to prevent bias, then sort by duration descending to schedule multi-hour classes first
        random.shuffle(assignments)
        assignments.sort(key=lambda x: x['duration'], reverse=True)

        possible_slots = []
        for timeslot in data['all_timeslots']:
            for day_index, day in enumerate(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']):
                if timeslot['day_of_week'] == day:
                    possible_slots.append((day_index, timeslot['timeslot_id']))

        day_map_rev = {i: day for i, day in enumerate(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'])}

        return {
            'section_id': data['section_info']['section_id'],
            'section_info': data['section_info'],
            'assignments': assignments,
            'total_assignments_to_schedule': len(assignments),
            'possible_slots': possible_slots,
            'all_timeslots': {ts['timeslot_id']: ts for ts in data['all_timeslots']},
            'all_rooms': {r['room_id']: r for r in data['all_rooms']},
            'all_rooms_list': data['all_rooms'],
            'faculty_assignments_raw': {fa['faculty_subject_id']: fa for fa in data['faculty_assignments']},
            'faculty_constraints': self.faculty_constraints,
            'faculty_unavailability': data['faculty_unavailability'],
            'day_map_rev': day_map_rev,
            'faculty_assignments': data['faculty_assignments'] 
        }

    def _select_room(self, assignment):
        """
        Selects a room for an assignment, strictly enforcing preferred rooms for theory,
        and finding the best available lab for lab sessions.
        """
        is_lab = assignment['is_lab']
        preferred_room_id = assignment.get('preferred_room_id')
        students_in_session = self.problem_data['section_info'].get('total_students', 0)

        if not is_lab:
            # For theory sessions, we prioritize the section's default room
            section_room_id = self.problem_data['section_info'].get('theory_room_id')
            return section_room_id if section_room_id else self._find_available_room_by_type('Lecture', students_in_session)

        room_type_needed = 'Lab'

        if preferred_room_id and preferred_room_id in self.problem_data['all_rooms']:
            preferred_room = self.problem_data['all_rooms'][preferred_room_id]
            if preferred_room['room_type'] == room_type_needed:
                return preferred_room_id

        return self._find_available_room_by_type(room_type_needed, students_in_session)

    def _find_available_room_by_type(self, room_type, min_capacity):
        """Finds an available room of a specific type with sufficient capacity."""
        suitable_rooms = [
            room['room_id'] for room in self.problem_data['all_rooms_list']
            if room['room_type'] == room_type and room['capacity'] >= min_capacity
        ]
        if suitable_rooms:
            return random.choice(suitable_rooms)
        return None

    def _find_available_slot(self, assignment, room_id, occupied_slots):
        """
        Finds a continuous block of time slots for an assignment, respecting all constraints.
        """
        required_duration = int(assignment['duration'])
        faculty_id = assignment['faculty_id']
        is_lab_required = assignment['is_lab']
        is_continuous_lab = assignment['is_lab_continuous']
        
        possible_slots = []
        days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        all_slots_by_day = defaultdict(list)
        for ts in self.problem_data['all_timeslots'].values():
            if isinstance(ts['start_time'], timedelta):
                ts['start_time'] = (datetime.min + ts['start_time']).time()
            if isinstance(ts['end_time'], timedelta):
                ts['end_time'] = (datetime.min + ts['end_time']).time()
            all_slots_by_day[ts['day_of_week']].append(ts)
        
        for day_index, day_of_week in enumerate(days_order):
            day_slots = sorted(all_slots_by_day[day_of_week], key=lambda x: x['start_time'])
            
            if len(day_slots) < required_duration:
                continue

            for i in range(len(day_slots) - required_duration + 1):
                slot_block = []
                is_valid_block = True
                
                # Check for physical time continuity for the entire block if required
                if is_continuous_lab and required_duration > 1:
                    for j in range(required_duration - 1):
                        current_end_time = day_slots[i+j]['end_time']
                        next_start_time = day_slots[i+j+1]['start_time']
                        if current_end_time != next_start_time:
                            is_valid_block = False
                            break
                
                if not is_valid_block:
                    continue

                # Now check for resource conflicts
                for j in range(required_duration):
                    next_slot = day_slots[i+j]
                    slot_key = (day_index, next_slot['timeslot_id'])

                    # Check for section conflict
                    if occupied_slots['section'].get(slot_key):
                        is_valid_block = False; break
                    
                    # Check for faculty conflict
                    if slot_key in occupied_slots['faculty'].get(faculty_id, set()):
                        is_valid_block = False; break
                    
                    # Check for room conflict
                    if room_id in occupied_slots['room'].get(slot_key, set()):
                        is_valid_block = False; break
                    
                    slot_block.append(slot_key)
                
                if is_valid_block:
                    possible_slots.append(slot_block)

        random.shuffle(possible_slots)
        return possible_slots


def generate_timetable_wrapper(section_id, start_date=None, semester_weeks=1):
    try:
        logger.info(f"Starting wrapper for section {section_id}")
        generator = TimetableGenerator()
        result = generator.generate_timetable_for_section(section_id, start_date, semester_weeks=1)
        return result
    except Exception as e:
        logger.error(f"Wrapper function error: {str(e)}", exc_info=True)
        return {"error": f"Unexpected error: {str(e)}"}

def generate_csv_output(timetables_data_list):
    """
    Generates a CSV string from a list of raw timetable data for multiple sections.
    Each section's timetable will be preceded by a descriptive header.
    """
    output = io.StringIO()
    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

    all_timeslot_strings = set()
    for timetable_raw_container in timetables_data_list:
        for entry in timetable_raw_container['raw_timetable']:
            start_time = entry['start_time'].strftime('%H:%M')
            end_time = entry['end_time'].strftime('%H:%M')
            all_timeslot_strings.add(f"{start_time}-{end_time}")
    
    sorted_timeslot_strings = sorted(list(all_timeslot_strings))

    header_row = ["Day"] + sorted_timeslot_strings
    
    for timetable_data in timetables_data_list:
        section_name = timetable_data['section_name']
        department_name = timetable_data['department']
        academic_year_display = f"Year {timetable_data.get('academic_year_int', 'N/A')}"
        semester_display = f"Semester {timetable_data.get('semester_int', 'N/A')}"

        output.write(f"\n\nTimetable for {department_name} - {academic_year_display} - {semester_display} - Section {section_name}\n")
        output.write(",".join(header_row) + "\n")

        grid_for_csv = {day: {slot: "" for slot in sorted_timeslot_strings} for day in days_order}
        
        for entry in timetable_data['raw_timetable']:
            day = entry['day_of_week']
            start_time = entry['start_time'].strftime('%H:%M')
            end_time = entry['end_time'].strftime('%H:%M')
            time_key = f"{start_time}-{end_time}"
            
            if day in grid_for_csv and time_key in grid_for_csv[day]:
                faculty_name = entry.get('faculty_name', 'Unassigned')
                room_number = entry.get('room_number', 'N/A')
                subject_name = entry['subject_name']
                
                cell_content = f"{subject_name} ({faculty_name}) [{room_number}]"
                
                if grid_for_csv[day][time_key]:
                    grid_for_csv[day][time_key] += f" / {cell_content}"
                else:
                    grid_for_csv[day][time_key] = cell_content

        for day in days_order:
            row_data = [day]
            for slot in sorted_timeslot_strings:
                content = grid_for_csv[day][slot].replace('"', '""')
                if ',' in content or '\n' in content:
                    row_data.append(f'"{content}"')
                else:
                    row_data.append(content)
            output.write(",".join(row_data) + "\n")

    return output.getvalue()

def get_schools():
    """Retrieves a list of all schools from the database."""
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True, buffered=True)
        try:
            cursor.execute("SELECT * FROM schools ORDER BY name")
            result = cursor.fetchall()
            while cursor.nextset():
                pass
            return result
        finally:
            cursor.close()

def get_departments_by_school(school_id):
    """Retrieves departments associated with a specific school."""
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True, buffered=True)
        try:
            cursor.execute("""
                SELECT * FROM departments
                WHERE school_id = %s
                ORDER BY name
            """, (school_id,))
            result = cursor.fetchall()
            while cursor.nextset():
                pass
            return result
        finally:
            cursor.close()

def get_academic_years():
    """Retrieves all academic years from the database."""
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True, buffered=True) as cursor:
            cursor.execute("SELECT * FROM academic_years ORDER BY start_year DESC")
            result = cursor.fetchall()
            while cursor.nextset():
                pass
            return result

def get_semesters_by_year(year_id):
    """Retrieves distinct semesters available for a given academic year."""
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True, buffered=True) as cursor:
            cursor.execute("""
                SELECT DISTINCT semester
                FROM batches
                WHERE academic_year_id = %s
                ORDER BY semester
            """, (year_id,))
            result = cursor.fetchall()
            while cursor.nextset():
                pass
            return result

def get_sections_by_filters(school_id=None, dept_id=None, year_id=None, semester=None):
    """
    Retrieves sections based on a combination of filters.
    Fixed to ensure correct joins for all academic years and semesters.
    """
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True, buffered=True) as cursor:
            query = """
                SELECT DISTINCT
                    s.section_id,
                    s.name as section_name,
                    s.batch_id,
                    d.name as department_name,
                    sch.name as school_name,
                    ay.year_name as academic_year,
                    b.semester,
                    b.year as academic_year_int,
                    se.total_students
                FROM sections s
                JOIN batches b ON s.batch_id = b.batch_id
                JOIN academic_years ay ON b.academic_year_id = ay.year_id
                LEFT JOIN section_enrollment se ON s.section_id = se.section_id
                JOIN batch_departments bd ON b.batch_id = bd.batch_id
                JOIN departments d ON bd.department_id = d.department_id
                JOIN schools sch ON d.school_id = sch.school_id
                WHERE 1=1
            """
            params = []

            if school_id:
                query += " AND sch.school_id = %s"
                params.append(school_id)
            if dept_id:
                query += " AND d.department_id = %s"
                params.append(dept_id)
            if year_id is not None and year_id != '':
                query += " AND b.academic_year_id = %s"
                params.append(year_id)
            if semester is not None and semester != '':
                query += " AND b.semester = %s"
                params.append(semester)

            query += " ORDER BY sch.name, d.name, ay.start_year DESC, b.semester, s.name"
            cursor.execute(query, params)
            result = cursor.fetchall()
            while cursor.nextset():
                pass
            return result

def get_user_school(user_id):
    """Retrieves the school associated with an academic coordinator user."""
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True, buffered=True) as cursor:
            cursor.execute("""
                SELECT s.* FROM schools s
                JOIN academic_coordinators ac ON s.school_id = ac.school_id
                WHERE ac.user_id = %s AND ac.is_active = 1
            """, (user_id,))
            result = cursor.fetchone()
            while cursor.nextset():
                pass
            return result

def authenticate_coordinator(email, school_id=None):
    """Authenticates an academic coordinator based on email and optional school ID."""
    with get_db_connection() as conn:
        with conn.cursor(dictionary=True, buffered=True) as cursor:
            if school_id:
                cursor.execute("""
                    SELECT u.*, ac.school_id, s.name as school_name, s.abbreviation as school_abbr
                    FROM users u
                    JOIN academic_coordinators ac ON u.user_id = ac.user_id
                    JOIN schools s ON ac.school_id = s.school_id
                    WHERE u.email = %s AND ac.school_id = %s AND ac.is_active = 1
                """, (email, school_id))
            else:
                cursor.execute("""
                    SELECT u.*, ac.school_id, s.name as school_name, s.abbreviation as school_abbr
                    FROM users u
                    JOIN academic_coordinators ac ON u.user_id = ac.user_id
                    JOIN schools s ON ac.school_id = s.school_id
                    WHERE u.email = %s AND ac.is_active = 1
                """, (email,))
            result = cursor.fetchone()
            while cursor.nextset():
                pass
            return result

def get_semester_dates_by_school(school_id):
    """
    Retrieves the start and end dates for the current active semester
    for a given school.
    """
    query = """
        SELECT sc.start_date, sc.end_date, sc.semester_number, sc.academic_year
        FROM semester_config sc
        JOIN semester_info si ON sc.semester_id = si.sem_id
        WHERE si.school_id = %s AND sc.is_active = 1
        ORDER BY sc.start_date DESC
        LIMIT 1
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True, buffered=True)
            cursor.execute(query, (school_id,))
            result = cursor.fetchone()
            while cursor.nextset():
                pass
            return result
    except mysql.connector.Error as e:
        logger.error(f"Database error getting semester dates for school {school_id}: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting semester dates for school {school_id}: {e}", exc_info=True)
        return None

def get_subject_progress_for_department_and_semester(department_id, semester_number, academic_year_name, semester_start_date, semester_end_date):
    """
    Calculates and retrieves subject progress (planned vs. scheduled lectures)
    for all subjects within a given department for a specific semester.
    'Scheduled' sessions are defined as entries in the timetable table within the semester dates.
    """
    query = """
        SELECT
            s.subject_id,
            s.subject_code,
            s.name AS subject_name,
            s.credits AS total_credits_per_week,
            sec.section_id,
            sec.name AS section_name,
            u.name AS faculty_name,
            bs.batch_subject_id,
            COUNT(t.entry_id) AS scheduled_sessions_count
        FROM subjects s
        JOIN batch_subjects bs ON s.subject_id = bs.subject_id
        JOIN batches b ON bs.batch_id = b.batch_id
        JOIN sections sec ON b.batch_id = sec.batch_id
        JOIN batch_departments bd ON b.batch_id = bd.batch_id
        JOIN departments d ON bd.department_id = d.department_id
        JOIN academic_years ay ON b.academic_year_id = ay.year_id
        LEFT JOIN timetable t ON t.batch_subject_id = bs.batch_subject_id
                               AND t.section_id = sec.section_id
                               AND t.date BETWEEN %s AND %s
        LEFT JOIN users u ON t.faculty_id = u.user_id
        WHERE d.department_id = %s
          AND b.semester = %s
          AND ay.year_name = %s
        GROUP BY s.subject_id, s.subject_code, s.name, s.credits, sec.section_id, sec.name, u.name, bs.batch_subject_id
        ORDER BY s.name, sec.name
    """
    params = (semester_start_date, semester_end_date, department_id, semester_number, academic_year_name)

    try:
        raw_data = TimetableGenerator()._execute_query(query, params, dictionary_cursor=True)
        total_semester_weeks = (semester_end_date - semester_start_date).days // 7 + 1

        subject_progress_summary = defaultdict(lambda: {
            'subject_id': None,
            'subject_code': None,
            'subject_name': None,
            'total_credits': 0,
            'planned_sessions_total': 0,
            'conducted_sessions_total': 0,
            'completion_percentage': 0.0,
            'sections': defaultdict(lambda: {
                'section_id': None,
                'section_name': None,
                'faculty_name': 'N/A',
                'planned_sessions': 0,
                'conducted_sessions': 0,
                'completion_percentage': 0.0
            })
        })

        for row in raw_data:
            subject_id = row['subject_id']
            section_id = row['section_id']

            subject_progress_summary[subject_id]['subject_id'] = subject_id
            subject_progress_summary[subject_id]['subject_code'] = row['subject_code']
            subject_progress_summary[subject_id]['subject_name'] = row['subject_name']
            subject_progress_summary[subject_id]['total_credits'] = row['total_credits_per_week']

            planned_sessions_for_section_subject = row['total_credits_per_week'] * total_semester_weeks

            section_data = subject_progress_summary[subject_id]['sections'][section_id]
            section_data['section_id'] = section_id
            section_data['section_name'] = row['section_name']
            if row['faculty_name']:
                section_data['faculty_name'] = row['faculty_name']
            section_data['planned_sessions'] = planned_sessions_for_section_subject
            section_data['conducted_sessions'] = row['scheduled_sessions_count']

        final_progress_list = []
        for subject_id, subject_data in subject_progress_summary.items():
            total_planned_sessions_for_subject_agg = 0
            total_conducted_sessions_for_subject_agg = 0

            sections_list = []
            for sec_id, sec_data in subject_data['sections'].items():
                sec_data['completion_percentage'] = (sec_data['conducted_sessions'] / sec_data['planned_sessions'] * 100) if sec_data['planned_sessions'] > 0 else 0
                sections_list.append(sec_data)
                total_planned_sessions_for_subject_agg += sec_data['planned_sessions']
                total_conducted_sessions_for_subject_agg += sec_data['conducted_sessions']

            subject_data['planned_sessions_total'] = total_planned_sessions_for_subject_agg
            subject_data['conducted_sessions_total'] = total_conducted_sessions_for_subject_agg
            subject_data['completion_percentage'] = (total_conducted_sessions_for_subject_agg / total_planned_sessions_for_subject_agg * 100) if total_planned_sessions_for_subject_agg > 0 else 0
            subject_data['sections'] = sorted(sections_list, key=lambda x: x['section_name'])

            final_progress_list.append(subject_data)

        return sorted(final_progress_list, key=lambda x: x['subject_name'])

    except mysql.connector.Error as e:
        logger.error(f"Database error getting subject progress for department {department_id}: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting subject progress for department {department_id}: {e}", exc_info=True)
        return []
