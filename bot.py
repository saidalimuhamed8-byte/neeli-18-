import os
import sqlite3
import logging
import asyncio
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaVideo
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest

# ---------- Config ----------
TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8000))

ADMIN_IDS = [8301447343]  # Replace with your Telegram ID
DB_FILE = "bot.db"
LOG_CHANNEL_ID = -1002871565651  # Replace with your log channel ID

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- Database ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS chats (chat_id INTEGER PRIMARY KEY, type TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS videos (category TEXT, file_id TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS stats_shown (user_id INTEGER PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS fsub_channel (id INTEGER PRIMARY KEY AUTOINCREMENT, invite_link TEXT)")
    conn.commit()
    conn.close()
init_db()

# ---------- Fsub helpers ----------
def set_fsub_channel(invite_link: str):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM fsub_channel")
    cur.execute("INSERT INTO fsub_channel (invite_link) VALUES (?)", (invite_link,))
    conn.commit()
    conn.close()

def get_fsub_channel():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, invite_link FROM fsub_channel ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row if row else (0, None)

async def send_join_prompt(update, context):
    _, invite_link = get_fsub_channel()
    if not invite_link:
        return False
    keyboard = [
        [InlineKeyboardButton("📢 Join Channel", url=invite_link)],
        [InlineKeyboardButton("✅ I Joined / Continue", callback_data="continue")]
    ]
    kb = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text("⚠️ Please join the channel first:", reply_markup=kb)
    elif update.callback_query:
        await update.callback_query.message.reply_text("⚠️ Please join the channel first:", reply_markup=kb)
    return True

# ---------- Chat tracking ----------
def save_chat(chat_id, chat_type):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO chats (chat_id, type) VALUES (?, ?)", (chat_id, chat_type))
    conn.commit()
    conn.close()

# ---------- Video helpers ----------
def add_video(category, file_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT INTO videos (category, file_id) VALUES (?, ?)", (category, file_id))
    conn.commit()
    conn.close()

def remove_video(category, index):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT rowid, file_id FROM videos WHERE category = ?", (category,))
    rows = cur.fetchall()
    if 0 <= index < len(rows):
        rowid, _ = rows[index]
        cur.execute("DELETE FROM videos WHERE rowid = ?", (rowid,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def get_videos(category):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT file_id FROM videos WHERE category = ?", (category,))
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.effective_chat.id, update.effective_chat.type)
    categories = ["mallu", "latest", "desi"]
    keyboard = [[InlineKeyboardButton(cat.title(), callback_data=f"{cat}:0")] for cat in categories]
    await update.message.reply_text("📂 Choose a category:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_data = context.user_data

    if query.data == "continue":
        _, _ = get_fsub_channel()
        user_data["joined_version"] = True
        if "pending_category" in user_data:
            category = user_data.pop("pending_category")
            await send_videos_after_join(query, context, category, 0)
        return

    if ":" in query.data:
        category, page_str = query.data.split(":")
        page = int(page_str)

        if not user_data.get("joined_version"):
            user_data["pending_category"] = category
            await send_join_prompt(update, context)
        else:
            await send_videos_after_join(query, context, category, page)

async def send_videos_after_join(query, context, category, page):
    videos = get_videos(category)
    if not videos:
        await query.message.reply_text("⚠️ No videos available in this category.")
        return

    start_idx, end_idx = page * 10, (page + 1) * 10
    chunk = videos[start_idx:end_idx]
    media_group = [InputMediaVideo(vid) for vid in chunk]
    try:
        await context.bot.send_media_group(chat_id=query.from_user.id, media=media_group)
    except BadRequest:
        for vid in chunk:
            await context.bot.send_video(chat_id=query.from_user.id, video=vid)

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"{category}:{page-1}"))
    if end_idx < len(videos):
        buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"{category}:{page+1}"))
    if buttons:
        await context.bot.send_message(chat_id=query.from_user.id, text="📺 Navigate:", reply_markup=InlineKeyboardMarkup([buttons]))

async def add_video_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("⛔ Not authorized")
    if len(context.args) != 1:
        return await update.message.reply_text("Usage: /addvideo <category>")
    context.user_data["adding_category"] = context.args[0]
    await update.message.reply_text(f"📤 Send a video to add to `{context.args[0]}`", parse_mode="Markdown")

async def bulkadd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("⛔ Not authorized")
    if len(context.args) != 1:
        return await update.message.reply_text("Usage: /bulkadd <category>")
    context.user_data["bulk_category"] = context.args[0]
    context.user_data["bulk_mode"] = True
    await update.message.reply_text(f"📤 Bulk mode started for `{context.args[0]}`. Send videos, then /done", parse_mode="Markdown")

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("bulk_mode"):
        context.user_data.pop("bulk_mode")
        context.user_data.pop("bulk_category", None)
        await update.message.reply_text("✅ Bulk add finished.")

async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "adding_category" in context.user_data:
        category = context.user_data.pop("adding_category")
        add_video(category, update.message.video.file_id)
        await update.message.reply_text(f"✅ Video added to `{category}`", parse_mode="Markdown")
    elif context.user_data.get("bulk_mode"):
        category = context.user_data["bulk_category"]
        add_video(category, update.message.video.file_id)

async def removevideo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("⛔ Not authorized")
    if len(context.args) != 2 or not context.args[1].isdigit():
        return await update.message.reply_text("Usage: /removevideo <category> <index>")
    category, index = context.args[0], int(context.args[1])
    if remove_video(category, index):
        await update.message.reply_text(f"🗑️ Removed video {index} from `{category}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ Invalid category or index")

async def fsub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("⛔ Not authorized")
    if len(context.args) != 1:
        return await update.message.reply_text("Usage: /fsub <invite_link>")
    set_fsub_channel(context.args[0])
    await update.message.reply_text(f"✅ Force sub channel set to `{context.args[0]}`", parse_mode="Markdown")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM stats_shown WHERE user_id = ?", (uid,))
    if cur.fetchone():
        conn.close()
        return
    cur.execute("INSERT INTO stats_shown (user_id) VALUES (?)", (uid,))
    conn.commit()
    conn.close()

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM chats WHERE type = 'private'")
    user_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM chats WHERE type != 'private'")
    group_count = cur.fetchone()[0]
    conn.close()

    msg = f"📊 Bot Stats:\n👤 Users: {user_count}\n👥 Groups: {group_count}"
    await update.message.reply_text(msg)

    try:
        await context.bot.send_message(LOG_CHANNEL_ID, f"📊 Stats requested by {uid}\n{msg}")
    except Exception as e:
        logger.error(f"Failed to log stats: {e}")

async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat(update.chat_member.chat.id, update.chat_member.chat.type)

# ---------- Main ----------
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addvideo", add_video_cmd))
    app.add_handler(CommandHandler("bulkadd", bulkadd_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("removevideo", removevideo_cmd))
    app.add_handler(CommandHandler("fsub", fsub_command))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.VIDEO, video_handler))
    app.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))

    if WEBHOOK_URL:
        await app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
        )
    else:
        await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
