import os
import sqlite3
import logging
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaVideo
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from telegram.error import BadRequest

# ---------------- CONFIG ----------------
TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # e.g., https://<your-domain>.onrender.com
PORT = int(os.environ.get("PORT", 8000))

ADMIN_IDS = [8301447343]  # replace with your ID
DB_FILE = "bot.db"
LOG_CHANNEL = -1002871565651  # replace with your log channel ID

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- DATABASE ----------------
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT,
    file_id TEXT
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS fsub_channel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invite_link TEXT
)
""")
conn.commit()

# ---------------- HELPERS ----------------
def add_video_to_db(category, file_id):
    cursor.execute("INSERT INTO videos (category, file_id) VALUES (?, ?)", (category, file_id))
    conn.commit()

def get_videos(category):
    cursor.execute("SELECT file_id FROM videos WHERE category=? ORDER BY id DESC", (category,))
    return [r[0] for r in cursor.fetchall()]

def set_fsub_channel(invite_link):
    cursor.execute("DELETE FROM fsub_channel")
    cursor.execute("INSERT INTO fsub_channel (invite_link) VALUES (?)", (invite_link,))
    conn.commit()

def get_fsub_channel():
    cursor.execute("SELECT invite_link FROM fsub_channel ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    return row[0] if row else None

# ---------------- HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cursor.execute("INSERT OR IGNORE INTO users (user_id, first_name) VALUES (?, ?)", (user.id, user.first_name))
    conn.commit()
    if LOG_CHANNEL:
        await context.bot.send_message(LOG_CHANNEL, f"👤 New user: {user.first_name} ({user.id})")
    categories = ["Mallu", "Desi", "Trending", "Latest", "Premium"]
    keyboard = [[InlineKeyboardButton(cat, callback_data=f"cat_{cat}")] for cat in categories]
    await update.message.reply_text(
        "Welcome 🔥\nSelect a category to start:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def category_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("cat_", "")
    context.user_data["category"] = category
    context.user_data["page"] = 0
    invite_link = get_fsub_channel()
    if invite_link:
        keyboard = [
            [InlineKeyboardButton("📢 Join Channel", url=invite_link)],
            [InlineKeyboardButton("✅ I Joined / Continue", callback_data="continue")]
        ]
        await query.edit_message_text("⚠️ Please join the channel first:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await send_videos(update, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "continue":
        category = context.user_data.get("category")
        await send_videos(update, context)
        return

    if ":" in query.data:
        category, page = query.data.split(":")
        context.user_data["category"] = category
        context.user_data["page"] = int(page)
        await send_videos(update, context)

async def send_videos(update, context):
    category = context.user_data.get("category", "general")
    page = context.user_data.get("page", 0)
    videos = get_videos(category)
    if not videos:
        await (update.message or update.callback_query.message).reply_text("⚠️ No videos available.")
        return

    start_idx, end_idx = page*10, (page+1)*10
    batch = videos[start_idx:end_idx]
    media = [InputMediaVideo(file_id=vid) for vid in batch]

    if update.message:
        await update.message.reply_media_group(media)
    else:
        await update.callback_query.message.reply_media_group(media)

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅ Previous", callback_data=f"{category}:{page-1}"))
    if end_idx < len(videos):
        buttons.append(InlineKeyboardButton("Next ➡", callback_data=f"{category}:{page+1}"))
    if buttons:
        await (update.message or update.callback_query.message).reply_text(
            "Navigation:", reply_markup=InlineKeyboardMarkup([buttons])
        )

# ---------------- ADMIN ----------------
async def addvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not update.message.video:
        await update.message.reply_text("Send a video with caption = category")
        return
    category = update.message.caption or "general"
    add_video_to_db(category, update.message.video.file_id)
    await update.message.reply_text(f"✅ Video added to {category}")

async def bulkadd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /bulkadd <category>")
        return
    context.user_data["bulk_mode"] = True
    context.user_data["bulk_category"] = context.args[0]
    await update.message.reply_text(f"📤 Send multiple videos for `{context.args[0]}`, then /done")

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("bulk_mode", None)
    context.user_data.pop("bulk_category", None)
    await update.message.reply_text("✅ Bulk add finished.")

async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("bulk_mode"):
        category = context.user_data["bulk_category"]
        add_video_to_db(category, update.message.video.file_id)
    elif "adding_category" in context.user_data:
        category = context.user_data.pop("adding_category")
        add_video_to_db(category, update.message.video.file_id)
        await update.message.reply_text(f"✅ Video added to {category}")

async def removevideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if len(context.args) != 2 or not context.args[1].isdigit():
        await update.message.reply_text("Usage: /removevideo <category> <index>")
        return
    category, index = context.args[0], int(context.args[1])
    videos = get_videos(category)
    if 0 <= index < len(videos):
        file_id = videos[index]
        cursor.execute("DELETE FROM videos WHERE file_id=?", (file_id,))
        conn.commit()
        await update.message.reply_text(f"🗑️ Removed video {index} from {category}")
    else:
        await update.message.reply_text("⚠️ Invalid index or category")

async def fsub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /fsub <invite_link>")
        return
    set_fsub_channel(context.args[0])
    await update.message.reply_text(f"✅ Force sub channel set: {context.args[0]}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    await update.message.reply_text(f"📊 Total users: {total_users}")

# ---------------- APPLICATION ----------------
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(category_select, pattern="^cat_"))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(CommandHandler("addvideo", addvideo))
app.add_handler(CommandHandler("bulkadd", bulkadd))
app.add_handler(CommandHandler("done", done))
app.add_handler(MessageHandler(filters.VIDEO, video_handler))
app.add_handler(CommandHandler("removevideo", removevideo))
app.add_handler(CommandHandler("fsub", fsub))
app.add_handler(CommandHandler("stats", stats))

# ---------------- RUN WEBHOOK ----------------
if WEBHOOK_URL:
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
    )
else:
    app.run_polling()
