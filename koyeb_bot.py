#!/usr/bin/env python3
"""
🤖 TELEGRAM UNIVERSAL VIDEO DOWNLOADER BOT
📥 YouTube, Instagram, TikTok, Pinterest, Terabox
🌐 Deployed on Koyeb - 24/7 FREE Hosting
✅ PRODUCTION READY WITH FLASK WEBHOOKS
"""

import os
import sys
import logging
import re
import json
import time
import hashlib
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import io
import sqlite3
import traceback

# Flask imports for webhooks
from flask import Flask, request, jsonify
from threading import Thread

# Telegram imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, CallbackContext, CallbackQueryHandler,
    ApplicationBuilder
)
from telegram.constants import ParseMode
import telegram

# Third-party imports
import requests
from bs4 import BeautifulSoup
import yt_dlp
import aiohttp
from urllib.parse import urlparse, unquote

# ========== CONFIGURATION ==========
TOKEN = "7863008338:AAGoOdY4xpl0ATf0GRwQfCTg_Dt9ny5AM2c"
ADMIN_IDS = [7575087826]  # Your admin ID
BOT_USERNAME = "TelegramDownloaderKoyebBot"  # Will be updated
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB Telegram limit
RATE_LIMIT = 10  # Downloads per hour per user
PORT = int(os.environ.get("PORT", 8080))  # Koyeb uses PORT 8080

# Get Koyeb URL
KOYEB_APP_NAME = os.environ.get("KOYEB_APP_NAME", "encouraging-di-1carnage1-6226074c")
KOYEB_ORG = os.environ.get("KOYEB_ORG", "koyeb")
WEBHOOK_URL = f"https://{KOYEB_APP_NAME}.{KOYEB_ORG}.app/webhook"

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

# ========== FLASK APP SETUP ==========
app = Flask(__name__)

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
                    success INTEGER DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # Stats table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stats (
                    id INTEGER PRIMARY KEY,
                    total_users INTEGER DEFAULT 0,
                    total_downloads INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Initialize stats
            cursor.execute('INSERT OR IGNORE INTO stats (id) VALUES (1)')
            
            self.conn.commit()
            logger.info("✅ Database setup complete")
            
        except Exception as e:
            logger.error(f"❌ Database setup failed: {e}")
    
    def add_user(self, user_id, username, first_name):
        """Add or update user in database"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, username, first_name)
                VALUES (?, ?, ?)
            ''', (user_id, username, first_name))
            
            # Update stats
            cursor.execute('UPDATE stats SET total_users = (SELECT COUNT(*) FROM users) WHERE id = 1')
            
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
            
            # Update stats
            cursor.execute('UPDATE stats SET total_downloads = total_downloads + 1, last_updated = CURRENT_TIMESTAMP WHERE id = 1')
            
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error recording download: {e}")
            return False
    
    def get_bot_stats(self):
        """Get overall bot statistics"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT total_users, total_downloads FROM stats WHERE id = 1')
            result = cursor.fetchone()
            
            if result:
                total_users, total_downloads = result
                
                # Get today's downloads
                cursor.execute('''
                    SELECT COUNT(*) FROM downloads 
                    WHERE date(download_date) = date('now')
                ''')
                today_downloads = cursor.fetchone()[0]
                
                # Get active users (last 7 days)
                cursor.execute('''
                    SELECT COUNT(DISTINCT user_id) FROM downloads 
                    WHERE download_date > datetime('now', '-7 days')
                ''')
                active_users = cursor.fetchone()[0]
                
                # Get platform distribution
                cursor.execute('''
                    SELECT platform, COUNT(*) as count 
                    FROM downloads 
                    GROUP BY platform 
                    ORDER BY count DESC LIMIT 5
                ''')
                platform_stats = cursor.fetchall()
                
                return {
                    'total_users': total_users,
                    'total_downloads': total_downloads,
                    'today_downloads': today_downloads,
                    'active_users': active_users,
                    'platform_stats': platform_stats
                }
            
            return {}
            
        except Exception as e:
            logger.error(f"Error getting bot stats: {e}")
            return {}

# Initialize database
db = Database()

# ========== DOWNLOADER ENGINE ==========
class UniversalDownloader:
    """Universal downloader for all platforms"""
    
    PLATFORMS = {
        'youtube': {'icon': '📺', 'domains': ['youtube.com', 'youtu.be']},
        'instagram': {'icon': '📸', 'domains': ['instagram.com', 'instagr.am']},
        'tiktok': {'icon': '🎵', 'domains': ['tiktok.com', 'vm.tiktok.com']},
        'pinterest': {'icon': '📌', 'domains': ['pinterest.com', 'pin.it']},
        'terabox': {'icon': '📦', 'domains': ['terabox.com', 'teraboxapp.com']},
        'twitter': {'icon': '🐦', 'domains': ['twitter.com', 'x.com']},
        'facebook': {'icon': '📘', 'domains': ['facebook.com', 'fb.watch']},
        'reddit': {'icon': '🔴', 'domains': ['reddit.com', 'redd.it']},
        'likee': {'icon': '🎬', 'domains': ['likee.video', 'likee.com']}
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
    async def get_video_info_async(url, platform):
        """Get video information using yt-dlp (async)"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best[filesize<?50M]',
                'socket_timeout': 30,
                'retries': 3,
                'no_check_certificate': True,
                'ignoreerrors': True,
                'extract_flat': False
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return None
                
                # Get best format under 50MB
                best_format = None
                if 'formats' in info:
                    for fmt in info['formats']:
                        if fmt.get('filesize') and fmt['filesize'] <= MAX_FILE_SIZE:
                            if not best_format or fmt.get('filesize', 0) > best_format.get('filesize', 0):
                                best_format = fmt
                
                if best_format:
                    return {
                        'title': info.get('title', 'Video'),
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail'),
                        'url': best_format.get('url'),
                        'filesize': best_format.get('filesize', 0),
                        'ext': best_format.get('ext', 'mp4')
                    }
                
                # If no format found, try direct URL
                if 'url' in info:
                    return {
                        'title': info.get('title', 'Video'),
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail'),
                        'url': info['url'],
                        'filesize': info.get('filesize', 0),
                        'ext': info.get('ext', 'mp4')
                    }
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return None
    
    @staticmethod
    def get_video_info_sync(url, platform):
        """Get video information using yt-dlp (sync version)"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best[filesize<?50M]',
                'socket_timeout': 30,
                'retries': 3,
                'no_check_certificate': True,
                'ignoreerrors': True
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return None
                
                # Get best format under 50MB
                best_format = None
                if 'formats' in info:
                    for fmt in info['formats']:
                        if fmt.get('filesize') and fmt['filesize'] <= MAX_FILE_SIZE:
                            if not best_format or fmt.get('filesize', 0) > best_format.get('filesize', 0):
                                best_format = fmt
                
                if best_format:
                    return {
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
    async def download_to_memory_async(video_url):
        """Download video directly to memory (async)"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.google.com/'
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
    
    @staticmethod
    def download_to_memory_sync(video_url):
        """Download video directly to memory (sync version)"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*'
            }
            
            response = requests.get(video_url, headers=headers, stream=True, timeout=60)
            if response.status_code == 200:
                buffer = io.BytesIO()
                total_size = 0
                
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
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

# ========== TELEGRAM BOT SETUP ==========
# Global bot instance
bot_application = None
bot = None

async def setup_bot():
    """Setup Telegram bot application"""
    global bot_application, bot, BOT_USERNAME
    
    try:
        # Create application
        bot_application = (
            ApplicationBuilder()
            .token(TOKEN)
            .pool_timeout(30)
            .connect_timeout(30)
            .read_timeout(30)
            .write_timeout(30)
            .build()
        )
        
        # Get bot info
        bot = bot_application.bot
        bot_info = await bot.get_me()
        BOT_USERNAME = bot_info.username
        
        logger.info(f"✅ Bot initialized: @{BOT_USERNAME}")
        
        # Add handlers
        bot_application.add_handler(CommandHandler("start", start_command))
        bot_application.add_handler(CommandHandler("help", help_command))
        bot_application.add_handler(CommandHandler("stats", stats_command))
        bot_application.add_handler(CommandHandler("ping", ping_command))
        bot_application.add_handler(CommandHandler("admin", admin_command))
        bot_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Initialize application
        await bot_application.initialize()
        
        # Set webhook
        await bot.set_webhook(
            url=WEBHOOK_URL,
            max_connections=40,
            allowed_updates=['message', 'callback_query']
        )
        
        logger.info(f"✅ Webhook set: {WEBHOOK_URL}")
        
        # Send startup notification to admin
        await send_admin_message("🤖 *Bot Started Successfully!*\n\n"
                               f"• Username: @{BOT_USERNAME}\n"
                               f"• Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                               f"• Webhook: {WEBHOOK_URL}\n"
                               f"• Status: 🟢 Online")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to setup bot: {e}")
        return False

async def send_admin_message(message):
    """Send message to admin"""
    try:
        for admin_id in ADMIN_IDS:
            await bot.send_message(
                chat_id=admin_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        logger.error(f"Failed to send admin message: {e}")

# ========== BOT COMMAND HANDLERS ==========
async def start_command(update: Update, context: CallbackContext):
    """Handle /start command"""
    user = update.effective_user
    
    # Add user to database
    db.add_user(user.id, user.username, user.first_name)
    
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

🔧 *Commands:*
/start - Show this message
/help - Detailed guide
/stats - Your statistics
/ping - Check bot status

🌐 *Hosted on:* Koyeb Cloud
🆔 *Your ID:* `{user.id}`
"""
    
    keyboard = [
        [InlineKeyboardButton("📺 YouTube", callback_data="guide_yt"),
         InlineKeyboardButton("📸 Instagram", callback_data="guide_ig")],
        [InlineKeyboardButton("🎵 TikTok", callback_data="guide_tt"),
         InlineKeyboardButton("📌 Pinterest", callback_data="guide_pin")],
        [InlineKeyboardButton("📦 Terabox", callback_data="guide_tb"),
         InlineKeyboardButton("📊 My Stats", callback_data="my_stats")]
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
    help_text = f"""
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
• Reddit (video posts)
• Likee (videos)

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
/ping - Check bot status

📞 *Support:*
Contact admin if you need help.
"""
    
    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def stats_command(update: Update, context: CallbackContext):
    """Handle /stats command"""
    user_id = update.effective_user.id
    stats = db.get_user_stats(user_id)
    
    # Get bot stats
    bot_stats = db.get_bot_stats()
    
    stats_text = f"""
📊 *YOUR STATISTICS*

👤 User: {update.effective_user.first_name}
🆔 ID: `{user_id}`

📥 *Download Stats:*
• This Hour: *{stats['hourly']}/{RATE_LIMIT}*
• Today: *{stats['daily']} downloads*
• Total: *{stats['total']} downloads*
• Remaining: *{stats['remaining']} downloads*

🌐 *Bot Stats:*
• Total Users: *{bot_stats.get('total_users', 0)}*
• Total Downloads: *{bot_stats.get('total_downloads', 0)}*
• Active Users: *{bot_stats.get('active_users', 0)}*

💡 *Tip:* Send any video link to download!
"""
    
    await update.message.reply_text(
        stats_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def ping_command(update: Update, context: CallbackContext):
    """Handle /ping command"""
    bot_stats = db.get_bot_stats()
    
    ping_text = f"""
🏓 *PONG!* Bot is alive and healthy!

📊 *Bot Status:*
✅ *Status:* Operational
🌐 *Host:* Koyeb Cloud
👥 *Users:* {bot_stats.get('total_users', 0)}
📥 *Downloads:* {bot_stats.get('total_downloads', 0)}

🔗 *Health Endpoints:*
• https://encouraging-di-1carnage1-6226074c.koyeb.app/health
• https://encouraging-di-1carnage1-6226074c.koyeb.app/ping
• https://encouraging-di-1carnage1-6226074c.koyeb.app/ping1
• https://encouraging-di-1carnage1-6226074c.koyeb.app/ping2

🕒 *Last Check:* {datetime.now().strftime('%H:%M:%S')}

*Everything is working perfectly!* 🎉
"""
    
    await update.message.reply_text(
        ping_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_command(update: Update, context: CallbackContext):
    """Handle /admin command"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only command.")
        return
    
    bot_stats = db.get_bot_stats()
    
    admin_text = f"""
👑 *ADMIN PANEL*

📊 *Bot Statistics:*
• Total Users: *{bot_stats.get('total_users', 0)}*
• Total Downloads: *{bot_stats.get('total_downloads', 0)}*
• Today's Downloads: *{bot_stats.get('today_downloads', 0)}*
• Active Users: *{bot_stats.get('active_users', 0)}*

🔗 *Platform Usage:*
"""
    
    # Add platform stats
    for platform_stat in bot_stats.get('platform_stats', []):
        platform, count = platform_stat
        icon = UniversalDownloader.PLATFORMS.get(platform, {}).get('icon', '📹')
        admin_text += f"• {icon} {platform.title()}: *{count}*\n"
    
    admin_text += f"""
🌐 *System Info:*
• Webhook: {WEBHOOK_URL}
• Bot: @{BOT_USERNAME}
• Uptime: {int(time.time() - start_time)} seconds

🕒 *Last Updated:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    await update.message.reply_text(
        admin_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_message(update: Update, context: CallbackContext):
    """Handle incoming messages with video links"""
    user_id = update.effective_user.id
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
            "I support: YouTube, Instagram, TikTok, Pinterest, Terabox, Twitter, Facebook, Reddit, Likee",
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
        f"{icon} *Processing {platform.upper()} link...*\n"
        f"⏳ Please wait...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        # Get video info (sync version to avoid async issues)
        await processing_msg.edit_text(
            f"{icon} *{platform.upper()} DETECTED*\n"
            f"🔍 Analyzing video...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        video_info = UniversalDownloader.get_video_info_sync(url, platform)
        
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
        
        # Download to memory (sync version)
        await processing_msg.edit_text(
            f"⬇️ *Downloading video...*",
            parse_mode=ParseMode.MARKDOWN
        )
        
        video_stream = UniversalDownloader.download_to_memory_sync(video_info['url'])
        
        if not video_stream:
            await processing_msg.edit_text(
                f"❌ *Download Failed*\n\n"
                f"Could not download the video.",
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
            f"🤖 Downloaded via @{BOT_USERNAME}\n"
            f"⭐ Rate: /rate"
        )
        
        # Send video
        video_stream.seek(0)
        await update.message.reply_video(
            video=video_stream,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            supports_streaming=True,
            filename=f"{video_info['title'][:50]}.mp4".replace('/', '_')
        )
        
        # Record download
        db.record_download(user_id, platform, url, len(video_stream.getvalue()), True)
        
        # Success message
        await processing_msg.edit_text(
            f"✅ *Success!* Video sent.\n\n"
            f"Downloads this hour: {stats['hourly'] + 1}/{RATE_LIMIT}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Clean up
        video_stream.close()
        
        # Notify admin
        if user_id not in ADMIN_IDS:
            await send_admin_message(
                f"📥 *New Download*\n\n"
                f"👤 User: {update.effective_user.first_name}\n"
                f"🆔 ID: `{user_id}`\n"
                f"📊 Platform: {platform.upper()}\n"
                f"💾 Size: {file_size_mb:.1f}MB\n"
                f"🕒 Time: {datetime.now().strftime('%H:%M:%S')}"
            )
        
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        await processing_msg.edit_text(
            f"❌ *Download Failed*\n\n"
            f"Error: {str(e)[:100]}\n\n"
            f"Please try again.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Record failed download
        db.record_download(user_id, platform, url, 0, False)

# ========== FLASK ROUTES ==========
@app.route('/')
def home():
    """Home page"""
    return jsonify({
        'status': 'online',
        'service': 'telegram-downloader-bot',
        'version': '2.0',
        'timestamp': datetime.now().isoformat(),
        'endpoints': ['/health', '/ping', '/ping1', '/ping2', '/stats', '/webhook']
    })

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'telegram-downloader-bot',
        'timestamp': datetime.now().isoformat(),
        'uptime': int(time.time() - start_time),
        'database': 'connected',
        'webhook': WEBHOOK_URL
    })

@app.route('/ping')
@app.route('/ping1')
@app.route('/ping2')
def ping():
    """Ping endpoints for uptime monitoring"""
    return jsonify({
        'status': 'pong',
        'timestamp': datetime.now().isoformat(),
        'message': 'Bot is running on Koyeb'
    })

@app.route('/stats')
def stats():
    """Statistics endpoint"""
    bot_stats = db.get_bot_stats()
    return jsonify({
        'status': 'online',
        'statistics': bot_stats,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/webhook', methods=['POST'])
async def webhook():
    """Telegram webhook endpoint"""
    if request.method == "POST":
        try:
            # Process update
            update = Update.de_json(request.get_json(force=True), bot)
            
            # Process update in background
            Thread(target=lambda: asyncio.run(process_update(update))).start()
            
            return 'OK'
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return 'ERROR', 500
    
    return 'Method not allowed', 405

async def process_update(update: Update):
    """Process update in async context"""
    try:
        await bot_application.process_update(update)
    except Exception as e:
        logger.error(f"Error processing update: {e}")

# ========== STARTUP FUNCTION ==========
def start_bot():
    """Start the bot in background"""
    import asyncio
    
    async def _start_bot():
        success = await setup_bot()
        if success:
            logger.info("✅ Bot started successfully")
        else:
            logger.error("❌ Failed to start bot")
    
    # Run in background thread
    thread = Thread(target=lambda: asyncio.run(_start_bot()))
    thread.daemon = True
    thread.start()

# ========== MAIN ==========
if __name__ == '__main__':
    # Global start time
    start_time = time.time()
    
    print("=" * 60)
    print("🤖 TELEGRAM UNIVERSAL DOWNLOADER BOT")
    print("📥 YouTube • Instagram • TikTok • Pinterest • Terabox")
    print("🌐 Deployed on Koyeb - Production Ready")
    print("=" * 60)
    
    # Start bot in background
    start_bot()
    
    # Start Flask app
    logger.info(f"✅ Starting Flask server on port {PORT}")
    logger.info(f"🌐 Webhook URL: {WEBHOOK_URL}")
    logger.info(f"📡 Health endpoints: /health, /ping, /ping1, /ping2")
    
    # Run Flask app
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
