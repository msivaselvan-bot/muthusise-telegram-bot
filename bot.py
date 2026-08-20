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

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
FAST2SMS_API_KEY = os.getenv("FAST2SMS_API_KEY")

GOOGLE_SHEET_API_URL = "https://script.google.com/macros/s/AKfycbyLFfJfVJ4yfJo4WnOfxJAZLbcPPTnxVTOxcjX1-W9uzqanPF99fhhHoFQJOKGYEk7Z/exec"
HEAD_OFFICE_CHAT_ID = "1889072007"

# Cash Out வகைகள் (செலவு - நாம் வாடிக்கையாளருக்குக் கொடுப்பது)
CASH_OUT_TYPES = [
    "GOLD LOAN", "FD Interest", "RD Interest", "FD Closure", 
    "RD Closure", "GP", "Cash Transfer"
]

# Cash In வகைகள் (வரவு - வாடிக்கையாளர் நமக்குத் தருவது)
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = get_data_from_sheet()
    staff_map = data.get("staff_map", {})
    
    if user_id not in staff_map and user_id != HEAD_OFFICE_CHAT_ID:
        await update.message.reply_text("மன்னிக்கவும், இந்த பாட்டைப் பயன்படுத்த உங்களுக்கு அனுமதி இல்லை.")
        return
    
    if user_id == HEAD_OFFICE_CHAT_ID:
        await update.message.reply_text("வணக்கம் தலைமை அலுவலக மேலாளர்! கிளைகளிலிருந்து வரும் பரிவர்த்தனை ஒப்புதல்களுக்காக இந்த பாட் காத்திருக்கிறது.")
        return

    branch = staff_map[user_id]
    context.user_data.clear()
    await update.message.reply_text(
        f"வணக்கம்! உங்கள் கிளை: *{branch}*.\n\n"
        "வாடிக்கையாளரைத் தேட அவரது பெயரின் சில எழுத்துகளைத் தட்டச்சு செய்து அனுப்பவும் (எ.கா: `Kumar`).",
        parse_mode="Markdown"
    )

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

# வாடிக்கையாளர் தேர்வு செய்யப்பட்டதும் OTP அனுப்புவது
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
    context.user_data["transactions_cart"] = []

    otp = str(random.randint(1000, 9999))
    context.user_data["generated_otp"] = otp
    mobile = str(cust.get("Mobile No", "")).strip()

    if mobile:
        url = "https://www.fast2sms.com/dev/bulkV2"
        querystring = {
            "authorization": FAST2SMS_API_KEY,
            "route": "dlt",
            "sender_id": "MTHSEG",
            "message": "219823",
            "variables_values": f"{otp}|",
            "numbers": mobile
        }
        try:
            requests.get(url, params=querystring, headers={'cache-control': "no-cache"})
        except Exception as e:
            print(f"SMS Error: {e}")

    context.user_data["step"] = "verify_initial_otp"

    await query.edit_message_text(
        f"வாடிக்கையாளர்: *{cust.get('Full Name')}* ({cust.get('Customer No')}) தேர்வு செய்யப்பட்டுள்ளார்.\n"
        f"அவரது பதிவு செய்யப்பட்ட எண்ணிற்கு ({mobile}) **OTP** அனுப்பப்பட்டுள்ளது.\n\n"
        "பரிவர்த்தனையைத் தொடங்க வாடிக்கையாளரிடம் பெற்ற **OTP-ஐ** இங்கே உள்ளிடவும்:",
        parse_mode="Markdown"
    )

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
            context.user_data["step"] = "select_category"
            
            keyboard = [
                [InlineKeyboardButton("📥 Cash In (வரவு)", callback_data="cat_cashin")],
                [InlineKeyboardButton("📤 Cash Out (செலவு)", callback_data="cat_cashout")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "✅ *OTP வெற்றிகரமாக உறுதிப்படுத்தப்பட்டது!*\n\n"
                "இப்போது முதல் பரிவர்த்தனை வகையைத் தேர்ந்தெடுக்கவும்:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ தவறான OTP! சரியான OTP-ஐ மீண்டும் உள்ளிடவும்:")

    elif step == "get_ref_no":
        context.user_data["ref_no"] = text
        context.user_data["step"] = "get_staff_name"
        await update.message.reply_text("அடுத்து, **பரிவர்த்தனைக்குப் பொறுப்பான பணியாளர் பெயரை** உள்ளிடவும்:")

    elif step == "get_staff_name":
        context.user_data["staff_name"] = text
        context.user_data["step"] = "get_amount"
        await update.message.reply_text("அடுத்து, **தொகையை (Amount)** உள்ளிடவும்:")

    elif step == "get_amount":
        amount = text
        txn = context.user_data.get("selected_txn")
        ref_no = context.user_data.get("ref_no")
        staff = context.user_data.get("staff_name")
        cat_type = context.user_data.get("selected_category_type") # cashin அல்லது cashout

        cart = context.user_data.get("transactions_cart", [])
        cart.append({
            "txn_type": txn,
            "category": cat_type,
            "amount": float(amount),
            "ref_no": ref_no,
            "staff_name": staff
        })
        context.user_data["transactions_cart"] = cart

        context.user_data["step"] = "waiting_for_next_action"

        keyboard = [
            [InlineKeyboardButton("➕ மற்றொரு பரிவர்த்தனை சேர்க்க (Add More)", callback_data="action_add_more")],
            [InlineKeyboardButton("✅ பரிவர்த்தனைகளை முடிக்க (Finish & Submit)", callback_data="action_finish")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"✅ பரிவர்த்தனை சேர்க்கப்பட்டது! (மொத்த பரிவர்த்தனைகள்: {len(cart)})\n\n"
            "அடுத்து என்ன செய்ய வேண்டும்?",
            reply_markup=reply_markup
        )

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    cat_type = query.data.replace("cat_", "")
    context.user_data["selected_category_type"] = cat_type
    keyboard = []

    if cat_type == "cashin":
        for txn in CASH_IN_TYPES:
            keyboard.append([InlineKeyboardButton(txn, callback_data=f"txn_{txn}")])
    else:
        for txn in CASH_OUT_TYPES:
            keyboard.append([InlineKeyboardButton(txn, callback_data=f"txn_{txn}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("பரிவர்த்தனை வகைத் தேர்வு செய்யவும்:", reply_markup=reply_markup)

async def transaction_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    txn_type = query.data.replace("txn_", "")
    context.user_data["selected_txn"] = txn_type
    context.user_data["step"] = "get_ref_no"

    await query.edit_message_text(
        f"தேர்ந்தெடுக்கப்பட்ட பரிவர்த்தனை: *{txn_type}*\n\n"
        "தயவுசெய்து **பரிவர்த்தனை குறிப்பு எண்ணை (Reference Number)** அனுப்பவும்:"
    )

async def handle_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data.replace("action_", "")

    if action == "add_more":
        keyboard = [
            [InlineKeyboardButton("📥 Cash In (வரவு)", callback_data="cat_cashin")],
            [InlineKeyboardButton("📤 Cash Out (செலவு)", callback_data="cat_cashout")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("அடுத்த பரிவர்த்தனை வகையைத் தேர்ந்தெடுக்கவும்:", reply_markup=reply_markup)
    
    elif action == "finish":
        cust = context.user_data.get("selected_customer")
        cart = context.user_data.get("transactions_cart", [])
        
        staff_map = get_data_from_sheet().get("staff_map", {})
        user_id = str(query.from_user.id)
        branch = staff_map.get(user_id, "Branch")

        if not cart:
            await query.edit_message_text("எந்தப் பரிவர்த்தனையும் சேர்க்கப்படவில்லை.")
            return

        # 1. Cash In மற்றும் Cash Out தொகைகளைக் தனித்தனியாகக் கூட்டுவது
        cashin_total = sum(item["amount"] for item in cart if item["category"] == "cashin")
        cashout_total = sum(item["amount"] for item in cart if item["category"] == "cashout")
        
        # 2. நிலுவைத் தொகையைக் கணக்கிடுதல் (Net Balance)
        net_diff = cashin_total - cashout_total
        if net_diff > 0:
            balance_text = f"₹{net_diff} (வாடிக்கையாளர் செலுத்த வேண்டியது)"
        elif net_diff < 0:
            balance_text = f"₹{abs(net_diff)} (வாடிக்கையாளருக்கு நாம் கொடுக்க வேண்டியது)"
        else:
            balance_text = "₹0 (சமமாக உள்ளது)"

        branch_code = branch[:3].upper()
        time_str = datetime.now().strftime("%Y%m%d-%H%M%S")
        auto_receipt_no = f"{branch_code}-{time_str}"

        # இறுதி OTP உருவாக்குவது
        final_otp = str(random.randint(1000, 9999))

        # சுருக்கம் தயாரித்தல்
        summary_text = f"🏷️ **ரசீது எண்:** `{auto_receipt_no}`\n"
        summary_text += f"👤 **வாடிக்கையாளர்:** {cust.get('Full Name')} ({cust.get('Customer No')})\n\n"
        summary_text += "📑 **செய்த பரிவர்த்தனைகள்:**\n"
        
        ho_items_desc = ""
        for i, item in enumerate(cart, 1):
            cat_name = "Cash In" if item['category'] == 'cashin' else "Cash Out"
            summary_text += f"{i}. [{cat_name}] {item['txn_type']} - ₹{item['amount']}\n"
            ho_items_desc += f"- [{cat_name}] {item['txn_type']}: ₹{item['amount']} (Ref: {item['ref_no']}, Staff: {item['staff_name']})\n"

        summary_text += f"\n📥 **மொத்த வரவு (Cash In):** ₹{cashin_total}\n"
        summary_text += f"📤 **மொத்த செலவு (Cash Out):** ₹{cashout_total}\n"
        summary_text += f"⚖️ **இறுதி நிலுவை:** {balance_text}\n"
        summary_text += f"🔑 **உறுதிப்படுத்தல் OTP:** `{final_otp}`\n"

        # வாடிக்கையாளருக்கு நீங்கள் கேட்ட வடிவில் SMS அனுப்புவது
        mobile = str(cust.get("Mobile No", "")).strip()
        if mobile:
            sms_message = (
                f"Dear {cust.get('Full Name')}, "
                f"மொத்த செலுத்துதல்கள் {cashin_total}, "
                f"பெறுதல்கள் {cashout_total} போக நீங்கள் செலுத்தவேண்டிய/பெறவேண்டிய தொகை {balance_text}. "
                f"OTP: {final_otp}"
            )
            url = "https://www.fast2sms.com/dev/bulkV2"
            querystring = {
                "authorization": FAST2SMS_API_KEY,
                "route": "dlt",
                "sender_id": "MTHSEG",
                "message": "219823",
                "variables_values": f"{cashin_total}|{cashout_total}|{net_diff}|{final_otp}|",
                "numbers": mobile
            }
            try:
                requests.get(url, params=querystring, headers={'cache-control': "no-cache"})
            except Exception as e:
                print(f"SMS Error: {e}")

        await query.edit_message_text(
            "✅ *அனைத்துப் பரிவர்த்தனைகளும் முடிக்கப்பட்டன!*\n\n"
            f"{summary_text}\n"
            "⏳ *தலைமை அலுவலக ஒப்புதலுக்கு (HO Approval) அனுப்பி வைக்கப்பட்டுள்ளது.*",
            parse_mode="Markdown"
        )

        # தலைமை அலுவலகத்திற்கு அனுப்புவது
        ho_message = (
            "🔔 *புதிய பல பரிவர்த்தனை ஒப்புதல் தேவை (HO Approval)*\n\n"
            f"{summary_text}\n"
            f"📍 **கிளை:** {branch}\n\n"
            f"{ho_items_desc}"
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"app_{auto_receipt_no}_{branch}_{cust.get('Customer No')}_{cust.get('Full Name')}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"rej_{auto_receipt_no}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        context.application.bot_data[auto_receipt_no] = cart

        await context.bot.send_message(
            chat_id=HEAD_OFFICE_CHAT_ID,
            text=ho_message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

        context.user_data.clear()
        await context.bot.send_message(
            chat_id=user_id,
            text="அடுத்த வாடிக்கையாளரைத் தேட அவரது பெயரின் சில எழுத்துகளைத் தட்டச்சு செய்யவும்."
        )

async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data_parts = query.data.split("_")
    action = data_parts[0]
    receipt_no = data_parts[1]

    if action == "app":
        branch = data_parts[2]
        cust_no = data_parts[3]
        cust_name = data_parts[4]

        cart = context.application.bot_data.get(receipt_no, [])

        for item in cart:
            payload = {
                "action": "save_transaction",
                "receipt_no": receipt_no,
                "branch": branch,
                "customer_no": cust_no,
                "customer_name": cust_name,
                "txn_type": f"[{item['category'].upper()}] {item['txn_type']}",
                "amount": item["amount"],
                "ref_no": item["ref_no"],
                "staff_name": item["staff_name"]
            }
            try:
                requests.post(GOOGLE_SHEET_API_URL, json=payload)
            except Exception as e:
                print(f"Sheet Save Error: {e}")

        await query.edit_message_text(
            f"{query.message.text}\n\n"
            "🟢 **நிலை:** தலைமை அலுவலகத்தால் **ஒப்புதல் அளிக்கப்பட்டது** மற்றும் அனைத்துப் பரிவர்த்தனைகளும் கூகுள் ஷீட்டில் பதிவானது ✅",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            f"{query.message.text}\n\n"
            "🔴 **நிலை:** தலைமை அலுவலகத்தால் **நிராகரிக்கப்பட்டது** ❌",
            parse_mode="Markdown"
        )

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(customer_selected, pattern="^cust_"))
    app.add_handler(CallbackQueryHandler(category_selected, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(transaction_selected, pattern="^txn_"))
    app.add_handler(CallbackQueryHandler(handle_actions, pattern="^action_"))
    app.add_handler(CallbackQueryHandler(handle_approval, pattern="^(app|rej)_"))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), search_customer))

    print("Bot is running with Net Balance Summary & Custom SMS...")
    app.run_polling()

if __name__ == "__main__":
    main()
