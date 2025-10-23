# UNISYNC: Automatic Timetable Generator

## 1\. Overview

**UNISYNC** is a robust, web-based system designed to automatically generate conflict-free and optimized academic timetables for educational institutions.

This project addresses the challenges of manual scheduling by implementing a smart algorithm that handles complex constraints—such as faculty availability, subject priorities, and classroom capacity—to produce accurate, ready-to-use schedules quickly and efficiently.

-----

## 2\. Features

The core capabilities of the UNISYNC system include:

  * **Automatic Generation:** Generates a full semester/year timetable automatically by processing input data (faculty, subjects, rooms, and constraints).
  * **Conflict-Free Logic:** Employs an advanced scheduling algorithm (`advanced_timetable_logic.py`) to ensure zero conflicts for faculty, classrooms, and batches.
  * **Role-Based Access:** Dedicated interfaces and database configurations for different user roles (implied by `hod_db.py`).
  * **Data Management:** Functions to easily add, edit, and delete records for **Faculty**, **Subjects**, **Classes**, and **Rooms**.
  * **SQL Persistence:** Stores all data securely and reliably using a dedicated SQL database.
  * **Web Interface:** A user-friendly, browser-accessible interface for data input and viewing the final generated timetable.

-----

## 3\. Technology Stack

This project is built using a classic, robust, and scalable stack:

| Category | Technology | Purpose |
| :--- | :--- | :--- |
| **Backend** | **Python** (via `app.py`) | Core application logic and algorithmic processing. |
| **Web Framework** | **Flask** (Inferred) | Routing, handling HTTP requests, and connecting the backend logic to the templates. |
| **Frontend** | **HTML / CSS** | Structure (via files in `templates/`) and basic styling (via files in `static/`). |
| **Database** | **SQL (e.g., MySQL, PostgreSQL)** | Data storage for constraints, faculty, and the final timetable (implied by `reclassify_tables.sql` and `db_config.py`). |
| **Logic** | **Custom Timetabling Algorithm** | The constraint satisfaction logic in `advanced_timetable_logic.py`. |

-----

## 4\. Getting Started

### Prerequisites

You will need the following installed on your system to run the project locally:

  * **Python 3.x**
  * **pip** (Python package installer)
  * **SQL Database:** Access to a running SQL server (e.g., MySQL or PostgreSQL) to host the database.

### Installation and Setup

Follow these steps to set up the project environment:

1.  **Clone the Repository:**

    ```bash
    git clone https://github.com/Ashi-run/Automatic-Timetable-Generator-
    cd Automatic-Timetable-Generator-
    ```

2.  **Install Python Dependencies:**
    All necessary Python libraries are listed in `requirements.txt`.

    ```bash
    pip install -r requirements.txt
    ```

3.  **Database Configuration:**
    a. Create a new database on your SQL server (e.g., `unisync_db`).
    b. **Configure Connection:** Edit the connection details in **`db_config.py`** to match your database credentials.
    c. **Initialize Schema:** Execute the SQL script to create the necessary tables:

    ```bash
    # Use your specific SQL command line or tool to run the file
    mysql -u [user] -p [database_name] < reclassify_tables.sql
    ```

4.  **Run the Application:**
    Start the Flask development server:

    ```bash
    python app.py
    ```

    The application will now be running at `http://localhost:5000` (or the port specified by Flask).

-----

## 5\. Usage Guide

The system is designed for a multi-step workflow:

### A. Data Input

1.  Navigate to the respective data entry pages (e.g., /faculty, /subjects).
2.  Input all required data points:
      * **Faculty:** Name, availability, maximum load, preferred subjects.
      * **Subjects:** Name, semester, number of required periods, and constraints.
      * **Rooms:** Room number, capacity, and special features (e.g., lab).

### B. Timetable Generation

1.  Once all data is entered and saved to the database, navigate to the **Generate Timetable** page.
2.  Click the **"Generate"** button. The logic in `advanced_timetable_logic.py` will run, solve the constraints, and save the resulting timetable to the database.

### C. Viewing and Export

1.  View the finalized timetable on the main page.
2.  The interface allows filtering by **Batch**, **Day**, and **Faculty** to verify the results.
3.  *(If implemented)* Use the print or export functions to generate a PDF or print-out of the schedule.

-----

## 6\. Project Structure

| File/Folder | Description |
| :--- | :--- |
| `app.py` | The main Python Flask application entry point. |
| `advanced_timetable_logic.py` | Contains the core algorithm for constraint satisfaction and timetable generation. |
| `db_config.py` | Database connection settings and utility functions. |
| `hod_db.py` | Contains database functions specific to HOD/Admin user roles. |
| `reclassify_tables.sql` | The SQL schema definition for creating all necessary tables. |
| `templates/` | HTML files for all web pages (UI). |
| `static/` | CSS, images, and other static assets for styling. |
| `requirements.txt` | List of all required Python packages. |

-----

## 7\. Key Constraints
 Key Constraints Handled by UNISYNC ⚙️
Timetable generation is a complex optimization problem. The UNISYNC system is specifically designed to manage and resolve a wide variety of constraints to ensure the generated schedule is both valid and high-quality.1. Hard Constraints (Must Not Be Violated)A timetable that violates any Hard Constraint is considered infeasible and unacceptable.Constraint CategoryConstraint DescriptionFaculty ConflictsHC1: A single faculty member cannot be assigned to two different classes or activities (lectures, labs) at the exact same time slot.Room ConflictsHC2: A single physical room (classroom, lab, seminar hall) cannot be assigned to more than one class at the same time slot.Batch/Student ConflictsHC3: A single student batch (e.g., "Second Year, Section A") cannot have two different subjects or activities scheduled at the same time slot.Room CapacityHC4: The room assigned to a class must have a seating capacity greater than or equal to the number of students in that class batch.Resource Type MatchHC5: A lab subject must only be scheduled in a designated lab room, and a theory subject must be scheduled in a general classroom.AvailabilityHC6: A class must only be scheduled when the assigned faculty member is explicitly available (i.e., not marked as unavailable for that time slot/day).Workload LimitsHC7: A faculty member’s total assigned lecture hours for the week must not exceed their predefined maximum teaching load.2. Soft Constraints (Desirable, but Negotiable)Soft Constraints relate to quality and preference. Violating them does not make the timetable invalid, but satisfying them increases the overall quality and user satisfaction.Constraint CategoryConstraint DescriptionSubject GroupingSC1: For subjects requiring multiple periods per day (e.g., practicals), periods should be scheduled consecutively (e.g., 2 back-to-back periods) to maintain flow.Faculty PreferencesSC2: Attempt to schedule faculty in their preferred time slots (e.g., morning lectures) or avoid their marked non-mandatory preferred free time.Workload DistributionSC3: The daily teaching load for any faculty member should be distributed evenly throughout the working week to prevent overly heavy or light days.Optimal BreaksSC4: Ensure a fair and appropriate scheduled break/lunch period for both students and faculty during the middle of the day.Course PrioritySC5: High-priority or core subjects should be scheduled during peak learning hours (e.g., mid-morning).Room ProximitySC6: Where possible, minimize the need for the same faculty or student batch to move long distances between two consecutive classes (e.g., assign nearby rooms).By successfully managing these constraints, UNISYNC ensures that the final timetable is not only conflict-free but also a highly optimized and efficient plan for resource allocation.

## 8\. License

This project is open-source. Please include a `LICENSE` file if you plan to share it publicly.

-----


## 9\. Contact

For questions or support, please contact the repository owner:

**[Ashi-run]**
*Project Link:* [https://github.com/Ashi-run/Automatic-Timetable-Generator-](https://github.com/Ashi-run/Automatic-Timetable-Generator-)
