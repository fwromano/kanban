from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from typing import Dict

from flask import Flask, jsonify, render_template_string, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import scoped_session, sessionmaker # For scoped session

# Configure logging early and globally
import logging
logging.basicConfig(level=logging.DEBUG) # Set to DEBUG for verbose output globally

DB_URI = os.getenv("KANBAN_DB", "sqlite:///kanban.db")
PORT   = int(os.getenv("KANBAN_PORT", 5000))

app = Flask(__name__)
# Ensure Flask's logger also respects the DEBUG level
app.logger.setLevel(logging.DEBUG)

app.config.update(
    SQLALCHEMY_DATABASE_URI=DB_URI, 
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ECHO=True  # Enable SQLAlchemy SQL statement logging
)

# Instantiate SQLAlchemy without the app object initially
db = SQLAlchemy()

# ────────────────────────────────────────────────────────────────────────────────
# Auto‑migrate SQLite (adds new columns without losing data)
# ────────────────────────────────────────────────────────────────────────────────

def ensure_columns() -> None:
    if not DB_URI.startswith("sqlite:///"):
        app.logger.debug("Database is not SQLite. Skipping auto-migration.")
        return
    
    path = DB_URI.replace("sqlite:///", "", 1)
    
    if not os.path.exists(path):
        app.logger.debug(f"Database file {path} does not exist. Skipping auto-migration (SQLAlchemy's create_all will handle).")
        return
    
    app.logger.info(f"Auto-migration: Checking schema for existing SQLite database: {path}")
    needed = {
        "card": {
            "start_date": "DATE",
            "due_date": "DATE",
            "priority": "INTEGER DEFAULT 2",
        }
    }
    
    conn = None
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        app.logger.debug(f"Auto-migration: Successfully connected to {path} for schema modification.")
        
        for table_name, cols_to_add in needed.items():
            app.logger.debug(f"Auto-migration: Processing table: {table_name}")

            table_exists_query = f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';"
            cur.execute(table_exists_query)
            if not cur.fetchone():
                app.logger.warning(f"Auto-migration: Table '{table_name}' does not exist in the database. SQLAlchemy's create_all should create it. Skipping column additions for this table.")
                continue

            app.logger.debug(f"Auto-migration: Table '{table_name}' exists. Fetching its columns.")
            cur.execute(f"PRAGMA table_info({table_name})")
            fetched_rows = cur.fetchall()
            existing_columns = {row[1] for row in fetched_rows}
            app.logger.debug(f"Auto-migration: Existing columns in '{table_name}': {existing_columns}")
            
            for col_name, col_definition in cols_to_add.items():
                if col_name not in existing_columns:
                    app.logger.info(f"Auto-migration: Adding column '{col_name}' ({col_definition}) to table '{table_name}'.")
                    alter_query = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_definition}"
                    app.logger.debug(f"Auto-migration: Executing: {alter_query}")
                    cur.execute(alter_query)
                else:
                    app.logger.debug(f"Auto-migration: Column '{col_name}' already exists in '{table_name}'.")
        
        conn.commit()
        app.logger.info("Auto-migration: SQLite schema migration changes committed successfully.")
    except sqlite3.Error as e:
        app.logger.error(f"Auto-migration: SQLite error during migration: {e}")
        if conn:
            app.logger.debug("Auto-migration: Rolling back changes due to SQLite error.")
            conn.rollback()
    finally:
        if conn:
            conn.close()
            app.logger.debug("Auto-migration: SQLite connection for schema modification closed.")

# ORM models (definition remains the same)
# ────────────────────────────────────────────────────────────────────────────────
class Board(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), default="My Board", nullable=False)
    columns = db.relationship("Column", backref="board", cascade="all, delete")

class Column(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(64), nullable=False)
    position = db.Column(db.Integer, default=0)
    board_id = db.Column(db.Integer, db.ForeignKey("board.id"))
    cards = db.relationship("Card", backref="column", cascade="all, delete")

class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, default="")
    position = db.Column(db.Integer, default=0)
    start_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    priority = db.Column(db.Integer, default=2)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    column_id = db.Column(db.Integer, db.ForeignKey("column.id"))

# ────────────────────────────────────────────────────────────────────────────────
# DB init / seed
# ────────────────────────────────────────────────────────────────────────────────
with app.app_context():
    app.logger.info("Entered app_context for DB initialization.")
    
    ensure_columns() 
    
    app.logger.info("Initializing SQLAlchemy with the app (db.init_app(app)).")
    db.init_app(app)
    app.logger.info("SQLAlchemy initialized with the app.")

    app.logger.info("Executing db.create_all(). Check console for CREATE TABLE statements.")
    db.create_all()
    app.logger.info("db.create_all() completed.")

    Session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=db.engine))
    temp_session = Session()
    app.logger.debug("Created temporary session for seeding check.")

    try:
        board_exists = temp_session.query(Board).first()
        if not board_exists:
            app.logger.info("No board found using temporary session, seeding initial data.")
            board = Board(name="Kanban")
            db.session.add(board)
            db.session.flush() 
            app.logger.debug(f"Board flushed, ID: {board.id}")
            for i, t in enumerate(["Backlog", "In Progress", "Done"]):
                db.session.add(Column(title=t, position=i, board_id=board.id)) 
            db.session.commit()
            app.logger.info("Initial data seeded using db.session.")
        else:
            app.logger.info(f"Existing board found (ID: {board_exists.id}) using temporary session, skipping seed.")
    except Exception as e:
        app.logger.error(f"Error during seeding check or seeding: {e}")
        temp_session.rollback() 
        db.session.rollback()   
    finally:
        app.logger.debug("Removing temporary session for seeding check.")
        Session.remove() 

    app.logger.info("Exited app_context for DB initialization.")

# Helpers (definition remains the same)
# ────────────────────────────────────────────────────────────────────────────────
PRIO_MAP = {1: "High", 2: "Medium", 3: "Low"}
PRIO_MAP_JS = {v: k for k, v in PRIO_MAP.items()} # For JS, mapping name to value

def parse_date(s: str | None):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except ValueError:
        return None

def card_to_dict(card: Card) -> Dict:
    return {
        "id": card.id,
        "title": card.title,
        "description": card.description,
        "position": card.position,
        "column_id": card.column_id,
        "start_date": card.start_date.isoformat() if card.start_date else None,
        "due_date": card.due_date.isoformat() if card.due_date else None,
        "priority": card.priority,
        "priority_name": PRIO_MAP.get(card.priority, "Medium")
    }

def column_to_dict(col: Column) -> Dict:
    return {
        "id": col.id,
        "title": col.title,
        "position": col.position,
        "cards": sorted([card_to_dict(c) for c in col.cards], key=lambda x: x["position"]),
    }

# API routes (definitions remain the same)
# ────────────────────────────────────────────────────────────────────────────────
@app.get("/api/board")
def api_board():
    app.logger.debug("GET /api/board called")
    b = Board.query.first()
    if not b:
        app.logger.warning("/api/board: Board not found")
        return jsonify({"error": "Board not found"}), 404
    return jsonify({
        "id": b.id,
        "name": b.name,
        "columns": sorted([column_to_dict(c) for c in b.columns], key=lambda x: x["position"]),
    })

@app.get("/api/metrics")
def api_metrics():
    app.logger.debug("GET /api/metrics called")
    total = Card.query.count()
    by_pri_counts = {p_val: Card.query.filter_by(priority=p_val).count() for p_val in PRIO_MAP.keys()}
    # Format for frontend to use priority names as keys
    by_pri_display = {PRIO_MAP[p_val]: count for p_val, count in by_pri_counts.items()}

    overdue = Card.query.filter(Card.due_date != None, Card.due_date < date.today()).count()
    board = Board.query.first()
    if not board:
        app.logger.warning("/api/metrics: Board not found")
        return jsonify({"error": "Board not found, cannot calculate metrics"}), 404
    return jsonify({
        "total": total,
        "by_priority": by_pri_display, # Use display version
        "overdue": overdue,
        "columns": {c.title: len(c.cards) for c in board.columns},
    })

@app.post("/api/column")
def api_add_column():
    app.logger.debug("POST /api/column called")
    title = (request.json or {}).get("title", "Untitled")
    board = Board.query.first()
    if not board:
        app.logger.warning("/api/column: Board not found")
        return jsonify({"error": "Board not found, cannot add column"}), 404
    col = Column(title=title, position=len(board.columns), board_id=board.id) 
    db.session.add(col); db.session.commit()
    app.logger.info(f"/api/column: Column '{title}' added.")
    return jsonify(column_to_dict(col)), 201

@app.post("/api/card")
@app.patch("/api/card/<int:cid>")
def api_card(cid: int | None = None):
    data = request.json or {}
    if request.method == "POST":
        app.logger.debug(f"POST /api/card called with data: {data}")
        column_id_val = data.get("column_id")
        if column_id_val is None:
            app.logger.warning("/api/card (POST): column_id is required")
            return jsonify({"error": "column_id is required"}), 400
        
        target_column = Column.query.get(column_id_val)
        if not target_column: 
            app.logger.warning(f"/api/card (POST): Column with id {column_id_val} not found")
            return jsonify({"error": f"Column with id {column_id_val} not found"}), 404

        raw_priority = data.get("priority", "2") 
        try:
            priority_val = int(raw_priority)
            if priority_val not in PRIO_MAP.keys(): 
                app.logger.warning(f"/api/card (POST): Invalid priority value {priority_val}")
                return jsonify({"error": f"Priority must be one of {list(PRIO_MAP.keys())}"}), 400
        except (ValueError, TypeError):
            app.logger.warning(f"/api/card (POST): Priority must be an integer, got {raw_priority}")
            return jsonify({"error": f"Priority must be an integer ({list(PRIO_MAP.keys())})"}), 400

        card = Card(
            title=data.get("title", "Untitled Card"), # Ensure a default title
            description=data.get("description", ""),
            column_id=column_id_val, 
            position=data.get("position", 0), 
            start_date=parse_date(data.get("start_date")),
            due_date=parse_date(data.get("due_date")),
            priority=priority_val, 
        )
        if not card.title: # Double check title isn't empty string from form
            card.title = "Untitled Card"
            
        db.session.add(card); db.session.commit()
        app.logger.info(f"/api/card (POST): Card '{card.title}' created with id {card.id}.")
        return jsonify(card_to_dict(card)), 201
    
    # PATCH
    app.logger.debug(f"PATCH /api/card/{cid} called with data: {data}")
    card = Card.query.get_or_404(cid)
    
    if "title" in data and data["title"]: # Ensure title is not empty
        card.title = data["title"]
    elif "title" in data and not data["title"]: # Prevent empty title on update
        app.logger.warning(f"/api/card (PATCH): Title cannot be empty for card {cid}")
        return jsonify({"error": "Title cannot be empty"}), 400


    for f in ("description", "column_id", "position"): # Title handled above
        if f in data:
            if f == "column_id": 
                target_column = Column.query.get(data[f])
                if not target_column:
                    app.logger.warning(f"/api/card (PATCH): Target column {data[f]} for card {cid} not found.")
                    return jsonify({"error": f"Column with id {data[f]} not found"}), 404
            setattr(card, f, data[f])
            
    if "start_date" in data:
        card.start_date = parse_date(data["start_date"])
    if "due_date" in data:
        card.due_date = parse_date(data["due_date"])
        
    if "priority" in data:
        raw_priority = data["priority"]
        if raw_priority is None or raw_priority == "": # Handle empty string from form
            card.priority = 2 # Default
        else:
            try:
                priority_val = int(raw_priority)
                if priority_val not in PRIO_MAP.keys():
                    app.logger.warning(f"/api/card (PATCH): Invalid priority {priority_val} for card {cid}")
                    return jsonify({"error": f"Priority must be one of {list(PRIO_MAP.keys())}"}), 400
                card.priority = priority_val
            except (ValueError, TypeError):
                app.logger.warning(f"/api/card (PATCH): Priority for card {cid} must be int, got {raw_priority}")
                return jsonify({"error": f"Priority must be an integer ({list(PRIO_MAP.keys())})"}), 400
                
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

# ────────────────────────────────────────────────────────────────────────────────
# Front‑end template (HTML + JS inline)
# ────────────────────────────────────────────────────────────────────────────────
TEMPLATE = r"""
<!DOCTYPE html><html lang='en'><head>
<meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{{ board_name }} – Kanban</title>
<link rel='preconnect' href='https://fonts.googleapis.com'>
<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap' rel='stylesheet'>
<style>
:root{--bg:#f9fafb;--surface:#fff;--text:#111827;--muted:#6b7280;--card:#f3f4f6;--high:#ef4444;--med:#f59e0b;--low:#10b981; --overlay-bg: rgba(0,0,0,0.5); --modal-bg: var(--surface); --input-bg: var(--card); --button-primary-bg: #2563eb; --button-primary-text: #fff; --button-secondary-bg: var(--card); --button-secondary-text: var(--text);}
[data-theme=dark]{--bg:#1f2937;--surface:#111827;--text:#f3f4f6;--muted:#9ca3af;--card:#374151; --modal-bg: #1f2937; --input-bg: #374151; --button-secondary-bg: #374151; --button-secondary-text: var(--text);}
html,body{height:100%;margin:0;font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--text)}
header{display:flex;align-items:center;justify-content:space-between;padding:.75rem 1rem;background:var(--surface);box-shadow:0 1px 2px rgba(0,0,0,.05)}
#dash{display:flex;gap:1rem;align-items:center}
.dash-item{padding:.25rem .5rem;border-radius:.375rem;background:var(--card);font-size:.875rem}
.board{display:flex;gap:1rem;padding:1rem;overflow-x:auto;height:calc(100% - 112px)}
.column{background:var(--surface);border-radius:.5rem;display:flex;flex-direction:column;min-width:280px;max-height:100%; box-shadow: 0 1px 3px 0 rgba(0,0,0,.1), 0 1px 2px -1px rgba(0,0,0,.1);}
.column-header{display:flex;align-items:center;justify-content:space-between;padding:.75rem;border-bottom:1px solid var(--card);font-weight:600}
.cards{flex:1;overflow-y:auto;display:flex;flex-direction:column;padding:.5rem;gap:.5rem}
.card{background:var(--card);border-radius:.5rem;padding:.75rem;cursor:pointer; box-shadow: 0 1px 2px 0 rgba(0,0,0,.05);}
.card:hover{box-shadow: 0 4px 6px -1px rgba(0,0,0,.1), 0 2px 4px -2px rgba(0,0,0,.1);}
.card[data-prio="1"]{border-left:4px solid var(--high)}
.card[data-prio="2"]{border-left:4px solid var(--med)}
.card[data-prio="3"]{border-left:4px solid var(--low)}
button{font-family:inherit; border-radius: 0.375rem; padding: 0.5rem 0.75rem; font-size: 0.875rem; cursor: pointer; border: 1px solid transparent;}
.add-card{font-size:1.25rem;border:none;background:none;cursor:pointer;color:var(--muted); padding: 0.25rem;}
#addCol{margin-left:1rem;border:1px solid var(--muted);background:var(--surface); color: var(--text);}
#addCol:hover{background:var(--card);}
.filter{display:flex;gap:.5rem;padding:.5rem 1rem;background:var(--surface);border-bottom:1px solid var(--card);align-items:center;}
.filter input,.filter select{padding:.25rem .5rem;border-radius:.375rem;border:1px solid var(--muted);background:var(--input-bg);color:var(--text)}
.filter label{font-size:0.875rem; color: var(--muted); display:flex; align-items:center; gap: 0.25rem;}
#clearFilter{border:1px solid var(--muted);background:var(--input-bg);color:var(--text)}

/* Modal Styles */
.modal-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:var(--overlay-bg);display:none;align-items:center;justify-content:center;z-index:1000;}
.modal{background:var(--modal-bg);padding:1.5rem;border-radius:.5rem;box-shadow:0 10px 15px -3px rgba(0,0,0,.1),0 4px 6px -4px rgba(0,0,0,.1);width:90%;max-width:500px; color: var(--text);}
.modal h2{margin-top:0;margin-bottom:1rem;font-size:1.25rem;}
.modal-form label{display:block;margin-bottom:.25rem;font-size:.875rem;font-weight:600;}
.modal-form input[type="text"],.modal-form textarea,.modal-form select,.modal-form input[type="date"]{width:calc(100% - 1rem);padding:.5rem;margin-bottom:.75rem;border-radius:.375rem;border:1px solid var(--muted);background:var(--input-bg);color:var(--text);font-family:inherit;}
.modal-form textarea{min-height:80px;resize:vertical;}
.modal-actions{display:flex;justify-content:flex-end;gap:.5rem;margin-top:1rem;}
.modal-actions button.primary{background-color:var(--button-primary-bg);color:var(--button-primary-text);border-color:transparent;}
.modal-actions button.secondary{background-color:var(--button-secondary-bg);color:var(--button-secondary-text);border:1px solid var(--muted);}
</style></head><body>
<header>
  <div><strong>{{ board_name }}</strong><button id='addCol'>＋ Column</button></div>
  <div id='dash'></div>
  <button id='themeToggle' aria-label='Toggle theme'>🌓</button>
</header>
<div class='filter'>
  <input id='search' placeholder='Search…'>
  <select id='prioFilter'>
    <option value=''>Priority</option><option value='1'>High</option><option value='2'>Medium</option><option value='3'>Low</option>
  </select>
  <label>Start <input type='date' id='startFrom'></label>
  <label>Due <input type='date' id='endTo'></label>
  <button id='clearFilter'>✕</button>
</div>
<main class='board' id='board'></main>

<div id="cardModalOverlay" class="modal-overlay">
  <div class="modal">
    <h2 id="cardModalTitle">Create Card</h2>
    <form id="cardModalForm" class="modal-form">
      <input type="hidden" id="cardModalId">
      <input type="hidden" id="cardModalColumnId">
      <div>
        <label for="cardTitle">Title</label>
        <input type="text" id="cardTitle" name="title" required>
      </div>
      <div>
        <label for="cardDescription">Description</label>
        <textarea id="cardDescription" name="description"></textarea>
      </div>
      <div>
        <label for="cardPriority">Priority</label>
        <select id="cardPriority" name="priority">
          <option value="1">High</option>
          <option value="2" selected>Medium</option>
          <option value="3">Low</option>
        </select>
      </div>
      <div>
        <label for="cardStartDate">Start Date</label>
        <input type="date" id="cardStartDate" name="start_date">
      </div>
      <div>
        <label for="cardDueDate">Due Date</label>
        <input type="date" id="cardDueDate" name="due_date">
      </div>
      <div class="modal-actions">
        <button type="button" id="cancelCardModal" class="secondary">Cancel</button>
        <button type="submit" id="saveCardModal" class="primary">Save Card</button>
      </div>
    </form>
  </div>
</div>

<script src='https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js'></script>
<script>
//── theme toggle
const themeToggleEl = document.getElementById('themeToggle');
const setTheme=t=>{document.documentElement.setAttribute('data-theme',t); themeToggleEl.textContent = t === 'dark' ? '☀️' : '🌓';};
setTheme(localStorage.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'));
themeToggleEl.onclick=()=>{const next=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';setTheme(next);localStorage.theme=next};

//── elements
const boardEl=document.getElementById('board');
const dashEl=document.getElementById('dash');
const filt={q:'',prio:'',from:'',to:''};
const PRIO_MAP_JS_FRONTEND = {1: "High", 2: "Medium", 3: "Low"};

// Card Modal Elements
const cardModalOverlay = document.getElementById('cardModalOverlay');
const cardModalForm = document.getElementById('cardModalForm');
const cardModalTitleEl = document.getElementById('cardModalTitle');
const cardModalIdInput = document.getElementById('cardModalId');
const cardModalColumnIdInput = document.getElementById('cardModalColumnId');
const cardTitleInput = document.getElementById('cardTitle');
const cardDescriptionInput = document.getElementById('cardDescription');
const cardPriorityInput = document.getElementById('cardPriority');
const cardStartDateInput = document.getElementById('cardStartDate');
const cardDueDateInput = document.getElementById('cardDueDate');
const cancelCardModalBtn = document.getElementById('cancelCardModal');

//── filter inputs listeners
document.getElementById('search').oninput = (e) => { filt.q = e.target.value.toLowerCase(); applyFilters(); };
document.getElementById('prioFilter').oninput = (e) => { filt.prio = e.target.value; applyFilters(); }; // Changed ID
document.getElementById('startFrom').oninput = (e) => { filt.from = e.target.value; applyFilters(); };
document.getElementById('endTo').oninput = (e) => { filt.to = e.target.value; applyFilters(); };
document.getElementById('clearFilter').onclick = () => {
  Object.keys(filt).forEach(k => filt[k] = '');
  document.querySelectorAll('.filter input, .filter select').forEach(e => e.value = '');
  applyFilters();
};

//── API helpers
const j=async (u,opts)=>{
    const res = await fetch(u,opts);
    if (!res.ok) {
        const errData = await res.json().catch(() => ({error: "Request failed with status " + res.status, detail: res.statusText }));
        console.error("API Error:", errData);
        alert(`Error: ${errData.error || 'Unknown API error'}\n${errData.detail || ''}`);
        throw new Error(errData.error || "API request failed");
    }
    if (res.status === 204) return null; 
    return res.json();
};

//── refresh board + dash
function refresh(){Promise.all([j('/api/board'),j('/api/metrics')]).then(([b,m])=>{if(b)renderBoard(b); if(m)renderDash(m);applyFilters()}).catch(err => console.error("Refresh failed:", err))}

//── dashboard render
function renderDash(m){
  dashEl.innerHTML = `<span class='dash-item'>Total: ${m.total}</span>` +
  Object.entries(m.by_priority).map(([name,v])=>`<span class='dash-item'>${name}: ${v}</span>`).join('') +
  `<span class='dash-item'>Overdue: ${m.overdue}</span>`;
}

//── board render
function renderBoard(data){boardEl.innerHTML='';data.columns.forEach(col=>{
  const colEl=document.createElement('div');colEl.className='column';colEl.dataset.id=col.id;
  colEl.innerHTML=`<div class='column-header'><span>${col.title}</span><button class='add-card' data-column-id='${col.id}'>＋</button></div><div class='cards'></div>`;
  boardEl.appendChild(colEl);
  const cardsC=colEl.querySelector('.cards');
  col.cards.forEach(c=>cardsC.appendChild(renderCard(c)));
  enableDnD(cardsC);
  colEl.querySelector('.add-card').onclick = (e) => openCardModal(null, e.target.dataset.columnId);
})}

function renderCard(c){const d=document.createElement('div');d.className='card';d.dataset.id=c.id;d.dataset.prio=c.priority;
  d.dataset.start=c.start_date||'';d.dataset.due=c.due_date||'';
  
  let cardHTML = `<strong>${c.title}</strong>`;
  if (c.description) cardHTML += `<p style="font-size:0.8em; margin-top:4px; color:var(--muted);">${c.description.substring(0,100)}${c.description.length > 100 ? '...' : ''}</p>`;
  
  const prioName = PRIO_MAP_JS_FRONTEND[c.priority] || 'Medium';
  cardHTML += `<div style="font-size:0.75em; margin-top:6px; color:var(--muted);">Priority: ${prioName}</div>`;

  if (c.start_date || c.due_date) {
    cardHTML += `<div style="font-size:0.75em; margin-top:2px; color:var(--muted);">`;
    if (c.start_date) cardHTML += `<span>Start: ${c.start_date}</span>`;
    if (c.start_date && c.due_date) cardHTML += ` | `;
    if (c.due_date) cardHTML += `<span>Due: ${c.due_date}</span>`;
    cardHTML += `</div>`;
  }
  d.innerHTML = cardHTML;

  d.onclick=(e)=>{ if (e.target.closest('button')) return; openCardModal(c)};
  d.oncontextmenu=e=>{e.preventDefault();if(confirm('Delete card?'))deleteCard(c.id)};return d}

//── Card Modal Logic
function openCardModal(card = null, columnId = null) {
  cardModalForm.reset(); // Clear previous form data
  if (card) { // Editing existing card
    cardModalTitleEl.textContent = 'Edit Card';
    cardModalIdInput.value = card.id;
    cardTitleInput.value = card.title;
    cardDescriptionInput.value = card.description || '';
    cardPriorityInput.value = card.priority || '2';
    cardStartDateInput.value = card.start_date || '';
    cardDueDateInput.value = card.due_date || '';
    cardModalColumnIdInput.value = card.column_id; // Store for potential re-assignment if not changed by D&D
  } else { // Creating new card
    cardModalTitleEl.textContent = 'Create Card';
    cardModalIdInput.value = ''; // No ID for new card
    cardModalColumnIdInput.value = columnId;
    cardPriorityInput.value = '2'; // Default priority
  }
  cardModalOverlay.style.display = 'flex';
}

function closeCardModal() {
  cardModalOverlay.style.display = 'none';
}

cancelCardModalBtn.onclick = closeCardModal;
cardModalOverlay.onclick = (e) => { // Close if clicking on overlay
  if (e.target === cardModalOverlay) {
    closeCardModal();
  }
};

cardModalForm.onsubmit = async (e) => {
  e.preventDefault();
  const cardId = cardModalIdInput.value;
  const title = cardTitleInput.value.trim();
  if (!title) {
    alert("Title is required.");
    return;
  }

  const cardData = {
    title: title,
    description: cardDescriptionInput.value.trim(),
    priority: parseInt(cardPriorityInput.value, 10),
    start_date: cardStartDateInput.value || null,
    due_date: cardDueDateInput.value || null,
    column_id: parseInt(cardModalColumnIdInput.value, 10) // This is for new cards or if not D&D
  };

  try {
    if (cardId) { // Editing existing card
      await j(`/api/card/${cardId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cardData)
      });
    } else { // Creating new card
      await j('/api/card', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cardData)
      });
    }
    closeCardModal();
    refresh();
  } catch (err) {
    // Error already alerted by j()
    console.error("Failed to save card:", err);
  }
};

//── Delete Card (kept separate from modal for now)
async function deleteCard(id){
  try {
    await j(`/api/card/${id}`,{method:'DELETE'});
    refresh();
  } catch(e) {/* error already handled by j() */}
}

//── drag‑and‑drop
function enableDnD(cont){new Sortable(cont,{group:'kanban',animation:150,onEnd:async e=>{
  const id=e.item.dataset.id;const newColumnId=e.to.parentElement.dataset.id;const newPosition=[...e.to.children].indexOf(e.item);
  try {
    await j(`/api/card/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({column_id: parseInt(newColumnId),position:newPosition})})
    // OPTIONAL: Could do a partial refresh or update card data locally if performance is an issue
    // For simplicity, a full refresh is robust.
    refresh(); 
  } catch(e) { /* error handled by j() */ }
}})}

//── filter apply
function applyFilters(){document.querySelectorAll('.card').forEach(cardEl=>{ // Renamed to cardEl to avoid conflict
  const qOk=!filt.q||cardEl.textContent.toLowerCase().includes(filt.q);
  const pOk=!filt.prio||cardEl.dataset.prio===filt.prio;
  const sOk=!filt.from||(cardEl.dataset.start&&cardEl.dataset.start>=filt.from);
  const dOk=!filt.to||(cardEl.dataset.due&&cardEl.dataset.due<=filt.to);
  cardEl.style.display=qOk&&pOk&&sOk&&dOk?'block':'none';
})}

//── column create
document.getElementById('addCol').onclick=async()=>{
  const name=prompt('Column title?'); // Keeping prompt for column add for now
  if(!name)return;
  try {
    await j('/api/column',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:name})});
    refresh();
  } catch(e) {/* error already handled by j() */}
}

//── bootstrap
refresh();
</script></body></html>
"""

# ────────────────────────────────────────────────────────────────────────────────
# Routes
# ────────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    app.logger.debug("GET / called")
    b = Board.query.first() 
    if not b: 
        app.logger.error("Board not found in index route even after initialization. This indicates a problem with DB setup or seeding.")
        b = Board.query.first() 
        if not b:
             return "Error: Kanban board could not be initialized or found. Check logs.", 500
    return render_template_string(TEMPLATE, board_name=b.name)

if __name__ == "__main__":
    app.logger.info(f"Starting Kanban app on port {PORT} with DB_URI: {DB_URI}")
    # Disable reloader for stable DB initialization testing
    # For normal development, you might want use_reloader=True, but be aware of DB init.
    app.run(debug=True, port=PORT, use_reloader=False) 
