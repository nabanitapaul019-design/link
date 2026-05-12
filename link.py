"""
Telethon Last 5 Messages Fetcher Bot (Fixed)
- Home reply keyboard: [ START ] [ LIST ]
- LIST: shows inline chat pages (Prev/Next)
- Selecting a chat fetches and displays the last 5 messages from that chat
"""

import asyncio
import os
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --------- CONFIG ----------
BOT_TOKEN = "7571130670:AAGZsaxxoB9EOG1kvRZRuqrpIpHQ5NVPNN8"
API_ID = 27400429
API_HASH = "e4585a30e42079fef123da0c70b5e5a6"
TELETHON_SESSION = "user_session"
TEMP_DIR = "temp_downloads"
# ---------------------------

# Create temp directory for media downloads
os.makedirs(TEMP_DIR, exist_ok=True)

tele_client = TelegramClient(TELETHON_SESSION, API_ID, API_HASH)
bot_sessions = {}
ITEMS_PER_PAGE = 30


async def ensure_telethon():
    """Ensure Telethon client is connected and authorized."""
    if not tele_client.is_connected():
        await tele_client.connect()
    if not await tele_client.is_user_authorized():
        print("\n🔐 LOGIN REQUIRED")
        phone = input("Enter phone with country code: ")
        await tele_client.send_code_request(phone)
        code = input("Enter the login code: ")
        try:
            await tele_client.sign_in(phone, code)
        except SessionPasswordNeededError:
            pwd = input("Enter 2FA password: ")
            await tele_client.sign_in(password=pwd)


async def post_init(application: Application):
    """Initialize Telethon client when bot starts."""
    await ensure_telethon()


# ------------------ BOT HELPERS ------------------

def home_keyboard():
    """Return home reply keyboard."""
    return ReplyKeyboardMarkup([["START", "LIST"]], resize_keyboard=True)


# ------------------ BOT COMMANDS & HANDLERS ------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    uid = update.effective_user.id
    bot_sessions[uid] = {"msg_ids": []}
    msg = await update.message.reply_text("✅ Bot Ready. Press LIST to select a chat.", reply_markup=home_keyboard())
    bot_sessions[uid]["msg_ids"] = [msg.id]


async def list_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show list of chats as inline keyboard with pagination."""
    uid = update.effective_user.id
    session = bot_sessions.get(uid, {})
    prev_msg_ids = session.get("msg_ids", [])
    chat_id = update.effective_chat.id

    # Clean up previous tracked messages
    for msg_id in prev_msg_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

    # Hide reply keyboard and show fetching message
    fetching_msg = await update.message.reply_text("⏳ Fetching chats...", reply_markup=ReplyKeyboardRemove())

    chats = []
    async for dialog in tele_client.iter_dialogs():
        name = dialog.name or str(dialog.id)
        chats.append((dialog.id, name))

    bot_sessions[uid] = {
        "chats": chats,
        "page": 0,
        "temp_msg_ids": [fetching_msg.id],
        "page_msg_id": None,
    }

    await send_chat_page(update, uid, context)


async def send_chat_page(chat_or_update, uid, context: ContextTypes.DEFAULT_TYPE):
    """Send a page of chats as inline keyboard."""
    data = bot_sessions.get(uid, {})
    chats = data.get("chats", [])
    page = data.get("page", 0)

    if isinstance(chat_or_update, Update):
        target = chat_or_update.message
    else:
        target = chat_or_update

    if not chats:
        msg = await target.reply_text("❌ No chats found.", reply_markup=home_keyboard())
        data.setdefault("msg_ids", []).append(msg.id)
        bot_sessions[uid] = data
        return

    # Delete previous inline page message if exists
    prev_page_msg_id = data.get("page_msg_id")
    if prev_page_msg_id:
        try:
            await context.bot.delete_message(chat_id=target.chat_id, message_id=prev_page_msg_id)
        except Exception:
            pass

    start_index = page * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
    sliced = chats[start_index:end_index]

    keyboard = []
    for chat_id, name in sliced:
        label = (name[:57] + "...") if len(name) > 60 else name
        keyboard.append([InlineKeyboardButton(label, callback_data=f"SEL:{chat_id}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data="PREV"))
    if end_index < len(chats):
        nav.append(InlineKeyboardButton("Next ▶️", callback_data="NEXT"))
    if nav:
        keyboard.append(nav)

    msg = await target.reply_text("📍 Select a chat to fetch last 5 messages:", reply_markup=InlineKeyboardMarkup(keyboard))
    data["page_msg_id"] = msg.id
    data.setdefault("temp_msg_ids", []).append(msg.id)
    bot_sessions[uid] = data


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks (pagination & chat selection)."""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data
    session = bot_sessions.get(uid, {})

    if data == "NEXT":
        session["page"] = session.get("page", 0) + 1
        bot_sessions[uid] = session
        await send_chat_page(query.message, uid, context)

    elif data == "PREV":
        session["page"] = max(0, session.get("page", 0) - 1)
        bot_sessions[uid] = session
        await send_chat_page(query.message, uid, context)

    elif data.startswith("SEL:"):
        chat_id = int(data.split(":", 1)[1])
        session["selected"] = chat_id

        try:
            await query.edit_message_text("⏳ Fetching last 5 messages...", reply_markup=None)
        except Exception:
            await query.message.reply_text("⏳ Fetching last 5 messages...")

        await fetch_and_send_last_5(query.from_user.id, chat_id, context)

        bot_sessions[uid] = {}
        try:
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text="✅ Done. What next?",
                reply_markup=home_keyboard()
            )
        except Exception:
            await query.message.reply_text("✅ Done. What next?", reply_markup=home_keyboard())


async def fetch_and_send_last_5(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Fetch last 5 messages from chat and forward them to user."""
    try:
        entity = await tele_client.get_entity(chat_id)
    except Exception as e:
        await context.bot.send_message(chat_id=user_id, text=f"❌ Could not access chat: {str(e)}", reply_markup=home_keyboard())
        return

    name = getattr(entity, "title", None) or getattr(entity, "username", None) or str(chat_id)

    messages = []
    async for msg in tele_client.iter_messages(entity, limit=5, reverse=False):
        messages.append(msg)

    messages.reverse()  # Newest first

    if not messages:
        await context.bot.send_message(chat_id=user_id, text=f"ℹ️ No messages found in: {name}", reply_markup=home_keyboard())
        return

    await context.bot.send_message(chat_id=user_id, text=f"📨 Last 5 messages from: {name}")

    for msg in messages:
        try:
            await forward_message_to_user(msg, user_id, context)
            await asyncio.sleep(0.3)
        except Exception as e:
            await context.bot.send_message(chat_id=user_id, text=f"⚠️ Could not forward: {str(e)[:100]}")


async def forward_message_to_user(msg: Message, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Forward a Telethon message to the user via python-telegram-bot."""
    # Send text/caption
    text = msg.text or msg.caption or ""
    if text:
        if len(text) > 4000:
            text = text[:3997] + "..."
        await context.bot.send_message(chat_id=user_id, text=f"📝 {text}")

    # Handle media
    if msg.media:
        try:
            if isinstance(msg.media, MessageMediaPhoto):
                # Photo
                path = await msg.download_media(file=TEMP_DIR)
                await context.bot.send_photo(chat_id=user_id, photo=open(path, 'rb'))
                if os.path.exists(path):
                    os.remove(path)

            elif isinstance(msg.media, MessageMediaDocument):
                # Document, video, audio, etc.
                doc = msg.media.document
                if not doc:
                    return
                # Optional: skip large files (>50MB)
                if doc.size and doc.size > 50 * 1024 * 1024:
                    await context.bot.send_message(chat_id=user_id, text="⚠️ File too large to forward (>50MB)")
                    return
                path = await msg.download_media(file=TEMP_DIR)
                caption = msg.caption or "📎 File"
                # Try to detect media type for better sending
                mime_type = getattr(doc, 'mime_type', '')
                if mime_type.startswith('video/'):
                    await context.bot.send_video(chat_id=user_id, video=open(path, 'rb'), caption=caption)
                elif mime_type.startswith('audio/'):
                    await context.bot.send_audio(chat_id=user_id, audio=open(path, 'rb'), caption=caption)
                elif mime_type.startswith('image/'):
                    await context.bot.send_photo(chat_id=user_id, photo=open(path, 'rb'), caption=caption)
                else:
                    await context.bot.send_document(chat_id=user_id, document=open(path, 'rb'), caption=caption)
                if os.path.exists(path):
                    os.remove(path)
        except Exception as e:
            await context.bot.send_message(chat_id=user_id, text=f"⚠️ Media error: {str(e)[:100]}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reply keyboard button presses."""
    text = (update.message.text or "").strip().upper()
    uid = update.effective_user.id

    if text == "START":
        bot_sessions[uid] = {"msg_ids": []}
        msg = await update.message.reply_text("✅ Bot Ready. Press LIST to select a chat.", reply_markup=home_keyboard())
        bot_sessions[uid]["msg_ids"] = [msg.id]

    elif text == "LIST":
        await list_chats(update, context)

    else:
        await update.message.reply_text("🤔 Use START or LIST buttons.", reply_markup=home_keyboard())


# ------------------ MAIN ------------------

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("✅ Bot Started - Fetch Last 5 Messages Mode")
    app.run_polling()


if __name__ == "__main__":
    main()
