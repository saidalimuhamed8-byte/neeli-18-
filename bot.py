import os
import sqlite3
import logging
import asyncio
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.error import BadRequest

# ------------------ CONFIG ------------------
TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # Only for webhook deployments
PORT = int(os.environ.get("PORT", 8000))
DATABASE = "bot.db"

# Channels to force subscription (use username or ID)
FORCE_CHANNELS = ["@YourChannelUsername1", "@YourChannelUsername2"]

# ------------------ LOGGING ------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# ------------------ DATABASE ------------------
conn = sqlite3.connect(DATABASE)
c = conn.cursor()
c.execute(
    """CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT
    )"""
)
c.execute(
    """CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id TEXT,
        caption TEXT
    )"""
)
conn.commit()

# ------------------ FORCE SUBSCRIPTION ------------------
async def is_user_subscribed(user_id, app):
    """Check if the user is a member of all required channels."""
    for channel in FORCE_CHANNELS:
        try:
            member = await app.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ["kicked", "left"]:
                return False
        except BadRequest:
            return False
    return True

async def force_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check subscription, return True if subscribed."""
    user_id = update.effective_user.id
    if not await is_user_subscribed(user_id, context.application):
        buttons = [
            [InlineKeyboardButton(f"Join {ch}", url=f"https://t.me/{ch.replace('@','')}")]
            for ch in FORCE_CHANNELS
        ]
        await update.effective_message.reply_text(
            "You must join the required channels to use this bot:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return False
    return True

# ------------------ HANDLERS ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await force_subscribe(update, context):
        return
    user = update.effective_user
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (user.id, user.username))
    conn.commit()
    await update.message.reply_text(
        "Welcome! Use /bulkadd or /removevideo to manage videos."
    )

async def bulk_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await force_subscribe(update, context):
        return
    if not update.message.video:
        await update.message.reply_text("Please send videos with this command.")
        return
    file_id = update.message.video.file_id
    caption = update.message.caption or ""
    c.execute("INSERT INTO videos (file_id, caption) VALUES (?,?)", (file_id, caption))
    conn.commit()
    await update.message.reply_text("Video added successfully!")

async def remove_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await force_subscribe(update, context):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /removevideo <video_id>")
        return
    vid_id = args[0]
    c.execute("DELETE FROM videos WHERE id=?", (vid_id,))
    conn.commit()
    await update.message.reply_text(f"Video {vid_id} removed successfully!")

async def list_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await force_subscribe(update, context):
        return
    c.execute("SELECT id, caption FROM videos")
    rows = c.fetchall()
    if not rows:
        await update.message.reply_text("No videos available.")
        return
    msg = "\n".join([f"{r[0]} - {r[1]}" for r in rows])
    await update.message.reply_text(msg)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text=f"Button pressed: {query.data}")

# ------------------ MAIN ------------------
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bulkadd", bulk_add))
    app.add_handler(CommandHandler("removevideo", remove_video))
    app.add_handler(CommandHandler("listvideos", list_videos))
    app.add_handler(CallbackQueryHandler(button_callback))

    # Decide webhook or polling based on WEBHOOK_URL
    if WEBHOOK_URL:
        await app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
        )
    else:
        await app.start()
        await app.updater.start_polling()
        await app.updater.idle()

# ------------------ RUN ------------------
if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(main())
        else:
            loop.run_until_complete(main())
    except Exception as e:
        logging.error(f"Error running bot: {e}")
