# bot.py
import os
import logging
import json
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
from datetime import datetime

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния анкеты
STEP_FIO, STEP_DATES, STEP_REGION, STEP_KNOWN, STEP_GOAL, STEP_CONTACT = range(6)

# Типы кейсов и шаблоны
CASE_TEMPLATES = {
    "репрессии": """
🧠 Rodoslovnaya.pro рекомендует:

🗂 Что можно запросить:
* следственные материалы (допросы, обвинение),
* приговор (чаще — «тройкой НКВД»),
* справка о приведении приговора в исполнение,
* справка о реабилитации.

📄 Что потребуется:
✅ Цепочка документов, подтверждающих родство:
* свидетельство о рождении заявителя,
* свидетельство о рождении родителя,
* свидетельство о браке — если менялась фамилия.
📎 Дополнительно:
* паспорт заявителя (копия),
* заявление (мы вышлем шаблон),
* согласие на обработку данных.

🗺 Куда обращаться:
1. В УФСБ по региону следствия.
2. Отправьте письмо по Почте России с уведомлением и описью вложения.
3. Или сдайте лично — если вы в регионе.

📝 Образец заявления:
Мы вышлем адаптированный шаблон — просто напишите нам.
Или используйте общий шаблон: https://rodoslovnaya.pro/shtablon-ufsb.pdf

🌐 Полезные источники:
* Открытый список / OpenList
* Жертвы политического террора в СССР
* Архив Яндекса
* ОБД «Мемориал» — https://obd-memorial.ru

📬 Нужна помощь?
Заполните заявку на сайте rodoslovnaya.pro,
напишите на predki@rodoslovnaya.pro
или в Telegram: @rodoslovnaya_pro
    """,

    "плен": """
🧠 Rodoslovnaya.pro рекомендует:

🇷🇺 Военные и пленные:
1. Проверьте ОБД «Мемориал»
👉 https://obd-memorial.ru
Ищите по ФИО и году рождения. Особенно важно, если он был пропавшим без вести или попал в плен — там могут быть:
    • учетные карточки,
    • донесения о потерях,
    • списки обмена и т. д.

2. Портал «Память народа»
👉 https://pamyat-naroda.ru
Здесь можно найти:
    • данные о призыве,
    • списки пленных,
    • архивные документы о военной службе.

3. 🇩🇪 Arolsen Archives (бывший WASt)
👉 https://arolsen-archives.org
Особенно полезен, если он был в немецком плену. Здесь хранятся:
    • лагерные карточки (шталаг, офлаг),
    • информация о перемещениях и судьбе пленных.

📌 Для запроса данных в Arolsen нужно:
• Зарегистрироваться,
• Заполнить форму запроса на англ. или нем. языке,
• Желательно приложить данные о месте пленения или службе.

🧾 Поиск после войны:
4. Проверьте ЗАГС по месту смерти:
    • Запросите свидетельство о смерти — оно может содержать:
        • место смерти,
        • место захоронения,
        • супруга, детей (если кто-то оформлял),
        • причину смерти.

5. ⚠️ Если с момента смерти прошло < 100 лет — потребуется доказать родство:
    • свидетельство о рождении матери,
    • ваше свидетельство о рождении,
    • цепочка родства.

💡 Что ещё можно сделать:
• Отправить запрос в городской архив (трудовые, адресные карточки).
• Проверить сайт «Подвиг народа» — вдруг есть награды.
• Сделать ДНК-тест на Y-хромосому (через сына) — чтобы найти потомков.

🔬 Генетическая проверка
🧬 Genotek — ДНК-тесты для поиска родственников
Рекомендуем:
• "Навигатор" — для поиска дальних родственников;
• "Генеалогия по мужской линии (Y-ДНК)" — если нужно подтвердить мужскую линию.

📬 Нужна помощь?
Заполните заявку на сайте rodoslovnaya.pro,
напишите на predki@rodoslovnaya.pro
или в Telegram: @rodoslovnaya_pro
    """,

    "осуждён": """
🧠 Rodoslovnaya.pro рекомендует:

🔍 Шаг 1. Запрос свидетельства о рождении в ЗАГС
📌 Почему: в документе указаны оба родителя — ФИО, возраст, место проживания.
🗂 Куда обращаться: Архив ЗАГС региона рождения.
⚠️ Условие: потребуется подтвердить родство.
💰 Тариф: 350–400 ₽ | ⏳ Срок: 7–30 дней

🔐 Шаг 2. Запрос в ФСИН / МВД по факту осуждения
📌 Почему: в уголовном деле почти всегда указаны родители, место рождения, анкета, приговор.
🗂 Куда обращаться:
• ФСИН России,
• Архив МВД региона отбывания срока.

🏡 Шаг 3. Справки по месту смерти
📌 Что можно запросить:
• Свидетельство о смерти — может содержать место рождения, возраст, родителей.
• Домовые книги, карточки прописки — в архиве.

🪪 Шаг 4. Проверить базы:
• 🔗 ОБД «Мемориал» — https://obd-memorial.ru
• 🔗 Память народа — https://pamyat-naroda.ru
• 🔗 Подвиг народа — https://podvignaroda.ru
• 🔗 Архив Яндекса — поиск по фамилии

🧬 Шаг 5. ДНК-тест (если документов нет)
📌 Рекомендуем:
• Y-хромосома (для мужской линии),
• Загрузка в GEDmatch, MyHeritage, FamilyTreeDNA.

📬 Нужна помощь?
Заполните заявку на сайте rodoslovnaya.pro,
напишите на predki@rodoslovnaya.pro
или в Telegram: @rodoslovnaya_pro
    """,

    "раскулаченные": """
🧠 Rodoslovnaya.pro рекомендует:

1. Поиск в архивах по делам о раскулачивании
📌 Куда: Госархив области рождения (например, ГАСО, ГАТО).
📎 Документы: анкеты, списки, описи имущества, допросы.
💡 В них часто указаны родители, братья, соседи.

2. Метрические книги и исповедные ведомости
📌 Где: приходы деревни, где жил предок.
📎 FamilySearch.org — много оцифрованных записей.

3. Ревизские сказки (1850–1858 гг.)
📌 Где: ГАСО, ГАТО, fgurgia.ru
💡 Позволяют пройти на 2–3 поколения назад.

4. Военные документы (если был в ВОВ)
📌 Где:
• Память народа — https://pamyat-naroda.ru
• Подвиг народа — https://podvignaroda.ru
• ЦАМО — для официального запроса

🧬 ДНК-тест — для поиска родственников по фамилии
📌 Genotek: тесты «Навигатор», «Y-ДНК»

📬 Нужна помощь?
Заполните заявку на сайте rodoslovnaya.pro,
напишите на predki@rodoslovnaya.pro
или в Telegram: @rodoslovnaya_pro
    """,

    "внебрачное": """
🧠 Rodoslovnaya.pro рекомендует:

📌 Если отцовство не оформлено:
1. Проверьте свидетельство о рождении — если отец указан, это основание для запроса документов.

2. Запросите свидетельство о смерти — может содержать сведения о детях.

3. Поищите в архивах:
• трудовые книжки,
• адресные карточки,
• личные дела.

🧬 ДНК-тест — лучший способ подтвердить родство:
• Y-хромосома — для мужской линии,
• Авто-ДНК — для поиска родственников.

📌 Ресурсы:
• Genotek — https://genotek.ru
• GEDmatch — https://gedmatch.com
• MyHeritage — https://myheritage.ru

📬 Нужна помощь?
Заполните заявку на сайте rodoslovnaya.pro,
напишите на predki@rodoslovnaya.pro
или в Telegram: @rodoslovnaya_pro
    """,

    "родословная": """
🧠 Rodoslovnaya.pro рекомендует:

📌 1. Начни с документов из ЗАГСа
🗂 Что можно запросить:
* Свидетельство о рождении
* Свидетельство о браке родителей
* Справку о смерти
* Справку о смене фамилии
⏳ Записи хранятся в ЗАГСе 100 лет, потом передаются в архив.
📄 Если не прошло 100 лет — нужны документы, подтверждающие родство.
📬 Обратиться можно:
* в местный ЗАГС,
* либо через Госуслуги, МФЦ.
💰 Примерный тариф: 350–400 ₽ за справку
⏱ Срок: от 7 до 30 дней

🏛 2. Архивы региона
📁 В архиве можно запросить:
* подомовые книги,
* адресные карточки,
* документы о трудоустройстве и учебе
🌐 Сайт архива: уточните по региону
💳 Доступ к цифровым копиям — от ~90 ₽ в сутки

🧭 3. Онлайн-ресурсы
* 🔗 Архив Яндекса — https://yandex.ru/collections
* 🔗 Форум ВГД — https://forum.vgd.ru
* 🔗 Архивы.ру — https://arhivy.ru

📬 Нужна помощь?
Заполните заявку на сайте rodoslovnaya.pro,
напишите на predki@rodoslovnaya.pro
или в Telegram: @rodoslovnaya_pro
    """,

    "общий": """
🧠 Rodoslovnaya.pro рекомендует:

📌 Рекомендуем начать с:
1. Свидетельства о рождении (через ЗАГС или архив)
2. Поиска в ОБД «Мемориал», «Память народа», «Подвиг народа»
3. Проверки метрических книг и ревизских сказок
4. ДНК-теста (Genotek) для поиска родственников

💰 Примерные тарифы:
• Справка из ЗАГС: 350–400 ₽
• Доступ к архивам: от 90 ₽/сутки
• Аналоговый поиск: от 500 ₽ за запрос

📚 Глубина источников:
• ЗАГС — с 1920-х
• Метрические книги — с 1720-х до 1917
• Исповедные ведомости — до 1880-х
• Ревизские сказки — до 1858 г.

📬 Нужна помощь?
Заполните заявку на сайте rodoslovnaya.pro,
напишите на predki@rodoslovnaya.pro
или в Telegram: @rodoslovnaya_pro
    """
}

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

# Google Sheets
def save_to_google_sheets(data):
    try:
        print("✅ 1. Начинаем сохранение в Google Таблицу...")
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        print("✅ 2. Загружаем учётные данные...")

        # Получаем JSON из переменной
        json_creds = os.getenv("GOOGLE_CREDENTIALS")
        if not json_creds:
            raise EnvironmentError("Переменная GOOGLE_CREDENTIALS не найдена")

        creds_dict = json.loads(json_creds)
        print("✅ 3. JSON успешно распарсен")

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        print("✅ 4. Учётные данные созданы")

        client = gspread.authorize(creds)
        print("✅ 5. Подключились к Google Sheets API")

        sheet = client.open_by_url(os.getenv("GOOGLE_SHEET_URL")).sheet1
        print("✅ 6. Подключились к таблице")

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
        print("✅ 7. ДАННЫЕ УСПЕШНО ДОБАВЛЕНЫ В ТАБЛИЦУ!")
    except Exception as e:
        print(f"❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
# Команда /start
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
    case_type = classify_case(f"{data['known']} {data['goal']}")
    data["case_type"] = case_type

    # Генерируем ответ
    response = CASE_TEMPLATES.get(case_type, CASE_TEMPLATES["общий"])
    final_response = f"🧠 Совет от Rodoslovnaya.pro:\n\n{response}\n\n📬 Нужна помощь?..."

    # Отправляем ответ
    await update.message.reply_text(final_response)

    # Сохраняем ВСЁ, включая ответ
    save_to_google_sheets({
        "fio": data.get("fio"),
        "dates": data.get("dates"),
        "region": data.get("region"),
        "known": data.get("known"),
        "goal": data.get("goal"),
        "contact": data.get("contact"),
        "case_type": case_type,
        "recommendations": response  # Сохраняем рекомендации
    })

    return ConversationHandler.END

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
