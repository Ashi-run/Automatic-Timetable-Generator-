import random
import json
import re
import numpy as np
from datetime import datetime, timedelta, date, time
from collections import defaultdict
from db_config import get_connection
import logging
import mysql.connector
from contextlib import contextmanager
import io
from itertools import groupby

# Configure logging: INFO level for general messages, WARNING for issues, ERROR for critical errors.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(_name_)

# This is the same context manager as in the original code.
@contextmanager
def get_db_connection():
    """
    Context manager to get a new MySQL connection and ensure it's closed.
    This is used for all database operations to ensure isolated transactions
    and prevent 'Unread result found' errors.
    """
    conn = None
    try:
        conn = get_connection()
        # Ensure autocommit is off for proper transaction handling
        conn.autocommit = False
        yield conn
    except mysql.connector.Error as e:
        logger.error(f"Database connection error: {e}", exc_info=True)
        if conn and conn.is_connected():
            try:
                conn.rollback()
            except Exception as rb_exc:
                logger.error(f"Error during rollback: {rb_exc}")
        raise
    finally:
        if conn and conn.is_connected():
            try:
                # Consume any unread results before closing
                if hasattr(conn, 'get_warnings') and callable(conn.get_warnings):
                    conn.get_warnings()
                conn.close()
                logger.info("Database connection closed by context manager.")
            except Exception as e:
                logger.warning(f"Error closing connection: {e}")

class TimetableGenerator:
    """
    Generates and manages timetables based on various constraints using a Hybrid NSGA-II.
    """
    def _init_(self):
        logger.info("TimetableGenerator initialized. Database connection handled per operation.")
        self.problem_data = {}
        self.population_size = 100
        self.num_generations = 100  # Increased for better optimization
        self.crossover_probability = 0.9
        self.mutation_probability = 0.2 # Increased for more exploration
        self.num_objectives = 2

        # --- Penalty weights for optimization ---
        self.PENALTY_HARD = 1000  # For unbreakable rules (e.g., double booking)
        self.PENALTY_MEDIUM = 50    # For important rules (e.g., room capacity)
        self.PENALTY_SOFT = 1       # For preferences (e.g., minimizing student gaps)


    def _del_(self):
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
        This function adds new entries and does not delete previous timetables.
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
        and updates the lecture_trackers table.
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
            
            # This block runs for faculty with NO entry in the database.
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
            
            # This block fills in missing values for faculty who HAVE an entry in the database.
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
            WHERE 1=1
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
                'is_lab_session': row['is_lab_session'],
                'subsection_id': row.get('subsection_id'),
                'week_number': row['week_number'],
                'is_rescheduled': row['is_rescheduled'],
                'academic_year_int': row['academic_year_int'],
                'semester_int': row['semester_int'],
                'start_time': start_time_obj.strftime('%H:%M:%S'),
                'end_time': end_time_obj.strftime('%H:%M:%S')
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
            if formatted[day]: # Check if the list for the day is not empty
                formatted[day].sort(key=lambda x: datetime.strptime(x['start_time'], '%H:%M:%S').time())
        return formatted

    def format_timetable_grid(self, timetable, timeslots):
        """
        Transforms the timetable data into a grid format suitable for display,
        merging consecutive lab sessions with a rowspan attribute.
        """
        unique_timeslots = {}
        for slot in timeslots:
            start = (datetime.min + slot['start_time']).time().strftime('%H:%M')
            end = (datetime.min + slot['end_time']).time().strftime('%H:%M')
            unique_timeslots[(start, end)] = f"{start}-{end}"
        timeslot_labels = [f"{start}-{end}" for start, end in sorted(unique_timeslots.keys())]
        days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        grid = {day: {slot: None for slot in timeslot_labels} for day in days_order}
        merged_cells = set()
        timetable.sort(key=lambda x: (x['day_of_week'], datetime.strptime(x['start_time'], '%H:%M:%S').time()))

        for i, session in enumerate(timetable):
            day = session['day_of_week']
            start_time_str = datetime.strptime(session['start_time'], '%H:%M:%S').time().strftime('%H:%M')
            end_time_str = datetime.strptime(session['end_time'], '%H:%M:%S').time().strftime('%H:%M')
            time_key = f"{start_time_str}-{end_time_str}"

            if (day, time_key) in merged_cells:
                continue

            is_lab = session.get('is_lab_session', False)
            rowspan = 1
            if is_lab and session.get('subject_name', 'N/A') != 'Remedial Mathematics':
                next_session = None
                if i + 1 < len(timetable):
                    next_session = timetable[i+1]

                if next_session and \
                        next_session['day_of_week'] == day and \
                        next_session['subject_name'] == session['subject_name'] and \
                        next_session['faculty_name'] == session['faculty_name'] and \
                        datetime.strptime(next_session['start_time'], '%H:%M:%S').time() == datetime.strptime(session['end_time'], '%H:%M:%S').time():
                    rowspan = 2
                    next_start_time = datetime.strptime(session['end_time'], '%H:%M:%S').time().strftime('%H:%M')
                    next_end_time = datetime.strptime(next_session['end_time'], '%H:%M:%S').time().strftime('%H:%M')
                    merged_cells.add((day, f"{next_start_time}-{next_end_time}"))

            if day in grid and time_key in grid[day]:
                grid[day][time_key] = {
                    'subject': session['subject_name'],
                    'faculty': session.get('faculty_name', 'Unassigned'),
                    'room': session.get('room_number', 'N/A'),
                    'is_lab': is_lab,
                    'rowspan': rowspan
                }
        return grid, timeslot_labels

    def generate_timetable_for_section(self, section_id, start_date=None, semester_weeks=1):
        """
        Main function to generate a timetable for a given section using NSGA-II.
        """
        full_generation_start = datetime.now()
        logger.info(f"Starting NSGA-II based timetable generation for section {section_id}")
        
        try:
            self._capture_completed_sessions(section_id)
            self.delete_existing_timetable(section_id)

            # 1. Fetch all necessary data for the optimization problem
            data = self._fetch_problem_data(section_id)
            if "error" in data:
                return data

            # 2. Define the problem representation for NSGA-II
            self.problem_data = self._prepare_problem_data(data)
            if "error" in self.problem_data:
                return self.problem_data
            
            # 3. NSGA-II Main Loop
            population = self._initialize_population()
            
            for generation in range(self.num_generations):
                logger.info(f"NSGA-II Generation: {generation+1}/{self.num_generations}")
                
                # Evaluate the population
                self._evaluate_population(population)
                
                # Non-dominated sorting
                fronts = self._non_dominated_sort(population)
                
                # Crossover and Mutation
                offspring = self._create_offspring(population, fronts)
                
                # Combine parent and offspring populations
                combined_population = population + offspring
                
                # Select the next generation
                population = self._select_next_generation(combined_population)

            # 4. Select the best solution from the final Pareto front
            self._evaluate_population(population)
            final_fronts = self._non_dominated_sort(population)
            best_individual = self._select_best_solution(final_fronts)

            if best_individual is None:
                return {"error": "NSGA-II failed to find any feasible solution."}
            
            # 5. Decode the best individual into a usable timetable format
            final_timetable_raw, generation_log = self._decode_solution(best_individual, self.problem_data)
            
            # FIX: Translate violation messages before saving and returning
            generation_log['constraints_violated'] = self._translate_violation_messages(
                generation_log.get('constraints_violated', []),
                self.problem_data['all_timeslots']
            )

            if not final_timetable_raw:
                generation_log['generation_status'] = 'Partial' # No Failed status
                generation_log['constraints_violated'].append("Decoded solution produced no valid timetable sessions.")
                
                log_id = self.save_generation_log(section_id, generation_log)
                return {"error": "Timetable generation failed: Decoded solution produced no valid sessions.", "log_id": log_id, "generation_log": generation_log}
                
            # 6. Save the results
            generation_log['total_slots_assigned'] = len(best_individual['chromosome'])
            generation_log['total_slots_required'] = self.problem_data.get('total_assignments_to_schedule', 0)
            
            # FIX: Implement user's new rule for "Failed" status. Only "Success" or "Partial".
            final_penalty = best_individual['objectives'][0]
            if final_penalty == 0:
                generation_log['generation_status'] = 'Success'
            else:
                generation_log['generation_status'] = 'Partial'

            log_id = self.save_generation_log(section_id, generation_log)
            if not log_id:
                return {"error": "Failed to save generation log."}
            
            save_success = self.save_timetable_to_db(log_id, {'raw_timetable': final_timetable_raw})
            if not save_success:
                generation_log['generation_status'] = 'Partial' # No Failed status
                generation_log['constraints_violated'].append("Failed to save timetable entries to database.")
                update_query = "UPDATE timetable_generation_log SET status = %s, constraints_violated = %s WHERE log_id = %s"
                self._execute_dml(update_query, ('Partial', json.dumps(generation_log['constraints_violated']), log_id))
                return {"error": "Failed to save generated timetable to database."}

            # 7. Format for display and return
            all_timeslots_data = self._execute_query("SELECT * FROM timeslots WHERE is_active = 1 ORDER BY timeslot_id")
            grid, timeslot_labels = self.format_timetable_grid(final_timetable_raw, all_timeslots_data)

            full_generation_time = datetime.now() - full_generation_start
            generation_log['generation_time_seconds'] = full_generation_time.total_seconds()
            update_query = "UPDATE timetable_generation_log SET generation_time_seconds = %s WHERE log_id = %s"
            self._execute_dml(update_query, (full_generation_time.total_seconds(), log_id))

            return {
                'status': generation_log['generation_status'],
                'section_id': section_id,
                'section_name': data['section_info']['name'],
                'batch_id': data['section_info']['batch_id'],
                'department': data['section_info']['department_name'],
                'generation_log': generation_log,
                'raw_timetable': final_timetable_raw,
                'grid': grid,
                'timeslot_labels': timeslot_labels,
                'generation_seconds': full_generation_time.total_seconds(),
                'generated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'start_date': start_date,
                'end_date': start_date + timedelta(days=6) if start_date else None,
                'log_id': log_id
            }

        except Exception as e:
            logger.error(f"Unexpected error in main NSGA-II generation: {str(e)}", exc_info=True)
            return {"error": f"Unexpected error: {str(e)}"}

    def _fetch_problem_data(self, section_id):
        """Fetches all data required for the optimization problem."""
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
                u.name as faculty_name, s.subject_code, s.has_lab as is_lab_session, s.lab_duration_hours,
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

        # Fetch all faculty members assigned to this section
        all_assigned_faculty_ids = {fa['faculty_id'] for fa in faculty_assignments}
        
        # Fetch constraints for all assigned faculty and fill in defaults for any missing
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
            'faculty_constraints': self.faculty_constraints,
            'faculty_unavailability': self.faculty_unavailability,
        }

    def _prepare_problem_data(self, data):
        """Converts raw database data into a structured format for the algorithm."""
        assignments = []
        
        lab_rooms = [room for room in data['all_rooms'] if room['room_type'] == 'Lab']
        max_lab_capacity = max(r['capacity'] for r in lab_rooms) if lab_rooms else 0
        
        key_func = lambda x: x['batch_subject_id']
        sorted_faculty_assignments = sorted(data['faculty_assignments'], key=key_func)
        
        for batch_subject_id, group in groupby(sorted_faculty_assignments, key=key_func):
            assignments_for_subject = list(group)
            first_assignment = assignments_for_subject[0]
            faculty_pool = [fa['faculty_id'] for fa in assignments_for_subject]

            total_students = data['section_info'].get('total_students', 0) or 0
            max_subsection_size = data['section_info'].get('max_subsection_size') or total_students

            theory_sessions_per_week = first_assignment.get('theory_sessions_per_week') or 0
            lab_sessions_per_week = first_assignment.get('lab_sessions_per_week') or 0
            
            lab_duration_value = first_assignment.get('lab_duration_hours')
            lab_duration_hours = float(lab_duration_value) if lab_duration_value is not None else 1.0

            preferred_lab_room = first_assignment.get('preferred_lab_room_id')
            preferred_theory_room = data['section_info'].get('theory_room_id')
            is_continuous = first_assignment.get('is_lab_continuous', True)

            needs_subsection = False
            if lab_sessions_per_week > 0 and total_students > 0:
                if max_subsection_size > 0 and total_students > max_subsection_size:
                    needs_subsection = True
                elif max_lab_capacity > 0 and total_students > max_lab_capacity:
                    needs_subsection = True
                    logger.info(f"Forcing subsection split for subject {first_assignment['subject_code']} because total students ({total_students}) exceeds max lab capacity ({max_lab_capacity}).")

            # Create Theory Sessions
            for _ in range(theory_sessions_per_week):
                assignments.append({
                    'assignment_id': first_assignment['faculty_subject_id'], 'faculty_id': random.choice(faculty_pool),
                    'batch_subject_id': batch_subject_id, 'is_lab': False,
                    'duration': 1, 'subsection_id': 'full',
                    'preferred_room_id': preferred_theory_room, 'is_lab_continuous': False
                })

            # Create Lab Sessions
            if needs_subsection:
                num_subsections = (total_students + max_subsection_size - 1) // max_subsection_size if max_subsection_size > 0 else 1
                for i in range(num_subsections):
                    for _ in range(lab_sessions_per_week):
                        assignments.append({
                            'assignment_id': first_assignment['faculty_subject_id'], 'faculty_id': random.choice(faculty_pool),
                            'batch_subject_id': batch_subject_id, 'is_lab': True,
                            'duration': lab_duration_hours, 'subsection_id': i + 1,
                            'preferred_room_id': preferred_lab_room, 'is_lab_continuous': is_continuous
                        })
            else: 
                for _ in range(lab_sessions_per_week):
                     assignments.append({
                        'assignment_id': first_assignment['faculty_subject_id'], 'faculty_id': random.choice(faculty_pool),
                        'batch_subject_id': batch_subject_id, 'is_lab': True,
                        'duration': lab_duration_hours, 'subsection_id': 'full',
                        'preferred_room_id': preferred_lab_room, 'is_lab_continuous': is_continuous
                    })
        
        if not assignments:
             return {"error": "No sessions could be generated from faculty assignments. Check subject session counts in the database."}

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
            'faculty_unavailability': self.faculty_unavailability,
            'day_map_rev': day_map_rev,
            'faculty_assignments': data['faculty_assignments'] 
        }

    def _select_room(self, assignment):
        """
        FIXED: Selects a room for an assignment, prioritizing preferred, then checking type and capacity.
        """
        students_in_session = self.problem_data['section_info'].get('max_subsection_size', 0) if isinstance(assignment['subsection_id'], int) else self.problem_data['section_info'].get('total_students', 0)
        is_lab = assignment['is_lab']
        room_type_needed = 'Lab' if is_lab else 'Lecture'

        # 1. Prioritize the preferred room if it meets type and capacity
        preferred_room_id = assignment.get('preferred_room_id')
        if preferred_room_id and preferred_room_id in self.problem_data['all_rooms']:
            preferred_room = self.problem_data['all_rooms'][preferred_room_id]
            if preferred_room['capacity'] >= students_in_session and preferred_room['room_type'] == room_type_needed:
                return preferred_room_id

        # 2. Fallback: Find any suitable room that meets type and capacity
        suitable_rooms = [
            room['room_id'] for room in self.problem_data['all_rooms_list']
            if room['room_type'] == room_type_needed and room['capacity'] >= students_in_session
        ]
        if suitable_rooms:
            return random.choice(suitable_rooms)

        # 3. Last resort: No room with sufficient capacity was found. This will be penalized.
        logger.warning(f"No suitable room with capacity >= {students_in_session} found for assignment. This will incur a penalty.")
        any_room_of_type = [
            room['room_id'] for room in self.problem_data['all_rooms_list']
            if room['room_type'] == room_type_needed
        ]
        if any_room_of_type:
            return random.choice(any_room_of_type)
        
        # 4. Absolute last resort if even the type isn't found.
        return random.choice(self.problem_data['all_rooms_list'])['room_id']

    def _initialize_population(self):
        """
        Initializes the population using a hybrid approach.
        Greedy initialization for some individuals and random for others.
        """
        population = []
        for i in range(self.population_size):
            individual = self._create_random_individual() if i % 2 == 0 else self._create_greedy_individual()
            population.append(individual)
        return population
    
    def _create_random_individual(self):
        """Creates a single individual with random assignments, respecting preferred rooms."""
        chromosome = []
        assignments_copy = list(self.problem_data['assignments'])
        random.shuffle(assignments_copy)
        
        for assignment in assignments_copy:
            random_slot = random.choice(self.problem_data['possible_slots'])
            
            chromosome.append({
                'assignment_idx': self.problem_data['assignments'].index(assignment),
                'day_index': random_slot[0],
                'timeslot_id': random_slot[1],
                'room_id': self._select_room(assignment)
            })
        return {'chromosome': chromosome}
    
    def _create_greedy_individual(self):
        """
        FIXED: Creates a single individual with a smarter greedy heuristic that prioritizes labs.
        """
        chromosome = []
        
        # FIX: Prioritize labs by separating assignments
        all_assignments = list(self.problem_data['assignments'])
        lab_assignments = [a for a in all_assignments if a['is_lab']]
        theory_assignments = [a for a in all_assignments if not a['is_lab']]
        random.shuffle(lab_assignments)
        random.shuffle(theory_assignments)
        assignments_to_schedule = lab_assignments + theory_assignments

        used_slots_section = defaultdict(list)
        used_slots_room = defaultdict(set)
        used_slots_faculty = defaultdict(set)

        for assignment in assignments_to_schedule:
            best_slot_block = None
            best_room_id = None
            
            required_duration = int(assignment.get('duration', 1))
            
            possible_start_slots = list(self.problem_data['possible_slots'])
            random.shuffle(possible_start_slots)
            
            for day_index, start_timeslot_id in possible_start_slots:
                # 1. Determine the full block of timeslots required
                slot_block = []
                if required_duration > 1:
                    day_of_week = self.problem_data['day_map_rev'][day_index]
                    current_timeslot_info = self.problem_data['all_timeslots'].get(start_timeslot_id)
                    if not current_timeslot_info: continue

                    slot_block.append((day_index, start_timeslot_id))
                    current_time_obj = (datetime.min + current_timeslot_info['end_time']).time()

                    for _ in range(required_duration - 1):
                        next_slot_info = next((ts for ts in self.problem_data['all_timeslots'].values() if ts['day_of_week'] == day_of_week and (datetime.min + ts['start_time']).time() == current_time_obj), None)
                        if next_slot_info:
                            slot_block.append((day_index, next_slot_info['timeslot_id']))
                            current_time_obj = (datetime.min + next_slot_info['end_time']).time()
                        else:
                            slot_block = []
                            break
                    
                    if len(slot_block) < required_duration:
                        continue
                else:
                    slot_block = [(day_index, start_timeslot_id)]

                # 2. Check for time conflicts across the block
                block_is_free = True
                current_subsection = assignment['subsection_id']
                faculty_id = assignment['faculty_id']

                for d_idx, ts_id in slot_block:
                    slot_key = (d_idx, ts_id)
                    subsections_in_slot = used_slots_section.get(slot_key, [])
                    if ('full' in subsections_in_slot or current_subsection == 'full') and subsections_in_slot:
                        block_is_free = False
                    elif current_subsection != 'full' and current_subsection in subsections_in_slot:
                        block_is_free = False
                    if slot_key in used_slots_faculty.get(faculty_id, set()):
                        block_is_free = False
                    if not block_is_free:
                        break
                
                if not block_is_free:
                    continue
                
                # 3. If time is free, find a suitable room (with capacity check)
                students_in_session = self.problem_data['section_info'].get('max_subsection_size', 0) if isinstance(current_subsection, int) else self.problem_data['section_info'].get('total_students', 0)
                is_lab_required = assignment['is_lab']
                room_type_needed = 'Lab' if is_lab_required else 'Lecture'

                available_rooms = [r for r in self.problem_data['all_rooms_list'] if r['room_type'] == room_type_needed and r['capacity'] >= students_in_session]
                random.shuffle(available_rooms)
                
                found_room_id = None
                for room in available_rooms:
                    is_room_free_for_block = all((d_idx, ts_id) not in used_slots_room.get(room['room_id'], set()) for d_idx, ts_id in slot_block)
                    if is_room_free_for_block:
                        found_room_id = room['room_id']
                        break
                
                if found_room_id:
                    best_slot_block = slot_block
                    best_room_id = found_room_id
                    break 
            
            # Fallback logic: If no conflict-free spot was found
            if not best_slot_block or not best_room_id:
                # IMPORTANT: Find a starting slot where a block of the required duration can at least be physically constructed
                constructible_start_slots = []
                for d_idx, s_id in self.problem_data['possible_slots']:
                    day_of_week = self.problem_data['day_map_rev'][d_idx]
                    start_slot_info = self.problem_data['all_timeslots'].get(s_id)
                    if not start_slot_info: continue

                    num_found = 1
                    current_time_obj = (datetime.min + start_slot_info['end_time']).time()
                    for _ in range(required_duration - 1):
                        next_slot = next((ts for ts in self.problem_data['all_timeslots'].values() if ts['day_of_week'] == day_of_week and (datetime.min + ts['start_time']).time() == current_time_obj), None)
                        if next_slot:
                            num_found += 1
                            current_time_obj = (datetime.min + next_slot['end_time']).time()
                        else: break
                    if num_found == required_duration:
                        constructible_start_slots.append((d_idx, s_id))
                
                if constructible_start_slots:
                    start_day, start_id = random.choice(constructible_start_slots)
                    day_of_week = self.problem_data['day_map_rev'][start_day]
                    current_timeslot_info = self.problem_data['all_timeslots'][start_id]
                    best_slot_block = [(start_day, start_id)]
                    current_time_obj = (datetime.min + current_timeslot_info['end_time']).time()
                    for _ in range(required_duration - 1):
                        next_slot_info = next((ts for ts in self.problem_data['all_timeslots'].values() if ts['day_of_week'] == day_of_week and (datetime.min + ts['start_time']).time() == current_time_obj), None)
                        best_slot_block.append((start_day, next_slot_info['timeslot_id']))
                        current_time_obj = (datetime.min + next_slot_info['end_time']).time()
                else:
                    logger.error(f"Could not find any physically constructible block of {required_duration} hours. Placing as 1-hour.")
                    start_slot = random.choice(self.problem_data['possible_slots'])
                    best_slot_block = [start_slot]

                best_room_id = self._select_room(assignment)

            chromosome.append({
                'assignment_idx': self.problem_data['assignments'].index(assignment),
                'day_index': best_slot_block[0][0],
                'timeslot_id': best_slot_block[0][1],
                'room_id': best_room_id
            })
            
            for d_idx, ts_id in best_slot_block:
                slot_key = (d_idx, ts_id)
                used_slots_section[slot_key].append(assignment['subsection_id'])
                used_slots_faculty[assignment['faculty_id']].add(slot_key)
                used_slots_room[best_room_id].add(slot_key)
        
        return {'chromosome': chromosome}

    def _evaluate_individual(self, individual):
        """
        Evaluates an individual by calculating its two objective values.
        Objective 1: A weighted penalty score for all constraint violations (to be minimized).
        Objective 2: Faculty Workload Variance (to be minimized).
        """
        chromosome = individual['chromosome']
        total_penalty = 0
        violations_log = []

        occupied_section_slots = defaultdict(list)
        occupied_faculty_slots = defaultdict(list)
        occupied_room_slots = defaultdict(list)
        faculty_daily_hours = defaultdict(lambda: defaultdict(int))
        section_daily_slots = defaultdict(list)

        all_gene_slots = []
        # First, determine the full block of timeslots for each gene, checking for continuity
        for gene in chromosome:
            assignment = self.problem_data['assignments'][gene['assignment_idx']]
            timeslot = self.problem_data['all_timeslots'][gene['timeslot_id']]
            day_index = gene['day_index']
            day_of_week = self.problem_data['day_map_rev'][day_index]
            
            slots_for_this_gene = [(day_index, gene['timeslot_id'])]
            required_duration = int(assignment['duration'])

            if required_duration > 1:
                current_time_obj = (datetime.min + timeslot['end_time']).time()
                for _ in range(required_duration - 1):
                    next_slot_info = next((ts for ts in self.problem_data['all_timeslots'].values() if ts['day_of_week'] == day_of_week and (datetime.min + ts['start_time']).time() == current_time_obj), None)
                    if next_slot_info:
                        slots_for_this_gene.append((day_index, next_slot_info['timeslot_id']))
                        current_time_obj = (datetime.min + next_slot_info['end_time']).time()
                    else:
                        break # Failed to find a continuous slot
                
                if len(slots_for_this_gene) < required_duration:
                    total_penalty += self.PENALTY_HARD
                    # FIX: Use subject name instead of ID in error message
                    fs_id = assignment['assignment_id']
                    subject_name = 'Unknown Subject'
                    if fs_id in self.problem_data['faculty_assignments_raw']:
                        subject_name = self.problem_data['faculty_assignments_raw'][fs_id]['subject_name']
                    violations_log.append(f"Lab continuity broken for '{subject_name}'. Required {required_duration} hours.")
            
            all_gene_slots.append(slots_for_this_gene)
        
        # Now, check for conflicts using the full blocks of time
        for i, gene in enumerate(chromosome):
            assignment = self.problem_data['assignments'][gene['assignment_idx']]
            slots_for_gene = all_gene_slots[i]

            for day_idx, ts_id in slots_for_gene:
                slot_key = (day_idx, ts_id)
                occupied_section_slots[slot_key].append(assignment['subsection_id'])
                occupied_faculty_slots[slot_key].append(assignment['faculty_id'])
                occupied_room_slots[slot_key].append(gene['room_id'])
                faculty_daily_hours[assignment['faculty_id']][day_idx] += 1
                section_daily_slots[day_idx].append(self.problem_data['all_timeslots'][ts_id]['start_time'])

        # --- Evaluate HARD and MEDIUM constraints ---
        for slot, subsections in occupied_section_slots.items():
            if len(subsections) > 1 and 'full' in subsections:
                total_penalty += self.PENALTY_HARD
                violations_log.append(f"Section conflict at slot {slot}: full class scheduled with a subsection.")
            
            counts = defaultdict(int)
            for sub in subsections:
                if sub != 'full':
                    counts[sub] += 1
            for sub, count in counts.items():
                if count > 1:
                    total_penalty += self.PENALTY_HARD
                    violations_log.append(f"Section conflict at slot {slot}: same subsection ({sub}) scheduled twice.")

        for slot, faculties in occupied_faculty_slots.items():
            if len(set(faculties)) != len(faculties):
                total_penalty += self.PENALTY_HARD * (len(faculties) - len(set(faculties)))
                violations_log.append(f"Faculty double-booked at slot {slot}.")
        
        for slot, rooms in occupied_room_slots.items():
            if len(set(rooms)) != len(rooms):
                total_penalty += self.PENALTY_HARD * (len(rooms) - len(set(rooms)))
                violations_log.append(f"Room double-booked at slot {slot}.")

        for gene in chromosome:
            assignment = self.problem_data['assignments'][gene['assignment_idx']]
            room = self.problem_data['all_rooms'][gene['room_id']]
            
            if assignment['is_lab'] and room['room_type'] != 'Lab':
                total_penalty += self.PENALTY_MEDIUM
                violations_log.append("Room type mismatch: Lab session in a Lecture room.")
            if not assignment['is_lab'] and room['room_type'] == 'Lab':
                 total_penalty += self.PENALTY_SOFT 
            
            students_in_session = self.problem_data['section_info'].get('max_subsection_size', 0) if isinstance(assignment['subsection_id'], int) else self.problem_data['section_info'].get('total_students', 0)
            if room['capacity'] < students_in_session:
                 total_penalty += self.PENALTY_MEDIUM
                 violations_log.append(f"Room capacity too small: {room['room_number']} ({room['capacity']}) for {students_in_session} students.")
        
        faculty_weekly_hours = defaultdict(float)
        for gene in chromosome:
             assignment = self.problem_data['assignments'][gene['assignment_idx']]
             faculty_weekly_hours[assignment['faculty_id']] += assignment['duration']

        for faculty_id, hours in faculty_weekly_hours.items():
            constraints = self.problem_data['faculty_constraints'].get(faculty_id, {})
            max_weekly = constraints.get('max_weekly_hours', 20)
            max_daily = constraints.get('max_hours_per_day', 8)
            
            if hours > max_weekly:
                total_penalty += self.PENALTY_MEDIUM
                violations_log.append(f"Faculty {faculty_id} over weekly limit.")

            for day_hours in faculty_daily_hours[faculty_id].values():
                if day_hours > max_daily:
                    total_penalty += self.PENALTY_MEDIUM
                    violations_log.append(f"Faculty {faculty_id} over daily limit.")
        
        # --- Evaluate SOFT constraints (Student Gaps) ---
        for day, slots in section_daily_slots.items():
            if len(slots) > 1:
                unique_slots = sorted(list(set(slots)))
                first_hour = unique_slots[0].seconds // 3600
                last_hour = unique_slots[-1].seconds // 3600
                total_span = last_hour - first_hour
                gaps = total_span - (len(unique_slots) - 1)
                if gaps > 0:
                    total_penalty += gaps * self.PENALTY_SOFT
        
        workloads = [h for h in faculty_weekly_hours.values()]
        workload_variance = np.var(workloads) if len(workloads) > 1 else 0
        
        individual['objectives'] = [total_penalty, workload_variance]
        individual['violations'] = violations_log
        
    def _evaluate_population(self, population):
        """Evaluates all individuals in the population."""
        for individual in population:
            self._evaluate_individual(individual)
            
    def _non_dominated_sort(self, population):
        """Performs non-dominated sorting on the population."""
        fronts = []
        for p1 in population:
            p1['dominates'] = set()
            p1['dominated_by_count'] = 0
            for p2 in population:
                if id(p1) == id(p2):
                    continue
                if self._dominates(p1, p2):
                    p1['dominates'].add(id(p2))
                elif self._dominates(p2, p1):
                    p1['dominated_by_count'] += 1
            
            if p1['dominated_by_count'] == 0:
                p1['rank'] = 0
                if not fronts:
                    fronts.append([])
                fronts[0].append(p1)
        
        i = 0
        while True:
            next_front = []
            if i >= len(fronts):
                break
            
            for p in fronts[i]:
                for q_id in p['dominates']:
                    q = next(ind for ind in population if id(ind) == q_id)
                    q['dominated_by_count'] -= 1
                    if q['dominated_by_count'] == 0:
                        q['rank'] = i + 1
                        next_front.append(q)
            
            if next_front:
                fronts.append(next_front)
            else:
                break
            i += 1
        return fronts
        
    def _dominates(self, p1, p2):
        """Checks if individual p1 dominates individual p2."""
        is_equal = True
        for i in range(self.num_objectives):
            if p1['objectives'][i] > p2['objectives'][i]:
                return False
            if p1['objectives'][i] < p2['objectives'][i]:
                is_equal = False
        return not is_equal
        
    def _calculate_crowding_distance(self, front):
        """Calculates crowding distance for all individuals in a given front."""
        if not front:
            return
        
        for i in range(self.num_objectives):
            front.sort(key=lambda x: x['objectives'][i])
            
            obj_min = front[0]['objectives'][i]
            obj_max = front[-1]['objectives'][i]
            
            if obj_max == obj_min:
                for ind in front:
                    ind['crowding_distance'] = float('inf')
                continue
            
            front[0]['crowding_distance'] = float('inf')
            front[-1]['crowding_distance'] = float('inf')
            
            for j in range(1, len(front) - 1):
                dist = front[j+1]['objectives'][i] - front[j-1]['objectives'][i]
                front[j]['crowding_distance'] = front[j].get('crowding_distance', 0) + dist / (obj_max - obj_min)

    def _create_offspring(self, population, fronts):
        """Creates offspring using binary tournament selection, crossover, and mutation."""
        offspring = []
        for front in fronts:
            self._calculate_crowding_distance(front)
        
        while len(offspring) < self.population_size:
            parent1 = self._binary_tournament_selection(population, fronts)
            parent2 = self._binary_tournament_selection(population, fronts)
            
            if random.random() < self.crossover_probability:
                child1_chromosome, child2_chromosome = self._crossover(parent1['chromosome'], parent2['chromosome'])
            else:
                child1_chromosome, child2_chromosome = parent1['chromosome'][:], parent2['chromosome'][:]
            
            child1_chromosome = self._mutate(child1_chromosome)
            child2_chromosome = self._mutate(child2_chromosome)
            
            offspring.append({'chromosome': child1_chromosome})
            if len(offspring) < self.population_size:
                offspring.append({'chromosome': child2_chromosome})
            
        return offspring

    def _binary_tournament_selection(self, population, fronts):
        """Selects a parent using binary tournament based on rank and crowding distance."""
        p1 = random.choice(population)
        p2 = random.choice(population)
        
        if p1['rank'] < p2['rank']:
            return p1
        elif p2['rank'] < p1['rank']:
            return p2
        else:
            return p1 if p1.get('crowding_distance', 0) >= p2.get('crowding_distance', 0) else p2
            
    def _crossover(self, parent1_c, parent2_c):
        """Performs a single-point crossover on the chromosomes."""
        if len(parent1_c) != len(parent2_c) or len(parent1_c) < 2:
            return parent1_c, parent2_c

        crossover_point = random.randint(1, len(parent1_c) - 1)
        
        child1_c = parent1_c[:crossover_point] + parent2_c[crossover_point:]
        child2_c = parent2_c[:crossover_point] + parent1_c[crossover_point:]
        
        return child1_c, child2_c
        
    def _mutate(self, chromosome):
        """Performs a smarter swap mutation on the chromosome."""
        if len(chromosome) < 2:
            return chromosome
            
        for _ in range(len(chromosome)): # Number of mutation attempts
            if random.random() < self.mutation_probability:
                idx1, idx2 = random.sample(range(len(chromosome)), 2)
                
                # Swap timeslot and day information
                chromosome[idx1]['day_index'], chromosome[idx2]['day_index'] = \
                    chromosome[idx2]['day_index'], chromosome[idx1]['day_index']
                chromosome[idx1]['timeslot_id'], chromosome[idx2]['timeslot_id'] = \
                    chromosome[idx2]['timeslot_id'], chromosome[idx1]['timeslot_id']
                
        return chromosome

    def _select_next_gene