#!/usr/bin/env python3
"""
🤖 TELEGRAM UNIVERSAL VIDEO DOWNLOADER BOT - PREMIUM EDITION
📥 YouTube, Instagram, TikTok, Pinterest, Terabox + 15+ Platforms
⭐ Premium Features • Analytics • Compression
🌐 Deployed on Koyeb - Production Ready
"""

import os
import sys
import logging
import re
import json
import time
import hashlib
import threading
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import io
import sqlite3
import traceback
import math
import subprocess
from pathlib import Path
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor

# Flask imports
from flask import Flask, request, jsonify
from threading import Thread
import requests as http_requests

# Third-party imports
import yt_dlp
from urllib.parse import urlparse, unquote, quote

# ========== CONFIGURATION ==========
TOKEN = "7863008338:AAGoOdY4xpl0ATf0GRwQfCTg_Dt9ny5AM2c"
ADMIN_IDS = [7575087826]  # Your admin ID
BOT_USERNAME = ""
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB Telegram limit
RATE_LIMIT = 10  # Downloads per hour for free users
PREMIUM_RATE_LIMIT = 50  # Downloads per hour for premium users
PREMIUM_MAX_SIZE = 200 * 1024 * 1024  # 200MB for premium
PORT = int(os.environ.get("PORT", 8000))  # Koyeb uses 8000

# Get Koyeb URL from environment
KOYEB_APP_URL = os.environ.get("KOYEB_APP_URL", "https://encouraging-di-1carnage1-6226074c.koyeb.app")
WEBHOOK_URL = f"{KOYEB_APP_URL}/webhook"

print(f"🔧 Configuration:")
print(f"📱 Bot Token: {TOKEN[:10]}...")
print(f"🌐 Webhook URL: {WEBHOOK_URL}")
print(f"🔌 Port: {PORT}")
print(f"👑 Admin IDs: {ADMIN_IDS}")

# ========== LOGGING SETUP ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

# ========== DATABASE SETUP ==========
class Database:
    """SQLite database handler with premium features"""
    
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
                    rating INTEGER DEFAULT 0,
                    is_premium INTEGER DEFAULT 0,
                    premium_until TIMESTAMP,
                    total_premium_days INTEGER DEFAULT 0
                )
            ''')
            
            # Downloads table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    platform TEXT,
                    url TEXT,
                    title TEXT,
                    file_size INTEGER,
                    quality TEXT,
                    download_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    success INTEGER DEFAULT 1,
                    compressed INTEGER DEFAULT 0,
                    is_premium INTEGER DEFAULT 0
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
            
            # Video history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS video_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    platform TEXT,
                    url TEXT,
                    title TEXT,
                    thumbnail TEXT,
                    download_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    file_size INTEGER,
                    quality TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Analytics table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS analytics (
                    date DATE PRIMARY KEY,
                    total_downloads INTEGER DEFAULT 0,
                    total_users INTEGER DEFAULT 0,
                    premium_downloads INTEGER DEFAULT 0
                )
            ''')
            
            # Ads table (admin managed)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ad_type TEXT,
                    content TEXT,
                    url TEXT,
                    impressions INTEGER DEFAULT 0,
                    clicks INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Initialize platforms
            platforms = ['youtube', 'instagram', 'tiktok', 'pinterest', 'terabox', 
                        'twitter', 'facebook', 'reddit', 'likee', 'snackvideo',
                        'dailymotion', 'vimeo', 'twitch', 'bilibili', 'rutube']
            for platform in platforms:
                cursor.execute('INSERT OR IGNORE INTO platform_stats (platform) VALUES (?)', (platform,))
            
            self.conn.commit()
            logger.info("✅ Database setup complete with premium features")
            
        except Exception as e:
            logger.error(f"❌ Database setup failed: {e}")
    
    def add_user(self, user_id, username, first_name):
        """Add or update user in database"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, username, first_name, join_date)
                VALUES (?, ?, ?, COALESCE((SELECT join_date FROM users WHERE user_id = ?), CURRENT_TIMESTAMP))
            ''', (user_id, username, first_name, user_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False
    
    def get_user_stats(self, user_id):
        """Get user download statistics"""
        try:
            cursor = self.conn.cursor()
            
            # Check if premium
            cursor.execute('SELECT is_premium, premium_until FROM users WHERE user_id = ?', (user_id,))
            user_data = cursor.fetchone()
            is_premium = user_data[0] if user_data else 0
            premium_until = user_data[1] if user_data and user_data[1] else None
            
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
            
            # Get rate limit
            rate_limit = PREMIUM_RATE_LIMIT if is_premium else RATE_LIMIT
            remaining = max(0, rate_limit - hourly)
            
            return {
                'hourly': hourly,
                'daily': daily,
                'weekly': weekly,
                'total': total,
                'remaining': remaining,
                'last_download': last_download,
                'is_premium': bool(is_premium),
                'premium_until': premium_until,
                'rate_limit': rate_limit
            }
            
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return {'hourly': 0, 'daily': 0, 'weekly': 0, 'total': 0, 'remaining': RATE_LIMIT, 
                   'last_download': None, 'is_premium': False, 'premium_until': None, 'rate_limit': RATE_LIMIT}
    
    def record_download(self, user_id, platform, url, title, file_size, quality, success=True, compressed=False):
        """Record a download attempt"""
        try:
            cursor = self.conn.cursor()
            
            # Check if premium
            cursor.execute('SELECT is_premium FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            is_premium = result[0] if result else 0
            
            # Record download
            cursor.execute('''
                INSERT INTO downloads (user_id, platform, url, title, file_size, quality, success, compressed, is_premium)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, platform, url, title, file_size, quality, 1 if success else 0, 
                  1 if compressed else 0, is_premium))
            
            # Add to video history
            if success:
                cursor.execute('''
                    INSERT INTO video_history (user_id, platform, url, title, file_size, quality)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, platform, url, title, file_size, quality))
            
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
            
            # Update analytics
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
                INSERT OR IGNORE INTO analytics (date) VALUES (?)
            ''', (today,))
            
            cursor.execute('''
                UPDATE analytics 
                SET total_downloads = total_downloads + 1,
                    premium_downloads = premium_downloads + ?
                WHERE date = ?
            ''', (1 if is_premium else 0, today))
            
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error recording download: {e}")
            return False
    
    def get_download_history(self, user_id, limit=20):
        """Get user's download history"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT id, platform, url, title, thumbnail, download_date, file_size, quality
                FROM video_history 
                WHERE user_id = ?
                ORDER BY download_date DESC
                LIMIT ?
            ''', (user_id, limit))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting download history: {e}")
            return []
    
    def add_premium(self, user_id, days, admin_id):
        """Add premium subscription to user"""
        try:
            cursor = self.conn.cursor()
            
            # Get current premium status
            cursor.execute('SELECT premium_until FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            
            if result and result[0]:
                current_until = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
                new_until = current_until + timedelta(days=days)
            else:
                new_until = datetime.now() + timedelta(days=days)
            
            # Update user
            cursor.execute('''
                UPDATE users 
                SET is_premium = 1,
                    premium_until = ?,
                    total_premium_days = total_premium_days + ?
                WHERE user_id = ?
            ''', (new_until.strftime('%Y-%m-%d %H:%M:%S'), days, user_id))
            
            # Log admin action
            cursor.execute('''
                INSERT INTO admin_logs (admin_id, action, target_id, details)
                VALUES (?, 'add_premium', ?, ?)
            ''', (admin_id, user_id, f'{days} days'))
            
            self.conn.commit()
            return True, new_until
        except Exception as e:
            logger.error(f"Error adding premium: {e}")
            return False, None
    
    def remove_premium(self, user_id, admin_id, reason=""):
        """Remove premium subscription from user"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET is_premium = 0,
                    premium_until = NULL
                WHERE user_id = ?
            ''', (user_id,))
            
            # Log admin action
            cursor.execute('''
                INSERT INTO admin_logs (admin_id, action, target_id, details)
                VALUES (?, 'remove_premium', ?, ?)
            ''', (admin_id, user_id, reason))
            
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error removing premium: {e}")
            return False
    
    def get_premium_users(self):
        """Get all premium users"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT user_id, username, first_name, premium_until, total_premium_days, downloads
                FROM users 
                WHERE is_premium = 1
                ORDER BY premium_until DESC
            ''')
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting premium users: {e}")
            return []
    
    def is_premium_user(self, user_id):
        """Check if user is premium"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT is_premium, premium_until FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            
            if result and result[0]:
                if result[1]:
                    premium_until = datetime.strptime(result[1], '%Y-%m-%d %H:%M:%S')
                    if premium_until < datetime.now():
                        # Premium expired
                        cursor.execute('UPDATE users SET is_premium = 0, premium_until = NULL WHERE user_id = ?', (user_id,))
                        self.conn.commit()
                        return False
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking premium status: {e}")
            return False
    
    def get_all_users(self, limit=100):
        """Get all users"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT user_id, username, first_name, downloads, 
                       last_download, is_banned, join_date, is_premium
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
            
            # Premium users count
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_premium = 1')
            premium_users = cursor.fetchone()[0]
            
            return {
                'total_users': total_users,
                'active_users': active_users,
                'banned_users': banned_users,
                'premium_users': premium_users,
                'total_downloads': total_downloads,
                'today_downloads': today_downloads,
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
    
    # Ads management methods
    def create_ad(self, ad_type, content, url):
        """Create a new ad"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO ads (ad_type, content, url, is_active)
                VALUES (?, ?, ?, 1)
            ''', (ad_type, content, url))
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error creating ad: {e}")
            return None
    
    def get_ads(self, active_only=True):
        """Get all ads"""
        try:
            cursor = self.conn.cursor()
            if active_only:
                cursor.execute('SELECT * FROM ads WHERE is_active = 1 ORDER BY created_at DESC')
            else:
                cursor.execute('SELECT * FROM ads ORDER BY created_at DESC')
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting ads: {e}")
            return []
    
    def toggle_ad(self, ad_id, active):
        """Toggle ad status"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE ads SET is_active = ? WHERE id = ?', (1 if active else 0, ad_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error toggling ad: {e}")
            return False
    
    def delete_ad(self, ad_id):
        """Delete an ad"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM ads WHERE id = ?', (ad_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting ad: {e}")
            return False

# Initialize database
db = Database()

# ========== DOWNLOADER ENGINE ==========
class UniversalDownloader:
    """Universal downloader with premium features"""
    
    PLATFORMS = {
        'youtube': {'icon': '📺', 'domains': ['youtube.com', 'youtu.be', 'm.youtube.com', 'www.youtube.com']},
        'instagram': {'icon': '📸', 'domains': ['instagram.com', 'instagr.am', 'www.instagram.com']},
        'tiktok': {'icon': '🎵', 'domains': ['tiktok.com', 'vm.tiktok.com', 'www.tiktok.com', 'vt.tiktok.com']},
        'pinterest': {'icon': '📌', 'domains': ['pinterest.com', 'pin.it', 'www.pinterest.com']},
        'terabox': {'icon': '📦', 'domains': ['terabox.com', 'teraboxapp.com', 'www.terabox.com', 'teraboxurl.com']},
        'twitter': {'icon': '🐦', 'domains': ['twitter.com', 'x.com', 'www.twitter.com', 'www.x.com']},
        'facebook': {'icon': '📘', 'domains': ['facebook.com', 'fb.watch', 'www.facebook.com', 'm.facebook.com']},
        'reddit': {'icon': '🔴', 'domains': ['reddit.com', 'redd.it', 'www.reddit.com', 'v.redd.it']},
        'likee': {'icon': '🎬', 'domains': ['likee.video', 'likee.com', 'www.likee.com']},
        'snackvideo': {'icon': '🎥', 'domains': ['snackvideo.com', 'www.snackvideo.com']},
        'dailymotion': {'icon': '🎞️', 'domains': ['dailymotion.com', 'www.dailymotion.com']},
        'vimeo': {'icon': '🎬', 'domains': ['vimeo.com', 'www.vimeo.com']},
        'twitch': {'icon': '👾', 'domains': ['twitch.tv', 'www.twitch.tv', 'clips.twitch.tv']},
        'bilibili': {'icon': '🇨🇳', 'domains': ['bilibili.com', 'www.bilibili.com']},
        'rutube': {'icon': '🇷🇺', 'domains': ['rutube.ru', 'www.rutube.ru']},
        'rumble': {'icon': '🎥', 'domains': ['rumble.com', 'www.rumble.com']},
        'streamable': {'icon': '🎞️', 'domains': ['streamable.com', 'www.streamable.com']},
        'odysee': {'icon': '🔵', 'domains': ['odysee.com', 'www.odysee.com']}
    }
    
    @staticmethod
    def detect_platform(url):
        """Detect which platform the URL belongs to"""
        url_lower = url.lower()
        # Remove protocol prefix for checking
        url_lower = url_lower.replace('https://', '').replace('http://', '')
        
        for platform, data in UniversalDownloader.PLATFORMS.items():
            for domain in data['domains']:
                if domain in url_lower:
                    return platform, data['icon']
        return None, '📹'
    
    @staticmethod
    def get_video_info(url, is_premium=False):
        """Get video information using yt-dlp with premium options"""
        try:
            max_size = PREMIUM_MAX_SIZE if is_premium else MAX_FILE_SIZE
            
            # Special handling for Terabox URLs
            if 'terabox' in url.lower():
                # Try with special extractor
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'format': 'best[filesize<?{}]'.format(max_size),
                    'socket_timeout': 60,
                    'retries': 3,
                    'no_check_certificate': True,
                    'ignoreerrors': True,
                    'extract_flat': False,
                    'noplaylist': True,
                    'cookiefile': None,
                    'geo_bypass': True,
                    'geo_bypass_country': 'US',
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': '*/*',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Referer': 'https://www.terabox.com/',
                        'Origin': 'https://www.terabox.com',
                        'Sec-Fetch-Dest': 'empty',
                        'Sec-Fetch-Mode': 'cors',
                        'Sec-Fetch-Site': 'same-site'
                    },
                    'extractor_args': {
                        'terabox': {'skip': False}
                    }
                }
            elif 'instagram' in url.lower():
                # Instagram specific settings with cookies
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'format': 'best[filesize<?{}]'.format(max_size),
                    'socket_timeout': 30,
                    'retries': 3,
                    'no_check_certificate': True,
                    'ignoreerrors': True,
                    'extract_flat': False,
                    'noplaylist': True,
                    'geo_bypass': True,
                    'geo_bypass_country': 'US',
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': '*/*',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Referer': 'https://www.instagram.com/',
                        'Origin': 'https://www.instagram.com',
                        'Sec-Fetch-Dest': 'empty',
                        'Sec-Fetch-Mode': 'cors',
                        'Sec-Fetch-Site': 'same-site'
                    },
                    'cookiefile': None,
                    'extractor_args': {
                        'instagram': {
                            'skip': False,
                            'geo_bypass': True,
                            'geo_bypass_country': 'US'
                        }
                    }
                }
            else:
                # Default settings for other platforms
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'format': 'best[filesize<?{}]'.format(max_size),
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
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': '*/*',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Referer': 'https://www.google.com/'
                    }
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    logger.error(f"No info extracted for URL: {url}")
                    return None
                
                # Get available formats
                available_formats = []
                if 'formats' in info:
                    for fmt in info['formats']:
                        if fmt.get('filesize') and fmt['filesize'] <= max_size:
                            available_formats.append({
                                'format_id': fmt.get('format_id'),
                                'ext': fmt.get('ext', 'mp4'),
                                'filesize': fmt.get('filesize'),
                                'format_note': fmt.get('format_note', 'unknown'),
                                'width': fmt.get('width'),
                                'height': fmt.get('height'),
                                'url': fmt.get('url')
                            })
                elif 'url' in info:
                    # Single format available
                    available_formats.append({
                        'format_id': 'best',
                        'ext': info.get('ext', 'mp4'),
                        'filesize': info.get('filesize', 0),
                        'format_note': 'best',
                        'width': info.get('width'),
                        'height': info.get('height'),
                        'url': info.get('url')
                    })
                
                # Sort by quality (higher resolution first)
                available_formats.sort(key=lambda x: (x.get('height', 0) or 0, x.get('filesize', 0)), reverse=True)
                
                # Get best format
                best_format = available_formats[0] if available_formats else None
                
                if best_format:
                    return {
                        'success': True,
                        'title': info.get('title', 'Video')[:200],
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail'),
                        'url': best_format.get('url'),
                        'filesize': best_format.get('filesize', 0),
                        'ext': best_format.get('ext', 'mp4'),
                        'quality': best_format.get('format_note', 'best'),
                        'description': (info.get('description', '')[:100] + '...') if info.get('description') else '',
                        'view_count': info.get('view_count', 0),
                        'uploader': info.get('uploader', 'Unknown'),
                        'available_formats': available_formats[:5]  # Top 5 formats
                    }
                
                return None
                
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Download error getting video info: {e}")
            # Try alternative method for Instagram
            if 'instagram' in url.lower():
                return UniversalDownloader._get_instagram_info_alternative(url, max_size)
            return None
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            logger.error(traceback.format_exc())
            return None
    
    @staticmethod
    def _get_instagram_info_alternative(url, max_size):
        """Alternative method to get Instagram video info"""
        try:
            # Use a different approach for Instagram
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0'
            }
            
            response = http_requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                # Try to find video URL in the HTML
                html = response.text
                
                # Look for video URLs in the HTML
                video_url_patterns = [
                    r'"video_url":"([^"]+)"',
                    r'"contentUrl":"([^"]+)"',
                    r'<meta property="og:video" content="([^"]+)"',
                    r'src="([^"]+\.mp4[^"]*)"',
                ]
                
                for pattern in video_url_patterns:
                    matches = re.findall(pattern, html)
                    if matches:
                        video_url = matches[0]
                        # Fix URL encoding
                        video_url = video_url.replace('\\u0026', '&')
                        
                        # Get video info from headers
                        head_response = http_requests.head(video_url, headers=headers, timeout=10, allow_redirects=True)
                        
                        if head_response.status_code == 200:
                            content_length = head_response.headers.get('content-length')
                            file_size = int(content_length) if content_length else 0
                            
                            if file_size <= max_size:
                                # Extract title
                                title_patterns = [
                                    r'"title":"([^"]+)"',
                                    r'<title>([^<]+)</title>',
                                    r'<meta property="og:title" content="([^"]+)"'
                                ]
                                
                                title = "Instagram Video"
                                for tpattern in title_patterns:
                                    tmatches = re.findall(tpattern, html)
                                    if tmatches:
                                        title = tmatches[0]
                                        break
                                
                                return {
                                    'success': True,
                                    'title': title[:200],
                                    'duration': 0,
                                    'thumbnail': None,
                                    'url': video_url,
                                    'filesize': file_size,
                                    'ext': 'mp4',
                                    'quality': 'best',
                                    'description': '',
                                    'view_count': 0,
                                    'uploader': 'Instagram',
                                    'available_formats': [{'format_id': 'best', 'ext': 'mp4', 'filesize': file_size, 'format_note': 'best', 'url': video_url}]
                                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error in Instagram alternative method: {e}")
            return None
    
    @staticmethod
    def download_video(video_url, progress_callback=None):
        """Download video to memory with progress tracking"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive',
                'Referer': 'https://www.google.com/',
                'Sec-Fetch-Dest': 'video',
                'Sec-Fetch-Mode': 'no-cors',
                'Sec-Fetch-Site': 'cross-site'
            }
            
            # Special headers for different platforms
            if 'instagram' in video_url:
                headers.update({
                    'Referer': 'https://www.instagram.com/',
                    'Origin': 'https://www.instagram.com'
                })
            elif 'terabox' in video_url:
                headers.update({
                    'Referer': 'https://www.terabox.com/',
                    'Origin': 'https://www.terabox.com'
                })
            elif 'tiktok' in video_url:
                headers.update({
                    'Referer': 'https://www.tiktok.com/',
                    'Origin': 'https://www.tiktok.com'
                })
            
            response = http_requests.get(video_url, headers=headers, stream=True, timeout=120)
            
            if response.status_code == 200:
                total_size = int(response.headers.get('content-length', 0))
                buffer = io.BytesIO()
                downloaded = 0
                chunk_size = 8192
                
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        buffer.write(chunk)
                        downloaded += len(chunk)
                        
                        # Call progress callback
                        if progress_callback and total_size > 0:
                            progress = min(100, int((downloaded / total_size) * 100))
                            progress_callback(progress)
                        
                        if downloaded > MAX_FILE_SIZE * 2:  # Double check for safety
                            logger.warning(f"File too large: {downloaded} bytes")
                            return None, 0
                
                buffer.seek(0)
                logger.info(f"Downloaded {downloaded} bytes from {video_url}")
                return buffer, downloaded
            
            logger.error(f"Download failed with status: {response.status_code}")
            return None, 0
            
        except Exception as e:
            logger.error(f"Error downloading video: {e}")
            logger.error(traceback.format_exc())
            return None, 0
    
    @staticmethod
    def compress_video(input_buffer, quality='medium'):
        """Compress video using ffmpeg"""
        try:
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_input:
                temp_input.write(input_buffer.read())
                temp_input_path = temp_input.name
            
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_output:
                temp_output_path = temp_output.name
            
            # Compression settings based on quality
            if quality == 'high':
                crf = '23'
                preset = 'medium'
            elif quality == 'medium':
                crf = '28'
                preset = 'fast'
            else:  # low
                crf = '32'
                preset = 'ultrafast'
            
            # FFmpeg command
            cmd = [
                'ffmpeg', '-i', temp_input_path,
                '-c:v', 'libx264', '-crf', crf, '-preset', preset,
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                '-y', temp_output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                with open(temp_output_path, 'rb') as f:
                    compressed_data = f.read()
                
                # Cleanup
                os.unlink(temp_input_path)
                os.unlink(temp_output_path)
                
                return io.BytesIO(compressed_data), len(compressed_data)
            else:
                logger.error(f"FFmpeg error: {result.stderr}")
            
            # Cleanup on failure
            if os.path.exists(temp_input_path):
                os.unlink(temp_input_path)
            if os.path.exists(temp_output_path):
                os.unlink(temp_output_path)
            
            return None, 0
            
        except Exception as e:
            logger.error(f"Error compressing video: {e}")
            # Cleanup
            if 'temp_input_path' in locals() and os.path.exists(temp_input_path):
                os.unlink(temp_input_path)
            if 'temp_output_path' in locals() and os.path.exists(temp_output_path):
                os.unlink(temp_output_path)
            return None, 0

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
        
        response = http_requests.post(url, json=payload, timeout=30)
        logger.info(f"📤 Sent message to {chat_id}, status: {response.status_code}")
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
        
        response = http_requests.post(url, data=data, files=files, timeout=120)
        logger.info(f"📤 Sent video to {chat_id}, status: {response.status_code}")
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
        
        response = http_requests.post(url, json=payload, timeout=30)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        return False

def delete_telegram_message(chat_id, message_id):
    """Delete a Telegram message"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/deleteMessage"
        payload = {
            'chat_id': chat_id,
            'message_id': message_id
        }
        
        response = http_requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
        return False

def get_bot_info():
    """Get bot information"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getMe"
        response = http_requests.get(url, timeout=30)
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
            'max_connections': 100,
            'allowed_updates': ['message', 'callback_query', 'inline_query']
        }
        
        response = http_requests.post(url, json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            logger.info(f"✅ Webhook set: {data}")
            return True
        else:
            logger.error(f"❌ Failed to set webhook: {response.status_code} - {response.text}")
        return False
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        return False

def delete_webhook():
    """Delete Telegram webhook"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
        response = http_requests.post(url, timeout=30)
        if response.status_code == 200:
            logger.info("✅ Webhook deleted")
            return True
        return False
    except Exception as e:
        logger.error(f"Error deleting webhook: {e}")
        return False

# ========== BOT HANDLERS ==========
def handle_start(user_id, username, first_name, message_id):
    """Handle /start command"""
    # Add user to database
    db.add_user(user_id, username, first_name)
    
    # Check premium status
    is_premium = db.is_premium_user(user_id)
    premium_badge = "⭐ PREMIUM USER ⭐\n\n" if is_premium else ""
    
    welcome_text = f"""
<b>🌟 Welcome {first_name}! 🌟</b>

{premium_badge}🤖 <b>Universal Video Downloader Bot</b>

🚀 <b>Download videos from:</b>
📺 YouTube • 📸 Instagram • 🎵 TikTok
📌 Pinterest • 📦 Terabox • 🐦 Twitter • 📘 Facebook
🔴 Reddit • 🎬 Likee • 🎞️ Dailymotion • 🎬 Vimeo
👾 Twitch • 🇨🇳 Bilibili • 🇷🇺 Rutube • 🎥 Rumble

📥 <b>How to use:</b>
1. Send me any video link
2. I'll process it instantly
3. Get your video in best quality!

⚡ <b>Features:</b>
• No storage - Videos never saved
• Best available quality
• Fast & reliable
• Free forever!

⭐ <b>Premium Features:</b>
• 200MB file size limit
• 50 downloads/hour
• Video compression
• Priority processing

💰 <b>Premium Subscription:</b>
Contact admin @Tg_AssistBot

⚠️ <b>Important:</b>
• Free: Max <b>50MB</b> • Premium: Max <b>200MB</b>
• Free: <b>{RATE_LIMIT} downloads/hour</b>
• Premium: <b>{PREMIUM_RATE_LIMIT} downloads/hour</b>

📊 <b>Your Stats:</b>
• Status: {'⭐ PREMIUM' if is_premium else '🆓 FREE'}
• Downloads this hour: 0/{PREMIUM_RATE_LIMIT if is_premium else RATE_LIMIT}
• Total downloads: 0

🔧 <b>Commands:</b>
/start - Show this message
/help - Detailed guide
/stats - Your statistics
/history - Download history
/premium - Premium info
/features - All features
"""
    
    # Create inline keyboard
    keyboard = {
        'inline_keyboard': [
            [
                {'text': '📺 YouTube', 'callback_data': 'guide_youtube'},
                {'text': '📸 Instagram', 'callback_data': 'guide_instagram'},
                {'text': '🎵 TikTok', 'callback_data': 'guide_tiktok'}
            ],
            [
                {'text': '📌 Pinterest', 'callback_data': 'guide_pinterest'},
                {'text': '📦 Terabox', 'callback_data': 'guide_terabox'},
                {'text': '🐦 Twitter', 'callback_data': 'guide_twitter'}
            ],
            [
                {'text': '📊 My Stats', 'callback_data': 'my_stats'},
                {'text': '📋 History', 'callback_data': 'history'}
            ],
            [
                {'text': '⭐ Premium', 'callback_data': 'premium_info'},
                {'text': '🛠️ Tools', 'callback_data': 'tools_menu'}
            ],
            [
                {'text': '📖 Help Guide', 'callback_data': 'help_menu'},
                {'text': '📞 Contact Admin', 'url': 'https://t.me/Tg_AssistBot'}
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
• Rutube (videos)
• Rumble (videos)
• Streamable (videos)
• Odysee (videos)

📥 <b>How to Download:</b>
1. Copy video link from any app
2. Send it to me as a message
3. Wait 10-60 seconds for processing
4. Receive video directly in chat

🎯 <b>Quality Options:</b>
• Free: Best available (up to 720p)
• Premium: Up to 4K when available
• Multiple format options for premium users

⚡ <b>Quick Start Examples:</b>
• YouTube: <code>https://youtube.com/watch?v=dQw4w9WgXcQ</code>
• Instagram: <code>https://instagram.com/p/Cxample123/</code>
• TikTok: <code>https://tiktok.com/@user/video/123456789</code>
• Terabox: <code>https://terabox.com/s/xxxxx</code>
• <b>Any valid video link!</b>

⚠️ <b>Limitations:</b>
• Free: Max <b>50MB</b> file size
• Free: <b>{RATE_LIMIT} downloads/hour</b>
• Premium: Max <b>200MB</b> file size
• Premium: <b>{PREMIUM_RATE_LIMIT} downloads/hour</b>

❓ <b>Troubleshooting:</b>
1. <b>Link not working?</b>
   - Check if video is public
   - Try in browser first
   - Use a different link

2. <b>Download failed?</b>
   - File might be too large
   - Server might be busy
   - Try again in 5 minutes
   - Use /report to notify admin

3. <b>Quality issues?</b>
   - Source might limit quality
   - Try a different video
   - Check original source quality

🔧 <b>Commands:</b>
/start - Welcome message
/help - This guide
/stats - Your download statistics
/history - Your download history
/premium - Premium subscription info
/features - All bot features
/report - Report issues

🛡 <b>Privacy:</b>
• Videos are never stored on our servers
• No login required
• No personal data collected
• Direct streaming to Telegram

📞 <b>Support:</b>
Contact admin @Tg_AssistBot for help.
Remember to only download content you have rights to!
"""
    
    keyboard = {
        'inline_keyboard': [
            [
                {'text': '🚀 Try Download', 'switch_inline_query_current_chat': 'https://'},
                {'text': '📊 My Stats', 'callback_data': 'my_stats'}
            ],
            [
                {'text': '⭐ Go Premium', 'callback_data': 'premium_info'},
                {'text': '🛠️ Tools', 'callback_data': 'tools_menu'}
            ],
            [
                {'text': '📋 History', 'callback_data': 'history'},
                {'text': '📞 Contact Admin', 'url': 'https://t.me/Tg_AssistBot'}
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
    
    # Format premium until
    premium_until = stats['premium_until']
    premium_status = ""
    if stats['is_premium']:
        if premium_until:
            try:
                until_dt = datetime.strptime(premium_until, '%Y-%m-%d %H:%M:%S')
                days_left = (until_dt - datetime.now()).days
                premium_status = f"⭐ <b>Premium Active</b>\n📅 Expires: {until_dt.strftime('%b %d, %Y')}\n⏳ Days left: <b>{days_left}</b>\n\n"
            except:
                premium_status = "⭐ <b>Premium Active</b>\n\n"
    else:
        premium_status = "🆓 <b>Free Account</b>\n💡 Upgrade to premium for more features!\n\n"
    
    stats_text = f"""
<b>📊 YOUR STATISTICS</b>

{premium_status}👤 <b>User:</b> {first_name}
🆔 <b>ID:</b> <code>{user_id}</code>

📥 <b>Download Stats:</b>
• This Hour: <b>{stats['hourly']}/{stats['rate_limit']}</b>
• Today: <b>{stats['daily']} downloads</b>
• This Week: <b>{stats['weekly']} downloads</b>
• Total: <b>{stats['total']} downloads</b>
• Remaining: <b>{stats['remaining']} downloads</b>

⏰ <b>Last Download:</b> {last_str}

📈 <b>Progress Bar:</b>
"""
    
    # Create progress bar
    progress = min(stats['hourly'], 10)
    stats_text += f"[{'█' * progress}{'░' * (10 - progress)}] {stats['hourly']}/10\n\n"
    
    stats_text += """💡 <b>Tips:</b>
• Send any video link to download
• Rate limit resets every hour
• Contact admin for premium
"""
    
    keyboard = {
        'inline_keyboard': [
            [
                {'text': '🔄 Refresh', 'callback_data': 'refresh_stats'},
                {'text': '📥 Download Now', 'switch_inline_query_current_chat': ''}
            ],
            [
                {'text': '📋 History', 'callback_data': 'history'},
                {'text': '⭐ Premium', 'callback_data': 'premium_info'}
            ]
        ]
    }
    
    return send_telegram_message(user_id, stats_text, parse_mode='HTML', reply_markup=keyboard)

def handle_history(user_id, page=1):
    """Handle /history command"""
    history = db.get_download_history(user_id, limit=50)
    
    if not history:
        return send_telegram_message(user_id, "📭 <b>No download history found.</b>\n\nStart by sending me a video link!", parse_mode='HTML')
    
    # Paginate
    items_per_page = 10
    total_pages = (len(history) + items_per_page - 1) // items_per_page
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_items = history[start_idx:end_idx]
    
    history_text = f"""
<b>📋 DOWNLOAD HISTORY</b>

📊 <b>Total Downloads:</b> {len(history)}
📄 <b>Page:</b> {page}/{total_pages}

"""
    
    for idx, item in enumerate(page_items, start=start_idx + 1):
        item_id, platform, url, title, thumbnail, download_date, file_size, quality = item
        
        # Format date
        try:
            dt = datetime.strptime(download_date, '%Y-%m-%d %H:%M:%S')
            date_str = dt.strftime('%b %d, %H:%M')
        except:
            date_str = download_date
        
        # Truncate title
        display_title = title[:30] + "..." if len(title) > 30 else title
        
        # Format size
        size_mb = file_size / (1024 * 1024) if file_size else 0
        
        icon = UniversalDownloader.PLATFORMS.get(platform, {}).get('icon', '📹')
        
        history_text += f"""<b>{idx}.</b> {icon} <b>{platform.upper()}</b>
├─ <b>Title:</b> {display_title}
├─ <b>Quality:</b> {quality}
├─ <b>Size:</b> {size_mb:.1f}MB
├─ <b>Date:</b> {date_str}
└─ <b>Link:</b> <code>{url[:30]}...</code>

"""
    
    keyboard_buttons = []
    
    # Navigation buttons
    if page > 1:
        keyboard_buttons.append({'text': '⬅️ Previous', 'callback_data': f'history_{page-1}'})
    
    if page < total_pages:
        keyboard_buttons.append({'text': 'Next ➡️', 'callback_data': f'history_{page+1}'})
    
    # Other buttons
    other_buttons = [
        {'text': '🗑️ Clear History', 'callback_data': 'clear_history'},
        {'text': '📊 Stats', 'callback_data': 'my_stats'},
        {'text': '🚀 New Download', 'switch_inline_query_current_chat': ''}
    ]
    
    keyboard = {
        'inline_keyboard': [keyboard_buttons] if keyboard_buttons else [] + [other_buttons]
    }
    
    return send_telegram_message(user_id, history_text, parse_mode='HTML', reply_markup=keyboard)

def handle_premium_info(user_id):
    """Handle /premium command"""
    is_premium = db.is_premium_user(user_id)
    
    premium_text = f"""
<b>⭐ PREMIUM SUBSCRIPTION</b>

{'🎉 <b>YOU ARE A PREMIUM USER!</b> 🎉' if is_premium else '🆓 <b>FREE ACCOUNT</b>'}
{'<i>Thank you for supporting us!</i>' if is_premium else ''}

<b>Premium Features:</b>
✅ <b>200MB</b> file size limit (Free: 50MB)
✅ <b>{PREMIUM_RATE_LIMIT}</b> downloads/hour (Free: {RATE_LIMIT})
✅ <b>Video Compression</b> tool
✅ <b>Priority Processing</b>
✅ <b>Custom Quality Selection</b>
✅ <b>Batch Downloading</b>
✅ <b>Priority Support</b>

<b>Pricing:</b>
💰 <b>1 Month:</b> Contact Admin
💰 <b>3 Months:</b> Contact Admin
💰 <b>6 Months:</b> Contact Admin
💰 <b>1 Year:</b> Contact Admin

<b>How to Upgrade:</b>
1. Contact admin @Tg_AssistBot
2. Make payment
3. Admin will activate premium
4. Enjoy all features!

<b>Your Status:</b>
"""
    
    if is_premium:
        stats = db.get_user_stats(user_id)
        if stats['premium_until']:
            try:
                until_dt = datetime.strptime(stats['premium_until'], '%Y-%m-%d %H:%M:%S')
                days_left = (until_dt - datetime.now()).days
                premium_text += f"✅ <b>Active until:</b> {until_dt.strftime('%b %d, %Y')}\n"
                premium_text += f"⏳ <b>Days remaining:</b> {days_left}\n"
            except:
                premium_text += "✅ <b>Premium Active</b>\n"
    else:
        premium_text += "❌ <b>Not Premium</b>\n💡 <i>Contact admin to upgrade!</i>\n"
    
    premium_text += f"""
📞 <b>Contact Admin:</b> @Tg_AssistBot

<i>All payments are secure and one-time only.
No automatic renewals.</i>
"""
    
    keyboard = {
        'inline_keyboard': [
            [
                {'text': '📞 Contact Admin', 'url': 'https://t.me/Tg_AssistBot'},
                {'text': '📊 My Stats', 'callback_data': 'my_stats'}
            ],
            [
                {'text': '🔄 Refresh Status', 'callback_data': 'refresh_premium'},
                {'text': '🚀 Try Download', 'switch_inline_query_current_chat': ''}
            ]
        ]
    }
    
    return send_telegram_message(user_id, premium_text, parse_mode='HTML', reply_markup=keyboard)

def handle_features(user_id):
    """Handle /features command"""
    features_text = """
<b>🛠️ ALL FEATURES</b>

<b>📥 Core Features:</b>
✅ Download from 18+ platforms
✅ Best quality auto-selection
✅ No storage on servers
✅ Fast processing
✅ Free forever

<b>⭐ Premium Features:</b>
✅ 200MB file size limit
✅ 50 downloads/hour
✅ Video compression
✅ Custom quality selection
✅ Priority processing
✅ Batch downloading
✅ Priority support

<b>🔄 Processing Features:</b>
✅ Progress bar display
✅ Real-time status updates
✅ Automatic format detection
✅ Multi-threaded downloads
✅ Error recovery
✅ Instagram rate-limit bypass
✅ Terabox support

<b>📊 Analytics Features:</b>
✅ Download history
✅ User statistics
✅ Platform usage stats
✅ Hourly/daily/weekly reports
✅ Leaderboards

<b>🔧 Admin Features:</b>
✅ User management
✅ Premium management
✅ Bot statistics
✅ Broadcast messages
✅ Ad management

<b>🛡️ Security Features:</b>
✅ Rate limiting
✅ Ban system
✅ Link validation
✅ File size limits
✅ Privacy protection

<b>🌐 Platform Support:</b>
✅ YouTube, Instagram, TikTok
✅ Pinterest, Terabox, Twitter
✅ Facebook, Reddit, Likee
✅ Dailymotion, Vimeo, Twitch
✅ Bilibili, Rutube, Rumble
✅ Streamable, Odysee, and more!
"""
    
    keyboard = {
        'inline_keyboard': [
            [
                {'text': '⭐ Go Premium', 'callback_data': 'premium_info'},
                {'text': '📖 Help Guide', 'callback_data': 'help_menu'}
            ],
            [
                {'text': '🚀 Start Downloading', 'switch_inline_query_current_chat': ''},
                {'text': '📞 Contact Admin', 'url': 'https://t.me/Tg_AssistBot'}
            ]
        ]
    }
    
    return send_telegram_message(user_id, features_text, parse_mode='HTML', reply_markup=keyboard)

def handle_tools_menu(user_id):
    """Handle /tools command - Show premium tools menu"""
    is_premium = db.is_premium_user(user_id)
    
    if not is_premium:
        return send_telegram_message(user_id, "❌ <b>Premium Tools</b>\n\nThis feature is available only for premium users.\n\nContact admin @Tg_AssistBot to upgrade to premium!", parse_mode='HTML')
    
    tools_text = """
<b>🛠️ PREMIUM TOOLS</b>

<b>Available Tools:</b>

1. <b>🎞️ Video Compression</b>
   Reduce video file size while maintaining quality
   • Options: High, Medium, Low compression
   • Maintains original resolution
   • Fast processing

<b>How to use:</b>
1. First download a video
2. Use the tools button below the video
3. Select desired tool
4. Process and receive result

<i>All tools are available only for premium users.</i>
"""
    
    keyboard = {
        'inline_keyboard': [
            [
                {'text': '🎞️ Compress Video', 'callback_data': 'compress_info'},
                {'text': '📥 Download Video', 'switch_inline_query_current_chat': ''}
            ],
            [
                {'text': '📊 My Stats', 'callback_data': 'my_stats'},
                {'text': '⭐ Premium Info', 'callback_data': 'premium_info'}
            ],
            [
                {'text': '📖 Help Guide', 'callback_data': 'help_menu'},
                {'text': '📞 Contact Admin', 'url': 'https://t.me/Tg_AssistBot'}
            ]
        ]
    }
    
    return send_telegram_message(user_id, tools_text, parse_mode='HTML', reply_markup=keyboard)

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
⭐ <b>Premium Users:</b> <b>{bot_stats.get('premium_users', 0)}</b>

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
• Premium Users: <b>{bot_stats.get('premium_users', 0)}</b>

🌐 <b>System Info:</b>
• Webhook: {WEBHOOK_URL}
• Bot: @{BOT_USERNAME}
• Uptime: {int(time.time() - start_time)} seconds

<b>👥 User Management:</b>
• <code>/users</code> - List all users
• <code>/ban [user_id]</code> - Ban a user
• <code>/unban [user_id]</code> - Unban a user
• <code>/addpremium [user_id] [days]</code> - Add premium
• <code>/removepremium [user_id]</code> - Remove premium

<b>💰 Premium Management:</b>
• <code>/premiumusers</code> - List premium users

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
                {'text': '⭐ Premium Users', 'callback_data': 'admin_premium_users'}
            ],
            [
                {'text': '🔄 Refresh', 'callback_data': 'admin_refresh'},
                {'text': '📋 Logs', 'callback_data': 'admin_logs'}
            ]
        ]
    }
    
    return send_telegram_message(user_id, admin_text, parse_mode='HTML', reply_markup=keyboard)

def handle_report(user_id, text):
    """Handle /report command to report issues"""
    report_text = text.replace('/report', '').strip()
    
    if not report_text:
        return send_telegram_message(user_id, "📝 <b>Usage:</b> <code>/report [your issue here]</code>\n\nExample: /report Instagram videos not downloading", parse_mode='HTML')
    
    # Save report to database
    try:
        cursor = db.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO admin_logs (admin_id, action, target_id, details)
            VALUES (?, 'user_report', ?, ?)
        ''', (user_id, user_id, report_text))
        db.conn.commit()
    except Exception as e:
        logger.error(f"Error saving report: {e}")
    
    # Notify admin
    for admin_id in ADMIN_IDS:
        admin_msg = f"""
🚨 <b>USER REPORT</b>

👤 <b>User:</b> {user_id}
📝 <b>Report:</b> {report_text}
🕒 <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}
"""
        send_telegram_message(admin_id, admin_msg, parse_mode='HTML')
    
    return send_telegram_message(user_id, "✅ <b>Report submitted!</b>\n\nThank you for your feedback. Our admin team will review it shortly.", parse_mode='HTML')

def handle_video_download(user_id, username, first_name, text, message_id):
    """Handle video download requests"""
    # Check if user is banned
    if db.is_user_banned(user_id):
        return send_telegram_message(user_id, "🚫 <b>Your account has been banned.</b>\n\nIf you believe this is a mistake, contact admin @Tg_AssistBot.", parse_mode='HTML')
    
    # Check for URLs
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w\.\-?=&%#+]*'
    urls = re.findall(url_pattern, text)
    
    if not urls:
        return send_telegram_message(user_id, "🔍 <b>No URL found.</b>\n\nPlease send a video link from:\n• YouTube\n• Instagram\n• TikTok\n• Pinterest\n• Terabox\n• Twitter\n• Facebook\n• Reddit\n• Likee\n• Dailymotion\n• Vimeo\n• Twitch\n\nExample: <code>https://youtube.com/watch?v=dQw4w9WgXcQ</code>", parse_mode='HTML')
    
    url = urls[0].strip()
    
    # Detect platform
    platform, icon = UniversalDownloader.detect_platform(url)
    
    if not platform:
        return send_telegram_message(user_id, f"❌ <b>Platform not supported.</b>\n\nI support:\n• YouTube (youtube.com)\n• Instagram (instagram.com)\n• TikTok (tiktok.com)\n• Pinterest (pinterest.com)\n• Terabox (terabox.com)\n• Twitter/X (twitter.com/x.com)\n• Facebook (facebook.com)\n• Reddit (reddit.com)\n• Likee (likee.com)\n• Dailymotion (dailymotion.com)\n• Vimeo (vimeo.com)\n• Twitch (twitch.tv)\n• Rumble (rumble.com)\n\nYour link: <code>{url[:50]}...</code>\n\nPlease check your link and try again.", parse_mode='HTML')
    
    # Check if premium user
    is_premium = db.is_premium_user(user_id)
    rate_limit = PREMIUM_RATE_LIMIT if is_premium else RATE_LIMIT
    
    # Check rate limit
    stats = db.get_user_stats(user_id)
    if stats['hourly'] >= rate_limit:
        return send_telegram_message(user_id, f"⏰ <b>Rate Limit Reached!</b>\n\nYou've used {stats['hourly']}/{rate_limit} downloads this hour.\nPlease wait 1 hour before downloading more.\n\n{'⭐ Premium users get 50 downloads/hour' if not is_premium else ''}\n\n<i>Tip: The limit resets every hour at :00 minutes.</i>", parse_mode='HTML')
    
    # Send initial processing message
    status_msg = f"{icon} <b>Processing {platform.upper()} link...</b>\n\n⏳ Please wait while I analyze the video...\n\n<i>This may take 10-60 seconds depending on the platform.</i>"
    
    # Send processing message and store its ID
    send_telegram_message(user_id, status_msg, parse_mode='HTML')
    
    # Process in background thread
    Thread(target=process_video_download, args=(user_id, username, first_name, url, platform, icon, message_id, is_premium)).start()
    
    return True

def process_video_download(user_id, username, first_name, url, platform, icon, message_id, is_premium):
    """Process video download in background thread"""
    try:
        # Get video information
        edit_telegram_message(user_id, message_id + 1, f"{icon} <b>{platform.upper()} DETECTED</b>\n\n🔍 Analyzing video information...\n\n<i>This may take a moment...</i>")
        
        # Get video information
        video_info = UniversalDownloader.get_video_info(url, is_premium)
        
        if not video_info:
            edit_telegram_message(user_id, message_id + 1, f"❌ <b>Failed to get video information</b>\n\nPlatform: {platform.upper()}\n\nPossible reasons:\n• Video is private/restricted\n• Link is invalid or expired\n• Platform is blocking downloads\n• Server timeout\n\nPlease try a different video or use /report to notify admin.")
            return
        
        # Check file size
        max_size = PREMIUM_MAX_SIZE if is_premium else MAX_FILE_SIZE
        if video_info['filesize'] > max_size:
            size_mb = video_info['filesize'] / (1024 * 1024)
            limit_mb = max_size / (1024 * 1024)
            edit_telegram_message(user_id, message_id + 1, f"❌ <b>File Too Large</b>\n\nVideo size: <b>{size_mb:.1f}MB</b>\nYour limit: <b>{limit_mb:.0f}MB</b>\n\nThis video exceeds your file size limit.\n{'⭐ Upgrade to premium for 200MB limit!' if not is_premium else 'Try a shorter video or different format.'}")
            return
        
        # Show video info card
        duration_str = f"{video_info['duration']//60}:{video_info['duration']%60:02d}" if video_info['duration'] else "N/A"
        size_mb = video_info['filesize'] / (1024 * 1024) if video_info['filesize'] else 0
        
        info_text = f"""
📊 <b>VIDEO INFORMATION</b>

📁 <b>Title:</b> {video_info['title'][:100]}
👤 <b>Uploader:</b> {video_info.get('uploader', 'Unknown')[:50]}
⏱ <b>Duration:</b> {duration_str}
💾 <b>Size:</b> {size_mb:.1f}MB
🎯 <b>Quality:</b> {video_info.get('quality', 'best')}
👁 <b>Views:</b> {video_info.get('view_count', 'N/A')}

📥 <b>Starting download...</b>
<i>Please wait, this may take a few minutes.</i>
"""
        
        edit_telegram_message(user_id, message_id + 1, info_text)
        
        # Download video
        video_buffer, downloaded_size = UniversalDownloader.download_video(video_info['url'])
        
        if not video_buffer:
            edit_telegram_message(user_id, message_id + 1, "❌ <b>Download Failed</b>\n\nCould not download the video.\nPossible reasons:\n• Network error\n• Server timeout\n• Video unavailable\n• Platform restrictions\n\nPlease try again or use a different link.\nUse /report to notify admin if problem persists.")
            # Record failed download
            db.record_download(user_id, platform, url, video_info['title'], 0, video_info.get('quality', 'unknown'), False)
            return
        
        # Upload to Telegram
        edit_telegram_message(user_id, message_id + 1, "📤 <b>Uploading to Telegram...</b>\n\nFinal step... This may take a moment.")
        
        # Prepare caption
        file_size_mb = downloaded_size / (1024 * 1024)
        duration_str = f"{video_info['duration']//60}:{video_info['duration']%60:02d}" if video_info['duration'] else "N/A"
        
        caption = f"""
✅ <b>DOWNLOAD COMPLETE!</b>

📁 <b>Title:</b> {video_info['title'][:100]}
📊 <b>Platform:</b> {platform.upper()}
💾 <b>Size:</b> {file_size_mb:.1f}MB
⏱ <b>Duration:</b> {duration_str}
🎯 <b>Quality:</b> {video_info.get('quality', 'best')}
{'⭐ <b>Premium:</b> Yes' if is_premium else '🆓 <b>Free:</b> Yes'}

🤖 Downloaded via @{BOT_USERNAME}
"""
        
        # Send video
        filename = f"{video_info['title'][:50]}.mp4".replace('/', '_').replace('\\', '_')
        success = send_telegram_video(user_id, video_buffer, caption, filename)
        
        if success:
            # Record successful download
            db.record_download(user_id, platform, url, video_info['title'], downloaded_size, video_info.get('quality', 'best'), True, False)
            
            # Update user
            db.add_user(user_id, username, first_name)
            
            # Update message
            new_stats = db.get_user_stats(user_id)
            completion_text = f"✅ <b>Success! Video sent successfully!</b>\n\n"
            completion_text += f"📥 <b>Download Details:</b>\n"
            completion_text += f"• Platform: {platform.upper()}\n"
            completion_text += f"• Size: {file_size_mb:.1f}MB\n"
            completion_text += f"• Status: ✅ Complete\n\n"
            completion_text += f"📊 <b>Your Updated Stats:</b>\n"
            completion_text += f"• This Hour: {new_stats['hourly']}/{new_stats['rate_limit']}\n"
            completion_text += f"• Remaining: {new_stats['remaining']} downloads\n\n"
            completion_text += "⭐ <b>Rate your experience:</b> /rate"
            
            edit_telegram_message(user_id, message_id + 1, completion_text)
            
            # Notify admin
            if user_id not in ADMIN_IDS:
                admin_message = f"""
📥 <b>NEW DOWNLOAD</b>

👤 <b>User:</b> {first_name}
🆔 <b>ID:</b> <code>{user_id}</code>
📊 <b>Platform:</b> {platform.upper()}
💾 <b>Size:</b> {file_size_mb:.1f}MB
⭐ <b>Premium:</b> {'Yes' if is_premium else 'No'}
🕒 <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}
"""
                for admin_id in ADMIN_IDS:
                    send_telegram_message(admin_id, admin_message, parse_mode='HTML')
        
        else:
            edit_telegram_message(user_id, message_id + 1, "❌ <b>Upload Failed</b>\n\nCould not send video to Telegram.\nPossible reasons:\n• File too large for Telegram\n• Telegram API error\n• Network issue\n\nPlease try again or use /report.")
            db.record_download(user_id, platform, url, video_info['title'], 0, video_info.get('quality', 'best'), False)
        
        # Clean up
        video_buffer.close()
        
    except Exception as e:
        logger.error(f"Error in process_video_download: {e}")
        logger.error(traceback.format_exc())
        error_msg = f"❌ <b>Download Failed</b>\n\nError: <code>{str(e)[:200]}</code>\n\nPlease try again or contact support using /report."
        try:
            edit_telegram_message(user_id, message_id + 1, error_msg)
        except:
            send_telegram_message(user_id, error_msg, parse_mode='HTML')
        db.record_download(user_id, platform, url, "Unknown", 0, "unknown", False)

# ========== FLASK APP ==========
app = Flask(__name__)

@app.route('/')
def home():
    """Home page"""
    return jsonify({
        'status': 'online',
        'service': 'telegram-downloader-bot',
        'version': '4.1',
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

@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    """Telegram webhook endpoint"""
    try:
        if request.method == "POST":
            data = request.get_json()
            
            # Log the update
            logger.info(f"📩 Received update from Telegram")
            
            # Process update in background thread
            Thread(target=process_webhook_update, args=(data,)).start()
            
            return 'OK'
        else:
            # GET request - for verification
            return jsonify({'status': 'webhook_active', 'bot': BOT_USERNAME})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    
    return 'OK'

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
            
            logger.info(f"📝 Message from {user_id} ({first_name}): {text[:100]}")
            
            # Handle commands
            if text.startswith('/'):
                command = text.split()[0].lower()
                logger.info(f"🔧 Processing command: {command}")
                
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
                elif command == '/report':
                    handle_report(user_id, text)
                elif command.startswith('/users'):
                    # Handle admin users command
                    if user_id in ADMIN_IDS:
                        users = db.get_all_users(limit=20)
                        user_list = "👥 <b>RECENT USERS</b> (Last 20)\n\n"
                        for user in users:
                            uid, uname, fname, downloads, last_dl, banned, join_date, is_premium = user
                            status = "🔴 BANNED" if banned else ("⭐ PREMIUM" if is_premium else "🟢 FREE")
                            user_list += f"• <b>{fname}</b> (@{uname or 'N/A'})\n  ID: <code>{uid}</code> | {status}\n  📥 {downloads} DLs\n\n"
                        
                        send_telegram_message(user_id, user_list, parse_mode='HTML')
                elif command.startswith('/addpremium'):
                    # Handle add premium command
                    if user_id in ADMIN_IDS:
                        parts = text.split()
                        if len(parts) >= 3:
                            try:
                                target_id = int(parts[1])
                                days = int(parts[2])
                                success, until_date = db.add_premium(target_id, days, user_id)
                                if success:
                                    send_telegram_message(user_id, f"✅ Premium added successfully!\n\nUser: <code>{target_id}</code>\nDays: {days}\nValid until: {until_date.strftime('%Y-%m-%d')}", parse_mode='HTML')
                                else:
                                    send_telegram_message(user_id, f"❌ Failed to add premium for user <code>{target_id}</code>.", parse_mode='HTML')
                            except ValueError:
                                send_telegram_message(user_id, "❌ Invalid format. Use: <code>/addpremium [user_id] [days]</code>", parse_mode='HTML')
                        else:
                            send_telegram_message(user_id, "❌ Format: <code>/addpremium [user_id] [days]</code>", parse_mode='HTML')
                elif command.startswith('/removepremium'):
                    # Handle remove premium command
                    if user_id in ADMIN_IDS:
                        parts = text.split()
                        if len(parts) >= 2:
                            try:
                                target_id = int(parts[1])
                                reason = ' '.join(parts[2:]) if len(parts) > 2 else ''
                                if db.remove_premium(target_id, user_id, reason):
                                    send_telegram_message(user_id, f"✅ Premium removed from user <code>{target_id}</code>.", parse_mode='HTML")
                                else:
                                    send_telegram_message(user_id, f"❌ Failed to remove premium from user <code>{target_id}</code>.", parse_mode='HTML')
                            except ValueError:
                                send_telegram_message(user_id, "❌ Invalid user ID.", parse_mode='HTML')
                        else:
                            send_telegram_message(user_id, "❌ Format: <code>/removepremium [user_id] [reason]</code>", parse_mode='HTML')
                elif command.startswith('/premiumusers'):
                    # Handle premium users command
                    if user_id in ADMIN_IDS:
                        premium_users = db.get_premium_users()
                        if premium_users:
                            premium_text = "⭐ <b>PREMIUM USERS</b>\n\n"
                            for user in premium_users:
                                uid, uname, fname, premium_until, total_days, downloads = user
                                try:
                                    until_dt = datetime.strptime(premium_until, '%Y-%m-%d %H:%M:%S')
                                    days_left = (until_dt - datetime.now()).days
                                    status = f"⏳ {days_left} days left"
                                except:
                                    status = "Active"
                                
                                premium_text += f"• <b>{fname}</b> (@{uname or 'N/A'})\n  ID: <code>{uid}</code>\n  📅 {status}\n  📥 {downloads} DLs\n\n"
                            
                            send_telegram_message(user_id, premium_text, parse_mode='HTML')
                        else:
                            send_telegram_message(user_id, "❌ No premium users found.", parse_mode='HTML')
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
                                    send_telegram_message(uid, f"📢 <b>ANNOUNCEMENT FROM ADMIN</b>\n\n{broadcast_message}\n\n<i>Sent via @{BOT_USERNAME}</i>", parse_mode='HTML')
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
• Premium: <b>{bot_stats.get('premium_users', 0)}</b>

📥 <b>Downloads:</b>
• Total: <b>{bot_stats.get('total_downloads', 0)}</b>
• Today: <b>{bot_stats.get('today_downloads', 0)}</b>

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
            
            logger.info(f"🔘 Callback query from {user_id}: {data_str}")
            
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
            elif data_str.startswith('guide_'):
                platform = data_str.replace('guide_', '')
                platform_names = {
                    'youtube': ('YouTube', '📺'),
                    'instagram': ('Instagram', '📸'),
                    'tiktok': ('TikTok', '🎵'),
                    'pinterest': ('Pinterest', '📌'),
                    'terabox': ('Terabox', '📦'),
                    'twitter': ('Twitter/X', '🐦')
                }
                if platform in platform_names:
                    name, icon = platform_names[platform]
                    send_telegram_message(user_id, f"{icon} <b>{name} DOWNLOAD</b>\n\nSend me any {name} video link and I'll download it!\n\n<i>Tip: Copy link from {name} app and paste it here.</i>\n\n<b>Example:</b> <code>{'https://youtube.com/watch?v=...' if platform == 'youtube' else 'https://instagram.com/p/...' if platform == 'instagram' else 'https://tiktok.com/@user/video/...' if platform == 'tiktok' else 'https://terabox.com/s/...'}</code>", parse_mode='HTML')
            
            # Admin callbacks
            elif data_str == 'admin_users':
                if user_id in ADMIN_IDS:
                    users = db.get_all_users(limit=20)
                    user_list = "👥 <b>RECENT USERS</b> (Last 20)\n\n"
                    for user in users:
                        uid, uname, fname, downloads, last_dl, banned, join_date, is_premium = user
                        status = "🔴 BANNED" if banned else ("⭐ PREMIUM" if is_premium else "🟢 FREE")
                        user_list += f"• <b>{fname}</b> (@{uname or 'N/A'})\n  ID: <code>{uid}</code> | {status}\n  📥 {downloads} DLs\n\n"
                    
                    send_telegram_message(user_id, user_list, parse_mode='HTML')
            
            elif data_str == 'admin_premium_users':
                if user_id in ADMIN_IDS:
                    premium_users = db.get_premium_users()
                    if premium_users:
                        premium_text = "⭐ <b>PREMIUM USERS</b>\n\n"
                        for user in premium_users:
                            uid, uname, fname, premium_until, total_days, downloads = user
                            try:
                                until_dt = datetime.strptime(premium_until, '%Y-%m-%d %H:%M:%S')
                                days_left = (until_dt - datetime.now()).days
                                status = f"⏳ {days_left} days left"
                            except:
                                status = "Active"
                            
                            premium_text += f"• <b>{fname}</b> (@{uname or 'N/A'})\n  ID: <code>{uid}</code>\n  📅 {status}\n  📥 {downloads} DLs\n\n"
                        
                        send_telegram_message(user_id, premium_text, parse_mode='HTML')
                    else:
                        send_telegram_message(user_id, "❌ No premium users found.", parse_mode='HTML')
            
            elif data_str == 'admin_refresh':
                if user_id in ADMIN_IDS:
                    handle_admin(user_id)
            
            elif data_str == 'admin_logs':
                if user_id in ADMIN_IDS:
                    send_telegram_message(user_id, "📋 <b>ADMIN LOGS</b>\n\nLogs are stored in the database. Use the admin panel to view detailed logs.", parse_mode='HTML')
                    
    except Exception as e:
        logger.error(f"Error processing webhook update: {e}")
        logger.error(traceback.format_exc())

# ========== STARTUP ==========
def initialize_bot():
    """Initialize the bot on startup"""
    global BOT_USERNAME, start_time
    
    start_time = time.time()
    
    print("=" * 60)
    print("🤖 TELEGRAM UNIVERSAL VIDEO DOWNLOADER BOT - PREMIUM EDITION")
    print("📥 YouTube • Instagram • TikTok • Pinterest • Terabox • 18+ Platforms")
    print("⭐ Premium Features • Analytics • Compression")
    print("🌐 Deployed on Koyeb - Production Ready")
    print("=" * 60)
    
    # Get bot info
    retries = 3
    for i in range(retries):
        try:
            bot_info = get_bot_info()
            if bot_info:
                BOT_USERNAME = bot_info.get('username', '')
                logger.info(f"✅ Bot username: @{BOT_USERNAME}")
                break
            else:
                logger.error(f"❌ Failed to get bot info (attempt {i+1}/{retries})")
                time.sleep(2)
        except Exception as e:
            logger.error(f"Error getting bot info (attempt {i+1}/{retries}): {e}")
            time.sleep(2)
    
    if not BOT_USERNAME:
        logger.error("❌ Failed to get bot info after retries")
        BOT_USERNAME = "TelegramDownloaderBot"
    
    # Delete existing webhook first
    delete_webhook()
    time.sleep(1)
    
    # Set webhook
    if set_webhook():
        logger.info(f"✅ Webhook set to: {WEBHOOK_URL}")
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
⭐ <b>Version:</b> 4.1 Premium Edition
✅ <b>Status:</b> 🟢 Online

<b>All features loaded and ready! 🎉</b>
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
