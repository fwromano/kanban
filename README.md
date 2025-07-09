# Personal Kanban Board

A powerful, feature-rich personal kanban board application built with Flask and vanilla JavaScript. This single-file application provides a complete project management solution with advanced features rivaling commercial tools like Trello, Jira, and Asana.

## 🚀 Quick Start

### Super Easy Setup
1. **Run the launcher** (recommended):
   ```bash
   python launch_kanban.py
   ```
   This automatically creates a virtual environment, installs dependencies, and opens your browser!

### Manual Setup
1. **Install dependencies**:
   ```bash
   pip install flask flask-sqlalchemy
   ```

2. **Run the application**:
   ```bash
   python kanban_app.py
   ```

3. **Open your browser** to `http://localhost:5000`

That's it! No complex configuration, no database setup - everything works out of the box.

## ✨ Features

### Core Kanban Functionality
- **Drag-and-Drop Cards**: Intuitive card movement between columns
- **Multiple Boards**: Create and manage multiple project boards
- **Board Persistence**: Automatically saves board state
- **Archive System**: Archive cards to declutter while preserving data
- **Real-time Updates**: Instant UI updates without page refresh

### Advanced Card Management
- **Priority Levels**: High, Medium, Low priority indicators with color coding
- **Due Dates**: Start and due date tracking with overdue highlighting
- **Labels/Tags**: Color-coded labels for categorization
- **Rich Descriptions**: Detailed card descriptions with markdown support
- **Card Templates**: Save and reuse common card configurations

### Enhanced Features
- **✅ Checklists**: Track subtasks with progress indicators
- **📎 File Attachments**: Upload and manage files per card
- **📝 Markdown Support**: Format descriptions with markdown
- **🎯 Smart Filtering**: Advanced filtering by labels, priority, dates, and search

### Productivity Features
- **📅 Calendar View**: Visual calendar displaying cards by due date
- **⚡ Quick Add Cards**: Fast card creation with smart syntax (`#high @tomorrow`)
- **📦 Bulk Operations**: Select multiple cards for batch actions
- **🎨 Themes**: Light and dark mode support

### Advanced Filtering & Sorting
- **Search**: Full-text search across card titles and descriptions
- **Filter by**: Priority, labels, date ranges
- **Sort by**: Priority, due date, start date, title, creation date
- **Group by**: Priority, labels, or due dates with visual sections

### Dashboard & Analytics
- **Real-time Metrics**: Card counts, completion rates, priority distribution
- **Visual Charts**: Priority pie chart and column distribution
- **Overdue Tracking**: Highlight and track overdue items
- **Board Statistics**: Comprehensive board analytics

### Responsive Design
- **Desktop Optimized**: Full-featured experience on larger screens
- **Smart Small Mode**: Automatically switches to single-column view when space is constrained
- **Always One Page**: Dashboard and board content fit on one screen without scrolling

## 📖 Usage Guide

### Creating Cards

#### Standard Method
1. Click the **"+"** button on any column
2. Fill in card details (title, description, priority, dates, labels)
3. Click "Save Card"

#### Quick Add Method
1. **Double-click** on any column header
2. Type card title with smart syntax:
   - `#high`, `#medium`, `#low` - Set priority
   - `@today`, `@tomorrow`, `@nextweek` - Set due date
   - Example: `Fix bug #high @tomorrow`
3. Press **Enter** to create, **Esc** to cancel

### Managing Boards
- **Switch Boards**: Use the dropdown in the header
- **Create Board**: Click "＋ Board" button
- **Board Persistence**: Your current board selection is saved

### Using Labels
1. Click "Manage Labels" in any card
2. Create labels with custom colors
3. Assign multiple labels to cards
4. Filter by labels using the filter bar

### Calendar View
1. Click **"📅 Calendar"** button to switch views
2. View all cards with due dates on a monthly calendar
3. Click any card to open and edit
4. Navigate months with arrow buttons

### Bulk Operations
1. Press **'m'** key to enter multi-select mode
2. Check boxes appear on all cards
3. Select multiple cards
4. Use bulk action bar at bottom:
   - Move to column
   - Set priority
   - Add/remove labels
   - Archive selected

### Filtering & Sorting

#### Filtering Options
- **Search**: Type in search box for instant filtering
- **Priority**: Filter by High/Medium/Low
- **Labels**: Filter by specific labels
- **Date Range**: Filter by start/due date ranges

#### Sorting Options
- Sort by Priority (High → Low)
- Sort by Due Date (earliest first)
- Sort by Start Date
- Sort by Title (alphabetical)
- Sort by Created (newest first)

#### Grouping Options
- **Group by Priority**: Sections for High/Medium/Low
- **Group by Labels**: Group cards by their labels
- **Group by Due Date**: Smart grouping (Overdue, Today, This Week, etc.)

### Advanced Features

#### Checklists
1. Open any existing card
2. Click "Add Checklist"
3. Add checklist items
4. Check off completed items
5. See progress indicator on card preview

#### File Attachments
1. Open any existing card
2. Click "Add Attachment"
3. Select files to upload
4. Download or delete attachments as needed

#### Templates
1. Configure a card with common settings
2. Click "Save as Template"
3. Use templates when creating new cards

### Archive System
- **Archive Card**: Click "Archive" button in card modal
- **View Archives**: Click "📦 Archive" in header
- **Restore Card**: Click "Restore" on any archived card
- **Stats**: Archived cards are excluded from metrics

### Keyboard Shortcuts
- **Esc**: Close any open modal
- **m**: Toggle multi-select mode

### Theme Toggle
Click the **🌓** button to switch between light and dark themes

## 🔧 Configuration

### Environment Variables
- `KANBAN_DB`: Database URI (default: `sqlite:///kanban.db`)
- `KANBAN_PORT`: Server port (default: `5000`)

### Database
The application uses SQLite by default with automatic migrations. The database file `kanban.db` is created in the application directory.

## 🎯 Best Practices

1. **Quick Add Syntax**: Use `#priority` and `@date` for faster card creation
2. **Bulk Operations**: Use multi-select for managing many cards at once
3. **Templates**: Create templates for recurring task types
4. **Labels**: Use consistent labeling for better organization
5. **Calendar View**: Great for deadline management
6. **Archiving**: Keep board clean by archiving completed work

## 🏗️ Technical Details

### Single-File Design
The entire application is contained in `kanban_app.py`, including:
- Flask backend with RESTful API
- SQLAlchemy models
- HTML/CSS/JavaScript frontend
- Auto-migration system

### Models
- **Board**: Project boards
- **Column**: Kanban columns (Backlog, To Do, In Progress, Done)
- **Card**: Task cards with full metadata
- **Label**: Reusable labels for categorization
- **Checklist/ChecklistItem**: Subtask tracking
- **Attachment**: File upload management
- **CardTemplate**: Reusable card templates

### API Endpoints
- `/api/boards` - Board CRUD operations
- `/api/columns` - Column management
- `/api/cards` - Card CRUD with filtering
- `/api/labels` - Label management
- `/api/checklists` - Checklist operations
- `/api/attachments` - File upload/download
- `/api/metrics` - Dashboard statistics

### Architecture
- **Backend**: Flask with SQLAlchemy ORM
- **Frontend**: Vanilla JavaScript with reactive UI
- **Database**: SQLite with automatic migrations
- **Styling**: CSS with CSS variables for theming
- **Charts**: Chart.js for analytics visualization
- **Drag & Drop**: SortableJS for card movement

## 📄 License

MIT License - Feel free to use and modify for your needs.

---

**Note**: This is a single-file application designed for personal use. For production deployment, consider security hardening, authentication, and proper backup strategies.