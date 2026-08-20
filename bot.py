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

# Environment Variables (Render-ல் இவற்றை Setup செய்ய வேண்டும்)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
FAST2SMS_API_KEY = os.getenv("FAST2SMS_API_KEY")

# தற்காலிக டேட்டா சேமிப்பு (Production-ல் Database அல்லது Google Sheets பயன்படுத்தலாம்)
# CSV/Google Sheets இலிருந்து டேட்டாவை இங்கே லோட் செய்து கொள்ளலாம்.
# உதாரண வாடிக்கையாளர் தரவு:
CUSTOMERS_DB = [
    {
        "Branch": "Nagercoil",
        "Customer No": "CUST001",
        "Full Name": "Kumar",
        "Mobile No": "9952452094",
    },
    {
        "Branch": "Thingalnagar",
        "Customer No": "CUST002",
        "Full Name": "Selvam",
        "Mobile No": "7810004040",
    }
]

# பணியாளர் எந்தக் கிளை என்பதை வரையறுக்க (Telegram User ID மூலம்)
STAFF_BRANCH_MAP = {
    # Telegram_User_ID: "Branch_Name"
    1889072007: "Nagercoil",
    1570175899: "Thingalnagar"
}

# பரிவர்த்தனை வகைகள்
CASH_OUT_TYPES = [
    "GOLD LOAN", "FD Interest", "RD Interest", "FD Closure", 
    "RD Closure", "GP", "Cash Transfer"
]

CASH_IN_TYPES = [
    "Gold loan Closure", "Gold Loan Interest", "Gold Loan Part Payment", 
    "GS", "Cash Received", "New RD", "New FD", "RD Due"
]

# /start கட்டளை
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in STAFF_BRANCH_MAP:
        await update.message.reply_text("மன்னிக்கவும், உங்களுக்கு இந்த பாட்டைப் பயன்படுத்த அனுமதி இல்லை.")
        return
    
    branch = STAFF_BRANCH_MAP[user_id]
    await update.message.reply_text(
        f"வணக்கம்! உங்கள் கிளை: *{branch}*.\n"
        "வாடிக்கையாளரைத் தேட வாடிக்கையாளரின் பெயரின் சில எழுத்துகளை அனுப்பவும் (எ.கா: `Kumar`).",
        parse_mode="Markdown"
    )

# வாடிக்கையாளரைத் தேடுதல் (Search Customer by Name)
async def search_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in STAFF_BRANCH_MAP:
        return

    branch = STAFF_BRANCH_MAP[user_id]
    query_text = update.message.text.strip().lower()

    # குறிப்பிட்ட கிளை வாடிக்கையாளர்களை மட்டும் தேடுதல்
    matched_customers = [
        c for c in CUSTOMERS_DB 
        if c["Branch"].lower() == branch.lower() and query_text in c["Full Name"].lower()
    ]

    if not matched_customers:
        await update.message.reply_text("உங்கள் கிளையில் இந்த பெயரில் வாடிக்கையாளர் இல்லை.")
        return

    # பட்டங்களாக வாடிக்கையாளர்களைக் காட்டுதல்
    keyboard = []
    for cust in matched_customers:
        callback_data = f"cust_{cust['Customer No']}"
        keyboard.append([InlineKeyboardButton(f"{cust['Full Name']} ({cust['Customer No']})", callback_data=callback_data)])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("சரியான வாடிக்கையாளரைத் தேர்வு செய்யவும்:", reply_markup=reply_markup)

# வாடிக்கையாளர் தேர்வு செய்யப்பட்டதும் OTP அனுப்புவது
async def customer_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cust_no = query.data.split("_")[1]
    cust = next((c for c in CUSTOMERS_DB if c["Customer No"] == cust_no), None)

    if not cust:
        await query.edit_message_text("பிழை: வாடிக்கையாளர் விவரங்கள் கிடைக்கவில்லை.")
        return

    # Session-ல் வாடிக்கையாளர் விவரங்களை சேமித்தல்
    context.user_data["selected_customer"] = cust

    # OTP உருவாக்குதல்
    otp = str(random.randint(1000, 9999))
    context.user_data["generated_otp"] = otp

    # Fast2SMS மூலம் OTP அனுப்புவது
    mobile = cust["Mobile No"]
    url = "https://www.fast2sms.com/dev/bulkV2"
    payload = {
        "authorization": FAST2SMS_API_KEY,
        "route": "otp",
        "variables_values": otp,
        "numbers": mobile,
    }
    headers = {'cache-control': "no-cache"}

    try:
        response = requests.post(url, data=payload, headers=headers)
        res_data = response.json()
        if not res_data.get("return"):
            # டெஸ்டிங்கிற்காக லோக்கலில் ஒர்க்காகவில்லை என்றாலும் தொடரலாம்
            pass
    except Exception as e:
        print(f"SMS Error: {e}")

    # பரிவர்த்தனை வகைகளைக் காட்டுவது (Cash In / Cash Out Menu)
    keyboard = []
    all_txns = CASH_OUT_TYPES + CASH_IN_TYPES
    for txn in all_txns:
        keyboard.append([InlineKeyboardButton(txn, callback_data=f"txn_{txn}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"வாடிக்கையாளர்: *{cust['Full Name']}* தேர்வு செய்யப்பட்டுள்ளார்.\n"
        f"அவரது பதிவு செய்யப்பட்ட எண்ணிற்கு ({mobile}) OTP அனுப்பப்பட்டுள்ளது.\n\n"
        "கீழ்கண்ட பரிவர்த்தனை வகைத் தேர்வு செய்யவும்:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# பரிவர்த்தனை வகை தேர்வு மற்றும் அடுத்த ধাপ உள்ளீடு
async def transaction_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    txn_type = query.data.replace("txn_", "")
    context.user_data["selected_txn"] = txn_type

    await query.edit_message_text(
        f"தேர்ந்தெடுக்கப்பட்ட பரிவர்த்தனை: *{txn_type}*\n\n"
        "தயவுசெய்து **பரிவர்த்தனை குறிப்பு எண்ணை (Transaction Reference Number)** அனுப்பவும்:"
    )
    context.user_data["step"] = "get_ref_no"

# டெக்ஸ்ட் உள்ளீடுகளைக் கையாளுதல் (Ref No, Staff Name, Amount, OTP)
async def handle_text_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in STAFF_BRANCH_MAP:
        return

    step = context.user_data.get("step")
    text = update.message.text.strip()

    if step == "get_ref_no":
        context.user_data["ref_no"] = text
        context.user_data["step"] = "get_staff_name"
        await update.message.reply_text("அடுத்து, **பரிவர்த்தனைக்குப் பொறுப்பான பணியாளர் பெயரை (Reference Staff Name)** உள்ளிடவும்:")

    elif step == "get_staff_name":
        context.user_data["staff_name"] = text
        context.user_data["step"] = "get_amount"
        await update.message.reply_text("அடுத்து, **தொகையை (Amount)** உள்ளிடவும்:")

    elif step == "get_amount":
        context.user_data["amount"] = text
        context.user_data["step"] = "get_otp"
        await update.message.reply_text(
            f"அனைத்து விவரங்களும் பெறப்பட்டன.\n"
            f"பரிவர்த்தனை: {context.user_data.get('selected_txn')}\n"
            f"தொகை: {text}\n\n"
            "வாடிக்கையாளரிடம் பெற்ற **OTP-ஐ** உள்ளிடவும்:"
        )

    elif step == "get_otp":
        entered_otp = text
        correct_otp = context.user_data.get("generated_otp")

        if entered_otp == correct_otp:
            cust = context.user_data.get("selected_customer")
            txn = context.user_data.get("selected_txn")
            amount = context.user_data.get("amount")
            ref_no = context.user_data.get("ref_no")
            staff = context.user_data.get("staff_name")
            branch = STAFF_BRANCH_MAP[user_id]

            # பரிவர்த்தனை வெற்றிகரமாக முடிந்தது
            await update.message.reply_text(
                "✅ *பரிவர்த்தனை வெற்றிகரமாக உறுதிப்படுத்தப்பட்டது!*\n\n"
                f"கிளை: {branch}\n"
                f"வாடிக்கையாளர்: {cust['Full Name']} ({cust['Customer No']})\n"
                f"வகை: {txn}\n"
                f"குறிப்பு எண்: {ref_no}\n"
                f"பொறுப்பு பணியாளர்: {staff}\n"
                f"தொகை: ₹{amount}",
                parse_mode="Markdown"
            )
            # இங்கு டேட்டாபேஸ் அல்லது Google Sheets-ல் டேட்டாவை சேமிக்கும் கோடை சேர்த்துக்கொள்ளலாம்.
            
            # டேட்டாவை கிளியர் செய்தல்
            context.user_data.clear()
        else:
            await update.message.reply_text("❌ தவறான OTP! மீண்டும் சரியான OTP-ஐ உள்ளிடவும் அல்லது பரிவர்த்தனையை மீளமைக்கவும்.")

# மெயின் ஆப் இயக்க முறை
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(customer_selected, pattern="^cust_"))
    app.add_handler(CallbackQueryHandler(transaction_selected, pattern="^txn_"))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), search_customer)) # வாடிக்கையாளர் தேடலுக்கு
    # குறிப்பு: நடைமுறையில் ஸ்டெப் வாரியாக ஹேண்டில் செய்ய தனித்தனி கண்டிஷன்கள் தேவைப்படும்.

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
