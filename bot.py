# bot.py
import os
import logging
import json  # ✅ Убедись, что импорт json здесь
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
from openai import OpenAI  # ✅ Импортируем здесь
from datetime import datetime

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния анкеты
STEP_FIO, STEP_DATES, STEP_REGION, STEP_KNOWN, STEP_GOAL, STEP_CONTACT = range(6)

# Классификация кейса
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
        "👋 Здравствуйте! Я — бот проекта Rodoslovnaya.pro.\n"
        "Подготовлю для Вас рекомендации для самостоятельного поиска информации о судьбе Ваших предков по документам и архивам.\n"
        "Расскажите о предке, чью историю Вы хотели бы исследовать.\n\n"
        "📌 Начнём с ФИО предка:"
    )
    return STEP_FIO

async def handle_fio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["fio"] = update.message.text
    await update.message.reply_text("📅 Примерные годы жизни предка (например: 1890–1942):")
    return STEP_DATES

async def handle_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["dates"] = update.message.text
    await update.message.reply_text(
    "📍 Где жил предок? Укажите:\n"
    "• Место рождения (деревня, село, город)\n"
    "• Где проживал\n"
    "• Где умер и похоронен (если известно)\n\n"
    "Пример: родился Петрово, Рязанская обл., затем Оренбургская область, умер в Алексине Тульская область"
)
    return STEP_REGION

async def handle_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["region"] = update.message.text
    await update.message.reply_text(
    "📚 Что Вы уже знаете о предке?\n"
    "Укажите всё, что передавали в семье:\n"
    "• Профессия, военная служба\n"
    "• Судьба в войну, репрессии, плен\n"
    "• Родственные связи (отец, мать — по имени-отчеству)\n"
    "• Интересные факты (например: «делал волокуши», «капитан с Кронштадта»)"
)
    return STEP_KNOWN

async def handle_known(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["known"] = update.message.text
    await update.message.reply_text(
    "🎯 Что бы Вы хотели узнать о предке и его фамильном роде?\n"
    "Выберите или укажите:\n"
    "• Кто были его родители?\n"
    "• Где он родился и где похоронен?\n"
    "• Какова была его судьба в войну или в репрессиях?\n"
    "• Из какого он рода, есть ли более ранние предки?\n"
    "• Что подтвердит его подвиг или трудовой путь?"
)
    return STEP_GOAL

async def handle_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["goal"] = update.message.text
    await update.message.reply_text("📬 Оставьте, пожалуйста, Telegram или email для связи:")
    return STEP_CONTACT

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["contact"] = update.message.text
    data = context.user_data
    case_type = classify_case(f"{data['known']} {data['goal']}")
    data["case_type"] = case_type
    
    await update.message.reply_text(
    "⏳ <b> 🔍 Спасибо за анкету!</b>\n"
    "🧠 Rodoslovnaya.pro анализирует данные по архивам и источникам…\n"
    "Подождите немного — скоро вы получите подробный план поиска.",
    parse_mode="HTML"
)
    await update.message.reply_chat_action("typing")
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
- Структурирован как: "📌 Исходные данные", "🔍 ПОШАГОВАЯ СТРАТЕГИЯ", "✅ Чек-лист", "📬 Нужна помощь?"
- С указанием **глубины источников**: ЗАГСы (с 1920-х по настоящее время), метрические книги (c 1700 до 1917), ревизские сказки (c 1700 до 1858), исповедные ведомости (c 1700 до 1880-х), данные сельскохозяйственной переписи 1916 года, данные всеобщей перепись населения 1897
- С **конкретными ссылками** на архивы, ЗАГСы, онлайн-ресурсы (не общие, а точные: https://obd-memorial.ru, https://pamyat-naroda.ru, https://arolsen-archives.org)
- С **точными рекомендациями по архивам**:
  • Если предок был в плену или репатриирован — укажи **конкретный архив по региону** (например: Госархив Мурманской области, фонд Р-140)
  • Используй данные из файла "фильтрация 20.06.2024.xlsx"
  • Укажи: "фильтрационно-проверочные дела", "табельные карточки", "списки репатриированных"
- С **примерными тарифами** (например: ЗАГС — 350–400 ₽, архив — от 500 ₽)
- С рекомендацией по **ДНК-тесту (Genotek, MyHeritage)** для поиска родственников
- Без общих фраз — только конкретика
- На русском языке
    """

    try:
        # Проверка ключа
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY не найден!")
    
        client = OpenAI(api_key=api_key)
    
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Ты — профессиональный генеалог. Пиши чётко, по делу, с источниками, тарифами и ссылками. Не добавляй вступления вроде 'Вот пошаговая стратегия' — начинай сразу с содержания."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1500,
            temperature=0.7
        )
        ai_response = completion.choices[0].message.content.strip()
    
        # Оборачиваем ответ в фирменный стиль
        response = f"""🧠 Rodoslovnaya.PRO рекомендует:
    
    {ai_response}
    
    📬 Нужна помощь?
    Заполните заявку на сайте rodoslovnaya.pro,
    напишите нам на predki@rodoslovnaya.pro
    или в Telegram @rodoslovnaya_pro"""
    except Exception as e:
        response = f"⚠️ Ошибка при генерации совета: {str(e)}\n\nПопробуйте позже или напишите нам напрямую."

    # Отправляем ответ
    await update.message.reply_text(response)

    # Сохраняем в таблицу
    save_to_google_sheets({
        "fio": data.get("fio"),
        "dates": data.get("dates"),
        "region": data.get("region"),
        "known": data.get("known"),
        "goal": data.get("goal"),
        "contact": data.get("contact"),
        "case_type": case_type,
        "recommendations": response
    })

    return ConversationHandler.END

def save_to_google_sheets(data):
    try:
        print("✅ 1. Начинаем сохранение в Google Таблицу...")
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]  # ✅ Исправлено: убраны пробелы
        
        json_creds = os.getenv("GOOGLE_CREDENTIALS")
        if not json_creds:
            raise EnvironmentError("Переменная GOOGLE_CREDENTIALS не найдена")
        
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
            data.get("recommendations")
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
    # 🔽 ДОБАВЬ СЮДА ПРИНТ 🔽
    print(f"TELEGRAM_TOKEN: {'Да, есть' if TOKEN else 'Нет!'}")
    print(f"OPENAI_API_KEY: {os.getenv('OPENAI_API_KEY')}")
    print(f"GOOGLE_SHEET_URL: {os.getenv('GOOGLE_SHEET_URL')}")
    # 🔼 ДОБАВЬ СЮДА ПРИНТ 🔼

    # Проверка OpenAI API Key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY не найден! Бот не сможет генерировать советы.")
        return
        
    # Создаём обработчик диалога
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

    # Создаём приложение
    app = (
        Application.builder()
        .token(TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )

    # Добавляем обработчик
    app.add_handler(conv_handler)

    # Запускаем бота
    app.run_polling()

# ✅ Запускаем main()
if __name__ == "__main__":
    main()
