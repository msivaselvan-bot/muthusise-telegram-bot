import os
import random
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Environment Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
FAST2SMS_API_KEY = os.getenv("FAST2SMS_API_KEY")

# Google Apps Script Web App URL
GOOGLE_SHEET_API_URL = "https://script.google.com/macros/s/AKfycbwFkhiOZwM4ONNyEEPtqI9TJq7luf_fyWBQoSnCUfnmzyyv3yVkGVf6XZMZTCfXIqex/exec"

# பரிவர்த்தனை வகைகள்
CASH_OUT_TYPES = [
    "GOLD LOAN", "FD Interest", "RD Interest", "FD Closure", 
    "RD Closure", "GP", "Cash Transfer"
]

CASH_IN_TYPES = [
    "Gold loan Closure", "Gold Loan Interest", "Gold Loan Part Payment", 
    "GS", "Cash Received", "New RD", "New FD", "RD Due"
]

def get_data_from_sheet():
    try:
        response = requests.get(GOOGLE_SHEET_API_URL)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error fetching from Google Sheets: {e}")
    return {"customers": [], "staff_map": {}}

# /start கட்டளை
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = get_data_from_sheet()
    staff_map = data.get("staff_map", {})
    
    if user_id not in staff_map:
        await update.message.reply_text("மன்னிக்கவும், இந்த பாட்டைப் பயன்படுத்த உங்களுக்கு அனுமதி இல்லை.")
        return
    
    branch = staff_map[user_id]
    context.user_data.clear()
    await update.message.reply_text(
        f"வணக்கம்! உங்கள் கிளை: *{branch}*.\n\n"
        "வாடிக்கையாளரைத் தேட அவரது பெயரின் சில எழுத்துகளைத் தட்டச்சு செய்து அனுப்பவும் (எ.கா: `Kumar`).",
        parse_mode="Markdown"
    )

# வாடிக்கையாளரைத் தேடுதல் (சரியான கிளை வாடிக்கையாளர்களை மட்டும் காட்டுவது)
async def search_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = get_data_from_sheet()
    staff_map = data.get("staff_map", {})

    if user_id not in staff_map:
        return

    if context.user_data.get("step"):
        await handle_text_inputs(update, context)
        return

    branch = staff_map[user_id]
    query_text = update.message.text.strip().lower()
    customers_db = data.get("customers", [])

    matched_customers = [
        c for c in customers_db 
        if str(c.get("Branch", "")).strip().lower() == branch.lower() and query_text in str(c.get("Full Name", "")).strip().lower()
    ]

    if not matched_customers:
        await update.message.reply_text("உங்கள் கிளையில் இந்த பெயரில் வாடிக்கையாளர் இல்லை. மீண்டும் சரியாகத் தேடவும்.")
        return

    keyboard = []
    for cust in matched_customers:
        cust_no = str(cust.get("Customer No", ""))
        name = str(cust.get("Full Name", ""))
        callback_data = f"cust_{cust_no}"
        keyboard.append([InlineKeyboardButton(f"{name} ({cust_no})", callback_data=callback_data)])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("சரியான வாடிக்கையாளரைத் தேர்வு செய்யவும்:", reply_markup=reply_markup)

# வாடிக்கையாளர் தேர்வு செய்யப்பட்டதும் Fast2SMS DLT முறைப்படி OTP அனுப்புவது
async def customer_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cust_no = query.data.split("_")[1]
    data = get_data_from_sheet()
    staff_map = data.get("staff_map", {})
    user_id = str(query.from_user.id)
    branch = staff_map.get(user_id, "")

    customers_db = data.get("customers", [])
    cust = next((c for c in customers_db if str(c.get("Customer No")) == cust_no and str(c.get("Branch", "")).strip().lower() == branch.lower()), None)

    if not cust:
        await query.edit_message_text("பிழை: வாடிக்கையாளர் விவரங்கள் கிடைக்கவில்லை.")
        return

    context.user_data["selected_customer"] = cust

    # 4 இலக்க OTP உருவாக்குதல்
    otp = str(random.randint(1000, 9999))
    context.user_data["generated_otp"] = otp

  # Fast2SMS மூலம் OTP அனுப்புவது
    mobile = str(cust.get("Mobile No", "")).strip()
    if mobile:
        url = "https://www.fast2sms.com/dev/bulkV2"
        payload = {
            "route": "otp",
            "variables_values": otp,
            "numbers": mobile,
        }
        headers = {
            'authorization': FAST2SMS_API_KEY,
            'cache-control': "no-cache",
            'content-type': "application/json"
        }
        try:
            print(f"Sending SMS to {mobile} with OTP {otp}...") # இதைச் சேர்த்தால் லாக்கில் தெரியும்
            response = requests.post(url, json=payload, headers=headers)
            print("Fast2SMS Full Response:", response.status_code, response.text)
        except Exception as e:
            print(f"SMS Exception Error: {e}")

    context.user_data["step"] = "verify_initial_otp"
    
    await query.edit_message_text(
        f"வாடிக்கையாளர்: *{cust.get('Full Name')}* ({cust.get('Customer No')}) தேர்வு செய்யப்பட்டுள்ளார்.\n"
        f"அவரது பதிவு செய்யப்பட்ட எண்ணிற்கு ({mobile}) **OTP** அனுப்பப்பட்டுள்ளது.\n\n"
        "பரிவர்த்தனையைத் தொடங்க வாடிக்கையாளரிடம் பெற்ற **OTP-ஐ** இங்கே உள்ளிடவும்:",
        parse_mode="Markdown"
    )

# டெக்ஸ்ட் உள்ளீடுகளைக் கையாளுதல்
async def handle_text_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = get_data_from_sheet()
    staff_map = data.get("staff_map", {})

    if user_id not in staff_map:
        return

    step = context.user_data.get("step")
    text = update.message.text.strip()

    if step == "verify_initial_otp":
        entered_otp = text
        correct_otp = context.user_data.get("generated_otp")

        if entered_otp == correct_otp:
            context.user_data["step"] = "select_transaction"
            
            keyboard = []
            all_txns = CASH_OUT_TYPES + CASH_IN_TYPES
            for txn in all_txns:
                keyboard.append([InlineKeyboardButton(txn, callback_data=f"txn_{txn}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "✅ *OTP வெற்றிகரமாக உறுதிப்படுத்தப்பட்டது!*\n\n"
                "இப்போது கீழ்கண்ட பரிவர்த்தனை வகைத் தேர்வு செய்யவும்:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ தவறான OTP! சரியான OTP-ஐ மீண்டும் உள்ளிடவும்:")

    elif step == "get_ref_no":
        context.user_data["ref_no"] = text
        context.user_data["step"] = "get_staff_name"
        await update.message.reply_text("அடுத்து, **பரிவர்த்தனைக்குப் பொறுப்பான பணியாளர் பெயரை (Reference Staff Name)** உள்ளிடவும்:")

    elif step == "get_staff_name":
        context.user_data["staff_name"] = text
        context.user_data["step"] = "get_amount"
        await update.message.reply_text("அடுத்து, **தொகையை (Amount)** உள்ளிடவும்:")

    elif step == "get_amount":
        cust = context.user_data.get("selected_customer")
        txn = context.user_data.get("selected_txn")
        amount = text
        ref_no = context.user_data.get("ref_no")
        staff = context.user_data.get("staff_name")
        branch = staff_map[user_id]

        await update.message.reply_text(
            "✅ *பரிவர்த்தனை வெற்றிகரமாக பதிவு செய்யப்பட்டது!*\n\n"
            f"கிளை: {branch}\n"
            f"வாடிக்கையாளர்: {cust.get('Full Name')} ({cust.get('Customer No')})\n"
            f"வகை: {txn}\n"
            f"குறிப்பு எண்: {ref_no}\n"
            f"பொறுப்பு பணியாளர்: {staff}\n"
            f"தொகை: ₹{amount}",
            parse_mode="Markdown"
        )
        
        context.user_data.clear()
        await update.message.reply_text("அடுத்த பரிவர்த்தனைக்கு வாடிக்கையாளர் பெயரின் சில எழுத்துகளைத் தேடவும்.")

# பரிவர்த்தனை வகை தேர்வு செய்யப்படும்போது
async def transaction_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    txn_type = query.data.replace("txn_", "")
    context.user_data["selected_txn"] = txn_type
    context.user_data["step"] = "get_ref_no"

    await query.edit_message_text(
        f"தேர்ந்தெடுக்கப்பட்ட பரிவர்த்தனை: *{txn_type}*\n\n"
        "தயவுசெய்து **பரிவர்த்தனை குறிப்பு எண்ணை (Transaction Reference Number)** அனுப்பவும்:"
    )

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(customer_selected, pattern="^cust_"))
    app.add_handler(CallbackQueryHandler(transaction_selected, pattern="^txn_"))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), search_customer))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
