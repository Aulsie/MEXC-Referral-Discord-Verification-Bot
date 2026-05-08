import sqlite3

DB_FILE = "database.db"


# =========================
# CONNECTION
# =========================

def get_connection():
    return sqlite3.connect(DB_FILE)


# =========================
# INIT DATABASE
# =========================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        discord_id TEXT PRIMARY KEY,
        mexc_uid TEXT,
        last_trade_time INTEGER,
        signup_time TEXT,
        nickname TEXT,
        email TEXT,
        trading_status TEXT,
        verified_at INTEGER
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS panel(
        id INTEGER PRIMARY KEY,
        message_id INTEGER,
        channel_id INTEGER
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    conn.commit()
    conn.close()


# =========================
# USER FUNCTIONS
# =========================

def add_user(discord_id, mexc_uid, last_trade_time, signup_time, nickname, email, trading_status, verified_at):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
    INSERT OR REPLACE INTO users
    (discord_id, mexc_uid, last_trade_time, signup_time, nickname, email, trading_status, verified_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(discord_id),
        str(mexc_uid),
        last_trade_time,
        signup_time,
        nickname,
        email,
        trading_status,
        verified_at
    ))

    conn.commit()
    conn.close()


def get_user(discord_id):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT * FROM users WHERE discord_id=?", (str(discord_id),))
    row = c.fetchone()

    conn.close()

    if not row:
        return None

    return {
        "discord_id": row[0],
        "uid": row[1],
        "lastTradeTime": row[2],
        "signup_time": row[3],
        "nickname": row[4],
        "email": row[5],
        "trading_status": row[6],
        "verified_at": row[7]
    }


# NEW (used by referral system)
def get_user_by_uid(uid):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT * FROM users WHERE mexc_uid=?", (str(uid),))
    row = c.fetchone()

    conn.close()

    if not row:
        return None

    return {
        "discord_id": row[0],
        "uid": row[1],
        "lastTradeTime": row[2],
        "signup_time": row[3],
        "nickname": row[4],
        "email": row[5],
        "trading_status": row[6],
        "verified_at": row[7]
    }


def remove_user(discord_id):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("DELETE FROM users WHERE discord_id=?", (str(discord_id),))

    conn.commit()
    conn.close()


def update_last_trade(uid, last_trade_time):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
    UPDATE users
    SET last_trade_time=?
    WHERE mexc_uid=?
    """, (last_trade_time, str(uid)))

    conn.commit()
    conn.close()


def update_trading_status(uid, status):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
    UPDATE users
    SET trading_status=?
    WHERE mexc_uid=?
    """, (status, str(uid)))

    conn.commit()
    conn.close()


def get_all_users():

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT * FROM users")
    rows = c.fetchall()

    conn.close()

    users = []

    for row in rows:
        users.append({
            "discord_id": row[0],
            "uid": row[1],
            "lastTradeTime": row[2],
            "signup_time": row[3],
            "nickname": row[4],
            "email": row[5],
            "trading_status": row[6],
            "verified_at": row[7]
        })

    return users


def count_users():

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]

    conn.close()

    return count


# =========================
# PANEL FUNCTIONS
# =========================

def save_panel(message_id, channel_id):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
    INSERT OR REPLACE INTO panel(id, message_id, channel_id)
    VALUES (1, ?, ?)
    """, (message_id, channel_id))

    conn.commit()
    conn.close()


def get_panel():

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT message_id, channel_id FROM panel WHERE id=1")
    row = c.fetchone()

    conn.close()

    if not row:
        return None

    return {
        "message_id": row[0],
        "channel_id": row[1]
    }


# =========================
# SETTINGS FUNCTIONS
# =========================

def set_setting(key, value):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
    INSERT INTO settings(key, value)
    VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, str(value)))

    conn.commit()
    conn.close()


def get_setting(key, default=None):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()

    conn.close()

    if row:
        return row[0]

    return default