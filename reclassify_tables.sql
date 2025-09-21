-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Host: 127.0.0.1
-- Generation Time: Sep 21, 2025 at 07:42 AM
-- Server version: 10.4.32-MariaDB
-- PHP Version: 8.0.30

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `reclassify`
--

-- --------------------------------------------------------

--
-- Table structure for table `academic_coordinators`
--

CREATE TABLE `academic_coordinators` (
  `coordinator_id` int(11) NOT NULL,
  `user_id` int(11) NOT NULL,
  `school_id` int(11) NOT NULL,
  `is_active` tinyint(1) DEFAULT 1,
  `assigned_date` date DEFAULT curdate()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `academic_years`
--

CREATE TABLE `academic_years` (
  `year_id` int(11) NOT NULL,
  `year_name` varchar(20) NOT NULL,
  `start_year` int(11) NOT NULL,
  `end_year` int(11) NOT NULL,
  `is_current` tinyint(1) DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `batches`
--

CREATE TABLE `batches` (
  `batch_id` int(11) NOT NULL,
  `year` int(11) NOT NULL,
  `academic_year_id` int(11) DEFAULT NULL,
  `semester` int(11) DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `batch_departments`
--

CREATE TABLE `batch_departments` (
  `batch_id` int(11) NOT NULL,
  `department_id` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `batch_subjects`
--

CREATE TABLE `batch_subjects` (
  `batch_subject_id` int(11) NOT NULL,
  `batch_id` int(11) NOT NULL,
  `semester` int(11) NOT NULL,
  `subject_id` int(11) NOT NULL,
  `preferred_lab_room_id` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `cancellations`
--

CREATE TABLE `cancellations` (
  `cancellation_id` int(11) NOT NULL,
  `timetable_id` int(11) NOT NULL,
  `reason` text NOT NULL,
  `canceled_by` int(11) NOT NULL,
  `suggested_faculty_id` int(11) DEFAULT NULL,
  `timestamp` datetime DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `credit_session_rules`
--

CREATE TABLE `credit_session_rules` (
  `credits` int(11) NOT NULL,
  `theory_sessions` int(11) NOT NULL,
  `lab_sessions` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `departments`
--

CREATE TABLE `departments` (
  `department_id` int(11) NOT NULL,
  `school_id` int(11) NOT NULL,
  `name` text NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `faculty_constraints`
--

CREATE TABLE `faculty_constraints` (
  `constraint_id` int(11) NOT NULL,
  `faculty_id` int(11) NOT NULL,
  `max_hours_per_week` int(11) DEFAULT 16,
  `max_hours_per_day` int(11) DEFAULT 3,
  `is_visiting_faculty` tinyint(1) DEFAULT 0,
  `available_days` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`available_days`)),
  `min_weekly_hours` int(11) DEFAULT NULL,
  `max_weekly_hours` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `faculty_subjects`
--

CREATE TABLE `faculty_subjects` (
  `faculty_subject_id` int(11) NOT NULL,
  `faculty_id` int(11) NOT NULL,
  `batch_subject_id` int(11) NOT NULL,
  `section_id` int(11) NOT NULL,
  `subsection_id` int(11) DEFAULT NULL,
  `assigned_date` datetime DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `faculty_unavailability`
--

CREATE TABLE `faculty_unavailability` (
  `id` int(11) NOT NULL,
  `faculty_id` int(11) NOT NULL,
  `day_of_week` varchar(10) DEFAULT NULL,
  `start_time` time DEFAULT NULL,
  `end_time` time DEFAULT NULL,
  `reason` varchar(100) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `faculty_workload`
--

CREATE TABLE `faculty_workload` (
  `workload_id` int(11) NOT NULL,
  `faculty_id` int(11) NOT NULL,
  `week_start_date` date NOT NULL,
  `total_hours_assigned` decimal(5,2) DEFAULT 0.00,
  `total_sessions` int(11) DEFAULT 0,
  `last_updated` datetime DEFAULT current_timestamp() ON UPDATE current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `holidays`
--

CREATE TABLE `holidays` (
  `holiday_id` int(11) NOT NULL,
  `date` date NOT NULL,
  `name` varchar(100) NOT NULL,
  `type` varchar(50) NOT NULL,
  `holiday_type` enum('National','University','Exam','Break') DEFAULT 'University',
  `affects_timetable` tinyint(1) DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `lecture_trackers`
--

CREATE TABLE `lecture_trackers` (
  `track_id` int(11) NOT NULL,
  `batch_subject_id` int(11) NOT NULL,
  `section_id` int(11) NOT NULL,
  `total_required` int(11) NOT NULL,
  `conducted` int(11) DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `notifications`
--

CREATE TABLE `notifications` (
  `notification_id` int(11) NOT NULL,
  `user_id` int(11) NOT NULL,
  `type` text NOT NULL,
  `message` text NOT NULL,
  `seen` tinyint(1) DEFAULT 0,
  `timestamp` datetime DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `rooms`
--

CREATE TABLE `rooms` (
  `room_id` int(11) NOT NULL,
  `room_number` varchar(50) NOT NULL,
  `room_type` enum('Lecture','Lab') NOT NULL,
  `capacity` int(11) NOT NULL,
  `building` varchar(100) DEFAULT NULL,
  `floor` int(11) DEFAULT NULL,
  `is_active` tinyint(1) DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `room_unavailability`
--

CREATE TABLE `room_unavailability` (
  `unavailability_id` int(11) NOT NULL,
  `room_id` int(11) NOT NULL,
  `date` date NOT NULL,
  `start_time` time NOT NULL,
  `end_time` time NOT NULL,
  `reason` text DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `schools`
--

CREATE TABLE `schools` (
  `school_id` int(11) NOT NULL,
  `name` text NOT NULL,
  `abbrevation` varchar(100) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `sections`
--

CREATE TABLE `sections` (
  `section_id` int(11) NOT NULL,
  `batch_id` int(11) NOT NULL,
  `name` text NOT NULL,
  `theory_room_id` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `section_enrollment`
--

CREATE TABLE `section_enrollment` (
  `section_id` int(11) NOT NULL,
  `total_students` int(11) NOT NULL,
  `max_subsection_size` int(11) DEFAULT 30
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `semester_config`
--

CREATE TABLE `semester_config` (
  `semester_id` int(11) NOT NULL,
  `academic_year` varchar(20) NOT NULL,
  `semester_number` int(11) NOT NULL,
  `start_date` date NOT NULL,
  `end_date` date NOT NULL,
  `total_weeks` int(11) DEFAULT 15,
  `is_active` tinyint(1) DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `semester_info`
--

CREATE TABLE `semester_info` (
  `sem_id` int(11) NOT NULL,
  `start_date` date NOT NULL,
  `end_date` date NOT NULL,
  `school_id` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `semester_timetables`
--

CREATE TABLE `semester_timetables` (
  `section_id` int(11) NOT NULL,
  `start_date` date NOT NULL,
  `faculty_id` int(11) NOT NULL,
  `subject_id` int(11) NOT NULL,
  `timeslot_id` int(11) NOT NULL,
  `day_of_week` varchar(10) NOT NULL,
  `start_time` time NOT NULL,
  `end_time` time NOT NULL,
  `room_id` int(11) NOT NULL,
  `date` date NOT NULL,
  `week_number` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `subjects`
--

CREATE TABLE `subjects` (
  `subject_id` int(11) NOT NULL,
  `subject_code` varchar(20) NOT NULL,
  `name` text NOT NULL,
  `credits` int(11) NOT NULL,
  `theory_sessions_per_week` int(11) DEFAULT NULL,
  `lab_sessions_per_week` int(11) DEFAULT NULL,
  `lab_duration_hours` decimal(3,1) DEFAULT NULL,
  `is_lab_continuous` tinyint(1) DEFAULT 1,
  `exam_type` enum('External','Internal') DEFAULT 'External',
  `has_lab` tinyint(1) DEFAULT 0,
  `preferred_lab_room_id` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `subject_progress`
--

CREATE TABLE `subject_progress` (
  `progress_id` int(11) NOT NULL,
  `section_id` int(11) NOT NULL,
  `batch_subject_id` int(11) NOT NULL,
  `faculty_id` int(11) NOT NULL,
  `planned_sessions` int(11) NOT NULL,
  `completed_sessions` int(11) DEFAULT 0,
  `remaining_sessions` int(11) GENERATED ALWAYS AS (`planned_sessions` - `completed_sessions`) STORED,
  `completion_percentage` decimal(5,2) GENERATED ALWAYS AS (`completed_sessions` / `planned_sessions` * 100) STORED,
  `last_updated` datetime DEFAULT current_timestamp() ON UPDATE current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `subsections`
--

CREATE TABLE `subsections` (
  `subsection_id` int(11) NOT NULL,
  `section_id` int(11) NOT NULL,
  `name` text NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `substitute_requests`
--

CREATE TABLE `substitute_requests` (
  `request_id` int(11) NOT NULL,
  `cancellation_id` int(11) NOT NULL,
  `requested_to` int(11) NOT NULL,
  `status` text DEFAULT 'pending',
  `responded_at` datetime DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `timeslots`
--

CREATE TABLE `timeslots` (
  `timeslot_id` int(11) NOT NULL,
  `day_of_week` text NOT NULL,
  `start_time` time NOT NULL,
  `end_time` time NOT NULL,
  `is_active` tinyint(1) DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `timetable`
--

CREATE TABLE `timetable` (
  `entry_id` int(11) NOT NULL,
  `section_id` int(11) NOT NULL,
  `faculty_id` int(11) NOT NULL,
  `batch_subject_id` int(11) NOT NULL,
  `timeslot_id` int(11) NOT NULL,
  `day_of_week` varchar(10) NOT NULL,
  `room_id` int(11) DEFAULT NULL,
  `subsection_id` int(11) DEFAULT NULL,
  `week_number` int(11) DEFAULT 1,
  `date` date DEFAULT NULL,
  `is_rescheduled` tinyint(1) DEFAULT 0,
  `created_at` datetime DEFAULT current_timestamp(),
  `modified_at` datetime DEFAULT NULL,
  `log_id` int(11) DEFAULT NULL,
  `is_lab_session` tinyint(1) DEFAULT 0,
  `is_completed` tinyint(1) DEFAULT 0,
  `is_cancelled` tinyint(1) DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `timetable_generation_log`
--

CREATE TABLE `timetable_generation_log` (
  `log_id` int(11) NOT NULL,
  `section_id` int(11) NOT NULL,
  `generation_date` datetime DEFAULT current_timestamp(),
  `status` enum('Success','Failed','Partial') NOT NULL,
  `constraints_violated` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `total_slots_assigned` int(11) DEFAULT 0,
  `total_slots_required` int(11) DEFAULT 0,
  `generation_time_seconds` decimal(10,3) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `users`
--

CREATE TABLE `users` (
  `user_id` int(11) NOT NULL,
  `name` text NOT NULL,
  `email` text NOT NULL,
  `password_hash` text NOT NULL,
  `role` text NOT NULL,
  `school_id` int(11) NOT NULL,
  `department_id` int(11) DEFAULT NULL,
  `employment_type` text DEFAULT 'permanent',
  `section_id` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `user_roles`
--

CREATE TABLE `user_roles` (
  `user_id` int(11) NOT NULL,
  `role` varchar(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `user_sessions`
--

CREATE TABLE `user_sessions` (
  `session_id` varchar(255) NOT NULL,
  `user_id` int(11) NOT NULL,
  `school_id` int(11) DEFAULT NULL,
  `login_time` datetime DEFAULT current_timestamp(),
  `last_activity` datetime DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  `is_active` tinyint(1) DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Indexes for dumped tables
--

--
-- Indexes for table `academic_coordinators`
--
ALTER TABLE `academic_coordinators`
  ADD PRIMARY KEY (`coordinator_id`),
  ADD KEY `user_id` (`user_id`),
  ADD KEY `school_id` (`school_id`);

--
-- Indexes for table `academic_years`
--
ALTER TABLE `academic_years`
  ADD PRIMARY KEY (`year_id`);

--
-- Indexes for table `batches`
--
ALTER TABLE `batches`
  ADD PRIMARY KEY (`batch_id`),
  ADD KEY `academic_year_id` (`academic_year_id`);

--
-- Indexes for table `batch_departments`
--
ALTER TABLE `batch_departments`
  ADD PRIMARY KEY (`batch_id`,`department_id`),
  ADD KEY `department_id` (`department_id`);

--
-- Indexes for table `batch_subjects`
--
ALTER TABLE `batch_subjects`
  ADD PRIMARY KEY (`batch_subject_id`),
  ADD UNIQUE KEY `batch_id_semester_subject_id` (`batch_id`,`semester`,`subject_id`),
  ADD KEY `subject_id` (`subject_id`),
  ADD KEY `fk_batch_subjects_room` (`preferred_lab_room_id`);

--
-- Indexes for table `cancellations`
--
ALTER TABLE `cancellations`
  ADD PRIMARY KEY (`cancellation_id`),
  ADD KEY `timetable_id` (`timetable_id`),
  ADD KEY `canceled_by` (`canceled_by`),
  ADD KEY `suggested_faculty_id` (`suggested_faculty_id`);

--
-- Indexes for table `credit_session_rules`
--
ALTER TABLE `credit_session_rules`
  ADD PRIMARY KEY (`credits`);

--
-- Indexes for table `departments`
--
ALTER TABLE `departments`
  ADD PRIMARY KEY (`department_id`),
  ADD UNIQUE KEY `name` (`name`) USING HASH,
  ADD KEY `school_id` (`school_id`);

--
-- Indexes for table `faculty_constraints`
--
ALTER TABLE `faculty_constraints`
  ADD PRIMARY KEY (`constraint_id`),
  ADD KEY `faculty_id` (`faculty_id`);

--
-- Indexes for table `faculty_subjects`
--
ALTER TABLE `faculty_subjects`
  ADD PRIMARY KEY (`faculty_subject_id`),
  ADD UNIQUE KEY `composite_key` (`faculty_id`,`batch_subject_id`,`section_id`,`subsection_id`),
  ADD KEY `batch_subject_id` (`batch_subject_id`),
  ADD KEY `section_id` (`section_id`),
  ADD KEY `subsection_id` (`subsection_id`);

--
-- Indexes for table `faculty_unavailability`
--
ALTER TABLE `faculty_unavailability`
  ADD PRIMARY KEY (`id`),
  ADD KEY `faculty_id` (`faculty_id`);

--
-- Indexes for table `faculty_workload`
--
ALTER TABLE `faculty_workload`
  ADD PRIMARY KEY (`workload_id`),
  ADD KEY `faculty_id` (`faculty_id`);

--
-- Indexes for table `holidays`
--
ALTER TABLE `holidays`
  ADD PRIMARY KEY (`holiday_id`);

--
-- Indexes for table `lecture_trackers`
--
ALTER TABLE `lecture_trackers`
  ADD PRIMARY KEY (`track_id`),
  ADD KEY `batch_subject_id` (`batch_subject_id`),
  ADD KEY `section_id` (`section_id`);

--
-- Indexes for table `notifications`
--
ALTER TABLE `notifications`
  ADD PRIMARY KEY (`notification_id`),
  ADD KEY `user_id` (`user_id`);

--
-- Indexes for table `rooms`
--
ALTER TABLE `rooms`
  ADD PRIMARY KEY (`room_id`);

--
-- Indexes for table `room_unavailability`
--
ALTER TABLE `room_unavailability`
  ADD PRIMARY KEY (`unavailability_id`),
  ADD KEY `room_id` (`room_id`);

--
-- Indexes for table `schools`
--
ALTER TABLE `schools`
  ADD PRIMARY KEY (`school_id`);

--
-- Indexes for table `sections`
--
ALTER TABLE `sections`
  ADD PRIMARY KEY (`section_id`),
  ADD KEY `batch_id` (`batch_id`),
  ADD KEY `fk_sections_room` (`theory_room_id`);

--
-- Indexes for table `section_enrollment`
--
ALTER TABLE `section_enrollment`
  ADD PRIMARY KEY (`section_id`);

--
-- Indexes for table `semester_config`
--
ALTER TABLE `semester_config`
  ADD PRIMARY KEY (`semester_id`),
  ADD UNIQUE KEY `academic_year_semester_number` (`academic_year`,`semester_number`);

--
-- Indexes for table `semester_info`
--
ALTER TABLE `semester_info`
  ADD PRIMARY KEY (`sem_id`),
  ADD KEY `school_id` (`school_id`);

--
-- Indexes for table `semester_timetables`
--
ALTER TABLE `semester_timetables`
  ADD PRIMARY KEY (`section_id`,`start_date`,`timeslot_id`,`date`),
  ADD KEY `faculty_id` (`faculty_id`),
  ADD KEY `subject_id` (`subject_id`),
  ADD KEY `timeslot_id` (`timeslot_id`),
  ADD KEY `room_id` (`room_id`);

--
-- Indexes for table `subjects`
--
ALTER TABLE `subjects`
  ADD PRIMARY KEY (`subject_id`),
  ADD UNIQUE KEY `subject_code` (`subject_code`),
  ADD KEY `fk_subjects_rooms` (`preferred_lab_room_id`);

--
-- Indexes for table `subject_progress`
--
ALTER TABLE `subject_progress`
  ADD PRIMARY KEY (`progress_id`),
  ADD KEY `section_id` (`section_id`),
  ADD KEY `batch_subject_id` (`batch_subject_id`),
  ADD KEY `faculty_id` (`faculty_id`);

--
-- Indexes for table `subsections`
--
ALTER TABLE `subsections`
  ADD PRIMARY KEY (`subsection_id`),
  ADD KEY `section_id` (`section_id`);

--
-- Indexes for table `substitute_requests`
--
ALTER TABLE `substitute_requests`
  ADD PRIMARY KEY (`request_id`),
  ADD KEY `cancellation_id` (`cancellation_id`),
  ADD KEY `requested_to` (`requested_to`);

--
-- Indexes for table `timeslots`
--
ALTER TABLE `timeslots`
  ADD PRIMARY KEY (`timeslot_id`);

--
-- Indexes for table `timetable`
--
ALTER TABLE `timetable`
  ADD PRIMARY KEY (`entry_id`),
  ADD KEY `section_id` (`section_id`),
  ADD KEY `faculty_id` (`faculty_id`),
  ADD KEY `batch_subject_id` (`batch_subject_id`),
  ADD KEY `timeslot_id` (`timeslot_id`),
  ADD KEY `room_id` (`room_id`),
  ADD KEY `subsection_id` (`subsection_id`);

--
-- Indexes for table `timetable_generation_log`
--
ALTER TABLE `timetable_generation_log`
  ADD PRIMARY KEY (`log_id`),
  ADD KEY `section_id` (`section_id`);

--
-- Indexes for table `users`
--
ALTER TABLE `users`
  ADD PRIMARY KEY (`user_id`),
  ADD UNIQUE KEY `email` (`email`) USING HASH,
  ADD KEY `school_id` (`school_id`),
  ADD KEY `department_id` (`department_id`);

--
-- Indexes for table `user_roles`
--
ALTER TABLE `user_roles`
  ADD PRIMARY KEY (`user_id`,`role`);

--
-- Indexes for table `user_sessions`
--
ALTER TABLE `user_sessions`
  ADD PRIMARY KEY (`session_id`),
  ADD KEY `user_id` (`user_id`),
  ADD KEY `school_id` (`school_id`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `academic_coordinators`
--
ALTER TABLE `academic_coordinators`
  MODIFY `coordinator_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `academic_years`
--
ALTER TABLE `academic_years`
  MODIFY `year_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `batches`
--
ALTER TABLE `batches`
  MODIFY `batch_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `batch_subjects`
--
ALTER TABLE `batch_subjects`
  MODIFY `batch_subject_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `cancellations`
--
ALTER TABLE `cancellations`
  MODIFY `cancellation_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `departments`
--
ALTER TABLE `departments`
  MODIFY `department_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `faculty_constraints`
--
ALTER TABLE `faculty_constraints`
  MODIFY `constraint_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `faculty_subjects`
--
ALTER TABLE `faculty_subjects`
  MODIFY `faculty_subject_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `faculty_unavailability`
--
ALTER TABLE `faculty_unavailability`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `faculty_workload`
--
ALTER TABLE `faculty_workload`
  MODIFY `workload_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `holidays`
--
ALTER TABLE `holidays`
  MODIFY `holiday_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `lecture_trackers`
--
ALTER TABLE `lecture_trackers`
  MODIFY `track_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `notifications`
--
ALTER TABLE `notifications`
  MODIFY `notification_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `rooms`
--
ALTER TABLE `rooms`
  MODIFY `room_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `room_unavailability`
--
ALTER TABLE `room_unavailability`
  MODIFY `unavailability_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `schools`
--
ALTER TABLE `schools`
  MODIFY `school_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `sections`
--
ALTER TABLE `sections`
  MODIFY `section_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `semester_config`
--
ALTER TABLE `semester_config`
  MODIFY `semester_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `semester_info`
--
ALTER TABLE `semester_info`
  MODIFY `sem_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `subjects`
--
ALTER TABLE `subjects`
  MODIFY `subject_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `subject_progress`
--
ALTER TABLE `subject_progress`
  MODIFY `progress_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `subsections`
--
ALTER TABLE `subsections`
  MODIFY `subsection_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `substitute_requests`
--
ALTER TABLE `substitute_requests`
  MODIFY `request_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `timeslots`
--
ALTER TABLE `timeslots`
  MODIFY `timeslot_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `timetable`
--
ALTER TABLE `timetable`
  MODIFY `entry_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `timetable_generation_log`
--
ALTER TABLE `timetable_generation_log`
  MODIFY `log_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `users`
--
ALTER TABLE `users`
  MODIFY `user_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- Constraints for dumped tables
--

--
-- Constraints for table `academic_coordinators`
--
ALTER TABLE `academic_coordinators`
  ADD CONSTRAINT `academic_coordinators_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `academic_coordinators_ibfk_2` FOREIGN KEY (`school_id`) REFERENCES `schools` (`school_id`) ON DELETE CASCADE;

--
-- Constraints for table `batches`
--
ALTER TABLE `batches`
  ADD CONSTRAINT `batches_ibfk_1` FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years` (`year_id`) ON DELETE SET NULL;

--
-- Constraints for table `batch_departments`
--
ALTER TABLE `batch_departments`
  ADD CONSTRAINT `batch_departments_ibfk_1` FOREIGN KEY (`batch_id`) REFERENCES `batches` (`batch_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `batch_departments_ibfk_2` FOREIGN KEY (`department_id`) REFERENCES `departments` (`department_id`) ON DELETE CASCADE;

--
-- Constraints for table `batch_subjects`
--
ALTER TABLE `batch_subjects`
  ADD CONSTRAINT `batch_subjects_ibfk_1` FOREIGN KEY (`batch_id`) REFERENCES `batches` (`batch_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `batch_subjects_ibfk_2` FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`subject_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `fk_batch_subjects_room` FOREIGN KEY (`preferred_lab_room_id`) REFERENCES `rooms` (`room_id`) ON DELETE SET NULL;

--
-- Constraints for table `cancellations`
--
ALTER TABLE `cancellations`
  ADD CONSTRAINT `cancellations_ibfk_1` FOREIGN KEY (`timetable_id`) REFERENCES `timetable` (`entry_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `cancellations_ibfk_2` FOREIGN KEY (`canceled_by`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `cancellations_ibfk_3` FOREIGN KEY (`suggested_faculty_id`) REFERENCES `users` (`user_id`) ON DELETE SET NULL;

--
-- Constraints for table `departments`
--
ALTER TABLE `departments`
  ADD CONSTRAINT `departments_ibfk_1` FOREIGN KEY (`school_id`) REFERENCES `schools` (`school_id`) ON DELETE CASCADE;

--
-- Constraints for table `faculty_constraints`
--
ALTER TABLE `faculty_constraints`
  ADD CONSTRAINT `faculty_constraints_ibfk_1` FOREIGN KEY (`faculty_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE;

--
-- Constraints for table `faculty_unavailability`
--
ALTER TABLE `faculty_unavailability`
  ADD CONSTRAINT `faculty_unavailability_ibfk_1` FOREIGN KEY (`faculty_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE;

--
-- Constraints for table `faculty_workload`
--
ALTER TABLE `faculty_workload`
  ADD CONSTRAINT `faculty_workload_ibfk_1` FOREIGN KEY (`faculty_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE;

--
-- Constraints for table `lecture_trackers`
--
ALTER TABLE `lecture_trackers`
  ADD CONSTRAINT `lecture_trackers_ibfk_2` FOREIGN KEY (`section_id`) REFERENCES `sections` (`section_id`) ON DELETE CASCADE;

--
-- Constraints for table `notifications`
--
ALTER TABLE `notifications`
  ADD CONSTRAINT `notifications_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE;

--
-- Constraints for table `room_unavailability`
--
ALTER TABLE `room_unavailability`
  ADD CONSTRAINT `room_unavailability_ibfk_1` FOREIGN KEY (`room_id`) REFERENCES `rooms` (`room_id`) ON DELETE CASCADE;

--
-- Constraints for table `sections`
--
ALTER TABLE `sections`
  ADD CONSTRAINT `fk_sections_room` FOREIGN KEY (`theory_room_id`) REFERENCES `rooms` (`room_id`) ON DELETE SET NULL,
  ADD CONSTRAINT `sections_ibfk_1` FOREIGN KEY (`batch_id`) REFERENCES `batches` (`batch_id`) ON DELETE CASCADE;

--
-- Constraints for table `section_enrollment`
--
ALTER TABLE `section_enrollment`
  ADD CONSTRAINT `section_enrollment_ibfk_1` FOREIGN KEY (`section_id`) REFERENCES `sections` (`section_id`) ON DELETE CASCADE;

--
-- Constraints for table `semester_info`
--
ALTER TABLE `semester_info`
  ADD CONSTRAINT `semester_info_ibfk_1` FOREIGN KEY (`school_id`) REFERENCES `schools` (`school_id`) ON DELETE CASCADE;

--
-- Constraints for table `semester_timetables`
--
ALTER TABLE `semester_timetables`
  ADD CONSTRAINT `semester_timetables_ibfk_1` FOREIGN KEY (`section_id`) REFERENCES `sections` (`section_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `semester_timetables_ibfk_2` FOREIGN KEY (`faculty_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `semester_timetables_ibfk_3` FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`subject_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `semester_timetables_ibfk_4` FOREIGN KEY (`timeslot_id`) REFERENCES `timeslots` (`timeslot_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `semester_timetables_ibfk_5` FOREIGN KEY (`room_id`) REFERENCES `rooms` (`room_id`) ON DELETE CASCADE;

--
-- Constraints for table `subjects`
--
ALTER TABLE `subjects`
  ADD CONSTRAINT `fk_subjects_rooms` FOREIGN KEY (`preferred_lab_room_id`) REFERENCES `rooms` (`room_id`) ON DELETE SET NULL ON UPDATE CASCADE;

--
-- Constraints for table `subject_progress`
--
ALTER TABLE `subject_progress`
  ADD CONSTRAINT `subject_progress_ibfk_1` FOREIGN KEY (`section_id`) REFERENCES `sections` (`section_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `subject_progress_ibfk_2` FOREIGN KEY (`batch_subject_id`) REFERENCES `batch_subjects` (`batch_subject_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `subject_progress_ibfk_3` FOREIGN KEY (`faculty_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE;

--
-- Constraints for table `subsections`
--
ALTER TABLE `subsections`
  ADD CONSTRAINT `subsections_ibfk_1` FOREIGN KEY (`section_id`) REFERENCES `sections` (`section_id`) ON DELETE CASCADE;

--
-- Constraints for table `substitute_requests`
--
ALTER TABLE `substitute_requests`
  ADD CONSTRAINT `substitute_requests_ibfk_1` FOREIGN KEY (`cancellation_id`) REFERENCES `cancellations` (`cancellation_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `substitute_requests_ibfk_2` FOREIGN KEY (`requested_to`) REFERENCES `users` (`user_id`) ON DELETE CASCADE;

--
-- Constraints for table `timetable`
--
ALTER TABLE `timetable`
  ADD CONSTRAINT `timetable_ibfk_1` FOREIGN KEY (`section_id`) REFERENCES `sections` (`section_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `timetable_ibfk_2` FOREIGN KEY (`faculty_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `timetable_ibfk_3` FOREIGN KEY (`batch_subject_id`) REFERENCES `batch_subjects` (`batch_subject_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `timetable_ibfk_4` FOREIGN KEY (`timeslot_id`) REFERENCES `timeslots` (`timeslot_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `timetable_ibfk_5` FOREIGN KEY (`room_id`) REFERENCES `rooms` (`room_id`) ON DELETE SET NULL,
  ADD CONSTRAINT `timetable_ibfk_6` FOREIGN KEY (`subsection_id`) REFERENCES `subsections` (`subsection_id`) ON DELETE CASCADE;

--
-- Constraints for table `timetable_generation_log`
--
ALTER TABLE `timetable_generation_log`
  ADD CONSTRAINT `timetable_generation_log_ibfk_1` FOREIGN KEY (`section_id`) REFERENCES `sections` (`section_id`) ON DELETE CASCADE;

--
-- Constraints for table `users`
--
ALTER TABLE `users`
  ADD CONSTRAINT `users_ibfk_1` FOREIGN KEY (`school_id`) REFERENCES `schools` (`school_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `users_ibfk_2` FOREIGN KEY (`department_id`) REFERENCES `departments` (`department_id`) ON DELETE SET NULL;

--
-- Constraints for table `user_roles`
--
ALTER TABLE `user_roles`
  ADD CONSTRAINT `user_roles_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE;

--
-- Constraints for table `user_sessions`
--
ALTER TABLE `user_sessions`
  ADD CONSTRAINT `user_sessions_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `user_sessions_ibfk_2` FOREIGN KEY (`school_id`) REFERENCES `schools` (`school_id`) ON DELETE SET NULL;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
