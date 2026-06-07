import sqlite3
from datetime import datetime

DB_PATH = "marketer_db.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS account_session (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT,
        api_id INTEGER,
        api_hash TEXT,
        session_string TEXT,
        status TEXT DEFAULT '🔴 Не авторизован'
    )""")
    
    # ИСПРАВЛЕНО: Добавлено поле user_id для разделения логов
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        timestamp TEXT,
        message TEXT
    )""")
    
    # Автоматическая миграция: добавляем колонку user_id, если БД уже существовала старой версии
    try:
        cursor.execute("ALTER TABLE logs ADD COLUMN user_id INTEGER")
    except sqlite3.OperationalError:
        pass  # Колонка уже создана
        
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('cooldown', '15')")
    conn.commit()
    conn.close()

# ИСПРАВЛЕНО: Теперь метод принимает user_id
def add_log(user_id: int, message: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%H:%M:%S")
    cursor.execute("INSERT INTO logs (user_id, timestamp, message) VALUES (?, ?, ?)", (user_id, timestamp, message))
    conn.commit()
    conn.close()

# ИСПРАВЛЕНО: Теперь метод фильтрует логи по конкретному user_id
def get_logs(user_id: int, limit=10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, message FROM logs WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [f"[{r[0]}] {r[1]}" for r in rows]

def save_session(phone: str, api_id: int, api_hash: str, session_string: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM account_session")
    cursor.execute(
        "INSERT INTO account_session (phone, api_id, api_hash, session_string, status) VALUES (?, ?, ?, ?, '🟢 Активна')",
        (phone, api_id, api_hash, session_string)
    )
    conn.commit()
    conn.close()

def get_session():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT session_string, api_id, api_hash, status FROM account_session LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row if row else (None, None, None, "🔴 Не авторизован")
