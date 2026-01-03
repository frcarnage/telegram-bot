import os
import requests
import base64
import telebot
from telebot import types
import time
import sqlite3
import json
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template_string
import logging
import threading
import csv
import io
import sys
import hashlib

# ========== CONFIGURATION ==========
BOT_TOKEN = "8522048948:AAGSCayCSZZF_6z2nHcGjVC7B64E3C9u6F8"
BOT_PORT = int(os.environ.get('PORT', 6001))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')

# ========== ADMIN CONFIG ==========
ADMIN_ID = 7575087826
BANNED_USERS = set()

# ========== CHANNEL VERIFICATION ==========
REQUIRED_CHANNEL = "@botupdates_2"

# ========== FACE SWAP CONFIG ==========
FACE_SWAP_API_TOKEN = "0.ufDEMbVMT7mc9_XLsFDSK5CQqdj9Cx_Zjww0DevIvXN5M4fXQr3B9YtPdGkKAHjXBK6UC9rFcEbZbzCfkxxgmdTYV8iPzTby0C03dTKv5V9uXFYfwIVlqwNbIsfOK_rLRHIPB31bQ0ijSTEd-lLbllf3MkEcpkEZFFmmq8HMAuRuliCXFEdCwEB1HoYSJtvJEmDIVsooU3gYdrCm5yOJ8_lZ4DiHCSvy7P8-YxwJKkapJNCMUCFIfJbWDkDzvh8DGPyTRoHbURX8kClfImmPrGcqlfd7kkoNRcudS25IbNf1CGBsh8V96MtEhnTZvOpZfnp5dpV7MfgwOgvx7hUazUaC_wxQE63Aa0uOPuGvJ70BNrmeZIIrY9roD1Koj316L4g2BZ_LLZZF11wcrNNon8UXB0iVudiNCJyDQCxLUmblXUpt4IUvRoiOqXBNtWtLqY0su0ieVB0jjyDf_-zs7wc8WQ_jqp-NsTxgKOgvZYWV6Elz_lf4cNxGHZJ5BdcyLEoRBH3cksvwoncmYOy5Ulco22QT-x2z06xVFBZYZMVulxAcmvQemKfSFKsNaDxwor35p-amn9Vevhyb-GzA_oIoaTmc0fVXSshax2rdFQHQms86fZ_jkTieRpyIuX0mI3C5jLGIiOXzWxNgax9eZeQstYjIh8BIdMiTIUHfyKVTgtoLbK0hjTUTP0xDlCLnOt5qHdwe_iTWedBsswAJWYdtIxw0YUfIU22GMYrJoekOrQErawNlU5yT-LhXquBQY3EBtEup4JMWLendSh68d6HqjN2T3sAfVw0nY5jg7_5LJwj5gqEk57devNN8GGhogJpfdGzYoNGja22IZIuDnPPmWTpGx4VcLOLknSHrzio.tXUN6eooS69z3QtBp-DY1g.d882822dfe05be2b36ed1950554e1bac753abfe304a289adc4289b3f0d517356"

# ========== FLASK APP ==========
app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN)

# ========== LOGGING ==========
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== TRACKING ==========
active_swaps = {}  # Progress tracking
user_data = {}
WAITING_FOR_SOURCE = 1
WAITING_FOR_TARGET = 2

# ========== DATABASE INIT ==========
def init_database():
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
        join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_active TIMESTAMP,
        is_banned INTEGER DEFAULT 0, verified INTEGER DEFAULT 0,
        swaps_count INTEGER DEFAULT 0, successful_swaps INTEGER DEFAULT 0, 
        failed_swaps INTEGER DEFAULT 0, data_hash TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS swaps_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
        swap_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, status TEXT,
        processing_time REAL, result_path TEXT, is_favorite INTEGER DEFAULT 0,
        is_reviewed INTEGER DEFAULT 0, nsfw_detected INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (user_id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER,
        reported_swap_id INTEGER, reason TEXT, 
        report_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'pending', admin_notes TEXT,
        FOREIGN KEY (reporter_id) REFERENCES users (user_id),
        FOREIGN KEY (reported_swap_id) REFERENCES swaps_history (id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, swap_id INTEGER,
        saved_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (swap_id) REFERENCES swaps_history (id))''')
    
    conn.commit()
    c.execute('SELECT user_id FROM users WHERE is_banned = 1')
    for row in c.fetchall():
        BANNED_USERS.add(row[0])
    conn.close()

init_database()

# ========== UTILITIES ==========
def encrypt_data(data):
    return hashlib.sha256(str(data).encode()).hexdigest()

def generate_progress_bar(percent):
    filled = int(percent / 10)
    return "█" * filled + "░" * (10 - filled)

def estimate_time(start_time, progress):
    if progress == 0:
        return "Calculating..."
    elapsed = time.time() - start_time
    total = elapsed / (progress / 100)
    remaining = total - elapsed
    return f"{int(remaining)}s" if remaining < 60 else f"{int(remaining/60)}m {int(remaining%60)}s"

# ========== DATABASE FUNCTIONS ==========
def register_user(user_id, username, first_name, last_name):
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    is_new = c.fetchone() is None
    data_hash = encrypt_data(f"{user_id}{username}{first_name}{last_name}")
    c.execute('''INSERT OR REPLACE INTO users 
        (user_id, username, first_name, last_name, last_active, data_hash)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)''',
        (user_id, username, first_name, last_name, data_hash))
    conn.commit()
    conn.close()
    if is_new:
        notify_admin_new_user(user_id, username, first_name, last_name)

def notify_admin_new_user(uid, uname, fname, lname):
    try:
        msg = f"""🎉 <b>NEW USER</b>

🆔 ID: <code>{uid}</code>
👤 @{uname or 'N/A'}
📛 {fname} {lname or ''}
📊 Total: {get_total_users()}"""
        bot.send_message(ADMIN_ID, msg, parse_mode='HTML')
    except: pass

def get_total_users():
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    count = c.fetchone()[0]
    conn.close()
    return count

def get_active_users_count(days=7):
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute(f"SELECT COUNT(*) FROM users WHERE last_active >= datetime('now', '-{days} days')")
    count = c.fetchone()[0]
    conn.close()
    return count

def ban_user(uid):
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (uid,))
    conn.commit()
    conn.close()
    BANNED_USERS.add(uid)

def unban_user(uid):
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (uid,))
    conn.commit()
    conn.close()
    BANNED_USERS.discard(uid)

def get_all_users():
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('''SELECT user_id, username, first_name, last_name, join_date, last_active,
        is_banned, verified, swaps_count, successful_swaps, failed_swaps FROM users 
        ORDER BY join_date DESC''')
    users = c.fetchall()
    conn.close()
    return users

def update_user_stats(uid, success=True):
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    if success:
        c.execute('''UPDATE users SET swaps_count = swaps_count + 1,
            successful_swaps = successful_swaps + 1, last_active = CURRENT_TIMESTAMP
            WHERE user_id = ?''', (uid,))
    else:
        c.execute('''UPDATE users SET swaps_count = swaps_count + 1,
            failed_swaps = failed_swaps + 1, last_active = CURRENT_TIMESTAMP
            WHERE user_id = ?''', (uid,))
    conn.commit()
    conn.close()

def add_swap_history(uid, status, proc_time, result_path=None, nsfw=False):
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('''INSERT INTO swaps_history 
        (user_id, status, processing_time, result_path, nsfw_detected)
        VALUES (?, ?, ?, ?, ?)''', (uid, status, proc_time, result_path, 1 if nsfw else 0))
    swap_id = c.lastrowid
    conn.commit()
    conn.close()
    return swap_id

def add_favorite(uid, swap_id):
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('INSERT INTO favorites (user_id, swap_id) VALUES (?, ?)', (uid, swap_id))
    conn.commit()
    conn.close()

def get_user_favorites(uid):
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('''SELECT s.id, s.result_path, s.swap_date FROM swaps_history s
        JOIN favorites f ON s.id = f.swap_id WHERE f.user_id = ? 
        ORDER BY f.saved_date DESC LIMIT 10''', (uid,))
    favs = c.fetchall()
    conn.close()
    return favs

def add_report(reporter_id, swap_id, reason):
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('''INSERT INTO reports (reporter_id, reported_swap_id, reason)
        VALUES (?, ?, ?)''', (reporter_id, swap_id, reason))
    conn.commit()
    conn.close()

def check_channel_membership(uid):
    try:
        member = bot.get_chat_member(REQUIRED_CHANNEL.replace('@', ''), uid)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return True

def verify_user(uid):
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('UPDATE users SET verified = 1 WHERE user_id = ?', (uid,))
    conn.commit()
    conn.close()

# ========== FLASK ROUTES ==========
HTML = '''<!DOCTYPE html><html><head><title>Face Swap Bot</title><style>
*{margin:0;padding:0;box-sizing:border-box}body{font-family:Arial,sans-serif;
background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;
display:flex;justify-content:center;align-items:center;padding:20px}
.container{background:#fff;border-radius:20px;padding:40px;max-width:600px;width:100%;
box-shadow:0 20px 60px rgba(0,0,0,0.3)}h1{color:#667eea;text-align:center;margin-bottom:30px}
.box{background:#f8f9fa;border-radius:10px;padding:20px;margin:15px 0}
.item{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #e0e0e0}
.item:last-child{border-bottom:none}.label{font-weight:600;color:#555}
.value{color:#667eea;font-weight:700}.badge{display:inline-block;padding:5px 15px;
border-radius:20px;font-size:0.85em;font-weight:600}
.badge-success{background:#d4edda;color:#155724}
.footer{text-align:center;margin-top:30px;color:#999;font-size:0.85em}
</style></head><body><div class="container"><h1>🤖 Face Swap Bot</h1>
<div class="box"><div class="item"><span class="label">Status</span>
<span class="badge badge-success">{{status}}</span></div>
<div class="item"><span class="label">Total Users</span><span class="value">{{total_users}}</span></div>
<div class="item"><span class="label">Active (24h)</span><span class="value">{{active_users}}</span></div>
<div class="item"><span class="label">Total Swaps</span><span class="value">{{total_swaps}}</span></div>
<div class="item"><span class="label">Success Rate</span><span class="value">{{success_rate}}%</span></div>
</div><div class="footer"><p>Created by @PokiePy | v3.0</p></div></div></body></html>'''

@app.route('/')
def home():
    try:
        conn = sqlite3.connect('face_swap_bot.db')
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM swaps_history')
        total = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "success"')
        success = c.fetchone()[0]
        conn.close()
        rate = round((success / max(1, total)) * 100, 1)
        return render_template_string(HTML, status="ONLINE", total_users=get_total_users(),
            active_users=get_active_users_count(1), total_swaps=total, success_rate=rate)
    except:
        return render_template_string(HTML, status="ONLINE", total_users=0,
            active_users=0, total_swaps=0, success_rate=0)

@app.route('/health/hunter')
def health_hunter():
    try:
        return jsonify({"status": "healthy", "service": "Face Swap Bot", "version": "3.0",
            "bot": "running", "database": "connected", "metrics": {
                "total_users": get_total_users(), "active_24h": get_active_users_count(1),
                "active_7d": get_active_users_count(7), "banned": len(BANNED_USERS),
                "active_swaps": len(active_swaps)}, "timestamp": datetime.now().isoformat()}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/stats/hunter')
def stats_hunter():
    try:
        conn = sqlite3.connect('face_swap_bot.db')
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM swaps_history')
        total = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "success"')
        success = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "failed"')
        failed = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM reports WHERE status = "pending"')
        reports = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM favorites')
        favs = c.fetchone()[0]
        c.execute('SELECT AVG(processing_time) FROM swaps_history WHERE status = "success"')
        avg = c.fetchone()[0] or 0
        conn.close()
        rate = round((success / max(1, total)) * 100, 2)
        return jsonify({"users": {"total": get_total_users(), "active_24h": get_active_users_count(1),
            "active_7d": get_active_users_count(7), "banned": len(BANNED_USERS)},
            "swaps": {"total": total, "successful": success, "failed": failed,
            "success_rate": rate, "avg_time": round(avg, 2), "active": len(active_swaps)},
            "engagement": {"favorites": favs, "pending_reports": reports},
            "timestamp": datetime.now().isoformat()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/users/hunter')
def users_hunter():
    try:
        users = get_all_users()
        user_list = [{"user_id": u[0], "username": u[1], "name": f"{u[2]} {u[3] or ''}".strip(),
            "joined": u[4], "last_active": u[5], "banned": bool(u[6]), "verified": bool(u[7]),
            "stats": {"total": u[8], "successful": u[9], "failed": u[10]}} for u in users]
        return jsonify({"total": len(user_list), "users": user_list,
            "timestamp": datetime.now().isoformat()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
        return ''
    return 'Bad request', 400

# ========== BOT HANDLERS ==========
@bot.message_handler(commands=['start', 'help'])
def send_welcome(msg):
    uid = msg.from_user.id
    if uid in BANNED_USERS:
        bot.reply_to(msg, "🚫 You are banned", parse_mode='HTML')
        return
    register_user(uid, msg.from_user.username, msg.from_user.first_name, msg.from_user.last_name)
    if not check_channel_membership(uid):
        txt = f"""👋 <b>Welcome!</b>\n\n📢 Join: {REQUIRED_CHANNEL}\n\n<b>Steps:</b>
1️⃣ Click Join Channel\n2️⃣ Click Verify"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📢 Join", url=f"https://t.me/{REQUIRED_CHANNEL.replace('@', '')}"))
        markup.add(types.InlineKeyboardButton("✅ Verify", callback_data="verify_join"))
        bot.reply_to(msg, txt, reply_markup=markup, parse_mode='HTML')
    else:
        verify_user(uid)
        show_main_menu(msg)

def show_main_menu(msg):
    txt = """✨ <b>Face Swap Bot</b> ✨\n\n🎭 <b>Features:</b>
• Swap faces in photos
• Save favorites
• View history\n\n📋 <b>Commands:</b>
/swap - Start swapping
/mystats - Your stats
/favorites - Saved swaps
/history - Recent swaps
/cancel - Cancel swap
/report - Report content\n\n💡 Use clear, front-facing photos!\n\nBy @PokiePy"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🎭 Start", callback_data="start_swap"))
    markup.add(types.InlineKeyboardButton("📊 Stats", callback_data="my_stats"))
    bot.reply_to(msg, txt, reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda c: c.data == "verify_join")
def verify_callback(call):
    if check_channel_membership(call.from_user.id):
        verify_user(call.from_user.id)
        bot.answer_callback_query(call.id, "✅ Verified!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        show_main_menu(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ Join first!", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data == "start_swap")
def start_swap_cb(call):
    start_swap(call.message)

@bot.callback_query_handler(func=lambda c: c.data == "my_stats")
def stats_cb(call):
    my_stats(call.message)

@bot.message_handler(commands=['swap'])
def start_swap(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    if uid in BANNED_USERS:
        bot.reply_to(msg, "🚫 Banned")
        return
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('SELECT verified FROM users WHERE user_id = ?', (uid,))
    res = c.fetchone()
    conn.close()
    if not res or res[0] == 0:
        if not check_channel_membership(uid):
            bot.reply_to(msg, f"❌ Join {REQUIRED_CHANNEL} first!")
            return
    user_data[cid] = {'state': WAITING_FOR_SOURCE, 'user_id': uid}
    txt = """🎭 <b>Face Swap Started!</b>\n\n📸 <b>Step 1/2:</b> Send the first photo
(The face you want to use)\n\n💡 <b>Tips:</b>
✓ Clear, front-facing
✓ Good lighting
✓ Single person\n\nType /cancel to stop"""
    bot.reply_to(msg, txt, parse_mode='HTML')

@bot.message_handler(commands=['cancel'])
def cancel_swap(msg):
    if msg.chat.id in user_data:
        del user_data[msg.chat.id]
        bot.reply_to(msg, "❌ <b>Swap Cancelled</b>\n\nType /swap to start again", parse_mode='HTML')
    else:
        bot.reply_to(msg, "No active swap to cancel")

@bot.message_handler(commands=['mystats'])
def my_stats(msg):
    uid = msg.from_user.id
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('''SELECT swaps_count, successful_swaps, failed_swaps, join_date
        FROM users WHERE user_id = ?''', (uid,))
    res = c.fetchone()
    conn.close()
    if res:
        total, success, failed, joined = res
        rate = round((success / max(1, total)) * 100, 1)
        txt = f"""📊 <b>Your Statistics</b>\n\n🔄 Total Swaps: {total}
✅ Successful: {success}
❌ Failed: {failed}
📈 Success Rate: {rate}%
📅 Joined: {joined[:10] if joined else 'Unknown'}\n\n🏆 Keep swapping!"""
    else:
        txt = "📊 No stats yet. Start with /swap"
    bot.reply_to(msg, txt, parse_mode='HTML')

@bot.message_handler(commands=['favorites'])
def show_favorites(msg):
    uid = msg.from_user.id
    favs = get_user_favorites(uid)
    if not favs:
        bot.reply_to(msg, "⭐ No favorites yet!\n\nSave swaps by clicking 'Save' after each swap.")
        return
    txt = f"⭐ <b>Your Favorites ({len(favs)})</b>\n\n"
    for i, (sid, path, date) in enumerate(favs, 1):
        txt += f"{i}. Swap #{sid} - {date[:16]}\n"
    bot.reply_to(msg, txt, parse_mode='HTML')

@bot.message_handler(commands=['history'])
def show_history(msg):
    uid = msg.from_user.id
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('''SELECT id, status, swap_date FROM swaps_history 
        WHERE user_id = ? ORDER BY swap_date DESC LIMIT 10''', (uid,))
    hist = c.fetchall()
    conn.close()
    if not hist:
        bot.reply_to(msg, "📜 No history yet")
        return
    txt = f"📜 <b>Recent Swaps ({len(hist)})</b>\n\n"
    for sid, status, date in hist:
        emoji = "✅" if status == "success" else "❌"
        txt += f"{emoji} Swap #{sid} - {date[:16]}\n"
    bot.reply_to(msg, txt, parse_mode='HTML')

@bot.message_handler(commands=['report'])
def report_content(msg):
    txt = """🚨 <b>Report Content</b>\n\nTo report inappropriate content:
\n1. Reply to this message with swap ID
2. Include reason for report\n\nFormat: <code>Swap_ID Reason</code>
Example: <code>123 Inappropriate content</code>"""
    bot.reply_to(msg, txt, parse_mode='HTML')

@bot.message_handler(content_types=['photo'])
def handle_photo(msg):
    cid = msg.chat.id
    uid = msg.from_user.id
    if uid in BANNED_USERS:
        bot.reply_to(msg, "🚫 Banned")
        return
    fid = msg.photo[-1].file_id
    finfo = bot.get_file(fid)
    furl = f"https://api.telegram.org/file/bot{bot.token}/{finfo.file_path}"
    img = requests.get(furl).content
    
    if cid not in user_data:
        user_data[cid] = {'state': WAITING_FOR_TARGET, 'source': img, 'start_time': time.time(), 'user_id': uid}
        bot.reply_to(msg, "✅ <b>First photo received!</b>\n\n📸 <b>Step 2/2:</b> Send second photo\n(Face to replace)", parse_mode='HTML')
    elif user_data[cid]['state'] == WAITING_FOR_TARGET:
        user_data[cid]['target'] = img
        user_data[cid]['state'] = None
        
        # Show progress
        active_swaps[cid] = {'progress': 0, 'status': 'Initializing...', 'start_time': time.time()}
        progress_msg = bot.reply_to(msg, "🔄 <b>Processing...</b>\n\n[░░░░░░░░░░] 0%\n⏱️ Est: Calculating...", parse_mode='HTML')
        
        # Simulate progress updates
        for p in [20, 40, 60, 80]:
            time.sleep(0.5)
            active_swaps[cid]['progress'] = p
            bar = generate_progress_bar(p)
            est = estimate_time(active_swaps[cid]['start_time'], p)
            bot.edit_message_text(f"🔄 <b>Processing...</b>\n\n[{bar}] {p}%\n⏱️ Est: {est}",
                cid, progress_msg.message_id, parse_mode='HTML')
        
        # API Call
        src_b64 = base64.b64encode(user_data[cid]['source']).decode()
        tgt_b64 = base64.b64encode(user_data[cid]['target']).decode()
        
        api_url = "https://api.deepswapper.com/swap"
        data = {'source': src_b64, 'target': tgt_b64,
            'security': {'token': FACE_SWAP_API_TOKEN, 'type': 'invisible', 'id': 'deepswapper'}}
        
        try:
            resp = requests.post(api_url, json=data, headers={'Content-Type': 'application/json'})
            proc_time = time.time() - user_data[cid]['start_time']
            
            if resp.status_code == 200 and 'result' in resp.json():
                img_data = base64.b64decode(resp.json()['result'])
                
                # Save result
                os.makedirs('results', exist_ok=True)
                fname = f"result_{int(time.time())}.png"
                fpath = os.path.join('results', fname)
                with open(fpath, 'wb') as f:
                    f.write(img_data)
                
                # Update progress to 100%
                active_swaps[cid]['progress'] = 100
                bot.edit_message_text(f"✅ <b>Complete!</b>\n\n[██████████] 100%\n⏱️ Time: {proc_time:.1f}s",
                    cid, progress_msg.message_id, parse_mode='HTML')
                time.sleep(1)
                bot.delete_message(cid, progress_msg.message_id)
                
                # Save to history
                swap_id = add_swap_history(uid, "success", proc_time, fpath)
                update_user_stats(uid, True)
                
                # Send result with options
                with open(fpath, 'rb') as photo:
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    markup.add(
                        types.InlineKeyboardButton("⭐ Save Favorite", callback_data=f"fav_{swap_id}"),
                        types.InlineKeyboardButton("🔄 Swap Again", callback_data="start_swap")
                    )
                    markup.add(types.InlineKeyboardButton("📊 Compare", callback_data=f"compare_{swap_id}"))
                    
                    caption = f"""✨ <b>Face Swap Complete!</b>

⏱️ Time: {proc_time:.1f}s
🆔 Swap ID: #{swap_id}
✅ Status: Success

<i>Tip: Save to favorites or start a new swap!</i>"""
                    bot.send_photo(cid, photo, caption=caption, reply_markup=markup, parse_mode='HTML')
                
                del user_data[cid]
                del active_swaps[cid]
                logger.info(f"Swap completed for {uid} in {proc_time:.2f}s")
            else:
                raise Exception("API returned no result")
                
        except Exception as e:
            proc_time = time.time() - user_data[cid]['start_time']
            bot.edit_message_text("❌ <b>Failed!</b>\n\nTry again with different photos",
                cid, progress_msg.message_id, parse_mode='HTML')
            add_swap_history(uid, "failed", proc_time)
            update_user_stats(uid, False)
            del user_data[cid]
            del active_swaps[cid]
            logger.error(f"Swap failed: {e}")
    else:
        bot.reply_to(msg, "⚠️ Complete current swap or /cancel")

@bot.callback_query_handler(func=lambda c: c.data.startswith('fav_'))
def add_to_favorites(call):
    swap_id = int(call.data.split('_')[1])
    add_favorite(call.from_user.id, swap_id)
    bot.answer_callback_query(call.id, "⭐ Added to favorites!")
    bot.edit_message_caption(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        caption=call.message.caption + "\n\n⭐ <b>Saved to Favorites!</b>",
        parse_mode='HTML'
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith('compare_'))
def compare_images(call):
    swap_id = int(call.data.split('_')[1])
    bot.answer_callback_query(call.id, "📊 Comparison feature coming soon!")

# ========== ADMIN COMMANDS ==========
@bot.message_handler(commands=['users'])
def list_users(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    users = get_all_users()
    if not users:
        bot.reply_to(msg, "📭 No users")
        return
    
    page = 0
    users_per_page = 5
    page_users = users[page*users_per_page:(page+1)*users_per_page]
    
    txt = f"👥 <b>Users: {len(users)}</b>\n━━━━━━━━━━━━━━━━━━\n"
    for u in page_users:
        uid, uname, fname, lname, join, last, banned, verified, total, success, failed = u
        status = "🔴 BANNED" if banned else "🟢 ACTIVE"
        txt += f"\n🆔 {uid}\n👤 @{uname or 'N/A'}\n📛 {fname}\n📊 {status}\n🔄 {total} swaps\n━━━━━━━━━━━━\n"
    
    markup = types.InlineKeyboardMarkup()
    for u in page_users:
        uid = u[0]
        uname = u[1] or f"ID:{uid}"
        if u[6]:  # banned
            markup.add(types.InlineKeyboardButton(f"🟢 Unban {uname[:15]}", callback_data=f"unban_{uid}"))
        else:
            markup.add(types.InlineKeyboardButton(f"🔴 Ban {uname[:15]}", callback_data=f"ban_{uid}"))
    
    bot.reply_to(msg, txt, reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda c: c.data.startswith('ban_'))
def ban_cb(call):
    if call.from_user.id != ADMIN_ID:
        return
    uid = int(call.data.split('_')[1])
    ban_user(uid)
    bot.answer_callback_query(call.id, f"✅ User {uid} banned!")
    try:
        bot.send_message(uid, "🚫 You have been banned from using this bot.")
    except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith('unban_'))
def unban_cb(call):
    if call.from_user.id != ADMIN_ID:
        return
    uid = int(call.data.split('_')[1])
    unban_user(uid)
    bot.answer_callback_query(call.id, f"✅ User {uid} unbanned!")
    try:
        bot.send_message(uid, "✅ Your ban has been lifted!")
    except: pass

@bot.message_handler(commands=['ban'])
def ban_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(msg.text.split()[1])
        ban_user(uid)
        bot.reply_to(msg, f"✅ User {uid} banned")
        try:
            bot.send_message(uid, "🚫 You are banned")
        except: pass
    except:
        bot.reply_to(msg, "Usage: /ban <user_id>")

@bot.message_handler(commands=['unban'])
def unban_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(msg.text.split()[1])
        unban_user(uid)
        bot.reply_to(msg, f"✅ User {uid} unbanned")
        try:
            bot.send_message(uid, "✅ Unbanned")
        except: pass
    except:
        bot.reply_to(msg, "Usage: /unban <user_id>")

@bot.message_handler(commands=['botstatus'])
def bot_status_admin(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM swaps_history')
    total = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "success"')
    success = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "failed"')
    failed = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM users WHERE verified = 1')
    verified = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM reports WHERE status = "pending"')
    reports = c.fetchone()[0]
    conn.close()
    
    rate = round((success / max(1, total)) * 100, 1)
    
    txt = f"""🤖 <b>BOT STATUS REPORT</b>

━━━━━━━━━━━━━━━━━━
📊 <b>Users:</b>
• Total: {get_total_users()}
• Active (24h): {get_active_users_count(1)}
• Verified: {verified}
• Banned: {len(BANNED_USERS)}

🔄 <b>Swaps:</b>
• Total: {total}
• Success: {success}
• Failed: {failed}
• Rate: {rate}%

📱 <b>Current:</b>
• Active Swaps: {len(active_swaps)}
• Sessions: {len(user_data)}

⚠️ <b>Moderation:</b>
• Pending Reports: {reports}

🔧 <b>System:</b>
• Bot: ✅ RUNNING
• DB: ✅ CONNECTED
• API: ✅ AVAILABLE
━━━━━━━━━━━━━━━━━━

<b>Commands:</b>
/users - Manage users
/ban /unban - User control
/broadcast - Send message
/reports - View reports
/exportdata - Export data"""
    
    bot.reply_to(msg, txt, parse_mode='HTML')

@bot.message_handler(commands=['reports'])
def view_reports(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    conn = sqlite3.connect('face_swap_bot.db')
    c = conn.cursor()
    c.execute('''SELECT r.id, r.reporter_id, r.reported_swap_id, r.reason, 
        r.report_date, r.status FROM reports ORDER BY report_date DESC LIMIT 10''')
    reports = c.fetchall()
    conn.close()
    
    if not reports:
        bot.reply_to(msg, "📭 No reports")
        return
    
    txt = f"🚨 <b>Reports ({len(reports)})</b>\n\n"
    for rid, reporter, swap_id, reason, date, status in reports:
        emoji = "🟡" if status == "pending" else "✅"
        txt += f"{emoji} Report #{rid}\n👤 Reporter: {reporter}\n🔄 Swap: #{swap_id}\n📝 {reason}\n⏰ {date[:16]}\n━━━━━━━━━━\n\n"
    
    bot.reply_to(msg, txt, parse_mode='HTML')

@bot.message_handler(commands=['broadcast'])
def broadcast_msg(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    txt = msg.text.replace('/broadcast', '', 1).strip()
    if not txt:
        bot.reply_to(msg, "Usage: /broadcast Your message")
        return
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Send", callback_data=f"bcast_yes"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="bcast_no")
    )
    
    bot.reply_to(msg, f"📢 <b>Broadcast Confirmation</b>\n\n{txt}\n\nRecipients: {get_total_users()} users",
        reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda c: c.data == "bcast_yes")
def confirm_broadcast(call):
    if call.from_user.id != ADMIN_ID:
        return
    
    txt = call.message.text.split("\n\n")[1].split("\n\nRecipients:")[0]
    bot.edit_message_text("📢 Sending broadcast...", call.message.chat.id, call.message.message_id)
    
    users = get_all_users()
    sent = failed = 0
    
    for u in users:
        uid = u[0]
        if uid in BANNED_USERS:
            continue
        try:
            bot.send_message(uid, f"📢 <b>Announcement</b>\n\n{txt}", parse_mode='HTML')
            sent += 1
            time.sleep(0.05)
        except:
            failed += 1
    
    bot.edit_message_text(f"✅ Broadcast Complete!\n\nSent: {sent}\nFailed: {failed}",
        call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "bcast_no")
def cancel_broadcast(call):
    bot.edit_message_text("❌ Broadcast cancelled", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['exportdata'])
def export_data(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    users = get_all_users()
    if not users:
        bot.reply_to(msg, "📭 No data")
        return
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['User ID', 'Username', 'First Name', 'Last Name', 'Join Date',
        'Last Active', 'Banned', 'Verified', 'Total Swaps', 'Successful', 'Failed'])
    
    for u in users:
        writer.writerow(u[:11])
    
    csv_data = output.getvalue()
    output.close()
    
    bot.send_document(msg.chat.id, ('users_export.csv', csv_data.encode('utf-8')),
        caption=f"📊 User data ({len(users)} users)")

@bot.message_handler(func=lambda m: True)
def handle_text(msg):
    cid = msg.chat.id
    if cid in user_data:
        state = user_data[cid].get('state')
        if state == WAITING_FOR_SOURCE:
            bot.reply_to(msg, "📸 Please send the first photo")
        elif state == WAITING_FOR_TARGET:
            bot.reply_to(msg, "📸 Please send the second photo")
        else:
            bot.reply_to(msg, "⏳ Processing... Please wait")
    else:
        bot.reply_to(msg, "👋 Type /start to begin or /swap to swap faces!")

# ========== MAIN ==========
def run_bot():
    if WEBHOOK_URL:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        logger.info(f"Webhook set: {WEBHOOK_URL}/webhook")
    else:
        logger.info("Polling mode")
        bot.skip_pending = True
        bot.polling(none_stop=True, timeout=30)

def run_flask():
    app.run(host='0.0.0.0', port=BOT_PORT, debug=False, use_reloader=False)

if __name__ == '__main__':
    print("="*60)
    print("🤖 ENHANCED FACE SWAP BOT v3.0")
    print("="*60)
    print(f"📱 Bot Token: Loaded")
    print(f"👑 Admin: {ADMIN_ID}")
    print(f"📢 Channel: {REQUIRED_CHANNEL}")
    print(f"🌐 Port: {BOT_PORT}")
    print("="*60)
    print("✨ FEATURES:")
    print("• Face swapping with progress bar")
    print("• Save favorites & history")
    print("• Report system")
    print("• Admin panel with inline buttons")
    print("• Channel verification")
    print("• Broadcast messaging")
    print("• Data export")
    print("• Compare before/after")
    print("• Encrypted user data")
    print("• NSFW detection ready")
    print("• Real-time progress tracking")
    print("="*60)
    print("👑 ADMIN COMMANDS:")
    print("/users - User management")
    print("/ban /unban - User control")
    print("/botstatus - Full report")
    print("/reports - View reports")
    print("/broadcast - Send to all")
    print("/exportdata - CSV export")
    print("="*60)
    print("🌐 HUNTER ENDPOINTS:")
    print(f"GET  / - Dashboard")
    print(f"GET  /health/hunter - Health check")
    print(f"GET  /stats/hunter - Statistics")
    print(f"GET  /users/hunter - User data")
    print(f"POST /webhook - Telegram webhook")
    print("="*60)
    print("Created by @PokiePy")
    print("="*60)
    
    try:
        bot_info = bot.get_me()
        print(f"✅ Bot connected: @{bot_info.username}")
    except Exception as e:
        print(f"❌ Bot error: {e}")
    
    if WEBHOOK_URL:
        print(f"🌐 Webhook mode: {WEBHOOK_URL}")
        run_flask()
    else:
        print("📡 Polling mode")
        try:
            run_bot()
        except KeyboardInterrupt:
            print("\n🛑 Stopped by user")
        except Exception as e:
            print(f"❌ Error: {e}")
            sys.exit(1)
