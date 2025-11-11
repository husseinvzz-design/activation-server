# activation_server.py
# Simple Activation Server (Flask + SQLite) with Telegram notifications.
# USAGE:
# 1) Put your Telegram bot token in the BOT_TOKEN variable below or export as environment variable BOT_TOKEN.
# 2) Set CHAT_ID to your Telegram chat id (default filled from earlier step).
# 3) pip install -r requirements.txt
# 4) python activation_server.py
#
# Endpoints:
# POST /request_activation   -> { "hwid": "...", "device_name": "..." }
# POST /verify_activation    -> { "hwid": "...", "activation_code": "..." }
#
# Note: Activation codes are stored hashed in the DB. The server sends the plain code to the admin's Telegram.
# Do NOT commit private keys or tokens in public repos.

from flask import Flask, request, jsonify
from pathlib import Path
import sqlite3, os, hashlib, base64, secrets, time, json, requests

# ------------- CONFIG -------------
# You can either edit BOT_TOKEN here or set environment variable BOT_TOKEN
BOT_TOKEN = "8405591213:AAH5odonyfpd4X_LAB-3ZtVKAJbpNo6jTf4"
CHAT_ID = os.environ.get('CHAT_ID', '1299648909')  # default from prior step; you can change
DB_FILE = Path('activations.db')
CODE_LENGTH = 12  # length of generated activation code (alphanumeric)
CODE_TTL_SECONDS = 60 * 60 * 24  # time-to-live for pending codes (24 hours)
# ----------------------------------

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect(str(DB_FILE))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS pending (
            hwid TEXT PRIMARY KEY,
            code_hash TEXT,
            code_plain_sample TEXT,
            device_name TEXT,
            created_at INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS activations (
            hwid TEXT PRIMARY KEY,
            activated_at INTEGER,
            activation_code_hash TEXT,
            device_name TEXT
        )
    """)
    conn.commit(); conn.close()

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

def send_telegram_message(token: str, chat_id: str, text: str) -> bool:
    if not token:
        print("No BOT_TOKEN set; skipping Telegram send.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        return r.status_code == 200 and r.json().get("ok", False)
    except Exception as e:
        print("Telegram send error:", e)
        return False

def generate_code(length=CODE_LENGTH):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # avoid ambiguous chars
    return ''.join(secrets.choice(alphabet) for _ in range(length))

@app.route('/request_activation', methods=['POST'])
def request_activation():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"ok":False, "error":"invalid_json"}), 400
    hwid = str(body.get('hwid', '')).strip()
    device_name = str(body.get('device_name', '')).strip()[:200]
    if not hwid:
        return jsonify({"ok":False, "error":"missing_hwid"}), 400

    init_db()
    conn = sqlite3.connect(str(DB_FILE)); c = conn.cursor()

    # If already activated, respond accordingly
    c.execute('SELECT hwid FROM activations WHERE hwid=?', (hwid,))
    if c.fetchone():
        conn.close()
        return jsonify({"ok":False, "error":"already_activated"}), 409

    # Generate code, hash it and store in pending table
    code = generate_code()
    code_hash = sha256_hex(code)
    created = int(time.time())

    c.execute('REPLACE INTO pending (hwid, code_hash, code_plain_sample, device_name, created_at) VALUES (?,?,?,?,?)',
              (hwid, code_hash, code[:4] + '...' , device_name, created))
    conn.commit(); conn.close()

    # send Telegram to admin with full info (hwid, device_name, code)
    token = BOT_TOKEN or os.environ.get('BOT_TOKEN','')
    chat = CHAT_ID or os.environ.get('CHAT_ID','')
    msg = f"🔔 طلب تفعيل جديد\nHWID: {hwid}\nDevice: {device_name}\nActivation Code: {code}\nTime: {time.ctime(created)}"
    send_ok = send_telegram_message(token, chat, msg)

    return jsonify({"ok":True, "sent_to_admin": send_ok, "note":"Admin received code via Telegram (if BOT_TOKEN set)."}), 200

@app.route('/verify_activation', methods=['POST'])
def verify_activation():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"ok":False, "error":"invalid_json"}), 400
    hwid = str(body.get('hwid','')).strip()
    code = str(body.get('activation_code','')).strip()
    device_name = str(body.get('device_name','')).strip()[:200]
    if not hwid or not code:
        return jsonify({"ok":False, "error":"missing_fields"}), 400

    init_db()
    conn = sqlite3.connect(str(DB_FILE)); c = conn.cursor()
    # fetch pending
    c.execute('SELECT code_hash, created_at FROM pending WHERE hwid=?', (hwid,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"ok":False, "error":"no_pending_request"}), 404
    code_hash_db, created_at = row[0], row[1]
    # check TTL
    if int(time.time()) - int(created_at) > CODE_TTL_SECONDS:
        # expired
        c.execute('DELETE FROM pending WHERE hwid=?', (hwid,)); conn.commit(); conn.close()
        return jsonify({"ok":False, "error":"code_expired"}), 410

    if sha256_hex(code) != code_hash_db:
        conn.close()
        return jsonify({"ok":False, "error":"invalid_code"}), 403

    # success: move to activations and remove pending
    activated_at = int(time.time())
    activation_hash = sha256_hex(code + '::' + hwid)
    c.execute('REPLACE INTO activations (hwid, activated_at, activation_code_hash, device_name) VALUES (?,?,?,?)',
              (hwid, activated_at, activation_hash, device_name))
    c.execute('DELETE FROM pending WHERE hwid=?', (hwid,))
    conn.commit(); conn.close()

    return jsonify({"ok":True, "activated_at": activated_at}), 200

@app.route('/admin/list_pending', methods=['GET'])
def admin_list_pending():
    init_db()
    conn = sqlite3.connect(str(DB_FILE)); c = conn.cursor()
    c.execute('SELECT hwid, code_plain_sample, device_name, created_at FROM pending ORDER BY created_at DESC')
    rows = c.fetchall(); conn.close()
    out = []
    for r in rows:
        out.append({"hwid": r[0], "code_sample": r[1], "device_name": r[2], "created_at": r[3]})
    return jsonify(out)

@app.route('/admin/list_activations', methods=['GET'])
def admin_list_activations():
    init_db()
    conn = sqlite3.connect(str(DB_FILE)); c = conn.cursor()
    c.execute('SELECT hwid, activated_at, device_name FROM activations ORDER BY activated_at DESC')
    rows = c.fetchall(); conn.close()
    out = []
    for r in rows:
        out.append({"hwid": r[0], "activated_at": r[1], "device_name": r[2]})
    return jsonify(out)

if __name__ == '__main__':
    init_db()
    print("Activation server running on http://0.0.0.0:5000")
    print("Make sure to set BOT_TOKEN (or export BOT_TOKEN env) and CHAT_ID if you want Telegram notifications.")
    app.run(host='0.0.0.0', port=5000)
