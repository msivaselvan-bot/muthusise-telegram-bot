import os
import random
import logging
import requests
from datetime import datetime
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

# புதிய Google Apps Script Web App URL
GOOGLE_SHEET_API_URL = "https://script.google.com/macros/s/AKfycbyLFfJfVJ4yfJo4WnOfxJAZLbcPPTnxVTOxcjX1-W9uzqanPF99fhhHoFQJOKGYEk7Z/exec"

# தலைமை அலுவலக (Head Office) Telegram User ID
HEAD_OFFICE_CHAT_ID = "1889072007"

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
    
    if user_id not in staff_map and user_id != HEAD_OFFICE_CHAT_ID:
        await update.message.reply_text("மன்னிக்கவும், இந்த பாட்டைப் பயன்படுத்த உங்களுக்கு அனுமதி இல்லை.")
        return
    
    if user_id == HEAD_OFFICE_CHAT_ID:
        await update.message.reply_text("வணக்கம் தலைமை அலுவலக மேலாளர்! கிளைகளிலிருந்து வரும் பரிவர்த்தனை ஒப்புதல்களுக்காக (Approvals) இந்த பாட் காத்திருக்கிறது.")
        return

    branch = staff_map[user_id]
    context.user_data.clear()
    await update.message.reply_text(
        f"வணக்கம்! உங்கள் கிளை: *{branch}*.\n\n"
        "வாடிக்கையாளரைத் தேட அவரது பெயரின் சில எழுத்துகளைத் தட்டச்சு செய்து அனுப்பவும் (எ.கா: `Kumar`).",
        parse_mode="Markdown"
    )

# வாடிக்கையாளரைத் தேடுதல்
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
        keyboard.append([InlineKeyboardButton(f"{name} ({cust_no})", callback_data=f"cust_{cust_no}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("சரியான வாடிக்கையாளரைத் தேர்வு செய்யவும்:", reply_markup=reply_markup)

# வாடிக்கையாளர் தேர்வு செய்யப்பட்டதும் Cash In / Cash Out பிரிவுகளைக் காட்டுவது
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

    keyboard = [
        [InlineKeyboardButton("📥 Cash In (வரவு)", callback_data="cat_cashin")],
        [InlineKeyboardButton("📤 Cash Out (செலவு)", callback_data="cat_cashout")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"வாடிக்கையாளர்: *{cust.get('Full Name')}* ({cust.get('Customer No')}) தேர்வு செய்யப்பட்டுள்ளார்.\n\n"
        "பரிவர்த்தனை வகையைத் தேர்ந்தெடுக்கவும்:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# பிரிவைத் தேர்ந்தெடுத்ததும் அந்தந்த பரிவர்த்தனைகளைக் காட்டுவது
async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    cat_type = query.data.replace("cat_", "")
    keyboard = []

    if cat_type == "cashin":
        for txn in CASH_IN_TYPES:
            keyboard.append([InlineKeyboardButton(txn, callback_data=f"txn_{txn}")])
    else:
        for txn in CASH_OUT_TYPES:
            keyboard.append([InlineKeyboardButton(txn, callback_data=f"txn_{txn}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("சரியான பரிவர்த்தனை வகைத் தேர்வு செய்யவும்:", reply_markup=reply_markup)

# பரிவர்த்தனை தேர்வு செய்யப்பட்டதும் Ref No கேட்பது
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

# டெக்ஸ்ட் உள்ளீடுகளைக் கையாளுதல் (Ref No -> Staff Name -> Amount -> OTP SMS)
async def handle_text_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = get_data_from_sheet()
    staff_map = data.get("staff_map", {})

    if user_id not in staff_map:
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
        context.user_data["step"] = "verify_final_otp"

        cust = context.user_data.get("selected_customer")
        mobile = str(cust.get("Mobile No", "")).strip()
        amount = text

        otp = str(random.randint(1000, 9999))
        context.user_data["generated_otp"] = otp

        # Fast2SMS மூலம் OTP அனுப்புவது
        if mobile:
            url = "https://www.fast2sms.com/dev/bulkV2"
            querystring = {
                "authorization": FAST2SMS_API_KEY,
                "route": "dlt",
                "sender_id": "MTHSEG",
                "message": "219823",
                "variables_values": f"{amount}|{otp}|",
                "numbers": mobile
            }
            try:
                requests.get(url, params=querystring, headers={'cache-control': "no-cache"})
            except Exception as e:
                print(f"SMS Error: {e}")

        await update.message.reply_text(
            f"✅ அனைத்து விவரங்களும் பெறப்பட்டன!\n"
            f"தொகை: ₹{amount} வாடிக்கையாளர் எண்ணிற்கு ({mobile}) OTP அனுப்பப்பட்டுள்ளது.\n\n"
            "பரிவர்த்தனையை முடிக்க வாடிக்கையாளரிடம் பெற்ற **OTP-ஐ** உள்ளிடவும்:"
        )

    elif step == "verify_final_otp":
        entered_otp = text
        correct_otp = context.user_data.get("generated_otp")

        if entered_otp == correct_otp:
            cust = context.user_data.get("selected_customer")
            txn = context.user_data.get("selected_txn")
            amount = context.user_data.get("amount")
            ref_no = context.user_data.get("ref_no")
            staff = context.user_data.get("staff_name")
            branch = staff_map[user_id]

            # ஆட்டோ ரசீது எண் (Auto Receipt Number) உருவாக்குவது
            branch_code = branch[:3].upper()
            time_str = datetime.now().strftime("%Y%m%d-%H%M%S")
            auto_receipt_no = f"{branch_code}-{time_str}"
            context.user_data["receipt_no"] = auto_receipt_no

            # கிளைப் பணியாளருக்கு ரசீது எண் காட்டுவது
            await update.message.reply_text(
                "✅ *OTP வெற்றிகரமாக உறுதிப்படுத்தப்பட்டது!*\n\n"
                f"🏷️ **ஆட்டோ ரசீது எண்:** `{auto_receipt_no}`\n"
                f"கிளை: {branch}\n"
                f"வாடிக்கையாளர்: {cust.get('Full Name')} ({cust.get('Customer No')})\n"
                f"வகை: {txn}\n"
                f"தொகை: ₹{amount}\n\n"
                "⏳ *தலைமை அலுவலக ஒப்புதலுக்கு (Head Office Approval) அனுப்பி வைக்கப்பட்டுள்ளது.*",
                parse_mode="Markdown"
            )

            # தலைமை அலுவலகத்திற்கு (HO) ஒப்புதலுக்காக அனுப்புவது
            ho_message = (
                "🔔 *புதிய பரிவர்த்தனை ஒப்புதல் தேவை (HO Approval)*\n\n"
                f"🏷️ **ரசீது எண்:** `{auto_receipt_no}`\n"
                f"📍 **கிளை:** {branch}\n"
                f"👤 **வாடிக்கையாளர்:** {cust.get('Full Name')} ({cust.get('Customer No')})\n"
                f"📑 **வகை:** {txn}\n"
                f"💰 **தொகை:** ₹{amount}\n"
                f"🔖 **குறிப்பு எண்:** {ref_no}\n"
                f"👨‍💼 **பணியாளர்:** {staff}"
            )

            keyboard = [
                [
                    InlineKeyboardButton("✅ Approve (ஒப்புதல் அளி)", callback_data=f"app_{auto_receipt_no}_{branch}_{cust.get('Customer No')}_{cust.get('Full Name')}_{txn}_{amount}_{ref_no}_{staff}"),
                    InlineKeyboardButton("❌ Reject (நிராகரி)", callback_data=f"rej_{auto_receipt_no}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(
                chat_id=HEAD_OFFICE_CHAT_ID,
                text=ho_message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            
            context.user_data.clear()
            await update.message.reply_text("அடுத்த பரிவர்த்தனைக்கு வாடிக்கையாளர் பெயரின் சில எழுத்துகளைத் தேடவும்.")
        else:
            await update.message.reply_text("❌ தவறான OTP! சரியான OTP-ஐ மீண்டும் உள்ளிடவும்:")

# தலைமை அலுவலகம் Approve அல்லது Reject செய்வதைக் கையாளுதல்
async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data_parts = query.data.split("_")
    action = data_parts[0]
    receipt_no = data_parts[1]

    if action == "app":
        # ஷீட்டிற்குத் தேவையான விவரங்களைப் பிரித்தெடுத்தல்
        if len(data_parts) >= 9:
            branch = data_parts[2]
            cust_no = data_parts[3]
            cust_name = data_parts[4]
            txn_type = data_parts[5]
            amount = data_parts[6]
            ref_no = data_parts[7]
            staff_name = data_parts[8]

            payload = {
                "action": "save_transaction",
                "receipt_no": receipt_no,
                "branch": branch,
                "customer_no": cust_no,
                "customer_name": cust_name,
                "txn_type": txn_type,
                "amount": amount,
                "ref_no": ref_no,
                "staff_name": staff_name
            }
            
            try:
                requests.post(GOOGLE_SHEET_API_URL, json=payload)
            except Exception as e:
                print(f"Sheet Save Error: {e}")

        await query.edit_message_text(
            f"{query.message.text}\n\n"
            "🟢 **நிலை:** தலைமை அலுவலகத்தால் **ஒப்புதல் அளிக்கப்பட்டது (Approved)** மற்றும் கூகுள் ஷீட்டில் பதிவானது ✅",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            f"{query.message.text}\n\n"
            "🔴 **நிலை:** தலைமை அலுவலகத்தால் **நிராகரிக்கப்பட்டது (Rejected)** ❌",
            parse_mode="Markdown"
        )

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(customer_selected, pattern="^cust_"))
    app.add_handler(CallbackQueryHandler(category_selected, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(transaction_selected, pattern="^txn_"))
    app.add_handler(CallbackQueryHandler(handle_approval, pattern="^(app|rej)_"))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), search_customer))

    print("Bot is running with Head Office Approval System...")
    app.run_polling()

if __name__ == "__main__":
    main()
