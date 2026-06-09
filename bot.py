import os
import asyncio
import feedparser
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

# เก็บประวัติแชทและโมเดลที่เลือกของแต่ละ user
chat_histories: dict[int, list] = {}
user_models: dict[int, str] = {}
user_names: dict[int, str] = {}

MODELS = {
    "groq": {"name": "Groq (LLaMA 3.3)", "model": "llama-3.3-70b-versatile"},
    "gpt": {"name": "GPT-4o Mini", "model": "gpt-4o-mini"},
}
DEFAULT_MODEL = "groq"


def get_user_model(user_id: int) -> str:
    return user_models.get(user_id, DEFAULT_MODEL)


async def ask_ai(user_id: int, messages: list) -> str:
    model_key = get_user_model(user_id)
    name = user_names.get(user_id)
    system_content = "คุณคือผู้ช่วย AI ที่เป็นมิตร ตอบเป็นภาษาไทยถ้าผู้ใช้คุยภาษาไทย"
    if name:
        system_content += f" ชื่อของผู้ใช้คือ {name} ให้เรียกชื่อเขาในการสนทนาด้วย"
    system = {"role": "system", "content": system_content}

    if model_key == "groq":
        response = groq_client.chat.completions.create(
            model=MODELS["groq"]["model"],
            messages=[system, *messages],
            max_tokens=1024,
        )
    else:
        if not openai_client:
            return "ยังไม่ได้ตั้งค่า OpenAI API Key ครับ"
        response = openai_client.chat.completions.create(
            model=MODELS["gpt"]["model"],
            messages=[system, *messages],
            max_tokens=1024,
        )

    return response.choices[0].message.content


MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📰 ข่าว AI"), KeyboardButton("🤖 เปลี่ยน AI")],
        [KeyboardButton("📝 สรุปข้อความ"), KeyboardButton("🌐 แปลภาษา")],
        [KeyboardButton("🗑 ล้างแชท"), KeyboardButton("ℹ️ Chat ID")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "สวัสดี! ฉันคือบอท AI\nพิมพ์อะไรก็ได้เพื่อคุยกัน!",
        reply_markup=MAIN_KEYBOARD,
    )


async def setname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.args:
        name = " ".join(context.args)
        user_names[user_id] = name
        await update.message.reply_text(f"จำชื่อของคุณแล้วครับ: *{name}* 😊", parse_mode="Markdown")
    else:
        await update.message.reply_text("กรุณาบอกชื่อด้วยครับ เช่น `/setname เอก`", parse_mode="Markdown")


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"Chat ID ของคุณคือ: `{user_id}`", parse_mode="Markdown")


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_histories[user_id] = []
    await update.message.reply_text("ล้างประวัติแชทแล้ว เริ่มต้นใหม่ได้เลย!")


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current = get_user_model(user_id)

    if context.args:
        choice = context.args[0].lower()
        if choice in MODELS:
            user_models[user_id] = choice
            chat_histories[user_id] = []
            await update.message.reply_text(
                f"เปลี่ยนเป็น {MODELS[choice]['name']} แล้วครับ\n(ประวัติแชทถูกล้างอัตโนมัติ)"
            )
        else:
            await update.message.reply_text(
                f"ไม่พบโมเดลนี้ครับ\nใช้ได้: {', '.join(MODELS.keys())}"
            )
    else:
        model_list = "\n".join(
            [f"{'✅' if k == current else '▪️'} /model {k} — {v['name']}" for k, v in MODELS.items()]
        )
        await update.message.reply_text(f"AI ที่ใช้อยู่ตอนนี้:\n\n{model_list}")


RSS_FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://venturebeat.com/category/ai/feed/",
]

def fetch_and_summarize() -> str:
    headlines = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:
            headlines.append(f"- {entry.title}")
    headlines_text = "\n".join(headlines[:15])

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "คุณคือผู้ช่วยสรุปข่าว AI เป็นภาษาไทย"},
            {"role": "user", "content": f"""สรุปข่าว AI เหล่านี้เป็นภาษาไทย:

{headlines_text}

ใช้รูปแบบนี้:
🤖 *ข่าว AI วันนี้*
━━━━━━━━━━━━━━━

emoji สีประจำบริษัท:
🟠 = Anthropic/Claude, 🟢 = OpenAI/ChatGPT, 🔵 = Google/Gemini, ⚫ = xAI/Grok, 🟣 = Meta AI, 🔴 = Apple

แต่ละข่าว:
[emoji] *ชื่อบริษัท*
สรุป 1-2 ประโยค

เลือก 4-5 ข่าวสำคัญ ปิดท้ายด้วย ━━━━━━━━━━━━━━━"""}
        ],
        max_tokens=1024,
    )
    return response.choices[0].message.content


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        text = " ".join(context.args)
    else:
        await update.message.reply_text(
            "📝 วางข้อความที่อยากสรุปมาได้เลยครับ!\n\nตัวอย่าง:\n/summary ข้อความยาวๆ ที่นี่\n\nหรือกดปุ่ม 📝 สรุปข้อความ แล้วส่งข้อความตามมาได้เลย"
        )
        context.user_data["waiting_summary"] = True
        return

    await update.message.chat.send_action("typing")
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "คุณคือผู้ช่วยสรุปข้อความ สรุปให้กระชับ ชัดเจน เป็นภาษาเดียวกับข้อความต้นฉบับ"},
                {"role": "user", "content": f"สรุปข้อความนี้:\n\n{text}"},
            ],
            max_tokens=1024,
        )
        reply = response.choices[0].message.content
        await update.message.reply_text(f"📝 *สรุป:*\n\n{reply}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"เกิดข้อผิดพลาด: {str(e)}")


async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        text = " ".join(context.args)
        lang = "ภาษาอังกฤษ"
    else:
        await update.message.reply_text(
            "🌐 ส่งข้อความที่อยากแปลมาได้เลยครับ!\n\nบอทจะแปลให้อัตโนมัติ:\n- ถ้าเป็นไทย → แปลเป็นอังกฤษ\n- ถ้าเป็นภาษาอื่น → แปลเป็นไทย"
        )
        context.user_data["waiting_translate"] = True
        return

    await update.message.chat.send_action("typing")
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "คุณคือนักแปลภาษา ถ้าข้อความเป็นภาษาไทยให้แปลเป็นอังกฤษ ถ้าเป็นภาษาอื่นให้แปลเป็นไทย ตอบแค่คำแปลเท่านั้น ไม่ต้องอธิบาย"},
                {"role": "user", "content": text},
            ],
            max_tokens=1024,
        )
        reply = response.choices[0].message.content
        await update.message.reply_text(f"🌐 *คำแปล:*\n\n{reply}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"เกิดข้อผิดพลาด: {str(e)}")


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ กำลังดึงข่าว AI ล่าสุด รอสักครู่...")
    await update.message.chat.send_action("typing")
    try:
        summary = fetch_and_summarize()
        await update.message.reply_text(summary, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"เกิดข้อผิดพลาด: {str(e)}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    # จัดการปุ่ม keyboard
    if user_text == "📰 ข่าว AI":
        await news_command(update, context)
        return
    elif user_text == "🤖 เปลี่ยน AI":
        await model_command(update, context)
        return
    elif user_text == "📝 สรุปข้อความ":
        await update.message.reply_text("📝 ส่งข้อความที่อยากสรุปมาได้เลยครับ!")
        context.user_data["waiting_summary"] = True
        return
    elif user_text == "🌐 แปลภาษา":
        await translate_command(update, context)
        return
    elif user_text == "🗑 ล้างแชท":
        await clear(update, context)
        return
    elif user_text == "ℹ️ Chat ID":
        await chatid(update, context)
        return

    # ถ้ารอสรุปข้อความอยู่
    if context.user_data.get("waiting_summary"):
        context.user_data["waiting_summary"] = False
        context.args = user_text.split()
        await summary_command(update, context)
        return

    # ถ้ารอแปลภาษาอยู่
    if context.user_data.get("waiting_translate"):
        context.user_data["waiting_translate"] = False
        context.args = user_text.split()
        await translate_command(update, context)
        return

    if user_id not in chat_histories:
        chat_histories[user_id] = []

    chat_histories[user_id].append({"role": "user", "content": user_text})
    await update.message.chat.send_action("typing")

    try:
        reply = await ask_ai(user_id, chat_histories[user_id])
        chat_histories[user_id].append({"role": "assistant", "content": reply})

        if len(chat_histories[user_id]) > 20:
            chat_histories[user_id] = chat_histories[user_id][-20:]

        await update.message.reply_text(reply, reply_markup=MAIN_KEYBOARD)

    except Exception as e:
        await update.message.reply_text(f"เกิดข้อผิดพลาด: {str(e)}")


async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("setname", setname))
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("summary", summary_command))
    app.add_handler(CommandHandler("translate", translate_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("บอทเริ่มทำงานแล้ว...")
    async with app:
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
