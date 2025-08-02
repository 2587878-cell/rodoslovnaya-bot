# bot.py
import os
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import openai
from datetime import datetime

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Устанавливаем API-ключ OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Состояния анкеты
STEP_FIO, STEP_DATES, STEP_REGION, STEP_KNOWN, STEP_GOAL, STEP_CONTACT = range(6)

# Классификация кейса (опционально — можно использовать для анализа)
def classify_case(text):
    text = text.lower()
    if any(k in text for k in ["арестован", "расстрелян", "реабилитирован", "тройка", "нквд", "к-р", "шпион"]):
        return "репрессии"
    elif any(k in text for k in ["плен", "шталаг", "офлаг", "arolsen", "wast", "военнопленный"]):
        return "плен"
    elif any(k in text for k in ["осуждён", "уголовное дело", "срок", "тюрьма", "мурмаши"]):
        return "осуждён"
    elif any(k in text for k in ["кулак", "раскулачены", "спецпереселение"]):
        return "раскулаченные"
    elif any(k in text for k in ["внебрачный", "не был женат", "отцовство", "родился от"]):
        return "внебрачное"
    elif "родословная" in text or "предки" in text:
        return "родословная"
    else:
        return "общий"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я — бот проекта Rodoslovnaya.pro.\n"
        "Готов помочь тебе в поиске предков.\n"
        "Напиши ФИО предка, историю которого хочешь исследовать."
    )
    return STEP_FIO

async def handle_fio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["fio"] = update.message.text
    await update.message.reply_text("📆 Примерные годы жизни?")
    return STEP_DATES

async def handle_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["dates"] = update.message.text
    await update.message.reply_text("📍 Где жил предок?")
    return STEP_REGION

async def handle_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["region"] = update.message.text
    await update.message.reply_text("📄 Что ты уже знаешь о нём?")
    return STEP_KNOWN

async def handle_known(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["known"] = update.message.text
    await update.message.reply_text("🔍 Что хочешь узнать?")
    return STEP_GOAL

async def handle_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["goal"] = update.message.text
    await update.message.reply_text("📬 Оставь Telegram или email для связи:")
    return STEP_CONTACT

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["contact"] = update.message.text
    data = context.user_data

    # Формируем промпт для OpenAI
    prompt = f"""
Составь пошаговую стратегию поиска предков на основе данных:

📌 Исходные данные:
ФИО: {data['fio']}
Годы жизни: {data['dates']}
Место: {data['region']}
Известно: {data['known']}
Цель: {data['goal']}

🧠 Рекомендации от Rodoslovnaya.pro:

Ответ должен быть:
- Структурирован как в примере: "📌 Исходные данные", "🔍 ПОШАГОВАЯ СТРАТЕГИЯ", "✅ Чек-лист"
- С источниками, ссылками, тарифами (например: ЗАГС — 350–400 ₽)
- Указанием глубины источников (метрические книги — до 1917, ревизские сказки — до 1858 и т.д.)
- На русском языке
- Без общих фраз
- Включай ссылки: ОБД Мемориал, Память народа, Подвиг народа, Arolsen, Genotek
- Указывай, где искать (архивы, ЗАГСы, форумы)
    """

    try:
        completion = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Ты — профессиональный генеалог. Пиши чётко, по делу, с источниками, тарифами и ссылками."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1500,
            temperature=0.7
        )
        response = completion.choices[0].message.content.strip()
    except Exception as e:
        response = f"⚠️ Ошибка при генерации совета: {str(e)}\n\nПопробуйте позже или напишите нам напрямую."

    # Отправляем ответ пользователю
    await update.message.reply_text(response)

    # Сохраняем в Google Таблицу (включая ответ)
    save_to_google_sheets({
        "fio": data.get("fio"),
        "dates": data.get("dates"),
        "region": data.get("region"),
        "known": data.get("known"),
        "goal": data.get("goal"),
        "contact": data.get("contact"),
        "case_type": classify_case(f"{data['known']} {data['goal']}"),
        "recommendations": response
    })

    return ConversationHandler.END

def save_to_google_sheets(data):
    try:
        print("✅ 1. Начинаем сохранение в Google Таблицу...")
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        
        # Читаем JSON из переменной
        json_creds = os.getenv("GOOGLE_CREDENTIALS")
        if not json_creds:
            raise EnvironmentError("Переменная GOOGLE_CREDENTIALS не найдена")
        
        import json
        creds_dict = json.loads(json_creds)
        print("✅ 2. JSON успешно распарсен")

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        print("✅ 3. Учётные данные созданы")

        client = gspread.authorize(creds)
        print("✅ 4. Подключились к Google Sheets API")

        sheet = client.open_by_url(os.getenv("GOOGLE_SHEET_URL")).sheet1
        print("✅ 5. Подключились к таблице")

        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data.get("fio"),
            data.get("dates"),
            data.get("region"),
            data.get("known"),
            data.get("goal"),
            data.get("contact"),
            data.get("case_type"),
            data.get("recommendations")  # Полный ответ бота
        ]
        sheet.append_row(row)
        print("✅ 6. ДАННЫЕ УСПЕШНО ДОБАВЛЕНЫ В ТАБЛИЦУ!")
    except Exception as e:
        print(f"❌ ОШИБКА при сохранении: {e}")

def main():
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    if not TOKEN:
        logger.error("Токен не найден! Установите переменную TELEGRAM_TOKEN")
        return

    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            STEP_FIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fio)],
            STEP_DATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_dates)],
            STEP_REGION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_region)],
            STEP_KNOWN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_known)],
            STEP_GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_goal)],
            STEP_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_contact)],
        },
        fallbacks=[]
    )

    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
