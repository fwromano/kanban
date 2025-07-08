# Personal Kanban Implementation Roadmap

This document outlines the implementation plan for enhancing the personal kanban board with additional features. Each phase builds upon the previous one, with features grouped by complexity and dependencies.

## Current State Summary
- ✅ Basic CRUD operations for cards and columns
- ✅ Drag-and-drop functionality
- ✅ Priority levels and date fields
- ✅ Basic filtering and search
- ✅ Dashboard with metrics
- ✅ Light/dark theme toggle
- ✅ SQLite database with auto-migration

## Phase 1: Core Enhancements (Foundation)
These features improve the existing functionality without major architectural changes.

### 1.1 Multiple Boards Support
**Priority:** High  
**Complexity:** Medium  
**Implementation:**
- Add `Board` model with fields: `id`, `name`, `description`, `created_at`, `updated_at`, `is_active`
- Add `board_id` foreign key to `Column` model
- Create board switcher UI component
- Add `/api/boards` endpoints (GET, POST, PUT, DELETE)
- Implement board selection persistence in localStorage
- Add "Create New Board" modal
- **Database Migration:** Add boards table, update columns table

### 1.2 Card Archiving
**Priority:** High  
**Complexity:** Low  
**Implementation:**
- Add `is_archived` boolean field to `Card` model
- Add "Archive" button to card modal/context menu
- Create archived cards view/filter
- Add bulk archive functionality for columns
- Implement restore from archive
- **Database Migration:** Add is_archived column to cards table

### 1.3 Labels/Tags System
**Priority:** High  
**Complexity:** Medium  
**Implementation:**
- Create `Label` model: `id`, `name`, `color`, `board_id`
- Create `CardLabel` association table for many-to-many relationship
- Add label management UI (create, edit, delete labels)
- Add label picker to card modal
- Display labels on card preview
- Add label-based filtering
- **Database Migration:** Add labels and card_labels tables

### 1.4 Keyboard Shortcuts
**Priority:** Medium  
**Complexity:** Low  
**Implementation:**
- Create keyboard event handler system
- Implement shortcuts:
  - `n`: New card
  - `b`: New board
  - `c`: New column
  - `/`: Focus search
  - `esc`: Close modals
  - `1-9`: Quick priority set
  - `?`: Show shortcuts help
- Add shortcuts help modal
- Store shortcut preferences

## Phase 2: Enhanced Card Features

### 2.1 Checklists
**Priority:** High  
**Complexity:** Medium  
**Implementation:**
- Create `Checklist` model: `id`, `card_id`, `title`, `position`
- Create `ChecklistItem` model: `id`, `checklist_id`, `text`, `is_checked`, `position`
- Add checklist UI component to card modal
- Implement checklist progress indicator on card
- Add `/api/cards/{id}/checklists` endpoints
- **Database Migration:** Add checklists and checklist_items tables

### 2.2 File Attachments
**Priority:** Medium  
**Complexity:** High  
**Implementation:**
- Create `Attachment` model: `id`, `card_id`, `filename`, `file_path`, `file_size`, `mime_type`, `uploaded_at`
- Add file upload endpoint with size/type validation
- Create attachments directory structure
- Add attachment UI in card modal
- Implement file preview for images
- Add attachment download endpoint
- **Database Migration:** Add attachments table

### 2.3 Card Templates
**Priority:** Medium  
**Complexity:** Medium  
**Implementation:**
- Create `CardTemplate` model: `id`, `name`, `description`, `template_data` (JSON)
- Add "Save as Template" option in card modal
- Create template picker when creating new cards
- Store templates with all card fields including checklists
- Add template management UI
- **Database Migration:** Add card_templates table

### 2.4 Markdown Support
**Priority:** Low  
**Complexity:** Low  
**Implementation:**
- Add markdown parser library (markdown-it or similar)
- Add markdown preview toggle in card description
- Create markdown toolbar for common formatting
- Add syntax highlighting for code blocks
- Update card preview to render basic markdown

## Phase 3: Advanced Views & Productivity

### 3.1 Calendar View
**Priority:** High  
**Complexity:** High  
**Implementation:**
- Create calendar component using CSS Grid
- Add view toggle (Board/Calendar)
- Display cards on calendar by due date
- Implement month/week/day views
- Add drag-and-drop to change dates
- Create calendar navigation controls
- Add quick date picker from calendar

### 3.2 Time Tracking
**Priority:** Medium  
**Complexity:** Medium  
**Implementation:**
- Add `time_estimate` and `time_spent` fields to Card model
- Create `TimeEntry` model: `id`, `card_id`, `start_time`, `end_time`, `description`
- Add timer component to card modal
- Implement start/stop timer functionality
- Add time tracking summary in dashboard
- Create time report view
- **Database Migration:** Add time fields and time_entries table

### 3.3 Quick Add Cards
**Priority:** High  
**Complexity:** Low  
**Implementation:**
- Add inline card creation at top of columns
- Parse quick add syntax (e.g., "Task title #high @tomorrow")
- Auto-assign to default column
- Add global quick add shortcut
- Implement bulk add with line separation

### 3.4 Bulk Operations
**Priority:** Medium  
**Complexity:** Medium  
**Implementation:**
- Add multi-select mode toggle
- Implement checkbox selection for cards
- Add bulk actions menu:
  - Move to column
  - Change priority
  - Archive/Delete
  - Add/Remove labels
- Add "Select All" functionality
- Implement undo for bulk operations

## Phase 4: Data Management & Import/Export

### 4.1 Import/Export
**Priority:** High  
**Complexity:** Medium  
**Implementation:**
- Create export formats:
  - JSON (full data with relationships)
  - CSV (flat structure for spreadsheets)
  - Markdown (for documentation)
- Add import validation and mapping UI
- Implement conflict resolution for imports
- Add scheduled auto-export option
- Create import from Trello JSON

### 4.2 Backup/Restore
**Priority:** High  
**Complexity:** Low  
**Implementation:**
- Add manual backup button
- Create timestamped backup files
- Implement restore with confirmation
- Add auto-backup on startup
- Keep last N backups configuration
- Store backups in `backups/` directory

### 4.3 Card History
**Priority:** Low  
**Complexity:** Medium  
**Implementation:**
- Create `CardHistory` model: `id`, `card_id`, `field_name`, `old_value`, `new_value`, `changed_at`
- Track changes to all card fields
- Add history view in card modal
- Implement history cleanup (keep last N days)
- Add activity timeline view
- **Database Migration:** Add card_history table

## Phase 5: Automation & Workflow

### 5.1 Simple Automation Rules
**Priority:** Medium  
**Complexity:** High  
**Implementation:**
- Create `AutomationRule` model: `id`, `board_id`, `trigger_type`, `trigger_config`, `action_type`, `action_config`
- Implement triggers:
  - Card moved to column
  - Due date approaching
  - Card created
  - Label added
- Implement actions:
  - Move to column
  - Set priority
  - Add label
  - Archive card
- Add rule builder UI
- Create rule execution engine
- **Database Migration:** Add automation_rules table

### 5.2 Recurring Tasks
**Priority:** Medium  
**Complexity:** Medium  
**Implementation:**
- Add `recurrence_pattern` field to Card model
- Create recurrence UI (daily, weekly, monthly, custom)
- Implement task generation on completion/schedule
- Add recurring task indicator
- Create recurrence management view
- **Database Migration:** Add recurrence fields

### 5.3 WIP Limits
**Priority:** Low  
**Complexity:** Low  
**Implementation:**
- Add `wip_limit` field to Column model
- Add WIP limit setting in column header
- Show visual warning when limit exceeded
- Optional hard limit (prevent adding cards)
- Add WIP limit stats to dashboard
- **Database Migration:** Add wip_limit to columns

## Phase 6: UI/UX Improvements

### 6.1 Enhanced Themes
**Priority:** Low  
**Complexity:** Medium  
**Implementation:**
- Create theme system with CSS variables
- Add built-in themes:
  - High contrast
  - Solarized (light/dark)
  - Custom color picker
- Add theme preview
- Store custom themes
- Add seasonal themes

### 6.2 Customizable Board Backgrounds
**Priority:** Low  
**Complexity:** Low  
**Implementation:**
- Add background image upload
- Create gradient background generator
- Add pattern backgrounds
- Implement opacity control
- Store background preferences per board

### 6.3 Focus/Zen Mode
**Priority:** Low  
**Complexity:** Low  
**Implementation:**
- Hide all UI except current column/card
- Add focus timer integration
- Minimize distractions mode
- Keyboard navigation only mode
- Add focus session tracking

### 6.4 Collapsible Columns
**Priority:** Medium  
**Complexity:** Low  
**Implementation:**
- Add collapse/expand button to column header
- Store collapsed state
- Show card count when collapsed
- Add "Collapse All" / "Expand All" options
- Animate collapse/expand transitions

## Implementation Guidelines

### Development Approach
1. Each feature should be developed in a feature branch
2. Write tests for new models and API endpoints
3. Update API documentation for new endpoints
4. Ensure backward compatibility for database changes
5. Add feature flags for experimental features

### Testing Strategy
- Unit tests for models and business logic
- Integration tests for API endpoints
- Manual testing checklist for UI features
- Performance testing for data-heavy features

### Database Migration Strategy
- Use Flask-Migrate for managing migrations
- Always provide rollback migrations
- Test migrations with sample data
- Document migration steps

### Priority Levels
- **High**: Essential for personal productivity
- **Medium**: Nice to have, enhances experience
- **Low**: Polish and advanced features

## Next Steps
1. Review and prioritize features based on user needs
2. Create detailed technical specifications for Phase 1
3. Set up development environment with testing framework
4. Begin implementation with Multiple Boards Support

## Notes
- This roadmap is iterative and can be adjusted based on user feedback
- Each phase should be completed and tested before moving to the next
- Consider creating a beta version after each phase for testing