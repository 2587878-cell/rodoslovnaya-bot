# bot.py
import os
import logging
import json  # ✅ Убедись, что импорт json здесь
import asyncio  # <-- ЭТА СТРОКА ДОЛЖНА БЫТЬ!
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup 
from telegram import Update as TgUpdate
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from openai import OpenAI  # ✅ Импортируем здесь
from datetime import datetime

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

import re

def parse_contact(raw_contact: str):
    if not raw_contact:
        return {"email": None, "phone": None, "telegram": None}

    text = raw_contact.lower().strip()
    result = {
        "raw": raw_contact,
        "email": None,
        "phone": None,
        "telegram": None
    }

    # 1. Email
    email_match = re.search(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b', text)
    if email_match:
        result["email"] = email_match.group()

    # 2. Телефон
    phone_match = re.search(r'(?:\+?7|8)[\s\-()]*?(\d[\s\-()]*?){10}', text)
    if phone_match:
        digits = re.sub(r'\D', '', phone_match.group())
        if len(digits) == 11 and digits.startswith('8'):
            digits = '7' + digits[1:]
        elif len(digits) == 10:
            digits = '7' + digits
        result["phone"] = f"+{digits}"

    # 3. Telegram — только если НЕ часть email
    # Убираем все email из текста, чтобы не ловить @gmail.com
    clean_text = re.sub(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b', '', text)

    tg_match = re.search(
        r'(?:@|t\.me/|https?://t\.me/)([a-zA-Z][a-zA-Z0-9_]{4,})|([a-zA-Z][a-zA-Z0-9_]{4,})(?=\s|$)',
        clean_text
    )
    if tg_match:
        username = tg_match.group(1) or tg_match.group(2)
        if username and len(username) >= 5 and not username.isdigit():
            result["telegram"] = f"@{username}"

    return result

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
    await update.message.reply_text("📬 Оставьте, пожалуйста, Ваш Telegram или email для связи:")
    return STEP_CONTACT

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["contact"] = update.message.text
    data = context.user_data
        # 🔽 ИЗВЛЕКАЕМ ФАМИЛИЮ ПРЕДКА 🔽
    full_name = data.get("fio", "")
    surname = ""
    if full_name:
        parts = full_name.strip().split()
        if len(parts) >= 1:
            surname = parts[0]  # Фамилия — первое слово
    # 🔼
    case_type = classify_case(f"{data['known']} {data['goal']}")
    data["case_type"] = case_type

    # 3. Парсим контакт
    contact_raw = update.message.text
    parsed_contact = parse_contact(contact_raw)
    data["contact_raw"] = contact_raw
    data["email"] = parsed_contact["email"]
    data["phone"] = parsed_contact["phone"]
    data["telegram"] = parsed_contact["telegram"]
    
    await update.message.reply_text(
    "<b> 🔍 Спасибо за анкету!</b>\n"
    "⏳ Rodoslovnaya.PRO анализирует данные по архивам и источникам…\n"
    "Подождите немного — скоро вы получите подробный план поиска.",
    parse_mode="HTML"
)
    await update.message.reply_chat_action("typing")
     # Переменные для контроля
    response_sent = False
    delay_task = None

    async def send_delay_notification():
        nonlocal response_sent
        await asyncio.sleep(10)
        if not response_sent:
            await update.message.reply_text(
                "⏳ Ваш генеалог формирует отчет — подождите немного, уже вот-вот..."
            )
            
    # Запускаем уведомление в фоне
    delay_task = asyncio.create_task(send_delay_notification())

    # Извлекаем год рождения из строки "даты"
    birth_year = None
    if data.get("dates"):
        # Находим все 4-значные числа в диапазоне 1700–2025
        years = re.findall(r'\b(1[7-9][0-9]{2}|20[0-2][0-5])\b', data["dates"])
        if years:
            birth_year = int(years[0])
    
    # Определяем, жив ли человек
    is_alive = any(k in data.get("known", "").lower() for k in ["жив", "живёт", "настоящее время", "по сей день"])
    
    # Формируем контекст источников
    source_context = "📌 Рекомендуемые источники по периоду:"
    
    if birth_year and birth_year >= 1920:
        # Современный период: только ЗАГСы
        source_context += f"\n• Для предков, родившихся после 1920 года, начните с **официальных запросов в региональные отделения ЗАГСов** по месту рождения, брака или смерти."
        if is_alive:
            source_context += f"\n• Учитывая, что {data['fio']} жив, акцент стоит сделать на **сборе устных свидетельств, семейных документов и фотоархивов**."
        source_context += f"\n• Онлайн-архивы (например, Яндекс.Архив) могут содержать упоминания в газетах, справочниках, переписях."
    else:
        # Исторический период: до 1920
        source_context += f"\n• Для предков, родившихся до 1920 года, используйте **архивированные данные**: метрические книги (до 1917), исповедные ведомости (до 1880-х), ревизские сказки (до 1858)."
        source_context += f"\n• Также проверьте данные **всеобщей переписи населения 1897 года** и **сельскохозяйственной переписи 1916 года** по местам, откуда предок предположительно родом."
        source_context += f"\n• Поиск в церковных архивах и фондах ФСГС (Федеральное Собрание Генеалогических Семей)."
    
    # Добавляем общие ресурсы
    source_context += f"""
    \n📌 Онлайн-ресурсы:
    • [ОБД Мемориал](https://obd-memorial.ru) — репрессии, военные, репатрианты
    • [Память народа](https://pamyat-naroda.ru) — фронтовики
    • [Подвиг народа](https://podvignaroda.ru) — награды
    • [Arolsen Archives](https://arolsen-archives.org) — военнопленные, "остарбайтеры"
    • [Genotek](https://genotek.ru) — ДНК-тесты для поиска родственников
    • [Yandex.Архив](https://yandex.ru/archive) — газеты, справочники, переписи
    • [Forum.VGD.ru](https://forum.vgd.ru) — консультации генеалогов
    """
    
    # 🔽 ФОРМИРУЕМ АНАЛИЗ ФАМИЛИИ 🔽
    surname_analysis = "Фамилия не указана."
    if surname:
        surname_analysis = f"""
    \n👪 АНАЛИЗ ФАМИЛИИ:
    Фамилия: {surname}
    Проанализируй происхождение фамилии '{surname}' и укажи:
    - Точное происхождение: от какого слова, имени или места (например: Зельпус — от латышского имени Zelpe)
    - Национальность: латышская, литовская, немецкая, русская и т.д.
    - Географическое распространение: регионы, страны (например: Латвия, Литва, Ленинградская область)
    - Суффикс: -ус (балтийский), -ов (русское отчественное) и его значение
    - Варианты написания: Zelpus, Zelpe, Зельпс
    - Связь с профессией, именем, местом: например, не связана с Мурзинкой
    - Рекомендации: где искать (Госархив ЛО, Arolsen, Latvijas Valsts arhīvs)
    - Какие документы могут содержать информацию (метрические книги, переписи, DP-лагеря)
    
    Не пиши общие фразы. Только конкретика.
    """
    else:
        surname_analysis = "Фамилия не указана."
    # 🔼
    # Формируем промпт для OpenAI
    prompt = f"""
Составь пошаговую стратегию поиска предков на основе данных:

📌 Исходные данные:
ФИО: {data['fio']}
Годы жизни: {data['dates']}
Место: {data['region']}
Известно: {data['known']}
Цель: {data['goal']}

{surname_analysis}

🧠 Рекомендации от Rodoslovnaya.pro:

Ответ должен быть:
- Структурирован как: "📌 ИСХОДНЫЕ ДАННЫЕ", "👪 АНАЛИЗ ФАМИЛИИ", "🔍 ПОШАГОВАЯ СТРАТЕГИЯ", "✅ ЧЕК-ЛИСТ"
- С указанием **актуальных источников** (см. ниже)
- С **конкретными ссылками** на архивы, ЗАГСы, онлайн-ресурсы для поиска
- С **примерными тарифами** (например: ЗАГС — 350–400 ₽)
- С рекомендацией по **ДНК-тесту (Genotek, MyHeritage)** для поиска родственников
- Без общих фраз — только конкретика
- На русском языке

{source_context}
"""
    try:
        # Проверка ключа
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY не найден!")
    
        client = OpenAI(api_key=api_key)
    
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """
Ты — профессиональный генеалог. Пиши чётко, по делу, с источниками, тарифами и ссылками. 
Никогда не пиши 'возможно', 'вероятно', 'предположительно'. 
Всегда давай конкретный ответ, как будто ты эксперт Rodoslovnaya.pro.

Для анализа фамилии:
- Указывай точное происхождение (не 'топонимическое', а 'латышское, от имени Zelpe')
- Называй национальность (не 'русская', а 'латышская, литовская')
- Объясняй суффиксы (-ус — балтийский)
- Давай конкретные архивы (Госархив ЛО, Latvijas Valsts arhīvs)
- Не выдумывай варианты написания — только реальные

При анализе любой фамилии используй следующую логику:
1. **Суффикс**:
   - "-ус", "-с", "-скус" → балтийские (латышские, литовские)
   - "-ов", "-ин" → русские, от отчества
   - "-ко", "-енко" → украинские
   - "-ский" → топонимические (от места)
   - "-ян", "-янц" → армянские
   - "-ян", "-янц" → армянские

2. **Распространение**:
   - Балтийские → ищите в Латвии, Литве, Калининграде, Ленинградской области
   - Татарские → Поволжье, Урал
   - Еврейские → Беларусь, Украина, Литва

3. **Не выдумывай происхождение**:
   - Если нет данных — скажи: "Нет точных данных, но по суффиксу и региону вероятно..."
   - Никогда не пиши: "возможно, от названия деревни", если нет подтверждения.
"""},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1500,
            temperature=0.7
        )
        ai_response = completion.choices[0].message.content.strip()
    
        # Оборачиваем ответ в фирменный стиль
        response = f"""🧠 Rodoslovnaya.PRO рекомендует:
    
    {ai_response}
    
"""
    
        # Отправляем ответ
        await update.message.reply_text(response)
        response_sent = True  # ✅ Отмечаем, что ответ отправлен
    except Exception as e:
        response = f"⚠️ Что-то пошло не так: {str(e)}\n\n Пожалуйста, попробуйте позже или напишите нам напрямую на @rodoslovnaya.pro."
        response_sent = True
    finally:
        # Отменяем задачу уведомления, если она ещё работает
        if delay_task and not delay_task.done():
            delay_task.cancel()

    # Сохраняем chat_id
    data["chat_id"] = update.effective_chat.id
    # Сохраняем в таблицу
    save_to_google_sheets({
        "fio": data.get("fio"),
        "dates": data.get("dates"),
        "region": data.get("region"),
        "known": data.get("known"),
        "goal": data.get("goal"),
        "chat_id": data.get("chat_id"),
        "contact": data.get("contact"),
        "email": data.get("email"),
        "phone": data.get("phone"),
        "telegram": data.get("telegram"),
        "case_type": case_type,
        "recommendations": response
    })
    # Запускаем в фоне
    chat_id = data["chat_id"]
    asyncio.create_task(send_follow_ups(chat_id, context.bot))  # ✅ Передаём bot

    return ConversationHandler.END
    
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Анкета отменена. Чтобы начать заново, нажмите /start")
    return ConversationHandler.END
    
# 🔔 ЗАПУСКАЕМ АВТОМАТИЧЕСКУЮ РАССЫЛКУ
async def send_follow_ups(chat_id: int, bot):
        try:
            # 0 день — сразу
            await asyncio.sleep(30)  # небольшая задержка
            keyboard = [[InlineKeyboardButton("Получить консультацию", callback_data="consultation")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await bot.send_message(
                chat_id=chat_id,  # ✅ Используем переданный chat_id
                text=f"👋 Спасибо за обращение!\n"
                     "Подписывайтесь на @rodoslovnaya_pro — свежие подсказки для самостоятельного поиска в архивах.\n"
                     "Подарим бесплатную мини-консультацию: подскажем, с чего начать. Нажмите «Получить консультацию».",
                reply_markup=reply_markup
            )

            # 3 день
            await asyncio.sleep(3 * 24 * 3600)  # 3 дня
            keyboard = [[InlineKeyboardButton("Хочу стартовый план", callback_data="consultation")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await bot.send_message(
                chat_id=chat_id,
                text="📜 В @rodoslovnaya_pro мы собрали для Вас материалы, которые помогут самостоятельно выстроить родословную — от первых шагов до архивных запросов.\n"
                     "Нужен персональный стартовый план?",
                reply_markup=reply_markup
            )

            # 7 день
            await asyncio.sleep(4 * 24 * 3600)  # ещё 4 дня = 7 день
            keyboard = [[InlineKeyboardButton("Получить консультацию", callback_data="consultation")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await bot.send_message(
                chat_id=chat_id,
                text="🎁 Держим для вас бесплатную консультацию: 3–5 шагов, куда писать и что приложить.\n"
                     "Нажмите «Получить консультацию» — свяжемся с Вами в ближайшее время!",
                reply_markup=reply_markup
            )

            # 14 день
            await asyncio.sleep(7 * 24 * 3600)  # ещё 7 дней = 14 день
            await bot.send_message(
                chat_id=chat_id,
                text="✨ Подарочные сертификаты для близких — консультация или исследование родословной.\n"
                     "Успей сегодня! Промокод **PRO10** на скидку 10% при оплате онлайн на http://rodoslovnaya.pro/"
            )

            # 30 день
            await asyncio.sleep(16 * 24 * 3600)  # ещё 16 дней = 30 день
            await bot.send_message(
                chat_id=chat_id,
                text="🕰 Готовы собрать вашу семейную историю: архивы + красивый альбом.\n"
                     "Подбери сегодня стартовый пакет с 10% скидкой по промокоду **PRO10** на http://rodoslovnaya.pro/"
            )

        except Exception as e:
            print(f"❌ Не удалось отправить сообщение: {e}")

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

        # Получаем chat_id из данных
        chat_id = data.get("chat_id", "")

        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data.get("fio"),
            data.get("dates"),
            data.get("region"),
            data.get("known"),
            data.get("goal"),
            chat_id, 
            data.get("contact"),
            data.get("email"),
            data.get("phone"),
            data.get("telegram"),
            data.get("case_type"),
            data.get("recommendations"),
            data.get("consultation_requested", "")
        ]
        sheet.append_row(row)
        print("✅ 6. ДАННЫЕ УСПЕШНО ДОБАВЛЕНЫ В ТАБЛИЦУ!")
    except Exception as e:
        print(f"❌ ОШИБКА при сохранении: {e}")
        
# 🔽 СЮДА ВСТАВЛЯЕМ button_callback 🔽
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("🔥 START: button_callback вызвана!", flush=True)  # 🔥 Должно быть в логах
    query = update.callback_query

    try:
        await query.answer()  # ✅ Подтверждаем нажатие
        print("✅ query.answer() отправлен", flush=True)

        if query.data == "consultation":
            # ✅ ВАЖНО: в PTB v20+ нет message.chat_id — используем .chat.id
            chat_id = query.message.chat.id
            user_name = query.from_user.full_name
            username = query.from_user.username
            telegram = f"@{username}" if username else ""
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            await query.edit_message_text(
            text="✅ Спасибо! Выберите удобное время для бесплатной консультации:\n\n"
                 "🔗 [Записаться на консультацию](https://calendar.app.google/YP6LwXcUwkT6tDJP9)\n\n"
                 "После записи вы получите подтверждение и напоминание!",
            parse_mode="Markdown",
            disable_web_page_preview=False
            )
            print(f"📝 Нажата кнопка: {query.data}, chat_id={chat_id}, пользователь={user_name}, время={timestamp}")
            try:
                save_to_google_sheets({
                    "fio": user_name,
                    "chat_id": chat_id,
                    "known": "Запрос на консультацию",
                    "goal": "Получить бесплатную консультацию",
                    "case_type": "консультация",
                    "recommendations": f"Запрос от пользователя через кнопку. Время: {timestamp}",
                    "consultation_requested": timestamp,
                    "telegram": telegram  # ✅ Теперь передаётся!
                })
            except Exception as e:
                print(f"❌ Ошибка при сохранении запроса на консультацию: {e}")
    except Exception as e:
        print("❌ Ошибка в button_callback")
# 🔼 СЮДА ВСТАВЛЯЕМ button_callback 🔼
async def consultation_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Отправляем ссылку на запись
    await update.message.reply_text(
        "✅ Спасибо за интерес к консультации!\n\n"
        "Выберите удобное время для бесплатной 15-минутной консультации:\n\n"
        "🔗 [Записаться на консультацию](https://calendar.app.google/YP6LwXcUwkT6tDJP9)\n\n"
        "После записи вы получите напоминание. Мы свяжемся с вами в выбранное время!",
        parse_mode="Markdown",
        disable_web_page_preview=False
    )

    # Сохраняем в таблицу (опционально)
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_name = user.full_name
    username = user.username
    telegram = f"@{username}" if username else ""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        save_to_google_sheets({
            "fio": user_name,
            "chat_id": chat_id,
            "known": "Команда /consultation",
            "goal": "Получить бесплатную консультацию",
            "case_type": "консультация",
            "recommendations": f"Пользователь вызвал /consultation. Время: {timestamp}",
            "consultation_requested": timestamp,
            "telegram": telegram
        })
    except Exception as e:
        print(f"❌ Ошибка при сохранении /consultation: {e}")

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
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel)
        ]
    )

    # Создаём приложение
    app = (
        Application.builder()
        .token(TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .get_updates_pool_timeout(10) # ✅ Обязательно
        .http_version("1.1")  
        .build()
    )
    # Добавляем обработчик
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("consultation", consultation_command))
    app.add_handler(CallbackQueryHandler(button_callback, pattern=r"^consultation$")) # ✅ Должно быть!

    # Запускаем бота
    app.run_polling(
    allowed_updates=TgUpdate.ALL_TYPES,
    drop_pending_updates=True,
)

# ✅ Запускаем main()
if __name__ == "__main__":
    main()
