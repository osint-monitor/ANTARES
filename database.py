import sqlite3
from datetime import datetime

DB_NAME = 'antares.db'

# Crea il database se non esiste, 
# oppure lo apre se già presente.
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Tabella task esistente (con group_id già presente)
    c.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_text TEXT,
            actor_id TEXT,
            backend TEXT DEFAULT 'local',
            model_file TEXT,
            status TEXT DEFAULT 'pending',
            result_text TEXT,
            blue_team_result TEXT,
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            group_id TEXT,
            lang TEXT DEFAULT 'it'
        )
    ''')
    
    # Tabella gruppi comparativi
    c.execute('''
        CREATE TABLE IF NOT EXISTS task_groups (
            group_id TEXT PRIMARY KEY,
            base_task_id INTEGER,
            fact_text_preview TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            actor_count INTEGER,
            status TEXT DEFAULT 'pending'
        )
    ''')
    
        
    conn.commit()
    conn.close()


def add_task(fact_text, actor_id, backend='local', model_file=None, group_id=None, lang='it'):
    conn = sqlite3.connect('antares.db')
    c = conn.cursor()
    c.execute(
        "INSERT INTO tasks (fact_text, actor_id, backend, model_file, group_id, lang, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
        (fact_text, actor_id, backend, model_file, group_id, lang)
    )
    task_id = c.lastrowid
    conn.commit()
    conn.close()
    return task_id


def add_group(group_id, base_task_id, fact_text_preview, actor_count):
    """Registra un nuovo gruppo comparativo."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "INSERT INTO task_groups (group_id, base_task_id, fact_text_preview, actor_count, status) VALUES (?, ?, ?, ?, 'pending')",
        (group_id, base_task_id, fact_text_preview, actor_count)
    )
    conn.commit()
    conn.close()


def get_all_groups():
    """Lista tutti i gruppi comparativi."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM task_groups ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_group(group_id):
    """Recupera un singolo gruppo."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM task_groups WHERE group_id = ?", (group_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def update_group_status(group_id):
    """Sincronizza lo stato del gruppo con lo stato dei suoi task."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT status FROM tasks WHERE group_id = ?", (group_id,))
    statuses = [r[0] for r in c.fetchall()]
    
    if not statuses:
        conn.close()
        return
    
    if all(s == 'completed' for s in statuses):
        new_status = 'completed'
    elif any(s == 'error' for s in statuses):
        new_status = 'error'
    else:
        new_status = 'processing'
    
    c.execute("UPDATE task_groups SET status = ? WHERE group_id = ?", (new_status, group_id))
    conn.commit()
    conn.close()


def get_task_status(task_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = c.fetchone()
    conn.close()
    return task


def get_all_tasks():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM tasks ORDER BY id DESC")
    tasks = c.fetchall()
    conn.close()
    return tasks

def get_tasks_by_group(group_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM tasks WHERE group_id = ? ORDER BY id ASC", (group_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]