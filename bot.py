import os
import sys
import sqlite3
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaVideo
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters, ChatJoinRequestHandler
)
from telegram.error import BadRequest

# ---------------- CONFIG ----------------
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", 0))
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", 0))
PORT = int(os.environ.get("PORT", 8000))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

# Validate critical variables
if not all([TOKEN, ADMIN_ID, LOG_CHANNEL, CHANNEL_ID, WEBHOOK_URL]):
    print("❌ ERROR: Missing required environment variables!")
    sys.exit(1)

# ---------------- DATABASE ----------------
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT,
    status TEXT DEFAULT 'none'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT,
    file_id TEXT
)
""")
conn.commit()

# ---------------- HELPERS ----------------
def get_videos(category):
    cursor.execute("SELECT id, file_id FROM videos WHERE category=? ORDER BY id DESC", (category,))
    return cursor.fetchall()

# ---------------- COMMAND HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cursor.execute("INSERT OR IGNORE INTO users (user_id, first_name) VALUES (?, ?)", (user.id, user.first_name))
    conn.commit()
    if LOG_CHANNEL:
        await context.bot.send_message(LOG_CHANNEL, f"👤 New user: {user.first_name} ({user.id})")
    keyboard = [[InlineKeyboardButton("✅ I am 18 or older", callback_data="age_confirm")]]
    await update.message.reply_text(
        "Welcome 🔥\n\n👉 Must be 18+ to continue.\nBy clicking below you confirm you're of legal age.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def age_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Mallu", callback_data="cat_mallu")],
        [InlineKeyboardButton("Desi", callback_data="cat_desi")],
        [InlineKeyboardButton("Trending", callback_data="cat_trending")],
        [InlineKeyboardButton("Latest", callback_data="cat_latest")],
        [InlineKeyboardButton("Premium", callback_data="cat_premium")]
    ]
    await query.edit_message_text("✅ Age confirmed!\n\nSelect a category:", reply_markup=InlineKeyboardMarkup(keyboard))

async def category_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data.replace("cat_", "").capitalize()
    keyboard = [[InlineKeyboardButton("📩 Request to Join Channel", url=f"https://t.me/{CHANNEL_ID}")]]
    await query.edit_message_text(
        f"You selected *{cat}* 🔥\n\nRequest to join the channel to access content.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data["category"] = cat
    context.user_data["page"] = 0

# ---------------- JOIN REQUEST ----------------
async def join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cursor.execute("UPDATE users SET status='pending' WHERE user_id=?", (user.id,))
    conn.commit()
    if LOG_CHANNEL:
        await context.bot.send_message(LOG_CHANNEL, f"📩 {user.first_name} ({user.id}) requested to join the channel.")

async def verify_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user.id)
        if member.status in ["member", "administrator", "creator"]:
            await send_videos(update, context)
        else:
            cursor.execute("SELECT status FROM users WHERE user_id=?", (user.id,))
            row = cursor.fetchone()
            if row and row[0] == "pending":
                await update.message.reply_text("✅ Join request detected! Access granted temporarily.")
                await send_videos(update, context)
            else:
                await update.message.reply_text("⚠️ Please request to join the channel first.")
    except BadRequest:
        await update.message.reply_text("⚠️ Cannot verify. Make sure you requested to join the channel.")

# ---------------- VIDEO SENDING ----------------
async def send_videos(update, context):
    category = context.user_data.get("category", "general")
    videos = get_videos(category)
    if not videos:
        await update.message.reply_text("⚠️ No videos in this category.")
        return
    page = context.user_data.get("page", 0)
    start, end = page*10, (page+1)*10
    batch = videos[start:end]
    media = [InputMediaVideo(file_id) for _, file_id in batch]
    if update.message:
        await update.message.reply_media_group(media)
    else:
        await update.callback_query.message.reply_media_group(media)
    buttons = []
    if page>0:
        buttons.append(InlineKeyboardButton("⬅ Previous", callback_data="prev"))
    if end < len(videos):
        buttons.append(InlineKeyboardButton("Next ➡", callback_data="next"))
    if buttons:
        if update.message:
            await update.message.reply_text("Navigation:", reply_markup=InlineKeyboardMarkup([buttons]))
        else:
            await update.callback_query.message.reply_text("Navigation:", reply_markup=InlineKeyboardMarkup([buttons]))

async def paginate(update, context):
    query = update.callback_query
    await query.answer()
    if query.data=="next":
        context.user_data["page"] = context.user_data.get("page",0)+1
    elif query.data=="prev":
        context.user_data["page"] = context.user_data.get("page",0)-1
    await send_videos(update, context)

# ---------------- ADMIN COMMANDS ----------------
async def add_video(update, context):
    if update.effective_user.id != ADMIN_ID: return
    if not update.message.video:
        await update.message.reply_text("Send a video with caption = category.")
        return
    category = update.message.caption or "general"
    file_id = update.message.video.file_id
    cursor.execute("INSERT INTO videos (category, file_id) VALUES (?, ?)", (category, file_id))
    conn.commit()
    await update.message.reply_text(f"✅ Saved video in {category}")

async def bulk_add(update, context):
    if update.effective_user.id != ADMIN_ID: return
    context.user_data["bulk_mode"] = True
    await update.message.reply_text("📩 Send multiple videos now. Use /done when finished.")

async def bulk_receive(update, context):
    if context.user_data.get("bulk_mode") and update.message.video:
        category = update.message.caption or "general"
        file_id = update.message.video.file_id
        cursor.execute("INSERT INTO videos (category, file_id) VALUES (?, ?)", (category, file_id))
        conn.commit()
        await update.message.reply_text(f"✅ Saved video in {category}")

async def bulk_done(update, context):
    if update.effective_user.id == ADMIN_ID and context.user_data.get("bulk_mode"):
        context.user_data["bulk_mode"] = False
        await update.message.reply_text("✅ Bulk adding finished.")

async def remove_video(update, context):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("Usage: /removevideo <id>")
        return
    vid_id = int(context.args[0])
    cursor.execute("DELETE FROM videos WHERE id=?", (vid_id,))
    conn.commit()
    await update.message.reply_text(f"🗑 Removed video ID {vid_id}")

async def stats(update, context):
    if update.effective_user.id != ADMIN_ID: return
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    await update.message.reply_text(f"📊 Users: {total_users}")

async def restart(update, context):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("♻ Restarting bot...")
        os.execv(sys.executable, ["python"] + sys.argv)

# ---------------- APPLICATION ----------------
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(age_confirm, pattern="age_confirm"))
app.add_handler(CallbackQueryHandler(category_select, pattern="cat_"))
app.add_handler(CallbackQueryHandler(paginate, pattern="^(next|prev)$"))
app.add_handler(CommandHandler("verify", verify_and_send))

# Video management
app.add_handler(CommandHandler("addvideo", add_video))
app.add_handler(CommandHandler("bulkadd", bulk_add))
app.add_handler(CommandHandler("done", bulk_done))
app.add_handler(CommandHandler("removevideo", remove_video))
app.add_handler(MessageHandler(filters.VIDEO & ~filters.COMMAND, bulk_receive))

# Admin
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("restart", restart))

# Join requests
app.add_handler(ChatJoinRequestHandler(join_request, CHANNEL_ID))

# ---------------- RUN WEBHOOK ----------------
app.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path=TOKEN,
    webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
)
