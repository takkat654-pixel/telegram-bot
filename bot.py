import os
import asyncio
import re
import base64
import feedparser
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv
from urllib.parse import quote
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

chat_histories: dict[int, list] = {}
user_models: dict[int, str] = {}
user_names: dict[int, str] = {}
user_notes: dict[int, list[str]] = {}

MODELS = {
    "groq": {"name": "Groq (LLaMA 3.3)", "model": "llama-3.3-70b-versatile"},
    "gpt": {"name": "GPT-4o Mini", "model": "gpt-4o-mini"},
}
DEFAULT_MODEL = "groq"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
ADMIN_ID = 8550023812


def get_user_model(user_id: int) -> str:
    return user_models.get(user_id, DEFAULT_MODEL)


def get_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    return MAIN_KEYBOARD if user_id == ADMIN_ID else USER_KEYBOARD


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
        [KeyboardButton("🎨 สร้างภาพ"), KeyboardButton("🔍 วิเคราะห์รูป")],
        [KeyboardButton("📒 Note"), KeyboardButton("⏰ Reminder")],
        [KeyboardButton("🗑 ล้างแชท"), KeyboardButton("ℹ️ Chat ID")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

USER_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📰 ข่าว AI")],
        [KeyboardButton("📝 สรุปข้อความ"), KeyboardButton("🌐 แปลภาษา")],
        [KeyboardButton("🎨 สร้างภาพ"), KeyboardButton("🔍 วิเคราะห์รูป")],
        [KeyboardButton("📒 Note"), KeyboardButton("⏰ Reminder")],
        [KeyboardButton("🗑 ล้างแชท"), KeyboardButton("ℹ️ Chat ID")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


# ─── Existing Features ────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        "สวัสดี! ฉันคือบอท AI\nพิมพ์อะไรก็ได้เพื่อคุยกัน!",
        reply_markup=get_keyboard(user_id),
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

เลือก 4-5 ข่าวสำคัญ ปิดท้ายด้วย ━━━━━━━━━━━━━━━"""},
        ],
        max_tokens=1024,
    )
    return response.choices[0].message.content


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ กำลังดึงข่าว AI ล่าสุด รอสักครู่...")
    await update.message.chat.send_action("typing")
    try:
        summary = fetch_and_summarize()
        await update.message.reply_text(summary, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"เกิดข้อผิดพลาด: {str(e)}")


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        text = " ".join(context.args)
    else:
        await update.message.reply_text(
            "📝 วางข้อความที่อยากสรุปมาได้เลยครับ!\n\n"
            "ตัวอย่าง:\n/summary ข้อความยาวๆ ที่นี่\n\n"
            "หรือกดปุ่ม 📝 สรุปข้อความ แล้วส่งข้อความตามมาได้เลย"
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
    else:
        await update.message.reply_text(
            "🌐 ส่งข้อความที่อยากแปลมาได้เลยครับ!\n\n"
            "บอทจะแปลให้อัตโนมัติ:\n- ถ้าเป็นไทย → แปลเป็นอังกฤษ\n- ถ้าเป็นภาษาอื่น → แปลเป็นไทย"
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


# ─── Image Generation (Pollinations.ai) ──────────────────────────────────────

async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        await _do_generate_image(update, " ".join(context.args))
    else:
        await update.message.reply_text(
            "🎨 บอกว่าอยากให้สร้างภาพอะไรครับ!\n\n"
            "ตัวอย่าง: `/image แมวน่ารักนั่งในป่า`\n\n"
            "หรือกดปุ่ม 🎨 สร้างภาพ แล้วส่งคำบรรยายตามมาได้เลย",
            parse_mode="Markdown",
        )
        context.user_data["waiting_image"] = True


async def _do_generate_image(update: Update, prompt: str):
    await update.message.reply_text("⏳ กำลังสร้างภาพ รอสักครู่...")
    await update.message.chat.send_action("upload_photo")
    try:
        image_url = (
            f"https://image.pollinations.ai/prompt/{quote(prompt)}"
            "?width=1024&height=1024&nologo=true"
        )
        await update.message.reply_photo(image_url, caption=f"🎨 {prompt}")
    except Exception as e:
        await update.message.reply_text(f"เกิดข้อผิดพลาด: {str(e)}")


# ─── Image Analysis (Groq Vision) ────────────────────────────────────────────

async def analyze_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        question = update.message.caption or "อธิบายรูปภาพนี้อย่างละเอียดเป็นภาษาไทย"

        response = groq_client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                        {"type": "text", "text": question},
                    ],
                }
            ],
            max_tokens=1024,
        )
        reply = response.choices[0].message.content
        await update.message.reply_text(f"🔍 *วิเคราะห์รูปภาพ:*\n\n{reply}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"เกิดข้อผิดพลาด: {str(e)}")


# ─── Notes ────────────────────────────────────────────────────────────────────

async def note_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "กรุณาพิมพ์ข้อความที่ต้องการบันทึก\nตัวอย่าง: `/note ซื้อนมพรุ่งนี้`",
            parse_mode="Markdown",
        )
        return
    text = " ".join(context.args)
    user_notes.setdefault(user_id, []).append(text)
    idx = len(user_notes[user_id])
    await update.message.reply_text(f"📒 บันทึกแล้ว (#{idx}): {text}")


async def notes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    notes = user_notes.get(user_id, [])
    if not notes:
        await update.message.reply_text("📒 ยังไม่มี note ครับ\nพิมพ์ /note <ข้อความ> เพื่อเพิ่ม")
        return
    lines = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(notes))
    await update.message.reply_text(f"📒 *Notes ของคุณ:*\n\n{lines}", parse_mode="Markdown")


async def delnote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    notes = user_notes.get(user_id, [])
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "ระบุหมายเลข note ที่ต้องการลบ\nตัวอย่าง: `/delnote 1`",
            parse_mode="Markdown",
        )
        return
    idx = int(context.args[0]) - 1
    if idx < 0 or idx >= len(notes):
        await update.message.reply_text(f"ไม่พบ note หมายเลข {idx + 1}")
        return
    deleted = notes.pop(idx)
    await update.message.reply_text(f"🗑 ลบแล้ว: {deleted}")


# ─── Reminder ─────────────────────────────────────────────────────────────────

def parse_duration(text: str) -> int | None:
    total = 0
    matches = re.findall(r"(\d+)([hms])", text.lower())
    if not matches:
        return None
    for value, unit in matches:
        if unit == "h":
            total += int(value) * 3600
        elif unit == "m":
            total += int(value) * 60
        elif unit == "s":
            total += int(value)
    return total or None


async def remind_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(
        chat_id=job.chat_id,
        text=f"⏰ *Reminder:* {job.data}",
        parse_mode="Markdown",
    )


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "⏰ ตั้ง reminder ได้เลยครับ!\n\n"
            "รูปแบบ: `/remind <เวลา> <ข้อความ>`\n\n"
            "ตัวอย่าง:\n"
            "`/remind 5m ดื่มน้ำ`\n"
            "`/remind 1h ประชุม`\n"
            "`/remind 30s ทดสอบ`\n"
            "`/remind 1h30m ออกกำลังกาย`",
            parse_mode="Markdown",
        )
        return

    duration_str = context.args[0]
    message = " ".join(context.args[1:])
    seconds = parse_duration(duration_str)

    if seconds is None:
        await update.message.reply_text(
            "รูปแบบเวลาไม่ถูกต้อง ใช้ เช่น `5m`, `1h`, `30s`, `1h30m`",
            parse_mode="Markdown",
        )
        return

    if context.job_queue is None:
        await update.message.reply_text("ฟีเจอร์ Reminder ยังไม่พร้อมใช้งานครับ")
        return

    context.job_queue.run_once(
        remind_callback,
        when=seconds,
        chat_id=update.effective_chat.id,
        data=message,
    )

    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours} ชั่วโมง")
    if minutes:
        parts.append(f"{minutes} นาที")
    if secs:
        parts.append(f"{secs} วินาที")

    await update.message.reply_text(
        f"⏰ ตั้ง reminder แล้ว!\nจะแจ้งเตือน *\"{message}\"* ในอีก {' '.join(parts)}",
        parse_mode="Markdown",
    )


# ─── Message Handler ──────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    # Keyboard buttons
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
    elif user_text == "🎨 สร้างภาพ":
        await update.message.reply_text("🎨 บอกว่าอยากให้สร้างภาพอะไรครับ? ส่งคำบรรยายมาเลย!")
        context.user_data["waiting_image"] = True
        return
    elif user_text == "🔍 วิเคราะห์รูป":
        await update.message.reply_text(
            "🔍 ส่งรูปภาพมาได้เลยครับ!\n\nใส่ caption ในรูปเพื่อถามคำถามเพิ่มเติมได้ เช่น \"มีอะไรในรูปนี้?\""
        )
        return
    elif user_text == "📒 Note":
        await notes_command(update, context)
        await update.message.reply_text(
            "คำสั่ง Note:\n"
            "/note <ข้อความ> — เพิ่ม note\n"
            "/notes — ดู notes ทั้งหมด\n"
            "/delnote <หมายเลข> — ลบ note"
        )
        return
    elif user_text == "⏰ Reminder":
        await update.message.reply_text(
            "⏰ ตั้ง reminder:\n"
            "`/remind <เวลา> <ข้อความ>`\n\n"
            "ตัวอย่าง:\n"
            "`/remind 5m ดื่มน้ำ`\n"
            "`/remind 1h ประชุม`\n"
            "`/remind 1h30m ออกกำลังกาย`",
            parse_mode="Markdown",
        )
        return
    elif user_text == "🗑 ล้างแชท":
        await clear(update, context)
        return
    elif user_text == "ℹ️ Chat ID":
        await chatid(update, context)
        return

    # Waiting states
    if context.user_data.get("waiting_summary"):
        context.user_data["waiting_summary"] = False
        context.args = user_text.split()
        await summary_command(update, context)
        return

    if context.user_data.get("waiting_translate"):
        context.user_data["waiting_translate"] = False
        context.args = user_text.split()
        await translate_command(update, context)
        return

    if context.user_data.get("waiting_image"):
        context.user_data["waiting_image"] = False
        await _do_generate_image(update, user_text)
        return

    # Normal AI chat
    chat_histories.setdefault(user_id, [])
    chat_histories[user_id].append({"role": "user", "content": user_text})
    await update.message.chat.send_action("typing")

    try:
        reply = await ask_ai(user_id, chat_histories[user_id])
        chat_histories[user_id].append({"role": "assistant", "content": reply})

        if len(chat_histories[user_id]) > 20:
            chat_histories[user_id] = chat_histories[user_id][-20:]

        await update.message.reply_text(reply, reply_markup=get_keyboard(user_id))

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
    app.add_handler(CommandHandler("image", image_command))
    app.add_handler(CommandHandler("note", note_command))
    app.add_handler(CommandHandler("notes", notes_command))
    app.add_handler(CommandHandler("delnote", delnote_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(MessageHandler(filters.PHOTO, analyze_photo))
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
