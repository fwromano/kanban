from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta # Added timedelta
from typing import Dict, List, Any # Added List, Any

from flask import Flask, jsonify, render_template_string, request, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import scoped_session, sessionmaker 

import logging
logging.basicConfig(level=logging.DEBUG) 

DB_URI = os.getenv("KANBAN_DB", "sqlite:///kanban.db")
PORT   = int(os.getenv("KANBAN_PORT", 5000))

app = Flask(__name__)
app.logger.setLevel(logging.DEBUG)

app.config.update(
    SQLALCHEMY_DATABASE_URI=DB_URI, 
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ECHO=False  # Set to True for verbose SQL, False for cleaner logs
)

db = SQLAlchemy()

# ────────────────────────────────────────────────────────────────────────────────
# Auto‑migrate SQLite
# ────────────────────────────────────────────────────────────────────────────────
def ensure_columns() -> None:
    if not DB_URI.startswith("sqlite:///"):
        app.logger.debug("Database is not SQLite. Skipping auto-migration.")
        return
    path = DB_URI.replace("sqlite:///", "", 1)
    if not os.path.exists(path):
        app.logger.debug(f"Database file {path} does not exist. Skipping auto-migration.")
        return
    
    app.logger.info(f"Auto-migration: Checking schema for existing SQLite database: {path}")
    needed = {
        "card": {
            "start_date": "DATE", 
            "due_date": "DATE", 
            "priority": "INTEGER DEFAULT 2",
            "is_archived": "BOOLEAN DEFAULT 0"
        },
        "board": {
            "description": "TEXT DEFAULT ''",
            "created_at": "DATETIME",
            "updated_at": "DATETIME",
            "is_active": "BOOLEAN DEFAULT 1"
        }
    }
    conn = None
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        for table_name, cols_to_add in needed.items():
            cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';")
            if not cur.fetchone():
                app.logger.warning(f"Auto-migration: Table '{table_name}' does not exist. Skipping.")
                continue
            cur.execute(f"PRAGMA table_info({table_name})")
            existing_columns = {row[1] for row in cur.fetchall()}
            for col_name, col_definition in cols_to_add.items():
                if col_name not in existing_columns:
                    app.logger.info(f"Auto-migration: Adding column '{col_name}' to '{table_name}'.")
                    cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_definition}")
        conn.commit()
        app.logger.info("Auto-migration: Schema migration commit successful.")
    except sqlite3.Error as e:
        app.logger.error(f"Auto-migration: SQLite error: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

def ensure_phase2_tables() -> None:
    """Create Phase 2 tables if they don't exist"""
    if not DB_URI.startswith("sqlite:///"):
        return
    path = DB_URI.replace("sqlite:///", "", 1)
    if not os.path.exists(path):
        return
    
    app.logger.info("Auto-migration: Checking Phase 2 tables")
    conn = None
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        
        # Check and create checklist table
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='checklist';")
        if not cur.fetchone():
            app.logger.info("Auto-migration: Creating checklist table")
            cur.execute("""
                CREATE TABLE checklist (
                    id INTEGER PRIMARY KEY,
                    card_id INTEGER NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    position INTEGER DEFAULT 0,
                    FOREIGN KEY (card_id) REFERENCES card(id)
                )
            """)
        
        # Check and create checklist_item table
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='checklist_item';")
        if not cur.fetchone():
            app.logger.info("Auto-migration: Creating checklist_item table")
            cur.execute("""
                CREATE TABLE checklist_item (
                    id INTEGER PRIMARY KEY,
                    checklist_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    is_checked BOOLEAN DEFAULT 0,
                    position INTEGER DEFAULT 0,
                    FOREIGN KEY (checklist_id) REFERENCES checklist(id)
                )
            """)
        
        # Check and create attachment table
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='attachment';")
        if not cur.fetchone():
            app.logger.info("Auto-migration: Creating attachment table")
            cur.execute("""
                CREATE TABLE attachment (
                    id INTEGER PRIMARY KEY,
                    card_id INTEGER NOT NULL,
                    filename VARCHAR(255) NOT NULL,
                    original_filename VARCHAR(255) NOT NULL,
                    file_path VARCHAR(500) NOT NULL,
                    file_size INTEGER NOT NULL,
                    mime_type VARCHAR(100) NOT NULL,
                    uploaded_at DATETIME,
                    FOREIGN KEY (card_id) REFERENCES card(id)
                )
            """)
        
        # Check and create card_template table
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='card_template';")
        if not cur.fetchone():
            app.logger.info("Auto-migration: Creating card_template table")
            cur.execute("""
                CREATE TABLE card_template (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    description TEXT,
                    template_data TEXT NOT NULL,
                    created_at DATETIME,
                    board_id INTEGER NOT NULL,
                    FOREIGN KEY (board_id) REFERENCES board(id)
                )
            """)
        
        conn.commit()
        app.logger.info("Auto-migration: Phase 2 tables created successfully")
    except sqlite3.Error as e:
        app.logger.error(f"Auto-migration: SQLite error creating Phase 2 tables: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

# ORM models
# ────────────────────────────────────────────────────────────────────────────────
class Board(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), default="My Board", nullable=False)
    description = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    columns = db.relationship("Column", backref="board", cascade="all, delete", order_by="Column.position")
    labels = db.relationship("Label", backref="board", cascade="all, delete")

class Column(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(64), nullable=False)
    position = db.Column(db.Integer, default=0)
    board_id = db.Column(db.Integer, db.ForeignKey("board.id"))
    cards = db.relationship("Card", backref="column", cascade="all, delete", order_by="Card.position") # Added order_by

class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, default="")
    position = db.Column(db.Integer, default=0)
    start_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    priority = db.Column(db.Integer, default=2) # 1:High, 2:Medium, 3:Low
    is_archived = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    column_id = db.Column(db.Integer, db.ForeignKey("column.id"))
    labels = db.relationship("Label", secondary="card_labels", backref="cards")
    checklists = db.relationship("Checklist", backref="card", cascade="all, delete-orphan", order_by="Checklist.position")
    attachments = db.relationship("Attachment", backref="card", cascade="all, delete-orphan", order_by="Attachment.uploaded_at")

class Label(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), nullable=False)
    color = db.Column(db.String(7), nullable=False) # Hex color
    board_id = db.Column(db.Integer, db.ForeignKey("board.id"))

card_labels = db.Table('card_labels',
    db.Column('card_id', db.Integer, db.ForeignKey('card.id'), primary_key=True),
    db.Column('label_id', db.Integer, db.ForeignKey('label.id'), primary_key=True)
)

# Phase 2 Models
class Checklist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('card.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    position = db.Column(db.Integer, default=0)
    items = db.relationship('ChecklistItem', backref='checklist', cascade='all, delete-orphan', order_by='ChecklistItem.position')

class ChecklistItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    checklist_id = db.Column(db.Integer, db.ForeignKey('checklist.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    is_checked = db.Column(db.Boolean, default=False)
    position = db.Column(db.Integer, default=0)

class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('card.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class CardTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    template_data = db.Column(db.Text, nullable=False)  # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    board_id = db.Column(db.Integer, db.ForeignKey('board.id'), nullable=False)

# DB init / seed
# ────────────────────────────────────────────────────────────────────────────────
with app.app_context():
    app.logger.info("Entered app_context for DB initialization.")
    ensure_columns()
    ensure_phase2_tables() 
    db.init_app(app)
    app.logger.info("SQLAlchemy initialized.")
    db.create_all()
    app.logger.info("db.create_all() completed.")

    Session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=db.engine))
    temp_session = Session()
    try:
        board_exists = temp_session.query(Board).first()
        if not board_exists:
            app.logger.info("No board found, seeding initial data.")
            board = Board(name="Kanban")
            db.session.add(board)
            db.session.flush() 
            default_columns = ["Backlog", "To Do", "In Progress", "Done"]
            for i, t in enumerate(default_columns):
                db.session.add(Column(title=t, position=i, board_id=board.id)) 
            db.session.commit()
            app.logger.info("Initial data seeded.")
        else:
            app.logger.info(f"Existing board found (ID: {board_exists.id}), skipping seed.")
    except Exception as e:
        app.logger.error(f"Error during seeding: {e}")
        temp_session.rollback() 
        db.session.rollback()   
    finally:
        Session.remove() 
    app.logger.info("Exited app_context for DB initialization.")

# Helpers
# ────────────────────────────────────────────────────────────────────────────────
PRIO_MAP = {1: "High", 2: "Medium", 3: "Low"}

def parse_date(s: str | None):
    try: return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except ValueError: return None

def card_to_dict(card: Card) -> Dict:
    return {
        "id": card.id, "title": card.title, "description": card.description,
        "position": card.position, "column_id": card.column_id,
        "start_date": card.start_date.isoformat() if card.start_date else None,
        "due_date": card.due_date.isoformat() if card.due_date else None,
        "priority": card.priority, "priority_name": PRIO_MAP.get(card.priority, "N/A"),
        "is_archived": card.is_archived,
        "labels": [label_to_dict(label) for label in card.labels],
        "checklists": [checklist_to_dict(checklist) for checklist in card.checklists],
        "attachments": [attachment_to_dict(attachment) for attachment in card.attachments]
    }

def column_to_dict(col: Column) -> Dict:
    return {
        "id": col.id, "title": col.title, "position": col.position,
        "cards": sorted([card_to_dict(c) for c in col.cards if not c.is_archived], key=lambda x: x["position"])
    }

def board_to_dict(board: Board) -> Dict:
    return {
        "id": board.id,
        "name": board.name,
        "description": board.description,
        "created_at": board.created_at.isoformat() if board.created_at else None,
        "updated_at": board.updated_at.isoformat() if board.updated_at else None,
        "is_active": board.is_active,
        "columns": sorted([column_to_dict(c) for c in board.columns], key=lambda x: x["position"]),
        "labels": [label_to_dict(label) for label in board.labels]
    }

def label_to_dict(label: Label) -> Dict:
    return {
        "id": label.id,
        "name": label.name,
        "color": label.color
    }

def checklist_to_dict(checklist: Checklist) -> Dict:
    return {
        "id": checklist.id,
        "title": checklist.title,
        "position": checklist.position,
        "items": [checklist_item_to_dict(item) for item in checklist.items]
    }

def checklist_item_to_dict(item: ChecklistItem) -> Dict:
    return {
        "id": item.id,
        "text": item.text,
        "is_checked": item.is_checked,
        "position": item.position
    }

def attachment_to_dict(attachment: Attachment) -> Dict:
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "original_filename": attachment.original_filename,
        "file_size": attachment.file_size,
        "mime_type": attachment.mime_type,
        "uploaded_at": attachment.uploaded_at.isoformat() if attachment.uploaded_at else None
    }

def card_template_to_dict(template: CardTemplate) -> Dict:
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "created_at": template.created_at.isoformat() if template.created_at else None
    }

# API routes
# ────────────────────────────────────────────────────────────────────────────────
@app.get("/api/boards")
def api_boards():
    app.logger.debug("GET /api/boards called")
    boards = Board.query.filter_by(is_active=True).all()
    return jsonify([{"id": b.id, "name": b.name, "description": b.description} for b in boards])

@app.post("/api/boards")
def api_create_board():
    app.logger.debug("POST /api/boards called")
    data = request.json or {}
    name = data.get("name", "New Board")
    description = data.get("description", "")
    
    board = Board(name=name, description=description)
    db.session.add(board)
    db.session.flush()
    
    # Add default columns
    default_columns = ["Backlog", "To Do", "In Progress", "Done"]
    for i, t in enumerate(default_columns):
        db.session.add(Column(title=t, position=i, board_id=board.id))
    
    db.session.commit()
    return jsonify(board_to_dict(board))

@app.put("/api/boards/<int:board_id>")
def api_update_board(board_id):
    app.logger.debug(f"PUT /api/boards/{board_id} called")
    board = Board.query.get_or_404(board_id)
    data = request.json or {}
    
    if "name" in data:
        board.name = data["name"]
    if "description" in data:
        board.description = data["description"]
    
    board.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(board_to_dict(board))

@app.delete("/api/boards/<int:board_id>")
def api_delete_board(board_id):
    app.logger.debug(f"DELETE /api/boards/{board_id} called")
    board = Board.query.get_or_404(board_id)
    
    # Don't delete the last board
    if Board.query.filter_by(is_active=True).count() <= 1:
        return jsonify({"error": "Cannot delete the last board"}), 400
    
    board.is_active = False
    board.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True})

@app.get("/api/board/<int:board_id>")
def api_board_data(board_id):
    app.logger.debug(f"GET /api/board/{board_id} called")
    b = Board.query.get_or_404(board_id)
    return jsonify(board_to_dict(b))

# Legacy endpoint for backward compatibility
@app.get("/api/board")
def api_board_data_legacy():
    app.logger.debug("GET /api/board called (legacy)")
    b = Board.query.first()
    if not b: return jsonify({"error": "Board not found"}), 404
    # Ensure columns are ordered by position for consistent display
    ordered_columns = sorted([column_to_dict(c) for c in b.columns], key=lambda x: x["position"])
    return jsonify({"id": b.id, "name": b.name, "columns": ordered_columns})




@app.get("/api/metrics")
def api_metrics():
    app.logger.debug("GET /api/metrics called")
    # Get current board (default to first board for legacy compatibility)
    current_board = Board.query.first()
    if not current_board:
        return jsonify({"error": "No board found"}), 404
    
    return _get_board_metrics(current_board.id)

@app.get("/api/metrics/<int:board_id>")
def api_metrics_board(board_id):
    app.logger.debug(f"GET /api/metrics/{board_id} called")
    current_board = Board.query.get(board_id)
    if not current_board:
        return jsonify({"error": "Board not found"}), 404
    
    return _get_board_metrics(board_id)

def _get_board_metrics(board_id):
    current_board = Board.query.get(board_id)
    if not current_board:
        return jsonify({"error": "Board not found"}), 404
    
    today = date.today()
    next_7_days_end = today + timedelta(days=7)

    # Filter cards by current board, excluding archived cards
    board_cards_query = Card.query.join(Column).filter(Column.board_id == current_board.id, Card.is_archived == False)
    board_columns = Column.query.filter_by(board_id=current_board.id)
    
    total_cards_count = board_cards_query.count()
    total_columns_count = board_columns.count()
    
    avg_cards_per_column = (total_cards_count / total_columns_count) if total_columns_count > 0 else 0

    priority_counts = {p_val: board_cards_query.filter(Card.priority == p_val).count() for p_val in PRIO_MAP.keys()}
    # Ensure all priorities are present in percentages, even if count is 0
    priority_percentages = {}
    for p_val, p_name in PRIO_MAP.items():
        count = priority_counts.get(p_val, 0)
        priority_percentages[p_name] = (count / total_cards_count * 100) if total_cards_count > 0 else 0

    priority_counts_named = {PRIO_MAP[p_val]: count for p_val, count in priority_counts.items()}

    overdue_cards_count = board_cards_query.filter(Card.due_date != None, Card.due_date < today).count()
    overdue_high_priority_count = board_cards_query.filter(
        Card.priority == 1, Card.due_date != None, Card.due_date < today
    ).count()
    
    cards_due_today_count = board_cards_query.filter(Card.due_date == today).count()
    cards_due_next_7_days_count = board_cards_query.filter(
        Card.due_date != None, Card.due_date >= today, Card.due_date < next_7_days_end
    ).count()

    done_column = board_columns.filter(Column.title.ilike("Done")).first()
    if not done_column: 
        done_column = board_columns.order_by(Column.position.desc()).first()

    cards_in_done_column_count = 0
    if done_column:
        cards_in_done_column_count = board_cards_query.filter(Card.column_id == done_column.id).count()
    
    active_cards_count = total_cards_count - cards_in_done_column_count
    
    all_columns = board_columns.order_by(Column.position).all()
    column_details: List[Dict[str, Any]] = []
    for col in all_columns:
        card_count_in_col = board_cards_query.filter(Card.column_id == col.id).count()
        percentage = (card_count_in_col / total_cards_count * 100) if total_cards_count > 0 else 0
        column_details.append({
            "name": col.title,
            "card_count": card_count_in_col,
            "percentage_of_total": round(percentage, 1)
        })

    return jsonify({
        "overall_stats": {
            "total_cards": total_cards_count,
            "total_columns": total_columns_count,
            "average_cards_per_column": round(avg_cards_per_column, 1),
            "active_cards": active_cards_count,
            "completed_cards": cards_in_done_column_count,
        },
        "priority_insights": { # This structure is good for a pie chart
            "labels": list(PRIO_MAP.values()), # e.g., ["High", "Medium", "Low"]
            "counts": [priority_counts.get(key, 0) for key in PRIO_MAP.keys()], # e.g., [count_high, count_med, count_low]
            "overdue_high_priority": overdue_high_priority_count, # Keep this as a separate prominent number
        },
        "due_date_insights": {
            "total_overdue": overdue_cards_count,
            "due_today": cards_due_today_count,
            "due_next_7_days": cards_due_next_7_days_count,
        },
        "column_breakdown": column_details, # Good for a bar chart
    })

@app.post("/api/column")
def api_add_column():
    app.logger.debug("POST /api/column called")
    data = request.json or {}
    title = data.get("title", "Untitled")
    board_id = data.get("board_id")
    
    # If no board_id provided, use the first board for backward compatibility
    if board_id:
        board = Board.query.get(board_id)
    else:
        board = Board.query.first()
        
    if not board:
        app.logger.warning("/api/column: Board not found")
        return jsonify({"error": "Board not found, cannot add column"}), 404
    
    max_pos = db.session.query(db.func.max(Column.position)).filter_by(board_id=board.id).scalar()
    new_pos = (max_pos + 1) if max_pos is not None else 0

    col = Column(title=title, position=new_pos, board_id=board.id) 
    db.session.add(col); db.session.commit()
    app.logger.info(f"/api/column: Column '{title}' added at position {new_pos}.")
    return jsonify(column_to_dict(col)), 201

# Label endpoints
@app.get("/api/boards/<int:board_id>/labels")
def api_get_labels(board_id):
    app.logger.debug(f"GET /api/boards/{board_id}/labels called")
    board = Board.query.get_or_404(board_id)
    return jsonify([label_to_dict(label) for label in board.labels])

@app.post("/api/boards/<int:board_id>/labels")
def api_create_label(board_id):
    app.logger.debug(f"POST /api/boards/{board_id}/labels called")
    board = Board.query.get_or_404(board_id)
    data = request.json or {}
    
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Label name is required"}), 400
    
    color = data.get("color", "#808080")  # Default gray
    if not color.startswith("#") or len(color) != 7:
        return jsonify({"error": "Color must be in hex format (#RRGGBB)"}), 400
    
    label = Label(name=name, color=color, board_id=board_id)
    db.session.add(label)
    db.session.commit()
    
    return jsonify(label_to_dict(label)), 201

@app.put("/api/labels/<int:label_id>")
def api_update_label(label_id):
    app.logger.debug(f"PUT /api/labels/{label_id} called")
    label = Label.query.get_or_404(label_id)
    data = request.json or {}
    
    if "name" in data:
        name = data["name"].strip()
        if not name:
            return jsonify({"error": "Label name cannot be empty"}), 400
        label.name = name
    
    if "color" in data:
        color = data["color"]
        if not color.startswith("#") or len(color) != 7:
            return jsonify({"error": "Color must be in hex format (#RRGGBB)"}), 400
        label.color = color
    
    db.session.commit()
    return jsonify(label_to_dict(label))

@app.delete("/api/labels/<int:label_id>")
def api_delete_label(label_id):
    app.logger.debug(f"DELETE /api/labels/{label_id} called")
    label = Label.query.get_or_404(label_id)
    db.session.delete(label)
    db.session.commit()
    return jsonify({"success": True})

# Archive endpoints
@app.get("/api/cards/archived")
def api_get_archived_cards():
    app.logger.debug("GET /api/cards/archived called")
    cards = Card.query.filter_by(is_archived=True).all()
    return jsonify([card_to_dict(card) for card in cards])

@app.post("/api/cards/<int:card_id>/archive")
def api_archive_card(card_id):
    app.logger.debug(f"POST /api/cards/{card_id}/archive called")
    card = Card.query.get_or_404(card_id)
    card.is_archived = True
    card.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(card_to_dict(card))

@app.post("/api/cards/<int:card_id>/unarchive")
def api_unarchive_card(card_id):
    app.logger.debug(f"POST /api/cards/{card_id}/unarchive called")
    card = Card.query.get_or_404(card_id)
    card.is_archived = False
    card.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(card_to_dict(card))


@app.post("/api/card")
@app.patch("/api/card/<int:cid>")
def api_card(cid: int | None = None):
    data = request.json or {}
    if request.method == "POST":
        app.logger.debug(f"POST /api/card called with data: {data}")
        column_id_val = data.get("column_id")
        if column_id_val is None: return jsonify({"error": "column_id is required"}), 400
        target_column = Column.query.get(column_id_val)
        if not target_column: return jsonify({"error": f"Column with id {column_id_val} not found"}), 404

        raw_priority = data.get("priority", "2") 
        try:
            priority_val = int(raw_priority)
            if priority_val not in PRIO_MAP.keys(): return jsonify({"error": f"Priority must be one of {list(PRIO_MAP.keys())}"}), 400
        except (ValueError, TypeError): return jsonify({"error": f"Priority must be an integer ({list(PRIO_MAP.keys())})"}), 400

        title = data.get("title", "").strip()
        if not title: title = "Untitled Card"

        max_card_pos = db.session.query(db.func.max(Card.position)).filter_by(column_id=column_id_val).scalar()
        new_card_pos = (max_card_pos + 1) if max_card_pos is not None else 0

        card = Card(
            title=title, description=data.get("description", ""), column_id=column_id_val, 
            position=new_card_pos, 
            start_date=parse_date(data.get("start_date")), due_date=parse_date(data.get("due_date")),
            priority=priority_val, 
        )
        db.session.add(card)
        db.session.flush()  # Get card ID before handling labels
        
        # Handle labels if provided
        label_ids = data.get("label_ids", [])
        if label_ids:
            labels = Label.query.filter(Label.id.in_(label_ids)).all()
            card.labels = labels
        
        db.session.commit()
        app.logger.info(f"/api/card (POST): Card '{card.title}' created with id {card.id}.")
        return jsonify(card_to_dict(card)), 201
    
    # PATCH
    app.logger.debug(f"PATCH /api/card/{cid} called with data: {data}")
    card = Card.query.get_or_404(cid)
    
    if "title" in data:
        title_val = data["title"].strip()
        if not title_val: return jsonify({"error": "Title cannot be empty"}), 400
        card.title = title_val

    if "description" in data: card.description = data["description"]
    if "column_id" in data:
        target_column_patch = Column.query.get(data["column_id"])
        if not target_column_patch: return jsonify({"error": f"Target column {data['column_id']} not found"}), 404
        card.column_id = data["column_id"]
    if "position" in data: card.position = data["position"]
            
    if "start_date" in data: card.start_date = parse_date(data["start_date"])
    if "due_date" in data: card.due_date = parse_date(data["due_date"])
        
    if "priority" in data:
        raw_priority = data["priority"]
        if raw_priority is None or str(raw_priority).strip() == "": card.priority = 2 
        else:
            try:
                priority_val = int(raw_priority)
                if priority_val not in PRIO_MAP.keys(): return jsonify({"error": f"Priority must be one of {list(PRIO_MAP.keys())}"}), 400
                card.priority = priority_val
            except (ValueError, TypeError): return jsonify({"error": f"Priority must be an integer ({list(PRIO_MAP.keys())})"}), 400
    
    # Handle labels update
    if "label_ids" in data:
        label_ids = data["label_ids"]
        if label_ids:
            labels = Label.query.filter(Label.id.in_(label_ids)).all()
            card.labels = labels
        else:
            card.labels = []
    
    db.session.commit()
    app.logger.info(f"/api/card (PATCH): Card {cid} updated.")
    return jsonify(card_to_dict(card))

@app.delete("/api/card/<int:cid>")
def api_delete_card(cid):
    app.logger.debug(f"DELETE /api/card/{cid} called")
    card = Card.query.get_or_404(cid)
    db.session.delete(card); db.session.commit()
    app.logger.info(f"/api/card (DELETE): Card {cid} deleted.")
    return "", 204

# Phase 2 API Endpoints
# ────────────────────────────────────────────────────────────────────────────────

# Checklist endpoints
@app.get("/api/cards/<int:card_id>/checklists")
def api_get_checklists(card_id):
    app.logger.debug(f"GET /api/cards/{card_id}/checklists called")
    card = Card.query.get_or_404(card_id)
    return jsonify([checklist_to_dict(checklist) for checklist in card.checklists])

@app.post("/api/cards/<int:card_id>/checklists")
def api_create_checklist(card_id):
    app.logger.debug(f"POST /api/cards/{card_id}/checklists called")
    card = Card.query.get_or_404(card_id)
    data = request.json or {}
    title = data.get("title", "New Checklist")
    position = data.get("position", len(card.checklists))
    
    checklist = Checklist(card_id=card_id, title=title, position=position)
    db.session.add(checklist)
    db.session.commit()
    
    return jsonify(checklist_to_dict(checklist)), 201

@app.put("/api/checklists/<int:checklist_id>")
def api_update_checklist(checklist_id):
    app.logger.debug(f"PUT /api/checklists/{checklist_id} called")
    checklist = Checklist.query.get_or_404(checklist_id)
    data = request.json or {}
    
    if "title" in data:
        checklist.title = data["title"]
    if "position" in data:
        checklist.position = data["position"]
    
    db.session.commit()
    return jsonify(checklist_to_dict(checklist))

@app.delete("/api/checklists/<int:checklist_id>")
def api_delete_checklist(checklist_id):
    app.logger.debug(f"DELETE /api/checklists/{checklist_id} called")
    checklist = Checklist.query.get_or_404(checklist_id)
    db.session.delete(checklist)
    db.session.commit()
    return "", 204

# Checklist item endpoints
@app.post("/api/checklists/<int:checklist_id>/items")
def api_create_checklist_item(checklist_id):
    app.logger.debug(f"POST /api/checklists/{checklist_id}/items called")
    checklist = Checklist.query.get_or_404(checklist_id)
    data = request.json or {}
    text = data.get("text", "")
    position = data.get("position", len(checklist.items))
    
    item = ChecklistItem(checklist_id=checklist_id, text=text, position=position)
    db.session.add(item)
    db.session.commit()
    
    return jsonify(checklist_item_to_dict(item)), 201

@app.put("/api/checklist-items/<int:item_id>")
def api_update_checklist_item(item_id):
    app.logger.debug(f"PUT /api/checklist-items/{item_id} called")
    item = ChecklistItem.query.get_or_404(item_id)
    data = request.json or {}
    
    if "text" in data:
        item.text = data["text"]
    if "is_checked" in data:
        item.is_checked = data["is_checked"]
    if "position" in data:
        item.position = data["position"]
    
    db.session.commit()
    return jsonify(checklist_item_to_dict(item))

@app.delete("/api/checklist-items/<int:item_id>")
def api_delete_checklist_item(item_id):
    app.logger.debug(f"DELETE /api/checklist-items/{item_id} called")
    item = ChecklistItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return "", 204

# Attachment endpoints
@app.post("/api/cards/<int:card_id>/attachments")
def api_upload_attachment(card_id):
    app.logger.debug(f"POST /api/cards/{card_id}/attachments called")
    card = Card.query.get_or_404(card_id)
    
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    # Create uploads directory if it doesn't exist
    upload_dir = "uploads"
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
    
    # Generate unique filename
    import uuid
    file_ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(upload_dir, filename)
    
    # Save file
    file.save(file_path)
    
    # Create attachment record
    attachment = Attachment(
        card_id=card_id,
        filename=filename,
        original_filename=file.filename,
        file_path=file_path,
        file_size=os.path.getsize(file_path),
        mime_type=file.content_type or 'application/octet-stream'
    )
    db.session.add(attachment)
    db.session.commit()
    
    return jsonify(attachment_to_dict(attachment)), 201

@app.get("/api/attachments/<int:attachment_id>/download")
def api_download_attachment(attachment_id):
    app.logger.debug(f"GET /api/attachments/{attachment_id}/download called")
    attachment = Attachment.query.get_or_404(attachment_id)
    
    if not os.path.exists(attachment.file_path):
        return jsonify({"error": "File not found"}), 404
    
    return send_file(
        attachment.file_path,
        as_attachment=True,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type
    )

@app.delete("/api/attachments/<int:attachment_id>")
def api_delete_attachment(attachment_id):
    app.logger.debug(f"DELETE /api/attachments/{attachment_id} called")
    attachment = Attachment.query.get_or_404(attachment_id)
    
    # Delete file from disk
    if os.path.exists(attachment.file_path):
        os.remove(attachment.file_path)
    
    db.session.delete(attachment)
    db.session.commit()
    return "", 204

# Card template endpoints
@app.get("/api/boards/<int:board_id>/templates")
def api_get_card_templates(board_id):
    app.logger.debug(f"GET /api/boards/{board_id}/templates called")
    board = Board.query.get_or_404(board_id)
    templates = CardTemplate.query.filter_by(board_id=board_id).all()
    return jsonify([card_template_to_dict(template) for template in templates])

@app.post("/api/boards/<int:board_id>/templates")
def api_create_card_template(board_id):
    app.logger.debug(f"POST /api/boards/{board_id}/templates called")
    board = Board.query.get_or_404(board_id)
    data = request.json or {}
    
    name = data.get("name", "New Template")
    description = data.get("description", "")
    template_data = data.get("template_data", "{}")
    
    template = CardTemplate(
        name=name,
        description=description,
        template_data=template_data,
        board_id=board_id
    )
    db.session.add(template)
    db.session.commit()
    
    return jsonify(card_template_to_dict(template)), 201

@app.delete("/api/templates/<int:template_id>")
def api_delete_card_template(template_id):
    app.logger.debug(f"DELETE /api/templates/{template_id} called")
    template = CardTemplate.query.get_or_404(template_id)
    db.session.delete(template)
    db.session.commit()
    return "", 204

@app.post("/api/templates/<int:template_id>/create-card")
def api_create_card_from_template(template_id):
    app.logger.debug(f"POST /api/templates/{template_id}/create-card called")
    template = CardTemplate.query.get_or_404(template_id)
    data = request.json or {}
    
    column_id = data.get("column_id")
    if not column_id:
        return jsonify({"error": "column_id is required"}), 400
    
    # Parse template data
    import json
    template_data = json.loads(template.template_data)
    
    # Create card from template
    card = Card(
        title=template_data.get("title", "New Card"),
        description=template_data.get("description", ""),
        priority=template_data.get("priority", 2),
        column_id=column_id
    )
    db.session.add(card)
    db.session.commit()
    
    # Create checklists from template
    for checklist_data in template_data.get("checklists", []):
        checklist = Checklist(
            card_id=card.id,
            title=checklist_data["title"],
            position=checklist_data["position"]
        )
        db.session.add(checklist)
        db.session.commit()
        
        # Create checklist items
        for item_data in checklist_data.get("items", []):
            item = ChecklistItem(
                checklist_id=checklist.id,
                text=item_data["text"],
                position=item_data["position"]
            )
            db.session.add(item)
    
    db.session.commit()
    return jsonify(card_to_dict(card)), 201

# TEMPLATE
# ────────────────────────────────────────────────────────────────────────────────
TEMPLATE = r"""
<!DOCTYPE html><html lang='en'><head>
<meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{{ board_name }} – Kanban</title>
<link rel='preconnect' href='https://fonts.googleapis.com'>
<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap' rel='stylesheet'>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#f9fafb;--surface:#fff;--text:#111827;--muted:#6b7280;--card-bg:#f3f4f6;--high:#ef4444;--med:#f59e0b;--low:#10b981; --overlay-bg: rgba(0,0,0,0.5); --modal-bg: var(--surface); --input-bg: var(--card-bg); --button-primary-bg: #2563eb; --button-primary-text: #fff; --button-secondary-bg: var(--card-bg); --button-secondary-text: var(--text); --border-color: #e5e7eb; --shadow-sm: 0 1px 2px 0 rgba(0,0,0,.05); --shadow-md: 0 4px 6px -1px rgba(0,0,0,.1),0 2px 4px -2px rgba(0,0,0,.1); --shadow-lg: 0 10px 15px -3px rgba(0,0,0,.1),0 4px 6px -4px rgba(0,0,0,.1); --hover-bg: rgba(0,0,0,0.05); --primary: #2563eb; --primary-text: #ffffff; --error-color: #ef4444;
--chart-high-prio: var(--high); --chart-medium-prio: var(--med); --chart-low-prio: var(--low); --chart-bar-bg: #60a5fa; --chart-grid-color: rgba(0,0,0,0.05);}
[data-theme=dark]{--bg:#111827;--surface:#1f2937;--text:#f3f4f6;--muted:#9ca3af;--card-bg:#374151; --modal-bg: #1f2937; --input-bg: #374151; --button-secondary-bg: #374151; --border-color: #374151; --hover-bg: rgba(255,255,255,0.1); --primary: #3b82f6; --primary-text: #ffffff; --error-color: #f87171;
--chart-high-prio: #f87171; --chart-medium-prio: #fbbf24; --chart-low-prio: #34d399; --chart-bar-bg: #3b82f6; --chart-grid-color: rgba(255,255,255,0.1);}
html,body{height:100%;margin:0;font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--text);font-size:16px;line-height:1.5;}
body{display:flex;flex-direction:column;}
/* Header Layout */
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1.5rem;
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  border-bottom: 1px solid var(--border-color);
  min-height: 3.5rem;
  flex-wrap: wrap;
  gap: 1rem;
}

header h1 {
  font-size: 1.25rem;
  font-weight: 600;
  margin: 0;
  color: var(--text);
}

/* Responsive header adjustments */
@media (max-width: 768px) {
  header {
    padding: 0.5rem 1rem;
    flex-direction: column;
    align-items: stretch;
    gap: 0.75rem;
  }
  
  .board-switcher {
    justify-content: center;
  }
  
  #appControls {
    justify-content: center;
    flex-wrap: wrap;
  }
  
  .board {
    padding: 0.5rem;
    gap: 0.5rem;
  }
  
  .column {
    min-width: 280px;
    max-width: 300px;
  }
  
  #dashboardArea {
    padding: 0.5rem;
    grid-template-columns: 1fr;
  }
  
  #calendarContainer {
    padding: 0.5rem;
  }
}

/* Extra small screens */
@media (max-width: 480px) {
  .board {
    padding: 0.25rem;
  }
  
  .column {
    min-width: 250px;
    max-width: 270px;
  }
  
  #dashboardArea {
    padding: 0.25rem;
  }
  
  .filter-bar {
    flex-direction: column;
    align-items: stretch;
  }
  
  .filter-bar input,
  .filter-bar select {
    width: 100%;
  }
}

/* Minimal dashboard for narrow windows */
@media (max-width: 800px) {
  #dashboardArea {
    grid-template-columns: 1fr 1fr; /* Only 2 columns max */
  }
  
  .dash-section h3 {
    display: none; /* Hide section titles */
  }
  
  .dash-metric .label {
    display: none; /* Hide metric labels */
  }
  
  .dash-metric {
    justify-content: center;
    font-size: 1rem;
    font-weight: 600;
  }
}

@media (max-width: 600px) {
  #dashboardArea {
    gap: 1rem;
    padding: 0.5rem;
  }
  
  .dash-stat {
    min-width: 60px;
  }
  
  .dash-stat-value {
    font-size: 1.25rem;
  }
  
  .dash-stat-label {
    font-size: 0.625rem;
  }
  
  .dash-separator {
    display: none;
  }
}

/* Single column mode for small windows */
.board.small-mode {
  flex-direction: column;
}

.board.small-mode .column {
  display: none;
  min-width: 100%;
  max-width: 100%;
  margin-bottom: 1rem;
}

.board.small-mode .column.active {
  display: flex;
}

/* Column navigation */
.column-nav {
  display: none;
  position: sticky;
  top: 0;
  background: var(--surface);
  padding: 0.5rem;
  border-radius: 0.375rem;
  margin-bottom: 0.5rem;
  box-shadow: var(--shadow-sm);
  z-index: 10;
}

.board.small-mode .column-nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.column-nav-title {
  font-weight: 600;
  font-size: 0.875rem;
}

.column-nav-buttons {
  display: flex;
  gap: 0.25rem;
}

.column-nav-btn {
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
  border: 1px solid var(--border-color);
  background: var(--surface);
  border-radius: 0.25rem;
  cursor: pointer;
}

.column-nav-btn:hover {
  background: var(--card-bg);
}

.column-nav-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
/* Main content wrapper */
.main-content{display:flex;flex-direction:column;flex:1;min-height:0;}
.board{display:flex;gap:1rem;padding:1rem;overflow-x:auto;flex:1;min-height:0;}
.column{background:var(--surface);border-radius:.5rem;display:flex;flex-direction:column;min-width:300px;max-width:320px;max-height:100%; box-shadow: var(--shadow-md);}
.column-header{display:flex;align-items:center;justify-content:space-between;padding:.75rem 1rem;border-bottom:1px solid var(--border-color);font-weight:600; font-size: 1rem;}
.cards{flex:1;overflow-y:auto;display:flex;flex-direction:column;padding:.75rem;gap:.75rem}
.card{background:var(--card-bg);border-radius:.5rem;padding:1rem;cursor:pointer; box-shadow: var(--shadow-sm); transition: box-shadow 0.2s ease-in-out;}
.card:hover{box-shadow: var(--shadow-md);}
.card strong { display: block; margin-bottom: 0.25rem; font-weight: 600;}
.card p {font-size:0.875rem; margin:0.25rem 0; color:var(--muted); line-height:1.4;}
.card .meta { font-size: 0.75rem; color: var(--muted); margin-top: 0.5rem; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;}
.card[data-prio="1"]{border-left:4px solid var(--high)}
.card[data-prio="2"]{border-left:4px solid var(--med)}
.card[data-prio="3"]{border-left:4px solid var(--low)}
/* Base Button Styles */
button {
  font-family: inherit;
  border-radius: 0.375rem;
  cursor: pointer;
  border: 1px solid transparent;
  font-weight: 500;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  text-decoration: none;
  outline: none;
  font-size: 0.875rem;
  padding: 0.5rem 1rem;
  height: 2.5rem;
  min-width: 2.5rem;
  gap: 0.5rem;
}

/* Button Size Variants */
.btn-xs {
  padding: 0.125rem 0.5rem;
  font-size: 0.75rem;
  line-height: 1.25;
}

.btn-sm {
  padding: 0.375rem 0.75rem;
  font-size: 0.875rem;
  line-height: 1.25;
}

.btn-md {
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  line-height: 1.25;
}

.btn-lg {
  padding: 0.75rem 1.5rem;
  font-size: 1rem;
  line-height: 1.25;
}

/* Button Style Variants */
.btn-primary {
  background-color: var(--button-primary-bg);
  color: var(--button-primary-text);
  border-color: var(--button-primary-bg);
}

.btn-primary:hover {
  background-color: #1d4ed8;
  border-color: #1d4ed8;
  box-shadow: var(--shadow-sm);
}

.btn-primary:active {
  background-color: #1e40af;
  border-color: #1e40af;
  transform: translateY(1px);
}

.btn-secondary {
  background-color: var(--button-secondary-bg);
  color: var(--button-secondary-text);
  border: 1px solid var(--border-color);
}

.btn-secondary:hover {
  background-color: var(--card-bg);
  border-color: var(--muted);
  box-shadow: var(--shadow-sm);
}

.btn-secondary:active {
  background-color: var(--border-color);
  transform: translateY(1px);
}

.btn-outline {
  background-color: transparent;
  color: var(--text);
  border: 1px solid var(--muted);
}

.btn-outline:hover {
  background-color: var(--card-bg);
  border-color: var(--text);
}

.btn-ghost {
  background-color: transparent;
  color: var(--muted);
  border: 1px solid transparent;
}

.btn-ghost:hover {
  background-color: var(--card-bg);
  color: var(--text);
}

.btn-danger {
  background-color: #dc2626;
  color: white;
  border-color: #dc2626;
}

.btn-danger:hover {
  background-color: #b91c1c;
  border-color: #b91c1c;
}

/* Button Focus States */
button:focus-visible {
  box-shadow: 0 0 0 2px var(--button-primary-bg), 0 0 0 4px rgba(37, 99, 235, 0.2);
}

/* Button Disabled States */
button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
}

button:disabled:hover {
  background-color: inherit;
  border-color: inherit;
  box-shadow: none;
}

/* Button Loading State */
button.loading {
  position: relative;
  color: transparent;
  pointer-events: none;
}

button.loading::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 1rem;
  height: 1rem;
  margin: -0.5rem 0 0 -0.5rem;
  border: 2px solid transparent;
  border-top: 2px solid currentColor;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  color: inherit;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

/* Icon Buttons */
.btn-icon {
  padding: 0.5rem;
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 0.375rem;
}

.btn-icon-sm {
  padding: 0.25rem;
  width: 2rem;
  height: 2rem;
}

/* Specific Button Overrides */
.add-card-btn {
  font-size: 1.125rem;
  border: none;
  background: none;
  cursor: pointer;
  color: var(--muted);
  padding: 0.25rem 0.5rem;
  line-height: 1;
  border-radius: 0.375rem;
  transition: all 0.2s ease;
  width: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.add-card-btn:hover {
  background: var(--card-bg);
  color: var(--text);
}

/* Header Button Styles */
#appControls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

#appControls button {
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
  height: 2.5rem;
  min-width: 2.5rem;
}

#addColBtn {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--muted);
}

#addColBtn:hover {
  background: var(--card-bg);
  border-color: var(--text);
}

#themeToggle {
  background: transparent;
  color: var(--muted);
  border: 1px solid transparent;
  font-size: 1.125rem;
  padding: 0.5rem;
  width: 2.5rem;
  height: 2.5rem;
}

#themeToggle:hover {
  background: var(--card-bg);
  color: var(--text);
}

#viewArchivedBtn {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--muted);
}

#viewArchivedBtn:hover {
  background: var(--card-bg);
  border-color: var(--text);
}

#keyboardShortcutsBtn {
  background: transparent;
  color: var(--muted);
  border: 1px solid transparent;
  font-size: 1.125rem;
  padding: 0.5rem;
  width: 2.5rem;
  height: 2.5rem;
}

#keyboardShortcutsBtn:hover {
  background: var(--card-bg);
  color: var(--text);
}

/* Filter Bar */
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding: 0.75rem 1.5rem;
  background: var(--surface);
  border-bottom: 1px solid var(--border-color);
  align-items: center;
}

.filter-bar input,
.filter-bar select {
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  border: 1px solid var(--muted);
  background: var(--input-bg);
  color: var(--text);
  font-size: 0.875rem;
  height: 2.5rem;
  box-sizing: border-box;
}

.filter-bar label {
  font-size: 0.875rem;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 0.5rem;
  white-space: nowrap;
}

#clearFilterBtn {
  background: var(--input-bg);
  color: var(--text);
  border: 1px solid var(--muted);
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
  height: 2.5rem;
}

#clearFilterBtn:hover {
  background: var(--card-bg);
  border-color: var(--text);
}

/* Responsive filter bar */
@media (max-width: 768px) {
  .filter-bar {
    padding: 0.5rem 1rem;
    gap: 0.5rem;
  }
  
  .filter-bar input,
  .filter-bar select {
    min-width: 120px;
  }
  
  .filter-bar label {
    font-size: 0.8rem;
  }
}

/* Compact Dashboard */
#dashboardArea { 
  padding: 0.75rem 1rem; 
  background: var(--surface); 
  border-bottom: 1px solid var(--border-color); 
  display: flex; 
  justify-content: space-between; 
  align-items: center; 
  gap: 2rem; 
  flex-wrap: wrap;
  min-height: 60px;
}

/* Responsive dashboard adjustments */
@media (max-width: 768px) {
  #dashboardArea {
    gap: 1rem;
    padding: 0.5rem;
  }
  
  .dashboard-mode-selector {
    margin-left: 0;
    margin-top: 0.5rem;
  }
  
  .dash-stat {
    min-width: 60px;
  }
  
  .dash-stat-value {
    font-size: 1.25rem;
  }
  
  .dash-stat-label {
    font-size: 0.65rem;
  }
  
  .dashboard-charts {
    height: 150px !important;
    flex-direction: column;
  }
}

/* Small mode dashboard */
.small-mode #dashboardArea {
  padding: 0.5rem;
  gap: 1rem;
}

.small-mode .dashboard-mode-selector {
  display: none;
}

.small-mode .dash-stat {
  min-width: 50px;
}

.small-mode .dash-stat-value {
  font-size: 1.1rem;
}

.small-mode .dash-stat-label {
  font-size: 0.6rem;
}

.small-mode .dashboard-charts {
  display: none;
}

.dash-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  min-width: 80px;
}

.dash-stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.2;
  margin-bottom: 0.25rem;
}

.dash-stat-label {
  font-size: 0.75rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.dash-stat-action {
  font-size: 0.65rem;
  color: var(--primary);
  margin-top: 0.25rem;
  opacity: 0;
  transition: opacity 0.2s ease;
}

.dash-stat.clickable:hover .dash-stat-action {
  opacity: 1;
}

.dash-stat.urgent .dash-stat-value {
  color: var(--high);
}

.dash-stat.warning .dash-stat-value {
  color: var(--med);
}

.dash-stat.success .dash-stat-value {
  color: var(--low);
}

.dash-separator {
  width: 1px;
  height: 30px;
  background: var(--border-color);
  opacity: 0.5;
}

/* Clickable stats */
.dash-stat.clickable {
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  border-radius: 4px;
  padding: 0.5rem;
  margin: -0.5rem;
}

.dash-stat.clickable:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0,0,0,0.1);
  background: var(--hover-bg);
}

.dash-stat.clickable:active {
  transform: translateY(0);
}

/* Dashboard charts styling */
.dashboard-charts {
  margin-top: 15px;
  display: flex;
  gap: 20px;
  height: 180px;
}

.dashboard-charts > div {
  flex: 1;
  position: relative;
}

/* Clean up old dashboard elements */
.dash-section { display: none; }
.chart-container { display: none; }
.bar-chart-container { display: none; }


/* Modal Styles */
.modal-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:var(--overlay-bg);display:none;align-items:center;justify-content:center;z-index:1000;padding:1rem;}
.modal{background:var(--modal-bg);padding:1.5rem;border-radius:.5rem;box-shadow:var(--shadow-lg);width:100%;max-width:800px; color: var(--text);max-height:90vh;overflow-y:auto;}
.modal h2{margin-top:0;margin-bottom:1.5rem;font-size:1.25rem; font-weight:600;}
.modal-form label{display:block;margin-bottom:.25rem;font-size:.875rem;font-weight:500;color:var(--muted);}
.modal-form input[type="text"],.modal-form textarea,.modal-form select,.modal-form input[type="date"]{width:100%;padding:.625rem .75rem;margin-bottom:.75rem;border-radius:.375rem;border:1px solid var(--muted);background:var(--input-bg);color:var(--text);font-family:inherit;box-sizing:border-box;font-size:0.875rem;}
.modal-form textarea{min-height:100px;resize:vertical;}
.modal-form input:focus, .modal-form textarea:focus, .modal-form select:focus {border-color: var(--button-primary-bg); box-shadow: 0 0 0 2px rgba(37,99,235,.2); outline:none;}
/* Modal Actions */
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1.5rem;
  flex-wrap: wrap;
}

.modal-actions button {
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  min-width: 5rem;
  height: 2.5rem;
}

.modal-actions button.primary {
  background-color: var(--button-primary-bg);
  color: var(--button-primary-text);
  border-color: var(--button-primary-bg);
}

.modal-actions button.primary:hover {
  background-color: #1d4ed8;
  border-color: #1d4ed8;
  box-shadow: var(--shadow-sm);
}

.modal-actions button.secondary {
  background-color: var(--button-secondary-bg);
  color: var(--button-secondary-text);
  border: 1px solid var(--border-color);
}

.modal-actions button.secondary:hover {
  background-color: var(--card-bg);
  border-color: var(--muted);
  box-shadow: var(--shadow-sm);
}

/* Modal responsive adjustments */
@media (max-width: 768px) {
  .modal {
    margin: 1rem;
    padding: 1rem;
  }
  
  .modal-actions {
    flex-direction: column-reverse;
    gap: 0.5rem;
  }
  
  .modal-actions button {
    width: 100%;
    justify-content: center;
  }
}

/* Board Switcher Styles */
.board-switcher {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.board-select {
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  border: 1px solid var(--muted);
  background: var(--input-bg);
  color: var(--text);
  font-size: 0.875rem;
  min-width: 150px;
  height: 2.5rem;
  box-sizing: border-box;
}

#newBoardBtn {
  font-size: 0.875rem;
  padding: 0.5rem 0.75rem;
  height: 2.5rem;
  background-color: var(--button-primary-bg);
  color: var(--button-primary-text);
  border-color: var(--button-primary-bg);
}

#newBoardBtn:hover {
  background-color: #1d4ed8;
  border-color: #1d4ed8;
  box-shadow: var(--shadow-sm);
}

/* Labels Styles */
.card-labels{display:flex;gap:0.25rem;flex-wrap:wrap;margin-top:0.5rem;}
.label{display:inline-flex;align-items:center;padding:0.125rem 0.5rem;border-radius:0.25rem;font-size:0.75rem;font-weight:500;color:#fff;}
.label-picker{display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.75rem;}
.label-picker .label-option{display:flex;align-items:center;gap:0.25rem;padding:0.25rem;cursor:pointer;border-radius:0.25rem;}
.label-picker .label-option:hover{background:var(--card-bg);}
.label-picker input[type="checkbox"]{margin:0;}
#manageLabelsBtnEl {
  font-size: 0.75rem;
  padding: 0.375rem 0.75rem;
  margin-top: 0.5rem;
  height: 2rem;
  background-color: var(--button-secondary-bg);
  color: var(--button-secondary-text);
  border: 1px solid var(--border-color);
}

#manageLabelsBtnEl:hover {
  background-color: var(--card-bg);
  border-color: var(--muted);
}

/* Archive Styles */
.archived-banner {
  background: var(--muted);
  color: var(--surface);
  padding: 0.5rem 1rem;
  text-align: center;
  font-size: 0.875rem;
}

.archive-btn {
  font-size: 0.75rem;
  padding: 0.375rem 0.75rem;
  margin-top: 0.5rem;
  height: 2rem;
  background: #dc2626;
  color: white;
  border: 1px solid #dc2626;
}

.archive-btn:hover {
  background: #b91c1c;
  border-color: #b91c1c;
}

/* Keyboard Shortcuts Modal */
.shortcuts-grid{display:grid;grid-template-columns:auto 1fr;gap:0.5rem 1rem;}
.shortcut-key{background:var(--card-bg);padding:0.25rem 0.5rem;border-radius:0.25rem;font-family:monospace;font-size:0.875rem;font-weight:600;}

/* Phase 2 UI Styles */
/* Checklist Styles */
.checklist {
  background: var(--card-bg);
  border-radius: 0.375rem;
  padding: 0.75rem;
  margin-bottom: 0.5rem;
  border: 1px solid var(--border-color);
}

.checklist-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.checklist-title {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--text);
}

.checklist-progress {
  font-size: 0.75rem;
  color: var(--muted);
}

.checklist-items {
  margin-bottom: 0.5rem;
}

.checklist-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0;
  border-bottom: 1px solid var(--border-color);
}

.checklist-item:last-child {
  border-bottom: none;
}

.checklist-item input[type="checkbox"] {
  margin: 0;
  width: auto;
}

.checklist-item-text {
  flex: 1;
  font-size: 0.875rem;
  color: var(--text);
}

.checklist-item-text.completed {
  text-decoration: line-through;
  color: var(--muted);
}

.checklist-item-actions {
  display: flex;
  gap: 0.25rem;
}

.checklist-add-item {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.checklist-add-item input {
  flex: 1;
  padding: 0.25rem 0.5rem;
  font-size: 0.875rem;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  background: var(--input-bg);
  color: var(--text);
}

/* Attachment Styles */
.attachment {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem;
  background: var(--card-bg);
  border-radius: 0.375rem;
  margin-bottom: 0.5rem;
  border: 1px solid var(--border-color);
}

.attachment-icon {
  width: 24px;
  height: 24px;
  background: var(--muted);
  border-radius: 0.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  color: white;
}

.attachment-info {
  flex: 1;
}

.attachment-name {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text);
}

.attachment-meta {
  font-size: 0.75rem;
  color: var(--muted);
}

.attachment-actions {
  display: flex;
  gap: 0.25rem;
}

/* Template Styles */
.template-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.template-option {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  padding: 0.5rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.template-option:hover {
  background: var(--surface);
  border-color: var(--button-primary-bg);
}

.template-option.selected {
  background: var(--button-primary-bg);
  color: var(--button-primary-text);
  border-color: var(--button-primary-bg);
}

/* Progress indicators */
.progress-bar {
  width: 100%;
  height: 4px;
  background: var(--border-color);
  border-radius: 2px;
  overflow: hidden;
  margin-top: 0.5rem;
}

.progress-fill {
  height: 100%;
  background: var(--button-primary-bg);
  transition: width 0.3s ease;
}

/* Card preview enhancements */
.card-checklist-preview {
  font-size: 0.75rem;
  color: var(--muted);
  margin-top: 0.25rem;
}

.card-attachment-preview {
  font-size: 0.75rem;
  color: var(--muted);
  margin-top: 0.25rem;
}

/* Multi-column layout for card modal */
.modal-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
  margin-bottom: 1rem;
}

.modal-column {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.modal-full-width {
  grid-column: 1 / -1;
}

/* Phase 2 sections styling */
#checklistsSection, #attachmentsSection, #templatesSection {
  border-top: 1px solid var(--border-color);
  padding-top: 1rem;
  margin-top: 1rem;
}

@media (max-width: 768px) {
  .modal-columns {
    grid-template-columns: 1fr;
    gap: 1rem;
  }
}

/* Group headers for filtering */
.group-header {
  background: var(--surface);
  padding: 0.5rem 0.75rem;
  margin: 0.5rem 0;
  border-radius: 0.375rem;
  border-left: 3px solid var(--button-primary-bg);
  font-size: 0.875rem;
  color: var(--muted);
}

/* Calendar View Styles */
#calendarContainer {
  padding: 1rem;
  background: var(--bg);
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.calendar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  padding: 0.75rem;
  background: var(--surface);
  border-radius: 0.5rem;
}

.calendar-nav {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 1px;
  background: var(--border-color);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  overflow: hidden;
}

.calendar-day-header {
  background: var(--surface);
  padding: 0.75rem;
  text-align: center;
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--muted);
}

.calendar-day {
  background: var(--card-bg);
  min-height: 100px;
  padding: 0.5rem;
  position: relative;
  cursor: pointer;
  transition: background 0.2s;
}

.calendar-day:hover {
  background: var(--surface);
}

.calendar-day-number {
  font-size: 0.875rem;
  font-weight: 500;
  margin-bottom: 0.25rem;
}

.calendar-day.other-month .calendar-day-number {
  color: var(--muted);
}

.calendar-day.today {
  background: var(--surface);
  border: 2px solid var(--button-primary-bg);
}

.calendar-card {
  background: var(--surface);
  border-radius: 0.25rem;
  padding: 0.25rem 0.5rem;
  margin: 0.125rem 0;
  font-size: 0.75rem;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: all 0.2s;
}

.calendar-card[data-prio="1"] {
  border-left-color: var(--high);
}

.calendar-card[data-prio="2"] {
  border-left-color: var(--med);
}

.calendar-card[data-prio="3"] {
  border-left-color: var(--low);
}

.calendar-card:hover {
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

/* Quick Add Card Styles */
.quick-add-container {
  margin-bottom: 0.5rem;
  padding: 0.5rem;
  background: var(--surface);
  border-radius: 0.375rem;
  display: none;
}

.quick-add-container.active {
  display: block;
}

.quick-add-input {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  background: var(--input-bg);
  color: var(--text);
  font-size: 0.875rem;
}

.quick-add-hint {
  font-size: 0.75rem;
  color: var(--muted);
  margin-top: 0.25rem;
}

/* Bulk Operations Styles */
.bulk-select-mode .card {
  position: relative;
  padding-left: 2rem;
}

.bulk-select-checkbox {
  position: absolute;
  left: 0.5rem;
  top: 0.75rem;
  display: none;
}

.bulk-select-mode .bulk-select-checkbox {
  display: block;
}

.bulk-actions-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: var(--surface);
  border-top: 1px solid var(--border-color);
  padding: 1rem;
  display: none;
  align-items: center;
  justify-content: space-between;
  box-shadow: var(--shadow-lg);
  z-index: 100;
}

.bulk-actions-bar.active {
  display: flex;
}

.bulk-actions-count {
  font-weight: 500;
}

.bulk-actions-buttons {
  display: flex;
  gap: 0.5rem;
}

/* Template Select Styles */
.template-select {
  width: 100%;
  padding: 0.625rem 0.75rem;
  margin-bottom: 0.75rem;
  border-radius: 0.375rem;
  border: 1px solid var(--muted);
  background: var(--input-bg);
  color: var(--text);
  font-family: inherit;
  box-sizing: border-box;
  font-size: 0.875rem;
}
</style></head><body>
<header>
  <div class="board-switcher">
    <select id="boardSelect" class="board-select">
      <!-- Boards will be loaded here -->
    </select>
    <button id="newBoardBtn" class="btn-primary">＋ Board</button>
  </div>
  <div id="appControls">
    <button id='addColBtn' class="btn-secondary">＋ Column</button>
    <button id='viewArchivedBtn' class="btn-secondary">📦 Archive</button>
    <button id='toggleViewBtn' class="btn-secondary">📅 Calendar</button>
    <button id='themeToggle' class="btn-ghost" aria-label='Toggle theme'>🌓</button>
  </div>
</header>

<div id="dashboardArea">
  </div>

<div class="main-content">
  <div class='filter-bar'>
    <input id='searchInput' placeholder='Search cards…'>
    <select id='prioFilterSelect'>
      <option value=''>All Priorities</option><option value='1'>High</option><option value='2'>Medium</option><option value='3'>Low</option>
    </select>
    <select id='labelFilterSelect'>
      <option value=''>All Labels</option>
      <!-- Labels will be populated here -->
    </select>
    <label>Start: <input type='date' id='startFromInput'></label>
    <label>Due: <input type='date' id='endToInput'></label>
    <select id='sortSelect'>
      <option value=''>Default Order</option>
      <option value='priority'>Sort by Priority</option>
      <option value='due_date'>Sort by Due Date</option>
      <option value='start_date'>Sort by Start Date</option>
      <option value='title'>Sort by Title</option>
      <option value='created'>Sort by Created Date</option>
    </select>
    <select id='groupBySelect'>
      <option value=''>No Grouping</option>
      <option value='priority'>Group by Priority</option>
      <option value='labels'>Group by Labels</option>
      <option value='due_date'>Group by Due Date</option>
    </select>
    <button id='clearFilterBtn' class="btn-secondary">✕ Clear</button>
  </div>
  <main class='board' id='boardContainer'></main>
  <div id='calendarContainer' style='display: none;'></div>
</div>

<!-- Bulk Actions Bar -->
<div id="bulkActionsBar" class="bulk-actions-bar">
  <div class="bulk-actions-count">
    <span id="bulkSelectCount">0</span> cards selected
  </div>
  <div class="bulk-actions-buttons">
    <button id="bulkMoveBtn" class="btn-secondary">Move to Column</button>
    <button id="bulkPriorityBtn" class="btn-secondary">Set Priority</button>
    <button id="bulkLabelBtn" class="btn-secondary">Add/Remove Labels</button>
    <button id="bulkArchiveBtn" class="btn-secondary">Archive</button>
    <button id="bulkCancelBtn" class="btn-ghost">Cancel</button>
  </div>
</div>

<div id="cardModalOverlay" class="modal-overlay">
  <div class="modal">
    <h2 id="cardModalTitleEl">Create Card</h2>
    <form id="cardModalFormEl" class="modal-form">
      <input type="hidden" id="cardModalIdField">
      <input type="hidden" id="cardModalColumnIdField">
      
      <!-- Template Picker for New Cards -->
      <div id="templatePicker" style="display: none; margin-bottom: 1rem;">
        <label>Use Template</label>
        <select id="templateSelect" class="template-select">
          <option value="">-- No Template --</option>
        </select>
      </div>
      
      <div class="modal-columns">
        <div class="modal-column">
          <div>
            <label for="cardTitleField">Title</label>
            <input type="text" id="cardTitleField" name="title" required>
          </div>
          <div>
            <label for="cardPriorityField">Priority</label>
            <select id="cardPriorityField" name="priority">
              <option value="1">High</option>
              <option value="2" selected>Medium</option>
              <option value="3">Low</option>
            </select>
          </div>
          <div>
            <label for="cardStartDateField">Start Date</label>
            <input type="date" id="cardStartDateField" name="start_date">
          </div>
          <div>
            <label for="cardDueDateField">Due Date</label>
            <input type="date" id="cardDueDateField" name="due_date">
          </div>
        </div>
        
        <div class="modal-column">
          <div>
            <label for="cardDescriptionField">Description</label>
            <textarea id="cardDescriptionField" name="description"></textarea>
          </div>
          <div>
            <label>Labels</label>
            <div id="labelPicker" class="label-picker">
              <!-- Labels will be loaded here -->
            </div>
            <button type="button" id="manageLabelsBtnEl" class="btn-secondary">Manage Labels</button>
          </div>
        </div>
      </div>
      
      <!-- Checklists Section -->
      <div id="checklistsSection" style="display: none;">
        <label>Checklists</label>
        <div id="checklistsContainer">
          <!-- Checklists will be loaded here -->
        </div>
        <button type="button" id="addChecklistBtn" class="btn-secondary btn-sm">+ Add Checklist</button>
      </div>
      
      <!-- Attachments Section -->
      <div id="attachmentsSection" style="display: none;">
        <label>Attachments</label>
        <div id="attachmentsContainer">
          <!-- Attachments will be loaded here -->
        </div>
        <input type="file" id="attachmentInput" multiple style="display: none;">
        <button type="button" id="addAttachmentBtn" class="btn-secondary btn-sm">+ Add Attachment</button>
      </div>
      
      <!-- Templates Section -->
      <div id="templatesSection" style="display: none;">
        <label>Save as Template</label>
        <button type="button" id="saveAsTemplateBtn" class="btn-secondary btn-sm">Save as Template</button>
      </div>
      
      <div class="modal-actions">
        <button type="button" id="cancelCardModalBtnEl" class="btn-secondary">Cancel</button>
        <button type="button" id="archiveCardBtnEl" class="btn-danger" style="display:none;">Archive</button>
        <button type="submit" id="saveCardModalBtnEl" class="btn-primary">Save Card</button>
      </div>
    </form>
  </div>
</div>

<!-- Board Modal -->
<div id="boardModalOverlay" class="modal-overlay">
  <div class="modal">
    <h2 id="boardModalTitle">New Board</h2>
    <form id="boardModalForm" class="modal-form">
      <input type="hidden" id="boardModalIdField">
      <div>
        <label for="boardNameField">Name</label>
        <input type="text" id="boardNameField" name="name" required>
      </div>
      <div>
        <label for="boardDescriptionField">Description</label>
        <textarea id="boardDescriptionField" name="description"></textarea>
      </div>
      <div class="modal-actions">
        <button type="button" id="cancelBoardModalBtn" class="btn-secondary">Cancel</button>
        <button type="submit" id="saveBoardModalBtn" class="btn-primary">Save Board</button>
      </div>
    </form>
  </div>
</div>

<!-- Column Modal -->
<div id="columnModalOverlay" class="modal-overlay">
  <div class="modal">
    <h2>New Column</h2>
    <form id="columnModalForm" class="modal-form">
      <div>
        <label for="columnTitleField">Column Title</label>
        <input type="text" id="columnTitleField" name="title" required>
      </div>
      <div class="modal-actions">
        <button type="button" id="cancelColumnModalBtn" class="btn-secondary">Cancel</button>
        <button type="submit" id="saveColumnModalBtn" class="btn-primary">Create Column</button>
      </div>
    </form>
  </div>
</div>

<!-- Labels Modal -->
<div id="labelsModalOverlay" class="modal-overlay">
  <div class="modal">
    <h2>Manage Labels</h2>
    <form id="labelForm" class="modal-form">
      <div>
        <label for="labelNameField">Label Name</label>
        <input type="text" id="labelNameField" required>
      </div>
      <div>
        <label for="labelColorField">Color</label>
        <input type="color" id="labelColorField" value="#808080">
      </div>
      <button type="submit" class="btn-primary">Add Label</button>
    </form>
    <div id="existingLabels" style="margin-top: 1.5rem;">
      <!-- Existing labels will be shown here -->
    </div>
    <div class="modal-actions">
      <button type="button" id="closeLabelModalBtn" class="btn-secondary">Close</button>
    </div>
  </div>
</div>

<!-- Archived Cards Modal -->
<div id="archivedModalOverlay" class="modal-overlay">
  <div class="modal" style="max-width: 800px;">
    <h2>Archived Cards</h2>
    <div id="archivedCardsList" style="max-height: 400px; overflow-y: auto;">
      <!-- Archived cards will be shown here -->
    </div>
    <div class="modal-actions">
      <button type="button" id="closeArchivedModalBtn" class="btn-secondary">Close</button>
    </div>
  </div>
</div>


<!-- Checklist Creation Modal -->
<div id="checklistModalOverlay" class="modal-overlay">
  <div class="modal">
    <h2>Create Checklist</h2>
    <form id="checklistForm" class="modal-form">
      <div>
        <label for="checklistTitleField">Checklist Title</label>
        <input type="text" id="checklistTitleField" name="title" required>
      </div>
      <div class="modal-actions">
        <button type="button" id="cancelChecklistBtn" class="btn-secondary">Cancel</button>
        <button type="submit" id="saveChecklistBtn" class="btn-primary">Create Checklist</button>
      </div>
    </form>
  </div>
</div>

<!-- Template Creation Modal -->
<div id="templateModalOverlay" class="modal-overlay">
  <div class="modal">
    <h2>Save as Template</h2>
    <form id="templateForm" class="modal-form">
      <div>
        <label for="templateNameField">Template Name</label>
        <input type="text" id="templateNameField" name="name" required>
      </div>
      <div>
        <label for="templateDescriptionField">Description (optional)</label>
        <textarea id="templateDescriptionField" name="description"></textarea>
      </div>
      <div class="modal-actions">
        <button type="button" id="cancelTemplateBtn" class="btn-secondary">Cancel</button>
        <button type="submit" id="saveTemplateBtn" class="btn-primary">Save Template</button>
      </div>
    </form>
  </div>
</div>

<script src='https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js'></script>
<script>
//── Theme Toggle
const themeToggleBtn = document.getElementById('themeToggle');
const applyTheme = (theme) => {
  document.documentElement.setAttribute('data-theme', theme);
  themeToggleBtn.textContent = theme === 'dark' ? '☀️' : '🌓';
  localStorage.setItem('theme', theme);
};
const currentTheme = localStorage.getItem('theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
applyTheme(currentTheme);
themeToggleBtn.onclick = () => {
  const newTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  applyTheme(newTheme);
};

//── Global State
let currentBoardId = 1;
let boards = [];
let labels = [];
let currentBoardTemplates = [];
let currentBoardData = null;
let currentView = 'board'; // 'board' or 'calendar'
let currentCalendarDate = new Date();
let bulkSelectMode = false;
let selectedCards = new Set();
let isSmallMode = false;
let currentColumnIndex = 0;
const filterState = { q: '', prio: '', label: '', from: '', to: '', sort: '', groupBy: '', showArchived: false };
const PRIORITY_MAP_DISPLAY = {1: "High", 2: "Medium", 3: "Low"};

//── DOM Elements
const boardContainerEl = document.getElementById('boardContainer');
const dashboardAreaEl = document.getElementById('dashboardArea');
const boardSelectEl = document.getElementById('boardSelect');
const newBoardBtn = document.getElementById('newBoardBtn');

// Card Modal Elements
const cardModalOverlayEl = document.getElementById('cardModalOverlay');
const cardModalForm = document.getElementById('cardModalFormEl');
const cardModalTitle = document.getElementById('cardModalTitleEl');
const cardModalIdField = document.getElementById('cardModalIdField');
const cardModalColumnIdField = document.getElementById('cardModalColumnIdField');
const cardTitleField = document.getElementById('cardTitleField');
const cardDescriptionField = document.getElementById('cardDescriptionField');
const cardPriorityField = document.getElementById('cardPriorityField');
const cardStartDateField = document.getElementById('cardStartDateField');
const cardDueDateField = document.getElementById('cardDueDateField');
const cancelCardBtn = document.getElementById('cancelCardModalBtnEl');
const archiveCardBtn = document.getElementById('archiveCardBtnEl');
const labelPickerEl = document.getElementById('labelPicker');

// Board Modal Elements
const boardModalOverlay = document.getElementById('boardModalOverlay');
const boardModalForm = document.getElementById('boardModalForm');
const boardNameField = document.getElementById('boardNameField');
const boardDescriptionField = document.getElementById('boardDescriptionField');

// Labels Modal Elements
const labelsModalOverlay = document.getElementById('labelsModalOverlay');
const labelForm = document.getElementById('labelForm');
const labelNameField = document.getElementById('labelNameField');
const labelColorField = document.getElementById('labelColorField');
const existingLabelsEl = document.getElementById('existingLabels');

// Archive Modal Elements
const archivedModalOverlay = document.getElementById('archivedModalOverlay');
const archivedCardsListEl = document.getElementById('archivedCardsList');

// Shortcuts Modal (removed)
// const shortcutsModalOverlay = document.getElementById('shortcutsModalOverlay');

// Chart instances (no longer used)
// let priorityPieChart = null;
// let columnBarChart = null;

//── Filter Listeners (with error handling)
const setupFilterListener = (id, property) => {
  const element = document.getElementById(id);
  if (element) {
    element.oninput = (e) => { 
      filterState[property] = property === 'q' ? e.target.value.toLowerCase() : e.target.value; 
      applyFiltersUI(); 
    };
  }
};

setupFilterListener('searchInput', 'q');
setupFilterListener('prioFilterSelect', 'prio');
setupFilterListener('labelFilterSelect', 'label');
setupFilterListener('startFromInput', 'from');
setupFilterListener('endToInput', 'to');
setupFilterListener('sortSelect', 'sort');
setupFilterListener('groupBySelect', 'groupBy');

const clearBtn = document.getElementById('clearFilterBtn');
if (clearBtn) {
  clearBtn.onclick = () => {
    filterState.q = ''; filterState.prio = ''; filterState.label = ''; filterState.from = ''; filterState.to = ''; filterState.sort = ''; filterState.groupBy = '';
    
    const inputs = ['searchInput', 'prioFilterSelect', 'labelFilterSelect', 'startFromInput', 'endToInput', 'sortSelect', 'groupBySelect'];
    inputs.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    
    applyFiltersUI();
  };
}

//── API Helper
const apiFetch = async (url, options = {}) => {
    const res = await fetch(url, options);
    if (!res.ok) {
        const errData = await res.json().catch(() => ({ error: `Request failed: ${res.status} ${res.statusText}`, detail: "" }));
        console.error("API Error:", errData);
        alert(`Error: ${errData.error}\n${errData.detail || ''}`);
        throw new Error(errData.error || "API request failed");
    }
    return res.status === 204 ? null : res.json();
};

//── Data Refresh
async function refreshBoardAndMetrics() {
    try {
        const [boardData, metricsData] = await Promise.all([
            apiFetch(currentBoardId ? `/api/board/${currentBoardId}` : '/api/board'),
            apiFetch(currentBoardId ? `/api/metrics/${currentBoardId}` : '/api/metrics')
        ]);
        if (boardData) {
            currentBoardData = boardData;
            renderBoardUI(boardData);
            // Update calendar view if currently active
            if (currentView === 'calendar') {
                renderCalendarView();
            }
        }
        if (metricsData) renderDashboardUI(metricsData);
        applyFiltersUI();
        
        // Check small mode after dashboard is rendered
        setTimeout(checkSmallMode, 100);
    } catch (err) {
        console.error("Refresh failed:", err);
        // Show user-friendly error message
        if (dashboardAreaEl) {
            dashboardAreaEl.innerHTML = '<div style="color: var(--error-color); text-align: center; padding: 2rem;">Failed to load board data. Please refresh the page.</div>';
        }
    }
}

//── Dashboard Rendering 
function renderDashboardUI(metrics) {
    if (!dashboardAreaEl) return;
    if (!metrics) {
        dashboardAreaEl.innerHTML = '<div>No metrics available</div>';
        return;
    }
    
    // Destroy existing charts
    if (window.priorityChart) {
        window.priorityChart.destroy();
        window.priorityChart = null;
    }
    if (window.columnChart) {
        window.columnChart.destroy();
        window.columnChart = null;
    }
    
    // Simple stats
    dashboardAreaEl.innerHTML = `
        <div class="dash-stat urgent">
            <div class="dash-stat-value">${metrics.due_date_insights?.total_overdue || 0}</div>
            <div class="dash-stat-label">Overdue</div>
        </div>
        <div class="dash-stat warning">
            <div class="dash-stat-value">${metrics.due_date_insights?.due_today || 0}</div>
            <div class="dash-stat-label">Due Today</div>
        </div>
        <div class="dash-stat">
            <div class="dash-stat-value">${metrics.due_date_insights?.due_next_7_days || 0}</div>
            <div class="dash-stat-label">Due This Week</div>
        </div>
        <div class="dash-separator"></div>
        <div class="dash-stat">
            <div class="dash-stat-value">${metrics.overall_stats?.active_cards || 0}</div>
            <div class="dash-stat-label">Active</div>
        </div>
        <div class="dash-stat success">
            <div class="dash-stat-value">${metrics.overall_stats?.completed_cards || 0}</div>
            <div class="dash-stat-label">Done</div>
        </div>
    `;
    
    // Add charts
    const chartContainer = document.createElement('div');
    chartContainer.style.cssText = `
        display: flex;
        gap: 20px;
        margin-top: 15px;
        height: 180px;
    `;
    
    // Priority chart
    const priorityDiv = document.createElement('div');
    priorityDiv.style.cssText = 'flex: 1; position: relative;';
    const priorityCanvas = document.createElement('canvas');
    priorityDiv.appendChild(priorityCanvas);
    chartContainer.appendChild(priorityDiv);
    
    // Column chart
    const columnDiv = document.createElement('div');
    columnDiv.style.cssText = 'flex: 1; position: relative;';
    const columnCanvas = document.createElement('canvas');
    columnDiv.appendChild(columnCanvas);
    chartContainer.appendChild(columnDiv);
    
    dashboardAreaEl.appendChild(chartContainer);
    
    // Create charts with theme-aware colors
    setTimeout(() => {
        const textColor = getComputedStyle(document.documentElement).getPropertyValue('--text') || '#111827';
        const surfaceColor = getComputedStyle(document.documentElement).getPropertyValue('--surface') || '#ffffff';
        const gridColor = getComputedStyle(document.documentElement).getPropertyValue('--border-color') || '#e5e7eb';
        
        if (metrics.priority_insights?.labels && metrics.priority_insights?.counts) {
            window.priorityChart = new Chart(priorityCanvas, {
                type: 'pie',
                data: {
                    labels: metrics.priority_insights.labels,
                    datasets: [{
                        data: metrics.priority_insights.counts,
                        backgroundColor: [
                            getComputedStyle(document.documentElement).getPropertyValue('--high') || '#ef4444',
                            getComputedStyle(document.documentElement).getPropertyValue('--med') || '#f59e0b',
                            getComputedStyle(document.documentElement).getPropertyValue('--low') || '#10b981'
                        ],
                        borderColor: surfaceColor,
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { 
                            position: 'bottom',
                            labels: {
                                color: textColor,
                                font: { size: 12 }
                            }
                        }
                    }
                }
            });
        }
        
        if (metrics.column_breakdown?.length) {
            window.columnChart = new Chart(columnCanvas, {
                type: 'bar',
                data: {
                    labels: metrics.column_breakdown.map(col => col.name),
                    datasets: [{
                        data: metrics.column_breakdown.map(col => col.card_count),
                        backgroundColor: getComputedStyle(document.documentElement).getPropertyValue('--button-primary-bg') || '#2563eb',
                        borderColor: getComputedStyle(document.documentElement).getPropertyValue('--button-primary-bg') || '#2563eb',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    indexAxis: 'y',
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        x: { 
                            beginAtZero: true,
                            ticks: { 
                                color: textColor,
                                font: { size: 11 }
                            },
                            grid: { color: gridColor }
                        },
                        y: { 
                            ticks: { 
                                color: textColor,
                                font: { size: 11 }
                            },
                            grid: { display: false }
                        }
                    }
                }
            });
        }
    }, 50);
}

function formatLabel(key) {
    return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}


//── Board Rendering
function renderBoardUI(boardData) {
    if (!boardContainerEl) {
        console.error("Board container element not found");
        return;
    }
    if (!boardData || !boardData.columns || !Array.isArray(boardData.columns)) {
        console.error("No board data or columns provided");
        boardContainerEl.innerHTML = '<div style="text-align: center; padding: 2rem; color: var(--error-color);">Invalid board data</div>';
        return;
    }
    boardContainerEl.innerHTML = ''; 
    boardData.columns.forEach(column => {
        if (!column || !column.id) {
            console.warn("Invalid column data:", column);
            return;
        }
        
        const columnEl = document.createElement('div');
        columnEl.className = 'column';
        columnEl.dataset.id = column.id;
        columnEl.innerHTML = `
            <div class='column-header'>
                <span>${column.title}</span>
                <button class='add-card-btn' data-column-id='${column.id}' title="Add new card">＋</button>
            </div>
            <div class='cards'></div>`;
        boardContainerEl.appendChild(columnEl);
        
        const cardsContainerEl = columnEl.querySelector('.cards');
        if (column.cards && Array.isArray(column.cards)) {
            column.cards.forEach(card => {
                if (card && card.id) {
                    cardsContainerEl.appendChild(createCardElement(card));
                } else {
                    console.warn("Invalid card data:", card);
                }
            });
        }
        
        initializeSortable(cardsContainerEl);
        const addCardBtn = columnEl.querySelector('.add-card-btn');
        if (addCardBtn) {
            addCardBtn.onclick = (e) => openCardModal(null, e.target.dataset.columnId);
        }
    });
    
    // Re-add column navigation and update small mode if active
    const existingNav = boardContainerEl.querySelector('.column-nav');
    if (!existingNav) {
        const navHTML = `
            <div class="column-nav" id="columnNav">
                <div class="column-nav-title" id="columnNavTitle">Column 1 of 4</div>
                <div class="column-nav-buttons">
                    <button class="column-nav-btn" id="prevColumnBtn" onclick="navigateColumn(-1)">‹</button>
                    <button class="column-nav-btn" id="nextColumnBtn" onclick="navigateColumn(1)">›</button>
                </div>
            </div>
        `;
        boardContainerEl.insertAdjacentHTML('afterbegin', navHTML);
    }
    
    // Update small mode display if active
    if (isSmallMode) {
        updateColumnDisplay();
    }
}

function createCardElement(card) {
    if (!card || !card.id || !card.title) {
        console.error("Invalid card data:", card);
        return document.createElement('div'); // Return empty div to prevent errors
    }
    
    const cardEl = document.createElement('div');
    cardEl.className = 'card';
    cardEl.dataset.id = card.id;
    cardEl.dataset.prio = card.priority || 2;
    cardEl.dataset.start = card.start_date || '';
    cardEl.dataset.due = card.due_date || '';
    cardEl.dataset.labels = card.labels && Array.isArray(card.labels) ? card.labels.map(l => l.id).join(',') : '';

    let cardHTML = `<strong>${card.title}</strong>`;
    if (card.description) {
        cardHTML += `<p>${card.description.substring(0, 100) + (card.description.length > 100 ? '...' : '')}</p>`;
    }
    
    // Add labels
    if (card.labels && card.labels.length > 0) {
        cardHTML += `<div class="card-labels">
            ${card.labels.map(label => 
                `<span class="label" style="background-color: ${label.color}">${label.name}</span>`
            ).join('')}
        </div>`;
    }
    
    cardHTML += `<div class="meta">
                    <span>Priority: ${PRIORITY_MAP_DISPLAY[card.priority] || 'N/A'}</span>`;
    if (card.due_date) {
        cardHTML += `<span>Due: ${card.due_date}</span>`;
    }
    cardHTML += `</div>`;
    cardEl.innerHTML = cardHTML;

    cardEl.onclick = (e) => { if (!e.target.closest('button')) openCardModal(card); };
    cardEl.oncontextmenu = (e) => { e.preventDefault(); if (confirm('Delete card?')) deleteCardAPI(card.id); };
    return cardEl;
}

//── Card Modal Logic
function openCardModal(card = null, columnId = null) {
    if (!cardModalForm || !cardModalTitle || !cardModalIdField || !cardTitleField || !cardDescriptionField) {
        console.error("Card modal elements not found");
        return;
    }
    
    cardModalForm.reset();
    const isEdit = !!card;
    const templatePicker = document.getElementById('templatePicker');
    const templateSelect = document.getElementById('templateSelect');
    
    if (card) {
        cardModalTitle.textContent = 'Edit Card';
        cardModalIdField.value = card.id;
        cardTitleField.value = card.title;
        cardDescriptionField.value = card.description || '';
        cardPriorityField.value = card.priority || '2';
        cardStartDateField.value = card.start_date || '';
        cardDueDateField.value = card.due_date || '';
        cardModalColumnIdField.value = card.column_id;
    } else {
        cardModalTitle.textContent = 'Create New Card';
        cardModalIdField.value = '';
        cardModalColumnIdField.value = columnId;
        cardPriorityField.value = '2'; 
    }
    
    // Show/hide archive button
    if (archiveCardBtn) {
        archiveCardBtn.style.display = isEdit ? 'inline-block' : 'none';
    }
    
    // Show template picker for new cards
    if (!isEdit && currentBoardTemplates.length > 0) {
        templatePicker.style.display = 'block';
        templateSelect.innerHTML = '<option value="">-- No Template --</option>';
        currentBoardTemplates.forEach(template => {
            const option = document.createElement('option');
            option.value = template.id;
            option.textContent = template.name;
            templateSelect.appendChild(option);
        });
    } else {
        templatePicker.style.display = 'none';
    }
    
    // Render label picker
    renderLabelPicker();
    
    // Check labels for this card
    if (card?.labels) {
        const labelIds = card.labels.map(l => l.id);
        labelPickerEl.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
            checkbox.checked = labelIds.includes(parseInt(checkbox.value));
        });
    }
    
    // Show Phase 2 sections when editing a card
    const checklistsSection = document.getElementById('checklistsSection');
    const attachmentsSection = document.getElementById('attachmentsSection');
    const templatesSection = document.getElementById('templatesSection');
    
    if (isEdit) {
        checklistsSection.style.display = 'block';
        attachmentsSection.style.display = 'block';
        templatesSection.style.display = 'block';
        
        // Load card data for Phase 2 features
        loadCardChecklists(card.id);
        loadCardAttachments(card.id);
    } else {
        checklistsSection.style.display = 'none';
        attachmentsSection.style.display = 'none';
        templatesSection.style.display = 'none';
    }
    
    cardModalOverlayEl.style.display = 'flex';
    cardTitleField.focus();
}

function closeCardModal() {
    cardModalOverlayEl.style.display = 'none';
}
cancelCardBtn.onclick = closeCardModal;
cardModalOverlayEl.onclick = (e) => { if (e.target === cardModalOverlayEl) closeCardModal(); };

cardModalForm.onsubmit = async (e) => {
    e.preventDefault();
    const cardId = cardModalIdField.value;
    const title = cardTitleField.value.trim();
    if (!title) { alert("Title is required."); cardTitleField.focus(); return; }

    // Get selected label IDs
    const selectedLabels = labelPickerEl ? Array.from(labelPickerEl.querySelectorAll('input[type="checkbox"]:checked'))
        .map(cb => parseInt(cb.value)) : [];
    
    const cardData = {
        title: title,
        description: cardDescriptionField.value.trim(),
        priority: parseInt(cardPriorityField.value, 10),
        start_date: cardStartDateField.value || null,
        due_date: cardDueDateField.value || null,
        column_id: parseInt(cardModalColumnIdField.value, 10),
        label_ids: selectedLabels
    };

    try {
        const url = cardId ? `/api/card/${cardId}` : '/api/card';
        const method = cardId ? 'PATCH' : 'POST';
        await apiFetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cardData) });
        closeCardModal();
        refreshBoardAndMetrics();
    } catch (err) { 
        console.error("Failed to save card:", err);
        alert("Failed to save card. Please try again.");
    }
};

//── Card Actions API
async function deleteCardAPI(cardId) {
    try {
        await apiFetch(`/api/card/${cardId}`, { method: 'DELETE' });
        refreshBoardAndMetrics();
    } catch (err) { console.error("Failed to delete card:", err); }
}

//── Drag‑and‑Drop
function initializeSortable(cardsContainerEl) {
    new Sortable(cardsContainerEl, {
        group: 'kanban-cards',
        animation: 150,
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        dragClass: 'sortable-drag',
        onEnd: async (evt) => {
            const cardId = evt.item.dataset.id;
            const newColumnId = evt.to.closest('.column').dataset.id;
            const newPosition = evt.newDraggableIndex;
            
            try {
                await apiFetch(`/api/card/${cardId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ column_id: parseInt(newColumnId), position: newPosition })
                });
                refreshBoardAndMetrics(); 
            } catch (err) {
                console.error("Failed to update card position:", err);
                refreshBoardAndMetrics();
            }
        }
    });
}

//── Filter Application with Sorting and Grouping
function applyFiltersUI() {
    const columns = document.querySelectorAll('.column');
    
    columns.forEach(column => {
        const cardsContainer = column.querySelector('.cards');
        if (!cardsContainer) return;
        
        const cards = Array.from(cardsContainer.querySelectorAll('.card'));
        
        // Filter cards
        const filteredCards = cards.filter(cardElement => {
            const titleDescContent = cardElement.textContent || ""; 
            const qOk = !filterState.q || titleDescContent.toLowerCase().includes(filterState.q);
            const pOk = !filterState.prio || cardElement.dataset.prio === filterState.prio;
            const sOk = !filterState.from || (cardElement.dataset.start && cardElement.dataset.start >= filterState.from);
            const dOk = !filterState.to || (cardElement.dataset.due && cardElement.dataset.due <= filterState.to);
            const lOk = !filterState.label || (cardElement.dataset.labels && cardElement.dataset.labels.includes(filterState.label));
            
            return qOk && pOk && sOk && dOk && lOk;
        });
        
        // Sort filtered cards if sorting is enabled
        if (filterState.sort) {
            filteredCards.sort((a, b) => {
                switch (filterState.sort) {
                    case 'priority':
                        return parseInt(a.dataset.prio) - parseInt(b.dataset.prio);
                    case 'due_date':
                        const aDate = a.dataset.due || '9999-12-31';
                        const bDate = b.dataset.due || '9999-12-31';
                        return aDate.localeCompare(bDate);
                    case 'start_date':
                        const aStart = a.dataset.start || '9999-12-31';
                        const bStart = b.dataset.start || '9999-12-31';
                        return aStart.localeCompare(bStart);
                    case 'title':
                        const aTitle = a.querySelector('strong')?.textContent || '';
                        const bTitle = b.querySelector('strong')?.textContent || '';
                        return aTitle.localeCompare(bTitle);
                    case 'created':
                        return parseInt(a.dataset.id) - parseInt(b.dataset.id);
                    default:
                        return 0;
                }
            });
        }
        
        // Clear the container
        cardsContainer.innerHTML = '';
        
        // Group cards if grouping is enabled
        if (filterState.groupBy) {
            displayGroupedCards(cardsContainer, filteredCards);
        } else {
            // Display cards normally
            filteredCards.forEach(card => {
                cardsContainer.appendChild(card);
            });
        }
    });
}

function displayGroupedCards(container, cards) {
    const groups = {};
    
    // Group cards
    cards.forEach(card => {
        let groupKey = 'Other';
        
        switch (filterState.groupBy) {
            case 'priority':
                groupKey = PRIORITY_MAP_DISPLAY[parseInt(card.dataset.prio)] || 'Other';
                break;
            case 'labels':
                const cardLabels = card.dataset.labels ? card.dataset.labels.split(',') : [];
                const labelNames = cardLabels.map(id => {
                    const label = labels.find(l => l.id == id);
                    return label ? label.name : 'Unknown';
                });
                groupKey = labelNames.length > 0 ? labelNames[0] : 'No Labels';
                break;
            case 'due_date':
                const dueDate = card.dataset.due;
                if (!dueDate) {
                    groupKey = 'No Due Date';
                } else {
                    const today = new Date();
                    const todayStr = today.toISOString().split('T')[0];
                    
                    const tomorrow = new Date(today);
                    tomorrow.setDate(tomorrow.getDate() + 1);
                    const tomorrowStr = tomorrow.toISOString().split('T')[0];
                    
                    const nextWeek = new Date(today);
                    nextWeek.setDate(nextWeek.getDate() + 7);
                    const nextWeekStr = nextWeek.toISOString().split('T')[0];
                    
                    if (dueDate < todayStr) groupKey = 'Overdue';
                    else if (dueDate === todayStr) groupKey = 'Due Today';
                    else if (dueDate === tomorrowStr) groupKey = 'Due Tomorrow';
                    else if (dueDate <= nextWeekStr) groupKey = 'Due This Week';
                    else groupKey = 'Due Later';
                }
                break;
        }
        
        if (!groups[groupKey]) groups[groupKey] = [];
        groups[groupKey].push(card);
    });
    
    // Display grouped cards
    Object.entries(groups).forEach(([groupName, groupCards]) => {
        const groupHeader = document.createElement('div');
        groupHeader.className = 'group-header';
        groupHeader.innerHTML = `<strong>${groupName} (${groupCards.length})</strong>`;
        container.appendChild(groupHeader);
        
        groupCards.forEach(card => {
            container.appendChild(card);
        });
    });
}

//── Add Column
document.getElementById('addColBtn').onclick = async () => {
    document.getElementById('columnModalOverlay').style.display = 'flex';
    document.getElementById('columnTitleField').focus();
};

//── Board Management
async function loadBoards() {
    try {
        boards = await apiFetch('/api/boards');
        boardSelectEl.innerHTML = '';
        boards.forEach(board => {
            const option = document.createElement('option');
            option.value = board.id;
            option.textContent = board.name;
            option.selected = board.id === currentBoardId;
            boardSelectEl.appendChild(option);
        });
        
        // Load saved board or first board
        const savedBoardId = localStorage.getItem('currentBoardId');
        const boardToLoad = savedBoardId && boards.find(b => b.id == savedBoardId) 
            ? savedBoardId 
            : boards[0]?.id;
        
        if (boardToLoad) {
            currentBoardId = parseInt(boardToLoad);
            boardSelectEl.value = currentBoardId;
        }
    } catch (err) {
        console.error("Failed to load boards:", err);
    }
}

async function switchBoard(boardId) {
    currentBoardId = parseInt(boardId);
    localStorage.setItem('currentBoardId', currentBoardId);
    
    try {
        const [boardData, metricsData] = await Promise.all([
            apiFetch(`/api/board/${currentBoardId}`),
            apiFetch(`/api/metrics/${currentBoardId}`)
        ]);
        
        await loadLabels();
        renderBoardUI(boardData);
        renderDashboardUI(metricsData);
        applyFiltersUI();
    } catch (err) {
        console.error("Failed to switch board:", err);
        alert("Failed to switch board. Please try again.");
        // Reset board selection to previous value
        if (boardSelectEl) {
            boardSelectEl.value = currentBoardId;
        }
    }
}

boardSelectEl.addEventListener('change', (e) => {
    switchBoard(e.target.value);
});

newBoardBtn.addEventListener('click', async () => {
    document.getElementById('boardModalOverlay').style.display = 'flex';
    document.getElementById('boardNameField').focus();
});

//── Archive Management
async function showArchivedCards() {
    archivedModalOverlay.style.display = 'flex';
    try {
        const archivedCards = await apiFetch('/api/cards/archived');
        archivedCardsListEl.innerHTML = archivedCards.length === 0 
            ? '<p style="text-align: center; color: var(--muted);">No archived cards</p>'
            : archivedCards.map(card => `
                <div class="card" data-prio="${card.priority}" style="margin-bottom: 0.75rem;">
                    <strong>${card.title}</strong>
                    ${card.description ? `<p>${card.description}</p>` : ''}
                    <div class="card-labels">
                        ${card.labels.map(label => 
                            `<span class="label" style="background-color: ${label.color}">${label.name}</span>`
                        ).join('')}
                    </div>
                    <div class="meta">
                        <span>${card.priority_name} Priority</span>
                        <button onclick="unarchiveCard(${card.id})" class="btn-primary btn-sm">Restore</button>
                    </div>
                </div>
            `).join('');
    } catch (err) {
        console.error("Failed to load archived cards:", err);
    }
}

async function archiveCard(cardId) {
    try {
        await apiFetch(`/api/cards/${cardId}/archive`, { method: 'POST' });
        cardModalOverlayEl.style.display = 'none';
        await refreshBoardAndMetrics();
    } catch (err) {
        console.error("Failed to archive card:", err);
    }
}

async function unarchiveCard(cardId) {
    try {
        await apiFetch(`/api/cards/${cardId}/unarchive`, { method: 'POST' });
        await showArchivedCards();
        await refreshBoardAndMetrics();
    } catch (err) {
        console.error("Failed to unarchive card:", err);
    }
}

//── Label Management
async function loadLabels() {
    try {
        labels = await apiFetch(`/api/boards/${currentBoardId}/labels`);
        renderLabelPicker();
        populateLabelFilter();
    } catch (err) {
        console.error("Failed to load labels:", err);
    }
}

function populateLabelFilter() {
    const labelFilterSelect = document.getElementById('labelFilterSelect');
    if (!labelFilterSelect) return;
    
    labelFilterSelect.innerHTML = '<option value="">All Labels</option>';
    
    labels.forEach(label => {
        const option = document.createElement('option');
        option.value = label.id;
        option.textContent = label.name;
        labelFilterSelect.appendChild(option);
    });
}

function renderLabelPicker() {
    if (!labelPickerEl) return;
    labelPickerEl.innerHTML = labels.map(label => `
        <label class="label-option">
            <input type="checkbox" value="${label.id}" name="labels">
            <span class="label" style="background-color: ${label.color}">${label.name}</span>
        </label>
    `).join('');
}

async function showLabelsModal() {
    labelsModalOverlay.style.display = 'flex';
    await loadExistingLabels();
}

async function loadExistingLabels() {
    existingLabelsEl.innerHTML = '<h3>Existing Labels</h3>' + labels.map(label => `
        <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem;">
            <span class="label" style="background-color: ${label.color}">${label.name}</span>
            <button onclick="deleteLabel(${label.id})" class="btn-danger btn-sm">Delete</button>
        </div>
    `).join('');
}

async function createLabel(event) {
    event.preventDefault();
    console.log("Creating label...");
    
    if (!labelNameField || !labelColorField) {
        console.error("Label form fields not found");
        return;
    }
    
    const name = labelNameField.value.trim();
    if (!name) {
        alert("Label name is required");
        return;
    }
    
    const data = {
        name: name,
        color: labelColorField.value
    };
    
    try {
        await apiFetch(`/api/boards/${currentBoardId}/labels`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        labelNameField.value = '';
        labelColorField.value = '#808080';
        
        await loadLabels();
        await loadExistingLabels();
        console.log("Label created successfully");
    } catch (err) {
        console.error("Failed to create label:", err);
    }
}

async function deleteLabel(labelId) {
    if (!confirm('Are you sure you want to delete this label?')) return;
    
    try {
        await apiFetch(`/api/labels/${labelId}`, { method: 'DELETE' });
        await loadLabels();
        await loadExistingLabels();
    } catch (err) {
        console.error("Failed to delete label:", err);
    }
}

//── Enhanced Modal Management
document.getElementById('viewArchivedBtn').onclick = showArchivedCards;
document.getElementById('manageLabelsBtnEl').onclick = showLabelsModal;
document.getElementById('closeArchivedModalBtn').onclick = () => archivedModalOverlay.style.display = 'none';
document.getElementById('closeLabelModalBtn').onclick = () => labelsModalOverlay.style.display = 'none';
// document.getElementById('closeShortcutsModalBtn').onclick = () => shortcutsModalOverlay.style.display = 'none';

// Archive button functionality
archiveCardBtn.onclick = () => {
    const cardId = cardModalIdField.value;
    if (cardId) archiveCard(cardId);
};

// Label form submission
if (labelForm) {
    labelForm.onsubmit = createLabel;
    console.log("Label form connected");
} else {
    console.error("Label form not found");
}

// Add logging to test form submission
document.addEventListener('DOMContentLoaded', () => {
    console.log("DOM loaded, checking form elements:");
    console.log("labelForm:", labelForm);
    console.log("labelNameField:", labelNameField);
    console.log("labelColorField:", labelColorField);
});

// Close modals on outside click
[archivedModalOverlay, labelsModalOverlay].forEach(overlay => {
    if (overlay) {
        overlay.onclick = (e) => {
            if (e.target === overlay) overlay.style.display = 'none';
        };
    }
});

//── Keyboard Shortcuts (Limited to essential ones)
document.addEventListener('keydown', (e) => {
    // Only handle keyboard shortcuts when not in input fields
    if (e.target.matches('input, textarea, select')) {
        return;
    }
    
    switch(e.key) {
        case 'Escape':
            document.querySelectorAll('.modal-overlay').forEach(modal => {
                modal.style.display = 'none';
            });
            break;
    }
});

// Export functions for inline onclick handlers
window.deleteLabel = deleteLabel;
window.unarchiveCard = unarchiveCard;

//── Phase 2 Features
// Checklist Management
let currentCardChecklists = [];

async function loadCardChecklists(cardId) {
    try {
        currentCardChecklists = await apiFetch(`/api/cards/${cardId}/checklists`);
        renderChecklists();
    } catch (err) {
        console.error("Failed to load checklists:", err);
    }
}

function renderChecklists() {
    const container = document.getElementById('checklistsContainer');
    if (!container) return;
    
    container.innerHTML = currentCardChecklists.map(checklist => `
        <div class="checklist" data-checklist-id="${checklist.id}">
            <div class="checklist-header">
                <span class="checklist-title">${checklist.title}</span>
                <span class="checklist-progress">${getChecklistProgress(checklist)}</span>
                <button onclick="deleteChecklist(${checklist.id})" class="btn-danger btn-xs">×</button>
            </div>
            <div class="checklist-items">
                ${checklist.items.map(item => `
                    <div class="checklist-item">
                        <input type="checkbox" ${item.is_checked ? 'checked' : ''} 
                               onchange="toggleChecklistItem(${item.id}, this.checked)">
                        <span class="checklist-item-text ${item.is_checked ? 'completed' : ''}">${item.text}</span>
                        <div class="checklist-item-actions">
                            <button onclick="deleteChecklistItem(${item.id})" class="btn-danger btn-xs">×</button>
                        </div>
                    </div>
                `).join('')}
            </div>
            <div class="checklist-add-item">
                <input type="text" placeholder="Add item..." onkeypress="if(event.key==='Enter') addChecklistItem(${checklist.id}, this.value, this)">
                <button onclick="addChecklistItem(${checklist.id}, this.previousElementSibling.value, this.previousElementSibling)" class="btn-secondary btn-xs">Add</button>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: ${getChecklistProgressPercent(checklist)}%"></div>
            </div>
        </div>
    `).join('');
}

function getChecklistProgress(checklist) {
    const completed = checklist.items.filter(item => item.is_checked).length;
    const total = checklist.items.length;
    return `${completed}/${total}`;
}

function getChecklistProgressPercent(checklist) {
    const completed = checklist.items.filter(item => item.is_checked).length;
    const total = checklist.items.length;
    return total > 0 ? (completed / total) * 100 : 0;
}

async function addChecklist() {
    const cardId = cardModalIdField.value;
    if (!cardId) return;
    
    // Show checklist creation modal
    document.getElementById('checklistModalOverlay').style.display = 'flex';
    document.getElementById('checklistTitleField').focus();
}

async function deleteChecklist(checklistId) {
    if (!confirm("Delete this checklist?")) return;
    
    try {
        await apiFetch(`/api/checklists/${checklistId}`, { method: 'DELETE' });
        const cardId = cardModalIdField.value;
        await loadCardChecklists(cardId);
    } catch (err) {
        console.error("Failed to delete checklist:", err);
    }
}

async function addChecklistItem(checklistId, text, inputEl) {
    if (!text.trim()) return;
    
    try {
        await apiFetch(`/api/checklists/${checklistId}/items`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text.trim() })
        });
        inputEl.value = '';
        const cardId = cardModalIdField.value;
        await loadCardChecklists(cardId);
    } catch (err) {
        console.error("Failed to add checklist item:", err);
    }
}

async function toggleChecklistItem(itemId, isChecked) {
    try {
        await apiFetch(`/api/checklist-items/${itemId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_checked: isChecked })
        });
        const cardId = cardModalIdField.value;
        await loadCardChecklists(cardId);
    } catch (err) {
        console.error("Failed to toggle checklist item:", err);
    }
}

async function deleteChecklistItem(itemId) {
    try {
        await apiFetch(`/api/checklist-items/${itemId}`, { method: 'DELETE' });
        const cardId = cardModalIdField.value;
        await loadCardChecklists(cardId);
    } catch (err) {
        console.error("Failed to delete checklist item:", err);
    }
}

// Attachment Management
let currentCardAttachments = [];

async function loadCardAttachments(cardId) {
    try {
        const card = await apiFetch(`/api/board/${currentBoardId}`);
        const cardData = card.columns.flatMap(col => col.cards).find(c => c.id == cardId);
        currentCardAttachments = cardData ? cardData.attachments || [] : [];
        renderAttachments();
    } catch (err) {
        console.error("Failed to load attachments:", err);
    }
}

function renderAttachments() {
    const container = document.getElementById('attachmentsContainer');
    if (!container) return;
    
    container.innerHTML = currentCardAttachments.map(attachment => `
        <div class="attachment" data-attachment-id="${attachment.id}">
            <div class="attachment-icon">${getFileIcon(attachment.mime_type)}</div>
            <div class="attachment-info">
                <div class="attachment-name">${attachment.original_filename}</div>
                <div class="attachment-meta">${formatFileSize(attachment.file_size)}</div>
            </div>
            <div class="attachment-actions">
                <button onclick="downloadAttachment(${attachment.id})" class="btn-secondary btn-xs">Download</button>
                <button onclick="deleteAttachment(${attachment.id})" class="btn-danger btn-xs">×</button>
            </div>
        </div>
    `).join('');
}

function getFileIcon(mimeType) {
    if (mimeType.startsWith('image/')) return '🖼️';
    if (mimeType.startsWith('text/')) return '📄';
    if (mimeType.includes('pdf')) return '📕';
    if (mimeType.includes('zip') || mimeType.includes('archive')) return '📦';
    return '📎';
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

async function addAttachment() {
    const input = document.getElementById('attachmentInput');
    input.click();
}

async function uploadAttachment(files) {
    const cardId = cardModalIdField.value;
    if (!cardId || !files.length) return;
    
    for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            await fetch(`/api/cards/${cardId}/attachments`, {
                method: 'POST',
                body: formData
            });
        } catch (err) {
            console.error("Failed to upload attachment:", err);
        }
    }
    
    await loadCardAttachments(cardId);
}

function downloadAttachment(attachmentId) {
    window.open(`/api/attachments/${attachmentId}/download`, '_blank');
}

async function deleteAttachment(attachmentId) {
    if (!confirm("Delete this attachment?")) return;
    
    try {
        await apiFetch(`/api/attachments/${attachmentId}`, { method: 'DELETE' });
        const cardId = cardModalIdField.value;
        await loadCardAttachments(cardId);
    } catch (err) {
        console.error("Failed to delete attachment:", err);
    }
}

// Template Management

async function loadBoardTemplates() {
    try {
        currentBoardTemplates = await apiFetch(`/api/boards/${currentBoardId}/templates`);
    } catch (err) {
        console.error("Failed to load templates:", err);
    }
}

async function saveAsTemplate() {
    const cardId = cardModalIdField.value;
    if (!cardId) return;
    
    // Show template creation modal
    document.getElementById('templateModalOverlay').style.display = 'flex';
    document.getElementById('templateNameField').focus();
}

// Markdown Support
function toggleMarkdownPreview(textareaId) {
    const textarea = document.getElementById(textareaId);
    const previewId = textareaId + 'Preview';
    let preview = document.getElementById(previewId);
    
    if (!preview) {
        preview = document.createElement('div');
        preview.id = previewId;
        preview.className = 'markdown-preview';
        preview.style.cssText = `
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 0.375rem;
            padding: 0.625rem 0.75rem;
            margin-bottom: 0.75rem;
            min-height: 100px;
            display: none;
        `;
        textarea.parentNode.insertBefore(preview, textarea);
    }
    
    if (preview.style.display === 'none') {
        preview.innerHTML = parseMarkdown(textarea.value);
        preview.style.display = 'block';
        textarea.style.display = 'none';
    } else {
        preview.style.display = 'none';
        textarea.style.display = 'block';
    }
}

function parseMarkdown(text) {
    return text
        .replace(/^# (.+)$/gm, '<h1>$1</h1>')
        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code>$1</code>')
        .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2">$1</a>')
        .replace(/\n/g, '<br>');
}

// Event Listeners for Phase 2
document.getElementById('addChecklistBtn').onclick = addChecklist;
document.getElementById('addAttachmentBtn').onclick = addAttachment;
document.getElementById('saveAsTemplateBtn').onclick = saveAsTemplate;
document.getElementById('attachmentInput').onchange = (e) => uploadAttachment(e.target.files);

// Checklist Modal Event Handlers
document.getElementById('cancelChecklistBtn').onclick = () => {
    document.getElementById('checklistModalOverlay').style.display = 'none';
};
document.getElementById('checklistModalOverlay').onclick = (e) => {
    if (e.target === document.getElementById('checklistModalOverlay')) {
        document.getElementById('checklistModalOverlay').style.display = 'none';
    }
};
document.getElementById('checklistForm').onsubmit = async (e) => {
    e.preventDefault();
    const cardId = cardModalIdField.value;
    const title = document.getElementById('checklistTitleField').value.trim();
    
    if (!title) return;
    
    try {
        await apiFetch(`/api/cards/${cardId}/checklists`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title })
        });
        await loadCardChecklists(cardId);
        document.getElementById('checklistModalOverlay').style.display = 'none';
        document.getElementById('checklistTitleField').value = '';
    } catch (err) {
        console.error("Failed to add checklist:", err);
    }
};

// Template Modal Event Handlers
document.getElementById('cancelTemplateBtn').onclick = () => {
    document.getElementById('templateModalOverlay').style.display = 'none';
};
document.getElementById('templateModalOverlay').onclick = (e) => {
    if (e.target === document.getElementById('templateModalOverlay')) {
        document.getElementById('templateModalOverlay').style.display = 'none';
    }
};
document.getElementById('templateForm').onsubmit = async (e) => {
    e.preventDefault();
    const cardId = cardModalIdField.value;
    const name = document.getElementById('templateNameField').value.trim();
    const description = document.getElementById('templateDescriptionField').value.trim();
    
    if (!name) return;
    
    try {
        // Get current card data
        const card = await apiFetch(`/api/board/${currentBoardId}`);
        const cardData = card.columns.flatMap(col => col.cards).find(c => c.id == cardId);
        
        const templateData = {
            title: cardData.title,
            description: cardData.description,
            priority: cardData.priority,
            checklists: cardData.checklists || []
        };
        
        await apiFetch(`/api/boards/${currentBoardId}/templates`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name,
                description,
                template_data: JSON.stringify(templateData)
            })
        });
        
        document.getElementById('templateModalOverlay').style.display = 'none';
        document.getElementById('templateNameField').value = '';
        document.getElementById('templateDescriptionField').value = '';
        await loadBoardTemplates();
    } catch (err) {
        console.error("Failed to save template:", err);
    }
};

// Board Modal Event Handlers
document.getElementById('cancelBoardModalBtn').onclick = () => {
    document.getElementById('boardModalOverlay').style.display = 'none';
};
document.getElementById('boardModalOverlay').onclick = (e) => {
    if (e.target === document.getElementById('boardModalOverlay')) {
        document.getElementById('boardModalOverlay').style.display = 'none';
    }
};
document.getElementById('boardModalForm').onsubmit = async (e) => {
    e.preventDefault();
    const name = document.getElementById('boardNameField').value.trim();
    
    if (!name) return;
    
    try {
        const newBoard = await apiFetch('/api/boards', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        currentBoardId = newBoard.id;
        await loadBoards();
        await switchBoard(currentBoardId);
        document.getElementById('boardModalOverlay').style.display = 'none';
        document.getElementById('boardNameField').value = '';
        document.getElementById('boardDescriptionField').value = '';
    } catch (err) {
        console.error("Failed to create board:", err);
    }
};

// Column Modal Event Handlers
document.getElementById('cancelColumnModalBtn').onclick = () => {
    document.getElementById('columnModalOverlay').style.display = 'none';
};
document.getElementById('columnModalOverlay').onclick = (e) => {
    if (e.target === document.getElementById('columnModalOverlay')) {
        document.getElementById('columnModalOverlay').style.display = 'none';
    }
};
document.getElementById('columnModalForm').onsubmit = async (e) => {
    e.preventDefault();
    const title = document.getElementById('columnTitleField').value.trim();
    
    if (!title) return;
    
    try {
        await apiFetch('/api/column', { 
            method: 'POST', 
            headers: { 'Content-Type': 'application/json' }, 
            body: JSON.stringify({ title, board_id: currentBoardId }) 
        });
        refreshBoardAndMetrics();
        document.getElementById('columnModalOverlay').style.display = 'none';
        document.getElementById('columnTitleField').value = '';
    } catch (err) {
        console.error("Failed to add column:", err);
    }
};

// Export functions for global access
window.deleteChecklist = deleteChecklist;
window.addChecklistItem = addChecklistItem;
window.toggleChecklistItem = toggleChecklistItem;
window.deleteChecklistItem = deleteChecklistItem;
window.downloadAttachment = downloadAttachment;
window.deleteAttachment = deleteAttachment;

//── Phase 3: Calendar View
function toggleView() {
    currentView = currentView === 'board' ? 'calendar' : 'board';
    const boardContainer = document.getElementById('boardContainer');
    const calendarContainer = document.getElementById('calendarContainer');
    const toggleBtn = document.getElementById('toggleViewBtn');
    
    if (currentView === 'calendar') {
        boardContainer.style.display = 'none';
        calendarContainer.style.display = 'block';
        toggleBtn.textContent = '📋 Board';
        renderCalendarView();
    } else {
        boardContainer.style.display = 'flex';
        calendarContainer.style.display = 'none';
        toggleBtn.textContent = '📅 Calendar';
    }
}

function renderCalendarView() {
    const calendarContainer = document.getElementById('calendarContainer');
    if (!calendarContainer) return;
    
    const year = currentCalendarDate.getFullYear();
    const month = currentCalendarDate.getMonth();
    const monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 
                       'July', 'August', 'September', 'October', 'November', 'December'];
    
    // Get first day of month and number of days
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const prevLastDay = new Date(year, month, 0);
    const daysInMonth = lastDay.getDate();
    const firstDayOfWeek = firstDay.getDay();
    
    // Get cards with due dates from actual data
    const cardsWithDates = [];
    if (currentBoardData && currentBoardData.columns) {
        currentBoardData.columns.forEach(column => {
            if (column.cards) {
                column.cards.forEach(card => {
                    if (card.due_date) {
                        cardsWithDates.push({
                            id: card.id,
                            title: card.title,
                            due: card.due_date,
                            priority: card.priority
                        });
                    }
                });
            }
        });
    }
    
    let calendarHTML = `
        <div class="calendar-header">
            <h2>${monthNames[month]} ${year}</h2>
            <div class="calendar-nav">
                <button onclick="changeCalendarMonth(-1)" class="btn-ghost">◀</button>
                <button onclick="currentCalendarDate = new Date(); renderCalendarView();" class="btn-secondary">Today</button>
                <button onclick="changeCalendarMonth(1)" class="btn-ghost">▶</button>
            </div>
        </div>
        <div class="calendar-grid">
    `;
    
    // Day headers
    const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    dayNames.forEach(day => {
        calendarHTML += `<div class="calendar-day-header">${day}</div>`;
    });
    
    // Previous month's trailing days
    for (let i = firstDayOfWeek - 1; i >= 0; i--) {
        const day = prevLastDay.getDate() - i;
        calendarHTML += `<div class="calendar-day other-month">
            <div class="calendar-day-number">${day}</div>
        </div>`;
    }
    
    // Current month days
    const today = new Date();
    for (let day = 1; day <= daysInMonth; day++) {
        const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        const isToday = today.getFullYear() === year && today.getMonth() === month && today.getDate() === day;
        const dayCards = cardsWithDates.filter(card => card.due === dateStr);
        
        calendarHTML += `<div class="calendar-day ${isToday ? 'today' : ''}" data-date="${dateStr}">
            <div class="calendar-day-number">${day}</div>`;
        
        dayCards.forEach(card => {
            calendarHTML += `<div class="calendar-card" data-prio="${card.priority}" onclick="openCardById(${card.id})">
                ${card.title}
            </div>`;
        });
        
        calendarHTML += `</div>`;
    }
    
    // Next month's leading days
    const remainingDays = 42 - (firstDayOfWeek + daysInMonth); // 6 weeks * 7 days
    for (let day = 1; day <= remainingDays; day++) {
        calendarHTML += `<div class="calendar-day other-month">
            <div class="calendar-day-number">${day}</div>
        </div>`;
    }
    
    calendarHTML += `</div>`;
    calendarContainer.innerHTML = calendarHTML;
}

function changeCalendarMonth(direction) {
    const newDate = new Date(currentCalendarDate);
    newDate.setMonth(newDate.getMonth() + direction);
    currentCalendarDate = newDate;
    renderCalendarView();
}

function openCardById(cardId) {
    // Find the card data and open modal
    if (!cardId || !currentBoardId) {
        console.error("Invalid cardId or currentBoardId");
        return;
    }
    
    fetch(`/api/board/${currentBoardId}`)
        .then(res => res.json())
        .then(boardData => {
            const card = boardData.columns.flatMap(col => col.cards).find(c => c.id == cardId);
            if (card) openCardModal(card);
        });
}

// Phase 3: Quick Add Cards
function enableQuickAdd(columnId) {
    const column = document.querySelector(`[data-id="${columnId}"]`);
    if (!column) return;
    
    const cardsContainer = column.querySelector('.cards');
    let quickAddContainer = column.querySelector('.quick-add-container');
    
    if (!quickAddContainer) {
        quickAddContainer = document.createElement('div');
        quickAddContainer.className = 'quick-add-container';
        quickAddContainer.innerHTML = `
            <input type="text" class="quick-add-input" placeholder="Enter card title (use #high, #medium, #low for priority)">
            <div class="quick-add-hint">Press Enter to add, Esc to cancel</div>
        `;
        cardsContainer.parentNode.insertBefore(quickAddContainer, cardsContainer);
    }
    
    quickAddContainer.classList.add('active');
    const input = quickAddContainer.querySelector('.quick-add-input');
    input.focus();
    
    input.onkeydown = async (e) => {
        if (e.key === 'Enter' && input.value.trim()) {
            await createQuickCard(columnId, input.value.trim());
            input.value = '';
        } else if (e.key === 'Escape') {
            quickAddContainer.classList.remove('active');
            input.value = '';
        }
    };
}

async function createQuickCard(columnId, text) {
    // Parse quick add syntax
    let title = text;
    let priority = 2; // default medium
    
    // Extract priority
    const priorityMatch = text.match(/#(high|medium|low)/i);
    if (priorityMatch) {
        const priorityMap = { 'high': 1, 'medium': 2, 'low': 3 };
        priority = priorityMap[priorityMatch[1].toLowerCase()];
        title = text.replace(priorityMatch[0], '').trim();
    }
    
    // Extract due date (@tomorrow, @nextweek, etc.)
    let dueDate = null;
    const dateMatch = text.match(/@(\w+)/);
    if (dateMatch) {
        const dateStr = dateMatch[1].toLowerCase();
        const today = new Date();
        
        if (dateStr === 'today') {
            dueDate = today.toISOString().split('T')[0];
        } else if (dateStr === 'tomorrow') {
            const tomorrow = new Date(today);
            tomorrow.setDate(tomorrow.getDate() + 1);
            dueDate = tomorrow.toISOString().split('T')[0];
        } else if (dateStr === 'nextweek') {
            const nextWeek = new Date(today);
            nextWeek.setDate(nextWeek.getDate() + 7);
            dueDate = nextWeek.toISOString().split('T')[0];
        }
        
        if (dueDate) {
            title = title.replace(dateMatch[0], '').trim();
        }
    }
    
    // Create card
    try {
        await apiFetch('/api/card', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title,
                description: '',
                column_id: parseInt(columnId),
                priority,
                due_date: dueDate
            })
        });
        refreshBoardAndMetrics();
    } catch (err) {
        console.error("Failed to create quick card:", err);
    }
}

// Phase 3: Bulk Operations
function toggleBulkSelectMode() {
    bulkSelectMode = !bulkSelectMode;
    selectedCards.clear();
    
    const board = document.getElementById('boardContainer');
    const bulkBar = document.getElementById('bulkActionsBar');
    
    if (bulkSelectMode) {
        board.classList.add('bulk-select-mode');
        addBulkSelectCheckboxes();
    } else {
        board.classList.remove('bulk-select-mode');
        removeBulkSelectCheckboxes();
        bulkBar.classList.remove('active');
    }
}

function addBulkSelectCheckboxes() {
    document.querySelectorAll('.card').forEach(card => {
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'bulk-select-checkbox';
        checkbox.onclick = (e) => {
            e.stopPropagation();
            toggleCardSelection(card.dataset.id);
        };
        card.appendChild(checkbox);
    });
}

function removeBulkSelectCheckboxes() {
    document.querySelectorAll('.bulk-select-checkbox').forEach(cb => cb.remove());
}

function toggleCardSelection(cardId) {
    if (selectedCards.has(cardId)) {
        selectedCards.delete(cardId);
    } else {
        selectedCards.add(cardId);
    }
    
    updateBulkActionsBar();
}

function updateBulkActionsBar() {
    const bulkBar = document.getElementById('bulkActionsBar');
    const countEl = document.getElementById('bulkSelectCount');
    
    countEl.textContent = selectedCards.size;
    
    if (selectedCards.size > 0) {
        bulkBar.classList.add('active');
    } else {
        bulkBar.classList.remove('active');
    }
}

async function bulkMoveCards() {
    if (!currentBoardData || !currentBoardData.columns) {
        alert('Board data not available. Please refresh the page.');
        return;
    }
    
    // Create column selection modal
    const columns = currentBoardData.columns;
    const columnOptions = columns.map(col => `<option value="${col.id}">${col.title}</option>`).join('');
    
    const modalHTML = `
        <div style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000;">
            <div style="background: var(--card-bg); padding: 2rem; border-radius: 8px; max-width: 400px; width: 90%;">
                <h3>Move ${selectedCards.size} cards to column:</h3>
                <select id="bulkColumnSelect" style="width: 100%; padding: 0.5rem; margin: 1rem 0; border: 1px solid var(--border); border-radius: 4px;">
                    <option value="">Select a column</option>
                    ${columnOptions}
                </select>
                <div style="display: flex; gap: 1rem; justify-content: flex-end;">
                    <button onclick="closeBulkMoveModal()" style="padding: 0.5rem 1rem; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; cursor: pointer;">Cancel</button>
                    <button onclick="executeBulkMove()" style="padding: 0.5rem 1rem; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer;">Move</button>
                </div>
            </div>
        </div>
    `;
    
    const modalEl = document.createElement('div');
    modalEl.innerHTML = modalHTML;
    modalEl.id = 'bulkMoveModal';
    document.body.appendChild(modalEl);
}

function closeBulkMoveModal() {
    const modal = document.getElementById('bulkMoveModal');
    if (modal) modal.remove();
}

async function executeBulkMove() {
    const columnId = document.getElementById('bulkColumnSelect').value;
    if (!columnId) {
        alert('Please select a column');
        return;
    }
    
    const bulkMoveBtn = document.querySelector('#bulkMoveModal button[onclick="executeBulkMove()"]');
    bulkMoveBtn.textContent = 'Moving...';
    bulkMoveBtn.disabled = true;
    
    let successful = 0;
    let failed = 0;
    
    for (const cardId of selectedCards) {
        try {
            await apiFetch(`/api/card/${cardId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ column_id: parseInt(columnId) })
            });
            successful++;
        } catch (err) {
            console.error(`Failed to move card ${cardId}:`, err);
            failed++;
        }
    }
    
    closeBulkMoveModal();
    
    if (failed > 0) {
        alert(`Moved ${successful} cards successfully. ${failed} cards failed to move.`);
    }
    
    toggleBulkSelectMode();
    refreshBoardAndMetrics();
}

async function bulkArchiveCards() {
    if (!confirm(`Archive ${selectedCards.size} cards? This action can be undone from the archive.`)) return;
    
    // Show progress indicator
    const bulkBar = document.getElementById('bulkActionsBar');
    const originalContent = bulkBar.innerHTML;
    bulkBar.innerHTML = '<div style="text-align: center; padding: 1rem;">Archiving cards...</div>';
    
    let successful = 0;
    let failed = 0;
    
    for (const cardId of selectedCards) {
        try {
            await apiFetch(`/api/cards/${cardId}/archive`, { method: 'POST' });
            successful++;
        } catch (err) {
            console.error(`Failed to archive card ${cardId}:`, err);
            failed++;
        }
    }
    
    // Restore original content
    bulkBar.innerHTML = originalContent;
    
    if (failed > 0) {
        alert(`Archived ${successful} cards successfully. ${failed} cards failed to archive.`);
    }
    
    toggleBulkSelectMode();
    refreshBoardAndMetrics();
}

// Template selection handler
document.getElementById('templateSelect').onchange = async (e) => {
    const templateId = e.target.value;
    if (!templateId) return;
    
    // Ensure templates are loaded
    if (!currentBoardTemplates || currentBoardTemplates.length === 0) {
        console.warn("Templates not loaded yet, loading now...");
        await loadBoardTemplates();
    }
    
    const template = currentBoardTemplates.find(t => t.id == templateId);
    if (!template) {
        console.error("Template not found:", templateId);
        return;
    }
    
    try {
        const templateData = JSON.parse(template.template_data);
        
        // Apply template data to form fields
        cardTitleField.value = templateData.title || '';
        cardDescriptionField.value = templateData.description || '';
        cardPriorityField.value = templateData.priority || 2;
        
        // TODO: Apply checklists from template when creating the card
    } catch (err) {
        console.error("Failed to apply template:", err);
    }
};

// Event listeners for Phase 3
document.getElementById('toggleViewBtn').onclick = toggleView;
document.getElementById('bulkCancelBtn').onclick = toggleBulkSelectMode;
document.getElementById('bulkMoveBtn').onclick = bulkMoveCards;
document.getElementById('bulkArchiveBtn').onclick = bulkArchiveCards;

// Add quick add to column headers
document.addEventListener('dblclick', (e) => {
    if (e.target.classList.contains('column-header')) {
        const columnId = e.target.closest('.column').dataset.id;
        enableQuickAdd(columnId);
    }
});

// Export functions for onclick handlers
window.changeCalendarMonth = changeCalendarMonth;
window.openCardById = openCardById;

// Enable bulk select with keyboard shortcut
document.addEventListener('keydown', (e) => {
    if (e.key === 'm' && !e.target.matches('input, textarea, select')) {
        toggleBulkSelectMode();
    }
});

//── Small Mode Functions
function checkSmallMode() {
    const wasSmallMode = isSmallMode;
    
    // Calculate available space for columns
    const dashboardArea = document.getElementById('dashboardArea');
    const boardContainer = document.getElementById('boardContainer');
    
    if (!boardContainer || !dashboardArea) return;
    
    // Get dashboard height
    const dashboardHeight = dashboardArea.offsetHeight;
    const windowHeight = window.innerHeight;
    const availableHeight = windowHeight - dashboardHeight - 120; // Account for header + filter bar
    
    // Check if window width can accommodate columns well
    const minColumnWidth = 300; // Minimum comfortable column width
    const maxColumnsForComfort = Math.floor(window.innerWidth / minColumnWidth);
    const totalColumns = currentBoardData?.columns?.length || 0;
    
    // Enter small mode if:
    // 1. Window width is <= dashboard height * 1.5, OR
    // 2. Can't comfortably fit more than 1 column, OR  
    // 3. Available height is too constrained
    isSmallMode = (
        window.innerWidth <= dashboardHeight * 1.5 ||
        maxColumnsForComfort <= 1 ||
        availableHeight < 300
    );
    
    if (isSmallMode && !wasSmallMode) {
        // Entering small mode
        boardContainer.classList.add('small-mode');
        currentColumnIndex = 0;
        updateColumnDisplay();
    } else if (!isSmallMode && wasSmallMode) {
        // Exiting small mode
        boardContainer.classList.remove('small-mode');
        // Show all columns
        const columns = boardContainer.querySelectorAll('.column');
        columns.forEach(col => col.classList.remove('active'));
    }
}

function navigateColumn(direction) {
    if (!isSmallMode || !currentBoardData) return;
    
    const totalColumns = currentBoardData.columns ? currentBoardData.columns.length : 0;
    if (totalColumns === 0) return;
    
    currentColumnIndex += direction;
    
    // Wrap around
    if (currentColumnIndex < 0) {
        currentColumnIndex = totalColumns - 1;
    } else if (currentColumnIndex >= totalColumns) {
        currentColumnIndex = 0;
    }
    
    updateColumnDisplay();
}

function updateColumnDisplay() {
    if (!isSmallMode || !currentBoardData) return;
    
    const boardContainer = document.getElementById('boardContainer');
    const columnNavTitle = document.getElementById('columnNavTitle');
    const prevBtn = document.getElementById('prevColumnBtn');
    const nextBtn = document.getElementById('nextColumnBtn');
    
    if (!boardContainer || !columnNavTitle) return;
    
    const columns = boardContainer.querySelectorAll('.column');
    const totalColumns = columns.length;
    
    if (totalColumns === 0) return;
    
    // Hide all columns
    columns.forEach(col => col.classList.remove('active'));
    
    // Show current column
    if (columns[currentColumnIndex]) {
        columns[currentColumnIndex].classList.add('active');
        const columnTitle = currentBoardData.columns[currentColumnIndex]?.title || 'Column';
        columnNavTitle.textContent = `${columnTitle} (${currentColumnIndex + 1}/${totalColumns})`;
    }
    
    // Update button states
    if (prevBtn) prevBtn.disabled = false;
    if (nextBtn) nextBtn.disabled = false;
}

// Touch support for small mode
let touchStartX = 0;
let touchEndX = 0;

function handleTouchStart(e) {
    if (!isSmallMode) return;
    touchStartX = e.changedTouches[0].screenX;
}

function handleTouchEnd(e) {
    if (!isSmallMode) return;
    touchEndX = e.changedTouches[0].screenX;
    handleSwipe();
}

function handleSwipe() {
    const swipeThreshold = 50; // Minimum distance for a swipe
    const swipeDistance = touchEndX - touchStartX;
    
    if (Math.abs(swipeDistance) > swipeThreshold) {
        if (swipeDistance > 0) {
            // Swipe right - go to previous column
            navigateColumn(-1);
        } else {
            // Swipe left - go to next column
            navigateColumn(1);
        }
    }
}

// Add touch listeners to board container
function addTouchSupport() {
    const boardContainer = document.getElementById('boardContainer');
    if (boardContainer) {
        boardContainer.addEventListener('touchstart', handleTouchStart, { passive: true });
        boardContainer.addEventListener('touchend', handleTouchEnd, { passive: true });
    }
}

// Make functions globally available
window.navigateColumn = navigateColumn;

//── Enhanced Initialization
async function initializeApp() {
    await loadBoards();
    await loadLabels();
    await loadBoardTemplates();
    await refreshBoardAndMetrics();
    
    // Initialize small mode
    checkSmallMode();
    
    // Add touch support for mobile
    addTouchSupport();
    
    // Add resize listener
    window.addEventListener('resize', checkSmallMode);
}

//── Initial Load
initializeApp();
</script></body></html>
"""

# Routes
# ────────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    app.logger.debug("GET / called")
    b = Board.query.first() 
    if not b: 
        app.logger.error("Board not found in index route. Check DB setup.")
        b = Board.query.first() 
        if not b:
             return "Error: Kanban board could not be initialized. Check server logs.", 500
    return render_template_string(TEMPLATE, board_name=b.name)

if __name__ == "__main__":
    app.logger.info(f"Starting Kanban app on port {PORT} with DB_URI: {DB_URI}")
    app.run(debug=True, port=PORT, use_reloader=False) 
