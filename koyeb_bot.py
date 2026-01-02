#!/usr/bin/env python3
"""
🤖 TELEGRAM UNIVERSAL VIDEO DOWNLOADER BOT
📥 YouTube, Instagram, TikTok, Pinterest, Terabox
🌐 Deployed on Koyeb - 24/7 FREE Hosting
✅ FIXED for Koyeb deployment
"""

import os
import sys
import logging
import re
import asyncio
import json
import time
import hashlib
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import io
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
import multiprocessing

# Telegram imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, CallbackContext, CallbackQueryHandler
)
from telegram.constants import ParseMode

# Third-party imports
import requests
from bs4 import BeautifulSoup
import yt_dlp
import aiohttp
from urllib.parse import urlparse, unquote

# ========== CONFIGURATION ==========
TOKEN = "7863008338:AAGoOdY4xpl0ATf0GRwQfCTg_Dt9ny5AM2c"
ADMIN_IDS = [7575087826]  # Your admin ID
BOT_USERNAME = ""
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB Telegram limit
RATE_LIMIT = 10  # Downloads per hour per user
PORT = int(os.environ.get("PORT", 8080))  # Koyeb uses PORT 8080

# ========== LOGGING SETUP ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# ========== HEALTH SERVER FOR KOYEB ==========
class HealthServer:
    """HTTP Server for health checks - REQUIRED for Koyeb"""
    
    def __init__(self, port=8080):
        self.port = port
        self.server = None
        self.thread = None
        
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/health' or self.path == '/ping' or self.path == '/ping1' or self.path == '/ping2' or self.path == '/':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = {
                    'status': 'online',
                    'service': 'telegram-downloader-bot',
                    'timestamp': datetime.now().isoformat(),
                    'endpoint': self.path,
                    'message': 'Bot is running on Koyeb'
                }
                self.wfile.write(json.dumps(response).encode())
            else:
                self.send_response(404)
                self.end_headers()
        
        def log_message(self, format, *args):
            logger.debug(f"HTTP {self.address_string()} - {format % args}")
    
    def start(self):
        """Start the health server in a separate thread"""
        def run():
            self.server = HTTPServer(('0.0.0.0', self.port), self.HealthHandler)
            logger.info(f"✅ Health server started on port {self.port}")
            logger.info(f"📡 Endpoints: /health, /ping, /ping1, /ping2")
            self.server.serve_forever()
        
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        return True

# Start health server immediately
health_server = HealthServer(port=PORT)
health_server.start()

# ========== DATABASE SETUP ==========
class Database:
    """SQLite database handler"""
    
    def __init__(self):
        self.db_file = "bot_database.db"
        self.setup_database()
    
    def setup_database(self):
        """Setup SQLite database with tables"""
        try:
            self.conn = sqlite3.connect(self.db_file, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            cursor = self.conn.cursor()
            
            # Users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    downloads INTEGER DEFAULT 0,
                    last_download TIMESTAMP,
                    is_banned INTEGER DEFAULT 0
                )
            ''')
            
            # Downloads table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    platform TEXT,
                    url TEXT,
                    file_size INTEGER,
                    download_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    success INTEGER DEFAULT 1
                )
            ''')
            
            self.conn.commit()
            logger.info("✅ Database setup complete")
            
        except Exception as e:
            logger.error(f"❌ Database setup failed: {e}")
            raise
    
    def add_user(self, user_id, username, first_name, last_name):
        """Add or update user in database"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO users 
                (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False
    
    def get_user_stats(self, user_id):
        """Get user download statistics"""
        try:
            cursor = self.conn.cursor()
            
            # Get hourly downloads
            cursor.execute('''
                SELECT COUNT(*) FROM downloads 
                WHERE user_id = ? 
                AND download_date > datetime('now', '-1 hour')
            ''', (user_id,))
            hourly = cursor.fetchone()[0]
            
            # Get daily downloads
            cursor.execute('''
                SELECT COUNT(*) FROM downloads 
                WHERE user_id = ? 
                AND date(download_date) = date('now')
            ''', (user_id,))
            daily = cursor.fetchone()[0]
            
            # Get total downloads
            cursor.execute('SELECT downloads FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            total = result[0] if result else 0
            
            return {
                'hourly': hourly,
                'daily': daily,
                'total': total,
                'remaining': max(0, RATE_LIMIT - hourly)
            }
            
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return {'hourly': 0, 'daily': 0, 'total': 0, 'remaining': RATE_LIMIT}
    
    def record_download(self, user_id, platform, url, file_size, success=True):
        """Record a download attempt"""
        try:
            cursor = self.conn.cursor()
            
            # Record download
            cursor.execute('''
                INSERT INTO downloads (user_id, platform, url, file_size, success)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, platform, url, file_size, 1 if success else 0))
            
            # Update user download count
            cursor.execute('''
                UPDATE users 
                SET downloads = downloads + 1, 
                    last_download = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (user_id,))
            
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error recording download: {e}")
            return False
    
    def get_all_users(self):
        """Get all users (for admin)"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT user_id, username, first_name, downloads, 
                       last_download, is_banned
                FROM users 
                ORDER BY join_date DESC
            ''')
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
    
    def ban_user(self, user_id):
        """Ban a user"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error banning user: {e}")
            return False
    
    def unban_user(self, user_id):
        """Unban a user"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error unbanning user: {e}")
            return False
    
    def is_user_banned(self, user_id):
        """Check if user is banned"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result[0] if result else False
        except Exception as e:
            logger.error(f"Error checking ban status: {e}")
            return False

# Initialize database
db = Database()

# ========== DOWNLOADER ENGINE ==========
class UniversalDownloader:
    """Universal downloader for all platforms"""
    
    PLATFORMS = {
        'youtube': {'domains': ['youtube.com', 'youtu.be'], 'icon': '📺'},
        'instagram': {'domains': ['instagram.com', 'instagr.am'], 'icon': '📸'},
        'tiktok': {'domains': ['tiktok.com', 'vm.tiktok.com'], 'icon': '🎵'},
        'pinterest': {'domains': ['pinterest.com', 'pin.it'], 'icon': '📌'},
        'terabox': {'domains': ['terabox.com', 'teraboxapp.com'], 'icon': '📦'},
        'twitter': {'domains': ['twitter.com', 'x.com'], 'icon': '🐦'},
        'facebook': {'domains': ['facebook.com', 'fb.watch'], 'icon': '📘'}
    }
    
    @staticmethod
    def detect_platform(url):
        """Detect which platform the URL belongs to"""
        url_lower = url.lower()
        for platform, data in UniversalDownloader.PLATFORMS.items():
            for domain in data['domains']:
                if domain in url_lower:
                    return platform, data['icon']
        return None, '📹'
    
    @staticmethod
    async def get_video_info(url, platform):
        """Get video information using yt-dlp"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'format': 'best[filesize<?50M]',
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                },
                'socket_timeout': 30
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return None
                
                # Get best format
                if 'formats' in info:
                    best_format = None
                    for fmt in info['formats']:
                        if fmt.get('filesize') and fmt['filesize'] <= MAX_FILE_SIZE:
                            if not best_format or fmt.get('filesize', 0) > best_format.get('filesize', 0):
                                best_format = fmt
                    
                    if best_format:
                        return {
                            'success': True,
                            'title': info.get('title', 'Video'),
                            'duration': info.get('duration', 0),
                            'thumbnail': info.get('thumbnail'),
                            'url': best_format.get('url'),
                            'filesize': best_format.get('filesize', 0),
                            'ext': best_format.get('ext', 'mp4')
                        }
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return None
    
    @staticmethod
    async def download_to_memory(video_url):
        """Download video directly to memory"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(video_url, timeout=60) as response:
                    if response.status == 200:
                        buffer = io.BytesIO()
                        total_size = 0
                        
                        async for chunk in response.content.iter_chunked(8192):
                            buffer.write(chunk)
                            total_size += len(chunk)
                            
                            if total_size > MAX_FILE_SIZE:
                                return None
                        
                        buffer.seek(0)
                        return buffer
                    
                    return None
                    
        except Exception as e:
            logger.error(f"Error downloading to memory: {e}")
            return None

# ========== BOT COMMAND HANDLERS ==========
async def start_command(update: Update, context: CallbackContext):
    """Handle /start command"""
    user = update.effective_user
    
    # Add user to database
    db.add_user(
        user.id,
        user.username,
        user.first_name,
        user.last_name
    )
    
    welcome_text = f"""
🌟 *Welcome {user.first_name}!* 🌟

🤖 *Universal Video Downloader Bot*

🚀 *Download videos from:*
📺 YouTube • 📸 Instagram • 🎵 TikTok
📌 Pinterest • 📦 Terabox • 🐦 Twitter • 📘 Facebook

📥 *How to use:*
1. Send me any video link
2. I'll process it instantly
3. Get your video in best quality!

⚡ *Features:*
• No storage - Videos never saved
• Best available quality
• Fast & reliable
• Free forever!

⚠️ *Important:*
• Max file size: *50MB*
• Rate limit: *{RATE_LIMIT} downloads/hour*
• Only public videos

📊 *Your Stats:*
• Downloads this hour: 0/{RATE_LIMIT}
• Total downloads: 0

🔧 *Commands:*
/start - Show this message
/help - Detailed guide
/stats - Your statistics
/rate - Rate our service

🌐 *Hosted on:* Koyeb Cloud
🆔 *Your ID:* `{user.id}`
"""
    
    keyboard = [
        [
            InlineKeyboardButton("📺 YouTube", callback_data="guide_yt"),
            InlineKeyboardButton("📸 Instagram", callback_data="guide_ig")
        ],
        [
            InlineKeyboardButton("🎵 TikTok", callback_data="guide_tt"),
            InlineKeyboardButton("📌 Pinterest", callback_data="guide_pin")
        ],
        [
            InlineKeyboardButton("📦 Terabox", callback_data="guide_tb"),
            InlineKeyboardButton("📊 My Stats", callback_data="my_stats")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )

async def help_command(update: Update, context: CallbackContext):
    """Handle /help command"""
    help_text = """
📖 *HELP GUIDE*

🤖 *What I can do:*
Download videos from multiple platforms.

🔗 *Supported Platforms:*
• YouTube (videos, shorts)
• Instagram (posts, reels)
• TikTok (videos)
• Pinterest (pins)
• Terabox (all videos)
• Twitter/X (video tweets)
• Facebook (public videos)

📥 *How to Download:*
1. Copy video link
2. Send it to me
3. Wait 10-30 seconds
4. Receive video in chat

🎯 *Quality:*
• Best quality under 50MB
• HD when possible

⚠️ *Limitations:*
• Max file size: *50MB*
• Rate limit: *{RATE_LIMIT}/hour*
• Only public videos

🔧 *Commands:*
/start - Welcome message
/help - This guide
/stats - Your statistics
/rate - Rate our service

📞 *Support:*
Contact admin if you need help.
"""
    
    await update.message.reply_text(
        help_text.format(RATE_LIMIT=RATE_LIMIT),
        parse_mode=ParseMode.MARKDOWN
    )

async def stats_command(update: Update, context: CallbackContext):
    """Handle /stats command"""
    user_id = update.effective_user.id
    stats = db.get_user_stats(user_id)
    
    stats_text = f"""
📊 *YOUR STATISTICS*

👤 User: {update.effective_user.first_name}
🆔 ID: `{user_id}`

📥 *Download Stats:*
• This Hour: *{stats['hourly']}/{RATE_LIMIT}*
• Today: *{stats['daily']} downloads*
• Total: *{stats['total']} downloads*
• Remaining: *{stats['remaining']} downloads*

💡 *Tip:* Send any video link to download!
"""
    
    await update.message.reply_text(
        stats_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def ping_command(update: Update, context: CallbackContext):
    """Handle /ping command - Health check"""
    await update.message.reply_text(
        "🏓 *PONG!*\n\n"
        "✅ Bot is online and healthy!\n"
        "🌐 Host: Koyeb Cloud\n"
        "🕒 Time: " + datetime.now().strftime('%H:%M:%S'),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_command(update: Update, context: CallbackContext):
    """Handle /admin command"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only command.")
        return
    
    admin_text = """
👑 *ADMIN PANEL*

Available commands:

👥 *User Management:*
• /users - List all users
• /ban <user_id> - Ban a user
• /unban <user_id> - Unban a user

📊 *Statistics:*
• /botstats - Bot statistics

📢 *Broadcast:*
• /broadcast <message> - Send to all users

🔧 *Maintenance:*
• /ping - Check bot status
"""
    
    await update.message.reply_text(
        admin_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_users_command(update: Update, context: CallbackContext):
    """Handle /users command"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only command.")
        return
    
    all_users = db.get_all_users()
    
    if not all_users:
        await update.message.reply_text("📭 No users found.")
        return
    
    users_text = f"👥 *ALL USERS* ({len(all_users)} total)\n\n"
    
    for user in all_users[:10]:  # Show first 10
        user_id, username, first_name, downloads, last_download, is_banned = user
        
        status = "🔴 BANNED" if is_banned else "🟢 ACTIVE"
        username_display = f"@{username}" if username else "No username"
        
        users_text += (
            f"• *{first_name}* {username_display}\n"
            f"  ID: `{user_id}` | {status}\n"
            f"  📥 {downloads} downloads\n\n"
        )
    
    await update.message.reply_text(
        users_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_broadcast_command(update: Update, context: CallbackContext):
    """Handle /broadcast command"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only command.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Usage: `/broadcast <message>`\nExample: `/broadcast Hello users!`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    message = " ".join(context.args)
    all_users = db.get_all_users()
    
    sent = 0
    failed = 0
    
    progress_msg = await update.message.reply_text(
        f"📢 Broadcasting to {len(all_users)} users..."
    )
    
    for user in all_users:
        try:
            await context.bot.send_message(
                chat_id=user[0],
                text=f"📢 *ANNOUNCEMENT*\n\n{message}\n\n_From bot admin_",
                parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
        except:
            failed += 1
    
    await progress_msg.edit_text(
        f"✅ Broadcast complete!\n\n"
        f"📊 Results:\n"
        f"• Successfully sent: {sent}\n"
        f"• Failed: {failed}"
    )

# ========== MESSAGE HANDLER ==========
async def handle_message(update: Update, context: CallbackContext):
    """Handle incoming messages with video links"""
    user_id = update.effective_user.id
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        await update.message.reply_text(
            "🚫 *Your account has been banned.*\n\n"
            "Contact admin if you believe this is a mistake.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    message_text = update.message.text
    
    # Check for URLs
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w\.\-?=&%#+]*'
    urls = re.findall(url_pattern, message_text)
    
    if not urls:
        await update.message.reply_text(
            "🔍 *No URL found.*\n\n"
            "Please send a video link from:\n"
            "YouTube, Instagram, TikTok, etc.\n\n"
            "Example: `https://youtube.com/watch?v=dQw4w9WgXcQ`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    url = urls[0].strip()
    
    # Detect platform
    platform, icon = UniversalDownloader.detect_platform(url)
    
    if not platform:
        await update.message.reply_text(
            "❌ *Platform not supported.*\n\n"
            "I support: YouTube, Instagram, TikTok, Pinterest, Terabox, Twitter, Facebook",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check rate limit
    stats = db.get_user_stats(user_id)
    if stats['hourly'] >= RATE_LIMIT:
        await update.message.reply_text(
            f"⏰ *Rate Limit Reached!*\n\n"
            f"You've used {stats['hourly']}/{RATE_LIMIT} downloads this hour.\n"
            f"Please wait 1 hour before downloading more.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Start processing
    processing_msg = await update.message.reply_text(
        f"{icon} *Processing {platform.upper()} link...*",
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        # Get video info
        video_info = await UniversalDownloader.get_video_info(url, platform)
        
        if not video_info:
            await processing_msg.edit_text(
                f"❌ *Failed to get video information*\n\n"
                f"Please try a different video.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Check file size
        if video_info['filesize'] > MAX_FILE_SIZE:
            size_mb = video_info['filesize'] / (1024 * 1024)
            await processing_msg.edit_text(
                f"❌ *File Too Large*\n\n"
                f"Video size: *{size_mb:.1f}MB*\n"
                f"Telegram limit: *50MB*",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Download to memory
        await processing_msg.edit_text(
            f"⬇️ *Downloading video...*",
            parse_mode=ParseMode.MARKDOWN
        )
        
        video_stream = await UniversalDownloader.download_to_memory(video_info['url'])
        
        if not video_stream:
            await processing_msg.edit_text(
                f"❌ *Download Failed*",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Upload to Telegram
        await processing_msg.edit_text(
            f"📤 *Uploading to Telegram...*",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Prepare caption
        file_size_mb = len(video_stream.getvalue()) / (1024 * 1024)
        
        caption = (
            f"✅ *DOWNLOAD COMPLETE!*\n\n"
            f"📁 *Title:* {video_info['title'][:100]}\n"
            f"📊 *Platform:* {platform.upper()}\n"
            f"💾 *Size:* {file_size_mb:.1f}MB\n\n"
            f"🤖 Downloaded via @{BOT_USERNAME}"
        )
        
        # Send video
        video_stream.seek(0)
        await update.message.reply_video(
            video=video_stream,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            supports_streaming=True
        )
        
        # Record download
        db.record_download(
            user_id,
            platform,
            url,
            len(video_stream.getvalue()),
            success=True
        )
        
        # Success message
        await processing_msg.edit_text(
            f"✅ *Success!* Video sent.\n\n"
            f"Downloads this hour: {stats['hourly'] + 1}/{RATE_LIMIT}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Clean up
        video_stream.close()
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await processing_msg.edit_text(
            f"❌ *Download Failed*\n\n"
            f"Please try again.",
            parse_mode=ParseMode.MARKDOWN
        )

# ========== BUTTON HANDLER ==========
async def button_callback(update: Update, context: CallbackContext):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("guide_"):
        platform = data.replace("guide_", "")
        platform_names = {
            'yt': ('YouTube', '📺'),
            'ig': ('Instagram', '📸'),
            'tt': ('TikTok', '🎵'),
            'pin': ('Pinterest', '📌'),
            'tb': ('Terabox', '📦')
        }
        
        if platform in platform_names:
            name, icon = platform_names[platform]
            await query.message.reply_text(
                f"{icon} *{name}*\n\n"
                f"Send me any {name} video link to download!",
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif data == "my_stats":
        await stats_command(update, context)

# ========== ERROR HANDLER ==========
async def error_handler(update: Update, context: CallbackContext):
    """Handle errors"""
    logger.error(f"Error: {context.error}")

# ========== MAIN FUNCTION ==========
async def main():
    """Main function to run the bot"""
    global BOT_USERNAME
    
    print("=" * 60)
    print("🤖 TELEGRAM UNIVERSAL DOWNLOADER BOT")
    print("🌐 Deployed on Koyeb")
    print("=" * 60)
    
    # Create Telegram application
    application = Application.builder().token(TOKEN).build()
    
    # Get bot username
    BOT_USERNAME = (await application.bot.get_me()).username
    print(f"✅ Bot username: @{BOT_USERNAME}")
    print(f"✅ Health server running on port {PORT}")
    print(f"✅ Endpoints: /health, /ping, /ping1, /ping2")
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("ping", ping_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("users", admin_users_command))
    application.add_handler(CommandHandler("broadcast", admin_broadcast_command))
    
    # Add message handler
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))
    
    # Add callback handler
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    print("🔄 Starting bot...")
    print("✅ Bot is running!")
    print("-" * 60)
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Keep running
    await asyncio.Event().wait()

# ========== START THE BOT ==========
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"\n💥 Error: {e}")
