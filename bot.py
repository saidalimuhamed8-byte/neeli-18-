import os
import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------- CONFIG ----------------
TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8000))

ADMINS = [123456789]  # Telegram user IDs of admins

if not TOKEN:
    raise ValueError("BOT_TOKEN is not set!")

# ---------------- LOGGING ----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- DATABASE ----------------
conn = sqlite3.connect("bot.db")
cursor = conn.cursor()
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT UNIQUE
)
"""
)
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE
)
"""
)
conn.commit()

# ---------------- HELPERS ----------------
async def force_sub(update: Update) -> bool:
    """Check if user has joined required channels. Always True for now."""
    return True

def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

# ---------------- COMMANDS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
    conn.commit()
    if not await force_sub(update):
        return
    await update.message.reply_text(
        "Welcome! Use /bulkadd to add videos, /removevideo to delete, /listvideos to see all, /stats for info."
    )

# ---------------- BULK ADD VIDEOS ----------------
async def bulk_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can add videos.")
        return

    media_group_id = update.message.media_group_id
    videos_to_add = []

    if update.message.video:
        videos_to_add.append(update.message.video.file_id)
    
    if media_group_id:
        group = context.bot_data.get(media_group_id, [])
        group.append(update.message)
        context.bot_data[media_group_id] = group

        for msg in group:
            if msg.video:
                videos_to_add.append(msg.video.file_id)

    if not videos_to_add:
        await update.message.reply_text("Send video(s) to add.")
        return

    added_count = 0
    for file_id in videos_to_add:
        try:
            cursor.execute("INSERT OR IGNORE INTO videos(file_id) VALUES(?)", (file_id,))
            conn.commit()
            added_count += 1
        except Exception as e:
            logger.error(f"Error adding video {file_id}: {e}")

    await update.message.reply_text(f"✅ Added {added_count} video(s) successfully!")

# ---------------- REMOVE VIDEO ----------------
async def remove_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can remove videos.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /removevideo <file_id>")
        return
    file_id = args[0]
    cursor.execute("DELETE FROM videos WHERE file_id=?", (file_id,))
    conn.commit()
    await update.message.reply_text(f"✅ Removed video: {file_id}")

# ---------------- LIST VIDEOS ----------------
async def list_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT file_id FROM videos")
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("No videos in database.")
        return
    msg = "\n".join([r[0] for r in rows])
    await update.message.reply_text(f"📁 Videos:\n{msg}")

# ---------------- STATS ----------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM videos")
    videos_count = cursor.fetchone()[0]
    await update.message.reply_text(f"👥 Users: {users_count}\n🎬 Videos: {videos_count}")

# ---------------- MAIN ----------------
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bulkadd", bulk_add))
    app.add_handler(CommandHandler("removevideo", remove_video))
    app.add_handler(CommandHandler("listvideos", list_videos))
    app.add_handler(CommandHandler("stats", stats))

    # Video handler for media groups
    app.add_handler(MessageHandler(filters.Video.ALL, bulk_add))

    # Deploy webhook if WEBHOOK_URL is set, else start polling
    if WEBHOOK_URL:
        await app.start_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{TOKEN}",
        )
        await app.updater.start_polling()
    else:
        await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
