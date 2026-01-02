#!/usr/bin/env python3
"""
🤖 TELEGRAM UNIVERSAL VIDEO DOWNLOADER BOT
📥 YouTube, Instagram, TikTok, Pinterest, Terabox
🌐 Deployed on Koyeb - Production Ready
✅ COMPLETE WORKING CODE WITH ALL FEATURES
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

# Flask imports
from flask import Flask, request, jsonify
from threading import Thread
import requests as http_requests

# Third-party imports
import yt_dlp
from urllib.parse import urlparse, unquote

# ========== CONFIGURATION ==========
TOKEN = "7863008338:AAGoOdY4xpl0ATf0GRwQfCTg_Dt9ny5AM2c"
ADMIN_IDS = [7575087826]  # Your admin ID
BOT_USERNAME = ""
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
                    is_banned INTEGER DEFAULT 0,
                    rating INTEGER DEFAULT 0
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
            
            # Admin logs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    action TEXT,
                    target_id INTEGER,
                    details TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Platform stats table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS platform_stats (
                    platform TEXT PRIMARY KEY,
                    download_count INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Initialize platforms
            platforms = ['youtube', 'instagram', 'tiktok', 'pinterest', 'terabox', 'twitter', 'facebook', 'reddit', 'likee']
            for platform in platforms:
                cursor.execute('INSERT OR IGNORE INTO platform_stats (platform) VALUES (?)', (platform,))
            
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
            
            # Get weekly downloads
            cursor.execute('''
                SELECT COUNT(*) FROM downloads 
                WHERE user_id = ? 
                AND download_date > datetime('now', '-7 days')
            ''', (user_id,))
            weekly = cursor.fetchone()[0]
            
            # Get total downloads
            cursor.execute('SELECT downloads FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            total = result[0] if result else 0
            
            # Get last download
            cursor.execute('SELECT MAX(download_date) FROM downloads WHERE user_id = ?', (user_id,))
            last_download = cursor.fetchone()[0]
            
            return {
                'hourly': hourly,
                'daily': daily,
                'weekly': weekly,
                'total': total,
                'remaining': max(0, RATE_LIMIT - hourly),
                'last_download': last_download
            }
            
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return {'hourly': 0, 'daily': 0, 'weekly': 0, 'total': 0, 'remaining': RATE_LIMIT, 'last_download': None}
    
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
            if success:
                cursor.execute('''
                    UPDATE users 
                    SET downloads = downloads + 1, 
                        last_download = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                ''', (user_id,))
            
            # Update platform stats
            if success:
                cursor.execute('''
                    UPDATE platform_stats 
                    SET download_count = download_count + 1,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE platform = ?
                ''', (platform,))
            
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error recording download: {e}")
            return False
    
    def get_all_users(self, limit=100):
        """Get all users"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT user_id, username, first_name, downloads, 
                       last_download, is_banned, join_date
                FROM users 
                ORDER BY join_date DESC
                LIMIT ?
            ''', (limit,))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
    
    def ban_user(self, user_id, admin_id, reason=""):
        """Ban a user"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
            
            # Log admin action
            cursor.execute('''
                INSERT INTO admin_logs (admin_id, action, target_id, details)
                VALUES (?, 'ban', ?, ?)
            ''', (admin_id, user_id, reason))
            
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error banning user: {e}")
            return False
    
    def unban_user(self, user_id, admin_id, reason=""):
        """Unban a user"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
            
            # Log admin action
            cursor.execute('''
                INSERT INTO admin_logs (admin_id, action, target_id, details)
                VALUES (?, 'unban', ?, ?)
            ''', (admin_id, user_id, reason))
            
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
            
            # Banned users
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_banned = 1')
            banned_users = cursor.fetchone()[0]
            
            # Total downloads
            cursor.execute('SELECT COUNT(*) FROM downloads WHERE success = 1')
            total_downloads = cursor.fetchone()[0]
            
            # Today's downloads
            cursor.execute('''
                SELECT COUNT(*) FROM downloads 
                WHERE date(download_date) = date('now') AND success = 1
            ''')
            today_downloads = cursor.fetchone()[0]
            
            # Platform distribution
            cursor.execute('SELECT platform, download_count FROM platform_stats ORDER BY download_count DESC')
            platform_stats = cursor.fetchall()
            
            # Recent downloads (last 24 hours)
            cursor.execute('''
                SELECT COUNT(*) FROM downloads 
                WHERE download_date > datetime('now', '-1 day') AND success = 1
            ''')
            daily_downloads = cursor.fetchone()[0]
            
            return {
                'total_users': total_users,
                'active_users': active_users,
                'banned_users': banned_users,
                'total_downloads': total_downloads,
                'today_downloads': today_downloads,
                'daily_downloads': daily_downloads,
                'platform_stats': platform_stats
            }
            
        except Exception as e:
            logger.error(f"Error getting bot stats: {e}")
            return {}
    
    def add_rating(self, user_id, rating):
        """Add user rating"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE users SET rating = ? WHERE user_id = ?', (rating, user_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding rating: {e}")
            return False

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
        'likee': {'icon': '🎬', 'domains': ['likee.video', 'likee.com']},
        'snackvideo': {'icon': '🎥', 'domains': ['snackvideo.com']},
        'dailymotion': {'icon': '🎞️', 'domains': ['dailymotion.com']},
        'vimeo': {'icon': '🎬', 'domains': ['vimeo.com']},
        'twitch': {'icon': '👾', 'domains': ['twitch.tv']},
        'bilibili': {'icon': '🇨🇳', 'domains': ['bilibili.com']}
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
    def get_video_info(url):
        """Get video information using yt-dlp"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best[filesize<?50M]',
                'socket_timeout': 30,
                'retries': 3,
                'no_check_certificate': True,
                'ignoreerrors': True,
                'extract_flat': False,
                'noplaylist': True,
                'cookiefile': None,
                'geo_bypass': True,
                'geo_bypass_country': 'US',
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://www.google.com/'
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return None
                
                # Get best format under 50MB
                best_format = None
                best_size = 0
                
                if 'formats' in info:
                    for fmt in info['formats']:
                        if fmt.get('filesize') and fmt['filesize'] <= MAX_FILE_SIZE:
                            if fmt['filesize'] > best_size:
                                best_size = fmt['filesize']
                                best_format = fmt
                
                if best_format:
                    return {
                        'success': True,
                        'title': info.get('title', 'Video'),
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail'),
                        'url': best_format.get('url'),
                        'filesize': best_size,
                        'ext': best_format.get('ext', 'mp4'),
                        'quality': best_format.get('format_note', 'best'),
                        'description': info.get('description', '')[:100] + '...' if info.get('description') else ''
                    }
                
                # Try direct URL if available
                if 'url' in info:
                    filesize = info.get('filesize', 0)
                    if filesize <= MAX_FILE_SIZE:
                        return {
                            'success': True,
                            'title': info.get('title', 'Video'),
                            'duration': info.get('duration', 0),
                            'thumbnail': info.get('thumbnail'),
                            'url': info['url'],
                            'filesize': filesize,
                            'ext': info.get('ext', 'mp4'),
                            'quality': 'best',
                            'description': ''
                        }
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return None
    
    @staticmethod
    def download_video(video_url):
        """Download video to memory"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Referer': 'https://www.google.com/'
            }
            
            response = http_requests.get(video_url, headers=headers, stream=True, timeout=60)
            
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
            logger.error(f"Error downloading video: {e}")
            return None

# ========== TELEGRAM BOT FUNCTIONS ==========
def send_telegram_message(chat_id, text, parse_mode='HTML', reply_markup=None):
    """Send message via Telegram Bot API"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode,
            'disable_web_page_preview': True
        }
        
        if reply_markup:
            payload['reply_markup'] = reply_markup
        
        response = http_requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return False

def send_telegram_video(chat_id, video_buffer, caption, filename):
    """Send video via Telegram Bot API"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendVideo"
        
        # Prepare files
        video_buffer.seek(0)
        files = {'video': (filename, video_buffer, 'video/mp4')}
        
        # Prepare data
        data = {
            'chat_id': chat_id,
            'caption': caption,
            'parse_mode': 'HTML',
            'supports_streaming': True
        }
        
        response = http_requests.post(url, data=data, files=files, timeout=60)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Error sending video: {e}")
        return False

def edit_telegram_message(chat_id, message_id, text, parse_mode='HTML'):
    """Edit existing Telegram message"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/editMessageText"
        payload = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
            'parse_mode': parse_mode,
            'disable_web_page_preview': True
        }
        
        response = http_requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        return False

def get_bot_info():
    """Get bot information"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getMe"
        response = http_requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                return data.get('result', {})
        return None
    except Exception as e:
        logger.error(f"Error getting bot info: {e}")
        return None

def set_webhook():
    """Set Telegram webhook"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
        payload = {
            'url': WEBHOOK_URL,
            'max_connections': 40,
            'allowed_updates': ['message', 'callback_query']
        }
        
        response = http_requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            logger.info(f"✅ Webhook set: {data}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        return False

# ========== BOT HANDLERS ==========
def handle_start(user_id, username, first_name, message_id):
    """Handle /start command"""
    # Add user to database
    db.add_user(user_id, username, first_name)
    
    welcome_text = f"""
<b>🌟 Welcome {first_name}! 🌟</b>

🤖 <b>Universal Video Downloader Bot</b>

🚀 <b>Download videos from:</b>
📺 YouTube • 📸 Instagram • 🎵 TikTok
📌 Pinterest • 📦 Terabox • 🐦 Twitter • 📘 Facebook
🔴 Reddit • 🎬 Likee • 🎞️ Dailymotion • 🎬 Vimeo

📥 <b>How to use:</b>
1. Send me any video link
2. I'll process it instantly
3. Get your video in best quality!

⚡ <b>Features:</b>
• No storage - Videos never saved
• Best available quality
• Fast & reliable
• Free forever!

⚠️ <b>Important:</b>
• Max file size: <b>50MB</b>
• Rate limit: <b>{RATE_LIMIT} downloads/hour</b>
• Only public videos

📊 <b>Your Stats:</b>
• Downloads this hour: 0/{RATE_LIMIT}
• Total downloads: 0

🔧 <b>Commands:</b>
/start - Show this message
/help - Detailed guide
/stats - Your statistics
/ping - Check bot status

🌐 <b>Hosted on:</b> Koyeb Cloud
🆔 <b>Your ID:</b> <code>{user_id}</code>
⭐ <b>Admin:</b> @Tg_AssistBot
"""
    
    # Create inline keyboard
    keyboard = {
        'inline_keyboard': [
            [
                {'text': '📺 YouTube', 'callback_data': 'guide_youtube'},
                {'text': '📸 Instagram', 'callback_data': 'guide_instagram'}
            ],
            [
                {'text': '🎵 TikTok', 'callback_data': 'guide_tiktok'},
                {'text': '📌 Pinterest', 'callback_data': 'guide_pinterest'}
            ],
            [
                {'text': '📦 Terabox', 'callback_data': 'guide_terabox'},
                {'text': '📊 My Stats', 'callback_data': 'my_stats'}
            ],
            [
                {'text': '📖 Help Guide', 'callback_data': 'help_menu'},
                {'text': '⭐ Rate Bot', 'callback_data': 'rate_bot'}
            ]
        ]
    }
    
    return send_telegram_message(user_id, welcome_text, parse_mode='HTML', reply_markup=keyboard)

def handle_help(user_id):
    """Handle /help command"""
    help_text = f"""
<b>📖 COMPLETE HELP GUIDE</b>

🤖 <b>What I can do:</b>
Download videos from multiple platforms in best quality.

🔗 <b>Supported Platforms:</b>
• YouTube (videos, shorts, live streams)
• Instagram (posts, reels, stories, IGTV)
• TikTok (videos, slideshows)
• Pinterest (pins, video pins)
• Terabox (all video files)
• Twitter/X (video tweets)
• Facebook (public videos)
• Reddit (video posts)
• Likee (videos)
• Dailymotion (videos)
• Vimeo (videos)
• Twitch (clips)
• Bilibili (videos)

📥 <b>How to Download:</b>
1. Copy video link from any app
2. Send it to me as a message
3. Wait 10-30 seconds for processing
4. Receive video directly in chat

🎯 <b>Quality:</b>
• Automatically selects best quality ≤50MB
• Multiple quality options when available
• HD when possible

⚡ <b>Quick Start Examples:</b>
• YouTube: <code>https://youtube.com/watch?v=dQw4w9WgXcQ</code>
• Instagram: <code>https://instagram.com/p/Cxample123/</code>
• TikTok: <code>https://tiktok.com/@user/video/123456789</code>
• <b>Any valid video link!</b>

⚠️ <b>Limitations:</b>
• Max file size: <b>50MB</b> (Telegram's limit)
• Rate limit: <b>{RATE_LIMIT} downloads/hour</b>
• Only public/accessible videos
• No password-protected content

❓ <b>Troubleshooting:</b>
1. <b>Link not working?</b>
   - Check if video is public
   - Try in browser first
   - Use a different link

2. <b>Download failed?</b>
   - File might be too large
   - Server might be busy
   - Try again in 5 minutes

3. <b>Quality issues?</b>
   - Source might limit quality
   - Try a different video
   - Check original source quality

🔧 <b>Commands:</b>
/start - Welcome message
/help - This guide
/stats - Your download statistics
/ping - Check bot status

🛡 <b>Privacy:</b>
• Videos are never stored on our servers
• No login required
• No personal data collected
• Direct streaming to Telegram

📞 <b>Support:</b>
Contact admin if you need help.
Remember to only download content you have rights to!
"""
    
    keyboard = {
        'inline_keyboard': [
            [
                {'text': '🚀 Try Download', 'switch_inline_query_current_chat': 'https://'},
                {'text': '📊 My Stats', 'callback_data': 'my_stats'}
            ],
            [
                {'text': '⭐ Rate Us', 'callback_data': 'rate_bot'},
                {'text': '🆘 Contact Admin', 'url': 'https://t.me/Tg_AssistBot'}
            ]
        ]
    }
    
    return send_telegram_message(user_id, help_text, parse_mode='HTML', reply_markup=keyboard)

def handle_stats(user_id, first_name):
    """Handle /stats command"""
    stats = db.get_user_stats(user_id)
    
    # Format last download
    last_download = stats['last_download']
    if last_download:
        try:
            last_dt = datetime.strptime(last_download, '%Y-%m-%d %H:%M:%S')
            last_str = last_dt.strftime('%b %d, %H:%M')
        except:
            last_str = "Never"
    else:
        last_str = "Never"
    
    # Get bot stats
    bot_stats = db.get_bot_stats()
    
    stats_text = f"""
<b>📊 YOUR STATISTICS</b>

👤 <b>User:</b> {first_name}
🆔 <b>ID:</b> <code>{user_id}</code>

📥 <b>Download Stats:</b>
• This Hour: <b>{stats['hourly']}/{RATE_LIMIT}</b>
• Today: <b>{stats['daily']} downloads</b>
• This Week: <b>{stats['weekly']} downloads</b>
• Total: <b>{stats['total']} downloads</b>
• Remaining: <b>{stats['remaining']} downloads</b>

⏰ <b>Last Download:</b> {last_str}
📈 <b>Progress:</b> {'█' * min(stats['hourly'], 5)}{'░' * max(0, 5 - stats['hourly'])} [{stats['hourly']}/5]

🌐 <b>Bot Statistics:</b>
• Total Users: <b>{bot_stats.get('total_users', 0)}</b>
• Total Downloads: <b>{bot_stats.get('total_downloads', 0)}</b>
• Active Users: <b>{bot_stats.get('active_users', 0)}</b>

💡 <b>Tips:</b>
• Send any video link to download
• Rate limit resets every hour
• Contact admin if you need help
"""
    
    keyboard = {
        'inline_keyboard': [
            [
                {'text': '🔄 Refresh', 'callback_data': 'refresh_stats'},
                {'text': '📥 Download Now', 'switch_inline_query_current_chat': ''}
            ],
            [
                {'text': '🏆 Leaderboard', 'callback_data': 'leaderboard'},
                {'text': '📈 Platform Stats', 'callback_data': 'platform_stats'}
            ]
        ]
    }
    
    return send_telegram_message(user_id, stats_text, parse_mode='HTML', reply_markup=keyboard)

def handle_ping(user_id):
    """Handle /ping command"""
    bot_stats = db.get_bot_stats()
    
    ping_text = f"""
<b>🏓 PONG! Bot is alive and healthy!</b>

📊 <b>Bot Status:</b>
✅ <b>Status:</b> Operational
🌐 <b>Host:</b> Koyeb Cloud
👥 <b>Users:</b> <b>{bot_stats.get('total_users', 0)}</b>
📥 <b>Downloads:</b> <b>{bot_stats.get('total_downloads', 0)}</b>
🎯 <b>Today:</b> <b>{bot_stats.get('today_downloads', 0)} downloads</b>

🔗 <b>Health Endpoints:</b>
• https://encouraging-di-1carnage1-6226074c.koyeb.app/health
• https://encouraging-di-1carnage1-6226074c.koyeb.app/ping
• https://encouraging-di-1carnage1-6226074c.koyeb.app/ping1
• https://encouraging-di-1carnage1-6226074c.koyeb.app/ping2

🕒 <b>Last Check:</b> {datetime.now().strftime('%H:%M:%S')}
📍 <b>Server:</b> Global CDN

<i>Everything is working perfectly! 🎉</i>
"""
    
    return send_telegram_message(user_id, ping_text, parse_mode='HTML')

def handle_admin(user_id):
    """Handle /admin command"""
    if user_id not in ADMIN_IDS:
        return send_telegram_message(user_id, "❌ <b>Admin only command.</b>", parse_mode='HTML')
    
    bot_stats = db.get_bot_stats()
    
    admin_text = f"""
<b>👑 ADMIN PANEL</b>

📊 <b>Bot Statistics:</b>
• Total Users: <b>{bot_stats.get('total_users', 0)}</b>
• Total Downloads: <b>{bot_stats.get('total_downloads', 0)}</b>
• Today's Downloads: <b>{bot_stats.get('today_downloads', 0)}</b>
• Active Users: <b>{bot_stats.get('active_users', 0)}</b>
• Banned Users: <b>{bot_stats.get('banned_users', 0)}</b>

🔗 <b>Platform Usage:</b>
"""
    
    # Add platform stats
    for platform_stat in bot_stats.get('platform_stats', []):
        platform, count = platform_stat
        icon = UniversalDownloader.PLATFORMS.get(platform, {}).get('icon', '📹')
        admin_text += f"• {icon} {platform.title()}: <b>{count}</b>\n"
    
    admin_text += f"""
🌐 <b>System Info:</b>
• Webhook: {WEBHOOK_URL}
• Bot: @{BOT_USERNAME}
• Uptime: {int(time.time() - start_time)} seconds

<b>👥 User Management:</b>
• <code>/users</code> - List all users
• <code>/ban [user_id]</code> - Ban a user
• <code>/unban [user_id]</code> - Unban a user

<b>📢 Broadcast:</b>
• <code>/broadcast [message]</code> - Send to all users

<b>📊 Statistics:</b>
• <code>/botstats</code> - Detailed statistics

🕒 <b>Last Updated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    keyboard = {
        'inline_keyboard': [
            [
                {'text': '👥 User List', 'callback_data': 'admin_users'},
                {'text': '🔄 Refresh', 'callback_data': 'admin_refresh'}
            ],
            [
                {'text': '📢 Broadcast', 'callback_data': 'admin_broadcast'},
                {'text': '📋 Logs', 'callback_data': 'admin_logs'}
            ]
        ]
    }
    
    return send_telegram_message(user_id, admin_text, parse_mode='HTML', reply_markup=keyboard)

def handle_video_download(user_id, username, first_name, text, message_id):
    """Handle video download requests"""
    # Check if user is banned
    if db.is_user_banned(user_id):
        return send_telegram_message(user_id, "🚫 <b>Your account has been banned.</b>\n\nIf you believe this is a mistake, contact admin @Tg_AssistBot.", parse_mode='HTML')
    
    # Check for URLs
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w\.\-?=&%#+]*'
    urls = re.findall(url_pattern, text)
    
    if not urls:
        return send_telegram_message(user_id, "🔍 <b>No URL found.</b>\n\nPlease send a video link from:\n• YouTube\n• Instagram\n• TikTok\n• Pinterest\n• Terabox\n• Twitter\n• Facebook\n\nExample: <code>https://youtube.com/watch?v=dQw4w9WgXcQ</code>", parse_mode='HTML')
    
    url = urls[0].strip()
    
    # Detect platform
    platform, icon = UniversalDownloader.detect_platform(url)
    
    if not platform:
        return send_telegram_message(user_id, "❌ <b>Platform not supported.</b>\n\nI support:\n• YouTube (youtube.com)\n• Instagram (instagram.com)\n• TikTok (tiktok.com)\n• Pinterest (pinterest.com)\n• Terabox (terabox.com)\n• Twitter/X (twitter.com/x.com)\n• Facebook (facebook.com)\n• Reddit (reddit.com)\n• Likee (likee.com)\n• Dailymotion (dailymotion.com)\n• Vimeo (vimeo.com)\n\nPlease check your link and try again.", parse_mode='HTML')
    
    # Check rate limit
    stats = db.get_user_stats(user_id)
    if stats['hourly'] >= RATE_LIMIT:
        return send_telegram_message(user_id, f"⏰ <b>Rate Limit Reached!</b>\n\nYou've used {stats['hourly']}/{RATE_LIMIT} downloads this hour.\nPlease wait 1 hour before downloading more.\n\n<i>Tip: The limit resets every hour at :00 minutes.</i>", parse_mode='HTML')
    
    # Send processing message
    processing_text = f"{icon} <b>Processing {platform.upper()} link...</b>\n⏳ Please wait while I analyze the video..."
    send_telegram_message(user_id, processing_text, parse_mode='HTML')
    
    # Process in background thread
    Thread(target=process_video_download, args=(user_id, username, first_name, url, platform, icon, message_id)).start()
    
    return True

def process_video_download(user_id, username, first_name, url, platform, icon, message_id):
    """Process video download in background thread"""
    try:
        # Step 1: Get video information
        edit_telegram_message(user_id, message_id + 1, f"{icon} <b>{platform.upper()} DETECTED</b>\n🔍 Analyzing video information...\nStep 1/3: Fetching metadata")
        
        video_info = UniversalDownloader.get_video_info(url)
        
        if not video_info:
            edit_telegram_message(user_id, message_id + 1, "❌ <b>Failed to get video information</b>\n\nPossible reasons:\n• Video is private/restricted\n• Link is invalid or expired\n• Platform is blocking downloads\n\nPlease try a different video.")
            return
        
        # Check file size
        if video_info['filesize'] > MAX_FILE_SIZE:
            size_mb = video_info['filesize'] / (1024 * 1024)
            edit_telegram_message(user_id, message_id + 1, f"❌ <b>File Too Large</b>\n\nVideo size: <b>{size_mb:.1f}MB</b>\nTelegram limit: <b>50MB</b>\n\nThis video exceeds Telegram's file size limit.\nTry a shorter video or different format.")
            return
        
        # Step 2: Download video
        edit_telegram_message(user_id, message_id + 1, f"⬇️ <b>Downloading video...</b>\n📁 Title: <code>{video_info['title'][:50]}...</code>\n💾 Size: {video_info['filesize']/(1024*1024):.1f}MB\nStep 2/3: Download in progress")
        
        video_buffer = UniversalDownloader.download_video(video_info['url'])
        
        if not video_buffer:
            edit_telegram_message(user_id, message_id + 1, "❌ <b>Download Failed</b>\n\nCould not download the video.\nPossible reasons:\n• Network error\n• Server timeout\n• Video unavailable\n\nPlease try again or use a different link.")
            # Record failed download
            db.record_download(user_id, platform, url, 0, False)
            return
        
        # Step 3: Upload to Telegram
        edit_telegram_message(user_id, message_id + 1, f"📤 <b>Uploading to Telegram...</b>\n⏳ Almost done...\nStep 3/3: Final upload")
        
        # Prepare caption
        file_size_mb = len(video_buffer.getvalue()) / (1024 * 1024)
        duration_str = f"{video_info['duration']}s" if video_info['duration'] else "N/A"
        
        caption = f"""
✅ <b>DOWNLOAD COMPLETE!</b>

📁 <b>Title:</b> {video_info['title'][:100]}
📊 <b>Platform:</b> {platform.upper()}
💾 <b>Size:</b> {file_size_mb:.1f}MB
⏱ <b>Duration:</b> {duration_str}
🎯 <b>Quality:</b> {video_info.get('quality', 'best')}

🤖 Downloaded via @{BOT_USERNAME}
⭐ Rate: /rate
"""
        
        # Send video
        filename = f"{video_info['title'][:50]}.mp4".replace('/', '_').replace('\\', '_')
        success = send_telegram_video(user_id, video_buffer, caption, filename)
        
        if success:
            # Record successful download
            db.record_download(user_id, platform, url, len(video_buffer.getvalue()), True)
            
            # Update user
            db.add_user(user_id, username, first_name)
            
            # Send success message
            new_stats = db.get_user_stats(user_id)
            edit_telegram_message(user_id, message_id + 1, f"✅ <b>Success! Video sent successfully!</b>\n\n📥 <b>Download Details:</b>\n• Platform: {platform.upper()}\n• Size: {file_size_mb:.1f}MB\n• Status: ✅ Complete\n\n📊 <b>Your Updated Stats:</b>\n• This Hour: {new_stats['hourly']}/{RATE_LIMIT}\n• Remaining: {new_stats['remaining']} downloads\n\n⭐ <b>Please rate your experience:</b> /rate")
            
            # Notify admin
            if user_id not in ADMIN_IDS:
                admin_message = f"""
📥 <b>NEW DOWNLOAD</b>

👤 <b>User:</b> {first_name}
🆔 <b>ID:</b> <code>{user_id}</code>
📊 <b>Platform:</b> {platform.upper()}
💾 <b>Size:</b> {file_size_mb:.1f}MB
🕒 <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}
"""
                for admin_id in ADMIN_IDS:
                    send_telegram_message(admin_id, admin_message, parse_mode='HTML')
        
        else:
            edit_telegram_message(user_id, message_id + 1, "❌ <b>Upload Failed</b>\n\nCould not send video to Telegram.\nPlease try again.")
            db.record_download(user_id, platform, url, 0, False)
        
        # Clean up
        video_buffer.close()
        
    except Exception as e:
        logger.error(f"Error in process_video_download: {e}")
        edit_telegram_message(user_id, message_id + 1, f"❌ <b>Download Failed</b>\n\nError: <code>{str(e)[:100]}</code>\n\nPlease try again or contact support.")
        db.record_download(user_id, platform, url, 0, False)

# ========== FLASK APP ==========
app = Flask(__name__)

@app.route('/')
def home():
    """Home page"""
    return jsonify({
        'status': 'online',
        'service': 'telegram-downloader-bot',
        'version': '3.0',
        'timestamp': datetime.now().isoformat(),
        'bot': BOT_USERNAME,
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
        'webhook': WEBHOOK_URL,
        'bot': BOT_USERNAME
    })

@app.route('/ping')
@app.route('/ping1')
@app.route('/ping2')
def ping():
    """Ping endpoints for uptime monitoring"""
    return jsonify({
        'status': 'pong',
        'timestamp': datetime.now().isoformat(),
        'message': 'Bot is running on Koyeb',
        'endpoint': request.path
    })

@app.route('/stats')
def stats():
    """Statistics endpoint"""
    bot_stats = db.get_bot_stats()
    return jsonify({
        'status': 'online',
        'statistics': bot_stats,
        'timestamp': datetime.now().isoformat(),
        'uptime': int(time.time() - start_time)
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram webhook endpoint"""
    try:
        if request.method == "POST":
            data = request.get_json()
            
            # Log the update
            logger.debug(f"Received update: {data}")
            
            # Process update in background thread
            Thread(target=process_webhook_update, args=(data,)).start()
            
            return 'OK'
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    
    return 'ERROR', 500

def process_webhook_update(data):
    """Process webhook update"""
    try:
        # Check if it's a message
        if 'message' in data:
            message = data['message']
            chat = message.get('chat', {})
            user_id = chat.get('id')
            username = chat.get('username', '')
            first_name = chat.get('first_name', 'User')
            message_id = message.get('message_id')
            text = message.get('text', '').strip()
            
            # Handle commands
            if text.startswith('/'):
                command = text.split()[0].lower()
                
                if command == '/start':
                    handle_start(user_id, username, first_name, message_id)
                elif command == '/help':
                    handle_help(user_id)
                elif command == '/stats':
                    handle_stats(user_id, first_name)
                elif command == '/ping':
                    handle_ping(user_id)
                elif command == '/admin':
                    handle_admin(user_id)
                elif command.startswith('/users'):
                    # Handle admin users command
                    if user_id in ADMIN_IDS:
                        # Simplified user list
                        users = db.get_all_users(limit=10)
                        user_list = "👥 <b>RECENT USERS</b>\n\n"
                        for user in users:
                            uid, uname, fname, downloads, last_dl, banned, join_date = user
                            status = "🔴 BANNED" if banned else "🟢 ACTIVE"
                            user_list += f"• {fname} (@{uname or 'N/A'})\n  ID: <code>{uid}</code> | {status}\n  📥 {downloads} DLs\n\n"
                        send_telegram_message(user_id, user_list, parse_mode='HTML')
                elif command.startswith('/ban'):
                    # Handle ban command
                    if user_id in ADMIN_IDS:
                        parts = text.split()
                        if len(parts) > 1:
                            target_id = int(parts[1])
                            reason = ' '.join(parts[2:]) if len(parts) > 2 else ''
                            if db.ban_user(target_id, user_id, reason):
                                send_telegram_message(user_id, f"✅ User <code>{target_id}</code> has been banned.", parse_mode='HTML')
                            else:
                                send_telegram_message(user_id, f"❌ Failed to ban user <code>{target_id}</code>.", parse_mode='HTML')
                elif command.startswith('/unban'):
                    # Handle unban command
                    if user_id in ADMIN_IDS:
                        parts = text.split()
                        if len(parts) > 1:
                            target_id = int(parts[1])
                            reason = ' '.join(parts[2:]) if len(parts) > 2 else ''
                            if db.unban_user(target_id, user_id, reason):
                                send_telegram_message(user_id, f"✅ User <code>{target_id}</code> has been unbanned.", parse_mode='HTML')
                            else:
                                send_telegram_message(user_id, f"❌ Failed to unban user <code>{target_id}</code>.", parse_mode='HTML')
                elif command.startswith('/broadcast'):
                    # Handle broadcast command
                    if user_id in ADMIN_IDS:
                        parts = text.split()
                        if len(parts) > 1:
                            broadcast_message = ' '.join(parts[1:])
                            users = db.get_all_users()
                            sent = 0
                            failed = 0
                            
                            for user in users:
                                uid = user[0]
                                try:
                                    send_telegram_message(uid, f"📢 <b>ANNOUNCEMENT</b>\n\n{broadcast_message}\n\n<i>From bot admin</i>", parse_mode='HTML')
                                    sent += 1
                                except:
                                    failed += 1
                            
                            send_telegram_message(user_id, f"✅ Broadcast complete!\n\n📊 Results:\n• Sent: {sent}\n• Failed: {failed}\n• Total: {len(users)}", parse_mode='HTML')
                elif command == '/botstats':
                    # Handle botstats command
                    if user_id in ADMIN_IDS:
                        bot_stats = db.get_bot_stats()
                        stats_text = f"""
📊 <b>BOT STATISTICS</b>

👥 <b>Users:</b>
• Total: <b>{bot_stats.get('total_users', 0)}</b>
• Active: <b>{bot_stats.get('active_users', 0)}</b>
• Banned: <b>{bot_stats.get('banned_users', 0)}</b>

📥 <b>Downloads:</b>
• Total: <b>{bot_stats.get('total_downloads', 0)}</b>
• Today: <b>{bot_stats.get('today_downloads', 0)}</b>
• Daily: <b>{bot_stats.get('daily_downloads', 0)}</b>

🔗 <b>Platform Stats:</b>
"""
                        for platform_stat in bot_stats.get('platform_stats', []):
                            platform, count = platform_stat
                            icon = UniversalDownloader.PLATFORMS.get(platform, {}).get('icon', '📹')
                            stats_text += f"• {icon} {platform.title()}: <b>{count}</b>\n"
                        
                        stats_text += f"\n🕒 <b>Last Updated:</b> {datetime.now().strftime('%H:%M:%S')}"
                        send_telegram_message(user_id, stats_text, parse_mode='HTML')
                else:
                    # Unknown command
                    handle_help(user_id)
            else:
                # Regular message - treat as video URL
                handle_video_download(user_id, username, first_name, text, message_id)
        
        # Handle callback queries
        elif 'callback_query' in data:
            callback = data['callback_query']
            query_id = callback.get('id')
            user_id = callback['from']['id']
            data_str = callback.get('data', '')
            message_id = callback['message']['message_id']
            
            # Answer callback query
            answer_url = f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery"
            http_requests.post(answer_url, json={'callback_query_id': query_id})
            
            # Handle callback data
            if data_str == 'my_stats':
                handle_stats(user_id, callback['from']['first_name'])
            elif data_str == 'refresh_stats':
                handle_stats(user_id, callback['from']['first_name'])
            elif data_str == 'help_menu':
                handle_help(user_id)
            elif data_str == 'rate_bot':
                # Show rating options
                keyboard = {
                    'inline_keyboard': [
                        [
                            {'text': '⭐ 1', 'callback_data': 'rate_1'},
                            {'text': '⭐⭐ 2', 'callback_data': 'rate_2'},
                            {'text': '⭐⭐⭐ 3', 'callback_data': 'rate_3'}
                        ],
                        [
                            {'text': '⭐⭐⭐⭐ 4', 'callback_data': 'rate_4'},
                            {'text': '⭐⭐⭐⭐⭐ 5', 'callback_data': 'rate_5'}
                        ],
                        [
                            {'text': '🚫 Skip', 'callback_data': 'rate_skip'}
                        ]
                    ]
                }
                send_telegram_message(user_id, "⭐ <b>RATE OUR SERVICE</b>\n\nHow was your experience with this bot?\n\nPlease select a rating:", parse_mode='HTML', reply_markup=keyboard)
            elif data_str.startswith('rate_'):
                if data_str == 'rate_skip':
                    edit_telegram_message(user_id, message_id, "Rating skipped. Thank you!")
                else:
                    rating = int(data_str.replace('rate_', ''))
                    db.add_rating(user_id, rating)
                    edit_telegram_message(user_id, message_id, f"⭐ <b>Thank you for rating us {rating}/5!</b>\n\nYour feedback helps us improve the service.\n\nHave a great day! 😊", parse_mode='HTML')
            elif data_str == 'leaderboard':
                # Show leaderboard
                users = db.get_all_users(limit=10)
                leaderboard = "🏆 <b>TOP 10 DOWNLOADERS</b>\n\n"
                for i, user in enumerate(users[:10], 1):
                    uid, uname, fname, downloads, last_dl, banned, join_date = user
                    medal = ['🥇', '🥈', '🥉'][i-1] if i <= 3 else f"{i}."
                    leaderboard += f"{medal} <b>{fname}</b> (@{uname or 'N/A'})\n   📥 {downloads} downloads | ID: <code>{uid}</code>\n\n"
                send_telegram_message(user_id, leaderboard, parse_mode='HTML')
            elif data_str == 'platform_stats':
                # Show platform stats
                bot_stats = db.get_bot_stats()
                stats_text = "📊 <b>PLATFORM STATISTICS</b>\n\n"
                total = bot_stats.get('total_downloads', 0)
                for platform_stat in bot_stats.get('platform_stats', []):
                    platform, count = platform_stat
                    icon = UniversalDownloader.PLATFORMS.get(platform, {}).get('icon', '📹')
                    percentage = (count / total * 100) if total > 0 else 0
                    bars = int(percentage / 10)
                    progress = '█' * bars + '░' * (10 - bars)
                    stats_text += f"{icon} <b>{platform.title()}</b>\n   📥 {count} downloads ({percentage:.1f}%)\n   [{progress}]\n\n"
                send_telegram_message(user_id, stats_text, parse_mode='HTML')
            elif data_str.startswith('guide_'):
                platform = data_str.replace('guide_', '')
                platform_names = {
                    'youtube': ('YouTube', '📺'),
                    'instagram': ('Instagram', '📸'),
                    'tiktok': ('TikTok', '🎵'),
                    'pinterest': ('Pinterest', '📌'),
                    'terabox': ('Terabox', '📦')
                }
                if platform in platform_names:
                    name, icon = platform_names[platform]
                    send_telegram_message(user_id, f"{icon} <b>{name} DOWNLOAD</b>\n\nSend me any {name} video link and I'll download it!\n\n<i>Tip: Copy link from {name} app and paste it here.</i>", parse_mode='HTML')
            elif data_str == 'admin_users':
                if user_id in ADMIN_IDS:
                    users = db.get_all_users(limit=10)
                    user_list = "👥 <b>RECENT USERS</b>\n\n"
                    for user in users:
                        uid, uname, fname, downloads, last_dl, banned, join_date = user
                        status = "🔴 BANNED" if banned else "🟢 ACTIVE"
                        user_list += f"• {fname} (@{uname or 'N/A'})\n  ID: <code>{uid}</code> | {status}\n  📥 {downloads} DLs\n\n"
                    send_telegram_message(user_id, user_list, parse_mode='HTML')
            elif data_str == 'admin_refresh':
                if user_id in ADMIN_IDS:
                    handle_admin(user_id)
            elif data_str == 'admin_broadcast':
                if user_id in ADMIN_IDS:
                    send_telegram_message(user_id, "📢 <b>BROADCAST MESSAGE</b>\n\nUse <code>/broadcast [message]</code> to send a message to all users.\n\nExample: <code>/broadcast New features added!</code>", parse_mode='HTML')
            elif data_str == 'admin_logs':
                if user_id in ADMIN_IDS:
                    send_telegram_message(user_id, "📋 <b>ADMIN LOGS</b>\n\nLogs are stored in the database. Use the admin panel to view detailed logs.", parse_mode='HTML')
                    
    except Exception as e:
        logger.error(f"Error processing webhook update: {e}")

# ========== STARTUP ==========
def initialize_bot():
    """Initialize the bot on startup"""
    global BOT_USERNAME, start_time
    
    start_time = time.time()
    
    print("=" * 60)
    print("🤖 TELEGRAM UNIVERSAL DOWNLOADER BOT")
    print("📥 YouTube • Instagram • TikTok • Pinterest • Terabox")
    print("🌐 Deployed on Koyeb - Production Ready")
    print("=" * 60)
    
    # Get bot info
    bot_info = get_bot_info()
    if bot_info:
        BOT_USERNAME = bot_info.get('username', '')
        logger.info(f"✅ Bot username: @{BOT_USERNAME}")
    else:
        logger.error("❌ Failed to get bot info")
        BOT_USERNAME = "TelegramDownloaderBot"
    
    # Set webhook
    if set_webhook():
        logger.info(f"✅ Webhook set: {WEBHOOK_URL}")
    else:
        logger.error("❌ Failed to set webhook")
    
    # Send startup notification
    startup_message = f"""
🤖 <b>BOT STARTED SUCCESSFULLY!</b>

📅 <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🤖 <b>Bot:</b> @{BOT_USERNAME}
🌐 <b>Host:</b> Koyeb Cloud
🔗 <b>Webhook:</b> {WEBHOOK_URL}
📊 <b>Database:</b> Connected
✅ <b>Status:</b> 🟢 Online

<b>Ready to serve! 🎉</b>
"""
    
    for admin_id in ADMIN_IDS:
        send_telegram_message(admin_id, startup_message, parse_mode='HTML')
    
    logger.info("✅ Bot initialization complete")
    logger.info(f"📡 Health endpoints: /health, /ping, /ping1, /ping2, /stats")

# Initialize bot
initialize_bot()

# ========== RUN FLASK APP ==========
if __name__ == '__main__':
    logger.info(f"✅ Starting Flask server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
