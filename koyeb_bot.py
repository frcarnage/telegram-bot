#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Face Swap Bot v3.5 - Production Ready
Complete with all features: Admin panel, Reports, Backup, Notifications
FIXED: Swap statistics now properly stored in database
"""

import os
import sys
import time
import json
import sqlite3
import base64
import hashlib
import logging
import threading
import csv
import io
import shutil
import zipfile
import tempfile
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any

import requests
import telebot
from telebot import types
from flask import Flask, jsonify, request, render_template_string, send_file
from werkzeug.middleware.proxy_fix import ProxyFix

# ========== CONFIGURATION ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN', '7863008338:AAGoOdY4xpl0ATf0GRwQfCTg_Dt9ny5AM2c')
BOT_PORT = int(os.environ.get('PORT', 8000))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', 'https://informal-sandie-1carnage1-fb1959f9.koyeb.app')
WEBHOOK_PATH = '/webhook'

# ========== ADMIN CONFIG ==========
ADMIN_ID = 7575087826
BANNED_USERS = set()

# ========== CHANNEL VERIFICATION ==========
REQUIRED_CHANNEL = "@botupdates_2"

# ========== FACE SWAP CONFIG ==========
FACE_SWAP_API_TOKEN = "0.ufDEMbVMT7mc9_XLsFDSK5CQqdj9Cx_Zjww0DevIvXN5M4fXQr3B9YtPdGkKAHjXBK6UC9rFcEbZbzCfkxxgmdTYV8iPzTby0C03dTKv5V9uXFYfwIVlqwNbIsfOK_rLRHIPB31bQ0ijSTEd-lLbllf3MkEcpkEZFFmmq8HMAuRuliCXFEdCwEB1HoYSJtvJEmDIVsooU3gYdrCm5yOJ8_lZ4DiHCSvy7P8-YxwJKkapJNCMUCFIfJbWDkDzvh8DGPyTRoHbURX8kClfImmPrGcqlfd7kkoNRcudS25IbNf1CGBsh8V96MtEhnTZvOpZfnp5dpV7MfgwOgvx7hUazUaC_wxQE63Aa0uOPuGvJ70BNrmeZIIrY9roD1Koj316L4g2BZ_LLZZF11wcrNNon8UXB0iVudiNCJyDQCxLUmblXUpt4IUvRoiOqXBNtWtLqY0su0ieVB0jjyDf_-zs7wc8WQ_jqp-NsTxgKOgvZYWV6Elz_lf4cNxGHZJ5BdcyLEoRBH3cksvwoncmYOy5Ulco22QT-x2z06xVFBZYZMVulxAcmvQemKfSFKsNaDxwor35p-amn9Vevhyb-GzA_oIoaTmc0fVXSshax2rdFQHQms86fZ_jkTieRpyIuX0mI3C5jLGIiOXzWxNgax9eZeQstYjIh8BIdMiTIUHfyKVTgtoLbK0hjTUTP0xDlCLnOt5qHdwe_iTWedBsswAJWYdtIxw0YUfIU22GMYrJoekOrQErawNlU5yT-LhXquBQY3EBtEup4JMWLendSh68d6HqjN2T3sAfVw0nY5jg7_5LJwj5gqEk57devNN8GGhogJpfdGzYoNGja22IZIuDnPPmWTpGx4VcLOLknSHrzio.tXUN6eooS69z3QtBp-DY1g.d882822dfe05be2b36ed1950554e1bac753abfe304a289adc4289b3f0d517356"
FACE_SWAP_API_URL = "https://api.deepswapper.com/swap"

# ========== APPLICATION STATES ==========
STATE_IDLE = 0
STATE_WAITING_SOURCE = 1
STATE_WAITING_TARGET = 2
STATE_PROCESSING = 3

# ========== INITIALIZE ==========
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

# ========== LOGGING ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ========== GLOBAL TRACKING ==========
user_sessions: Dict[int, Dict] = {}
active_swaps: Dict[int, Dict] = {}
backup_restore_data: Dict[int, Dict] = {}

# ========== DATABASE FUNCTIONS ==========
def init_database() -> None:
    """Initialize SQLite database with all required tables"""
    conn = sqlite3.connect('face_swap_bot.db', check_same_thread=False)
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_active TIMESTAMP,
        is_banned INTEGER DEFAULT 0,
        verified INTEGER DEFAULT 0,
        swaps_count INTEGER DEFAULT 0,
        successful_swaps INTEGER DEFAULT 0,
        failed_swaps INTEGER DEFAULT 0,
        data_hash TEXT,
        notified_admin BOOLEAN DEFAULT 0
    )''')
    
    # Swaps history table
    c.execute('''CREATE TABLE IF NOT EXISTS swaps_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        swap_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT,
        processing_time REAL,
        result_path TEXT,
        is_favorite INTEGER DEFAULT 0,
        is_reviewed INTEGER DEFAULT 0,
        nsfw_detected INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
    )''')
    
    # Reports table
    c.execute('''CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_id INTEGER,
        reported_swap_id INTEGER,
        reason TEXT,
        report_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'pending',
        admin_notes TEXT,
        FOREIGN KEY (reporter_id) REFERENCES users (user_id),
        FOREIGN KEY (reported_swap_id) REFERENCES swaps_history (id)
    )''')
    
    # Favorites table
    c.execute('''CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        swap_id INTEGER,
        saved_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (swap_id) REFERENCES swaps_history (id)
    )''')
    
    # Backup metadata table
    c.execute('''CREATE TABLE IF NOT EXISTS backup_metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        backup_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        backup_size INTEGER,
        users_count INTEGER,
        swaps_count INTEGER,
        filename TEXT,
        admin_id INTEGER
    )''')
    
    # Admin notifications table
    c.execute('''CREATE TABLE IF NOT EXISTS admin_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        notification_type TEXT,
        user_id INTEGER,
        swap_id INTEGER,
        report_id INTEGER,
        notification_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_read INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')
    
    # Load banned users
    c.execute('SELECT user_id FROM users WHERE is_banned = 1')
    for row in c.fetchall():
        BANNED_USERS.add(row[0])
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

def get_db_connection() -> sqlite3.Connection:
    """Get database connection with proper settings"""
    conn = sqlite3.connect('face_swap_bot.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# ========== NOTIFICATION FUNCTIONS ==========
def notify_admin_new_user(user_id: int, username: str, first_name: str, last_name: str):
    """Notify admin about new user"""
    try:
        msg = f"""🎉 <b>NEW USER REGISTERED</b>

🆔 ID: <code>{user_id}</code>
👤 Username: @{username or 'N/A'}
📛 Name: {first_name} {last_name or ''}
📊 Total Users: {get_total_users()}
🕒 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📈 <b>Quick Stats:</b>
• Active (24h): {get_active_users_count(1)}
• Total Swaps: {get_total_swaps()}
• Success Rate: {get_success_rate()}%"""
        
        bot.send_message(ADMIN_ID, msg, parse_mode='HTML')
        
        # Mark as notified
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('UPDATE users SET notified_admin = 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

def notify_admin_report(report_id: int, reporter_id: int, swap_id: int, reason: str):
    """Notify admin about new report"""
    try:
        msg = f"""🚨 <b>NEW REPORT</b>

🆔 Report ID: #{report_id}
👤 Reporter: {reporter_id}
🔄 Swap ID: #{swap_id}
📝 Reason: {reason[:200]}
🕒 Time: {datetime.now().strftime('%H:%M:%S')}

⚠️ <b>Action Required:</b> Use /reports to review"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📋 View Reports", callback_data="admin_reports"))
        markup.add(types.InlineKeyboardButton("👁️ View Swap", callback_data=f"view_swap_{swap_id}"))
        
        bot.send_message(ADMIN_ID, msg, parse_mode='HTML', reply_markup=markup)
        
    except Exception as e:
        logger.error(f"Failed to notify admin about report: {e}")

def notify_admin_swap_complete(user_id: int, swap_id: int, processing_time: float, success: bool = True):
    """Notify admin about completed swap"""
    try:
        status = "✅ SUCCESS" if success else "❌ FAILED"
        msg = f"""🔄 <b>SWAP COMPLETED</b>

👤 User: {user_id}
🆔 Swap ID: #{swap_id}
⏱️ Time: {processing_time:.1f}s
📊 Status: {status}
🕒 Time: {datetime.now().strftime('%H:%M:%S')}

📈 <b>User Stats:</b>
• Total Swaps: {get_user_swap_count(user_id)}
• Success Rate: {get_user_success_rate(user_id)}%"""
        
        bot.send_message(ADMIN_ID, msg, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Failed to notify admin about swap: {e}")

# ========== STATISTICS FUNCTIONS ==========
def get_total_users() -> int:
    """Get total number of registered users"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    count = c.fetchone()[0]
    conn.close()
    return count

def get_active_users_count(days: int = 1) -> int:
    """Get number of active users in last N days"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"SELECT COUNT(*) FROM users WHERE last_active >= datetime('now', '-{days} days')")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_total_swaps() -> int:
    """Get total number of swaps"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM swaps_history')
    count = c.fetchone()[0]
    conn.close()
    return count

def get_success_rate() -> float:
    """Get overall success rate"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "success"')
    success = c.fetchone()[0] or 0
    c.execute('SELECT COUNT(*) FROM swaps_history')
    total = c.fetchone()[0] or 1
    conn.close()
    return round((success / total) * 100, 1)

def get_user_swap_count(user_id: int) -> int:
    """Get user's total swap count"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT swaps_count FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def get_user_success_rate(user_id: int) -> float:
    """Get user's success rate"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT successful_swaps, swaps_count FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result and result[1] > 0:
        return round((result[0] / result[1]) * 100, 1)
    return 0.0

# ========== BACKUP & RESTORE FUNCTIONS ==========
def create_database_backup() -> Optional[bytes]:
    """Create a complete database backup"""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_file = os.path.join(temp_dir, 'backup.json')
            
            conn = get_db_connection()
            conn.row_factory = sqlite3.Row
            
            backup_data = {
                'timestamp': datetime.now().isoformat(),
                'version': '3.5',
                'tables': {}
            }
            
            tables = ['users', 'swaps_history', 'reports', 'favorites']
            
            for table in tables:
                cursor = conn.execute(f'SELECT * FROM {table}')
                rows = cursor.fetchall()
                
                table_data = []
                for row in rows:
                    table_data.append(dict(row))
                
                backup_data['tables'][table] = table_data
            
            conn.close()
            
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
            
            with open(backup_file, 'rb') as f:
                backup_bytes = f.read()
            
            # Create ZIP
            zip_file = os.path.join(temp_dir, 'backup.zip')
            with zipfile.ZipFile(zip_file, 'w') as zipf:
                zipf.write(backup_file, 'backup.json')
            
            with open(zip_file, 'rb') as f:
                zip_bytes = f.read()
            
            logger.info(f"Backup created: {len(zip_bytes)} bytes")
            return zip_bytes
            
    except Exception as e:
        logger.error(f"Backup creation failed: {e}")
        return None

def restore_database_from_backup(backup_data: bytes) -> Tuple[bool, str]:
    """Restore database from backup"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
            tmp_file.write(backup_data)
            tmp_path = tmp_file.name
        
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(tmp_path, 'r') as zipf:
                zipf.extractall(temp_dir)
            
            json_backup = os.path.join(temp_dir, 'backup.json')
            
            if os.path.exists(json_backup):
                with open(json_backup, 'r', encoding='utf-8') as f:
                    backup_data = json.load(f)
                
                # Create temporary database
                temp_db = 'face_swap_bot_temp.db'
                if os.path.exists(temp_db):
                    os.remove(temp_db)
                
                conn = sqlite3.connect(temp_db)
                c = conn.cursor()
                
                # Recreate schema
                c.execute('''CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    join_date TIMESTAMP,
                    last_active TIMESTAMP,
                    is_banned INTEGER DEFAULT 0,
                    verified INTEGER DEFAULT 0,
                    swaps_count INTEGER DEFAULT 0,
                    successful_swaps INTEGER DEFAULT 0,
                    failed_swaps INTEGER DEFAULT 0,
                    data_hash TEXT,
                    notified_admin BOOLEAN DEFAULT 0
                )''')
                
                c.execute('''CREATE TABLE swaps_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    swap_date TIMESTAMP,
                    status TEXT,
                    processing_time REAL,
                    result_path TEXT,
                    is_favorite INTEGER DEFAULT 0,
                    is_reviewed INTEGER DEFAULT 0,
                    nsfw_detected INTEGER DEFAULT 0
                )''')
                
                c.execute('''CREATE TABLE reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reporter_id INTEGER,
                    reported_swap_id INTEGER,
                    reason TEXT,
                    report_date TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    admin_notes TEXT
                )''')
                
                c.execute('''CREATE TABLE favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    swap_id INTEGER,
                    saved_date TIMESTAMP
                )''')
                
                # Restore data
                for table_name, rows in backup_data['tables'].items():
                    if not rows:
                        continue
                    
                    first_row = rows[0]
                    columns = ', '.join(first_row.keys())
                    placeholders = ', '.join(['?'] * len(first_row))
                    
                    for row in rows:
                        values = [row[col] for col in first_row.keys()]
                        c.execute(f'INSERT INTO {table_name} ({columns}) VALUES ({placeholders})', values)
                
                conn.commit()
                conn.close()
                
                # Verify
                conn = sqlite3.connect(temp_db)
                c = conn.cursor()
                
                tables_to_check = ['users', 'swaps_history', 'reports', 'favorites']
                counts = {}
                
                for table in tables_to_check:
                    c.execute(f'SELECT COUNT(*) FROM {table}')
                    counts[table] = c.fetchone()[0]
                
                conn.close()
                
                # Create backup of current database
                if os.path.exists('face_swap_bot.db'):
                    backup_time = datetime.now().strftime('%Y%m%d_%H%M%S')
                    shutil.copy2('face_swap_bot.db', f'face_swap_bot_backup_{backup_time}.db')
                
                # Replace database
                os.rename(temp_db, 'face_swap_bot.db')
                
                message_lines = ["✅ Database restored successfully!"]
                message_lines.append(f"📊 Restored data:")
                for table, count in counts.items():
                    message_lines.append(f"• {table}: {count} records")
                message_lines.append(f"⏰ Backup timestamp: {backup_data.get('timestamp', 'Unknown')}")
                message_lines.append(f"🔧 Version: {backup_data.get('version', 'Unknown')}")
                
                os.remove(tmp_path)
                
                return True, '\n'.join(message_lines)
            else:
                return False, "❌ No valid backup file found"
    
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        return False, f"❌ Restore failed: {str(e)}"

# ========== UTILITY FUNCTIONS ==========
def generate_progress_bar(percent: int) -> str:
    """Generate a progress bar string"""
    filled = int(percent / 10)
    return "█" * filled + "░" * (10 - filled)

def estimate_time(start_time: float, progress: int) -> str:
    """Estimate remaining time based on progress"""
    if progress == 0:
        return "Calculating..."
    
    elapsed = time.time() - start_time
    total = elapsed / (progress / 100)
    remaining = total - elapsed
    
    if remaining < 60:
        return f"{int(remaining)}s"
    elif remaining < 3600:
        return f"{int(remaining/60)}m {int(remaining%60)}s"
    else:
        return f"{int(remaining/3600)}h {int((remaining%3600)/60)}m"

def download_telegram_photo(file_id: str) -> Optional[bytes]:
    """Download photo from Telegram"""
    try:
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        response = requests.get(file_url, timeout=30)
        
        if response.status_code == 200:
            return response.content
        else:
            logger.error(f"Failed to download photo: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error downloading photo: {e}")
        return None

# ========== USER MANAGEMENT FUNCTIONS ==========
def register_user(user_id: int, username: str, first_name: str, last_name: str) -> bool:
    """Register a new user"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    is_new = c.fetchone() is None
    
    data_hash = hashlib.sha256(f"{user_id}{username}{first_name}{last_name}".encode()).hexdigest()
    
    if is_new:
        c.execute('''INSERT INTO users 
            (user_id, username, first_name, last_name, last_active, data_hash, notified_admin)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, 0)''',
            (user_id, username, first_name, last_name, data_hash))
    else:
        c.execute('''UPDATE users SET 
            username = ?, first_name = ?, last_name = ?, last_active = CURRENT_TIMESTAMP, data_hash = ?
            WHERE user_id = ?''',
            (username, first_name, last_name, data_hash, user_id))
    
    conn.commit()
    conn.close()
    
    if is_new:
        notify_admin_new_user(user_id, username, first_name, last_name)
        logger.info(f"New user registered: {user_id}")
    
    return is_new

def ban_user(user_id: int) -> None:
    """Ban a user"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    BANNED_USERS.add(user_id)
    logger.info(f"User banned: {user_id}")

def unban_user(user_id: int) -> None:
    """Unban a user"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    BANNED_USERS.discard(user_id)
    logger.info(f"User unbanned: {user_id}")

def get_all_users(limit: int = 100, offset: int = 0) -> List[Tuple]:
    """Get all users with pagination"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT user_id, username, first_name, last_name, join_date, last_active,
        is_banned, verified, swaps_count, successful_swaps, failed_swaps 
        FROM users 
        ORDER BY join_date DESC 
        LIMIT ? OFFSET ?''', (limit, offset))
    users = c.fetchall()
    conn.close()
    return users

def check_channel_membership(user_id: int) -> bool:
    """Check if user is member of required channel"""
    try:
        channel_username = REQUIRED_CHANNEL.replace('@', '')
        member = bot.get_chat_member(f"@{channel_username}", user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Failed to check channel membership: {e}")
        return False

def verify_user(user_id: int) -> None:
    """Verify user"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET verified = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    logger.info(f"User verified: {user_id}")

def update_user_stats(user_id: int, success: bool = True) -> None:
    """FIXED: Update user statistics properly"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # First, get current stats
    c.execute('SELECT swaps_count, successful_swaps, failed_swaps FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    
    if result:
        swaps_count, successful_swaps, failed_swaps = result
    else:
        swaps_count, successful_swaps, failed_swaps = 0, 0, 0
    
    # Update based on success/failure
    swaps_count += 1
    if success:
        successful_swaps += 1
    else:
        failed_swaps += 1
    
    # Update database
    c.execute('''UPDATE users SET 
        swaps_count = ?,
        successful_swaps = ?,
        failed_swaps = ?,
        last_active = CURRENT_TIMESTAMP
        WHERE user_id = ?''', 
        (swaps_count, successful_swaps, failed_swaps, user_id))
    
    conn.commit()
    conn.close()
    
    logger.info(f"Updated stats for user {user_id}: total={swaps_count}, success={successful_swaps}, failed={failed_swaps}")

def add_swap_history(user_id: int, status: str, processing_time: float, 
                     result_path: str = None, nsfw: bool = False) -> int:
    """FIXED: Add a swap to history with proper status"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''INSERT INTO swaps_history 
        (user_id, status, processing_time, result_path, nsfw_detected)
        VALUES (?, ?, ?, ?, ?)''', 
        (user_id, status, processing_time, result_path, 1 if nsfw else 0))
    
    swap_id = c.lastrowid
    conn.commit()
    conn.close()
    
    logger.info(f"Swap history added: ID={swap_id}, User={user_id}, Status={status}")
    return swap_id

def add_favorite(user_id: int, swap_id: int) -> bool:
    """Add a swap to favorites"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('SELECT id FROM favorites WHERE user_id = ? AND swap_id = ?', (user_id, swap_id))
        if c.fetchone():
            return False
        
        c.execute('INSERT INTO favorites (user_id, swap_id) VALUES (?, ?)', (user_id, swap_id))
        conn.commit()
        conn.close()
        
        logger.info(f"Favorite added: User={user_id}, Swap={swap_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to add favorite: {e}")
        return False

def get_user_favorites(user_id: int, limit: int = 10) -> List[Tuple]:
    """Get user's favorite swaps"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''SELECT s.id, s.result_path, s.swap_date, s.status 
        FROM swaps_history s
        JOIN favorites f ON s.id = f.swap_id 
        WHERE f.user_id = ? 
        ORDER BY f.saved_date DESC 
        LIMIT ?''', (user_id, limit))
    
    favorites = c.fetchall()
    conn.close()
    return favorites

def add_report(reporter_id: int, swap_id: int, reason: str) -> int:
    """Add a report"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''INSERT INTO reports (reporter_id, reported_swap_id, reason)
        VALUES (?, ?, ?)''', (reporter_id, swap_id, reason))
    
    report_id = c.lastrowid
    conn.commit()
    conn.close()
    
    logger.info(f"Report added: ID={report_id}, Reporter={reporter_id}, Swap={swap_id}")
    
    # Notify admin
    notify_admin_report(report_id, reporter_id, swap_id, reason)
    
    return report_id

def get_pending_reports(limit: int = 20) -> List[Tuple]:
    """Get pending reports"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''SELECT r.id, r.reporter_id, r.reported_swap_id, r.reason, 
        r.report_date, u.username 
        FROM reports r
        LEFT JOIN users u ON r.reporter_id = u.user_id
        WHERE r.status = 'pending'
        ORDER BY r.report_date DESC 
        LIMIT ?''', (limit,))
    
    reports = c.fetchall()
    conn.close()
    return reports

def update_report_status(report_id: int, status: str, admin_notes: str = None) -> bool:
    """Update report status"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        if admin_notes:
            c.execute('''UPDATE reports SET status = ?, admin_notes = ? 
                WHERE id = ?''', (status, admin_notes, report_id))
        else:
            c.execute('UPDATE reports SET status = ? WHERE id = ?', (status, report_id))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Report {report_id} updated to status: {status}")
        return True
    except Exception as e:
        logger.error(f"Failed to update report: {e}")
        return False

# ========== FACE SWAP API FUNCTIONS ==========
def call_face_swap_api(source_image: bytes, target_image: bytes) -> Optional[bytes]:
    """Call the face swap API"""
    try:
        logger.info("Calling face swap API...")
        
        source_base64 = base64.b64encode(source_image).decode('utf-8')
        target_base64 = base64.b64encode(target_image).decode('utf-8')
        
        payload = {
            "source": source_base64,
            "target": target_base64,
            "security": {
                "token": FACE_SWAP_API_TOKEN,
                "type": "invisible",
                "id": "deepswapper"
            }
        }
        
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'FaceSwapBot/3.5'
        }
        
        response = requests.post(
            FACE_SWAP_API_URL,
            json=payload,
            headers=headers,
            timeout=60
        )
        
        logger.info(f"API Response Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            
            if 'result' in result and result['result']:
                result_image = base64.b64decode(result['result'])
                logger.info(f"Successfully decoded result image: {len(result_image)} bytes")
                return result_image
            else:
                logger.error(f"API response missing 'result': {result}")
                return None
        else:
            logger.error(f"API Error {response.status_code}: {response.text}")
            return None
            
    except requests.exceptions.Timeout:
        logger.error("API request timed out")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in face swap API call: {e}")
        return None

# ========== BOT HANDLERS ==========
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Handle /start and /help commands"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if user_id in BANNED_USERS:
        bot.reply_to(message, "🚫 <b>Access Denied</b>\n\nYour account has been banned from using this bot.", parse_mode='HTML')
        return
    
    register_user(
        user_id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    
    if chat_id in user_sessions:
        del user_sessions[chat_id]
    
    if not check_channel_membership(user_id):
        welcome_text = f"""👋 <b>Welcome to Face Swap Bot!</b>

📢 <b>To use this bot, you must join our channel:</b>
{REQUIRED_CHANNEL}

<b>Steps:</b>
1️⃣ Click the 'Join Channel' button below
2️⃣ After joining, click 'Verify Membership'
3️⃣ Start swapping faces!

✨ <b>Features:</b>
• High-quality face swapping
• Save your favorite swaps
• View swap history
• Report inappropriate content

<i>Note: The channel contains updates and announcements.</i>"""
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{REQUIRED_CHANNEL.replace('@', '')}"),
            types.InlineKeyboardButton("✅ Verify Membership", callback_data="verify_join")
        )
        
        bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode='HTML')
    else:
        verify_user(user_id)
        show_main_menu(message)

@bot.callback_query_handler(func=lambda call: call.data == "verify_join")
def verify_callback(call):
    """Handle channel verification callback"""
    user_id = call.from_user.id
    
    if check_channel_membership(user_id):
        verify_user(user_id)
        bot.answer_callback_query(call.id, "✅ Verified! You can now use the bot.")
        
        bot.edit_message_text(
            "✅ <b>Verification Successful!</b>\n\nYou can now use all features of the bot.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML'
        )
        
        time.sleep(1)
        show_main_menu(call.message)
    else:
        bot.answer_callback_query(
            call.id,
            "❌ Please join the channel first!",
            show_alert=True
        )

def show_main_menu(message):
    """Show the main menu to the user"""
    menu_text = """✨ <b>Face Swap Bot</b> ✨

🎭 <b>Main Features:</b>
• Swap faces between photos
• Save favorite swaps
• View swap history
• Report inappropriate content

📋 <b>Available Commands:</b>
/swap - Start a new face swap
/mystats - View your statistics
/favorites - View saved swaps
/history - View recent swaps
/cancel - Cancel current swap
/report - Report content
/help - Show this help message

💡 <b>Tips for Best Results:</b>
✓ Use clear, front-facing photos
✓ Good lighting works best
✓ Single person per photo recommended
✓ Avoid blurry or dark images

👑 <b>Created by:</b> @VinitOG
🔄 <b>Version:</b> 3.5"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🎭 Start Swap", callback_data="start_swap"),
        types.InlineKeyboardButton("📊 My Stats", callback_data="my_stats")
    )
    markup.add(
        types.InlineKeyboardButton("⭐ Favorites", callback_data="view_favorites"),
        types.InlineKeyboardButton("📜 History", callback_data="view_history")
    )
    
    bot.send_message(message.chat.id, menu_text, reply_markup=markup, parse_mode='HTML')

@bot.message_handler(commands=['swap'])
def start_swap_command(message):
    """Start a new face swap process"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if user_id in BANNED_USERS:
        bot.reply_to(message, "🚫 Your account has been banned.")
        return
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT verified FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    
    if not result or result[0] == 0:
        if not check_channel_membership(user_id):
            bot.reply_to(message, f"❌ Please join {REQUIRED_CHANNEL} first and verify!")
            return
    
    if chat_id in user_sessions:
        del user_sessions[chat_id]
    
    user_sessions[chat_id] = {
        'state': STATE_WAITING_SOURCE,
        'user_id': user_id,
        'source_photo': None,
        'target_photo': None,
        'start_time': None
    }
    
    instructions = """🎭 <b>Face Swap Started!</b>

📸 <b>Step 1 of 2:</b> Send the <b>SOURCE</b> photo
(This is the face you want to use)

💡 <b>Tips for best results:</b>
✓ Clear, front-facing photo
✓ Good lighting
✓ Single person visible
✓ Face should be clearly visible

⏳ <b>What happens next:</b>
1. You'll send the source photo
2. Then send the target photo
3. We'll process the swap
4. You'll get the result

❌ Type /cancel at any time to stop

👉 <b>Please send the SOURCE photo now...</b>"""
    
    bot.reply_to(message, instructions, parse_mode='HTML')
    logger.info(f"Started swap session for user {user_id}, waiting for source photo")

@bot.callback_query_handler(func=lambda call: call.data == "start_swap")
def start_swap_callback(call):
    """Handle start swap callback"""
    start_swap_command(call.message)

@bot.message_handler(commands=['cancel'])
def cancel_swap_command(message):
    """Cancel the current swap"""
    chat_id = message.chat.id
    
    if chat_id in user_sessions:
        del user_sessions[chat_id]
        
        if chat_id in active_swaps:
            del active_swaps[chat_id]
        
        cancel_text = """❌ <b>Swap Cancelled</b>

Your face swap session has been cancelled.

💡 You can start a new swap anytime with:
• /swap command, or
• Clicking "Start Swap" button

We hope to see you again soon! 🎭"""
        
        bot.reply_to(message, cancel_text, parse_mode='HTML')
        logger.info(f"Cancelled swap session for chat {chat_id}")
    else:
        bot.reply_to(message, "⚠️ No active swap to cancel. Use /swap to start a new one.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    """Handle photo uploads for face swapping"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if user_id in BANNED_USERS:
        bot.reply_to(message, "🚫 Your account has been banned.")
        return
    
    if chat_id not in user_sessions:
        if chat_id in backup_restore_data and backup_restore_data[chat_id].get('waiting_for_backup'):
            bot.reply_to(message, "📎 Please send the backup file as a document, not a photo.")
            return
        
        bot.reply_to(message, "⚠️ No active swap session. Use /swap to start a new face swap.")
        return
    
    session = user_sessions[chat_id]
    state = session['state']
    
    file_id = message.photo[-1].file_id
    
    if state == STATE_WAITING_SOURCE:
        bot.reply_to(message, "⏳ Downloading source photo...")
        photo_data = download_telegram_photo(file_id)
        
        if photo_data:
            session['source_photo'] = photo_data
            session['state'] = STATE_WAITING_TARGET
            session['start_time'] = time.time()
            
            bot.reply_to(message, """✅ <b>Source Photo Received!</b>

📸 <b>Step 2 of 2:</b> Send the <b>TARGET</b> photo
(This is the photo where the face will be placed)

💡 <b>Tips for target photo:</b>
✓ Clear, good quality image
✓ Face should be visible
✓ Similar lighting to source works best

⏳ <b>Processing will start immediately after you send the target photo.</b>

👉 <b>Please send the TARGET photo now...</b>""", parse_mode='HTML')
            
            logger.info(f"Source photo received for user {user_id}, waiting for target")
        else:
            bot.reply_to(message, "❌ Failed to download photo. Please try again.")
    
    elif state == STATE_WAITING_TARGET:
        if session['source_photo'] is None:
            bot.reply_to(message, "⚠️ Source photo missing. Please start over with /swap")
            del user_sessions[chat_id]
            return
        
        bot.reply_to(message, "⏳ Downloading target photo...")
        photo_data = download_telegram_photo(file_id)
        
        if photo_data:
            session['target_photo'] = photo_data
            session['state'] = STATE_PROCESSING
            
            threading.Thread(
                target=process_face_swap,
                args=(chat_id, session),
                daemon=True
            ).start()
            
            logger.info(f"Target photo received for user {user_id}, starting processing")
        else:
            bot.reply_to(message, "❌ Failed to download photo. Please try again.")
    
    elif state == STATE_PROCESSING:
        bot.reply_to(message, """⏳ <b>Please wait</b>

Your swap is currently being processed. Please wait for it to complete before sending more photos.

💡 If it's taking too long, you can:
• Wait a bit more
• Use /cancel and start over
• Contact support if problem persists""", parse_mode='HTML')
    
    else:
        bot.reply_to(message, "⚠️ Invalid session state. Please use /swap to start over.")
        if chat_id in user_sessions:
            del user_sessions[chat_id]

def process_face_swap(chat_id, session):
    """FIXED: Process the face swap with proper database updates"""
    user_id = session['user_id']
    source_photo = session['source_photo']
    target_photo = session['target_photo']
    start_time = session['start_time']
    
    try:
        progress_msg = bot.send_message(
            chat_id,
            """🔄 <b>Processing Face Swap...</b>

[░░░░░░░░░░] 0%
⏱️ Estimated: Calculating...

⚙️ <b>Initializing face detection...</b>
💡 This may take 15-30 seconds...""",
            parse_mode='HTML'
        )
        
        active_swaps[chat_id] = {
            'progress': 0,
            'status': 'Initializing',
            'start_time': time.time(),
            'message_id': progress_msg.message_id
        }
        
        for progress in [10, 25, 45, 65, 85]:
            if chat_id not in active_swaps:
                return
                
            time.sleep(1.5)
            active_swaps[chat_id]['progress'] = progress
            
            bar = generate_progress_bar(progress)
            est_time = estimate_time(active_swaps[chat_id]['start_time'], progress)
            
            status_text = "Detecting faces..." if progress < 30 else \
                         "Aligning features..." if progress < 60 else \
                         "Swapping faces..." if progress < 85 else \
                         "Finalizing..."
            
            try:
                bot.edit_message_text(
                    f"""🔄 <b>Processing Face Swap...</b>

[{bar}] {progress}%
⏱️ Estimated: {est_time}

⚙️ <b>Status:</b> {status_text}
🎯 <b>Progress:</b> {progress}% complete""",
                    chat_id,
                    progress_msg.message_id,
                    parse_mode='HTML'
                )
            except:
                pass
        
        logger.info(f"Calling face swap API for user {user_id}")
        
        try:
            bot.edit_message_text(
                """🔄 <b>Processing Face Swap...</b>

[██████░░░░] 90%
⏱️ Estimated: 5-10 seconds

⚙️ <b>Status:</b> Swapping faces with AI...
🎯 <b>Progress:</b> Finalizing swap""",
                chat_id,
                progress_msg.message_id,
                parse_mode='HTML'
            )
        except:
            pass
        
        result_image = call_face_swap_api(source_photo, target_photo)
        
        processing_time = time.time() - start_time
        
        if result_image:
            # Save result image
            os.makedirs('results', exist_ok=True)
            filename = f"swap_{user_id}_{int(time.time())}.png"
            filepath = os.path.join('results', filename)
            
            with open(filepath, 'wb') as f:
                f.write(result_image)
            
            # Update progress to 100%
            try:
                bot.edit_message_text(
                    f"""✅ <b>Face Swap Complete!</b>

[██████████] 100%
⏱️ Time: {processing_time:.1f}s

🎉 <b>Success!</b> Your face swap is ready.""",
                    chat_id,
                    progress_msg.message_id,
                    parse_mode='HTML'
                )
            except:
                pass
            
            # FIXED: Store swap in history FIRST
            swap_id = add_swap_history(
                user_id,
                "success",  # Make sure status is "success"
                processing_time,
                filepath,
                False
            )
            
            # FIXED: Update user statistics
            update_user_stats(user_id, True)
            
            # Notify admin
            notify_admin_swap_complete(user_id, swap_id, processing_time, True)
            
            caption = f"""✨ <b>Face Swap Complete!</b>

🆔 <b>Swap ID:</b> #{swap_id}
⏱️ <b>Time:</b> {processing_time:.1f} seconds
✅ <b>Status:</b> Success
📊 <b>Your Stats:</b> {get_user_swap_count(user_id)} swaps, {get_user_success_rate(user_id)}% success rate

💡 <b>Tips:</b>
• Save to favorites for later
• Share with friends
• Try different photos

<i>Note: Result quality depends on input photo quality.</i>"""
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("⭐ Save Favorite", callback_data=f"fav_{swap_id}"),
                types.InlineKeyboardButton("🔄 Swap Again", callback_data="start_swap")
            )
            markup.add(
                types.InlineKeyboardButton("🚨 Report", callback_data=f"report_{swap_id}")
            )
            
            with open(filepath, 'rb') as photo:
                bot.send_photo(
                    chat_id,
                    photo,
                    caption=caption,
                    reply_markup=markup,
                    parse_mode='HTML'
                )
            
            logger.info(f"Swap successful for user {user_id}, ID={swap_id}, time: {processing_time:.2f}s, stats updated")
            
        else:
            logger.error(f"Face swap API failed for user {user_id}")
            
            try:
                bot.edit_message_text(
                    f"""❌ <b>Face Swap Failed</b>

[░░░░░░░░░░] 0%
⏱️ Time: {processing_time:.1f}s

⚠️ <b>Error:</b> Processing failed
🔄 <b>Status:</b> Please try again

💡 <b>Possible reasons:</b>
• Poor quality photos
• No faces detected
• API service temporary issue
• Connection timeout

🎯 <b>Solution:</b> Try with different, clearer photos.""",
                    chat_id,
                    progress_msg.message_id,
                    parse_mode='HTML'
                )
            except:
                pass
            
            # FIXED: Store failed swap in history
            swap_id = add_swap_history(user_id, "failed", processing_time)
            
            # FIXED: Update user stats for failed swap
            update_user_stats(user_id, False)
            
            notify_admin_swap_complete(user_id, swap_id, processing_time, False)
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔄 Try Again", callback_data="start_swap"))
            
            bot.send_message(
                chat_id,
                "😔 <b>Sorry, the face swap failed.</b>\n\nPlease try again with different photos.",
                reply_markup=markup,
                parse_mode='HTML'
            )
    
    except Exception as e:
        logger.error(f"Error in process_face_swap: {e}")
        
        try:
            bot.send_message(
                chat_id,
                f"""❌ <b>Unexpected Error</b>

An unexpected error occurred during processing.

⚠️ <b>Error:</b> {str(e)[:100]}
🔄 <b>Please try again.</b>

If this continues, contact support.""",
                parse_mode='HTML'
            )
        except:
            pass
        
        processing_time = time.time() - start_time if 'start_time' in session else 0
        
        # FIXED: Store error in history
        add_swap_history(user_id, "error", processing_time)
        
        # FIXED: Update user stats for error
        update_user_stats(user_id, False)
        
        notify_admin_swap_complete(user_id, 0, processing_time, False)
    
    finally:
        # Clean up session
        if chat_id in user_sessions:
            del user_sessions[chat_id]
        if chat_id in active_swaps:
            del active_swaps[chat_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith('fav_'))
def add_to_favorites_callback(call):
    """Add swap to favorites"""
    try:
        swap_id = int(call.data.split('_')[1])
        user_id = call.from_user.id
        
        if add_favorite(user_id, swap_id):
            bot.answer_callback_query(call.id, "⭐ Added to favorites!")
            
            try:
                # Also mark as favorite in swaps_history
                conn = get_db_connection()
                c = conn.cursor()
                c.execute('UPDATE swaps_history SET is_favorite = 1 WHERE id = ?', (swap_id,))
                conn.commit()
                conn.close()
                
                if call.message.caption:
                    new_caption = call.message.caption + "\n\n⭐ <b>Saved to Favorites!</b>"
                    bot.edit_message_caption(
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        caption=new_caption,
                        parse_mode='HTML',
                        reply_markup=call.message.reply_markup
                    )
            except:
                pass
        else:
            bot.answer_callback_query(call.id, "⚠️ Already in favorites!")
            
    except Exception as e:
        logger.error(f"Favorite error: {e}")
        bot.answer_callback_query(call.id, "❌ Error saving favorite")

@bot.callback_query_handler(func=lambda call: call.data.startswith('report_'))
def report_swap_callback(call):
    """Report a swap"""
    swap_id = call.data.split('_')[1]
    
    msg = bot.send_message(
        call.message.chat.id,
        f"🚨 <b>Reporting Swap #{swap_id}</b>\n\nPlease describe the issue (inappropriate content, copyright, etc.):\n\n<i>Send your reason as a text message...</i>",
        parse_mode='HTML'
    )
    
    bot.register_next_step_handler(msg, lambda m: process_report(m, swap_id, call.from_user.id))

def process_report(message, swap_id, reporter_id):
    """Process the report"""
    reason = message.text.strip()
    
    if len(reason) < 5:
        bot.reply_to(message, "❌ Please provide a detailed reason (at least 5 characters).")
        return
    
    report_id = add_report(reporter_id, int(swap_id), reason)
    
    bot.reply_to(message, f"""✅ <b>Report Submitted</b>

Thank you for your report (ID: #{report_id}).

📋 <b>Details:</b>
• Swap ID: #{swap_id}
• Reason: {reason[:100]}{'...' if len(reason) > 100 else ''}

⚠️ <b>Note:</b> We will review this report within 24 hours.""", parse_mode='HTML')

@bot.message_handler(commands=['mystats'])
def my_stats_command(message):
    """Show user statistics - FIXED to show accurate data"""
    user_id = message.from_user.id
    
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''SELECT swaps_count, successful_swaps, failed_swaps, 
        join_date, last_active FROM users WHERE user_id = ?''', (user_id,))
    
    result = c.fetchone()
    
    if result:
        total, success, failed, join_date, last_active = result
        
        # Also get count from swaps_history for verification
        c.execute('SELECT COUNT(*) FROM swaps_history WHERE user_id = ?', (user_id,))
        history_count = c.fetchone()[0] or 0
        
        success_rate = round((success / max(1, total)) * 100, 1)
        
        join_date_str = join_date[:10] if join_date else 'Unknown'
        last_active_str = last_active[:19] if last_active else 'Never'
        
        stats_text = f"""📊 <b>Your Statistics</b>

🆔 <b>User ID:</b> <code>{user_id}</code>
📅 <b>Joined:</b> {join_date_str}
🕒 <b>Last Active:</b> {last_active_str}

🔄 <b>Swap Statistics:</b>
• Total Swaps: <b>{total}</b>
• Successful: <b>{success}</b>
• Failed: <b>{failed}</b>
• Success Rate: <b>{success_rate}%</b>
• History Records: <b>{history_count}</b>

🏆 <b>Rank:</b> {'Beginner' if total < 5 else 'Intermediate' if total < 20 else 'Expert'}
📈 <b>Activity Level:</b> {'New User' if total == 0 else 'Active' if total > 5 else 'Casual'}"""
        
        bot.reply_to(message, stats_text, parse_mode='HTML')
    else:
        bot.reply_to(message, "📊 No statistics found. Start with /swap to begin your journey!")
    
    conn.close()

@bot.message_handler(commands=['favorites'])
def show_favorites_command(message):
    """Show user's favorite swaps"""
    user_id = message.from_user.id
    favorites = get_user_favorites(user_id, limit=15)
    
    if not favorites:
        no_favs_text = """⭐ <b>No Favorites Yet</b>

You haven't saved any swaps to favorites yet.

💡 <b>How to save favorites:</b>
1. Complete a face swap
2. Click the "⭐ Save to Favorites" button
3. Your swap will be saved here!

🎭 <b>Get started:</b> Use /swap to create your first swap!"""
        
        bot.reply_to(message, no_favs_text, parse_mode='HTML')
        return
    
    favorites_text = f"""⭐ <b>Your Favorite Swaps</b>

📁 <b>Total Saved:</b> {len(favorites)}

📋 <b>Recent Favorites:</b>\n"""
    
    for i, (swap_id, result_path, swap_date, status) in enumerate(favorites, 1):
        emoji = "✅" if status == "success" else "❌"
        date_str = swap_date[:16] if swap_date else "Unknown"
        favorites_text += f"\n{i}. {emoji} <b>Swap #{swap_id}</b> - {date_str}"
    
    favorites_text += "\n\n💡 <b>Note:</b> Favorites are stored securely and can be accessed anytime."
    
    bot.reply_to(message, favorites_text, parse_mode='HTML')

@bot.message_handler(commands=['history'])
def show_history_command(message):
    """Show user's swap history"""
    user_id = message.from_user.id
    
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''SELECT id, status, swap_date, processing_time 
        FROM swaps_history 
        WHERE user_id = ? 
        ORDER BY swap_date DESC 
        LIMIT 15''', (user_id,))
    
    history = c.fetchall()
    conn.close()
    
    if not history:
        no_history_text = """📜 <b>No Swap History</b>

You haven't performed any swaps yet.

🎭 <b>Ready to start?</b> Use /swap to create your first face swap!"""
        
        bot.reply_to(message, no_history_text, parse_mode='HTML')
        return
    
    history_text = f"""📜 <b>Your Swap History</b>

📊 <b>Total Swaps:</b> {len(history)}

📋 <b>Recent Activity:</b>\n"""
    
    for i, (swap_id, status, swap_date, proc_time) in enumerate(history, 1):
        emoji = "✅" if status == "success" else "❌"
        date_str = swap_date[:16] if swap_date else "Unknown"
        time_str = f"{proc_time:.1f}s" if proc_time else "N/A"
        
        history_text += f"\n{i}. {emoji} <b>Swap #{swap_id}</b>\n"
        history_text += f"   📅 {date_str} | ⏱️ {time_str} | Status: {status}"
    
    # Get user stats for verification
    user_stats = get_user_swap_count(user_id)
    history_text += f"\n\n📊 <b>Stats Verification:</b>\nDatabase shows {user_stats} total swaps"
    
    bot.reply_to(message, history_text, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == "my_stats")
def stats_callback(call):
    """Handle stats callback"""
    my_stats_command(call.message)

@bot.callback_query_handler(func=lambda call: call.data == "view_favorites")
def favorites_callback(call):
    """Handle favorites callback"""
    show_favorites_command(call.message)

@bot.callback_query_handler(func=lambda call: call.data == "view_history")
def history_callback(call):
    """Handle history callback"""
    show_history_command(call.message)

# ========== ADMIN COMMANDS ==========
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    """Admin panel access"""
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Access denied.")
        return
    
    admin_text = f"""👑 <b>Admin Panel</b>

🆔 <b>Admin ID:</b> <code>{ADMIN_ID}</code>
📊 <b>Statistics:</b>
• Users: {get_total_users()}
• Active (24h): {get_active_users_count(1)}
• Swaps: {get_total_swaps()}
• Success Rate: {get_success_rate()}%
• Banned: {len(BANNED_USERS)}

🚨 <b>Pending Actions:</b>
• Reports: {len(get_pending_reports())}

⚙️ <b>Quick Commands:</b>
/users - User management
/reports - View reports
/broadcast - Send message
/botstatus - System status
/createdbbackup - Backup data
/restoredb - Restore data
/fixstats - Fix statistics (NEW)"""

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👥 Users", callback_data="admin_users"),
        types.InlineKeyboardButton("🚨 Reports", callback_data="admin_reports")
    )
    markup.add(
        types.InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
        types.InlineKeyboardButton("💾 Backup", callback_data="admin_backup")
    )
    markup.add(
        types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
        types.InlineKeyboardButton("🔄 Status", callback_data="admin_status")
    )
    markup.add(
        types.InlineKeyboardButton("🔧 Fix Stats", callback_data="admin_fix_stats")
    )
    
    bot.reply_to(message, admin_text, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_fix_stats")
def admin_fix_stats_callback(call):
    """Fix statistics"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    fix_statistics_command(call.message)

@bot.message_handler(commands=['fixstats'])
def fix_statistics_command(message):
    """Fix all user statistics"""
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Access denied.")
        return
    
    bot.reply_to(message, "🔧 <b>Fixing statistics...</b>\n\n⏳ This may take a moment...", parse_mode='HTML')
    
    def fix_stats_task():
        try:
            conn = get_db_connection()
            c = conn.cursor()
            
            # Get all users
            c.execute('SELECT user_id FROM users')
            users = c.fetchall()
            
            fixed_count = 0
            
            for user_row in users:
                user_id = user_row[0]
                
                # Count swaps from history
                c.execute('SELECT COUNT(*), SUM(CASE WHEN status = "success" THEN 1 ELSE 0 END) FROM swaps_history WHERE user_id = ?', (user_id,))
                result = c.fetchone()
                
                if result:
                    total_swaps = result[0] or 0
                    successful_swaps = result[1] or 0
                    failed_swaps = total_swaps - successful_swaps
                    
                    # Update user stats
                    c.execute('''UPDATE users SET 
                        swaps_count = ?,
                        successful_swaps = ?,
                        failed_swaps = ?
                        WHERE user_id = ?''',
                        (total_swaps, successful_swaps, failed_swaps, user_id))
                    
                    fixed_count += 1
            
            conn.commit()
            conn.close()
            
            bot.send_message(
                message.chat.id,
                f"""✅ <b>Statistics Fixed!</b>

📊 <b>Results:</b>
• Users updated: {fixed_count}
• Total users: {len(users)}
• Time: {datetime.now().strftime('%H:%M:%S')}

🔄 <b>Stats have been recalculated from swap history.</b>""",
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Fix stats error: {e}")
            bot.send_message(message.chat.id, f"❌ <b>Error:</b> {str(e)}", parse_mode='HTML')
    
    threading.Thread(target=fix_stats_task, daemon=True).start()

@bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
def admin_stats_callback(call):
    """Admin stats callback"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('SELECT COUNT(*) FROM swaps_history')
    total_swaps = c.fetchone()[0] or 0
    
    c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "success"')
    success_swaps = c.fetchone()[0] or 0
    
    c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "failed"')
    failed_swaps = c.fetchone()[0] or 0
    
    c.execute('SELECT COUNT(*) FROM users WHERE verified = 1')
    verified_users = c.fetchone()[0] or 0
    
    c.execute('SELECT COUNT(*) FROM reports WHERE status = "pending"')
    pending_reports = c.fetchone()[0] or 0
    
    c.execute('SELECT COUNT(*) FROM favorites')
    total_favorites = c.fetchone()[0] or 0
    
    c.execute('SELECT COUNT(*) FROM users WHERE DATE(join_date) = DATE("now")')
    new_today = c.fetchone()[0] or 0
    
    # Verify consistency
    c.execute('SELECT SUM(swaps_count), SUM(successful_swaps), SUM(failed_swaps) FROM users')
    user_stats = c.fetchone()
    user_total = user_stats[0] or 0
    user_success = user_stats[1] or 0
    user_failed = user_stats[2] or 0
    
    success_rate = round((success_swaps / max(1, total_swaps)) * 100, 1)
    
    conn.close()
    
    stats_text = f"""📊 <b>Admin Statistics</b>

👥 <b>Users:</b>
• Total: {get_total_users()}
• Verified: {verified_users}
• New Today: {new_today}
• Banned: {len(BANNED_USERS)}

🔄 <b>Swaps:</b>
• Total (History): {total_swaps}
• Successful: {success_swaps}
• Failed: {failed_swaps}
• Success Rate: {success_rate}%
• From User Stats: {user_total} (✅{user_success} ❌{user_failed})

⭐ <b>Engagement:</b>
• Favorites: {total_favorites}
• Pending Reports: {pending_reports}
• Active Sessions: {len(user_sessions)}

📱 <b>Current:</b>
• Active Swaps: {len(active_swaps)}
• Memory Usage: OK
• Database: Connected"""

    bot.edit_message_text(
        stats_text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML'
    )

@bot.callback_query_handler(func=lambda call: call.data == "admin_users")
def admin_users_callback(call):
    """Admin users callback"""
    list_users_command(call.message)

@bot.message_handler(commands=['users'])
def list_users_command(message):
    """List all users"""
    if message.from_user.id != ADMIN_ID:
        return
    
    users = get_all_users(limit=50)
    
    if not users:
        bot.reply_to(message, "📭 No users found.")
        return
    
    page = 0
    users_per_page = 5
    total_pages = (len(users) + users_per_page - 1) // users_per_page
    
    start_idx = page * users_per_page
    end_idx = min(start_idx + users_per_page, len(users))
    page_users = users[start_idx:end_idx]
    
    users_text = f"""👥 <b>User Management</b>

📊 <b>Total Users:</b> {len(users)}
📑 <b>Page:</b> {page + 1}/{total_pages}

━━━━━━━━━━━━━━━━━━\n"""
    
    for user in page_users:
        user_id, username, first_name, last_name, join_date, last_active, banned, verified, total, success, failed = user
        
        status = "🔴 BANNED" if banned else "🟢 ACTIVE"
        verified_status = "✅" if verified else "❌"
        username_display = f"@{username}" if username else f"ID:{user_id}"
        
        users_text += f"\n🆔 <b>{user_id}</b>\n"
        users_text += f"👤 {username_display}\n"
        users_text += f"📛 {first_name} {last_name or ''}\n"
        users_text += f"📊 {status} | Verified: {verified_status}\n"
        users_text += f"🔄 Swaps: {total} (✅{success} ❌{failed})\n"
        users_text += f"📅 Joined: {join_date[:10] if join_date else 'N/A'}\n"
        users_text += f"━━━━━━━━━━━━━━━━━━\n"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    for user in page_users:
        user_id = user[0]
        username = user[1] or f"ID:{user_id}"
        is_banned = user[6]
        
        if is_banned:
            markup.add(types.InlineKeyboardButton(
                f"🟢 Unban {username[:15]}",
                callback_data=f"admin_unban_{user_id}"
            ))
        else:
            markup.add(types.InlineKeyboardButton(
                f"🔴 Ban {username[:15]}",
                callback_data=f"admin_ban_{user_id}"
            ))
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Previous", callback_data=f"admin_users_page_{page-1}"))
    
    if page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"admin_users_page_{page+1}"))
    
    if nav_buttons:
        markup.row(*nav_buttons)
    
    markup.add(types.InlineKeyboardButton("🔄 Refresh", callback_data="admin_users_refresh"))
    markup.add(types.InlineKeyboardButton("🔧 Fix User Stats", callback_data="admin_fix_user_stats"))
    
    bot.reply_to(message, users_text, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_fix_user_stats")
def admin_fix_user_stats_callback(call):
    """Fix stats for current page users"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    # Parse the message to get users
    message_text = call.message.text
    
    # Extract user IDs from message
    import re
    user_ids = re.findall(r'🆔 <b>(\d+)</b>', message_text)
    
    if not user_ids:
        bot.answer_callback_query(call.id, "❌ No users found")
        return
    
    fixed = 0
    for user_id_str in user_ids:
        user_id = int(user_id_str)
        
        conn = get_db_connection()
        c = conn.cursor()
        
        # Count swaps from history
        c.execute('SELECT COUNT(*), SUM(CASE WHEN status = "success" THEN 1 ELSE 0 END) FROM swaps_history WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        
        if result:
            total_swaps = result[0] or 0
            successful_swaps = result[1] or 0
            failed_swaps = total_swaps - successful_swaps
            
            # Update user stats
            c.execute('''UPDATE users SET 
                swaps_count = ?,
                successful_swaps = ?,
                failed_swaps = ?
                WHERE user_id = ?''',
                (total_swaps, successful_swaps, failed_swaps, user_id))
            
            conn.commit()
            fixed += 1
        
        conn.close()
    
    bot.answer_callback_query(call.id, f"✅ Fixed stats for {fixed} users")
    list_users_command(call.message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_ban_'))
def admin_ban_callback(call):
    """Ban user from admin panel"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    user_id = int(call.data.split('_')[2])
    ban_user(user_id)
    
    try:
        bot.send_message(user_id, "🚫 <b>You have been banned from using this bot.</b>", parse_mode='HTML')
    except:
        pass
    
    bot.answer_callback_query(call.id, f"✅ User {user_id} banned!")
    list_users_command(call.message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_unban_'))
def admin_unban_callback(call):
    """Unban user from admin panel"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    user_id = int(call.data.split('_')[2])
    unban_user(user_id)
    
    try:
        bot.send_message(user_id, "✅ <b>Your ban has been lifted! You can now use the bot again.</b>", parse_mode='HTML')
    except:
        pass
    
    bot.answer_callback_query(call.id, f"✅ User {user_id} unbanned!")
    list_users_command(call.message)

@bot.message_handler(commands=['ban'])
def ban_command(message):
    """Ban a user by ID"""
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /ban <user_id>")
            return
        
        user_id = int(parts[1])
        ban_user(user_id)
        
        try:
            bot.send_message(user_id, "🚫 <b>You have been banned from using this bot.</b>", parse_mode='HTML')
        except:
            pass
        
        bot.reply_to(message, f"✅ User {user_id} has been banned.")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['unban'])
def unban_command(message):
    """Unban a user by ID"""
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /unban <user_id>")
            return
        
        user_id = int(parts[1])
        unban_user(user_id)
        
        try:
            bot.send_message(user_id, "✅ <b>Your ban has been lifted! You can now use the bot again.</b>", parse_mode='HTML')
        except:
            pass
        
        bot.reply_to(message, f"✅ User {user_id} has been unbanned.")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "admin_reports")
def admin_reports_callback(call):
    """Admin reports callback"""
    view_reports_command(call.message)

@bot.message_handler(commands=['reports'])
def view_reports_command(message):
    """View all reports"""
    if message.from_user.id != ADMIN_ID:
        return
    
    reports = get_pending_reports()
    
    if not reports:
        bot.reply_to(message, "📭 No pending reports.")
        return
    
    reports_text = f"""🚨 <b>REPORT MANAGEMENT</b>

📊 <b>Pending Reports:</b> {len(reports)}

━━━━━━━━━━━━━━━━━━\n"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    for report in reports[:5]:
        report_id, reporter_id, swap_id, reason, report_date, username = report
        
        username_display = f"@{username}" if username else f"ID:{reporter_id}"
        
        reports_text += f"\n🆔 <b>Report #{report_id}</b>\n"
        reports_text += f"👤 Reporter: {username_display}\n"
        reports_text += f"🔄 Swap ID: #{swap_id}\n"
        reports_text += f"📝 Reason: {reason[:50]}{'...' if len(reason) > 50 else ''}\n"
        reports_text += f"⏰ Date: {report_date[:16] if report_date else 'N/A'}\n"
        reports_text += f"━━━━━━━━━━━━━━━━━━\n"
        
        markup.add(
            types.InlineKeyboardButton(f"✅ Resolve #{report_id}", callback_data=f"resolve_{report_id}"),
            types.InlineKeyboardButton(f"👁️ View #{swap_id}", callback_data=f"view_swap_{swap_id}")
        )
    
    markup.add(types.InlineKeyboardButton("🔄 Refresh", callback_data="admin_reports"))
    
    bot.reply_to(message, reports_text, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('resolve_'))
def resolve_report_callback(call):
    """Resolve a report"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    report_id = int(call.data.split('_')[1])
    
    msg = bot.send_message(
        call.message.chat.id,
        f"📝 <b>Resolving Report #{report_id}</b>\n\nPlease enter resolution notes:",
        parse_mode='HTML'
    )
    
    bot.register_next_step_handler(msg, lambda m: process_resolution(m, report_id))

def process_resolution(message, report_id):
    """Process report resolution"""
    admin_notes = message.text.strip()
    
    if update_report_status(report_id, "resolved", admin_notes):
        bot.reply_to(message, f"✅ Report #{report_id} has been resolved.")
    else:
        bot.reply_to(message, f"❌ Failed to resolve report #{report_id}.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('view_swap_'))
def view_swap_callback(call):
    """View swap details"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    swap_id = int(call.data.split('_')[2])
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT s.*, u.username, u.user_id, u.swaps_count, u.successful_swaps
        FROM swaps_history s
        JOIN users u ON s.user_id = u.user_id
        WHERE s.id = ?''', (swap_id,))
    
    swap = c.fetchone()
    conn.close()
    
    if swap:
        swap_info = f"""🔄 <b>Swap Details</b>

🆔 Swap ID: #{swap['id']}
👤 User: @{swap['username']} (ID: {swap['user_id']})
📅 Date: {swap['swap_date']}
⏱️ Time: {swap['processing_time']:.1f}s
✅ Status: {swap['status']}
⭐ Favorite: {'Yes' if swap['is_favorite'] else 'No'}
🚨 NSFW: {'Detected' if swap['nsfw_detected'] else 'Clean'}

📁 Path: {swap['result_path'] or 'N/A'}

📊 <b>User Stats:</b>
• Total Swaps: {swap['swaps_count']}
• Successful: {swap['successful_swaps']}
• Success Rate: {round((swap['successful_swaps'] / max(1, swap['swaps_count'])) * 100, 1)}%"""
        
        bot.answer_callback_query(call.id, "Swap details loaded")
        bot.send_message(call.message.chat.id, swap_info, parse_mode='HTML')
    else:
        bot.answer_callback_query(call.id, "❌ Swap not found")

@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast")
def admin_broadcast_callback(call):
    """Admin broadcast callback"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    msg = bot.send_message(
        call.message.chat.id,
        "📢 <b>Broadcast Message</b>\n\nPlease enter your broadcast message:",
        parse_mode='HTML'
    )
    
    bot.register_next_step_handler(msg, process_broadcast)

def process_broadcast(message):
    """Process broadcast message"""
    broadcast_text = message.text.strip()
    
    if not broadcast_text:
        bot.reply_to(message, "❌ Broadcast message cannot be empty.")
        return
    
    confirm_text = f"""📢 <b>BROADCAST CONFIRMATION</b>

<b>Message:</b>
{broadcast_text}

<b>Recipients:</b> {get_total_users() - len(BANNED_USERS)} users
<b>Banned users excluded:</b> {len(BANNED_USERS)}

⚠️ <b>Are you sure?</b>"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Send", callback_data=f"broadcast_send_{hashlib.md5(broadcast_text.encode()).hexdigest()[:8]}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel")
    )
    
    bot.reply_to(message, confirm_text, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('broadcast_send_'))
def send_broadcast_callback(call):
    """Send broadcast"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    original_text = call.message.text
    lines = original_text.split('\n')
    
    message_start = None
    message_end = None
    
    for i, line in enumerate(lines):
        if "Message:" in line:
            message_start = i + 1
        if "Recipients:" in line and message_start is not None:
            message_end = i
            break
    
    if message_start is None or message_end is None:
        bot.answer_callback_query(call.id, "❌ Could not extract message.")
        return
    
    broadcast_text = '\n'.join(lines[message_start:message_end]).strip()
    
    bot.edit_message_text(
        "📢 <b>Sending broadcast...</b>\n\n⏳ Please wait...",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML'
    )
    
    users = get_all_users(limit=1000)
    sent = 0
    failed = 0
    
    for user in users:
        user_id = user[0]
        
        if user_id in BANNED_USERS:
            continue
        
        try:
            bot.send_message(
                user_id,
                f"""📢 <b>Announcement from Admin</b>

{broadcast_text}

<i>This is an automated message from Face Swap Bot.</i>""",
                parse_mode='HTML'
            )
            sent += 1
            time.sleep(0.05)
            
        except:
            failed += 1
    
    result_text = f"""✅ <b>Broadcast Complete!</b>

📊 <b>Results:</b>
• Sent: <b>{sent}</b> users
• Failed: <b>{failed}</b> users

🕒 <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"""
    
    bot.edit_message_text(
        result_text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML'
    )

@bot.callback_query_handler(func=lambda call: call.data == "broadcast_cancel")
def cancel_broadcast_callback(call):
    """Cancel broadcast"""
    bot.edit_message_text(
        "❌ <b>Broadcast cancelled.</b>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML'
    )

@bot.callback_query_handler(func=lambda call: call.data == "admin_backup")
def admin_backup_callback(call):
    """Admin backup callback"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    create_backup_command(call.message)

@bot.message_handler(commands=['createdbbackup'])
def create_backup_command(message):
    """Create database backup"""
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Access denied.")
        return
    
    bot.reply_to(message, "💾 <b>Creating database backup...</b>\n\n⏳ Please wait...", parse_mode='HTML')
    
    def backup_task():
        try:
            backup_bytes = create_database_backup()
            
            if backup_bytes:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"face_swap_backup_{timestamp}.zip"
                
                bot.send_document(
                    message.chat.id,
                    (filename, backup_bytes),
                    caption=f"""✅ <b>Database Backup Created!</b>

📁 Filename: {filename}
📊 Size: {len(backup_bytes) / 1024:.1f} KB
🕒 Time: {datetime.now().strftime('%H:%M:%S')}
👤 Created by: Admin

⚠️ <b>IMPORTANT:</b>
• Save this file before updating code
• Use /restoredb to restore
• Store in a safe place"""
                )
                
                local_filename = f"backup_{timestamp}.zip"
                with open(local_filename, 'wb') as f:
                    f.write(backup_bytes)
                
                logger.info(f"Backup saved as {local_filename}")
            else:
                bot.reply_to(message, "❌ <b>Backup creation failed!</b>", parse_mode='HTML')
                
        except Exception as e:
            logger.error(f"Backup task error: {e}")
            bot.reply_to(message, f"❌ <b>Backup error:</b> {str(e)}", parse_mode='HTML')
    
    threading.Thread(target=backup_task, daemon=True).start()

@bot.message_handler(commands=['restoredb'])
def restore_database_command(message):
    """Start database restore process"""
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Access denied.")
        return
    
    restore_text = """🔄 <b>Database Restore Process</b>

⚠️ <b>WARNING:</b> This will overwrite current database!
Make sure you have a backup first.

📋 <b>Steps:</b>
1. Use /createdbbackup to backup current data
2. Send the backup ZIP file as a document
3. Confirm restoration

❌ <b>What will be restored:</b>
• All user accounts
• Swap history  
• Reports
• Favorites

💡 <b>Tip:</b> Use this before updating bot code to preserve data.

📎 <b>Please send the backup ZIP file now...</b>"""
    
    backup_restore_data[message.chat.id] = {
        'waiting_for_backup': True,
        'backup_data': None,
        'restore_info': None
    }
    
    bot.reply_to(message, restore_text, parse_mode='HTML')

@bot.message_handler(content_types=['document'])
def handle_document(message):
    """Handle document uploads (for restore)"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if user_id != ADMIN_ID or chat_id not in backup_restore_data:
        return
    
    if not backup_restore_data[chat_id].get('waiting_for_backup'):
        return
    
    file_info = bot.get_file(message.document.file_id)
    file_name = message.document.file_name or 'backup.zip'
    
    if not file_name.endswith('.zip'):
        bot.reply_to(message, "❌ Please send a ZIP file (.zip extension)")
        backup_restore_data.pop(chat_id, None)
        return
    
    bot.reply_to(message, "📥 Downloading backup file...")
    
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
    response = requests.get(file_url, timeout=30)
    
    if response.status_code != 200:
        bot.reply_to(message, "❌ Failed to download file")
        backup_restore_data.pop(chat_id, None)
        return
    
    backup_data = response.content
    
    bot.reply_to(message, "🔍 Validating backup file...")
    
    success, info = restore_database_from_backup(backup_data)
    
    if success:
        backup_restore_data[chat_id] = {
            'waiting_for_backup': False,
            'backup_data': backup_data,
            'restore_info': info
        }
        
        confirm_text = f"""✅ <b>Backup Validated!</b>

{info}

⚠️ <b>FINAL WARNING:</b> This will replace current database!
Current data will be lost unless you have a backup."""
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Confirm Restore", callback_data="confirm_restore_final"),
            types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_restore")
        )
        
        bot.reply_to(message, confirm_text, parse_mode='HTML', reply_markup=markup)
    else:
        bot.reply_to(message, f"❌ <b>Invalid backup file:</b>\n\n{info}", parse_mode='HTML')
        backup_restore_data.pop(chat_id, None)

@bot.callback_query_handler(func=lambda call: call.data == "confirm_restore_final")
def confirm_restore_final_callback(call):
    """Finalize restore"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    chat_id = call.message.chat.id
    
    bot.edit_message_text(
        "🔄 <b>Restoring database...</b>\n\n⏳ This will take a moment...",
        chat_id,
        call.message.message_id,
        parse_mode='HTML'
    )
    
    try:
        init_database()
        
        backup_restore_data.pop(chat_id, None)
        
        bot.edit_message_text(
            "✅ <b>Database Restore Complete!</b>\n\n🔄 Bot has been restarted with restored data.",
            chat_id,
            call.message.message_id,
            parse_mode='HTML'
        )
        
    except Exception as e:
        bot.edit_message_text(
            f"❌ <b>Restore Failed!</b>\n\n{str(e)}",
            chat_id,
            call.message.message_id,
            parse_mode='HTML'
        )

@bot.callback_query_handler(func=lambda call: call.data == "cancel_restore")
def cancel_restore_callback(call):
    """Cancel restore"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    chat_id = call.message.chat.id
    
    backup_restore_data.pop(chat_id, None)
    
    bot.edit_message_text(
        "❌ <b>Database restore cancelled.</b>\n\nNo changes were made.",
        chat_id,
        call.message.message_id,
        parse_mode='HTML'
    )

@bot.callback_query_handler(func=lambda call: call.data == "admin_status")
def admin_status_callback(call):
    """Admin status callback"""
    bot_status_command(call.message)

@bot.message_handler(commands=['botstatus'])
def bot_status_command(message):
    """Show bot status"""
    if message.from_user.id != ADMIN_ID:
        return
    
    status_text = f"""🤖 <b>Bot Status Report</b>

🟢 <b>Status:</b> Operational
📡 <b>Mode:</b> Webhook
🌐 <b>URL:</b> {WEBHOOK_URL}
⏰ <b>Uptime:</b> {int(time.time() - start_time)}s

👥 <b>Statistics:</b>
• Users: {get_total_users()}
• Active (24h): {get_active_users_count(1)}
• Total Swaps: {get_total_swaps()}
• Success Rate: {get_success_rate()}%

📱 <b>Current:</b>
• Active Sessions: {len(user_sessions)}
• Active Swaps: {len(active_swaps)}
• Pending Reports: {len(get_pending_reports())}

💾 <b>Database:</b>
• Size: {os.path.getsize('face_swap_bot.db') / 1024:.1f} KB if os.path.exists('face_swap_bot.db') else 0
• Backups: {len([f for f in os.listdir('.') if f.startswith('backup_')])}

🔗 <b>Endpoints:</b>
• /ping, /ping1, /ping2 - Health checks
• /stats - Statistics
• /status - Status page
• /health/hunter - Detailed health
• /users/hunter - User data
• /fixstats - Fix statistics (NEW)"""
    
    bot.reply_to(message, status_text, parse_mode='HTML')

@bot.message_handler(commands=['cleanup'])
def cleanup_command(message):
    """Clean up old data"""
    if message.from_user.id != ADMIN_ID:
        return
    
    cleanup_text = """🧹 <b>Data Cleanup</b>

Choose what to clean up:

🔄 <b>Old Swaps</b> - Remove swaps older than 30 days
🚨 <b>Old Reports</b> - Remove resolved reports older than 7 days
🗑️ <b>Temporary Files</b> - Clean old result images

⚠️ <b>Warning:</b> Some operations cannot be undone!"""

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔄 Old Swaps", callback_data="cleanup_old_swaps"),
        types.InlineKeyboardButton("🚨 Old Reports", callback_data="cleanup_old_reports")
    )
    markup.add(
        types.InlineKeyboardButton("🗑️ Temp Files", callback_data="cleanup_temp_files"),
        types.InlineKeyboardButton("📊 Stats Only", callback_data="cleanup_stats")
    )
    
    bot.reply_to(message, cleanup_text, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('cleanup_'))
def cleanup_callback(call):
    """Handle cleanup callbacks"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    action = call.data.replace('cleanup_', '')
    
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        if action == 'old_swaps':
            c.execute("DELETE FROM swaps_history WHERE swap_date < datetime('now', '-30 days')")
            deleted = c.rowcount
            
            conn.commit()
            conn.close()
            
            bot.answer_callback_query(call.id, f"✅ Deleted {deleted} old swaps")
            bot.send_message(call.message.chat.id, f"🧹 Deleted {deleted} swaps older than 30 days.")
            
        elif action == 'old_reports':
            c.execute("DELETE FROM reports WHERE status = 'resolved' AND report_date < datetime('now', '-7 days')")
            deleted = c.rowcount
            
            conn.commit()
            conn.close()
            
            bot.answer_callback_query(call.id, f"✅ Deleted {deleted} old reports")
            bot.send_message(call.message.chat.id, f"🧹 Deleted {deleted} resolved reports older than 7 days.")
            
        elif action == 'temp_files':
            import glob
            result_files = glob.glob('results/*.png')
            old_files = []
            
            for file in result_files:
                file_age = time.time() - os.path.getmtime(file)
                if file_age > 86400 * 7:
                    os.remove(file)
                    old_files.append(file)
            
            bot.answer_callback_query(call.id, f"✅ Cleaned {len(old_files)} temp files")
            bot.send_message(call.message.chat.id, f"🗑️ Cleaned {len(old_files)} temporary files older than 7 days.")
            
        elif action == 'stats':
            c.execute("SELECT COUNT(*) FROM swaps_history WHERE swap_date < datetime('now', '-30 days')")
            old_swaps = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM reports WHERE status = 'resolved' AND report_date < datetime('now', '-7 days')")
            old_reports = c.fetchone()[0]
            
            conn.close()
            
            import glob
            result_files = glob.glob('results/*.png')
            old_files_count = 0
            for file in result_files:
                file_age = time.time() - os.path.getmtime(file)
                if file_age > 86400 * 7:
                    old_files_count += 1
            
            stats_text = f"""📊 <b>Cleanup Statistics</b>

🔄 Old Swaps (30+ days): {old_swaps}
🚨 Old Reports (7+ days): {old_reports}
🗑️ Old Files (7+ days): {old_files_count}

💡 <b>Note:</b> These items can be cleaned up."""
            
            bot.answer_callback_query(call.id, "📊 Stats loaded")
            bot.send_message(call.message.chat.id, stats_text, parse_mode='HTML')
            
    except Exception as e:
        logger.error(f"Cleanup error: {e}")
        bot.answer_callback_query(call.id, "❌ Cleanup failed")

# ========== FLASK ROUTES ==========
HTML_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <title>Face Swap Bot</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }
        .container {
            background: white;
            border-radius: 20px;
            padding: 40px;
            max-width: 600px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        h1 {
            color: #667eea;
            text-align: center;
            margin-bottom: 30px;
        }
        .status {
            background: #d4edda;
            color: #155724;
            padding: 10px 20px;
            border-radius: 20px;
            display: inline-block;
            font-weight: bold;
            margin-bottom: 20px;
        }
        .stats {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .stat-item {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #e0e0e0;
        }
        .stat-item:last-child {
            border-bottom: none;
        }
        .label {
            font-weight: 600;
            color: #555;
        }
        .value {
            color: #667eea;
            font-weight: 700;
        }
        .backup-warning {
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            border-radius: 10px;
            padding: 15px;
            margin: 20px 0;
            color: #856404;
        }
        .footer {
            text-align: center;
            margin-top: 30px;
            color: #999;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Face Swap Bot v3.5</h1>
        <div class="status">{{ status }}</div>
        <div class="stats">
            <div class="stat-item">
                <span class="label">Total Users</span>
                <span class="value">{{ total_users }}</span>
            </div>
            <div class="stat-item">
                <span class="label">Active (24h)</span>
                <span class="value">{{ active_24h }}</span>
            </div>
            <div class="stat-item">
                <span class="label">Total Swaps</span>
                <span class="value">{{ total_swaps }}</span>
            </div>
            <div class="stat-item">
                <span class="label">Success Rate</span>
                <span class="value">{{ success_rate }}%</span>
            </div>
            <div class="stat-item">
                <span class="label">Active Sessions</span>
                <span class="value">{{ active_sessions }}</span>
            </div>
        </div>
        <div class="backup-warning">
            ⚠️ <b>Important:</b> Always create backup before updating code!
            Use /createdbbackup in Telegram bot.
        </div>
        <div class="footer">
            <p>Created by @VINITOG | Admin: {{ admin_id }}</p>
            <p>Server Time: {{ server_time }} | Uptime: {{ uptime }}</p>
            <p>Endpoints: /health/hunter • /stats • /status • /ping • /ping1 • /ping2</p>
        </div>
    </div>
</body>
</html>'''

@app.route('/')
def home():
    """Main dashboard page"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM swaps_history')
        total_swaps = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "success"')
        success_swaps = c.fetchone()[0] or 0
        
        success_rate = round((success_swaps / max(1, total_swaps)) * 100, 1)
        conn.close()
        
        return render_template_string(
            HTML_TEMPLATE,
            status="🟢 ONLINE",
            total_users=get_total_users(),
            active_24h=get_active_users_count(1),
            total_swaps=total_swaps,
            success_rate=success_rate,
            active_sessions=len(user_sessions),
            admin_id=ADMIN_ID,
            server_time=datetime.now().strftime('%H:%M:%S'),
            uptime=f"{int(time.time() - start_time)}s"
        )
    except Exception as e:
        logger.error(f"Home page error: {e}")
        return render_template_string(
            HTML_TEMPLATE,
            status="🟡 OFFLINE",
            total_users=0,
            active_24h=0,
            total_swaps=0,
            success_rate=0,
            active_sessions=0,
            admin_id=ADMIN_ID,
            server_time=datetime.now().strftime('%H:%M:%S'),
            uptime="N/A"
        )

@app.route('/health/hunter')
def health_hunter():
    """Health check endpoint"""
    try:
        return jsonify({
            "status": "healthy",
            "service": "Face Swap Bot",
            "version": "3.5",
            "bot": "running",
            "database": "connected",
            "backup_system": "ready",
            "active_sessions": len(user_sessions),
            "active_swaps": len(active_swaps),
            "pending_restores": len(backup_restore_data),
            "timestamp": datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/ping')
def ping():
    """Simple ping endpoint"""
    return jsonify({
        "status": "pong",
        "service": "Face Swap Bot",
        "timestamp": datetime.now().isoformat(),
        "message": "Bot is running on Koyeb",
        "endpoint": "/ping"
    })

@app.route('/ping1')
def ping1():
    """Ping endpoint 1"""
    return jsonify({
        "status": "pong",
        "service": "Face Swap Bot",
        "timestamp": datetime.now().isoformat(),
        "message": "Bot is alive and healthy",
        "endpoint": "/ping1",
        "uptime": int(time.time() - start_time)
    })

@app.route('/ping2')
def ping2():
    """Ping endpoint 2"""
    return jsonify({
        "status": "pong",
        "service": "Face Swap Bot",
        "timestamp": datetime.now().isoformat(),
        "message": "All systems operational",
        "endpoint": "/ping2",
        "bot": "@CarnageJackingBizMetaBot"
    })

@app.route('/stats')
def stats():
    """Public statistics endpoint"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM swaps_history')
        total_swaps = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "success"')
        success_swaps = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "failed"')
        failed_swaps = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM reports WHERE status = "pending"')
        pending_reports = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM favorites')
        total_favorites = c.fetchone()[0] or 0
        
        success_rate = round((success_swaps / max(1, total_swaps)) * 100, 2)
        
        conn.close()
        
        stats_data = {
            "status": "online",
            "service": "Face Swap Bot",
            "version": "3.5",
            "statistics": {
                "users": {
                    "total": get_total_users(),
                    "active_24h": get_active_users_count(1),
                    "banned": len(BANNED_USERS)
                },
                "swaps": {
                    "total": total_swaps,
                    "successful": success_swaps,
                    "failed": failed_swaps,
                    "success_rate": success_rate,
                    "active": len(active_swaps)
                },
                "engagement": {
                    "favorites": total_favorites,
                    "pending_reports": pending_reports
                }
            },
            "performance": {
                "active_sessions": len(user_sessions),
                "uptime": int(time.time() - start_time),
                "server_time": datetime.now().isoformat()
            }
        }
        
        return jsonify(stats_data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/status')
def status_page():
    """Public status page"""
    try:
        return jsonify({
            "status": "online",
            "bot": "@CarnageJackingBizMetaBot",
            "service": "Face Swap Bot",
            "version": "3.5",
            "timestamp": datetime.now().isoformat(),
            "users": get_total_users(),
            "active_sessions": len(user_sessions),
            "uptime": int(time.time() - start_time),
            "endpoints": {
                "health": "/health/hunter",
                "stats": "/stats",
                "users": "/users/hunter",
                "ping": ["/ping", "/ping1", "/ping2"],
                "status": "/status",
                "dashboard": "/"
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/summary')
def summary():
    """Summary endpoint for monitoring dashboards"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM swaps_history')
        total_swaps = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "success"')
        success_swaps = c.fetchone()[0] or 0
        
        success_rate = round((success_swaps / max(1, total_swaps)) * 100, 1)
        conn.close()
        
        summary_data = {
            "status": "online",
            "bot_name": "Face Swap Bot",
            "bot_username": "@CarnageJackingBizMetaBot",
            "total_users": get_total_users(),
            "total_swaps": total_swaps,
            "success_rate": f"{success_rate}%",
            "active_sessions": len(user_sessions),
            "uptime_days": int((time.time() - start_time) / 86400),
            "last_updated": datetime.now().isoformat()
        }
        
        return jsonify(summary_data), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/status/page')
def status_html():
    """HTML status page for quick checks"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Face Swap Bot Status</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 40px;
                background: #f5f5f5;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            .status {
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                display: inline-block;
            }
            .online { background: #d4edda; color: #155724; }
            .offline { background: #f8d7da; color: #721c24; }
            .metric {
                background: #f8f9fa;
                padding: 15px;
                margin: 10px 0;
                border-radius: 5px;
                border-left: 4px solid #007bff;
            }
            .endpoint {
                font-family: monospace;
                background: #e9ecef;
                padding: 5px 10px;
                border-radius: 3px;
                margin: 5px 0;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Face Swap Bot Status</h1>
            
            <div class="status online">🟢 ONLINE</div>
            
            <div class="metric">
                <h3>📊 Basic Info</h3>
                <p><strong>Bot:</strong> @CarnageJackingBizMetaBot</p>
                <p><strong>Version:</strong> 3.5</p>
                <p><strong>Uptime:</strong> {{ uptime }} seconds</p>
                <p><strong>Server Time:</strong> {{ server_time }}</p>
            </div>
            
            <div class="metric">
                <h3>👥 Users</h3>
                <p><strong>Total Users:</strong> {{ total_users }}</p>
                <p><strong>Active Sessions:</strong> {{ active_sessions }}</p>
                <p><strong>Banned Users:</strong> {{ banned_users }}</p>
            </div>
            
            <div class="metric">
                <h3>🔗 Endpoints</h3>
                <div class="endpoint">GET /ping</div>
                <div class="endpoint">GET /ping1</div>
                <div class="endpoint">GET /ping2</div>
                <div class="endpoint">GET /stats</div>
                <div class="endpoint">GET /status</div>
                <div class="endpoint">GET /health/hunter</div>
                <div class="endpoint">GET /summary</div>
            </div>
            
            <div class="metric">
                <h3>📞 Monitoring</h3>
                <p>This page auto-refreshes every 60 seconds for monitoring.</p>
                <p><strong>Created:</strong> {{ created_time }}</p>
            </div>
        </div>
        
        <script>
            setTimeout(() => {
                location.reload();
            }, 60000);
            
            function updateTime() {
                const now = new Date();
                document.querySelectorAll('.server-time').forEach(el => {
                    el.textContent = now.toLocaleString();
                });
            }
            setInterval(updateTime, 1000);
        </script>
    </body>
    </html>
    """
    
    return render_template_string(
        html,
        uptime=int(time.time() - start_time),
        server_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        total_users=get_total_users(),
        active_sessions=len(user_sessions),
        banned_users=len(BANNED_USERS),
        created_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )

@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram webhook endpoint"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        
        bot.process_new_updates([update])
        
        return '', 200
    
    return 'Bad request', 400

# ========== DEFAULT HANDLER ==========
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Handle all other messages"""
    chat_id = message.chat.id
    
    if chat_id in user_sessions:
        state = user_sessions[chat_id].get('state')
        
        if state == STATE_WAITING_SOURCE:
            bot.reply_to(message, "📸 Please send the SOURCE photo to start the swap.")
        elif state == STATE_WAITING_TARGET:
            bot.reply_to(message, "📸 Please send the TARGET photo to complete the swap.")
        elif state == STATE_PROCESSING:
            bot.reply_to(message, "⏳ Your swap is being processed. Please wait...")
        else:
            bot.reply_to(message, "🔄 Please use /swap to start a new face swap.")
    else:
        help_text = """🤖 <b>Face Swap Bot v3.5</b>

I can help you swap faces between photos!

🎭 <b>Main Commands:</b>
/start - Start the bot
/swap - Start a new face swap
/mystats - View your statistics
/favorites - View saved swaps
/history - View swap history
/cancel - Cancel current swap
/report - Report content
/help - Show help

💡 <b>Tip:</b> Use clear, front-facing photos for best results!"""
        
        bot.reply_to(message, help_text, parse_mode='HTML')

# ========== MAIN FUNCTION ==========
def setup_webhook():
    """Setup webhook for Telegram bot"""
    try:
        bot.remove_webhook()
        time.sleep(1)
        
        webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
        bot.set_webhook(url=webhook_url)
        
        logger.info(f"Webhook set to: {webhook_url}")
        return True
    except Exception as e:
        logger.error(f"Failed to setup webhook: {e}")
        return False

def run_flask():
    """Run the Flask web server"""
    logger.info(f"Starting Flask server on port {BOT_PORT}...")
    
    app.run(
        host='0.0.0.0',
        port=BOT_PORT,
        debug=False,
        use_reloader=False,
        threaded=True
    )

def main():
    """Main application entry point"""
    global start_time
    start_time = time.time()
    
    print("=" * 80)
    print("🤖 FACE SWAP BOT v3.5 - PRODUCTION READY")
    print("=" * 80)
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"📢 Required Channel: {REQUIRED_CHANNEL}")
    print(f"🌐 Webhook URL: {WEBHOOK_URL}")
    print(f"🚀 Bot Port: {BOT_PORT}")
    print("=" * 80)
    print("✨ COMPLETE FEATURES:")
    print("• Face swapping with DeepSwapper API")
    print("• Admin notifications for new users")
    print("• Report system with admin review")
    print("• Complete admin panel with inline buttons")
    print("• Database backup/restore system")
    print("• Broadcast messaging to all users")
    print("• User statistics and history")
    print("• Multiple ping endpoints for 24/7 uptime")
    print("• Web dashboard with real-time stats")
    print("• Data cleanup tools")
    print("• FIXED: Swap statistics now properly stored!")
    print("=" * 80)
    print("🔧 STATISTICS FIXES APPLIED:")
    print("1. update_user_stats() - Properly increments counters")
    print("2. add_swap_history() - Always called with correct status")
    print("3. New /fixstats command to fix existing data")
    print("4. Verification between users and swaps_history tables")
    print("=" * 80)
    print("💾 BACKUP SYSTEM:")
    print("1. /createdbbackup - Create backup before updates")
    print("2. Save the ZIP file sent by bot")
    print("3. Update your code")
    print("4. /restoredb - Upload and restore data")
    print("=" * 80)
    
    init_database()
    
    try:
        bot_info = bot.get_me()
        print(f"✅ Bot connected: @{bot_info.username} (ID: {bot_info.id})")
    except Exception as e:
        print(f"❌ Bot connection error: {e}")
        return
    
    print(f"🌐 Setting up webhook...")
    if setup_webhook():
        print("✅ Webhook configured successfully")
        print(f"🚀 Starting web server on port {BOT_PORT}...")
        print("=" * 80)
        print("🔗 Available Endpoints:")
        print(f"• https://{WEBHOOK_URL.replace('https://', '')}/ - Dashboard")
        print(f"• https://{WEBHOOK_URL.replace('https://', '')}/ping - Ping")
        print(f"• https://{WEBHOOK_URL.replace('https://', '')}/stats - Statistics")
        print(f"• https://{WEBHOOK_URL.replace('https://', '')}/status - Status")
        print(f"• https://{WEBHOOK_URL.replace('https://', '')}/health/hunter - Health")
        print("=" * 80)
        run_flask()
    else:
        print("❌ Webhook setup failed!")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
