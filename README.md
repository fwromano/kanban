# Flask Kanban Board

A self-contained, feature-rich Kanban board application built with Flask 3 and SQLite. It supports drag-and-drop functionality, a modal for task management, a dashboard with metrics, and a theme toggle.

## Features

* **Interactive Kanban Board:**
    * Create, edit, and delete cards.
    * Drag-and-drop cards between columns and reorder cards within columns (powered by SortableJS).
    * Add new columns to the board.
* **Rich Card Details:**
    * Cards include: Title, Description, Start Date, Due Date, and Priority (High, Medium, Low).
    * User-friendly modal (popup) for creating and editing card details.
* **Dashboard Metrics:**
    * View total number of cards.
    * See card counts by priority (High, Medium, Low).
    * Track overdue cards.
    * Display card counts per column.
* **Filtering:**
    * Client-side text search for cards.
    * Filter cards by priority.
    * Filter cards by start date (on or after).
    * Filter cards by due date (on or before).
    * Clear all active filters.
* **User Interface:**
    * Light and Dark theme toggle (persists in local storage).
    * Clean and responsive design.
* **Database:**
    * Uses SQLite for data storage (`kanban.db` file created automatically).
    * **Auto-migration:** Automatically adds missing columns (e.g., `start_date`, `due_date`, `priority`) to an existing `card` table if the database schema is outdated. This helps preserve data when updating the application.

## Technologies Used

* **Backend:**
    * Python 3
    * Flask 3
    * Flask-SQLAlchemy (for ORM and database interaction)
* **Database:**
    * SQLite
* **Frontend:**
    * HTML5
    * CSS3 (with CSS variables for theming)
    * Vanilla JavaScript (for UI interactions, API calls, modal, and filtering)
    * SortableJS (for drag-and-drop functionality)
    * Google Fonts (Inter)

## Setup and Installation

The easiest way to get started is by using the `launch_kanban.py` script (see "Running the Application" below), which automates virtual environment creation and dependency installation.

Alternatively, you can set up the environment manually:

## Running the Application

### Recommended Method: Using the Launcher Script (`launch_kanban.py`)

The `launch_kanban.py` script automates the setup and launch process. It will:
* Create (or re-use) a local virtual environment (default: `.venv`).
* Install/update Flask and Flask-SQLAlchemy (and any other specified requirements) inside it.
* Start the `kanban_app.py` server.
* Wait for the server to be ready and then automatically open it in your web browser.
* Stream server logs to your console.

To use it:
```bash
python launch_kanban.py
```
