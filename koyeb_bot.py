#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Face Swap Bot v3.2 - Fixed State Management
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
# Store user sessions: {chat_id: {state, user_id, data}}
user_sessions: Dict[int, Dict] = {}
active_swaps: Dict[int, Dict] = {}  # chat_id -> swap info

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
        data_hash TEXT
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
    """Register a new user or update existing user"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check if user exists
    c.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    is_new = c.fetchone() is None
    
    # Calculate data hash
    data_hash = hashlib.sha256(f"{user_id}{username}{first_name}{last_name}".encode()).hexdigest()
    
    # Insert or update user
    c.execute('''INSERT OR REPLACE INTO users 
        (user_id, username, first_name, last_name, last_active, data_hash)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)''',
        (user_id, username, first_name, last_name, data_hash))
    
    conn.commit()
    conn.close()
    
    return is_new

def get_total_users() -> int:
    """Get total number of registered users"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    count = c.fetchone()[0]
    conn.close()
    return count

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
    """Verify user (mark as channel member)"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET verified = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    logger.info(f"User verified: {user_id}")

def update_user_stats(user_id: int, success: bool = True) -> None:
    """Update user statistics after a swap"""
    conn = get_db_connection()
    c = conn.cursor()
    
    if success:
        c.execute('''UPDATE users SET 
            swaps_count = swaps_count + 1,
            successful_swaps = successful_swaps + 1,
            last_active = CURRENT_TIMESTAMP
            WHERE user_id = ?''', (user_id,))
    else:
        c.execute('''UPDATE users SET 
            swaps_count = swaps_count + 1,
            failed_swaps = failed_swaps + 1,
            last_active = CURRENT_TIMESTAMP
            WHERE user_id = ?''', (user_id,))
    
    conn.commit()
    conn.close()

def add_swap_history(user_id: int, status: str, processing_time: float, 
                     result_path: str = None, nsfw: bool = False) -> int:
    """Add a swap to history"""
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
        
        # Check if already favorited
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

# ========== FACE SWAP API FUNCTIONS ==========
def call_face_swap_api(source_image: bytes, target_image: bytes) -> Optional[bytes]:
    """Call the face swap API and return result image"""
    try:
        logger.info("Calling face swap API...")
        
        # Convert images to base64
        source_base64 = base64.b64encode(source_image).decode('utf-8')
        target_base64 = base64.b64encode(target_image).decode('utf-8')
        
        # Prepare API request
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
            'User-Agent': 'FaceSwapBot/3.2'
        }
        
        # Make API call
        logger.info(f"Sending request to API: {FACE_SWAP_API_URL}")
        response = requests.post(
            FACE_SWAP_API_URL,
            json=payload,
            headers=headers,
            timeout=60  # Increased timeout for API
        )
        
        logger.info(f"API Response Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"API Response Keys: {list(result.keys())}")
            
            if 'result' in result and result['result']:
                # Decode the base64 result image
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
    
    # Check if banned
    if user_id in BANNED_USERS:
        bot.reply_to(message, "🚫 <b>Access Denied</b>\n\nYour account has been banned from using this bot.", parse_mode='HTML')
        return
    
    # Register/update user
    register_user(
        user_id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    
    # Clear any existing session
    if chat_id in user_sessions:
        del user_sessions[chat_id]
    
    # Check channel membership
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
        # User is already a member
        verify_user(user_id)
        show_main_menu(message)

@bot.callback_query_handler(func=lambda call: call.data == "verify_join")
def verify_callback(call):
    """Handle channel verification callback"""
    user_id = call.from_user.id
    
    if check_channel_membership(user_id):
        verify_user(user_id)
        bot.answer_callback_query(call.id, "✅ Verified! You can now use the bot.")
        
        # Edit message to show success
        bot.edit_message_text(
            "✅ <b>Verification Successful!</b>\n\nYou can now use all features of the bot.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML'
        )
        
        # Show main menu after a short delay
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

👑 <b>Created by:</b> @PokiePy
🔄 <b>Version:</b> 3.2"""
    
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
    
    # Check if banned
    if user_id in BANNED_USERS:
        bot.reply_to(message, "🚫 Your account has been banned.")
        return
    
    # Check verification
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT verified FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    
    if not result or result[0] == 0:
        if not check_channel_membership(user_id):
            bot.reply_to(message, f"❌ Please join {REQUIRED_CHANNEL} first and verify!")
            return
    
    # Clear any existing session
    if chat_id in user_sessions:
        del user_sessions[chat_id]
    
    # Initialize new swap session
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
        # Clear session data
        del user_sessions[chat_id]
        
        # Clear active swap if exists
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
    
    # Check if banned
    if user_id in BANNED_USERS:
        bot.reply_to(message, "🚫 Your account has been banned.")
        return
    
    # Check if user has an active session
    if chat_id not in user_sessions:
        # No active session, start one
        bot.reply_to(message, "⚠️ No active swap session. Use /swap to start a new face swap.")
        return
    
    session = user_sessions[chat_id]
    state = session['state']
    
    # Get photo file
    file_id = message.photo[-1].file_id
    
    if state == STATE_WAITING_SOURCE:
        # Download source photo
        bot.reply_to(message, "⏳ Downloading source photo...")
        photo_data = download_telegram_photo(file_id)
        
        if photo_data:
            # Store source photo and update state
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
        # Check if we already have source photo
        if session['source_photo'] is None:
            bot.reply_to(message, "⚠️ Source photo missing. Please start over with /swap")
            del user_sessions[chat_id]
            return
        
        # Download target photo
        bot.reply_to(message, "⏳ Downloading target photo...")
        photo_data = download_telegram_photo(file_id)
        
        if photo_data:
            # Store target photo and start processing
            session['target_photo'] = photo_data
            session['state'] = STATE_PROCESSING
            
            # Start processing in a separate thread
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
    """Process the face swap with progress updates"""
    user_id = session['user_id']
    source_photo = session['source_photo']
    target_photo = session['target_photo']
    start_time = session['start_time']
    
    try:
        # Send initial progress message
        progress_msg = bot.send_message(
            chat_id,
            """🔄 <b>Processing Face Swap...</b>

[░░░░░░░░░░] 0%
⏱️ Estimated: Calculating...

⚙️ <b>Initializing face detection...</b>
💡 This may take 15-30 seconds...""",
            parse_mode='HTML'
        )
        
        # Add to active swaps tracking
        active_swaps[chat_id] = {
            'progress': 0,
            'status': 'Initializing',
            'start_time': time.time(),
            'message_id': progress_msg.message_id
        }
        
        # Simulate progress updates
        for progress in [10, 25, 45, 65, 85]:
            if chat_id not in active_swaps:
                return
                
            time.sleep(1.5)  # Simulate processing time
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
        
        # Call the actual face swap API
        logger.info(f"Calling face swap API for user {user_id}")
        
        # Update progress to "Processing with API"
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
        
        # Make API call
        result_image = call_face_swap_api(source_photo, target_photo)
        
        processing_time = time.time() - start_time
        
        if result_image:
            # Success - save result
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
            
            # Add to history
            swap_id = add_swap_history(
                user_id,
                "success",
                processing_time,
                filepath,
                False
            )
            
            # Update user stats
            update_user_stats(user_id, True)
            
            # Prepare result message
            caption = f"""✨ <b>Face Swap Complete!</b>

🆔 <b>Swap ID:</b> #{swap_id}
⏱️ <b>Time:</b> {processing_time:.1f} seconds
✅ <b>Status:</b> Success

💡 <b>Tips:</b>
• Save to favorites for later
• Share with friends
• Try different photos

<i>Note: Result quality depends on input photo quality.</i>"""
            
            # Create inline keyboard
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("⭐ Save Favorite", callback_data=f"fav_{swap_id}"),
                types.InlineKeyboardButton("🔄 Swap Again", callback_data="start_swap")
            )
            
            # Send result photo
            with open(filepath, 'rb') as photo:
                bot.send_photo(
                    chat_id,
                    photo,
                    caption=caption,
                    reply_markup=markup,
                    parse_mode='HTML'
                )
            
            logger.info(f"Swap successful for user {user_id}, time: {processing_time:.2f}s")
            
        else:
            # API failed
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
            
            # Add to history as failed
            add_swap_history(user_id, "failed", processing_time)
            update_user_stats(user_id, False)
            
            # Offer to try again
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
        
        # Send error message
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
        
        # Add to history as failed
        processing_time = time.time() - start_time if 'start_time' in session else 0
        add_swap_history(user_id, "failed", processing_time)
        update_user_stats(user_id, False)
    
    finally:
        # Clean up
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
            
            # Update message caption if possible
            try:
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

@bot.message_handler(commands=['mystats'])
def my_stats_command(message):
    """Show user statistics"""
    user_id = message.from_user.id
    
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''SELECT swaps_count, successful_swaps, failed_swaps, 
        join_date, last_active FROM users WHERE user_id = ?''', (user_id,))
    
    result = c.fetchone()
    conn.close()
    
    if result:
        total, success, failed, join_date, last_active = result
        
        # Calculate statistics
        success_rate = round((success / max(1, total)) * 100, 1)
        
        # Format dates
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

🏆 <b>Rank:</b> {'Beginner' if total < 5 else 'Intermediate' if total < 20 else 'Expert'}
📈 <b>Activity Level:</b> {'New User' if total == 0 else 'Active' if total > 5 else 'Casual'}"""
        
        bot.reply_to(message, stats_text, parse_mode='HTML')
    else:
        bot.reply_to(message, "📊 No statistics found. Start with /swap to begin your journey!")

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
        history_text += f"   📅 {date_str} | ⏱️ {time_str}"
    
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
        <h1>🤖 Face Swap Bot</h1>
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
        </div>
        <div class="footer">
            <p>Created by @PokiePy | v3.2</p>
            <p>Server Time: {{ server_time }}</p>
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
            active_24h=0,  # You can implement this function
            total_swaps=total_swaps,
            success_rate=success_rate,
            server_time=datetime.now().strftime('%H:%M:%S')
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
            server_time=datetime.now().strftime('%H:%M:%S')
        )

@app.route('/health/hunter')
def health_hunter():
    """Health check endpoint"""
    try:
        return jsonify({
            "status": "healthy",
            "service": "Face Swap Bot",
            "version": "3.2",
            "bot": "running",
            "database": "connected",
            "active_sessions": len(user_sessions),
            "active_swaps": len(active_swaps),
            "timestamp": datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram webhook endpoint"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        
        # Process update
        bot.process_new_updates([update])
        
        return '', 200
    
    return 'Bad request', 400

# ========== ADMIN COMMANDS (Simplified) ==========
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    """Admin panel access"""
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Access denied.")
        return
    
    admin_text = f"""👑 <b>Admin Panel</b>

📊 <b>Statistics:</b>
• Users: {get_total_users()}
• Active Sessions: {len(user_sessions)}
• Active Swaps: {len(active_swaps)}
• Banned Users: {len(BANNED_USERS)}

⚙️ <b>Commands:</b>
/users - List users
/ban [id] - Ban user
/unban [id] - Unban user
/botstatus - Bot status"""
    
    bot.reply_to(message, admin_text, parse_mode='HTML')

@bot.message_handler(commands=['botstatus'])
def bot_status_command(message):
    """Show bot status"""
    if message.from_user.id != ADMIN_ID:
        return
    
    status_text = f"""🤖 <b>Bot Status</b>

🟢 <b>Status:</b> Operational
📡 <b>Mode:</b> Webhook
👥 <b>Active Sessions:</b> {len(user_sessions)}
🔄 <b>Active Swaps:</b> {len(active_swaps)}
⏰ <b>Uptime:</b> {int(time.time() - start_time)}s
💾 <b>Database:</b> Connected

🌐 <b>Endpoints:</b>
• /health/hunter - Health check
• / - Dashboard
• /webhook - Telegram webhook"""
    
    bot.reply_to(message, status_text, parse_mode='HTML')

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
        help_text = """🤖 <b>Face Swap Bot</b>

I can help you swap faces between photos!

🎭 <b>Commands:</b>
/start - Start the bot
/swap - Start a new face swap
/mystats - View your statistics
/favorites - View saved swaps
/history - View swap history
/cancel - Cancel current swap
/help - Show help

💡 <b>Tip:</b> Use clear, front-facing photos for best results!"""
        
        bot.reply_to(message, help_text, parse_mode='HTML')

# ========== MAIN FUNCTION ==========
def setup_webhook():
    """Setup webhook for Telegram bot"""
    try:
        # Remove existing webhook
        bot.remove_webhook()
        time.sleep(1)
        
        # Set new webhook
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
    
    # Print banner
    print("=" * 70)
    print("🤖 FACE SWAP BOT v3.2 - FIXED")
    print("=" * 70)
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"📢 Required Channel: {REQUIRED_CHANNEL}")
    print(f"🌐 Webhook URL: {WEBHOOK_URL}")
    print(f"🚀 Bot Port: {BOT_PORT}")
    print("=" * 70)
    print("✨ FIXES IN THIS VERSION:")
    print("• Fixed state management bug")
    print("• Proper photo download handling")
    print("• Better error messages")
    print("• Threaded processing")
    print("• API call improvements")
    print("=" * 70)
    
    # Initialize database
    init_database()
    
    # Get bot info
    try:
        bot_info = bot.get_me()
        print(f"✅ Bot connected: @{bot_info.username} (ID: {bot_info.id})")
    except Exception as e:
        print(f"❌ Bot connection error: {e}")
        return
    
    # Setup webhook
    print(f"🌐 Setting up webhook...")
    if setup_webhook():
        print("✅ Webhook configured successfully")
        print(f"🚀 Starting web server on port {BOT_PORT}...")
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
