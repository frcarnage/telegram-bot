#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Face Swap Bot v3.1
A comprehensive Telegram bot for face swapping with admin controls, statistics, and web interface
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
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', 'https://informal-sandie-1carnage1-fb1959f9.koyeb.app/')
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
WAITING_FOR_SOURCE = 1
WAITING_FOR_TARGET = 2

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
active_swaps: Dict[int, Dict] = {}  # chat_id -> swap info
user_data: Dict[int, Dict] = {}     # chat_id -> user session data

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
    
    # Create indexes for better performance
    c.execute('CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_swaps_user_date ON swaps_history(user_id, swap_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)')
    
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
def encrypt_data(data: Any) -> str:
    """Generate SHA256 hash of data"""
    return hashlib.sha256(str(data).encode()).hexdigest()

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

def format_time(seconds: float) -> str:
    """Format seconds to human readable time"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"

# ========== USER MANAGEMENT FUNCTIONS ==========
def register_user(user_id: int, username: str, first_name: str, last_name: str) -> bool:
    """Register a new user or update existing user"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check if user exists
    c.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    is_new = c.fetchone() is None
    
    # Calculate data hash
    data_hash = encrypt_data(f"{user_id}{username}{first_name}{last_name}")
    
    # Insert or update user
    c.execute('''INSERT OR REPLACE INTO users 
        (user_id, username, first_name, last_name, last_active, data_hash)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)''',
        (user_id, username, first_name, last_name, data_hash))
    
    conn.commit()
    conn.close()
    
    # Notify admin for new users
    if is_new:
        notify_admin_new_user(user_id, username, first_name, last_name)
        logger.info(f"New user registered: {user_id} (@{username})")
    
    return is_new

def notify_admin_new_user(user_id: int, username: str, first_name: str, last_name: str) -> None:
    """Notify admin about new user registration"""
    try:
        msg = f"""🎉 <b>NEW USER REGISTERED</b>

🆔 ID: <code>{user_id}</code>
👤 Username: @{username or 'N/A'}
📛 Name: {first_name} {last_name or ''}
📊 Total Users: {get_total_users()}
🕒 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        
        bot.send_message(ADMIN_ID, msg, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

def get_total_users() -> int:
    """Get total number of registered users"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    count = c.fetchone()[0]
    conn.close()
    return count

def get_active_users_count(days: int = 7) -> int:
    """Get number of active users in last N days"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"SELECT COUNT(*) FROM users WHERE last_active >= datetime('now', '-{days} days')")
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
        
        # Update swap's favorite status
        c.execute('UPDATE swaps_history SET is_favorite = 1 WHERE id = ?', (swap_id,))
        
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
    return report_id

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

# ========== FLASK ROUTES ==========
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Face Swap Bot - Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 40px;
            max-width: 800px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            backdrop-filter: blur(10px);
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        
        .header h1 {
            color: #667eea;
            font-size: 2.5rem;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 15px;
        }
        
        .header p {
            color: #666;
            font-size: 1.1rem;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: #f8f9fa;
            border-radius: 15px;
            padding: 20px;
            text-align: center;
            transition: transform 0.3s ease;
            border: 2px solid transparent;
        }
        
        .stat-card:hover {
            transform: translateY(-5px);
            border-color: #667eea;
        }
        
        .stat-card .value {
            font-size: 2rem;
            font-weight: bold;
            color: #667eea;
            margin: 10px 0;
        }
        
        .stat-card .label {
            color: #666;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .badge {
            display: inline-block;
            padding: 8px 20px;
            border-radius: 20px;
            font-weight: 600;
            margin-bottom: 20px;
        }
        
        .badge-success {
            background: #d4edda;
            color: #155724;
        }
        
        .badge-error {
            background: #f8d7da;
            color: #721c24;
        }
        
        .info-box {
            background: #f8f9fa;
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 20px;
        }
        
        .info-item {
            display: flex;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid #e0e0e0;
        }
        
        .info-item:last-child {
            border-bottom: none;
        }
        
        .info-label {
            font-weight: 600;
            color: #555;
        }
        
        .info-value {
            color: #667eea;
            font-weight: 700;
        }
        
        .endpoints {
            margin-top: 30px;
        }
        
        .endpoints h3 {
            color: #667eea;
            margin-bottom: 15px;
        }
        
        .endpoint-list {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 15px;
        }
        
        .endpoint {
            font-family: monospace;
            padding: 8px;
            margin: 5px 0;
            background: white;
            border-radius: 5px;
            border-left: 4px solid #667eea;
        }
        
        .footer {
            text-align: center;
            margin-top: 30px;
            color: #999;
            font-size: 0.9rem;
            padding-top: 20px;
            border-top: 1px solid #eee;
        }
        
        @media (max-width: 768px) {
            .container {
                padding: 20px;
            }
            
            .header h1 {
                font-size: 2rem;
                flex-direction: column;
                gap: 10px;
            }
            
            .stats-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>
                <span>🤖</span>
                Face Swap Bot
                <span>🎭</span>
            </h1>
            <p>Advanced Face Swapping Telegram Bot with Real-time Dashboard</p>
            <div class="badge badge-success">{{ status }}</div>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="label">Total Users</div>
                <div class="value">{{ total_users }}</div>
            </div>
            
            <div class="stat-card">
                <div class="label">Active (24h)</div>
                <div class="value">{{ active_24h }}</div>
            </div>
            
            <div class="stat-card">
                <div class="label">Total Swaps</div>
                <div class="value">{{ total_swaps }}</div>
            </div>
            
            <div class="stat-card">
                <div class="label">Success Rate</div>
                <div class="value">{{ success_rate }}%</div>
            </div>
        </div>
        
        <div class="info-box">
            <div class="info-item">
                <span class="info-label">Bot Version</span>
                <span class="info-value">3.1</span>
            </div>
            <div class="info-item">
                <span class="info-label">Server Time</span>
                <span class="info-value">{{ server_time }}</span>
            </div>
            <div class="info-item">
                <span class="info-label">Uptime</span>
                <span class="info-value">{{ uptime }}</span>
            </div>
            <div class="info-item">
                <span class="info-label">Active Sessions</span>
                <span class="info-value">{{ active_sessions }}</span>
            </div>
        </div>
        
        <div class="endpoints">
            <h3>📊 API Endpoints</h3>
            <div class="endpoint-list">
                <div class="endpoint">GET /health/hunter - Health Check</div>
                <div class="endpoint">GET /stats/hunter - Statistics</div>
                <div class="endpoint">GET /users/hunter - User Data</div>
                <div class="endpoint">GET /status - Bot Status</div>
            </div>
        </div>
        
        <div class="footer">
            <p>Created with ❤️ by @PokiePy | Powered by Flask & Koyeb</p>
            <p>System Time: {{ timestamp }}</p>
        </div>
    </div>
    
    <script>
        // Auto-refresh every 60 seconds
        setTimeout(() => {
            location.reload();
        }, 60000);
        
        // Update timestamp every second
        function updateTime() {
            const now = new Date();
            document.querySelector('.footer p:last-child').textContent = 
                `System Time: ${now.toLocaleString()}`;
        }
        setInterval(updateTime, 1000);
    </script>
</body>
</html>'''

@app.route('/')
def home():
    """Main dashboard page"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Get statistics
        c.execute('SELECT COUNT(*) FROM swaps_history')
        total_swaps = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "success"')
        success_swaps = c.fetchone()[0] or 0
        
        # Calculate success rate
        success_rate = round((success_swaps / max(1, total_swaps)) * 100, 1)
        
        conn.close()
        
        # Render template
        return render_template_string(
            HTML_TEMPLATE,
            status="🟢 ONLINE",
            total_users=get_total_users(),
            active_24h=get_active_users_count(1),
            total_swaps=total_swaps,
            success_rate=success_rate,
            server_time=datetime.now().strftime('%H:%M:%S'),
            uptime=format_time(time.time() - start_time),
            active_sessions=len(user_data),
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
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
            server_time="N/A",
            uptime="N/A",
            active_sessions=0,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )

@app.route('/health/hunter')
def health_hunter():
    """Health check endpoint for monitoring"""
    try:
        health_data = {
            "status": "healthy",
            "service": "Face Swap Bot",
            "version": "3.1",
            "bot": "running",
            "database": "connected",
            "webhook": "active" if WEBHOOK_URL else "polling",
            "metrics": {
                "total_users": get_total_users(),
                "active_24h": get_active_users_count(1),
                "active_7d": get_active_users_count(7),
                "banned_users": len(BANNED_USERS),
                "active_swaps": len(active_swaps),
                "active_sessions": len(user_data)
            },
            "timestamp": datetime.now().isoformat(),
            "uptime": int(time.time() - start_time)
        }
        return jsonify(health_data), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/stats/hunter')
def stats_hunter():
    """Detailed statistics endpoint"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Swap statistics
        c.execute('SELECT COUNT(*) FROM swaps_history')
        total_swaps = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "success"')
        success_swaps = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM swaps_history WHERE status = "failed"')
        failed_swaps = c.fetchone()[0] or 0
        
        # Other statistics
        c.execute('SELECT COUNT(*) FROM reports WHERE status = "pending"')
        pending_reports = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM favorites')
        total_favorites = c.fetchone()[0] or 0
        
        # Average processing time
        c.execute('SELECT AVG(processing_time) FROM swaps_history WHERE status = "success"')
        avg_time = c.fetchone()[0] or 0
        
        conn.close()
        
        # Calculate rates
        success_rate = round((success_swaps / max(1, total_swaps)) * 100, 2)
        
        stats_data = {
            "users": {
                "total": get_total_users(),
                "active_24h": get_active_users_count(1),
                "active_7d": get_active_users_count(7),
                "banned": len(BANNED_USERS),
                "verified": get_active_users_count(30)  # Approximate
            },
            "swaps": {
                "total": total_swaps,
                "successful": success_swaps,
                "failed": failed_swaps,
                "success_rate": success_rate,
                "average_time": round(avg_time, 2),
                "active": len(active_swaps)
            },
            "engagement": {
                "favorites": total_favorites,
                "pending_reports": pending_reports,
                "active_sessions": len(user_data)
            },
            "performance": {
                "response_time": 0.1,  # Placeholder
                "api_status": "operational",
                "database_latency": "low"
            },
            "timestamp": datetime.now().isoformat()
        }
        
        return jsonify(stats_data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/users/hunter')
def users_hunter():
    """User data endpoint"""
    try:
        users = get_all_users(limit=100)
        
        user_list = []
        for user in users:
            user_list.append({
                "user_id": user[0],
                "username": user[1] or "N/A",
                "name": f"{user[2]} {user[3] or ''}".strip(),
                "joined": user[4],
                "last_active": user[5],
                "banned": bool(user[6]),
                "verified": bool(user[7]),
                "stats": {
                    "total_swaps": user[8],
                    "successful": user[9],
                    "failed": user[10]
                }
            })
        
        return jsonify({
            "total": len(user_list),
            "users": user_list,
            "timestamp": datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/status')
def status_page():
    """Simple status page"""
    return jsonify({
        "status": "online",
        "bot": "@face_swap_bot",
        "time": datetime.now().isoformat(),
        "users": get_total_users(),
        "uptime": int(time.time() - start_time)
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram webhook endpoint"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        
        # Process update in a separate thread
        threading.Thread(target=bot.process_new_updates, args=([update],)).start()
        
        return '', 200
    
    return 'Bad request', 400

@app.route('/export/users')
def export_users_csv():
    """Export users to CSV (admin only)"""
    # Simple authentication check
    token = request.args.get('token')
    if token != hashlib.sha256(BOT_TOKEN.encode()).hexdigest()[:16]:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        users = get_all_users(limit=1000)
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'User ID', 'Username', 'First Name', 'Last Name',
            'Join Date', 'Last Active', 'Banned', 'Verified',
            'Total Swaps', 'Successful', 'Failed'
        ])
        
        # Write data
        for user in users:
            writer.writerow(user[:11])
        
        # Prepare response
        output.seek(0)
        mem = io.BytesIO()
        mem.write(output.getvalue().encode('utf-8'))
        mem.seek(0)
        output.close()
        
        return send_file(
            mem,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'users_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== BOT HANDLERS ==========
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Handle /start and /help commands"""
    user_id = message.from_user.id
    
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
🔄 <b>Version:</b> 3.1"""
    
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

@bot.callback_query_handler(func=lambda call: call.data == "start_swap")
def start_swap_callback(call):
    """Handle start swap callback"""
    start_swap_command(call.message)

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
    
    # Initialize swap session
    user_data[chat_id] = {
        'state': WAITING_FOR_SOURCE,
        'user_id': user_id,
        'start_time': time.time()
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

@bot.message_handler(commands=['cancel'])
def cancel_swap_command(message):
    """Cancel the current swap"""
    chat_id = message.chat.id
    
    if chat_id in user_data:
        del user_data[chat_id]
        
        if chat_id in active_swaps:
            del active_swaps[chat_id]
        
        cancel_text = """❌ <b>Swap Cancelled</b>

Your face swap session has been cancelled.

💡 You can start a new swap anytime with:
• /swap command, or
• Clicking "Start Swap" button

We hope to see you again soon! 🎭"""
        
        bot.reply_to(message, cancel_text, parse_mode='HTML')
    else:
        bot.reply_to(message, "⚠️ No active swap to cancel. Use /swap to start a new one.")

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
📈 <b>Activity Level:</b> {'New User' if total == 0 else 'Active' if total > 5 else 'Casual'}

💡 <b>Tip:</b> The more you swap, the better you get at choosing good photos!"""
        
        # Add progress bar for swaps
        if total > 0:
            progress = min(total * 2, 100)  # Simple progress calculation
            bar = generate_progress_bar(progress)
            stats_text += f"\n\n📊 <b>Progress:</b> [{bar}] {progress}%"
        
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

🎭 <b>Ready to start?</b> Use /swap to create your first face swap!

💡 <b>What you'll see here:</b>
• List of all your swaps
• Success/failure status
• Processing time
• Dates of each swap"""
        
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
    
    history_text += "\n\n💡 <b>Tip:</b> Successful swaps usually have clear, well-lit photos."
    
    bot.reply_to(message, history_text, parse_mode='HTML')

@bot.message_handler(commands=['report'])
def report_content_command(message):
    """Handle report command"""
    report_text = """🚨 <b>Report Inappropriate Content</b>

If you encounter any inappropriate content or have concerns about a swap, you can report it here.

📝 <b>How to Report:</b>
1. Find the Swap ID (shown in swap results)
2. Use the format: <code>Swap_ID Reason</code>
3. Send it as a message

📋 <b>Example:</b>
<code>123 Inappropriate content</code>
<code>456 Copyright violation</code>

⚠️ <b>Important:</b>
• Only report genuine issues
• False reports may lead to action
• We review all reports within 24 hours

🙏 <b>Thank you for helping keep our community safe!</b>"""
    
    bot.reply_to(message, report_text, parse_mode='HTML')

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    """Handle photo uploads for face swapping"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Check if banned
    if user_id in BANNED_USERS:
        bot.reply_to(message, "🚫 Your account has been banned.")
        return
    
    # Get photo file
    file_id = message.photo[-1].file_id
    file_info = bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
    
    try:
        # Download photo
        response = requests.get(file_url, timeout=10)
        if response.status_code != 200:
            raise Exception(f"Failed to download photo: {response.status_code}")
        
        photo_data = response.content
        
        # Handle based on swap state
        if chat_id not in user_data:
            # Starting new swap
            user_data[chat_id] = {
                'state': WAITING_FOR_TARGET,
                'source_photo': photo_data,
                'user_id': user_id,
                'start_time': time.time()
            }
            
            bot.reply_to(message, """✅ <b>Source Photo Received!</b>

📸 <b>Step 2 of 2:</b> Send the <b>TARGET</b> photo
(This is the photo where the face will be placed)

💡 <b>Tips for target photo:</b>
✓ Clear, good quality image
✓ Face should be visible
✓ Similar lighting to source works best

⏳ <b>Processing will start immediately after you send the target photo.</b>

👉 <b>Please send the TARGET photo now...</b>""", parse_mode='HTML')
            
        elif user_data[chat_id]['state'] == WAITING_FOR_TARGET:
            # Got target photo, start processing
            user_data[chat_id]['target_photo'] = photo_data
            user_data[chat_id]['state'] = 'processing'
            
            # Start processing
            process_face_swap(chat_id, message)
            
        else:
            # Already processing or invalid state
            bot.reply_to(message, """⚠️ <b>Please wait</b>

Your swap is currently being processed. Please wait for it to complete before sending more photos.

⏳ If it's taking too long, you can:
• Wait a bit more
• Use /cancel and start over
• Contact support if problem persists""", parse_mode='HTML')
            
    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        bot.reply_to(message, "❌ <b>Error processing photo</b>\n\nPlease try again with a different photo or try again later.", parse_mode='HTML')
        
        # Clean up session
        if chat_id in user_data:
            del user_data[chat_id]

def process_face_swap(chat_id, message):
    """Process the face swap with progress updates"""
    try:
        user_session = user_data[chat_id]
        user_id = user_session['user_id']
        
        # Create progress message
        progress_msg = bot.reply_to(message, """🔄 <b>Processing Face Swap...</b>

[░░░░░░░░░░] 0%
⏱️ Estimated: Calculating...

⚙️ <b>Steps:</b>
1. Analyzing photos
2. Detecting faces
3. Swapping faces
4. Finalizing result

💡 <b>Please wait, this may take 15-30 seconds...</b>""", parse_mode='HTML')
        
        # Add to active swaps
        active_swaps[chat_id] = {
            'progress': 0,
            'status': 'Initializing...',
            'start_time': time.time(),
            'progress_msg_id': progress_msg.message_id
        }
        
        # Simulate progress updates (you would replace this with actual API progress)
        for progress in [10, 25, 45, 65, 85]:
            time.sleep(1.5)
            
            if chat_id not in active_swaps:
                return
            
            active_swaps[chat_id]['progress'] = progress
            bar = generate_progress_bar(progress)
            est_time = estimate_time(active_swaps[chat_id]['start_time'], progress)
            
            status_text = "Analyzing faces" if progress < 30 else \
                         "Swapping faces" if progress < 70 else \
                         "Finalizing result"
            
            try:
                bot.edit_message_text(
                    f"""🔄 <b>Processing Face Swap...</b>

[{bar}] {progress}%
⏱️ Estimated: {est_time}

⚙️ <b>Status:</b> {status_text}
🎯 <b>Progress:</b> {progress}% complete

💡 <b>Almost there...</b>""",
                    chat_id,
                    progress_msg.message_id,
                    parse_mode='HTML'
                )
            except:
                pass
        
        # Prepare API request
        source_b64 = base64.b64encode(user_session['source_photo']).decode('utf-8')
        target_b64 = base64.b64encode(user_session['target_photo']).decode('utf-8')
        
        api_data = {
            'source': source_b64,
            'target': target_b64,
            'security': {
                'token': FACE_SWAP_API_TOKEN,
                'type': 'invisible',
                'id': 'deepswapper'
            }
        }
        
        # Make API request
        response = requests.post(
            FACE_SWAP_API_URL,
            json=api_data,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        processing_time = time.time() - user_session['start_time']
        
        if response.status_code == 200:
            result_data = response.json()
            
            if 'result' in result_data and result_data['result']:
                # Decode result image
                result_image = base64.b64decode(result_data['result'])
                
                # Save result
                os.makedirs('results', exist_ok=True)
                filename = f"swap_{user_id}_{int(time.time())}.png"
                filepath = os.path.join('results', filename)
                
                with open(filepath, 'wb') as f:
                    f.write(result_image)
                
                # Update progress to 100%
                active_swaps[chat_id]['progress'] = 100
                
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
                markup.add(
                    types.InlineKeyboardButton("📊 View Stats", callback_data="my_stats"),
                    types.InlineKeyboardButton("🚨 Report Issue", callback_data=f"report_{swap_id}")
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
                
                logger.info(f"Swap successful: User={user_id}, Time={processing_time:.2f}s")
                
            else:
                raise Exception("No result in API response")
                
        else:
            raise Exception(f"API error: {response.status_code}")
            
    except Exception as e:
        logger.error(f"Face swap error: {e}")
        
        processing_time = time.time() - user_session.get('start_time', time.time())
        
        # Update progress message
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
                active_swaps[chat_id]['progress_msg_id'],
                parse_mode='HTML'
            )
        except:
            pass
        
        # Add to history as failed
        add_swap_history(user_id, "failed", processing_time)
        update_user_stats(user_id, False)
        
    finally:
        # Clean up
        if chat_id in user_data:
            del user_data[chat_id]
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
            
            # Update message caption
            if call.message.caption:
                new_caption = call.message.caption + "\n\n⭐ <b>Saved to Favorites!</b>"
                bot.edit_message_caption(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    caption=new_caption,
                    parse_mode='HTML',
                    reply_markup=call.message.reply_markup
                )
        else:
            bot.answer_callback_query(call.id, "⚠️ Already in favorites!")
            
    except Exception as e:
        logger.error(f"Favorite error: {e}")
        bot.answer_callback_query(call.id, "❌ Error saving favorite")

@bot.callback_query_handler(func=lambda call: call.data.startswith('report_'))
def report_swap_callback(call):
    """Report a swap"""
    swap_id = call.data.split('_')[1]
    
    # Ask for reason
    msg = bot.send_message(
        call.message.chat.id,
        f"🚨 <b>Reporting Swap #{swap_id}</b>\n\nPlease describe the issue (inappropriate content, etc.):",
        parse_mode='HTML'
    )
    
    # Store context for next message
    bot.register_next_step_handler(msg, lambda m: process_report(m, swap_id, call.from_user.id))

def process_report(message, swap_id, reporter_id):
    """Process the report"""
    reason = message.text.strip()
    
    if len(reason) < 5:
        bot.reply_to(message, "❌ Please provide a detailed reason (at least 5 characters).")
        return
    
    # Add report to database
    report_id = add_report(reporter_id, int(swap_id), reason)
    
    # Notify admin
    try:
        admin_msg = f"""🚨 <b>NEW REPORT</b>

🆔 <b>Report ID:</b> #{report_id}
👤 <b>Reporter:</b> {reporter_id}
🔄 <b>Swap ID:</b> #{swap_id}
📝 <b>Reason:</b> {reason[:200]}
🕒 <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}

⚠️ <b>Action Required:</b> Please review this report."""
        
        bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")
    
    # Confirm to user
    bot.reply_to(message, f"✅ <b>Report Submitted</b>\n\nThank you for your report (ID: #{report_id}). We will review it within 24 hours.", parse_mode='HTML')

# ========== ADMIN COMMANDS ==========
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    """Admin panel access"""
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Access denied.")
        return
    
    admin_text = f"""👑 <b>Admin Panel</b>

🆔 <b>Admin ID:</b> <code>{ADMIN_ID}</code>
🕒 <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}
🌐 <b>Mode:</b> {'Webhook' if WEBHOOK_URL else 'Polling'}

📊 <b>Statistics:</b>
• Users: {get_total_users()}
• Active (24h): {get_active_users_count(1)}
• Banned: {len(BANNED_USERS)}
• Active Swaps: {len(active_swaps)}

⚙️ <b>Admin Commands:</b>
/users - List all users
/ban [id] - Ban user
/unban [id] - Unban user
/botstatus - Bot status
/reports - View reports
/broadcast - Send message
/exportdata - Export data
/stats - Detailed stats

🔧 <b>Quick Actions:</b>"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 View Users", callback_data="admin_users"),
        types.InlineKeyboardButton("🚨 View Reports", callback_data="admin_reports")
    )
    markup.add(
        types.InlineKeyboardButton("📊 Full Stats", callback_data="admin_stats"),
        types.InlineKeyboardButton("🔄 Bot Status", callback_data="admin_status")
    )
    
    bot.reply_to(message, admin_text, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(commands=['users'])
def list_users_command(message):
    """List all users (admin only)"""
    if message.from_user.id != ADMIN_ID:
        return
    
    users = get_all_users(limit=50)
    
    if not users:
        bot.reply_to(message, "📭 No users found.")
        return
    
    # Pagination
    page = 0
    users_per_page = 5
    total_pages = (len(users) + users_per_page - 1) // users_per_page
    
    # Get current page users
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
    
    # Create inline keyboard with user actions
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
    
    # Add navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Previous", callback_data=f"admin_users_page_{page-1}"))
    
    if page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"admin_users_page_{page+1}"))
    
    if nav_buttons:
        markup.row(*nav_buttons)
    
    markup.add(types.InlineKeyboardButton("🔄 Refresh", callback_data="admin_users_refresh"))
    
    bot.reply_to(message, users_text, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_ban_'))
def admin_ban_callback(call):
    """Ban user from admin panel"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    user_id = int(call.data.split('_')[2])
    ban_user(user_id)
    
    # Try to notify user
    try:
        bot.send_message(user_id, "🚫 <b>You have been banned from using this bot.</b>", parse_mode='HTML')
    except:
        pass
    
    bot.answer_callback_query(call.id, f"✅ User {user_id} banned!")
    
    # Update the message
    list_users_command(call.message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_unban_'))
def admin_unban_callback(call):
    """Unban user from admin panel"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    user_id = int(call.data.split('_')[2])
    unban_user(user_id)
    
    # Try to notify user
    try:
        bot.send_message(user_id, "✅ <b>Your ban has been lifted! You can now use the bot again.</b>", parse_mode='HTML')
    except:
        pass
    
    bot.answer_callback_query(call.id, f"✅ User {user_id} unbanned!")
    
    # Update the message
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
        
        # Try to notify user
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
        
        # Try to notify user
        try:
            bot.send_message(user_id, "✅ <b>Your ban has been lifted! You can now use the bot again.</b>", parse_mode='HTML')
        except:
            pass
        
        bot.reply_to(message, f"✅ User {user_id} has been unbanned.")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['botstatus'])
def bot_status_command(message):
    """Show detailed bot status (admin only)"""
    if message.from_user.id != ADMIN_ID:
        return
    
    # Get statistics
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
    
    # Get recent activity
    c.execute('''SELECT user_id, status, swap_date FROM swaps_history 
        ORDER BY swap_date DESC LIMIT 5''')
    recent_activity = c.fetchall()
    
    conn.close()
    
    # Calculate rates
    success_rate = round((success_swaps / max(1, total_swaps)) * 100, 1)
    
    status_text = f"""🤖 <b>BOT STATUS REPORT</b>

━━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>USER STATISTICS:</b>
• Total Users: <b>{get_total_users()}</b>
• Active (24h): <b>{get_active_users_count(1)}</b>
• Active (7d): <b>{get_active_users_count(7)}</b>
• Verified Users: <b>{verified_users}</b>
• Banned Users: <b>{len(BANNED_USERS)}</b>

🔄 <b>SWAP STATISTICS:</b>
• Total Swaps: <b>{total_swaps}</b>
• Successful: <b>{success_swaps}</b>
• Failed: <b>{failed_swaps}</b>
• Success Rate: <b>{success_rate}%</b>
• Active Swaps: <b>{len(active_swaps)}</b>

📱 <b>CURRENT SESSIONS:</b>
• Active Sessions: <b>{len(user_data)}</b>
• Memory Usage: <b>{sys.getsizeof(user_data) + sys.getsizeof(active_swaps):,} bytes</b>

⚠️ <b>MODERATION:</b>
• Pending Reports: <b>{pending_reports}</b>
• Total Favorites: <b>{len(get_user_favorites(1)[:1]) if get_user_favorites(1) else 0}</b>

🔧 <b>SYSTEM STATUS:</b>
• Bot: <b>✅ RUNNING</b>
• Database: <b>✅ CONNECTED</b>
• API: <b>✅ AVAILABLE</b>
• Webhook: <b>{'✅ ACTIVE' if WEBHOOK_URL else '❌ INACTIVE'}</b>
• Uptime: <b>{format_time(time.time() - start_time)}</b>

🕒 <b>RECENT ACTIVITY:</b>\n"""
    
    for user_id, status, swap_date in recent_activity:
        emoji = "✅" if status == "success" else "❌"
        time_ago = datetime.now() - datetime.strptime(swap_date[:19], '%Y-%m-%d %H:%M:%S')
        hours_ago = int(time_ago.total_seconds() / 3600)
        status_text += f"• {emoji} User {user_id}: {status} ({hours_ago}h ago)\n"
    
    status_text += """━━━━━━━━━━━━━━━━━━━━━━━━

<b>ADMIN COMMANDS:</b>
/users - User management
/ban /unban - User control
/reports - View reports
/broadcast - Send message
/exportdata - Export data
/stats - Detailed statistics

💡 <b>Health Endpoints:</b>
• /health/hunter - Health check
• /stats/hunter - Statistics
• /users/hunter - User data"""
    
    bot.reply_to(message, status_text, parse_mode='HTML')

@bot.message_handler(commands=['reports'])
def view_reports_command(message):
    """View all reports (admin only)"""
    if message.from_user.id != ADMIN_ID:
        return
    
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''SELECT r.id, r.reporter_id, r.reported_swap_id, r.reason, 
        r.report_date, r.status, u.username 
        FROM reports r
        LEFT JOIN users u ON r.reporter_id = u.user_id
        ORDER BY r.report_date DESC 
        LIMIT 10''')
    
    reports = c.fetchall()
    conn.close()
    
    if not reports:
        bot.reply_to(message, "📭 No reports found.")
        return
    
    reports_text = f"""🚨 <b>REPORT MANAGEMENT</b>

📊 <b>Total Reports:</b> {len(reports)}

━━━━━━━━━━━━━━━━━━\n"""
    
    for report in reports:
        report_id, reporter_id, swap_id, reason, report_date, status, username = report
        
        status_emoji = "🟡" if status == "pending" else "✅"
        username_display = f"@{username}" if username else f"ID:{reporter_id}"
        
        reports_text += f"\n{status_emoji} <b>Report #{report_id}</b>\n"
        reports_text += f"👤 Reporter: {username_display}\n"
        reports_text += f"🔄 Swap ID: #{swap_id}\n"
        reports_text += f"📝 Reason: {reason[:100]}{'...' if len(reason) > 100 else ''}\n"
        reports_text += f"⏰ Date: {report_date[:16] if report_date else 'N/A'}\n"
        reports_text += f"📊 Status: {status.upper()}\n"
        reports_text += f"━━━━━━━━━━━━━━━━━━\n"
    
    # Create inline keyboard for actions
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    for report in reports[:5]:  # Show actions for first 5 reports
        report_id = report[0]
        markup.add(types.InlineKeyboardButton(
            f"✅ Resolve #{report_id}",
            callback_data=f"admin_resolve_{report_id}"
        ))
    
    markup.add(types.InlineKeyboardButton("🔄 Refresh", callback_data="admin_reports_refresh"))
    
    bot.reply_to(message, reports_text, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(commands=['broadcast'])
def broadcast_command(message):
    """Broadcast message to all users (admin only)"""
    if message.from_user.id != ADMIN_ID:
        return
    
    # Get message text
    broadcast_text = message.text.replace('/broadcast', '', 1).strip()
    
    if not broadcast_text:
        bot.reply_to(message, """📢 <b>Broadcast Usage:</b>

<code>/broadcast Your message here</code>

💡 <b>Example:</b>
<code>/broadcast New feature added! Check /help for details.</code>

⚠️ <b>Note:</b> This will send to all users except banned ones.""", parse_mode='HTML')
        return
    
    # Confirm broadcast
    confirm_text = f"""📢 <b>BROADCAST CONFIRMATION</b>

<b>Message:</b>
{broadcast_text}

<b>Recipients:</b> {get_total_users() - len(BANNED_USERS)} users
<b>Banned users excluded:</b> {len(BANNED_USERS)}

⚠️ <b>Are you sure you want to send this broadcast?</b>"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Send Broadcast", callback_data=f"broadcast_confirm_{hashlib.md5(broadcast_text.encode()).hexdigest()[:8]}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel")
    )
    
    bot.reply_to(message, confirm_text, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('broadcast_confirm_'))
def confirm_broadcast_callback(call):
    """Confirm and send broadcast"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    # Extract message from original message
    original_text = call.message.text
    lines = original_text.split('\n')
    
    # Find message content (between "Message:" and "Recipients:")
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
    
    # Update message to show sending status
    bot.edit_message_text(
        "📢 <b>Sending broadcast...</b>\n\n⏳ Please wait, this may take a while.",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML'
    )
    
    # Get all users
    users = get_all_users(limit=1000)
    sent_count = 0
    failed_count = 0
    
    # Send to each user
    for user in users:
        user_id = user[0]
        
        # Skip banned users
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
            sent_count += 1
            time.sleep(0.05)  # Rate limiting
            
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {e}")
            failed_count += 1
    
    # Update message with results
    result_text = f"""✅ <b>Broadcast Complete!</b>

📊 <b>Results:</b>
• Sent: <b>{sent_count}</b> users
• Failed: <b>{failed_count}</b> users
• Total Attempted: <b>{sent_count + failed_count}</b>

🕒 <b>Completed at:</b> {datetime.now().strftime('%H:%M:%S')}

💡 <b>Note:</b> Failed sends are usually due to users blocking the bot or deleted accounts."""
    
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

@bot.message_handler(commands=['exportdata'])
def export_data_command(message):
    """Export data as CSV (admin only)"""
    if message.from_user.id != ADMIN_ID:
        return
    
    # Create export
    export_text = """📊 <b>Data Export</b>

Choose what data to export:

1️⃣ <b>Users Data</b> - All user information
2️⃣ <b>Swaps History</b> - All swap records
3️⃣ <b>Reports Data</b> - All reports
4️⃣ <b>Favorites Data</b> - All favorite swaps

💡 <b>Note:</b> Data will be sent as CSV files."""

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👥 Users", callback_data="export_users"),
        types.InlineKeyboardButton("🔄 Swaps", callback_data="export_swaps")
    )
    markup.add(
        types.InlineKeyboardButton("🚨 Reports", callback_data="export_reports"),
        types.InlineKeyboardButton("⭐ Favorites", callback_data="export_favorites")
    )
    
    bot.reply_to(message, export_text, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('export_'))
def handle_export_callback(call):
    """Handle export callbacks"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Access denied.")
        return
    
    export_type = call.data.replace('export_', '')
    
    # Create CSV data based on type
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        if export_type == 'users':
            c.execute('SELECT * FROM users')
            data = c.fetchall()
            filename = 'users.csv'
            headers = ['User ID', 'Username', 'First Name', 'Last Name', 'Join Date', 
                      'Last Active', 'Banned', 'Verified', 'Swaps Count', 
                      'Successful Swaps', 'Failed Swaps', 'Data Hash']
        
        elif export_type == 'swaps':
            c.execute('SELECT * FROM swaps_history')
            data = c.fetchall()
            filename = 'swaps.csv'
            headers = ['ID', 'User ID', 'Swap Date', 'Status', 'Processing Time', 
                      'Result Path', 'Is Favorite', 'Is Reviewed', 'NSFW Detected']
        
        elif export_type == 'reports':
            c.execute('SELECT * FROM reports')
            data = c.fetchall()
            filename = 'reports.csv'
            headers = ['ID', 'Reporter ID', 'Reported Swap ID', 'Reason', 
                      'Report Date', 'Status', 'Admin Notes']
        
        elif export_type == 'favorites':
            c.execute('SELECT * FROM favorites')
            data = c.fetchall()
            filename = 'favorites.csv'
            headers = ['ID', 'User ID', 'Swap ID', 'Saved Date']
        
        else:
            bot.answer_callback_query(call.id, "❌ Invalid export type.")
            return
        
        conn.close()
        
        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        
        for row in data:
            writer.writerow(row)
        
        # Prepare file for sending
        output.seek(0)
        csv_data = output.getvalue().encode('utf-8')
        output.close()
        
        # Send file
        bot.send_document(
            call.message.chat.id,
            (filename, csv_data),
            caption=f"📊 {export_type.capitalize()} Data Export\n\n🕒 Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n📁 Rows: {len(data)}"
        )
        
        bot.answer_callback_query(call.id, f"✅ {export_type.capitalize()} exported!")
        
    except Exception as e:
        logger.error(f"Export error: {e}")
        bot.answer_callback_query(call.id, "❌ Export failed!")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Handle all other messages"""
    chat_id = message.chat.id
    
    if chat_id in user_data:
        state = user_data[chat_id].get('state')
        
        if state == WAITING_FOR_SOURCE:
            bot.reply_to(message, "📸 Please send the SOURCE photo first.")
        elif state == WAITING_FOR_TARGET:
            bot.reply_to(message, "📸 Please send the TARGET photo to complete the swap.")
        elif state == 'processing':
            bot.reply_to(message, "⏳ Your swap is being processed. Please wait...")
        else:
            bot.reply_to(message, "🔄 Please use /swap to start a new face swap or /help for instructions.")
    else:
        # Check if it's a report
        text = message.text.strip()
        if text and text[0].isdigit() and ' ' in text:
            # Might be a report in format "ID Reason"
            parts = text.split(' ', 1)
            if parts[0].isdigit() and len(parts) > 1:
                try:
                    swap_id = int(parts[0])
                    reason = parts[1]
                    
                    # Add report
                    report_id = add_report(message.from_user.id, swap_id, reason)
                    
                    bot.reply_to(message, f"✅ Report #{report_id} submitted. Thank you!")
                    return
                except:
                    pass
        
        # Default response
        help_text = """🤖 <b>Face Swap Bot</b>

I didn't understand that command. Here's what I can do:

🎭 <b>Main Commands:</b>
/start - Start the bot
/help - Show help message
/swap - Start a new face swap
/mystats - View your statistics
/favorites - View saved swaps
/history - View swap history
/cancel - Cancel current swap
/report - Report content

💡 <b>Need help?</b> Use /help for detailed instructions.

👑 <b>Admin commands available for authorized users.</b>"""
        
        bot.reply_to(message, help_text, parse_mode='HTML')

# ========== WEBHOOK SETUP ==========
def setup_webhook():
    """Setup webhook for Telegram bot"""
    if not WEBHOOK_URL:
        logger.info("Running in polling mode")
        return False
    
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

# ========== MAIN FUNCTION ==========
def run_bot():
    """Run the bot in polling mode"""
    logger.info("Starting bot in polling mode...")
    
    try:
        bot.infinity_polling(
            timeout=30,
            long_polling_timeout=30,
            logger_level=logging.INFO
        )
    except Exception as e:
        logger.error(f"Bot polling error: {e}")
        return False
    
    return True

def run_flask():
    """Run the Flask web server"""
    logger.info(f"Starting Flask server on port {BOT_PORT}...")
    
    try:
        app.run(
            host='0.0.0.0',
            port=BOT_PORT,
            debug=False,
            use_reloader=False,
            threaded=True
        )
    except Exception as e:
        logger.error(f"Flask server error: {e}")
        return False
    
    return True

def main():
    """Main application entry point"""
    global start_time
    start_time = time.time()
    
    # Print banner
    print("=" * 70)
    print("🤖 ENHANCED FACE SWAP BOT v3.1")
    print("=" * 70)
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"📢 Required Channel: {REQUIRED_CHANNEL}")
    print(f"🌐 Webhook URL: {WEBHOOK_URL or 'None (Polling)'}")
    print(f"🚀 Bot Port: {BOT_PORT}")
    print("=" * 70)
    print("✨ FEATURES:")
    print("• Real-time face swapping with progress tracking")
    print("• Channel verification system")
    print("• Save favorites & view history")
    print("• Report system with admin review")
    print("• Admin panel with inline user management")
    print("• Broadcast messaging to all users")
    print("• Data export (CSV format)")
    print("• Web dashboard with statistics")
    print("• Health monitoring endpoints")
    print("=" * 70)
    print("👑 ADMIN COMMANDS:")
    print("/admin - Admin panel")
    print("/users - User management")
    print("/ban /unban - User control")
    print("/botstatus - Detailed status")
    print("/reports - View reports")
    print("/broadcast - Send message to all")
    print("/exportdata - Export data")
    print("=" * 70)
    print("🌐 WEB ENDPOINTS:")
    print(f"GET  / - Dashboard")
    print(f"GET  /health/hunter - Health check")
    print(f"GET  /stats/hunter - Statistics")
    print(f"GET  /users/hunter - User data")
    print(f"POST /webhook - Telegram webhook")
    print(f"GET  /status - Bot status")
    print("=" * 70)
    print("📱 BOT COMMANDS:")
    print("/start - Welcome message")
    print("/swap - Start face swap")
    print("/mystats - Your statistics")
    print("/favorites - Saved swaps")
    print("/history - Swap history")
    print("/report - Report content")
    print("/cancel - Cancel swap")
    print("=" * 70)
    print("Created by @PokiePy")
    print("=" * 70)
    
    # Initialize database
    init_database()
    
    # Try to get bot info
    try:
        bot_info = bot.get_me()
        print(f"✅ Bot connected: @{bot_info.username} (ID: {bot_info.id})")
    except Exception as e:
        print(f"❌ Bot connection error: {e}")
        return
    
    # Setup based on mode
    if WEBHOOK_URL:
        print(f"🌐 Webhook mode enabled")
        
        # Setup webhook
        if setup_webhook():
            print("✅ Webhook configured successfully")
            
            # Start Flask in main thread
            print(f"🚀 Starting web server on port {BOT_PORT}...")
            run_flask()
        else:
            print("❌ Webhook setup failed, falling back to polling...")
            run_bot()
    else:
        print("📡 Polling mode enabled")
        run_bot()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
