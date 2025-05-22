from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta # Added timedelta
from typing import Dict, List, Any # Added List, Any

from flask import Flask, jsonify, render_template_string, request
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
    needed = {"card": {"start_date": "DATE", "due_date": "DATE", "priority": "INTEGER DEFAULT 2"}}
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

# ORM models
# ────────────────────────────────────────────────────────────────────────────────
class Board(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), default="My Board", nullable=False)
    columns = db.relationship("Column", backref="board", cascade="all, delete", order_by="Column.position") # Added order_by

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    column_id = db.Column(db.Integer, db.ForeignKey("column.id"))

# DB init / seed
# ────────────────────────────────────────────────────────────────────────────────
with app.app_context():
    app.logger.info("Entered app_context for DB initialization.")
    ensure_columns() 
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
        "priority": card.priority, "priority_name": PRIO_MAP.get(card.priority, "N/A")
    }

def column_to_dict(col: Column) -> Dict:
    return {
        "id": col.id, "title": col.title, "position": col.position,
        "cards": sorted([card_to_dict(c) for c in col.cards], key=lambda x: x["position"])
    }

# API routes
# ────────────────────────────────────────────────────────────────────────────────
@app.get("/api/board")
def api_board_data(): # Renamed to avoid conflict with model name
    app.logger.debug("GET /api/board called")
    b = Board.query.first()
    if not b: return jsonify({"error": "Board not found"}), 404
    # Ensure columns are ordered by position for consistent display
    ordered_columns = sorted([column_to_dict(c) for c in b.columns], key=lambda x: x["position"])
    return jsonify({"id": b.id, "name": b.name, "columns": ordered_columns})


@app.get("/api/metrics")
def api_metrics():
    app.logger.debug("GET /api/metrics called")
    today = date.today()
    next_7_days_end = today + timedelta(days=7)

    total_cards_count = Card.query.count()
    total_columns_count = Column.query.count()
    
    avg_cards_per_column = (total_cards_count / total_columns_count) if total_columns_count > 0 else 0

    priority_counts = {p_val: Card.query.filter_by(priority=p_val).count() for p_val in PRIO_MAP.keys()}
    # Ensure all priorities are present in percentages, even if count is 0
    priority_percentages = {}
    for p_val, p_name in PRIO_MAP.items():
        count = priority_counts.get(p_val, 0)
        priority_percentages[p_name] = (count / total_cards_count * 100) if total_cards_count > 0 else 0

    priority_counts_named = {PRIO_MAP[p_val]: count for p_val, count in priority_counts.items()}


    overdue_cards_count = Card.query.filter(Card.due_date != None, Card.due_date < today).count()
    overdue_high_priority_count = Card.query.filter(
        Card.priority == 1, Card.due_date != None, Card.due_date < today
    ).count()
    
    cards_due_today_count = Card.query.filter(Card.due_date == today).count()
    cards_due_next_7_days_count = Card.query.filter(
        Card.due_date != None, Card.due_date >= today, Card.due_date < next_7_days_end
    ).count()

    done_column = Column.query.filter(Column.title.ilike("Done")).first()
    if not done_column: 
        done_column = Column.query.order_by(Column.position.desc()).first()

    cards_in_done_column_count = 0
    if done_column:
        cards_in_done_column_count = Card.query.filter_by(column_id=done_column.id).count()
    
    active_cards_count = total_cards_count - cards_in_done_column_count
    
    all_columns = Column.query.order_by(Column.position).all()
    column_details: List[Dict[str, Any]] = []
    for col in all_columns:
        card_count_in_col = len(col.cards) 
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
    title = (request.json or {}).get("title", "Untitled")
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
        db.session.add(card); db.session.commit()
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
:root{--bg:#f9fafb;--surface:#fff;--text:#111827;--muted:#6b7280;--card-bg:#f3f4f6;--high:#ef4444;--med:#f59e0b;--low:#10b981; --overlay-bg: rgba(0,0,0,0.5); --modal-bg: var(--surface); --input-bg: var(--card-bg); --button-primary-bg: #2563eb; --button-primary-text: #fff; --button-secondary-bg: var(--card-bg); --button-secondary-text: var(--text); --border-color: #e5e7eb; --shadow-sm: 0 1px 2px 0 rgba(0,0,0,.05); --shadow-md: 0 4px 6px -1px rgba(0,0,0,.1),0 2px 4px -2px rgba(0,0,0,.1); --shadow-lg: 0 10px 15px -3px rgba(0,0,0,.1),0 4px 6px -4px rgba(0,0,0,.1);
--chart-high-prio: var(--high); --chart-medium-prio: var(--med); --chart-low-prio: var(--low); --chart-bar-bg: #60a5fa; --chart-grid-color: rgba(0,0,0,0.05);}
[data-theme=dark]{--bg:#111827;--surface:#1f2937;--text:#f3f4f6;--muted:#9ca3af;--card-bg:#374151; --modal-bg: #1f2937; --input-bg: #374151; --button-secondary-bg: #374151; --border-color: #374151;
--chart-high-prio: #f87171; --chart-medium-prio: #fbbf24; --chart-low-prio: #34d399; --chart-bar-bg: #3b82f6; --chart-grid-color: rgba(255,255,255,0.1);}
html,body{height:100%;margin:0;font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--text);font-size:16px;line-height:1.5;}
header{display:flex;align-items:center;justify-content:space-between;padding:.75rem 1.5rem;background:var(--surface);box-shadow:var(--shadow-sm);border-bottom:1px solid var(--border-color);}
header h1 {font-size: 1.25rem; font-weight: 600; margin:0;}
#appControls { display: flex; align-items: center; gap: 0.75rem;}
.board{display:flex;gap:1rem;padding:1rem;overflow-x:auto;height:calc(100vh - 240px - 49px)} /* Adjusted for larger dashboard */
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
button{font-family:inherit; border-radius: 0.375rem; padding: 0.5rem 1rem; font-size: 0.875rem; cursor: pointer; border: 1px solid transparent; font-weight:500; transition: background-color 0.2s ease, border-color 0.2s ease;}
.add-card-btn{font-size:1.125rem;border:none;background:none;cursor:pointer;color:var(--muted); padding: 0.25rem; line-height:1;}
#addColBtn{border:1px solid var(--muted);background:var(--surface); color: var(--text);}
#addColBtn:hover{background:var(--card-bg);}
.filter-bar{display:flex;flex-wrap:wrap;gap:.75rem;padding:0.75rem 1.5rem;background:var(--surface);border-bottom:1px solid var(--border-color);align-items:center;}
.filter-bar input,.filter-bar select{padding:.375rem .75rem;border-radius:.375rem;border:1px solid var(--muted);background:var(--input-bg);color:var(--text); font-size:0.875rem;}
.filter-bar label{font-size:0.875rem; color: var(--muted); display:flex; align-items:center; gap: 0.25rem;}
#clearFilterBtn{border:1px solid var(--muted);background:var(--input-bg);color:var(--text)}

/* Dashboard Styles with Charts */
#dashboardArea { padding: 1rem 1.5rem; background: var(--bg); border-bottom: 1px solid var(--border-color); display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }
.dash-section { background: var(--surface); padding: 1.25rem; border-radius: .5rem; box-shadow: var(--shadow-md); display: flex; flex-direction: column;}
.dash-section h3 { font-size: 1.125rem; font-weight: 600; margin-top: 0; margin-bottom: 1rem; border-bottom: 1px solid var(--border-color); padding-bottom: 0.75rem; }
.dash-metric { display: flex; justify-content: space-between; align-items: center; font-size: 0.9rem; padding: 0.4rem 0; border-bottom: 1px dashed var(--border-color); }
.dash-metric:last-child { border-bottom: none; }
.dash-metric .label { color: var(--muted); }
.dash-metric .value { font-weight: 600; font-size:1rem;}
.chart-container { position: relative; margin: auto; height: 200px; width:100%; max-width:280px; /* For pie chart */ }
.bar-chart-container { position: relative; margin: auto; height: 220px; width:100%;}


/* Modal Styles */
.modal-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:var(--overlay-bg);display:none;align-items:center;justify-content:center;z-index:1000;padding:1rem;}
.modal{background:var(--modal-bg);padding:1.5rem;border-radius:.5rem;box-shadow:var(--shadow-lg);width:100%;max-width:500px; color: var(--text);max-height:90vh;overflow-y:auto;}
.modal h2{margin-top:0;margin-bottom:1.5rem;font-size:1.25rem; font-weight:600;}
.modal-form label{display:block;margin-bottom:.25rem;font-size:.875rem;font-weight:500;color:var(--muted);}
.modal-form input[type="text"],.modal-form textarea,.modal-form select,.modal-form input[type="date"]{width:100%;padding:.625rem .75rem;margin-bottom:.75rem;border-radius:.375rem;border:1px solid var(--muted);background:var(--input-bg);color:var(--text);font-family:inherit;box-sizing:border-box;font-size:0.875rem;}
.modal-form textarea{min-height:100px;resize:vertical;}
.modal-form input:focus, .modal-form textarea:focus, .modal-form select:focus {border-color: var(--button-primary-bg); box-shadow: 0 0 0 2px rgba(37,99,235,.2); outline:none;}
.modal-actions{display:flex;justify-content:flex-end;gap:.75rem;margin-top:1.5rem;}
.modal-actions button.primary{background-color:var(--button-primary-bg);color:var(--button-primary-text);border-color:transparent;}
.modal-actions button.primary:hover{background-color:#1d4ed8;}
.modal-actions button.secondary{background-color:var(--button-secondary-bg);color:var(--button-secondary-text);border:1px solid var(--muted);}
.modal-actions button.secondary:hover{background-color:var(--border-color);}
</style></head><body>
<header>
  <h1>{{ board_name }}</h1>
  <div id="appControls">
    <button id='addColBtn'>＋ Column</button>
    <button id='themeToggle' aria-label='Toggle theme'>🌓</button>
  </div>
</header>

<div id="dashboardArea">
  </div>

<div class='filter-bar'>
  <input id='searchInput' placeholder='Search cards…'>
  <select id='prioFilterSelect'>
    <option value=''>All Priorities</option><option value='1'>High</option><option value='2'>Medium</option><option value='3'>Low</option>
  </select>
  <label>Start: <input type='date' id='startFromInput'></label>
  <label>Due: <input type='date' id='endToInput'></label>
  <button id='clearFilterBtn'>✕ Clear</button>
</div>
<main class='board' id='boardContainer'></main>

<div id="cardModalOverlay" class="modal-overlay">
  <div class="modal">
    <h2 id="cardModalTitleEl">Create Card</h2>
    <form id="cardModalFormEl" class="modal-form">
      <input type="hidden" id="cardModalIdField">
      <input type="hidden" id="cardModalColumnIdField">
      <div>
        <label for="cardTitleField">Title</label>
        <input type="text" id="cardTitleField" name="title" required>
      </div>
      <div>
        <label for="cardDescriptionField">Description</label>
        <textarea id="cardDescriptionField" name="description"></textarea>
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
      <div class="modal-actions">
        <button type="button" id="cancelCardModalBtnEl" class="secondary">Cancel</button>
        <button type="submit" id="saveCardModalBtnEl" class="primary">Save Card</button>
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

//── DOM Elements
const boardContainerEl = document.getElementById('boardContainer');
const dashboardAreaEl = document.getElementById('dashboardArea');
const filterState = { q: '', prio: '', from: '', to: '' };
const PRIORITY_MAP_DISPLAY = {1: "High", 2: "Medium", 3: "Low"};

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

// Chart instances
let priorityPieChart = null;
let columnBarChart = null;

//── Filter Listeners
document.getElementById('searchInput').oninput = (e) => { filterState.q = e.target.value.toLowerCase(); applyFiltersUI(); };
document.getElementById('prioFilterSelect').oninput = (e) => { filterState.prio = e.target.value; applyFiltersUI(); };
document.getElementById('startFromInput').oninput = (e) => { filterState.from = e.target.value; applyFiltersUI(); };
document.getElementById('endToInput').oninput = (e) => { filterState.to = e.target.value; applyFiltersUI(); };
document.getElementById('clearFilterBtn').onclick = () => {
  filterState.q = ''; filterState.prio = ''; filterState.from = ''; filterState.to = '';
  document.getElementById('searchInput').value = '';
  document.getElementById('prioFilterSelect').value = '';
  document.getElementById('startFromInput').value = '';
  document.getElementById('endToInput').value = '';
  applyFiltersUI();
};

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
            apiFetch('/api/board'),
            apiFetch('/api/metrics')
        ]);
        if (boardData) renderBoardUI(boardData);
        if (metricsData) renderDashboardUI(metricsData);
        applyFiltersUI();
    } catch (err) {
        console.error("Refresh failed:", err);
    }
}

//── Dashboard Rendering with Charts
function renderDashboardUI(metrics) {
    dashboardAreaEl.innerHTML = ''; // Clear previous dashboard

    // Helper to create a section
    const createDashSection = (title) => {
        const section = document.createElement('div');
        section.className = 'dash-section';
        section.innerHTML = `<h3>${title}</h3>`;
        return section;
    };
    // Helper to create a metric item
    const createMetricItem = (label, value) => `<div class="dash-metric"><span class="label">${formatLabel(label)}:</span><span class="value">${value}</span></div>`;

    // Overall Stats Section
    const overallSection = createDashSection('Overall Stats');
    for (const [key, value] of Object.entries(metrics.overall_stats)) {
        overallSection.innerHTML += createMetricItem(key, value);
    }
    dashboardAreaEl.appendChild(overallSection);

    // Due Date Insights Section
    const dueDateSection = createDashSection('Due Date Insights');
    for (const [key, value] of Object.entries(metrics.due_date_insights)) {
        dueDateSection.innerHTML += createMetricItem(key, value);
    }
     // Add Overdue High Priority to Due Date section for thematic grouping
    dueDateSection.innerHTML += createMetricItem('Overdue High Priority', metrics.priority_insights.overdue_high_priority);
    dashboardAreaEl.appendChild(dueDateSection);

    // Priority Insights Section (Pie Chart)
    const prioritySection = createDashSection('Priority Distribution');
    const priorityCanvasContainer = document.createElement('div');
    priorityCanvasContainer.className = 'chart-container';
    const priorityCanvas = document.createElement('canvas');
    priorityCanvas.id = 'priorityPieChart';
    priorityCanvasContainer.appendChild(priorityCanvas);
    prioritySection.appendChild(priorityCanvasContainer);
    dashboardAreaEl.appendChild(prioritySection);

    if (priorityPieChart) priorityPieChart.destroy(); // Destroy old chart instance
    priorityPieChart = new Chart(priorityCanvas, {
        type: 'pie',
        data: {
            labels: metrics.priority_insights.labels,
            datasets: [{
                label: 'Cards by Priority',
                data: metrics.priority_insights.counts,
                backgroundColor: [
                    getComputedStyle(document.documentElement).getPropertyValue('--chart-high-prio').trim(), // High
                    getComputedStyle(document.documentElement).getPropertyValue('--chart-medium-prio').trim(), // Medium
                    getComputedStyle(document.documentElement).getPropertyValue('--chart-low-prio').trim()  // Low
                ],
                borderColor: getComputedStyle(document.documentElement).getPropertyValue('--surface').trim(),
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom', labels: { color: getComputedStyle(document.documentElement).getPropertyValue('--text').trim() } } }
        }
    });
    
    // Column Breakdown Section (Bar Chart)
    const columnSection = createDashSection('Cards per Column');
    const columnCanvasContainer = document.createElement('div');
    columnCanvasContainer.className = 'bar-chart-container';
    const columnCanvas = document.createElement('canvas');
    columnCanvas.id = 'columnBarChart';
    columnCanvasContainer.appendChild(columnCanvas);
    columnSection.appendChild(columnCanvasContainer);
    dashboardAreaEl.appendChild(columnSection);

    if (columnBarChart) columnBarChart.destroy(); // Destroy old chart instance
    const columnLabels = metrics.column_breakdown.map(col => col.name);
    const columnData = metrics.column_breakdown.map(col => col.card_count);
    const textColor = getComputedStyle(document.documentElement).getPropertyValue('--text').trim();
    const gridColor = getComputedStyle(document.documentElement).getPropertyValue('--chart-grid-color').trim();

    columnBarChart = new Chart(columnCanvas, {
        type: 'bar',
        data: {
            labels: columnLabels,
            datasets: [{
                label: 'Number of Cards',
                data: columnData,
                backgroundColor: getComputedStyle(document.documentElement).getPropertyValue('--chart-bar-bg').trim(),
                borderColor: getComputedStyle(document.documentElement).getPropertyValue('--chart-bar-bg').trim(),
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: 'y', // Horizontal bar chart
            scales: {
                x: { 
                    beginAtZero: true, 
                    ticks: { color: textColor, stepSize: 1 }, 
                    grid: { color: gridColor } 
                },
                y: { 
                    ticks: { color: textColor }, 
                    grid: { display: false } 
                }
            },
            plugins: { legend: { display: false } }
        }
    });
}

function formatLabel(key) {
    return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

//── Board Rendering
function renderBoardUI(boardData) {
    boardContainerEl.innerHTML = ''; 
    boardData.columns.forEach(column => {
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
        column.cards.forEach(card => cardsContainerEl.appendChild(createCardElement(card)));
        
        initializeSortable(cardsContainerEl);
        columnEl.querySelector('.add-card-btn').onclick = (e) => openCardModal(null, e.target.dataset.columnId);
    });
}

function createCardElement(card) {
    const cardEl = document.createElement('div');
    cardEl.className = 'card';
    cardEl.dataset.id = card.id;
    cardEl.dataset.prio = card.priority;
    cardEl.dataset.start = card.start_date || '';
    cardEl.dataset.due = card.due_date || '';

    let cardHTML = `<strong>${card.title}</strong>`;
    if (card.description) {
        cardHTML += `<p>${card.description.substring(0, 100) + (card.description.length > 100 ? '...' : '')}</p>`;
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
    cardModalForm.reset();
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

    const cardData = {
        title: title,
        description: cardDescriptionField.value.trim(),
        priority: parseInt(cardPriorityField.value, 10),
        start_date: cardStartDateField.value || null,
        due_date: cardDueDateField.value || null,
        column_id: parseInt(cardModalColumnIdField.value, 10)
    };

    try {
        const url = cardId ? `/api/card/${cardId}` : '/api/card';
        const method = cardId ? 'PATCH' : 'POST';
        await apiFetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cardData) });
        closeCardModal();
        refreshBoardAndMetrics();
    } catch (err) { console.error("Failed to save card:", err); }
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

//── Filter Application (UI side)
function applyFiltersUI() {
    document.querySelectorAll('.card').forEach(cardElement => {
        const titleDescContent = cardElement.textContent || ""; 
        const qOk = !filterState.q || titleDescContent.toLowerCase().includes(filterState.q);
        const pOk = !filterState.prio || cardElement.dataset.prio === filterState.prio;
        const sOk = !filterState.from || (cardElement.dataset.start && cardElement.dataset.start >= filterState.from);
        const dOk = !filterState.to || (cardElement.dataset.due && cardElement.dataset.due <= filterState.to);
        cardElement.style.display = qOk && pOk && sOk && dOk ? 'block' : 'none';
    });
}

//── Add Column
document.getElementById('addColBtn').onclick = async () => {
    const name = prompt('New column title:');
    if (!name || !name.trim()) return;
    try {
        await apiFetch('/api/column', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: name.trim() }) });
        refreshBoardAndMetrics();
    } catch (err) { console.error("Failed to add column:", err); }
};

//── Initial Load
refreshBoardAndMetrics();
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
