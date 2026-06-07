import sqlite3
from datetime import datetime

DB_PATH = "marketer_db.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблица для хранения String Session юзербота
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS account_session (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT,
        session_string TEXT,
        status TEXT DEFAULT '🔴 Не авторизован'
    )""")
    
    # Таблица для логов работы
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        message TEXT
    )""")
    
    # Таблица настроек (например, задержка)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    
    # Установка дефолтного кулдауна (15 секунд), если его нет
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('cooldown', '15')")
    
    conn.commit()
    conn.close()

def add_log(message: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%H:%M:%S")
    cursor.execute("INSERT INTO logs (timestamp, message) VALUES (?, ?)", (timestamp, message))
    conn.commit()
    conn.close()

def get_logs(limit=10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, message FROM logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [f"[{r[0]}] {r[1]}" for r in rows]

def save_session(phone: str, session_string: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM account_session")  # Поддерживаем одну активную сессию
    cursor.execute("INSERT INTO account_session (phone, session_string, status) VALUES (?, ?, '🟢 Активна')", (phone, session_string))
    conn.commit()
    conn.close()

def get_session():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT session_string, status FROM account_session LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row if row else (None, "🔴 Сессия не создана")

def update_cooldown(seconds: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = ? WHERE key = 'cooldown'", (str(seconds),))
    conn.commit()
    conn.close()

def get_cooldown():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'cooldown'")
    row = cursor.fetchone()
    conn.close()
    return int(row[0]) if row else 15
