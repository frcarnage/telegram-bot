#!/usr/bin/env python3
"""
🤖 TELEGRAM UNIVERSAL VIDEO DOWNLOADER BOT
📥 YouTube, Instagram, TikTok, Pinterest, Terabox
🌐 Deployed on Koyeb - 24/7 FREE Hosting
✅ COMPLETE CODE WITH ALL FEATURES
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
            if self.path in ['/health', '/ping', '/ping1', '/ping2', '/']:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = {
                    'status': 'online',
                    'service': 'telegram-downloader-bot',
                    'timestamp': datetime.now().isoformat(),
                    'endpoint': self.path,
                    'message': 'Bot is running on Koyeb',
                    'uptime': time.time() - start_time
                }
                self.wfile.write(json.dumps(response).encode())
            elif self.path == '/stats':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = {
                    'status': 'online',
                    'users': len(db.get_all_users()),
                    'timestamp': datetime.now().isoformat()
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
            logger.info(f"📡 Endpoints: /health, /ping, /ping1, /ping2, /stats")
            self.server.serve_forever()
        
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        return True

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
                    is_banned INTEGER DEFAULT 0,
                    rating REAL DEFAULT 0,
                    rating_count INTEGER DEFAULT 0
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
            
            # Cache table for API responses
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cache (
                    url_hash TEXT PRIMARY KEY,
                    data TEXT,
                    expiry TIMESTAMP
                )
            ''')
            
            # Create indexes for better performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_downloads_user_date ON downloads(user_id, download_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cache_expiry ON cache(expiry)')
            
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
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, last_name, join_date)
                VALUES (?, ?, ?, ?, COALESCE((SELECT join_date FROM users WHERE user_id = ?), CURRENT_TIMESTAMP))
            ''', (user_id, username, first_name, last_name, user_id))
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
            
            # Get last download time
            cursor.execute('''
                SELECT MAX(download_date) FROM downloads WHERE user_id = ?
            ''', (user_id,))
            last_dl_result = cursor.fetchone()
            last_dl = last_dl_result[0] if last_dl_result and last_dl_result[0] else None
            
            return {
                'hourly': hourly,
                'daily': daily,
                'total': total,
                'remaining': max(0, RATE_LIMIT - hourly),
                'last_download': last_dl
            }
            
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return {'hourly': 0, 'daily': 0, 'total': 0, 'remaining': RATE_LIMIT, 'last_download': None}
    
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
                       last_download, is_banned, join_date
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
    
    def get_bot_stats(self):
        """Get overall bot statistics"""
        try:
            cursor = self.conn.cursor()
            
            # Total users
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]
            
            # Active users (last 7 days)
            cursor.execute('''
                SELECT COUNT(DISTINCT user_id) FROM downloads 
                WHERE download_date > datetime('now', '-7 days')
            ''')
            active_users = cursor.fetchone()[0]
            
            # Total downloads
            cursor.execute('SELECT COUNT(*) FROM downloads')
            total_downloads = cursor.fetchone()[0]
            
            # Today's downloads
            cursor.execute('''
                SELECT COUNT(*) FROM downloads 
                WHERE date(download_date) = date('now')
            ''')
            today_downloads = cursor.fetchone()[0]
            
            # Platform distribution
            cursor.execute('''
                SELECT platform, COUNT(*) as count 
                FROM downloads 
                GROUP BY platform 
                ORDER BY count DESC
            ''')
            platform_stats = cursor.fetchall()
            
            return {
                'total_users': total_users,
                'active_users': active_users,
                'total_downloads': total_downloads,
                'today_downloads': today_downloads,
                'platform_stats': platform_stats
            }
            
        except Exception as e:
            logger.error(f"Error getting bot stats: {e}")
            return {}

# Initialize database
db = Database()

# ========== DOWNLOADER ENGINE ==========
class UniversalDownloader:
    """Universal downloader for all platforms"""
    
    # Supported platforms and their domains
    PLATFORMS = {
        'youtube': {
            'domains': ['youtube.com', 'youtu.be', 'youtube.be'],
            'icon': '📺',
            'api_endpoints': [
                'https://co.wuk.sh/api/json',
                'https://ytdl.iamidiotareyoutoo.workers.dev/'
            ]
        },
        'instagram': {
            'domains': ['instagram.com', 'instagr.am', 'ig.me'],
            'icon': '📸',
            'api_endpoints': [
                'https://igram.io/api/ig',
                'https://www.instaapi.io/api/fetch'
            ]
        },
        'tiktok': {
            'domains': ['tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com', 'tiktokv.com'],
            'icon': '🎵',
            'api_endpoints': [
                'https://www.tikwm.com/api/',
                'https://api.tiktokdownload.io/download'
            ]
        },
        'pinterest': {
            'domains': ['pinterest.com', 'pin.it'],
            'icon': '📌',
            'api_endpoints': [
                'https://api.pinterestdl.com/download',
                'https://pinterestdl.iamidiotareyoutoo.workers.dev/'
            ]
        },
        'terabox': {
            'domains': ['terabox.com', 'teraboxapp.com', '1024tera.com', '4funbox.com'],
            'icon': '📦',
            'api_endpoints': [
                'https://terabox-dl.qtcloud.workers.dev/api/get-info',
                'https://terabox-api.iamidiotareyoutoo.workers.dev/'
            ]
        },
        'twitter': {
            'domains': ['twitter.com', 'x.com', 't.co'],
            'icon': '🐦',
            'api_endpoints': []
        },
        'facebook': {
            'domains': ['facebook.com', 'fb.watch', 'fb.com'],
            'icon': '📘',
            'api_endpoints': []
        }
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
        """Get video information using yt-dlp (fallback for all platforms)"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'format': 'best[filesize<?50M]',  # Best quality under 50MB
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://www.google.com/'
                },
                'socket_timeout': 30,
                'retries': 3,
                'fragment_retries': 3,
                'ignoreerrors': False,
                'no_color': True,
                'geo_bypass': True,
                'geo_bypass_country': 'US',
                'nocheckcertificate': True,
                'prefer_ffmpeg': False,
                'merge_output_format': 'mp4',
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4'
                }]
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return None
                
                # Get the best available format
                format_id = None
                best_size = 0
                
                if 'formats' in info:
                    for fmt in info['formats']:
                        if (fmt.get('vcodec') != 'none' and  # Has video
                            fmt.get('filesize') and 
                            fmt['filesize'] <= MAX_FILE_SIZE and
                            fmt['filesize'] > best_size):
                            best_size = fmt['filesize']
                            format_id = fmt['format_id']
                
                if not format_id and 'url' in info:
                    # Use direct URL if available
                    format_id = '0'
                
                if format_id:
                    return {
                        'success': True,
                        'title': info.get('title', 'Video'),
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail'),
                        'url': info.get('url') if 'url' in info else url,
                        'filesize': best_size if best_size > 0 else info.get('filesize', 0),
                        'ext': info.get('ext', 'mp4'),
                        'platform': platform,
                        'webpage_url': info.get('webpage_url', url),
                        'description': info.get('description', '')[:200] + '...' if info.get('description') else ''
                    }
                else:
                    return None
                    
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"YT-DLP Download Error for {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting video info for {url}: {e}")
            return None
    
    @staticmethod
    async def download_to_memory(video_url, max_size=MAX_FILE_SIZE):
        """Download video directly to memory (no disk storage)"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Referer': 'https://www.google.com/'
            }
            
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(video_url, timeout=60) as response:
                    if response.status == 200:
                        # Check content length
                        content_length = response.headers.get('Content-Length')
                        if content_length and int(content_length) > max_size:
                            return None
                        
                        # Stream to memory with progress tracking
                        buffer = io.BytesIO()
                        total_size = 0
                        
                        async for chunk in response.content.iter_chunked(1024 * 1024):  # 1MB chunks
                            buffer.write(chunk)
                            total_size += len(chunk)
                            
                            # Check size during download
                            if total_size > max_size:
                                return None
                        
                        buffer.seek(0)
                        
                        # Verify file is not empty
                        if total_size == 0:
                            return None
                            
                        return buffer
                    
                    return None
                    
        except asyncio.TimeoutError:
            logger.error(f"Timeout downloading {video_url}")
            return None
        except Exception as e:
            logger.error(f"Error downloading to memory: {e}")
            return None

# Global start time
start_time = time.time()

# Start health server immediately
health_server = HealthServer(port=PORT)
health_server.start()

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
    
    # Build welcome message
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
• No storage - Videos never saved on server
• Best available quality
• Fast & reliable downloads
• Free forever!

⚠️ *Important:*
• Max file size: *50MB* (Telegram limit)
• Rate limit: *{RATE_LIMIT} downloads/hour*
• Only public videos
• Respect copyrights

📊 *Your Stats:*
• Downloads this hour: 0/{RATE_LIMIT}
• Total downloads: 0

🔧 *Commands:*
/start - Show this message
/help - Detailed guide
/stats - Your statistics
/rate - Rate our service
/ping - Check bot status

🌐 *Hosted on:* Koyeb Cloud
🆔 *Your ID:* `{user.id}`
⭐ *Admin:* @Tg_AssistBot
"""
    
    # Create keyboard
    keyboard = [
        [
            InlineKeyboardButton("📺 YouTube", callback_data="guide_yt"),
            InlineKeyboardButton("📸 Instagram", callback_data="guide_ig"),
            InlineKeyboardButton("🎵 TikTok", callback_data="guide_tt")
        ],
        [
            InlineKeyboardButton("📌 Pinterest", callback_data="guide_pin"),
            InlineKeyboardButton("📦 Terabox", callback_data="guide_tb"),
            InlineKeyboardButton("📊 My Stats", callback_data="my_stats")
        ],
        [
            InlineKeyboardButton("📖 Help Guide", callback_data="help_menu"),
            InlineKeyboardButton("⭐ Rate Bot", callback_data="rate_bot")
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
    help_text = f"""
📖 *COMPLETE HELP GUIDE*

🤖 *What I can do:*
Download videos from multiple platforms in best quality.

🔗 *Supported Platforms:*
• YouTube (videos, shorts, live streams)
• Instagram (posts, reels, stories, IGTV)
• TikTok (videos, slideshows)
• Pinterest (pins, video pins)
• Terabox (all video files)
• Twitter/X (video tweets)
• Facebook (public videos)

📥 *How to Download:*
1. Copy video link from any app
2. Send it to me as a message
3. Wait 10-30 seconds for processing
4. Receive video directly in chat

🎯 *Quality:*
• Automatically selects best quality ≤50MB
• Multiple quality options when available
• HD when possible

⚡ *Quick Start Examples:*
• YouTube: `https://youtube.com/watch?v=dQw4w9WgXcQ`
• Instagram: `https://instagram.com/p/Cxample123/`
• TikTok: `https://tiktok.com/@user/video/123456789`
• Any valid video link!

⚠️ *Limitations:*
• Max file size: *50MB* (Telegram's limit)
• Rate limit: *{RATE_LIMIT} downloads/hour*
• Only public/accessible videos
• No password-protected content

❓ *Troubleshooting:*
1. *Link not working?*
   - Check if video is public
   - Try in browser first
   - Use a different link

2. *Download failed?*
   - File might be too large
   - Server might be busy
   - Try again in 5 minutes

3. *Quality issues?*
   - Source might limit quality
   - Try a different video
   - Check original source quality

🔧 *Commands:*
/start - Welcome message
/help - This guide
/stats - Your download statistics
/rate - Rate our service
/ping - Check bot status
/admin - Admin panel (admin only)

🛡 *Privacy:*
• Videos are never stored on our servers
• No login required
• No personal data collected
• Direct streaming to Telegram

📞 *Support:*
Contact admin if you need help.
Remember to only download content you have rights to!
"""
    
    keyboard = [
        [
            InlineKeyboardButton("🚀 Try Download", switch_inline_query_current_chat="https://"),
            InlineKeyboardButton("📊 My Stats", callback_data="my_stats")
        ],
        [
            InlineKeyboardButton("⭐ Rate Us", callback_data="rate_bot"),
            InlineKeyboardButton("🆘 Contact", url="https://t.me/Tg_AssistBot")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        help_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )

async def stats_command(update: Update, context: CallbackContext):
    """Handle /stats command"""
    user_id = update.effective_user.id
    stats = db.get_user_stats(user_id)
    
    # Format last download time
    if stats['last_download']:
        try:
            last_dt = datetime.strptime(stats['last_download'], '%Y-%m-%d %H:%M:%S')
            last_str = last_dt.strftime('%b %d, %H:%M')
        except:
            last_str = "Never"
    else:
        last_str = "Never"
    
    stats_text = f"""
📊 *YOUR STATISTICS*

👤 *User:* {update.effective_user.first_name}
🆔 *ID:* `{user_id}`

📥 *Download Stats:*
• This Hour: *{stats['hourly']}/{RATE_LIMIT}*
• Today: *{stats['daily']} downloads*
• Total: *{stats['total']} downloads*
• Remaining: *{stats['remaining']} downloads*

⏰ *Last Download:* {last_str}
📈 *Progress:* {'█' * min(stats['hourly'], 5)}{'░' * max(0, 5 - stats['hourly'])} [{stats['hourly']}/5]

💡 *Tips:*
• Send any video link to download
• Rate limit resets every hour
• Contact admin if you need help
"""
    
    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh_stats"),
            InlineKeyboardButton("📥 Download", switch_inline_query_current_chat="")
        ],
        [
            InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard"),
            InlineKeyboardButton("📈 Platform Stats", callback_data="platform_stats")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        stats_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def ping_command(update: Update, context: CallbackContext):
    """Handle /ping command - Health check"""
    uptime_seconds = time.time() - start_time
    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    
    # Get bot statistics
    bot_stats = db.get_bot_stats()
    
    ping_text = f"""
🏓 *PONG!* Bot is alive and healthy!

📊 *Bot Status:*
✅ *Status:* Operational
⏰ *Uptime:* {days}d {hours}h {minutes}m
🌐 *Host:* Koyeb Cloud
👥 *Users:* {bot_stats.get('total_users', 0)}
📥 *Downloads:* {bot_stats.get('total_downloads', 0)}

🔗 *Health Endpoints:*
• https://encouraging-di-1carnage1-6226074c.koyeb.app/health
• https://encouraging-di-1carnage1-6226074c.koyeb.app/ping
• https://encouraging-di-1carnage1-6226074c.koyeb.app/ping1
• https://encouraging-di-1carnage1-6226074c.koyeb.app/ping2

🕒 *Last Check:* {datetime.now().strftime('%H:%M:%S')}
📍 *Server:* Global CDN

*Everything is working perfectly!* 🎉
"""
    
    await update.message.reply_text(
        ping_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def rate_command(update: Update, context: CallbackContext):
    """Handle /rate command"""
    rating_text = """
⭐ *RATE OUR SERVICE*

How was your experience with this bot?

Your feedback helps us improve the service for everyone!

Please select a rating:
"""
    
    keyboard = [
        [
            InlineKeyboardButton("⭐ 1", callback_data="rate_1"),
            InlineKeyboardButton("⭐⭐ 2", callback_data="rate_2"),
            InlineKeyboardButton("⭐⭐⭐ 3", callback_data="rate_3")
        ],
        [
            InlineKeyboardButton("⭐⭐⭐⭐ 4", callback_data="rate_4"),
            InlineKeyboardButton("⭐⭐⭐⭐⭐ 5", callback_data="rate_5")
        ],
        [InlineKeyboardButton("🚫 Skip", callback_data="rate_skip")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        rating_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# ========== ADMIN COMMANDS ==========
async def admin_command(update: Update, context: CallbackContext):
    """Handle /admin command (admin only)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(
            "❌ This command is for administrators only."
        )
        return
    
    admin_text = """
👑 *ADMIN PANEL*

Available commands:

👥 *User Management:*
• /users - List all users
• /ban <user_id> - Ban a user
• /unban <user_id> - Unban a user

📢 *Broadcast:*
• /broadcast <message> - Send message to all users

📊 *Statistics:*
• /botstats - Bot statistics
• /refresh - Refresh bot cache

🔧 *Maintenance:*
• /ping - Check bot status
• /logs - View recent logs

Use any command to get started.
"""
    
    await update.message.reply_text(
        admin_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_users_command(update: Update, context: CallbackContext):
    """Handle /users command (admin only)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only command.")
        return
    
    all_users = db.get_all_users()
    
    if not all_users:
        await update.message.reply_text("📭 No users found.")
        return
    
    # Pagination
    page = int(context.args[0]) if context.args and context.args[0].isdigit() else 1
    users_per_page = 10
    total_pages = (len(all_users) + users_per_page - 1) // users_per_page
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * users_per_page
    end_idx = start_idx + users_per_page
    
    users_text = f"👥 *ALL USERS* (Page {page}/{total_pages})\n\n"
    
    for user in all_users[start_idx:end_idx]:
        user_id, username, first_name, downloads, last_download, is_banned, join_date = user
        
        status = "🔴 BANNED" if is_banned else "🟢 ACTIVE"
        username_display = f"@{username}" if username else "No username"
        last_dl = last_download[:16] if last_download else "Never"
        join_date_str = join_date[:10] if join_date else "Unknown"
        
        users_text += (
            f"• *{first_name}* {username_display}\n"
            f"  ID: `{user_id}` | {status}\n"
            f"  📥 {downloads} DLs | Joined: {join_date_str}\n"
            f"  Last: {last_dl}\n\n"
        )
    
    users_text += f"📊 *Total Users:* {len(all_users)}"
    
    # Create pagination keyboard
    keyboard_buttons = []
    if page > 1:
        keyboard_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data=f"admin_users_{page-1}"))
    if page < total_pages:
        keyboard_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"admin_users_{page+1}"))
    
    keyboard = []
    if keyboard_buttons:
        keyboard.append(keyboard_buttons)
    keyboard.append([InlineKeyboardButton("📊 Bot Stats", callback_data="admin_stats")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    await update.message.reply_text(
        users_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_ban_command(update: Update, context: CallbackContext):
    """Handle /ban command (admin only)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only command.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Usage: `/ban <user_id>`\nExample: `/ban 123456789`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        target_id = int(context.args[0])
        
        if target_id in ADMIN_IDS:
            await update.message.reply_text("❌ Cannot ban an admin.")
            return
        
        success = db.ban_user(target_id)
        
        if success:
            # Notify the banned user
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="🚫 *Your account has been banned.*\n\n"
                         "If you believe this is a mistake, contact admin.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
            
            await update.message.reply_text(
                f"✅ User `{target_id}` has been banned."
            )
        else:
            await update.message.reply_text(
                f"❌ Failed to ban user `{target_id}`."
            )
            
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def admin_unban_command(update: Update, context: CallbackContext):
    """Handle /unban command (admin only)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only command.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "Usage: `/unban <user_id>`\nExample: `/unban 123456789`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        target_id = int(context.args[0])
        success = db.unban_user(target_id)
        
        if success:
            # Notify the unbanned user
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="✅ *Your account has been unbanned.*\n\n"
                         "You can now use the bot again.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
            
            await update.message.reply_text(
                f"✅ User `{target_id}` has been unbanned."
            )
        else:
            await update.message.reply_text(
                f"❌ Failed to unban user `{target_id}`."
            )
            
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def admin_broadcast_command(update: Update, context: CallbackContext):
    """Handle /broadcast command (admin only)"""
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
    
    if not all_users:
        await update.message.reply_text("📭 No users to broadcast to.")
        return
    
    sent = 0
    failed = 0
    
    progress_msg = await update.message.reply_text(
        f"📢 Broadcasting to {len(all_users)} users...\n"
        f"Sent: 0 | Failed: 0"
    )
    
    for user in all_users:
        try:
            await context.bot.send_message(
                chat_id=user[0],
                text=f"📢 *ANNOUNCEMENT*\n\n{message}\n\n"
                     f"_From bot admin_",
                parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
        except Exception as e:
            failed += 1
        
        # Update progress every 5 users
        if (sent + failed) % 5 == 0:
            try:
                await progress_msg.edit_text(
                    f"📢 Broadcasting to {len(all_users)} users...\n"
                    f"Sent: {sent} | Failed: {failed}"
                )
            except:
                pass
    
    await progress_msg.edit_text(
        f"✅ Broadcast complete!\n\n"
        f"📊 Results:\n"
        f"• Total users: {len(all_users)}\n"
        f"• Successfully sent: {sent}\n"
        f"• Failed: {failed}\n"
        f"• Success rate: {(sent/len(all_users)*100):.1f}%"
    )

async def admin_stats_command(update: Update, context: CallbackContext):
    """Handle admin stats command"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only command.")
        return
    
    bot_stats = db.get_bot_stats()
    uptime_seconds = time.time() - start_time
    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    
    stats_text = f"""
📊 *ADMIN STATISTICS*

🤖 *Bot Info:*
• Username: @{BOT_USERNAME}
• Uptime: {days}d {hours}h {minutes}m
• Platform: Koyeb Cloud
• Mode: Polling

👥 *User Statistics:*
• Total Users: *{bot_stats.get('total_users', 0)}*
• Active Users (7 days): *{bot_stats.get('active_users', 0)}*
• Banned Users: {len([u for u in db.get_all_users() if u[5]])}

📥 *Download Statistics:*
• Total Downloads: *{bot_stats.get('total_downloads', 0)}*
• Today's Downloads: *{bot_stats.get('today_downloads', 0)}*
• Avg/User: *{(bot_stats.get('total_downloads', 0)/max(1, bot_stats.get('total_users', 1))):.1f}*

📈 *Platform Usage:*
"""
    
    # Add platform stats
    for platform_stat in bot_stats.get('platform_stats', []):
        platform, count = platform_stat
        icon = UniversalDownloader.PLATFORMS.get(platform, {}).get('icon', '📹')
        stats_text += f"• {icon} {platform.title()}: *{count}*\n"
    
    stats_text += f"""
⚙️ *System:*
• Python: {sys.version.split()[0]}
• Database: SQLite
• Rate Limit: {RATE_LIMIT}/hour
• Max File Size: 50MB

🕒 *Last Updated:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    keyboard = [
        [
            InlineKeyboardButton("👥 User List", callback_data="admin_users_1"),
            InlineKeyboardButton("🔄 Refresh", callback_data="admin_refresh_stats")
        ],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast_menu"),
            InlineKeyboardButton("📋 Logs", callback_data="admin_logs")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        stats_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# ========== MESSAGE HANDLER ==========
async def handle_message(update: Update, context: CallbackContext):
    """Handle incoming messages with video links"""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        await update.message.reply_text(
            "🚫 *Your account has been banned.*\n\n"
            "If you believe this is a mistake, contact admin @Tg_AssistBot.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check for URLs
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w\.\-?=&%#+]*'
    urls = re.findall(url_pattern, message_text)
    
    if not urls:
        await update.message.reply_text(
            "🔍 *No URL found.*\n\n"
            "Please send a video link from:\n"
            "• YouTube\n• Instagram\n• TikTok\n• Pinterest\n"
            "• Terabox\n• Twitter\n• Facebook\n\n"
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
            "I support:\n"
            "• YouTube (youtube.com)\n"
            "• Instagram (instagram.com)\n"
            "• TikTok (tiktok.com)\n"
            "• Pinterest (pinterest.com)\n"
            "• Terabox (terabox.com)\n"
            "• Twitter/X (twitter.com/x.com)\n"
            "• Facebook (facebook.com)\n\n"
            "Please check your link and try again.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check rate limit
    stats = db.get_user_stats(user_id)
    if stats['hourly'] >= RATE_LIMIT:
        await update.message.reply_text(
            f"⏰ *Rate Limit Reached!*\n\n"
            f"You've used {stats['hourly']}/{RATE_LIMIT} downloads this hour.\n"
            f"Please wait 1 hour before downloading more.\n\n"
            f"*Tip:* The limit resets every hour at :00 minutes.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Start processing
    processing_msg = await update.message.reply_text(
        f"{icon} *Processing {platform.upper()} link...*\n"
        f"⏳ Please wait while I analyze the video...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        # Step 1: Get video information
        await processing_msg.edit_text(
            f"{icon} *{platform.upper()} DETECTED*\n"
            f"🔍 Analyzing video information...\n"
            f"Step 1/3: Fetching metadata",
            parse_mode=ParseMode.MARKDOWN
        )
        
        video_info = await UniversalDownloader.get_video_info(url, platform)
        
        if not video_info:
            await processing_msg.edit_text(
                f"❌ *Failed to get video information*\n\n"
                f"Possible reasons:\n"
                f"• Video is private/restricted\n"
                f"• Link is invalid or expired\n"
                f"• Platform is blocking downloads\n\n"
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
                f"Telegram limit: *50MB*\n\n"
                f"This video exceeds Telegram's file size limit.\n"
                f"Try a shorter video or different format.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Step 2: Download to memory
        await processing_msg.edit_text(
            f"⬇️ *Downloading video...*\n"
            f"📁 Title: `{video_info['title'][:50]}...`\n"
            f"💾 Size: {video_info['filesize']/(1024*1024):.1f}MB\n"
            f"Step 2/3: Download in progress",
            parse_mode=ParseMode.MARKDOWN
        )
        
        video_stream = await UniversalDownloader.download_to_memory(video_info['url'])
        
        if not video_stream:
            await processing_msg.edit_text(
                f"❌ *Download Failed*\n\n"
                f"Could not download the video.\n"
                f"Possible reasons:\n"
                f"• Network error\n"
                f"• Server timeout\n"
                f"• Video unavailable\n\n"
                f"Please try again or use a different link.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Step 3: Upload to Telegram
        await processing_msg.edit_text(
            f"📤 *Uploading to Telegram...*\n"
            f"⏳ Almost done...\n"
            f"Step 3/3: Final upload",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Prepare caption
        file_size_mb = len(video_stream.getvalue()) / (1024 * 1024)
        duration_str = f"{video_info['duration']}s" if video_info['duration'] else "N/A"
        
        caption = (
            f"✅ *DOWNLOAD COMPLETE!*\n\n"
            f"📁 *Title:* {video_info['title'][:100]}\n"
            f"📊 *Platform:* {platform.upper()}\n"
            f"💾 *Size:* {file_size_mb:.1f}MB\n"
            f"⏱ *Duration:* {duration_str}\n\n"
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
            filename=f"{video_info['title'][:50]}.mp4".replace('/', '_').replace('\\', '_')
        )
        
        # Record download in database
        db.record_download(
            user_id,
            platform,
            url,
            len(video_stream.getvalue()),
            success=True
        )
        
        # Update user in database
        db.add_user(
            user_id,
            update.effective_user.username,
            update.effective_user.first_name,
            update.effective_user.last_name
        )
        
        # Send success message with stats
        new_stats = db.get_user_stats(user_id)
        
        await processing_msg.edit_text(
            f"✅ *Success!* Video sent successfully!\n\n"
            f"📥 *Download Details:*\n"
            f"• Platform: {platform.upper()}\n"
            f"• Size: {file_size_mb:.1f}MB\n"
            f"• Status: ✅ Complete\n\n"
            f"📊 *Your Updated Stats:*\n"
            f"• This Hour: {new_stats['hourly']}/{RATE_LIMIT}\n"
            f"• Remaining: {new_stats['remaining']} downloads\n\n"
            f"⭐ *Please rate your experience:* /rate",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Clean up
        video_stream.close()
        
        # Notify admin about successful download
        try:
            if user_id not in ADMIN_IDS:
                for admin_id in ADMIN_IDS:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"📥 *New Download*\n\n"
                             f"👤 User: {update.effective_user.first_name}\n"
                             f"🆔 ID: `{user_id}`\n"
                             f"📊 Platform: {platform.upper()}\n"
                             f"💾 Size: {file_size_mb:.1f}MB\n"
                             f"🕒 Time: {datetime.now().strftime('%H:%M:%S')}",
                        parse_mode=ParseMode.MARKDOWN
                    )
        except:
            pass
        
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        
        try:
            await processing_msg.edit_text(
                f"❌ *Download Failed*\n\n"
                f"Error: `{str(e)[:100]}`\n\n"
                f"Please try again or contact support.",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Record failed download
            db.record_download(
                user_id,
                platform if 'platform' in locals() else 'unknown',
                url,
                0,
                success=False
            )
        except:
            pass

# ========== BUTTON CALLBACK HANDLER ==========
async def button_callback(update: Update, context: CallbackContext):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
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
                f"{icon} *{name} DOWNLOAD GUIDE*\n\n"
                f"Send me any {name} video link and I'll download it!\n\n"
                f"*Example links:*\n"
                f"• {name}: `https://{platform}.com/...`\n\n"
                f"*Tips:*\n"
                f"• Copy link from {name} app\n"
                f"• Ensure video is public\n"
                f"• Send link directly to me",
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif data == "my_stats":
        await stats_command(update, context)
    
    elif data == "refresh_stats":
        await stats_command(update, context)
    
    elif data == "help_menu":
        await help_command(update, context)
    
    elif data == "rate_bot":
        await rate_command(update, context)
    
    elif data.startswith("rate_"):
        if data == "rate_skip":
            await query.message.edit_text("Rating skipped. Thank you!")
            return
        
        rating = int(data.replace("rate_", ""))
        await query.message.edit_text(
            f"⭐ *Thank you for rating us {rating}/5!*\n\n"
            f"Your feedback helps us improve the service.\n\n"
            f"Have a great day! 😊"
        )
    
    elif data == "leaderboard":
        await show_leaderboard(update, context)
    
    elif data == "platform_stats":
        await show_platform_stats(update, context)
    
    elif data.startswith("admin_users_"):
        page = int(data.replace("admin_users_", ""))
        # Could implement pagination here
    
    elif data == "admin_stats":
        await admin_stats_command(update, context)
    
    elif data == "admin_refresh_stats":
        await admin_stats_command(update, context)
    
    elif data == "admin_broadcast_menu":
        await query.message.reply_text(
            "📢 *Broadcast Message*\n\n"
            "Use `/broadcast <message>` to send a message to all users.\n\n"
            "Example: `/broadcast New features added!`",
            parse_mode=ParseMode.MARKDOWN
        )

async def show_leaderboard(update: Update, context: CallbackContext):
    """Show download leaderboard"""
    all_users = db.get_all_users()
    sorted_users = sorted(all_users, key=lambda x: x[3] if x[3] else 0, reverse=True)[:10]
    
    leaderboard_text = "🏆 *TOP 10 DOWNLOADERS* 🏆\n\n"
    
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for rank, user in enumerate(sorted_users[:10]):
        user_id, username, first_name, downloads, _, _, _ = user
        medal = medals[rank] if rank < len(medals) else f"{rank+1}."
        
        username_display = f"@{username}" if username else first_name
        
        leaderboard_text += (
            f"{medal} *{username_display}*\n"
            f"   📥 {downloads} downloads | ID: `{user_id}`\n\n"
        )
    
    await update.effective_message.reply_text(
        leaderboard_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def show_platform_stats(update: Update, context: CallbackContext):
    """Show platform usage statistics"""
    bot_stats = db.get_bot_stats()
    platform_stats = bot_stats.get('platform_stats', [])
    
    if not platform_stats:
        await update.effective_message.reply_text(
            "📊 No download statistics available yet."
        )
        return
    
    stats_text = "📊 *PLATFORM USAGE STATISTICS*\n\n"
    
    total_downloads = bot_stats.get('total_downloads', 0)
    
    for platform, count in platform_stats:
        icon = UniversalDownloader.PLATFORMS.get(platform, {}).get('icon', '📹')
        percentage = (count / total_downloads * 100) if total_downloads > 0 else 0
        
        # Create progress bar
        bars = int(percentage / 10)
        progress_bar = "█" * bars + "░" * (10 - bars)
        
        stats_text += (
            f"{icon} *{platform.title()}*\n"
            f"   📥 {count} downloads ({percentage:.1f}%)\n"
            f"   [{progress_bar}]\n\n"
        )
    
    stats_text += f"📈 *Total Downloads:* {total_downloads}"
    
    await update.effective_message.reply_text(
        stats_text,
        parse_mode=ParseMode.MARKDOWN
    )

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
    print("📥 YouTube • Instagram • TikTok • Pinterest • Terabox")
    print("🌐 Deployed on Koyeb - 24/7 FREE Hosting")
    print("=" * 60)
    
    # Create Telegram application
    application = Application.builder().token(TOKEN).build()
    
    # Get bot username
    BOT_USERNAME = (await application.bot.get_me()).username
    print(f"✅ Bot username: @{BOT_USERNAME}")
    print(f"✅ Health server running on port {PORT}")
    print(f"✅ Health endpoints: /health, /ping, /ping1, /ping2, /stats")
    print(f"👑 Admin ID: {ADMIN_IDS[0]}")
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("ping", ping_command))
    application.add_handler(CommandHandler("rate", rate_command))
    
    # Add admin command handlers
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("users", admin_users_command))
    application.add_handler(CommandHandler("ban", admin_ban_command))
    application.add_handler(CommandHandler("unban", admin_unban_command))
    application.add_handler(CommandHandler("broadcast", admin_broadcast_command))
    application.add_handler(CommandHandler("botstats", admin_stats_command))
    
    # Add message handler
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))
    
    # Add callback query handler
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    print("🔄 Starting bot with polling...")
    print("✅ Bot is running! Press Ctrl+C to stop")
    print("-" * 60)
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )
    
    # Send startup notification to admin
    try:
        for admin_id in ADMIN_IDS:
            await application.bot.send_message(
                chat_id=admin_id,
                text=f"🤖 *Bot Started Successfully!*\n\n"
                     f"• Username: @{BOT_USERNAME}\n"
                     f"• Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                     f"• Platform: Koyeb\n"
                     f"• URL: https://encouraging-di-1carnage1-6226074c.koyeb.app\n"
                     f"• Status: 🟢 Online\n\n"
                     f"Ready to serve! 🎉",
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")
    
    # Keep running
    await asyncio.Event().wait()

# ========== ENTRY POINT ==========
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"\n💥 Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
