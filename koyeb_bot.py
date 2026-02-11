#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Rain Selfbot v2.0 - Production Ready
Complete with group management, inline button clicking, and monitoring
Optimized for Koyeb deployment
"""

import os
import sys
import re
import json
import time
import logging
import asyncio
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any

import aiohttp
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl import types
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
from flask import Flask, request, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

# ========== CONFIGURATION ==========
SESSION_STRING = os.environ.get('TELEGRAM_SESSION_STRING', '1BVtsOIwBu77iLjtJS9sDpHTirCAB2EuPrb7fWA6B6M1KoRPY3fdSqDyq2A5qODauYg-qhkP7UTMK1-logKBmD7LmqMO04ZKm2G8_PwLSlLX6z6oa6ah3b8J5Q5Mo5d_h0QOg-HwWIF2O29jgd_6noOQ9pv-4SGEkXWKy45q2HxFhJz1ZESmhntAAyyN2syrFU_ci7IQgQ2G59657iuU6sSXyXlttWvRPMqAknIVIbHDOrmLwha4AD2Z1P84ymdB312MtFtF7_wA2jxr3PL2Jw5dEBq2AxWoHl5ByEc5CMxUbvxJ1c0gcO26hRl7evZwAiL-br1VtbZBDOwmx4oEcHLZNyRUdsxs=')
ALERT_CHANNEL = os.environ.get('ALERT_CHANNEL', 'me')  # "me" for Saved Messages
ADMIN_ID = int(os.environ.get('ADMIN_ID', 8472371058))

# Bot settings
WEB_PORT = int(os.environ.get('PORT', 8080))

# Keywords for detection
KEYWORDS = [
    "rain", "airdrop", "giveaway", "claim", "free", "distribution",
    "drop", "contest", "reward", "prize", "raffle", "lottery",
    "win", "participate", "bot", "crypto", "token", "nft",
    "💰", "🎁", "🎉", "🚀", "🔥", "✨", "🪙", "🆓", "🏆"
]

# Button text patterns to click
CLICKABLE_BUTTON_TEXTS = [
    "join", "participate", "claim", "tap", "click", "start",
    "enter", "submit", "verify", "connect", "open", "go",
    "get", "receive", "collect", "airdrop", "reward", "check",
    "🎯", "✅", "🔗", "📲", "🎰", "👆", "👉", "👇", "🎮"
]

# Auto settings
AUTO_CLICK_BUTTONS = True
AUTO_JOIN_LINKS = True
SEND_REACTIONS = True
REACTION_EMOJI = "👀"

# Cooldowns (seconds)
CHAT_COOLDOWN = 2
BUTTON_COOLDOWN = 1
USER_COOLDOWN = 1

# ========== INITIALIZE ==========
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# ========== LOGGING ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('rain_bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ========== DATABASE ==========
class Database:
    def __init__(self, db_path='rain_bot.db'):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        c = conn.cursor()
        
        # Monitored groups
        c.execute('''CREATE TABLE IF NOT EXISTS monitored_groups (
            id INTEGER PRIMARY KEY,
            group_id INTEGER UNIQUE,
            group_title TEXT,
            group_username TEXT,
            added_by TEXT,
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )''')
        
        # Processed messages
        c.execute('''CREATE TABLE IF NOT EXISTS processed_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            message_id INTEGER,
            processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chat_id, message_id)
        )''')
        
        # Statistics
        c.execute('''CREATE TABLE IF NOT EXISTS statistics (
            id INTEGER PRIMARY KEY,
            rains_detected INTEGER DEFAULT 0,
            buttons_clicked INTEGER DEFAULT 0,
            links_joined INTEGER DEFAULT 0,
            errors INTEGER DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Initialize stats
        c.execute('INSERT OR IGNORE INTO statistics (id) VALUES (1)')
        
        # Cooldown tracking
        c.execute('''CREATE TABLE IF NOT EXISTS cooldown_tracker (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            last_action TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        conn.commit()
        conn.close()
    
    def get_connection(self):
        """Get database connection"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    
    def add_group(self, group_id: int, title: str, username: str = None, added_by: str = "admin") -> bool:
        """Add a group to monitoring list"""
        try:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO monitored_groups 
                (group_id, group_title, group_username, added_by, is_active)
                VALUES (?, ?, ?, ?, 1)''',
                (group_id, title, username, added_by))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error adding group: {e}")
            return False
    
    def remove_group(self, group_id: int) -> bool:
        """Remove a group from monitoring"""
        try:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute('DELETE FROM monitored_groups WHERE group_id = ?', (group_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error removing group: {e}")
            return False
    
    def get_monitored_groups(self) -> List[Dict]:
        """Get all monitored groups"""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('''SELECT group_id, group_title, group_username, added_date 
            FROM monitored_groups WHERE is_active = 1 ORDER BY added_date''')
        
        groups = []
        for row in c.fetchall():
            groups.append({
                'id': row[0],
                'title': row[1],
                'username': row[2],
                'added_date': row[3]
            })
        
        conn.close()
        return groups
    
    def is_group_monitored(self, group_id: int) -> bool:
        """Check if a group is being monitored"""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('SELECT 1 FROM monitored_groups WHERE group_id = ? AND is_active = 1', (group_id,))
        result = c.fetchone() is not None
        conn.close()
        return result
    
    def mark_message_processed(self, chat_id: int, message_id: int):
        """Mark message as processed"""
        try:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute('''INSERT OR IGNORE INTO processed_messages (chat_id, message_id)
                VALUES (?, ?)''', (chat_id, message_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error marking message processed: {e}")
    
    def is_message_processed(self, chat_id: int, message_id: int) -> bool:
        """Check if message was already processed"""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('SELECT 1 FROM processed_messages WHERE chat_id = ? AND message_id = ?', (chat_id, message_id))
        result = c.fetchone() is not None
        conn.close()
        return result
    
    def check_cooldown(self, key: str, cooldown_seconds: int) -> bool:
        """Check if action is allowed (not in cooldown)"""
        conn = self.get_connection()
        c = conn.cursor()
        
        c.execute('SELECT last_action FROM cooldown_tracker WHERE key = ?', (key,))
        row = c.fetchone()
        
        now = datetime.now().timestamp()
        
        if row:
            last_action = datetime.fromisoformat(row[0]).timestamp()
            elapsed = now - last_action
            
            if elapsed < cooldown_seconds:
                conn.close()
                return False
            
            c.execute('UPDATE cooldown_tracker SET last_action = CURRENT_TIMESTAMP WHERE key = ?', (key,))
        else:
            c.execute('INSERT INTO cooldown_tracker (key, last_action) VALUES (?, CURRENT_TIMESTAMP)', (key,))
        
        conn.commit()
        conn.close()
        return True
    
    def update_stat(self, stat_name: str, increment: int = 1):
        """Update statistics"""
        valid_stats = ['rains_detected', 'buttons_clicked', 'links_joined', 'errors']
        if stat_name in valid_stats:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute(f'''UPDATE statistics 
                SET {stat_name} = {stat_name} + ?, last_updated = CURRENT_TIMESTAMP
                WHERE id = 1''', (increment,))
            conn.commit()
            conn.close()
    
    def get_stats(self) -> Dict:
        """Get all statistics"""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('SELECT rains_detected, buttons_clicked, links_joined, errors, last_updated FROM statistics WHERE id = 1')
        row = c.fetchone()
        conn.close()
        
        if row:
            return {
                'rains_detected': row[0],
                'buttons_clicked': row[1],
                'links_joined': row[2],
                'errors': row[3],
                'last_updated': row[4]
            }
        return {}
    
    def get_total_processed(self) -> int:
        """Get total processed messages"""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM processed_messages')
        result = c.fetchone()[0] or 0
        conn.close()
        return result

# Initialize database
db = Database()

# ========== COOLDOWN MANAGER ==========
class CooldownManager:
    def __init__(self):
        self.memory_cooldowns = {}
    
    def check_memory_cooldown(self, key: str, cooldown_seconds: int) -> bool:
        """Memory-based cooldown for fast operations"""
        now = time.time()
        
        if key in self.memory_cooldowns:
            elapsed = now - self.memory_cooldowns[key]
            if elapsed < cooldown_seconds:
                return False
        
        self.memory_cooldowns[key] = now
        return True

cooldown = CooldownManager()

# ========== HELPER FUNCTIONS ==========
def contains_keywords(text: str) -> bool:
    """Check if text contains rain/giveaway keywords"""
    if not text:
        return False
    
    text_lower = text.lower()
    
    # Check direct keywords
    for keyword in KEYWORDS:
        if keyword.lower() in text_lower:
            return True
    
    # Check patterns
    patterns = [
        r"/start\s+[A-Za-z0-9_]+",
        r"claim\s+(?:your|free|reward)",
        r"join\s+(?:here|now|quick)",
        r"airdrop\s+(?:bot|claimer)",
        r"free\s+\d+\s*(?:usdt|eth|btc|sol)",
        r"win\s+\d+\s*(?:usdt|eth|btc|sol)",
        r"participate.*(?:now|here)",
        r"distribution.*(?:live|ongoing)",
        r"giveaway.*(?:win|prize|reward)",
        r"raffle.*(?:entry|join)"
    ]
    
    for pattern in patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    
    return False

def should_click_button(button_text: str) -> bool:
    """Determine if button should be clicked"""
    if not button_text:
        return False
    
    button_lower = button_text.lower()
    
    # Check for clickable texts
    for text in CLICKABLE_BUTTON_TEXTS:
        if text.lower() in button_lower:
            return True
    
    # Check for emoji indicators
    emoji_patterns = ["🎯", "✅", "🔗", "💰", "🎁", "🎰", "👆", "👉", "👇", "🎮"]
    for emoji in emoji_patterns:
        if emoji in button_text:
            return True
    
    # Check for common patterns
    patterns = [
        r"^claim$", r"^join$", r"^start$", r"^verify$",
        r"claim\s+now", r"join\s+airdrop", r"get\s+reward",
        r"participate\s+now", r"click\s+here", r"tap\s+to"
    ]
    
    for pattern in patterns:
        if re.match(pattern, button_lower, re.IGNORECASE):
            return True
    
    return False

def extract_links(text: str) -> List[str]:
    """Extract all links from text"""
    links = []
    
    # Find URLs
    url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+|t\.me/[^\s<>"]+'
    found = re.findall(url_pattern, text)
    
    for link in found:
        if not link.startswith('http'):
            link = f'https://{link}'
        links.append(link)
    
    return list(set(links))

# ========== TELEGRAM SESSION VALIDATION ==========
async def validate_session(session_string: str) -> Tuple[bool, Optional[str]]:
    """Validate Telegram session string"""
    if not session_string or session_string == "YOUR_SESSION_STRING_HERE":
        return False, "Session string not configured"
    
    try:
        client = TelegramClient(StringSession(session_string), 1, "b6bcc390bbf71818a6c6b2d3c2de5b86")
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.disconnect()
            return False, "Session not authorized"
        
        me = await client.get_me()
        await client.disconnect()
        
        return True, f"Valid session for @{me.username if me.username else me.id}"
    
    except Exception as e:
        return False, f"Session validation failed: {str(e)}"

# ========== TELEGRAM SELF-BOT CLASS ==========
class TelegramRainBot:
    def __init__(self, session_string: str):
        self.session_string = session_string
        self.client = None
        self.is_running = False
        self.start_time = time.time()
        
    async def start(self):
        """Start the selfbot"""
        print("=" * 70)
        print("🤖 TELEGRAM RAIN SELF-BOT v2.0")
        print("=" * 70)
        
        # Validate session
        is_valid, message = await validate_session(self.session_string)
        if not is_valid:
            print(f"❌ {message}")
            return False
        
        # Create client
        self.client = TelegramClient(StringSession(self.session_string), 1, "b6bcc390bbf71818a6c6b2d3c2de5b86")
        
        try:
            await self.client.start()
            me = await self.client.get_me()
            
            print(f"✅ Logged in as: {me.first_name} (@{me.username})")
            print(f"📱 Phone: {me.phone}")
            print(f"🆔 User ID: {me.id}")
            print("=" * 70)
            
            # Setup event handlers
            self.setup_handlers()
            
            # Send startup message
            await self.send_startup_message(me)
            
            self.is_running = True
            logger.info(f"Selfbot started successfully for user @{me.username}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start selfbot: {e}")
            print(f"❌ Failed to start: {e}")
            return False
    
    async def send_startup_message(self, me):
        """Send startup notification"""
        try:
            monitored_groups = db.get_monitored_groups()
            stats = db.get_stats()
            
            message = f"""✅ <b>Rain Selfbot Started</b>

👤 <b>User:</b> {me.first_name} (@{me.username})
📱 <b>Phone:</b> {me.phone}
🆔 <b>ID:</b> <code>{me.id}</code>
🕒 <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📊 <b>Statistics:</b>
• Rains Detected: {stats.get('rains_detected', 0)}
• Buttons Clicked: {stats.get('buttons_clicked', 0)}
• Links Joined: {stats.get('links_joined', 0)}
• Monitored Groups: {len(monitored_groups)}

⚙️ <b>Settings:</b>
• Auto-Click: {'✅ ON' if AUTO_CLICK_BUTTONS else '❌ OFF'}
• Auto-Join: {'✅ ON' if AUTO_JOIN_LINKS else '❌ OFF'}
• Reactions: {'✅ ON' if SEND_REACTIONS else '❌ OFF'}

🚀 <b>Bot is now monitoring for rains...</b>"""
            
            await self.client.send_message(ALERT_CHANNEL, message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Failed to send startup message: {e}")
    
    def setup_handlers(self):
        """Setup Telegram event handlers"""
        
        @self.client.on(events.NewMessage(incoming=True))
        async def message_handler(event):
            """Handle incoming messages"""
            try:
                # Skip our own messages
                if event.out:
                    return
                
                # Check if from monitored group
                chat = await event.get_chat()
                if not db.is_group_monitored(chat.id):
                    return
                
                # Check if already processed
                if db.is_message_processed(chat.id, event.message.id):
                    return
                
                # Check cooldown
                if not db.check_cooldown(f"chat_{chat.id}", CHAT_COOLDOWN):
                    return
                
                # Check for keywords
                message_text = event.message.text or event.message.raw_text or ""
                if not contains_keywords(message_text):
                    return
                
                logger.info(f"Rain detected in chat: {getattr(chat, 'title', 'Unknown')}")
                db.mark_message_processed(chat.id, event.message.id)
                
                # Process the message
                await self.process_rain_message(event)
                
            except Exception as e:
                logger.error(f"Message handler error: {e}")
                db.update_stat('errors')
        
        @self.client.on(events.NewMessage(pattern=r'^!add\s+', outgoing=True))
        async def add_command_handler(event):
            """Handle !add command"""
            try:
                if event.sender_id != ADMIN_ID:
                    return
                
                args = event.message.text.split(maxsplit=1)
                if len(args) < 2:
                    await event.reply("❌ Usage: `!add <group_id|@username|link>`")
                    return
                
                await self.handle_add_command(event, args[1])
                
            except Exception as e:
                logger.error(f"Add command error: {e}")
                await event.reply(f"❌ Error: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern=r'^!remove\s+', outgoing=True))
        async def remove_command_handler(event):
            """Handle !remove command"""
            try:
                if event.sender_id != ADMIN_ID:
                    return
                
                args = event.message.text.split(maxsplit=1)
                if len(args) < 2:
                    await event.reply("❌ Usage: `!remove <group_id>`")
                    return
                
                await self.handle_remove_command(event, args[1])
                
            except Exception as e:
                logger.error(f"Remove command error: {e}")
                await event.reply(f"❌ Error: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern=r'^!list$', outgoing=True))
        async def list_command_handler(event):
            """Handle !list command"""
            try:
                if event.sender_id != ADMIN_ID:
                    return
                
                await self.handle_list_command(event)
                
            except Exception as e:
                logger.error(f"List command error: {e}")
                await event.reply(f"❌ Error: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern=r'^!stats$', outgoing=True))
        async def stats_command_handler(event):
            """Handle !stats command"""
            try:
                if event.sender_id != ADMIN_ID:
                    return
                
                await self.handle_stats_command(event)
                
            except Exception as e:
                logger.error(f"Stats command error: {e}")
                await event.reply(f"❌ Error: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern=r'^!help$', outgoing=True))
        async def help_command_handler(event):
            """Handle !help command"""
            try:
                if event.sender_id != ADMIN_ID:
                    return
                
                await self.handle_help_command(event)
                
            except Exception as e:
                logger.error(f"Help command error: {e}")
                await event.reply(f"❌ Error: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern=r'^!ping$', outgoing=True))
        async def ping_command_handler(event):
            """Handle !ping command"""
            try:
                if event.sender_id != ADMIN_ID:
                    return
                
                await self.handle_ping_command(event)
                
            except Exception as e:
                logger.error(f"Ping command error: {e}")
                await event.reply(f"❌ Error: {str(e)}")
    
    async def process_rain_message(self, event):
        """Process a rain/giveaway message"""
        try:
            chat = await event.get_chat()
            message = event.message
            
            clicked_buttons = []
            joined_links = []
            
            # Process inline buttons
            if AUTO_CLICK_BUTTONS:
                buttons_clicked = await self.click_buttons(chat.id, message)
                clicked_buttons.extend(buttons_clicked)
            
            # Process links
            if AUTO_JOIN_LINKS:
                message_text = message.text or message.raw_text or ""
                links = extract_links(message_text)
                
                for link in links:
                    if db.check_cooldown(f"link_{chat.id}", CHAT_COOLDOWN):
                        success, result = await self.join_link(link)
                        if success:
                            joined_links.append(link)
                            db.update_stat('links_joined')
                            await asyncio.sleep(0.5)
            
            # Add reaction
            if SEND_REACTIONS:
                try:
                    reaction = ReactionEmoji(emoticon=REACTION_EMOJI)
                    await self.client(SendReactionRequest(
                        peer=await message.get_input_chat(),
                        msg_id=message.id,
                        reaction=[reaction]
                    ))
                except Exception:
                    pass
            
            # Update statistics
            db.update_stat('rains_detected')
            if clicked_buttons:
                db.update_stat('buttons_clicked', len(clicked_buttons))
            
            # Send alert
            await self.send_alert(chat, message, clicked_buttons, joined_links)
            
            logger.info(f"Processed rain in {getattr(chat, 'title', 'Unknown')}: "
                       f"buttons={len(clicked_buttons)}, links={len(joined_links)}")
            
        except Exception as e:
            logger.error(f"Process rain error: {e}")
            db.update_stat('errors')
    
    async def click_buttons(self, chat_id: int, message) -> List[str]:
        """Click all relevant buttons in a message"""
        clicked = []
        
        if not hasattr(message, 'reply_markup') or not message.reply_markup:
            return clicked
        
        try:
            if hasattr(message.reply_markup, 'rows'):
                for row in message.reply_markup.rows:
                    for button in row.buttons:
                        button_text = getattr(button, 'text', '')
                        
                        if should_click_button(button_text):
                            # Check cooldown
                            if not cooldown.check_memory_cooldown(f"button_{chat_id}", BUTTON_COOLDOWN):
                                continue
                            
                            try:
                                if hasattr(button, 'data'):  # Callback button
                                    await self.client(GetBotCallbackAnswerRequest(
                                        peer=chat_id,
                                        msg_id=message.id,
                                        data=button.data
                                    ))
                                    clicked.append(button_text[:20])
                                    await asyncio.sleep(0.3)
                                
                                elif hasattr(button, 'url'):  # URL button
                                    # We'll handle URLs in join_link function
                                    pass
                                
                            except Exception as e:
                                logger.debug(f"Failed to click button '{button_text}': {e}")
        
        except Exception as e:
            logger.error(f"Button clicking error: {e}")
        
        return clicked
    
    async def join_link(self, link: str) -> Tuple[bool, str]:
        """Join a Telegram link"""
        try:
            # Clean link
            if '?' in link:
                link = link.split('?')[0]
            
            if 't.me/' not in link:
                return False, "Not a Telegram link"
            
            # Handle different types of links
            if '/joinchat/' in link or '+' in link:
                # Private group
                await self.client(JoinChannelRequest(link))
                return True, f"Joined private group: {link}"
            
            elif '/start' in link:
                # Bot with start parameter
                parts = link.split('t.me/')[1].split('/')
                if len(parts) >= 1:
                    username = parts[0]
                    
                    if username.endswith('bot'):
                        entity = await self.client.get_entity(f'@{username}')
                        
                        if len(parts) >= 3:
                            start_param = parts[2]
                            await self.client.send_message(entity, f'/start {start_param}')
                        else:
                            await self.client.send_message(entity, '/start')
                        
                        return True, f"Started bot: @{username}"
            
            else:
                # Public group/channel
                username = link.split('t.me/')[1].split('/')[0]
                entity = await self.client.get_entity(f'@{username}')
                
                if hasattr(entity, 'megagroup') or hasattr(entity, 'broadcast'):
                    await self.client(JoinChannelRequest(f'@{username}'))
                    return True, f"Joined: @{username}"
                else:
                    # Try to start chat
                    await self.client.send_message(entity, '/start')
                    return True, f"Started chat with: @{username}"
            
            return False, "Unknown link type"
            
        except Exception as e:
            logger.error(f"Failed to join link {link}: {e}")
            return False, str(e)
    
    async def send_alert(self, chat, message, clicked_buttons: List[str] = None, joined_links: List[str] = None):
        """Send alert about detected rain"""
        try:
            chat_title = getattr(chat, 'title', 'Private Chat') or 'Private Chat'
            
            sender = await message.get_sender()
            sender_name = ""
            if sender:
                first = getattr(sender, 'first_name', '')
                last = getattr(sender, 'last_name', '')
                username = getattr(sender, 'username', '')
                
                if first:
                    sender_name = first
                    if last:
                        sender_name += f" {last}"
                if username:
                    sender_name += f" (@{username})"
            
            # Format message preview
            message_text = message.text or message.raw_text or ""
            preview = message_text[:300] + ("..." if len(message_text) > 300 else "")
            
            # Build alert
            alert_lines = [
                "🚨 <b>RAIN DETECTED!</b>",
                "",
                f"<b>Chat:</b> {chat_title}",
                f"<b>From:</b> {sender_name}",
                f"<b>Time:</b> {datetime.now().strftime('%H:%M:%S')}",
                ""
            ]
            
            if clicked_buttons:
                alert_lines.append(f"<b>Buttons clicked:</b> {', '.join(clicked_buttons[:3])}")
                if len(clicked_buttons) > 3:
                    alert_lines[-1] += f" (+{len(clicked_buttons)-3} more)"
            
            if joined_links:
                alert_lines.append(f"<b>Links joined:</b> {len(joined_links)}")
            
            alert_lines.extend([
                "",
                "<b>Message:</b>",
                f"<code>{preview}</code>",
                ""
            ])
            
            # Add message link if available
            if hasattr(message, 'id'):
                alert_lines.append(f"🔗 <a href='https://t.me/c/{str(chat.id).replace('-100', '')}/{message.id}'>Jump to message</a>")
            
            alert_msg = "\n".join(alert_lines)
            
            await self.client.send_message(
                ALERT_CHANNEL,
                alert_msg,
                parse_mode='HTML',
                link_preview=False
            )
            
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
    
    async def handle_add_command(self, event, args: str):
        """Handle !add command"""
        try:
            identifier = args.strip()
            
            if identifier.isdigit() or (identifier.startswith('-100') and identifier[4:].isdigit()):
                # Numeric ID
                group_id = int(identifier)
                if not group_id < 0:
                    group_id = -1000000000000 - group_id
                
                entity = await self.client.get_entity(group_id)
                title = getattr(entity, 'title', f"Group {group_id}")
                username = getattr(entity, 'username', None)
            
            elif identifier.startswith('@'):
                # Username
                entity = await self.client.get_entity(identifier)
                group_id = entity.id
                title = getattr(entity, 'title', identifier)
                username = identifier.lstrip('@')
            
            elif 't.me/' in identifier:
                # Link
                if '/joinchat/' in identifier or '+' in identifier:
                    # Private group
                    await self.client(JoinChannelRequest(identifier))
                    entity = await self.client.get_participants(identifier, limit=1)
                    if entity:
                        group_id = entity[0].id
                        title = "Private Group"
                        username = None
                else:
                    # Public group/channel
                    username = identifier.split('t.me/')[1].split('/')[0]
                    entity = await self.client.get_entity(f'@{username}')
                    group_id = entity.id
                    title = getattr(entity, 'title', username)
            
            else:
                # Try as username without @
                entity = await self.client.get_entity(f'@{identifier}')
                group_id = entity.id
                title = getattr(entity, 'title', identifier)
                username = identifier
            
            # Add to database
            sender = await event.get_sender()
            added_by = getattr(sender, 'username', 'admin')
            
            success = db.add_group(group_id, title, username, added_by)
            
            if success:
                await event.reply(f"""✅ <b>Group Added to Monitoring</b>

<b>Name:</b> {title}
<b>ID:</b> <code>{group_id}</code>
<b>Username:</b> {f'@{username}' if username else 'N/A'}
<b>Added by:</b> @{added_by}

📊 Now monitoring: {len(db.get_monitored_groups())} groups""", parse_mode='HTML')
            else:
                await event.reply("❌ Failed to add group to database")
            
        except Exception as e:
            logger.error(f"Add command error: {e}")
            await event.reply(f"❌ Error: {str(e)[:200]}")
    
    async def handle_remove_command(self, event, args: str):
        """Handle !remove command"""
        try:
            group_id_str = args.strip()
            
            if group_id_str.isdigit() or (group_id_str.startswith('-100') and group_id_str[4:].isdigit()):
                group_id = int(group_id_str)
                if not group_id < 0:
                    group_id = -1000000000000 - group_id
            else:
                await event.reply("❌ Please provide a numeric group ID")
                return
            
            success = db.remove_group(group_id)
            
            if success:
                await event.reply(f"✅ Removed group <code>{group_id}</code> from monitoring", parse_mode='HTML')
            else:
                await event.reply("❌ Group not found in monitoring list")
            
        except Exception as e:
            logger.error(f"Remove command error: {e}")
            await event.reply(f"❌ Error: {str(e)}")
    
    async def handle_list_command(self, event):
        """Handle !list command"""
        try:
            groups = db.get_monitored_groups()
            
            if not groups:
                await event.reply("📭 No groups being monitored")
                return
            
            message_lines = ["📋 <b>Monitored Groups:</b>", ""]
            
            for i, group in enumerate(groups, 1):
                title = group['title'][:30] + "..." if len(group['title']) > 30 else group['title']
                username = f"@{group['username']}" if group['username'] else "No username"
                date_str = group['added_date'][:10] if group['added_date'] else "Unknown"
                
                message_lines.append(f"{i}. <b>{title}</b>")
                message_lines.append(f"   ID: <code>{group['id']}</code>")
                message_lines.append(f"   Username: {username}")
                message_lines.append(f"   Added: {date_str}")
                message_lines.append("")
            
            message = "\n".join(message_lines)
            
            # Split if too long
            if len(message) > 4000:
                chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
                for chunk in chunks:
                    await event.reply(chunk, parse_mode='HTML')
                    await asyncio.sleep(0.5)
            else:
                await event.reply(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"List command error: {e}")
            await event.reply(f"❌ Error: {str(e)}")
    
    async def handle_stats_command(self, event):
        """Handle !stats command"""
        try:
            stats = db.get_stats()
            total_processed = db.get_total_processed()
            monitored_groups = db.get_monitored_groups()
            
            message = f"""📊 <b>Rain Bot Statistics</b>

<b>Detection:</b>
• Rains Detected: {stats.get('rains_detected', 0)}
• Buttons Clicked: {stats.get('buttons_clicked', 0)}
• Links Joined: {stats.get('links_joined', 0)}
• Errors: {stats.get('errors', 0)}

<b>Monitoring:</b>
• Monitored Groups: {len(monitored_groups)}
• Messages Processed: {total_processed}
• Last Updated: {stats.get('last_updated', 'Never')}

<b>System:</b>
• Uptime: {int(time.time() - self.start_time)}s
• Auto-Click: {'✅ ON' if AUTO_CLICK_BUTTONS else '❌ OFF'}
• Auto-Join: {'✅ ON' if AUTO_JOIN_LINKS else '❌ OFF'}"""
            
            await event.reply(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Stats command error: {e}")
            await event.reply(f"❌ Error: {str(e)}")
    
    async def handle_help_command(self, event):
        """Handle !help command"""
        help_text = """🤖 <b>Rain Selfbot Commands</b>

<b>Group Management:</b>
<code>!add &lt;id|@username|link&gt;</code> - Add group to monitoring
<code>!remove &lt;group_id&gt;</code> - Remove group from monitoring
<code>!list</code> - List all monitored groups

<b>Bot Control:</b>
<code>!stats</code> - Show bot statistics
<code>!help</code> - Show this help
<code>!ping</code> - Check if bot is alive

<b>Examples:</b>
<code>!add -1001234567890</code>
<code>!add @crypto_rains</code>
<code>!add https://t.me/cryptogiveaways</code>
<code>!remove -1001234567890</code>

<b>Settings (configure in code):</b>
• Keywords: {keywords_count} patterns
• Auto-click buttons: {auto_click}
• Auto-join links: {auto_join}
• Reactions: {reactions}""".format(
            keywords_count=len(KEYWORDS),
            auto_click='✅ ON' if AUTO_CLICK_BUTTONS else '❌ OFF',
            auto_join='✅ ON' if AUTO_JOIN_LINKS else '❌ OFF',
            reactions='✅ ON' if SEND_REACTIONS else '❌ OFF'
        )
        
        await event.reply(help_text, parse_mode='HTML')
    
    async def handle_ping_command(self, event):
        """Handle !ping command"""
        uptime = int(time.time() - self.start_time)
        
        # Get current status
        monitored_groups = len(db.get_monitored_groups())
        stats = db.get_stats()
        
        message = f"""🏓 <b>Pong!</b>

✅ <b>Bot Status:</b> Running
⏱️ <b>Uptime:</b> {uptime}s
📊 <b>Monitored Groups:</b> {monitored_groups}
🚨 <b>Rains Detected:</b> {stats.get('rains_detected', 0)}

🔄 <b>Last Check:</b> {datetime.now().strftime('%H:%M:%S')}"""
        
        await event.reply(message, parse_mode='HTML')
    
    async def stop(self):
        """Stop the selfbot"""
        self.is_running = False
        if self.client:
            await self.client.disconnect()
        logger.info("Selfbot stopped")

# ========== FLASK ROUTES ==========
@app.route('/')
def home():
    """Home page"""
    stats = db.get_stats()
    
    html = """<!DOCTYPE html>
<html>
<head>
    <title>Telegram Rain Selfbot</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
            min-height: 100vh;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            padding: 40px;
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
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .stat-number {
            font-size: 2em;
            font-weight: bold;
            color: #667eea;
            margin: 10px 0;
        }
        .stat-label {
            color: #666;
            font-size: 0.9em;
        }
        .groups-list {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 20px;
            margin-top: 20px;
            max-height: 300px;
            overflow-y: auto;
        }
        .group-item {
            padding: 10px;
            border-bottom: 1px solid #e0e0e0;
        }
        .group-item:last-child {
            border-bottom: none;
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
        <h1>🤖 Telegram Rain Selfbot</h1>
        <div class="status">🟢 ONLINE</div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Rains Detected</div>
                <div class="stat-number">{rains_detected}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Buttons Clicked</div>
                <div class="stat-number">{buttons_clicked}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Links Joined</div>
                <div class="stat-number">{links_joined}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Monitored Groups</div>
                <div class="stat-number">{monitored_groups}</div>
            </div>
        </div>
        
        <h3>📋 Monitored Groups</h3>
        <div class="groups-list">
            {groups_list}
        </div>
        
        <div class="footer">
            <p>🚀 Running on Koyeb | Admin: {admin_id}</p>
            <p>🕒 Last Updated: {last_updated} | Uptime: {uptime}s</p>
            <p>🔗 Endpoints: /ping, /stats, /status, /health</p>
        </div>
    </div>
</body>
</html>"""
    
    # Get monitored groups
    groups = db.get_monitored_groups()
    groups_list_html = ""
    for group in groups[:10]:  # Show first 10
        title = group['title'][:30] + "..." if len(group['title']) > 30 else group['title']
        groups_list_html += f'<div class="group-item">📱 {title} (ID: {group["id"]})</div>'
    
    if not groups_list_html:
        groups_list_html = '<div class="group-item">No groups being monitored</div>'
    
    return html.format(
        rains_detected=stats.get('rains_detected', 0),
        buttons_clicked=stats.get('buttons_clicked', 0),
        links_joined=stats.get('links_joined', 0),
        monitored_groups=len(groups),
        groups_list=groups_list_html,
        admin_id=ADMIN_ID,
        last_updated=stats.get('last_updated', 'Never'),
        uptime=int(time.time() - bot_instance.start_time) if 'bot_instance' in globals() else 0
    )

@app.route('/ping')
def ping():
    """Ping endpoint"""
    return jsonify({
        "status": "pong",
        "service": "Telegram Rain Selfbot",
        "timestamp": datetime.now().isoformat(),
        "message": "Bot is running on Koyeb"
    })

@app.route('/ping1')
def ping():
    """Ping endpoint"""
    return jsonify({
        "status": "pong",
        "service": "Telegram Rain Selfbot",
        "timestamp": datetime.now().isoformat(),
        "message": "Bot is running on Koyeb"
    })

@app.route('/ping2')
def ping():
    """Ping endpoint"""
    return jsonify({
        "status": "pong",
        "service": "Telegram Rain Selfbot",
        "timestamp": datetime.now().isoformat(),
        "message": "Bot is running on Koyeb"
    })
    
    

@app.route('/stats')
def stats_endpoint():
    """Statistics endpoint"""
    stats = db.get_stats()
    groups = db.get_monitored_groups()
    
    return jsonify({
        "status": "online",
        "service": "Telegram Rain Selfbot",
        "statistics": {
            "rains_detected": stats.get('rains_detected', 0),
            "buttons_clicked": stats.get('buttons_clicked', 0),
            "links_joined": stats.get('links_joined', 0),
            "errors": stats.get('errors', 0),
            "monitored_groups": len(groups),
            "messages_processed": db.get_total_processed(),
            "last_updated": stats.get('last_updated', 'Never')
        },
        "settings": {
            "auto_click": AUTO_CLICK_BUTTONS,
            "auto_join": AUTO_JOIN_LINKS,
            "send_reactions": SEND_REACTIONS,
            "keywords_count": len(KEYWORDS),
            "button_patterns": len(CLICKABLE_BUTTON_TEXTS)
        },
        "uptime": int(time.time() - bot_instance.start_time) if 'bot_instance' in globals() else 0
    })

@app.route('/status')
def status():
    """Status endpoint"""
    is_running = 'bot_instance' in globals() and bot_instance.is_running
    
    return jsonify({
        "status": "online" if is_running else "offline",
        "bot_running": is_running,
        "timestamp": datetime.now().isoformat(),
        "admin_id": ADMIN_ID,
        "monitored_groups": len(db.get_monitored_groups()),
        "endpoints": ["/", "/ping", "/stats", "/status", "/health"]
    })

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "database": "connected",
        "session_valid": SESSION_STRING != "",
        "monitoring_active": len(db.get_monitored_groups()) > 0,
        "timestamp": datetime.now().isoformat()
    })

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


# ========== MAIN ASYNC FUNCTION ==========
async def main_async():
    """Main async function"""
    global bot_instance
    
    print("=" * 70)
    print("🚀 Starting Telegram Rain Selfbot...")
    print("=" * 70)
    
    # Check session string
    if not SESSION_STRING or SESSION_STRING == "YOUR_SESSION_STRING_HERE":
        print("❌ ERROR: TELEGRAM_SESSION_STRING not set in environment!")
        print("\nTo get your session string:")
        print("1. Run: python session_generator.py")
        print("2. Copy the generated session string")
        print("3. Set it as TELEGRAM_SESSION_STRING environment variable")
        print("4. Restart the application")
        print("=" * 70)
        return
    
    # Initialize bot
    bot_instance = TelegramRainBot(SESSION_STRING)
    
    # Start bot
    success = await bot_instance.start()
    
    if not success:
        print("❌ Failed to start bot!")
        return
    
    print("✅ Bot started successfully!")
    print("🌐 Web server running on port:", WEB_PORT)
    print("=" * 70)
    print("📋 Available Commands (in private chat with yourself):")
    print("  !add <id|@username|link>  - Add group to monitor")
    print("  !remove <group_id>         - Remove group")
    print("  !list                      - List monitored groups")
    print("  !stats                     - Show statistics")
    print("  !help                      - Show help")
    print("  !ping                      - Check if bot is alive")
    print("=" * 70)
    print("🌐 Web Endpoints:")
    print(f"  http://localhost:{WEB_PORT}/       - Dashboard")
    print(f"  http://localhost:{WEB_PORT}/ping   - Ping")
    print(f"  http://localhost:{WEB_PORT}/stats  - Statistics")
    print(f"  http://localhost:{WEB_PORT}/status - Status")
    print("=" * 70)
    
    # Keep running
    try:
        while bot_instance.is_running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping bot...")
    finally:
        await bot_instance.stop()
        print("👋 Bot stopped.")

# ========== FLASK RUNNER ==========
def run_flask():
    """Run Flask web server"""
    print(f"🌐 Starting Flask server on port {WEB_PORT}...")
    app.run(
        host='0.0.0.0',
        port=WEB_PORT,
        debug=False,
        use_reloader=False,
        threaded=True
    )

# ========== MAIN ENTRY POINT ==========
def main():
    """Main entry point"""
    # Check if we should generate session
    if len(sys.argv) > 1 and sys.argv[1] == "--generate-session":
        from session_generator import generate_session
        asyncio.run(generate_session())
        return
    
    # Create asyncio event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Run both Flask and Telegram bot
    try:
        # Start Flask in a separate thread
        import threading
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        # Run Telegram bot
        loop.run_until_complete(main_async())
        
    except KeyboardInterrupt:
        print("\n👋 Application stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        loop.close()

if __name__ == '__main__':
    main()
