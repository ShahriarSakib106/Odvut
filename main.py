import os
import secrets
import threading
import asyncio
import time
import json
from threading import Event
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
# Your code that uses the 'build' function
from collections import defaultdict
from flask import Flask
from telegram.constants import ParseMode  # Adjusting the import based on the new structure
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ContextTypes
)

# Initialize Flask
keep_running = Event()
server = Flask(__name__)

@server.route('/')
def home():
    return "🟢 Bot is ONLINE", 200

# Telegram Bot Functions (keep all your existing handlers)

# Initialize message limiter
class MessageLimiter:
    def __init__(self):
        self.user_messages = defaultdict(list)

    def check_limit(self, user_id, max_messages=3, period_seconds=60):
        now = datetime.now()
        self.user_messages[user_id] = [t for t in self.user_messages[user_id] if (now - t).seconds < period_seconds]
        if len(self.user_messages[user_id]) < max_messages:
            self.user_messages[user_id].append(now)
            return True
        return False

message_limiter = MessageLimiter()

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_USERNAME = "@ShahriarSakib"
ADMIN_CHAT_ID = 5512534898

# Google Sheets Configuration
SPREADSHEET_ID = '1r_zR236RAp-Pf1GduE--M89BM-I8wYlqOqMWj6ldiRI'
SHEET_RANGE = "'Sheet1'!A:D"
FORM_URL = "https://forms.gle/YOUR_GOOGLE_FORM_LINK"
service_info = json.loads(os.environ['GOOGLE_SERVICE_JSON'])
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Initialize Google Sheets credentials
creds = service_account.Credentials.from_service_account_info(service_info, scopes=SCOPES)

# Store user states and messages
user_states = {}
user_messages = {}

def get_main_menu():
    """Return the main menu with buttons"""
    keyboard = [
        [InlineKeyboardButton("📌 Rules", callback_data="rules")],
        [InlineKeyboardButton("📝 Admission Form", callback_data='form')],
        [InlineKeyboardButton("🆔 KYC Check", callback_data="kyc_check")],
        [InlineKeyboardButton("💳 Payment Info", callback_data="payment_info")],
        [InlineKeyboardButton("📞 Contact Us", callback_data="contact_admin")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_msg = (
        f"Hello {update.effective_user.first_name}!\n\n"
        "Welcome to *Odvut Info Bot*. Please choose an option below:"
    )
    
    await update.message.reply_text(
        welcome_msg,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu()
    )

async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display rules with checkboxes"""
    query = update.callback_query
    await query.answer()
    
    rules_text = """
📜 *VERIFICATION REQUIREMENTS*

✅ *MUST HAVE*
1. A public Telegram username (@yourname)
2. Clear profile photo (not default)
3. Facebook link in bio (must be 2+ years old)
4. Matching name & photo across all platforms

🚫 *PROHIBITED*
1. No blank/private profiles
2. No recently created accounts
3. No mismatched information
4. No VPN/proxy connections

⚠️ *NOTE*
- Fake profiles will be banned permanently
- All info must match your government ID
"""
    await query.edit_message_text(
        rules_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Admission Form", callback_data='form')],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data='back')]
        ])
    )

def check_kyc_status(username):
    """Check user's KYC status from Google Sheets"""
    try:
        service = build('sheets', 'v4', credentials=creds)
        sheet = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=SHEET_RANGE
        ).execute()
        values = sheet.get('values', [])
        
        for row in values:
            if username.lower().lstrip('@') == row[0].lower().lstrip('@'):
                status = row[1].strip().upper() if len(row) > 1 and row[1].strip() else ""
                reason = row[2] if len(row) > 2 and row[2].strip() else "No reason provided"
                
                if not status:
                    return {'verified': None, 'reason': "Under review"}
                return {
                    'verified': status == 'VERIFIED',
                    'reason': reason
                }
        return {'verified': False, 'reason': 'Not found in database'}
    except Exception as e:
        print(f"Sheet error: {e}")
        return {'verified': None, 'reason': "Error accessing database"}

async def kyc_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle KYC check with duplicate message prevention"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    username = user.username or f"user_{user.id}"
    status = check_kyc_status(username)
    
    # Generate new message content
    if status['verified'] is None:
        new_message = (
            "⏳ *KYC Status*\n\n"
            "Your verification is under review.\n"
            "Please check back later."
        )
        new_buttons = [
            [InlineKeyboardButton("🔄 Refresh", callback_data='kyc_check')],
            [InlineKeyboardButton("🔙 Back", callback_data='back')]
        ]
    elif not status['verified']:
        new_message = (
            f"🔍 *KYC Status for* @{username}\n\n"
            f"• Status: Not Verified\n"
            f"• Reason: {status['reason']}\n\n"
            "Please complete verification again"
        )
        new_buttons = [
            [InlineKeyboardButton("📝 Submit Verification", url=FORM_URL)],
            [InlineKeyboardButton("🔄 Refresh Status", callback_data='kyc_check')],
            [InlineKeyboardButton("🔙 Back", callback_data='back')]
        ]
    else:
        new_message = (
            f"✅ *KYC Verified*\n\n"
            f"Congratulations @{username}!\n"
            "Your account has been successfully verified."
        )
        new_buttons = [
            [InlineKeyboardButton("💳 Proceed to Payment", callback_data='payment')],
            [InlineKeyboardButton("🔙 Back", callback_data='back')]
        ]

    # Only edit if content has changed
    current_text = query.message.text
    current_markup = query.message.reply_markup
    
    try:
        # Convert new buttons to comparable format
        new_markup = InlineKeyboardMarkup(new_buttons)
        
        if (current_text != new_message) or (str(current_markup) != str(new_markup)):
            await query.edit_message_text(
                text=new_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=new_markup
            )
        else:
            await query.answer("✅ Status is already up-to-date")
    except Exception as e:
        print(f"KYC check error: {e}")
        await query.answer("⚠️ Could not update status")

async def show_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admission form with proper formatting"""
    query = update.callback_query
    await query.answer()  # Always answer callback queries
    
    form_text = (
        "📝 *Admission Form*\n\n"
        "Please fill out the form carefully with accurate information.\n"
        "All fields are required for verification.\n\n"
        f"[Click here to access the form]({FORM_URL})"
    )
    
    await query.edit_message_text(
        form_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ I've Submitted", callback_data='back')],
            [InlineKeyboardButton("🔙 Back", callback_data='back')]
        ])
    )

async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment button click"""
    query = update.callback_query
    await query.answer()  # This stops the loading animation
    
    try:
        user = query.from_user
        secret_code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
        
        context.user_data['payment_code'] = secret_code

        user_message = (
            "✅ *Payment Verification*\n\n"
            f"🔐 Your code: `{secret_code}`\n\n"
            f"Send this to {ADMIN_USERNAME}"
        )

        admin_message = (
            f"🆕 Payment Request from @{user.username}\n"
            f"🔢 Code: `{secret_code}`\n"
            f"🆔 User ID: {user.id}"
        )

        await query.edit_message_text(
            text=user_message,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data='back')],
                [InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME[1:]}")]
            ])
        )
        
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
    except Exception as e:
        print(f"Payment error: {e}")
        await query.edit_message_text("⚠️ Payment processing failed. Please try again.")

async def show_payment_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show payment instructions"""
    query = update.callback_query
    await query.answer()  # This stops the loading animation
    
    payment_text = (
        "💳 *Payment Instructions*\n\n"
        "1. Complete your KYC verification first\n"
        "2. Payment methods available:\n"
        "   - Cryptocurrency (USDT)\n"
        "3. Contact admin for payment details\n\n"
        f"Admin: {ADMIN_USERNAME}"
    )
    
    await query.edit_message_text(
        payment_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🆔 Check KYC Status", callback_data='kyc_check')],
            [InlineKeyboardButton("🔙 Back", callback_data='back')]
        ])
    )

async def contact_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiate contact with admin"""
    query = update.callback_query

    await query.answer()
    
    user_states[query.from_user.id] = "AWAITING_MESSAGE"
    
    await query.edit_message_text(
        "✉️ Please type your message for admin (max 500 characters):",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_message")]
        ])
    )

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process user message to admin"""
    user_id = update.message.from_user.id
    
    if user_id not in user_states or user_states[user_id] != "AWAITING_MESSAGE":
        return
    
    # Check rate limit
    if not message_limiter.check_limit(user_id):
        await update.message.reply_text("⏳ Please wait before sending another message")
        return
    
    message = update.message.text[:500]  # Truncate long messages
    user_messages[user_id] = message
    
    # Notify admin with reply button
    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Reply", callback_data=f"reply_{user_id}")]
    ])
    
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📨 New message from @{update.message.from_user.username} (ID: {user_id}):\n\n{message}",
            reply_markup=admin_keyboard
        )
        await update.message.reply_text(
            "✅ Your message has been sent to admin!",
            reply_markup=get_main_menu()
        )
    except Exception as e:
        await update.message.reply_text("⚠️ Failed to send message. Please try later.")
    
    del user_states[user_id]

async def admin_reply_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin reply button clicks"""
    query = update.callback_query
    await query.answer()
    
    # Verify admin
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.edit_message_text("🚫 Admin only feature")
        return
    
    # Extract user ID from callback data (format: reply_123456)
    try:
        user_id = int(query.data.split('_')[1])
        context.user_data['replying_to'] = user_id
        
        # Get original message text
        original_text = query.message.text
        
        await query.edit_message_text(
            f"{original_text}\n\n"
            "✍️ You are now replying to this user.\n"
            "Type your message below:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_reply")]
            ])
        )
    except Exception as e:
        await query.edit_message_text(f"Error: {str(e)}")

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process admin's reply to user"""
    # Verify admin
    if update.message.from_user.id != ADMIN_CHAT_ID:
        return
    
    # Check if replying to someone
    if 'replying_to' not in context.user_data:
        await update.message.reply_text("⚠️ No user selected to reply to. Use the reply button from a user's message.")
        return
    
    user_id = context.user_data['replying_to']
    reply_text = f"💬 Admin Reply:\n\n{update.message.text}"
    
    try:
        # Send to user
        await context.bot.send_message(
            chat_id=user_id,
            text=reply_text,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Confirm to admin
        await update.message.reply_text(
            f"✅ Reply sent to user {user_id}",
            reply_to_message_id=update.message.message_id
        )
        
        # Log the conversation
        log_message = (
            f"🔷 Admin Reply Log\n\n"
            f"👤 User ID: {user_id}\n"
            f"🕒 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"📝 Message: {update.message.text}"
        )
        await context.bot.send_message(ADMIN_CHAT_ID, log_message)
        
    except Exception as e:
        error_msg = f"⚠️ Failed to send reply to {user_id}: {str(e)}"
        print(error_msg)
        await update.message.reply_text(error_msg)

async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forward user messages to admin with back button in confirmation"""
    user_id = update.message.from_user.id
    
    # Check rate limit
    if not message_limiter.check_limit(user_id):
        await update.message.reply_text(
            "⏳ Please wait 1 minute before sending another message",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Menu", callback_data='back')]
            ])
        )
        return
    
    try:
        # Forward to admin
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📩 From @{update.message.from_user.username} (ID: {user_id}):\n\n{update.message.text}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 Reply", callback_data=f"reply_{user_id}")]
            ])
        )
        
        # Confirm to user with back button
        await update.message.reply_text(
            "✅ Message sent to admin!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Menu", callback_data='back')]
            ])
        )
        
    except Exception as e:
        print(f"Forwarding error: {e}")
        await update.message.reply_text(
            "⚠️ Failed to send message. Please try again.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Menu", callback_data='back')],
                [InlineKeyboardButton("🔄 Try Again", callback_data='contact_admin')]
            ])
        )

async def cancel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel message to admin"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id in user_states:
        del user_states[user_id]
    
    await query.edit_message_text(
        "❌ Message cancelled",
        reply_markup=get_main_menu()
    )

async def cancel_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel admin reply"""
    query = update.callback_query
    await query.answer()
    
    if 'replying_to' in context.user_data:
        user_id = context.user_data.pop('replying_to')
        await query.edit_message_text(
            f"❌ Reply to user {user_id} cancelled",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 Reply Anyway", callback_data=f"reply_{user_id}")]
            ])
        )
    else:
        await query.edit_message_text("No active reply to cancel")

async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Properly edits previous message instead of creating new ones"""
    try:
        # Get the message we want to edit
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            message_to_edit = query.message
        elif update.message:
            message_to_edit = update.message
        else:
            return

        # Edit the existing message
        await message_to_edit.edit_text(
            text="👋 Welcome back! Select an option:",
            reply_markup=get_main_menu()
        )
        
    except Exception as e:
        print(f"⚠️ Menu edit failed, sending new message: {e}")
        # Fallback to new message if edit fails
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="👋 Welcome back! Select an option:",
            reply_markup=get_main_menu()
        )

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help information"""
    query = update.callback_query
    await query.answer()  # Important: always answer callback queries first
    
    help_text = (
        "❓ *Help Center*\n\n"
        "For any assistance, please contact our admin team.\n\n"
        f"Admin: {ADMIN_USERNAME}\n"
        "We're available to help you."
    )
    
    await query.edit_message_text(
        help_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📞 Contact Admin", callback_data="contact_admin")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ])
    )            

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        print(f"Error: {context.error}")
        try:
            if update.callback_query:
                await update.callback_query.answer("⚠️ Error occurred")
                await return_to_menu(update, context)
        except:
            pass

async def run_telegram_bot():
    """Run the Telegram bot with proper initialization for v20.8+"""
    print("🤖 Starting Telegram bot...")
    
    # Initialize the bot application (using 'app' as variable name)
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rules", lambda u,c: show_rules(u.callback_query)))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(show_rules, pattern="^rules$"))
    app.add_handler(CallbackQueryHandler(kyc_check, pattern="^kyc_check$"))
    app.add_handler(CallbackQueryHandler(show_payment_info, pattern="^payment_info$"))
    app.add_handler(CallbackQueryHandler(contact_admin, pattern="^contact_admin$"))
    app.add_handler(CallbackQueryHandler(show_help, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(show_form, pattern="^form$"))
    app.add_handler(CallbackQueryHandler(cancel_message, pattern="^cancel_message$"))
    app.add_handler(CallbackQueryHandler(cancel_reply, pattern="^cancel_reply$"))
    app.add_handler(CallbackQueryHandler(lambda update, context: return_to_menu(update, context),
            pattern="^back$"
        ))
    app.add_handler(CallbackQueryHandler(handle_payment, pattern="^payment$"))
    app.add_handler(CallbackQueryHandler(admin_reply_button, pattern="^reply_"))

    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_CHAT_ID), handle_admin_reply))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, forward_to_admin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_user_message))

    app.add_error_handler(error_handler)
    
    # Start polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await app.updater.start_polling()
    
    # Keep running while the event is set
    try:
        while keep_running.is_set():
            await asyncio.sleep(1)
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

def run_flask_server():
    """Run Flask server in a separate thread"""
    print("🌐 Starting Flask server on port 5000...")
    server.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

def run_bot_in_thread():
    """Wrapper to run the async bot in a thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_telegram_bot())
    finally:
        loop.close()

if __name__ == "__main__":
    # Start bot thread
    bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
    bot_thread.start()
    
    # Start Flask
    from waitress import serve
    serve(server, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
