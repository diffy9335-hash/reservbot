import asyncio
import functools
import logging
import random
import json
import os
import time
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# --- НАСТРОЙКА ЛОГОВ И ТОКЕНА ---
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = "8979310355:AAHyNdXMeqNssz741ARifPC89lVnUknN7IU"

SPONSOR_CHANNEL_ID = "@jdoauqh"
SPONSOR_CHANNEL_URL = "https://t.me/jdoauqh"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

ADMINS = ["Diffysh1", "SilentRagex"]

PLAYERS_FILE = "players.json"
LEADERBOARD_FILE = "leaderboard.json"
TABLES_FILE = "tables.json"
SLOTS_FILE = "slots.json"
EURO_FILE = "euro_qualification.json"

def _load_data_sync(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            backup_name = f"{filename}.corrupted_{int(time.time())}"
            os.replace(filename, backup_name)
            logging.error(f"Файл {filename} был поврежден ({e}) и переименован в {backup_name}. Создан новый.")
            return {}
    return {}

def _save_data_sync(filename, data):
    tmp_path = f"{filename}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp_path, filename)

_cache_locks = {}

def get_cache_lock(filename):
    if filename not in _cache_locks:
        _cache_locks[filename] = asyncio.Lock()
    return _cache_locks[filename]

async def load_data(filename):
    return await asyncio.to_thread(_load_data_sync, filename)

async def save_data(filename, data):
    lock = get_cache_lock(filename)
    async with lock:
        await asyncio.to_thread(_save_data_sync, filename, data)

async def get_active_slot(user_id: str):
    slots = await load_data(SLOTS_FILE)
    return slots.get(str(user_id), "1")

async def set_active_slot(user_id: str, slot: str):
    slots = await load_data(SLOTS_FILE)
    slots[str(user_id)] = slot
    await save_data(SLOTS_FILE, slots)

async def get_uid(event):
    tg_id = str(event.from_user.id)
    slot = await get_active_slot(tg_id)
    return f"{tg_id}_{slot}"

_user_locks = {}
_table_lock = None

def get_user_lock(user_id: str) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]

def get_table_lock() -> asyncio.Lock:
    global _table_lock
    if _table_lock is None:
        _table_lock = asyncio.Lock()
    return _table_lock

async def check_sub(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=SPONSOR_CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False

def sub_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на Спонсора", url=SPONSOR_CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Я подписался (Проверить)", callback_data="check_sub_callback")]
    ])

def with_user_lock(func):
    @functools.wraps(func)
    async def wrapper(event, *args, **kwargs):
        user_id = await get_uid(event)
        lock = get_user_lock(user_id)
        async with lock:
            return await func(event, *args, **kwargs)
    return wrapper

def retired_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Начать новую карьеру", callback_data="start_new_career")]])

async def deny_if_retired_cb(callback: CallbackQuery, p) -> bool:
    if not p:
        await callback.message.answer("⚠️ Профиль не найден. Нажми /start, чтобы начать.", parse_mode="Markdown")
        return True
    if p.get("retired"):
        try:
            await callback.message.edit_text(
                "🏁 **Твоя карьера уже завершена!**\nЭта кнопка осталась от старого меню — нажми ниже, чтобы начать новую карьеру.",
                parse_mode="Markdown", reply_markup=retired_keyboard()
            )
        except:
            await callback.message.answer("🏁 **Твоя карьера уже завершена!**", reply_markup=retired_keyboard())
        return True
    return False

async def deny_if_retired_msg(message: Message, p) -> bool:
    if not p:
        await message.answer("⚠️ Профиль не найден. Нажми /start, чтобы начать.", parse_mode="Markdown")
        return True
    if p.get("retired"):
        await message.answer(
            "🏁 **Твоя карьера уже завершена!**\nНажми ниже, чтобы начать новую карьеру.",
            parse_mode="Markdown", reply_markup=retired_keyboard()
        )
        return True
    return False

class PlayerCreation(StatesGroup):
    waiting_for_name = State()
    waiting_for_nation = State()
    waiting_for_position = State()
    waiting_for_country_league = State()
    waiting_for_number = State()
    waiting_for_club = State()

class AdminPanel(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_money = State()
    waiting_for_rating = State()

class InterviewState(StatesGroup):
    waiting_for_answer = State()

class EuroMatch(StatesGroup):
    waiting_for_action = State()

# --- ДАННЫЕ И СПРАВОЧНИКИ ---
EURO_NATIONS = [
    "Россия", "Франция", "Италия", "Испания", "Германия", "Англия",
    "Португалия", "Нидерланды", "Бельгия", "Украина", "Хорватия",
    "Дания", "Швейцария", "Польша", "Швеция", "Норвегия", "Сербия", "Турция"
]

NATIONS = EURO_NATIONS

CLUBS = {
    "ФНЛ 2": ["Знамя Труда", "Сатурн Раменское", "Коломна", "Зенит-2", "Спартак-2", "Амкар Пермь", "Динамо Киров", "Рубин-2", "Торпедо Владимир", "Тверь", "Химик Дзержинск", "Иркутск"],
    "ФНЛ": ["Черноморец", "Шинник", "Урал", "Сочи", "Балтика", "Родина", "Торпедо М", "Арсенал Тула", "КАМАЗ", "Енисей", "Нефтехимик", "СКА-Хабаровск", "Уфа", "Тюмень", "Ротор", "Сокол", "Чайка", "Алания"],
    "РПЛ": ["Зенит", "Краснодар", "Динамо М", "Локомотив", "Спартак", "ЦСКА", "Ростов", "Рубин", "Крылья Советов", "Ахмат", "Факел", "Оренбург", "Пари НН", "Химки", "Акрон", "Динамо Мх"],
    "Насьональ": ["Ред Стар", "Ним", "Дижон", "Сошо", "Руан", "Ле Ман", "Версаль", "Нанси", "Шатору", "Кевийи", "Орлеан", "Булонь"],
    "Лига 2": ["Пари ФК", "Кан", "Генгам", "Амьен", "Бастия", "Бордо", "Труа", "Мец", "Аяччо", "Лорьян", "Клермон", "Анси", "Гренобль", "Дюнкерк", "По", "Родез", "Лаваль", "Ньор"],
    "Лига 1": ["ПСЖ", "Монако", "Брест", "Лилль", "Ницца", "Лион", "Ланс", "Марсель", "Ренн", "Реймс", "Тулуза", "Монпелье", "Страсбур", "Нант", "Гавр", "Осер", "Анже", "Сент-Этьен"],
    "Первая лига Англии": ["Рединг", "Уиган", "Болтон", "Чарльтон", "Барнсли", "Питерборо", "Блэкпул", "Портсмут", "Дерби Каунти", "Стивенедж", "Линкольн", "Шрусбери"],
    "Чемпионшип": ["Лестер", "Лидс", "Саутгемптон", "Ипсвич", "Вест Бромвич", "Норвич", "Халл Сити", "Ковентри", "Престон", "Мидлсбро", "Кардифф", "Бристоль Сити", "Сандерленд", "Суонси", "Уотфорд", "Миллуолл", "КПР", "Блэкберн"],
    "АПЛ": ["Манчестер Сити", "Арсенал", "Ливерпуль", "Астон Вилла", "Тоттенхэм", "Челси", "Ньюкасл", "Манчестер Юнайтед", "Вест Хэм", "Борнмут", "Кристал Пэлас", "Брайтон", "Фулхэм", "Вулверхэмптон", "Эвертон", "Брентфорд", "Ноттингем Форест", "Шеффилд Юнайтед"],
    "Сегунда": ["Эспаньол", "Сарагоса", "Леванте", "Эйбар", "Спортинг Хихон", "Вальядолид", "Тенерифе", "Овьедо", "Расинг", "Альбасете", "Картахена", "Бургос"],
    "Ла Лига": ["Реал Мадрид", "Барселона", "Атлетико", "Жирона", "Атлетик", "Реал Сосьедад", "Бетис", "Вильярреал", "Валенсия", "Алавес", "Осасуна", "Хетафе", "Сельта", "Севилья", "Мальорка", "Лас-Пальмас"],
    "Серия Б": ["Сампдория", "Парма", "Палермо", "Венеция", "Бари", "Кремонезе", "Комо", "Пиза", "Брешия", "Катандзаро", "Специя", "Тернана"],
    "Серия А": ["Интер", "Милан", "Ювентус", "Аталанта", "Болонья", "Рома", "Лацио", "Фиорентина", "Торино", "Наполи", "Дженоа", "Монца", "Лечче", "Удинезе", "Кальяри", "Эмполи"],
    "Вторая Бундеслига": ["Кёльн", "Дармштадт", "Гамбург", "Фортуна Д", "Ганновер", "Падерборн", "Герта", "Шальке", "Эльферсберг", "Нюрнберг", "Кайзерслаутерн", "Магдебург"],
    "Бундеслига": ["Бавария", "Боруссия Д", "Байер", "РБ Лейпциг", "Штутгарт", "Айнтрахт Ф", "Хоффенхайм", "Фрайбург", "Вердер", "Аугсбург", "Вольфсбург", "Боруссия М", "Унион Берлин", "Майнц", "Хайденхайм", "Санкт-Паули"],
    "Сегунда лига": ["Тондела", "Визела", "Академика", "Лейшойнш", "Оливейренсе", "Фейренсе", "Варзин", "Ковильян", "Трофенсе", "Амадора", "Мануэл да Круш", "Насьонал"],
    "Примейра": ["Порту", "Бенфика", "Спортинг", "Брага", "Витория", "Фамаликан", "Риу Аве", "Арока", "Жил Висенте", "Эшторил", "Боавишта", "Пасуш де Феррейра", "Санта-Клара", "Портимоненсе", "Морейренсе", "Насьонал"],
    "Бразильская Серия А": ["Фламенго", "Палмейрас", "Сантос", "Коринтианс", "Сан-Паулу", "Интернасьонал", "Гремио", "Атлетико Минейро", "Крузейро", "Ботафого", "Васко да Гама", "Флуминенсе", "Баия", "Форталеза", "Куяба", "Атлетико Паранаэнсе", "Гояс", "Спорт Ресифи", "Сеара", "Америка Минейро"],
    "Эрстедивизи": ["Йонг Аякс", "Йонг ПСВ", "Йонг Утрехт", "Ден Босх", "Камбюр", "Де Графсхап", "Дордрехт", "Эйндховен", "Эммен", "Гронинген", "Хелмонд Спорт", "Хераклес", "Маастрихт", "Осс", "Рода", "Телстар", "Венло", "Виллем II", "Зволле", "Алмере Сити"],
    "Эредивизи": ["Аякс", "ПСВ", "Фейеноорд", "АЗ Алкмаар", "Твенте", "Утрехт", "Витесс", "Спарта Роттердам", "Херенвен", "Фортуна Ситтард", "НЕК", "Гоу Эхед Иглз", "Валвейк", "Эксельсиор", "Волендам", "Эммен", "Камбюр", "Гронинген"],
    "Jupiler Pro League": ["Андерлехт", "Брюгге", "Генк", "Гент", "Стандард Льеж", "Шарлеруа", "Мехелен", "Антверпен", "Серкль Брюгге", "Зюлте-Варегем", "Остенде", "Кортрейк", "Эйпен", "Лёвен", "Вестерло", "Беерсхот"],
    "Беларусь Первая лига": ["Локомотив Гомель", "Барановичи", "Лида", "Молодечно", "Орша", "Осиповичи", "Волна Пинск", "Жодино-Южное", "Слоним-2017", "Гомель-2", "Минск-2", "Динамо-Минск-2"],
    "Беларусь Высшая лига": ["Динамо Минск", "БАТЭ", "Шахтер Солигорск", "Торпедо-БелАЗ", "Неман Гродно", "Славия Мозырь", "Ислочь", "Минск", "Гомель", "Сморгонь", "Нафтан Новополоцк", "Слуцк", "Витебск", "Днепр-Могилев", "Арсенал Дзержинск", "Брест"],
    "Турция Первая лига": ["Гёзтепе", "Алтай", "Аданаспор", "Бурсаспор", "Денизлиспор", "Эскишехирспор", "Гиресунспор", "Истанбулспор", "Коджаэлиспор", "Манисаспор", "Менеменспор", "Самсунспор", "Тузласпор", "Умраниеспор", "Бандырмаспор", "ББ Эрзурумспор", "Сакарьяспор", "Кечиоренгюджю"],
    "Турция Суперлига": ["Галатасарай", "Фенербахче", "Бешикташ", "Трабзонспор", "Истанбул Башакшехир", "Адана Демирспор", "Аланьяспор", "Антальяспор", "Газиантеп", "Ризеспор", "Сивасспор", "Кайсериспор", "Коньяспор", "Самсунспор", "Касымпаша", "Хатайспор", "Анкарагюджю", "Пендикспор", "Эюпспор", "Бодрумспор"],
    "Казахстан Премьер-лига": ["Актобе", "Астана", "Кайрат", "Тобол", "Ордабасы", "Кызыл-Жар", "Тараз", "Шахтер-Караганда", "Жетысу", "Елимай", "Кайсар", "Туран", "Атырау", "Женис", "Улытау", "Каспий"]
}

CLUB_RATINGS = {
    "Знамя Труда": 40, "Сатурн Раменское": 45, "Коломна": 38, "Зенит-2": 52, "Спартак-2": 50, "Амкар Пермь": 48, "Динамо Киров": 42, "Рубин-2": 44, "Торпедо Владимир": 41, "Тверь": 39, "Химик Дзержинск": 43, "Иркутск": 40,
    "Черноморец": 60, "Шинник": 62, "Урал": 68, "Сочи": 69, "Балтика": 67, "Родина": 65, "Торпедо М": 66, "Арсенал Тула": 64, "КАМАЗ": 58, "Енисей": 63, "Нефтехимик": 61, "СКА-Хабаровск": 60, "Уфа": 59, "Тюмень": 57, "Ротор": 62, "Сокол": 56, "Чайка": 55, "Алания": 64,
    "Зенит": 85, "Краснодар": 83, "Динамо М": 81, "Локомотив": 80, "Спартак": 82, "ЦСКА": 81, "Ростов": 77, "Рубин": 75, "Крылья Советов": 76, "Ахмат": 74, "Факел": 72, "Оренбург": 73, "Пари НН": 71, "Химки": 70, "Акрон": 69, "Динамо Мх": 68,
    "Ред Стар": 45, "Ним": 44, "Дижон": 46, "Сошо": 47, "Руан": 42, "Ле Ман": 43, "Версаль": 41, "Нанси": 48, "Шатору": 40, "Кевийи": 45, "Орлеан": 42, "Булонь": 39,
    "Пари ФК": 65, "Кан": 64, "Генгам": 62, "Амьен": 61, "Бастия": 60, "Бордо": 66, "Труа": 63, "Мец": 68, "Аяччо": 59, "Лорьян": 67, "Клермон": 65, "Анси": 58, "Гренобль": 62, "Дюнкерк": 57, "По": 56, "Родез": 61, "Лаваль": 60, "Ньор": 55,
    "ПСЖ": 90, "Монако": 83, "Брест": 79, "Лилль": 82, "Ницца": 80, "Лион": 83, "Ланс": 81, "Марсель": 82, "Ренн": 80, "Реймс": 77, "Тулуза": 76, "Монпелье": 75, "Страсбур": 76, "Нант": 75, "Гавр": 73, "Осер": 72, "Анже": 71, "Сент-Этьен": 74,
    "Рединг": 50, "Уиган": 52, "Болтон": 51, "Чарльтон": 49, "Барнсли": 53, "Питерборо": 50, "Блэкпул": 48, "Портсмут": 54, "Дерби Каунти": 55, "Стивенедж": 46, "Линкольн": 47, "Шрусбери": 45,
    "Лестер": 75, "Лидс": 74, "Саутгемптон": 73, "Ипсвич": 70, "Вест Бромвич": 69, "Норвич": 68, "Халл Сити": 67, "Ковентри": 68, "Престон": 66, "Мидлсбро": 69, "Кардифф": 65, "Бристоль Сити": 64, "Сандерленд": 68, "Суонси": 66, "Уотфорд": 70, "Миллуолл": 65, "КПР": 64, "Блэкберн": 66,
    "Манчестер Сити": 92, "Арсенал": 89, "Ливерпуль": 89, "Астон Вилла": 84, "Тоттенхэм": 85, "Челси": 84, "Ньюкасл": 83, "Манчестер Юнайтед": 84, "Вест Хэм": 81, "Борнмут": 78, "Кристал Пэлас": 78, "Брайтон": 80, "Фулхэм": 79, "Вулверхэмптон": 78, "Эвертон": 77, "Брентфорд": 78, "Ноттингем Форест": 76, "Шеффилд Юнайтед": 75,
    "Эспаньол": 72, "Сарагоса": 70, "Леванте": 71, "Эйбар": 71, "Спортинг Хихон": 69, "Вальядолид": 72, "Тенерифе": 68, "Овьедо": 68, "Расинг": 67, "Альбасете": 66, "Картахена": 65, "Бургос": 64,
    "Реал Мадрид": 93, "Барселона": 90, "Атлетико": 87, "Жирона": 83, "Атлетик": 82, "Реал Сосьедад": 82, "Бетис": 81, "Вильярреал": 80, "Валенсия": 79, "Алавес": 77, "Осасуна": 78, "Хетафе": 77, "Сельта": 78, "Севилья": 80, "Мальорка": 76, "Лас-Пальмас": 75,
    "Сампдория": 70, "Парма": 72, "Палермо": 71, "Венеция": 71, "Бари": 69, "Кремонезе": 72, "Комо": 70, "Пиза": 68, "Брешия": 67, "Катандзаро": 66, "Специя": 69, "Тернана": 65,
    "Интер": 90, "Милан": 86, "Ювентус": 86, "Аталанта": 84, "Болонья": 82, "Рома": 83, "Лацио": 82, "Фиорентина": 81, "Торино": 79, "Наполи": 84, "Дженоа": 77, "Монца": 76, "Лечче": 75, "Удинезе": 76, "Кальяри": 75, "Эмполи": 74,
    "Кёльн": 72, "Дармштадт": 69, "Гамбург": 72, "Фортуна Д": 71, "Ганновер": 70, "Падерборн": 68, "Герта": 71, "Шальке": 70, "Эльферсберг": 66, "Нюрнберг": 67, "Кайзерслаутерн": 68, "Магдебург": 66,
    "Бавария": 91, "Боруссия Д": 86, "Байер": 88, "РБ Лейпциг": 86, "Штутгарт": 82, "Айнтрахт Ф": 81, "Хоффенхайм": 78, "Фрайбург": 79, "Вердер": 77, "Аугсбург": 76, "Вольфсбург": 78, "Боруссия М": 77, "Унион Берлин": 76, "Майнц": 75, "Хайденхайм": 76, "Санкт-Паули": 74,
    "Тондела": 62, "Визела": 63, "Академика": 60, "Лейшойнш": 59, "Оливейренсе": 58, "Фейренсе": 61, "Варзин": 57, "Ковильян": 56, "Трофенсе": 55, "Амадора": 64, "Мануэл да Круш": 54, "Насьонал": 68,
    "Порту": 88, "Бенфика": 86, "Спортинг": 87, "Брага": 80, "Витория": 76, "Фамаликан": 74, "Риу Аве": 72, "Арока": 70, "Жил Висенте": 71, "Эшторил": 69, "Боавишта": 73, "Пасуш де Феррейра": 68, "Санта-Клара": 67, "Портимоненсе": 70, "Морейренсе": 72, "Насьонал": 68,
    "Фламенго": 85, "Палмейрас": 84, "Сантос": 80, "Коринтианс": 79, "Сан-Паулу": 78,
    "Интернасьонал": 77, "Гремио": 76, "Атлетико Минейро": 75, "Крузейро": 74, "Ботафого": 73,
    "Васко да Гама": 72, "Флуминенсе": 72, "Баия": 71, "Форталеза": 70, "Куяба": 69,
    "Атлетико Паранаэнсе": 70, "Гояс": 68, "Спорт Ресифи": 69, "Сеара": 68, "Америка Минейро": 67,
    "Йонг Аякс": 58, "Йонг ПСВ": 56, "Йонг Утрехт": 52, "Ден Босх": 55, "Камбюр": 62, "Де Графсхап": 60,
    "Дордрехт": 54, "Эйндховен": 57, "Эммен": 63, "Гронинген": 66, "Хелмонд Спорт": 53, "Хераклес": 65,
    "Маастрихт": 56, "Осс": 51, "Рода": 59, "Телстар": 52, "Венло": 58, "Виллем II": 64, "Зволле": 63, "Алмере Сити": 55,
    "Аякс": 89, "ПСВ": 88, "Фейеноорд": 86, "АЗ Алкмаар": 82, "Твенте": 79, "Утрехт": 77, "Витесс": 76,
    "Спарта Роттердам": 74, "Херенвен": 73, "Фортуна Ситтард": 72, "НЕК": 72, "Гоу Эхед Иглз": 70,
    "Валвейк": 69, "Эксельсиор": 68, "Волендам": 67, "Камбюр": 62, "Гронинген": 66,
    "Андерлехт": 82, "Брюгге": 84, "Генк": 80, "Гент": 78, "Стандард Льеж": 76, "Шарлеруа": 74,
    "Мехелен": 73, "Антверпен": 75, "Серкль Брюгге": 72, "Зюлте-Варегем": 70, "Остенде": 71,
    "Кортрейк": 69, "Эйпен": 68, "Лёвен": 67, "Вестерло": 69, "Беерсхот": 66,
    "Локомотив Гомель": 45, "Барановичи": 43, "Лида": 42, "Молодечно": 41, "Орша": 40, "Осиповичи": 39,
    "Волна Пинск": 38, "Жодино-Южное": 37, "Слоним-2017": 36, "Гомель-2": 35, "Минск-2": 34, "Динамо-Минск-2": 33,
    "Динамо Минск": 72, "БАТЭ": 70, "Шахтер Солигорск": 68, "Торпедо-БелАЗ": 66, "Неман Гродно": 65, "Славия Мозырь": 63,
    "Ислочь": 62, "Минск": 61, "Гомель": 60, "Сморгонь": 58, "Нафтан Новополоцк": 57, "Слуцк": 56, "Витебск": 55,
    "Днепр-Могилев": 54, "Арсенал Дзержинск": 53, "Брест": 52,
    "Гёзтепе": 52, "Алтай": 51, "Аданаспор": 50, "Бурсаспор": 49, "Денизлиспор": 48, "Эскишехирспор": 47,
    "Гиресунспор": 46, "Истанбулспор": 45, "Коджаэлиспор": 44, "Манисаспор": 43, "Менеменспор": 42, "Самсунспор": 41,
    "Тузласпор": 40, "Умраниеспор": 39, "Бандырмаспор": 38, "ББ Эрзурумспор": 37, "Сакарьяспор": 36, "Кечиоренгюджю": 35,
    "Галатасарай": 82, "Фенербахче": 81, "Бешикташ": 80, "Трабзонспор": 78, "Истанбул Башакшехир": 76,
    "Адана Демирспор": 74, "Аланьяспор": 73, "Антальяспор": 72, "Газиантеп": 71, "Ризеспор": 70, "Сивасспор": 69,
    "Кайсериспор": 68, "Коньяспор": 67, "Самсунспор": 66, "Касымпаша": 65, "Хатайспор": 64, "Анкарагюджю": 63,
    "Пендикспор": 62, "Эюпспор": 61, "Бодрумспор": 60,
    "Актобе": 68, "Астана": 70, "Кайрат": 69, "Тобол": 67, "Ордабасы": 66, "Кызыл-Жар": 65, "Тараз": 63, "Шахтер-Караганда": 64,
    "Жетысу": 62, "Елимай": 61, "Кайсар": 60, "Туран": 59, "Атырау": 58, "Женис": 57, "Улытау": 56, "Каспий": 55
}

CUP_STAGES = ["1/16", "1/8", "1/4", "Полуфинал", "Финал"]

# --- ДАННЫЕ СПОНСОРОВ ---
SPONSORS_DATA = {
    "Литвин":   {"emoji": "🥤", "min_rating": 40, "income_per_match": 500,   "sign_bonus": 2_000},
    "Самосвет": {"emoji": "💎", "min_rating": 50, "income_per_match": 800,   "sign_bonus": 3_000},
    "Жигули":   {"emoji": "🍺", "min_rating": 55, "income_per_match": 1_000, "sign_bonus": 4_000},
    "Найк":     {"emoji": "👟", "min_rating": 67, "income_per_match": 3_000, "sign_bonus": 15_000},
    "Пума":     {"emoji": "🐆", "min_rating": 67, "income_per_match": 2_500, "sign_bonus": 12_000},
    "Рибок":    {"emoji": "🏅", "min_rating": 67, "income_per_match": 2_200, "sign_bonus": 10_000},
    "ПСБ банк": {"emoji": "🏦", "min_rating": 67, "income_per_match": 2_800, "sign_bonus": 13_000},
}

POSITIONS = {
    "⚽ Нападающий": "ST", 
    "🪄 Полузащитник": "CM", 
    "🛡️ Защитник": "CB",
    "🧤 Вратарь": "GK"
}

# --- КВЕСТЫ ---
QUESTS_DATA = {
    "q1": {"name": "Первая кровь", "desc": "Забить 1 гол", "reward": 0.05, "type": "goals", "target": 1},
    "q2": {"name": "Бомбардир", "desc": "Забить 10 голов", "reward": 0.08, "type": "goals", "target": 10},
    "q3": {"name": "Снайпер", "desc": "Забить 50 голов", "reward": 0.15, "type": "goals", "target": 50},
    "q4": {"name": "Легендарный голеадор", "desc": "Забить 100 голов", "reward": 0.3, "type": "goals", "target": 100},
    "q5": {"name": "Первый ассист", "desc": "Отдать 1 голевой пас", "reward": 0.05, "type": "assists", "target": 1},
    "q6": {"name": "Командный игрок", "desc": "Отдать 20 ассистов", "reward": 0.08, "type": "assists", "target": 20},
    "q7": {"name": "Маэстро паса", "desc": "Отдать 50 ассистов", "reward": 0.15, "type": "assists", "target": 50},
    "q8": {"name": "Надежный щит", "desc": "10 отборов/сейвов", "reward": 0.05, "type": "def", "target": 10},
    "q9": {"name": "Министр обороны", "desc": "50 отборов/сейвов", "reward": 0.15, "type": "def", "target": 50},
    "q10": {"name": "Стена", "desc": "150 отборов/сейвов", "reward": 0.3, "type": "def", "target": 150},
    "q11": {"name": "Вкус победы", "desc": "Выиграть 1 трофей", "reward": 0.1, "type": "trophies", "target": 1},
    "q12": {"name": "Коллекционер", "desc": "Выиграть 3 трофея", "reward": 0.25, "type": "trophies", "target": 3},
    "q13": {"name": "Опытный", "desc": "Сыграть 50 матчей", "reward": 0.1, "type": "games", "target": 50},
    "q14": {"name": "Ветеран", "desc": "Сыграть 150 матчей", "reward": 0.25, "type": "games", "target": 150},
    "q15": {"name": "Миллионер", "desc": "Накопить 1,000,000$", "reward": 0.3, "type": "money", "target": 1000000}
}

def get_quest_progress(p, q_type):
    st = p.get("stats_total", {})
    if q_type == "goals": return st.get("goals", 0)
    elif q_type == "assists": return st.get("assists", 0)
    elif q_type == "def": return st.get("tackles", 0) + st.get("saves", 0)
    elif q_type == "trophies": return len(p.get("trophies", []))
    elif q_type == "money": return p.get("money", 0)
    elif q_type == "games": return st.get("games", 0)
    return 0

def get_division(club_name):
    for div, clubs in CLUBS.items():
        if club_name in clubs:
            return div
    return "ФНЛ 2"

# --- ЛЕСТНИЦЫ ДИВИЗИОНОВ ---
DIVISION_LADDERS = [
    ["ФНЛ 2", "ФНЛ", "РПЛ"],
    ["Насьональ", "Лига 2", "Лига 1"],
    ["Первая лига Англии", "Чемпионшип", "АПЛ"],
    ["Сегунда", "Ла Лига"],
    ["Серия Б", "Серия А"],
    ["Вторая Бундеслига", "Бундеслига"],
    ["Сегунда лига", "Примейра"],
    ["Бразильская Серия А"],
    ["Эрстедивизи", "Эредивизи"],
    ["Jupiler Pro League"],
    ["Беларусь Первая лига", "Беларусь Высшая лига"],
    ["Турция Первая лига", "Турция Суперлига"],
    ["Казахстан Премьер-лига"]
]

def get_ladder(division):
    for ladder in DIVISION_LADDERS:
        if division in ladder:
            return ladder
    return [division]

def get_status_by_trust(trust):
    if 0 <= trust <= 20:
        return "Глубокий резерв ❌"
    elif 21 <= trust <= 50:
        return "Скамейка запасных 🪑"
    elif 51 <= trust <= 75:
        return "Джокер ⏱️"
    else:
        return "Игрок старта 🔥"

def calculate_player_value(rating, division):
    mult = {
        "ФНЛ 2": 12500, "Насьональ": 12500, "Первая лига Англии": 15000,
        "Сегунда": 35000, "Серия Б": 35000, "Вторая Бундеслига": 40000,
        "ФНЛ": 45000, "Лига 2": 45000, "Чемпионшип": 55000,
        "РПЛ": 250000, "Лига 1": 250000, "АПЛ": 350000, "Ла Лига": 350000, "Серия А": 300000, "Бундеслига": 320000,
        "Примейра": 280000, "Сегунда лига": 40000,
        "Бразильская Серия А": 250000,
        "Эрстедивизи": 35000, "Эредивизи": 280000,
        "Jupiler Pro League": 280000,
        "Беларусь Первая лига": 15000,
        "Беларусь Высшая лига": 40000,
        "Турция Первая лига": 20000,
        "Турция Суперлига": 200000,
        "Казахстан Премьер-лига": 40000
    }
    base = mult.get(division, 15000)
    return int(rating * base * (1 + (rating - 40) / 30))

async def add_to_retired_leaderboard(name, rating, trophies_count):
    leaderboard = await load_data(LEADERBOARD_FILE)
    if "top_careers" not in leaderboard:
        leaderboard["top_careers"] = []
    
    leaderboard["top_careers"].append({
        "name": name,
        "rating": rating,
        "trophies": trophies_count
    })
    
    leaderboard["top_careers"] = sorted(leaderboard["top_careers"], key=lambda x: (x["rating"], x["trophies"]), reverse=True)[:10]
    await save_data(LEADERBOARD_FILE, leaderboard)

async def track_activity(user_id: str):
    players = await load_data(PLAYERS_FILE)
    if user_id in players:
        p = players[user_id]
        current_week = datetime.now().isocalendar()[1]
        
        if p.get("activity_week", current_week) != current_week:
            p["activity_minutes"] = 0
            p["activity_week"] = current_week
            
        p["activity_minutes"] = p.get("activity_minutes", 0) + random.randint(1, 5)
        players[user_id] = p
        await save_data(PLAYERS_FILE, players)

def _init_tables_internal(tables, user_id, division, player_club=None):
    clubs_list = CLUBS[division].copy()
    if player_club and player_club not in clubs_list:
        clubs_list[-1] = player_club
        
    division_table = [{"club": club, "points": 0, "wins": 0, "draws": 0, "losses": 0} for club in clubs_list]
    if user_id not in tables:
        tables[user_id] = {}
    tables[user_id][division] = division_table

async def init_tables_for_user(user_id, division, player_club=None):
    async with get_table_lock():
        tables = await load_data(TABLES_FILE)
        _init_tables_internal(tables, user_id, division, player_club)
        await save_data(TABLES_FILE, tables)

async def simulate_table_tour(user_id, division, player_club, player_match_rival, player_match_outcome):
    async with get_table_lock():
        tables = await load_data(TABLES_FILE)
        if user_id not in tables or division not in tables[user_id]:
            _init_tables_internal(tables, user_id, division, player_club)
            
        table = tables[user_id][division]
        
        for row in table:
            if row["club"] == player_club:
                if player_match_outcome == "win": row["points"] += 3; row["wins"] += 1
                elif player_match_outcome == "draw": row["points"] += 1; row["draws"] += 1
                else: row["losses"] += 1
            elif row["club"] == player_match_rival:
                if player_match_outcome == "win": row["losses"] += 1
                elif player_match_outcome == "draw": row["points"] += 1; row["draws"] += 1
                else: row["points"] += 3; row["wins"] += 1
     
        other_clubs = [row for row in table if row["club"] not in (player_club, player_match_rival)]
        random.shuffle(other_clubs)
        
        while len(other_clubs) >= 2:
            c1 = other_clubs.pop()
            c2 = other_clubs.pop()
            r1, r2 = CLUB_RATINGS.get(c1["club"], 50), CLUB_RATINGS.get(c2["club"], 50)
            chance_w1 = 0.35 + ((r1 - r2) * 0.01)
            chance_w2 = 0.35 + ((r2 - r1) * 0.01)
            rand = random.random()
            
            if rand < chance_w1: c1["points"] += 3; c1["wins"] += 1; c2["losses"] += 1
            elif rand < chance_w1 + chance_w2: c2["points"] += 3; c2["wins"] += 1; c1["losses"] += 1
            else: c1["points"] += 1; c1["draws"] += 1; c2["points"] += 1; c2["draws"] += 1
     
        if other_clubs:
            c = other_clubs.pop()
            res = random.choice(["win", "draw", "loss"])
            if res == "win": c["points"] += 3; c["wins"] += 1
            elif res == "draw": c["points"] += 1; c["draws"] += 1
            else: c["losses"] += 1
     
        tables[user_id][division] = sorted(table, key=lambda x: x["points"], reverse=True)
        await save_data(TABLES_FILE, tables)

async def simulate_background_division(user_id, division):
    async with get_table_lock():
        tables = await load_data(TABLES_FILE)
        if user_id not in tables or division not in tables[user_id]:
            _init_tables_internal(tables, user_id, division)
        table = tables[user_id][division]
        
        clubs = table.copy()
        random.shuffle(clubs)
        while len(clubs) >= 2:
            c1 = clubs.pop()
            c2 = clubs.pop()
            r1, r2 = CLUB_RATINGS.get(c1["club"], 50), CLUB_RATINGS.get(c2["club"], 50)
            chance_w1 = 0.35 + ((r1 - r2) * 0.01)
            chance_w2 = 0.35 + ((r2 - r1) * 0.01)
            rand = random.random()
            if rand < chance_w1: c1["points"] += 3; c1["wins"] += 1; c2["losses"] += 1
            elif rand < chance_w1 + chance_w2: c2["points"] += 3; c2["wins"] += 1; c1["losses"] += 1
            else: c1["points"] += 1; c1["draws"] += 1; c2["points"] += 1; c2["draws"] += 1
 
        if clubs:
            c = clubs.pop()
            res = random.choice(["win", "draw", "loss"])
            if res == "win": c["points"] += 3; c["wins"] += 1
            elif res == "draw": c["points"] += 1; c["draws"] += 1
            else: c["losses"] += 1
 
        tables[user_id][division] = sorted(table, key=lambda x: x["points"], reverse=True)
        await save_data(TABLES_FILE, tables)

# ========== ТРЕНИРОВКИ ==========
TRAINING_CONFIG = {
    "ST": {
        "tech": {"name": "Дриблинг", "base_gain": 0.05, "fatigue": 15},
        "phys": {"name": "Скорость", "base_gain": 0.05, "fatigue": 15},
        "special": {"name": "Завершение", "base_gain": 0.08, "fatigue": 18}
    },
    "CM": {
        "tech": {"name": "Пас", "base_gain": 0.05, "fatigue": 15},
        "phys": {"name": "Выносливость", "base_gain": 0.05, "fatigue": 15},
        "special": {"name": "Видение поля", "base_gain": 0.08, "fatigue": 18}
    },
    "CB": {
        "tech": {"name": "Отбор", "base_gain": 0.05, "fatigue": 15},
        "phys": {"name": "Сила", "base_gain": 0.05, "fatigue": 15},
        "special": {"name": "Позиция", "base_gain": 0.08, "fatigue": 18}
    },
    "GK": {
        "tech": {"name": "Реакция", "base_gain": 0.05, "fatigue": 15},
        "phys": {"name": "Прыжок", "base_gain": 0.05, "fatigue": 15},
        "special": {"name": "Игра ногами", "base_gain": 0.08, "fatigue": 18}
    }
}

STREAK_BONUSES = {
    5: 0.1,
    10: 0.2,
    15: 0.3,
    20: 0.5
}

TRAIN_ACHIEVEMENTS = {
    "train_25": {"name": "🏅 Трудяга", "desc": "25 тренировок", "reward": 0.1},
    "train_50": {"name": "🏅 Профи", "desc": "50 тренировок", "reward": 0.2},
    "train_100": {"name": "🏅 Легенда тренировок", "desc": "100 тренировок", "reward": 0.3},
    "streak_5": {"name": "🔥 Дисциплина", "desc": "5 тренировок подряд", "reward": 0.1},
    "streak_10": {"name": "🔥 Железная воля", "desc": "10 тренировок подряд", "reward": 0.2},
    "streak_20": {"name": "🔥 Монах", "desc": "20 тренировок подряд", "reward": 0.3},
}

def get_train_cost(rating: float) -> int:
    return int(200 + (rating * 5))

def get_streak_bonus(streak: int) -> float:
    bonus = 0.0
    for s, b in sorted(STREAK_BONUSES.items()):
        if streak >= s:
            bonus = b
    return bonus

def check_train_achievements(p: dict, train_count: int, streak: int) -> tuple:
    unlocked = []
    total_reward = 0.0
    
    train_achievements = p.get("train_achievements", [])
    
    for key, ach in TRAIN_ACHIEVEMENTS.items():
        if key in train_achievements:
            continue
            
        if key == "train_25" and train_count >= 25:
            unlocked.append(ach)
            total_reward += ach["reward"]
        elif key == "train_50" and train_count >= 50:
            unlocked.append(ach)
            total_reward += ach["reward"]
        elif key == "train_100" and train_count >= 100:
            unlocked.append(ach)
            total_reward += ach["reward"]
        elif key == "streak_5" and streak >= 5:
            unlocked.append(ach)
            total_reward += ach["reward"]
        elif key == "streak_10" and streak >= 10:
            unlocked.append(ach)
            total_reward += ach["reward"]
        elif key == "streak_20" and streak >= 20:
            unlocked.append(ach)
            total_reward += ach["reward"]
    
    return unlocked, total_reward

# ========== ФУНКЦИЯ ЛЕЧЕНИЯ ТРАВМ ==========
async def heal_injury_if_needed(user_id: str):
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if not p:
        return
    
    if p.get("injury_tours", 0) > 0:
        p["injury_tours"] -= 1
        if p["injury_tours"] <= 0:
            p["is_injured"] = False
            p["injury_tours"] = 0
        players[user_id] = p
        await save_data(PLAYERS_FILE, players)

# ========== ЕВРОКУБКИ - ФУНКЦИИ ==========

EURO_TOURNAMENTS = {
    "champions_league": {
        "name": "🏆 Лига Чемпионов",
        "short_name": "Лига Чемпионов",
        "emoji": "🏆",
        "prize_win": 150000,
        "prize_draw": 50000,
        "prize_top8": 500000,
        "prize_winner": 5000000,
        "rating_bonus_winner": 2.0
    },
    "europa_league": {
        "name": "🥈 Лига Европы",
        "short_name": "Лига Европы",
        "emoji": "🥈",
        "prize_win": 100000,
        "prize_draw": 30000,
        "prize_top8": 300000,
        "prize_winner": 2500000,
        "rating_bonus_winner": 1.0
    },
    "conference_league": {
        "name": "🥉 Лига Конференций",
        "short_name": "Лига Конференций",
        "emoji": "🥉",
        "prize_win": 50000,
        "prize_draw": 15000,
        "prize_top8": 150000,
        "prize_winner": 1000000,
        "rating_bonus_winner": 0.5
    }
}

EURO_KEYS = ["champions_league", "europa_league", "conference_league"]
EURO_TABLE_PAGE_SIZE = 9


def get_club_country(club):
    for div, clubs in CLUBS.items():
        if club in clubs:
            if div in ["ФНЛ 2", "ФНЛ", "РПЛ"]:
                return "Россия"
            elif div in ["Насьональ", "Лига 2", "Лига 1"]:
                return "Франция"
            elif div in ["Первая лига Англии", "Чемпионшип", "АПЛ"]:
                return "Англия"
            elif div in ["Сегунда", "Ла Лига"]:
                return "Испания"
            elif div in ["Серия Б", "Серия А"]:
                return "Италия"
            elif div in ["Вторая Бундеслига", "Бундеслига"]:
                return "Германия"
            elif div in ["Сегунда лига", "Примейра"]:
                return "Португалия"
            elif div in ["Эрстедивизи", "Эредивизи"]:
                return "Нидерланды"
            elif div == "Jupiler Pro League":
                return "Бельгия"
            elif div in ["Беларусь Первая лига", "Беларусь Высшая лига"]:
                return "Беларусь"
            elif div in ["Турция Первая лига", "Турция Суперлига"]:
                return "Турция"
            elif div == "Казахстан Премьер-лига":
                return "Казахстан"
            elif div == "Бразильская Серия А":
                return "Бразилия"
    return "Неизвестно"


def get_euro_tournament_by_position(division, position):
    top_leagues = ["РПЛ", "АПЛ", "Ла Лига", "Серия А", "Бундеслига", "Лига 1", "Примейра", "Эредивизи"]
    mid_leagues = [
        "ФНЛ", "Лига 2", "Чемпионшип", "Сегунда", "Серия Б", "Вторая Бундеслига",
        "Сегунда лига", "Эрстедивизи", "Jupiler Pro League", "Беларусь Высшая лига",
        "Турция Суперлига", "Казахстан Премьер-лига", "Бразильская Серия А"
    ]

    if division in top_leagues:
        if position <= 3:
            return "champions_league"
        elif position <= 5:
            return "europa_league"
        elif position <= 7:
            return "conference_league"
    elif division in mid_leagues:
        if position == 1:
            return "europa_league"
        elif position <= 3:
            return "conference_league"
    return None


def _all_known_clubs():
    result = []
    seen = set()
    for clubs in CLUBS.values():
        for club in clubs:
            if club not in seen:
                seen.add(club)
                result.append(club)
    return result


def _new_euro_table_row():
    return {
        "points": 0,
        "goals_for": 0,
        "goals_against": 0,
        "played": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0
    }


def _make_euro_tournament_data(clubs):
    clubs = list(dict.fromkeys(clubs))[:36]
    table = {club: _new_euro_table_row() for club in clubs}
    return {
        "clubs": clubs,
        "table": table,
        "fixtures": {},
        "played": 0,
        "status": "group",
        "qualified": [],
        "eliminated": []
    }


def _normalise_euro_clubs(existing_clubs, used_clubs=None):
    used_clubs = used_clubs or set()
    result = []
    seen = set()

    for club in existing_clubs or []:
        if club in CLUB_RATINGS and club not in seen:
            result.append(club)
            seen.add(club)

    available = [c for c in _all_known_clubs() if c not in seen and c not in used_clubs]
    random.shuffle(available)
    result.extend(available[:max(0, 36 - len(result))])

    if len(result) < 36:
        fallback = [c for c in _all_known_clubs() if c not in seen]
        for club in fallback:
            if club not in result:
                result.append(club)
            if len(result) >= 36:
                break

    return result[:36]


def generate_swiss_fixtures(clubs):
    """Создает ровно 8 уникальных матчей для каждого клуба.
    Формат специально хранится отдельно для каждого клуба, поэтому игрок
    всегда может получить свой календарь даже если остальные матчи еще не сыграны.
    """
    clubs = list(dict.fromkeys(clubs))[:36]
    if len(clubs) < 2:
        return {club: [] for club in clubs}

    ratings = {club: CLUB_RATINGS.get(club, 50) for club in clubs}
    sorted_clubs = sorted(clubs, key=lambda c: ratings[c], reverse=True)
    pots = {
        1: sorted_clubs[0:9],
        2: sorted_clubs[9:18],
        3: sorted_clubs[18:27],
        4: sorted_clubs[27:36]
    }

    fixtures = {club: [] for club in clubs}

    for club in clubs:
        opponents = []
        country = get_club_country(club)

        # По два соперника из каждой корзины.
        for pot_num in [1, 2, 3, 4]:
            same_pot = [
                c for c in pots[pot_num]
                if c != club and c not in opponents and get_club_country(c) != country
            ]
            if len(same_pot) < 2:
                same_pot = [c for c in pots[pot_num] if c != club and c not in opponents]
            random.shuffle(same_pot)
            opponents.extend(same_pot[:2])

        # Если из-за ограничений стран не набралось 8, добираем из всех клубов.
        if len(opponents) < 8:
            remaining = [c for c in clubs if c != club and c not in opponents]
            random.shuffle(remaining)
            opponents.extend(remaining[:8 - len(opponents)])

        opponents = opponents[:8]
        home_flags = [True] * 4 + [False] * 4
        random.shuffle(home_flags)

        for tour, opponent in enumerate(opponents, 1):
            fixtures[club].append({
                "opponent": opponent,
                "home": home_flags[tour - 1],
                "tour": tour,
                "played": False,
                "goals_for": 0,
                "goals_against": 0,
                "result": None
            })

    return fixtures


async def determine_euro_participants(season):
    tables = await load_data(TABLES_FILE)
    players = await load_data(PLAYERS_FILE)
    club_positions = {}

    # Берем реальные позиции клубов из таблиц игроков.
    for user_id, p in players.items():
        if p.get("retired"):
            continue
        club = p.get("club")
        division = p.get("division")
        if not club or not division:
            continue
        if user_id in tables and division in tables[user_id]:
            table = tables[user_id][division]
            position = next((i + 1 for i, row in enumerate(table) if row.get("club") == club), None)
            if position:
                club_positions[club] = {"division": division, "position": position}

    champions = []
    europa = []
    conference = []

    for club, info in club_positions.items():
        tournament = get_euro_tournament_by_position(info["division"], info["position"])
        if tournament == "champions_league":
            champions.append(club)
        elif tournament == "europa_league":
            europa.append(club)
        elif tournament == "conference_league":
            conference.append(club)

    # Не допускаем один клуб сразу в нескольких турнирах.
    champions = list(dict.fromkeys(champions))
    europa = [c for c in dict.fromkeys(europa) if c not in champions]
    conference = [c for c in dict.fromkeys(conference) if c not in champions and c not in europa]

    used = set(champions + europa + conference)
    champions = _normalise_euro_clubs(champions, used - set(champions))
    used.update(champions)
    europa = _normalise_euro_clubs(europa, used - set(europa))
    used.update(europa)
    conference = _normalise_euro_clubs(conference, used - set(conference))

    return {
        "champions_league": champions[:36],
        "europa_league": europa[:36],
        "conference_league": conference[:36]
    }


async def generate_euro_data(season):
    participants = await determine_euro_participants(season)
    euro_data = {
        "season": season,
        "status": "group",
        "champions_league": _make_euro_tournament_data(participants["champions_league"]),
        "europa_league": _make_euro_tournament_data(participants["europa_league"]),
        "conference_league": _make_euro_tournament_data(participants["conference_league"]),
        "playoffs": {
            "champions_league": {"playoff": [], "round_16": [], "quarter": [], "semi": [], "final": None},
            "europa_league": {"playoff": [], "round_16": [], "quarter": [], "semi": [], "final": None},
            "conference_league": {"playoff": [], "round_16": [], "quarter": [], "semi": [], "final": None}
        }
    }

    for tournament in EURO_KEYS:
        euro_data[tournament]["fixtures"] = generate_swiss_fixtures(euro_data[tournament]["clubs"])

    await save_data(EURO_FILE, euro_data)
    return euro_data


async def ensure_euro_data(season=None):
    """Проверяет старый euro_qualification.json и автоматически чинит его.
    Это важно для уже существующих сохранений: старый файл мог содержать только
    20 команд или вообще не иметь fixtures.
    """
    players = await load_data(PLAYERS_FILE)
    if season is None:
        seasons = [int(p.get("season", 1)) for p in players.values() if str(p.get("season", 1)).isdigit()]
        season = max(seasons or [1])

    euro_data = await load_data(EURO_FILE)
    changed = False

    if not isinstance(euro_data, dict) or not euro_data:
        euro_data = await generate_euro_data(season)
        return euro_data

    if euro_data.get("season") != season:
        # Новый сезон создается только если сохранение действительно относится
        # к старому сезону. Старый сезон при этом не трогаем до конца его матчей.
        euro_data = await generate_euro_data(season)
        return euro_data

    euro_data.setdefault("season", season)
    euro_data.setdefault("status", "group")
    euro_data.setdefault("playoffs", {})

    all_existing = set()
    for tournament in EURO_KEYS:
        section = euro_data.get(tournament)
        if not isinstance(section, dict):
            section = _make_euro_tournament_data([])
            euro_data[tournament] = section
            changed = True

        old_clubs = section.get("clubs", [])
        # Старые таблицы могли иметь 20 команд. Сохраняем их очки и дополняем до 36.
        if len(old_clubs) != 36:
            new_clubs = _normalise_euro_clubs(old_clubs, all_existing - set(old_clubs))
            old_table = section.get("table", {}) if isinstance(section.get("table", {}), dict) else {}
            new_table = {}
            for club in new_clubs:
                row = _new_euro_table_row()
                if isinstance(old_table.get(club), dict):
                    for key in row:
                        if key in old_table[club]:
                            row[key] = old_table[club][key]
                new_table[club] = row
            section["clubs"] = new_clubs
            section["table"] = new_table
            changed = True

        all_existing.update(section.get("clubs", []))

        fixtures = section.get("fixtures")
        if not isinstance(fixtures, dict):
            fixtures = {}
        valid = True
        for club in section.get("clubs", []):
            club_fixtures = fixtures.get(club, [])
            if not isinstance(club_fixtures, list) or len(club_fixtures) != 8:
                valid = False
                break
            opponents = [f.get("opponent") for f in club_fixtures if isinstance(f, dict)]
            if len(opponents) != 8 or len(set(opponents)) != 8:
                valid = False
                break

        if not valid:
            # Если календарь отсутствовал, создаем его. Сыгранные результаты из
            # таблицы не стираются.
            section["fixtures"] = generate_swiss_fixtures(section.get("clubs", []))
            changed = True
        else:
            section["fixtures"] = fixtures

        section.setdefault("played", 0)
        section.setdefault("status", "group")
        section.setdefault("qualified", [])
        section.setdefault("eliminated", [])

        euro_data["playoffs"].setdefault(tournament, {
            "playoff": [], "round_16": [], "quarter": [], "semi": [], "final": None
        })

    # Если у старого файла статус playoff был поставлен после матча только одного
    # игрока, возвращаем корректный групповой статус. Каждый турнир теперь имеет свой статус.
    for tournament in EURO_KEYS:
        section = euro_data[tournament]
        if section.get("status") not in ("group", "playoff", "finished"):
            section["status"] = "group"
            changed = True

    if changed:
        await save_data(EURO_FILE, euro_data)

    # Привязываем игроков к турниру, если клуб уже есть в новом исправленном файле.
    players_changed = False
    for uid, p in players.items():
        if p.get("retired") or not p.get("club"):
            continue
        found = None
        for tournament in EURO_KEYS:
            if p["club"] in euro_data[tournament]["clubs"]:
                found = tournament
                break
        if found:
            if p.get("euro_tournament") != found:
                p["euro_tournament"] = found
                p.setdefault("euro_goals", 0)
                p.setdefault("euro_assists", 0)
                p.setdefault("euro_matches", 0)
                p.setdefault("euro_playoff_stage", None)
                players_changed = True
        elif p.get("euro_tournament") not in EURO_KEYS:
            p["euro_tournament"] = "none"
            players_changed = True

    if players_changed:
        await save_data(PLAYERS_FILE, players)

    return euro_data


async def get_euro_fixture(user_id):
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if not p:
        return None

    euro_data = await ensure_euro_data(p.get("season", 1))
    tournament = p.get("euro_tournament")
    if tournament not in EURO_KEYS:
        return None

    section = euro_data[tournament]
    if section.get("status") != "group":
        return None

    fixtures = section.get("fixtures", {}).get(p["club"], [])
    for fixture in fixtures:
        if not fixture.get("played", False):
            return fixture
    return None


async def get_euro_position(user_id):
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if not p:
        return None

    euro_data = await ensure_euro_data(p.get("season", 1))
    tournament = p.get("euro_tournament")
    if tournament not in EURO_KEYS:
        return None

    table = euro_data[tournament].get("table", {})
    sorted_table = sorted(
        table.items(),
        key=lambda x: (
            x[1].get("points", 0),
            x[1].get("goals_for", 0) - x[1].get("goals_against", 0),
            x[1].get("goals_for", 0)
        ),
        reverse=True
    )

    for i, (club, data) in enumerate(sorted_table, 1):
        if club == p.get("club"):
            return i
    return None


def get_euro_name(tournament):
    names = {key: value["name"] for key, value in EURO_TOURNAMENTS.items()}
    return names.get(tournament, "❌ Нет")


def _euro_table_sorted(section):
    table = section.get("table", {})
    return sorted(
        table.items(),
        key=lambda x: (
            x[1].get("points", 0),
            x[1].get("goals_for", 0) - x[1].get("goals_against", 0),
            x[1].get("goals_for", 0)
        ),
        reverse=True
    )


def _euro_table_keyboard(page, total_pages):
    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"euro_table:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"euro_table:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🔙 В еврокубки", callback_data="menu_euro")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _render_euro_menu(callback, user_id, p, euro_data):
    tournament = p.get("euro_tournament")
    if tournament not in EURO_KEYS:
        await callback.message.edit_text(
            "🌍 Твой клуб не участвует в еврокубках в этом сезоне.",
            reply_markup=await main_menu_keyboard(callback.from_user.username, user_id)
        )
        return

    section = euro_data[tournament]
    euro_info = EURO_TOURNAMENTS[tournament]
    table = section.get("table", {})
    fixtures = section.get("fixtures", {}).get(p["club"], [])
    played = sum(1 for f in fixtures if f.get("played", False))
    total = len(fixtures)
    position = await get_euro_position(user_id)
    status = section.get("status", "group")

    text = f"{euro_info['emoji']} **{euro_info['name']}**\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📊 Статус: {'Групповой этап' if status == 'group' else 'Плей-офф'}\n"
    text += f"📈 Твое место: {position if position else '?'} из {len(table)}\n"
    text += f"📅 Сыграно матчей: {played}/{total}\n"

    stats = table.get(p["club"])
    if stats:
        text += f"📊 Очки: {stats.get('points', 0)} | Голы: {stats.get('goals_for', 0)}:{stats.get('goals_against', 0)}\n"

    text += "\n📋 **Календарь ЛЧ / Еврокубка:**\n"
    if fixtures:
        for f in fixtures:
            status_icon = "✅" if f.get("played") else "⏳"
            venue = "🏠" if f.get("home") else "✈️"
            if f.get("played"):
                result = f"{f.get('goals_for', 0)}:{f.get('goals_against', 0)}"
            else:
                result = "ожидается"
            text += f"{status_icon} Тур {f.get('tour', '?')}: {venue} **{f.get('opponent', '?')}** — {result}\n"
    else:
        text += "⚠️ Календарь не найден. Он будет восстановлен автоматически.\n"

    buttons = []
    next_match = next((f for f in fixtures if not f.get("played", False)), None)
    if next_match and status == "group":
        buttons.append([InlineKeyboardButton(text="▶️ Сыграть следующий матч", callback_data="euro_play_match")])
    elif p.get("euro_playoff_stage") in {"playoff", "round_16", "quarter", "semi", "final"}:
        buttons.append([InlineKeyboardButton(text="🏆 Открыть плей-офф", callback_data="euro_playoff_menu")])
    elif status == "playoff":
        buttons.append([InlineKeyboardButton(text="🏆 Открыть плей-офф", callback_data="euro_playoff_menu")])

    buttons.append([InlineKeyboardButton(text="📊 Таблица", callback_data="euro_table:0")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        else:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)


@dp.callback_query(F.data == "menu_euro")
@with_user_lock
async def euro_menu_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    await track_activity(user_id)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if await deny_if_retired_cb(callback, p):
        return

    euro_data = await ensure_euro_data(p.get("season", 1))
    await _render_euro_menu(callback, user_id, p, euro_data)


@dp.callback_query(F.data == "euro_table")
@dp.callback_query(F.data.startswith("euro_table:"))
@with_user_lock
async def euro_table_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if await deny_if_retired_cb(callback, p):
        return

    euro_data = await ensure_euro_data(p.get("season", 1))
    tournament = p.get("euro_tournament")
    if tournament not in EURO_KEYS:
        await callback.answer("Ты не участвуешь в еврокубках", show_alert=True)
        return

    try:
        page = int(callback.data.split(":", 1)[1]) if ":" in callback.data else 0
    except ValueError:
        page = 0

    sorted_table = _euro_table_sorted(euro_data[tournament])
    total_pages = max(1, (len(sorted_table) + EURO_TABLE_PAGE_SIZE - 1) // EURO_TABLE_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * EURO_TABLE_PAGE_SIZE
    end = start + EURO_TABLE_PAGE_SIZE
    current_rows = sorted_table[start:end]

    info = EURO_TOURNAMENTS[tournament]
    text = f"📊 **ТАБЛИЦА — {info['name']}**\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += "🏆 Победа — 3 | 🤝 Ничья — 1\n"
    text += f"📄 Страница {page + 1}/{total_pages}\n\n"

    for index, (club, stats) in enumerate(current_rows, start + 1):
        marker = "👉" if club == p.get("club") else "•"
        gd = stats.get("goals_for", 0) - stats.get("goals_against", 0)
        text += (
            f"{index}. {marker} **{club}** — {stats.get('points', 0)} очк. | "
            f"{stats.get('played', 0)} игр | {stats.get('goals_for', 0)}:{stats.get('goals_against', 0)} | РМ {gd:+d}\n"
        )

    kb = _euro_table_keyboard(page, total_pages)
    try:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        else:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)


@dp.callback_query(F.data == "euro_play_match")
@with_user_lock
async def euro_play_match_handler(callback: CallbackQuery, state: FSMContext):
    user_id = await get_uid(callback)
    await track_activity(user_id)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if await deny_if_retired_cb(callback, p):
        return

    euro_data = await ensure_euro_data(p.get("season", 1))
    tournament = p.get("euro_tournament")
    if tournament not in EURO_KEYS:
        await callback.answer("Ты не участвуешь в еврокубках", show_alert=True)
        return

    if euro_data[tournament].get("status") != "group":
        await callback.answer("Групповой этап этого турнира уже завершен", show_alert=True)
        return

    fixture = await get_euro_fixture(user_id)
    if not fixture:
        await callback.answer("Все 8 матчей группового этапа сыграны", show_alert=True)
        return

    await state.update_data(euro_match={
        "tournament": tournament,
        "opponent": fixture["opponent"],
        "home": fixture["home"],
        "tour": fixture["tour"],
        "goals": 0,
        "assists": 0,
        "saves": 0,
        "tackles": 0,
        "yellow_cards": 0,
        "my_score": 0,
        "opponent_score": 0,
        "log": "",
        "moment": 0,
        "total_moments": random.randint(4, 6),
        "minute": 0
    })
    await start_euro_match(callback, state, user_id)


async def start_euro_match(callback: CallbackQuery, state: FSMContext, user_id: str):
    data = await state.get_data()
    match = data.get("euro_match")
    if not match:
        return
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    info = EURO_TOURNAMENTS.get(match["tournament"], {})
    venue = "🏠 Дома" if match["home"] else "✈️ В гостях"

    text = (
        f"{info.get('emoji', '🌍')} **{info.get('name', 'Еврокубки')}**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ **{p['club']}** vs **{match['opponent']}**\n"
        f"📍 {venue}\n"
        f"📅 Тур {match['tour']}/8\n\n"
        "🏟️ **Матч начался!**\n"
        "Судья дает свисток к началу игры."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Продолжить", callback_data="euro_match_action")]
    ])

    try:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        else:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)


@dp.callback_query(F.data == "euro_match_action")
@with_user_lock
async def euro_match_action_handler(callback: CallbackQuery, state: FSMContext):
    user_id = await get_uid(callback)
    data = await state.get_data()
    match = data.get("euro_match")
    if not match:
        await callback.answer("Матч не найден", show_alert=True)
        return

    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if not p:
        await callback.answer("Профиль не найден", show_alert=True)
        return

    match["moment"] = match.get("moment", 0) + 1
    previous_minute = match.get("minute", 0)
    match["minute"] = min(90, previous_minute + random.randint(12, 24))

    # Генерируем события с нормальными вероятностями, чтобы матчи не заканчивались 0:0 постоянно.
    event_roll = random.random()
    if event_roll < 0.42:
        if random.random() < 0.53:
            match["my_score"] += 1
            match["goals"] += 1
            match["log"] += f"⚽ **{match['minute']}'** | Твоя команда забивает гол!\n"
        else:
            match["opponent_score"] += 1
            match["log"] += f"⚡ **{match['minute']}'** | Соперник забивает гол!\n"
    elif event_roll < 0.58:
        if p.get("position") == "GK":
            match["saves"] += random.randint(1, 2)
            match["log"] += f"🧤 **{match['minute']}'** | Вратарь делает сейв.\n"
        elif p.get("position") == "CB":
            match["tackles"] += 1
            match["log"] += f"🛡️ **{match['minute']}'** | Удачный отбор в обороне.\n"
        else:
            match["assists"] += 1 if random.random() < 0.25 else 0
            match["log"] += f"🎯 **{match['minute']}'** | Хорошая атака команды.\n"
    elif random.random() < 0.12:
        match["yellow_cards"] += 1
        match["log"] += f"🟨 **{match['minute']}'** | Желтая карточка.\n"

    # Финальный момент обязательно завершает матч.
    if match["moment"] >= match.get("total_moments", 5) or match["minute"] >= 90:
        await state.update_data(euro_match=match)
        await finish_euro_match(callback, state, user_id)
        return

    text = (
        f"⏱ **{match['minute']}' МИНУТА**\n"
        f"⚔️ **{p['club']}** vs **{match['opponent']}**\n"
        f"Счет: **{match['my_score']} : {match['opponent_score']}**\n\n"
        f"📝 **События матча:**\n{match['log'] or 'Идет игра...'}"
    )
    match["log"] = ""
    await state.update_data(euro_match=match)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Продолжить", callback_data="euro_match_action")]
    ])
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)


async def _update_euro_table_for_match(section, club, opponent, my_score, opponent_score, result):
    table = section.setdefault("table", {})
    table.setdefault(club, _new_euro_table_row())
    table.setdefault(opponent, _new_euro_table_row())

    home = table[club]
    away = table[opponent]
    home["played"] += 1
    away["played"] += 1
    home["goals_for"] += my_score
    home["goals_against"] += opponent_score
    away["goals_for"] += opponent_score
    away["goals_against"] += my_score

    if result == "win":
        home["points"] += 3
        home["wins"] += 1
        away["losses"] += 1
    elif result == "draw":
        home["points"] += 1
        away["points"] += 1
        home["draws"] += 1
        away["draws"] += 1
    else:
        away["points"] += 3
        home["losses"] += 1
        away["wins"] += 1


async def _mark_euro_fixture_played(section, club, tour, my_score, opponent_score, result):
    fixtures = section.setdefault("fixtures", {})
    club_fixtures = fixtures.setdefault(club, [])
    opponent = None

    for fixture in club_fixtures:
        if fixture.get("tour") == tour:
            fixture["played"] = True
            fixture["goals_for"] = my_score
            fixture["goals_against"] = opponent_score
            fixture["result"] = result
            opponent = fixture.get("opponent")
            break

    # Если этот же матч присутствует в календаре соперника, закрываем его тоже,
    # чтобы один матч никогда не начислялся дважды.
    if opponent and opponent in fixtures:
        reverse_result = "win" if result == "loss" else "loss" if result == "win" else "draw"
        for reverse in fixtures[opponent]:
            if reverse.get("opponent") == club and not reverse.get("played", False):
                reverse["played"] = True
                reverse["goals_for"] = opponent_score
                reverse["goals_against"] = my_score
                reverse["result"] = reverse_result
                break

    return opponent


async def finish_euro_match(callback: CallbackQuery, state: FSMContext, user_id: str):
    data = await state.get_data()
    match = data.get("euro_match")
    if not match:
        await callback.answer("Матч уже завершен", show_alert=True)
        return

    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if not p:
        await state.clear()
        await callback.answer("Профиль не найден", show_alert=True)
        return

    euro_data = await ensure_euro_data(p.get("season", 1))
    tournament = match.get("tournament")
    if tournament not in EURO_KEYS or tournament not in euro_data:
        await state.clear()
        await callback.answer("Еврокубок не найден", show_alert=True)
        return

    section = euro_data[tournament]
    my_score = int(match.get("my_score", 0))
    opponent_score = int(match.get("opponent_score", 0))

    if my_score > opponent_score:
        result = "win"
        result_text = "🏆 **ПОБЕДА!**"
        prize = EURO_TOURNAMENTS[tournament]["prize_win"]
    elif my_score == opponent_score:
        result = "draw"
        result_text = "🤝 **НИЧЬЯ**"
        prize = EURO_TOURNAMENTS[tournament]["prize_draw"]
    else:
        result = "loss"
        result_text = "❌ **ПОРАЖЕНИЕ**"
        prize = 0

    # Защита от повторного начисления, если Telegram повторно доставил callback.
    fixtures = section.setdefault("fixtures", {}).setdefault(p["club"], [])
    current_fixture = next((f for f in fixtures if f.get("tour") == match.get("tour")), None)
    if current_fixture and current_fixture.get("played"):
        await state.clear()
        await callback.answer("Этот матч уже сохранен", show_alert=True)
        return

    opponent = await _mark_euro_fixture_played(
        section, p["club"], match["tour"], my_score, opponent_score, result
    )
    opponent = opponent or match.get("opponent", "Соперник")

    # В таблице учитываем обе команды. Это исправляет старую проблему,
    # когда очки получал только игрок, а соперник оставался с 0 матчей.
    await _update_euro_table_for_match(
        section, p["club"], opponent, my_score, opponent_score, result
    )
    section["played"] = section.get("played", 0) + 1

    p["money"] = p.get("money", 0) + prize
    p["euro_goals"] = p.get("euro_goals", 0) + match.get("goals", 0)
    p["euro_assists"] = p.get("euro_assists", 0) + match.get("assists", 0)
    p["euro_matches"] = p.get("euro_matches", 0) + 1

    # Сезонная статистика игрока тоже получает еврокубковый матч.
    p.setdefault("stats_season", {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0})
    p.setdefault("stats_total", {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0})
    p["stats_season"]["games"] = p["stats_season"].get("games", 0) + 1
    p["stats_total"]["games"] = p["stats_total"].get("games", 0) + 1
    for key in ["goals", "assists", "saves", "tackles"]:
        value = int(match.get(key, 0))
        if value:
            p["stats_season"][key] = p["stats_season"].get(key, 0) + value
            p["stats_total"][key] = p["stats_total"].get(key, 0) + value

    rating_bonus = (
        match.get("goals", 0) * 0.1 +
        match.get("assists", 0) * 0.05 +
        match.get("saves", 0) * 0.05 +
        match.get("tackles", 0) * 0.03
    )
    if result == "win":
        rating_bonus += 0.1
    elif result == "loss":
        rating_bonus -= 0.05
    p["rating"] = max(1.0, min(100.0, round(p.get("rating", 40.0) + rating_bonus, 1)))

    # Проверяем именно этот турнир, а не глобальный статус всего EURO_FILE.
    club_fixtures = section["fixtures"].get(p["club"], [])
    all_player_matches = bool(club_fixtures) and all(f.get("played", False) for f in club_fixtures)

    playoff_text = ""
    if all_player_matches:
        sorted_table = _euro_table_sorted(section)
        position = next((i + 1 for i, (club, _) in enumerate(sorted_table) if club == p["club"]), None)
        section["status"] = "playoff" if position and position <= 24 else "finished"

        if position and position <= 8:
            p["euro_playoff_stage"] = "round_16"
            section.setdefault("qualified", []).append(p["club"])
            playoff_text = "\n\n🎉 **Ты прошел напрямую в 1/8 финала!**"
        elif position and position <= 24:
            p["euro_playoff_stage"] = "playoff"
            section.setdefault("qualified", []).append(p["club"])
            playoff_text = "\n\n⚔️ **Ты попал в стыковые матчи за выход в 1/8!**"
        else:
            p["euro_playoff_stage"] = None
            p["euro_tournament"] = "none"
            section.setdefault("eliminated", []).append(p["club"])
            playoff_text = "\n\n😔 **К сожалению, ты вылетел из еврокубков.**"

        # Плей-офф строим только после завершения всех 36 клубами группового этапа.
        # Для текущего игрока не блокируем матчами остальных клубов.
        all_clubs_finished = all(
            all(f.get("played", False) for f in section["fixtures"].get(club, []))
            for club in section.get("clubs", [])
        )
        if all_clubs_finished:
            section["status"] = "playoff"
            await generate_euro_playoffs(euro_data, tournament)

    players[user_id] = p
    await save_data(PLAYERS_FILE, players)
    await save_data(EURO_FILE, euro_data)

    text = (
        "🏁 **МАТЧ ЗАВЕРШЕН!**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ **{p['club']} {my_score} : {opponent_score} {opponent}**\n"
        f"{result_text}\n\n"
        "📊 **Твоя статистика:**\n"
        f"⚽ Голы: {match.get('goals', 0)}\n"
        f"🅰️ Ассисты: {match.get('assists', 0)}\n"
        f"🧤 Сейвы: {match.get('saves', 0)}\n"
        f"🛡️ Отборы: {match.get('tackles', 0)}\n\n"
        f"💰 Призовые: +{prize}$\n"
        f"📈 Рейтинг: {p['rating']} ({'+' if rating_bonus >= 0 else ''}{round(rating_bonus, 1)})"
        f"{playoff_text}"
    )

    await state.clear()
    kb = await main_menu_keyboard(callback.from_user.username, user_id)
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        if callback.message.photo:
            await callback.message.delete()
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)


async def generate_euro_playoffs(euro_data, tournament):
    section = euro_data[tournament]
    sorted_table = _euro_table_sorted(section)
    top8 = [club for club, _ in sorted_table[:8]]
    positions_9_24 = [club for club, _ in sorted_table[8:24]]

    playoff_pairs = []
    random.shuffle(positions_9_24)
    for i in range(0, len(positions_9_24), 2):
        if i + 1 < len(positions_9_24):
            playoff_pairs.append([positions_9_24[i], positions_9_24[i + 1]])

    # Для текущей виртуальной лиги стыковые пары моделируются заранее.
    playoff_winners = []
    for pair in playoff_pairs:
        winner = random.choice(pair)
        playoff_winners.append(winner)

    round16_teams = top8 + playoff_winners
    random.shuffle(round16_teams)
    round16 = []
    for i in range(0, len(round16_teams), 2):
        if i + 1 < len(round16_teams):
            round16.append([round16_teams[i], round16_teams[i + 1]])

    euro_data.setdefault("playoffs", {}).setdefault(tournament, {})
    euro_data["playoffs"][tournament]["playoff"] = playoff_pairs
    euro_data["playoffs"][tournament]["round_16"] = round16

    await save_data(EURO_FILE, euro_data)


@dp.callback_query(F.data == "euro_group_results")
@with_user_lock
async def euro_group_results_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if await deny_if_retired_cb(callback, p):
        return

    euro_data = await ensure_euro_data(p.get("season", 1))
    tournament = p.get("euro_tournament")
    if tournament not in EURO_KEYS:
        await callback.answer("Ты не участвуешь в еврокубках", show_alert=True)
        return

    position = await get_euro_position(user_id)
    info = EURO_TOURNAMENTS[tournament]
    text = (
        f"📊 **ИТОГИ ГРУППОВОГО ЭТАПА**\n"
        f"{info['emoji']} {info['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 Твое место: {position if position else '?'} из 36\n\n"
    )

    if position and position <= 8:
        text += "🎉 **Поздравляю!**\nТы напрямую прошел в 1/8 финала!"
    elif position and position <= 24:
        text += "⚔️ **Стыковые матчи!**\nТы сыграешь за выход в 1/8 финала."
    else:
        text += "😔 **Вылет из еврокубков.**\nСосредоточься на следующем сезоне!"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Таблица", callback_data="euro_table:0")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_euro")]
    ])
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)


@dp.callback_query(F.data == "euro_playoff_menu")
@with_user_lock
async def euro_playoff_menu_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if await deny_if_retired_cb(callback, p):
        return

    euro_data = await ensure_euro_data(p.get("season", 1))
    tournament = p.get("euro_tournament")
    if tournament not in EURO_KEYS:
        await callback.answer("Ты не участвуешь в еврокубках", show_alert=True)
        return

    section = euro_data[tournament]
    playoffs = euro_data.get("playoffs", {}).get(tournament, {})
    stage = p.get("euro_playoff_stage")
    info = EURO_TOURNAMENTS[tournament]

    stage_names = {
        "playoff": "Стыковые матчи",
        "round_16": "1/8 финала",
        "quarter": "1/4 финала",
        "semi": "Полуфинал",
        "final": "Финал"
    }

    text = (
        f"🏆 **ПЛЕЙ-ОФФ — {info['name']}**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Текущая стадия: {stage_names.get(stage, 'Еще не определена')}\n\n"
    )

    if playoffs.get("playoff"):
        text += "**Стыковые матчи:**\n"
        for pair in playoffs["playoff"]:
            marker = "👉 " if p["club"] in pair else "• "
            text += f"{marker}{pair[0]} vs {pair[1]}\n"
        text += "\n"

    if playoffs.get("round_16"):
        text += "**1/8 финала:**\n"
        for pair in playoffs["round_16"]:
            marker = "👉 " if p["club"] in pair else "• "
            text += f"{marker}{pair[0]} vs {pair[1]}\n"

    buttons = []
    if stage == "playoff":
        buttons.append([InlineKeyboardButton(text="▶️ Сыграть стыковой матч", callback_data="euro_playoff_match:playoff")])
    elif stage == "round_16":
        buttons.append([InlineKeyboardButton(text="▶️ Сыграть 1/8 финала", callback_data="euro_playoff_match:round_16")])
    elif stage == "quarter":
        buttons.append([InlineKeyboardButton(text="▶️ Сыграть 1/4 финала", callback_data="euro_playoff_match:quarter")])
    elif stage == "semi":
        buttons.append([InlineKeyboardButton(text="▶️ Сыграть полуфинал", callback_data="euro_playoff_match:semi")])
    elif stage == "final":
        buttons.append([InlineKeyboardButton(text="🏆 Сыграть финал!", callback_data="euro_playoff_match:final")])

    buttons.append([InlineKeyboardButton(text="📊 Таблица", callback_data="euro_table:0")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu_euro")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)


@dp.callback_query(F.data.startswith("euro_playoff_match:"))
@with_user_lock
async def euro_playoff_match_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if await deny_if_retired_cb(callback, p):
        return

    euro_data = await ensure_euro_data(p.get("season", 1))
    tournament = p.get("euro_tournament")
    stage = callback.data.split(":", 1)[1]
    if tournament not in EURO_KEYS:
        await callback.answer("Ты не участвуешь в еврокубках", show_alert=True)
        return

    playoffs = euro_data.get("playoffs", {}).get(tournament, {})
    pairs = playoffs.get(stage, [])
    pair = next((pair for pair in pairs if p["club"] in pair), None)

    if not pair:
        await callback.answer("Твоя пара на этой стадии не найдена", show_alert=True)
        return

    opponent = pair[1] if pair[0] == p["club"] else pair[0]
    my_strength = CLUB_RATINGS.get(p["club"], 50)
    opp_strength = CLUB_RATINGS.get(opponent, 50)
    probability = 0.5 + max(-0.22, min(0.22, (my_strength - opp_strength) * 0.012))
    roll = random.random()
    if roll < probability:
        my_score = random.randint(1, 3)
        opponent_score = random.randint(0, max(0, my_score - 1))
        winner = p["club"]
    else:
        opponent_score = random.randint(1, 3)
        my_score = random.randint(0, max(0, opponent_score - 1))
        winner = opponent

    if my_score == opponent_score:
        # В плей-офф ничья после основного времени решается серией пенальти.
        winner = p["club"] if random.random() < probability else opponent
        winner_text = "по пенальти"
    else:
        winner_text = ""

    next_stage = {
        "playoff": "round_16",
        "round_16": "quarter",
        "quarter": "semi",
        "semi": "final",
        "final": "winner"
    }.get(stage, "winner")
    stage_names = {
        "playoff": "стыковые матчи",
        "round_16": "1/8 финала",
        "quarter": "1/4 финала",
        "semi": "полуфинал",
        "final": "финал"
    }

    if winner == p["club"]:
        p["euro_playoff_stage"] = next_stage if next_stage != "winner" else None
        if next_stage == "winner":
            p["money"] = p.get("money", 0) + EURO_TOURNAMENTS[tournament]["prize_winner"]
            p["trophies"] = p.get("trophies", []) + [f"🏆 Победитель {EURO_TOURNAMENTS[tournament]['short_name']} (Сезон {p.get('season', 1)})"]
            p["rating"] = min(100.0, round(p.get("rating", 40.0) + EURO_TOURNAMENTS[tournament]["rating_bonus_winner"], 1))
            p["euro_tournament"] = "none"
            result_line = "🏆 **ТЫ ПОБЕДИЛ В ЕВРОКУБКЕ!**"
        else:
            result_line = f"✅ **Ты проходишь в {stage_names.get(next_stage, next_stage)}!**"
    else:
        p["euro_playoff_stage"] = None
        p["euro_tournament"] = "none"
        result_line = "❌ **Ты вылетел из еврокубков.**"

    players = await load_data(PLAYERS_FILE)
    players[user_id] = p
    await save_data(PLAYERS_FILE, players)

    score_line = f"{p['club']} {my_score} : {opponent_score} {opponent}"
    if winner_text:
        score_line += f" ({winner_text})"

    text = (
        f"🏁 **МАТЧ ПЛЕЙ-ОФФ ЗАВЕРШЕН!**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ **{score_line}**\n\n"
        f"{result_line}"
    )
    kb = await main_menu_keyboard(callback.from_user.username, user_id)
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)

# ========== ФУНКЦИЯ ДЛЯ АВТОУДАЛЕНИЯ СООБЩЕНИЙ (3 СЕКУНДЫ) ==========
async def send_auto_delete_message(message: Message, text: str, parse_mode: str = "Markdown", reply_markup=None, delay: int = 3):
    """Отправляет сообщение и удаляет его через delay секунд (по умолчанию 3)"""
    sent = await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
    await asyncio.sleep(delay)
    try:
        await sent.delete()
    except Exception:
        pass

# ============================================================
# ОБРАБОТЧИКИ (ОСТАЛЬНЫЕ)
# ============================================================

@dp.callback_query(F.data == "menu_online")
async def online_handler(callback: CallbackQuery):
    players = await load_data(PLAYERS_FILE)
    total = len(players)
    online = max(1, int(total * 0.15) + random.randint(1, 4))
    
    top_active = sorted(players.values(), key=lambda x: x.get("activity_minutes", 0), reverse=True)[:5]
    top_text = "\n\n🔥 **Топ игроков по активности (за эту неделю):**\n"
    for i, p in enumerate(top_active, 1):
        mins = p.get('activity_minutes', 0)
        hours = mins // 60
        minutes = mins % 60
        if hours > 0:
            time_str = f"{hours} ч. {minutes} мин."
        else:
            time_str = f"{minutes} мин."
        top_text += f"{i}. {p['name']} — {time_str}\n"

    await callback.answer(f"🟢 Сейчас в боте: {online} чел.\n👥 Всего игроков в базе: {total}", show_alert=True)
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(top_text, parse_mode="Markdown", reply_markup=await main_menu_keyboard(callback.from_user.username, await get_uid(callback)))
    else:
        await callback.message.edit_text(top_text, parse_mode="Markdown", reply_markup=await main_menu_keyboard(callback.from_user.username, await get_uid(callback)))

@dp.callback_query(F.data == "menu_leaderboard")
async def leaderboard_handler(callback: CallbackQuery):
    try:
        leaderboard = await load_data(LEADERBOARD_FILE)
        careers = leaderboard.get("top_careers", [])
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 10
        if not careers:
            text = (
                "🏆 **ЗАЛ СЛАВЫ**\n━━━━━━━━━━━━━━━━━━━━\n"
                "Здесь появятся лучшие игроки, завершившие карьеру.\n"
                "Стань первым легендой!"
            )
        else:
            lines = ["🏆 **ЗАЛ СЛАВЫ — Легенды игры**\n━━━━━━━━━━━━━━━━━━━━"]
            for i, c in enumerate(careers[:10]):
                lines.append(
                    f"{medals[i]} {c['name']} | "
                    f"⭐ Рейтинг: {c['rating']} | "
                    f"🏆 Трофеев: {c['trophies']}"
                )
            text = "\n".join(lines)
    except Exception as e:
        logging.warning(f"leaderboard_handler load error: {e}")
        text = "⚠️ Не удалось загрузить Зал Славы. Попробуй позже."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    try:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        else:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logging.warning(f"leaderboard_handler send error: {e}")
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data.startswith("interview:"))
@with_user_lock
async def interview_handler(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) != 3:
        return await callback.answer()
    q_idx = int(parts[1])
    choice = parts[2]

    data = await state.get_data()
    iv = data.get("interview")
    if not iv:
        await callback.answer()
        user_id = await get_uid(callback)
        kb = await main_menu_keyboard(callback.from_user.username, user_id)
        try:
            await callback.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass
        return

    questions = iv["questions"]
    trust_gain = iv.get("trust_gain", 0)
    rep_gain = iv.get("rep_gain", 0)
    
    if q_idx < len(questions):
        q = questions[q_idx]
        if choice == "a":
            trust_gain += q.get("trust_a", 0)
            rep_gain += q.get("rep_a", 0)
        elif choice == "b":
            trust_gain += q.get("trust_b", 0)
            rep_gain += q.get("rep_b", 0)
        else:
            trust_gain += q.get("trust_c", 0)
            rep_gain += q.get("rep_c", 0)

    user_id = await get_uid(callback)
    next_idx = q_idx + 1
    await callback.answer()

    if next_idx < len(questions):
        await state.update_data(interview={"questions": questions, "current": next_idx, "trust_gain": trust_gain, "rep_gain": rep_gain})
        nq = questions[next_idx]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"A) {nq['a']}", callback_data=f"interview:{next_idx}:a")],
            [InlineKeyboardButton(text=f"B) {nq['b']}", callback_data=f"interview:{next_idx}:b")],
            [InlineKeyboardButton(text=f"C) {nq['c']}", callback_data=f"interview:{next_idx}:c")]
        ])
        try:
            await callback.message.edit_text(
                f"🎙️ **Интервью — вопрос {next_idx + 1}/3:**\n_{nq['question']}_\n\nВыбери ответ:",
                parse_mode="Markdown", reply_markup=kb
            )
        except Exception as e:
            logging.warning(f"interview next_q error: {e}")
    else:
        await state.update_data(interview=None)
        players = await load_data(PLAYERS_FILE)
        p = players.get(user_id)
        if p:
            p["trust"] = min(100, p.get("trust", 0) + trust_gain)
            p["reputation"] = min(100, max(0, p.get("reputation", 50) + rep_gain))
            players[user_id] = p
            await save_data(PLAYERS_FILE, players)

        trust_now = p.get("trust", 0)
        rep_now = p.get("reputation", 50)
        text = (
            f"🎙️ **Интервью завершено!**\n"
            f"📣 Твои ответы произвели впечатление на публику!\n"
            f"❤️ +{trust_gain} к доверию болельщиков (итого: {trust_now})\n"
            f"⭐ {rep_gain:+} к репутации (итого: {rep_now})"
        )
        kb = await main_menu_keyboard(callback.from_user.username, user_id)
        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            logging.warning(f"interview finish error: {e}")
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "menu_sponsors")
@with_user_lock
async def sponsors_menu(callback: CallbackQuery):
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if await deny_if_retired_cb(callback, p): return

    rating = p.get("rating", 40)
    current_sponsor = p.get("sponsor")
    reputation = p.get("reputation", 50)

    lines = []
    buttons = []
    row = []
    for name, info in SPONSORS_DATA.items():
        locked = rating < info["min_rating"]
        bonus = " ⭐+5%" if reputation > 70 and not locked else ""
        
        if name == current_sponsor:
            status = "✅"
        elif locked:
            status = f"🔒 (рейт. {info['min_rating']})"
        else:
            status = ""
        lines.append(
            f"{info['emoji']} **{name}** {status} — {info['income_per_match']}$/матч{bonus}"
            + (f", бонус {info['sign_bonus']}$" if not locked else "")
        )
        label = f"{info['emoji']} {name} {status}"
        cb = "noop" if (locked or name == current_sponsor) else f"sponsor:{name}"
        row.append(InlineKeyboardButton(text=label, callback_data=cb))
        if len(row) == 2:
            buttons.append(row); row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])

    text = (
        f"💰 **РЕКЛАМНЫЕ КОНТРАКТЫ**\n"
        f"Твой рейтинг: **{rating}** | ⭐ Репутация: {reputation}\n"
        f"Активный спонсор: **{current_sponsor or 'Нет'}**\n"
        f"Доход начисляется за каждый матч автоматически.\n\n"
        + "\n".join(lines)
    )
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
        else:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        logging.warning(f"sponsors_menu error: {e}")
        await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data.startswith("sponsor:"))
@with_user_lock
async def sponsor_sign(callback: CallbackQuery):
    user_id = await get_uid(callback)
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if await deny_if_retired_cb(callback, p): return

    sp = callback.data.split(":")[1]
    info = SPONSORS_DATA.get(sp)
    if not info:
        return await callback.answer("❌ Неизвестный спонсор.", show_alert=True)
    if p.get("rating", 40) < info["min_rating"]:
        return await callback.answer(f"❌ Нужен рейтинг {info['min_rating']}!", show_alert=True)

    p["sponsor"] = sp
    bonus_mult = 1.05 if p.get("reputation", 50) > 70 else 1.0
    sign_bonus = int(info["sign_bonus"] * bonus_mult)
    p["money"] = p.get("money", 0) + sign_bonus
    players[user_id] = p
    await save_data(PLAYERS_FILE, players)

    text = (f"🤝 **Контракт с {info['emoji']} {sp} подписан!**\n"
            f"💵 Бонус при подписании: +{sign_bonus}$\n"
            f"📈 Доход за каждый матч: +{info['income_per_match']}$")
    kb = await main_menu_keyboard(callback.from_user.username, user_id)
    try:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        else:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logging.warning(f"sponsor_sign error: {e}")
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "menu_quests")
@with_user_lock
async def quests_menu_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if await deny_if_retired_cb(callback, p): return
    
    completed = p.get("completed_quests", [])
    has_claimable = False
    
    text = "🎯 **КВЕСТЫ И ДОСТИЖЕНИЯ**\nВыполняй задания и получай прибавку к рейтингу!\n\n"
    
    for q_id, q in QUESTS_DATA.items():
        if q_id in completed:
            text += f"✅ ~~{q['name']}~~ (+{q['reward']})\n"
        else:
            prog = get_quest_progress(p, q['type'])
            if prog >= q['target']:
                text += f"🎁 **{q['name']}** — ГОТОВО! (+{q['reward']})\n"
                has_claimable = True
            else:
                text += f"⏳ **{q['name']}**: {prog}/{q['target']} | Награда: +{q['reward']}\n"
                
    kb = []
    if has_claimable:
        kb.append([InlineKeyboardButton(text="🎁 Забрать награды", callback_data="claim_quests")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")

@dp.callback_query(F.data == "claim_quests")
@with_user_lock
async def claim_quests_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if await deny_if_retired_cb(callback, p): return
    
    completed = p.get("completed_quests", [])
    total_reward = 0.0
    
    for q_id, q in QUESTS_DATA.items():
        if q_id not in completed:
            if get_quest_progress(p, q['type']) >= q['target']:
                total_reward += q['reward']
                completed.append(q_id)
                
    if total_reward > 0:
        p["completed_quests"] = completed
        p["rating"] = min(100.0, round(p.get("rating", 40.0) + total_reward, 1))
        players[user_id] = p
        await save_data(PLAYERS_FILE, players)
        
        await callback.answer(f"🎉 Награды получены!\n\nТвой рейтинг вырос на +{round(total_reward, 1)}", show_alert=True)
        kb = await main_menu_keyboard(callback.from_user.username, user_id)
        await callback.message.edit_text("🏠 Главное меню", reply_markup=kb)
    else:
        await callback.answer("Нет доступных наград.", show_alert=True)

@dp.callback_query(F.data == "menu_personal_life")
@with_user_lock
async def personal_life_menu(callback: CallbackQuery):
    user_id = await get_uid(callback)
    await track_activity(user_id)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if await deny_if_retired_cb(callback, p): return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍽 В ресторан (-500$)", callback_data="personal:rest")],
        [InlineKeyboardButton(text="💃 Найти девушку (-2000$)" if p.get("girlfriend", "Нет") == "Нет" else "🎁 Подарок девушке (-1000$)", callback_data="personal:girl")],
        [InlineKeyboardButton(text="🧘 Йога (-300$)", callback_data="personal:yoga")],
        [InlineKeyboardButton(text="🪂 Парашют (-1500$)", callback_data="personal:parachute")],
        [InlineKeyboardButton(text="🎁 Благотворительность (-1000$)", callback_data="personal:charity")],
        [InlineKeyboardButton(text="🎉 Вечеринка (-800$)", callback_data="personal:party")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

    text = (f"🍷 **ЛИЧНАЯ ЖИЗНЬ**\n━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Баланс: {p.get('money', 0)}$\n"
            f"🔋 Усталость: {p.get('fatigue', 0)}%\n"
            f"❤️ Доверие: {p.get('trust', 0)}%\n\n"
            f"Трать деньги, чтобы снижать усталость!")

    await callback.message.delete()
    await callback.message.answer(text=text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("personal:"))
@with_user_lock
async def personal_action(callback: CallbackQuery):
    user_id = await get_uid(callback)
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if await deny_if_retired_cb(callback, p): return

    action = callback.data.split(":")[1]
    cost = 0
    msg = ""
    fatigue_reduction = 0
    trust_boost = 0

    if action == "rest":
        cost = 500
        fatigue_reduction = 15
        msg = "🍽 Ты отлично поужинал! Усталость -15%."
    elif action == "girl":
        if p.get("girlfriend", "Нет") == "Нет":
            cost = 2000
            if p.get("money", 0) >= cost:
                p["girlfriend"] = "Есть"
                msg = "💃 Ты познакомился с потрясающей девушкой!"
            else:
                msg = "❌ Не хватает денег на красивые ухаживания."
        else:
            cost = 1000
            fatigue_reduction = 20
            msg = "🎁 Ты подарил девушке дорогие украшения! Усталость -20%."
    elif action == "yoga":
        cost = 300
        fatigue_reduction = 20
        trust_boost = 1
        msg = "🧘 Йога помогла тебе расслабиться и восстановить баланс! Усталость -20%."
    elif action == "parachute":
        cost = 1500
        fatigue_reduction = 25
        trust_boost = 5
        msg = "🪂 Адреналин от прыжка с парашютом зарядил тебя энергией! Усталость -25%."
    elif action == "charity":
        cost = 1000
        trust_boost = 10
        msg = "🎁 Благотворительность повысила твой авторитет в глазах болельщиков! Доверие +10."
    elif action == "party":
        cost = 800
        fatigue_reduction = 15
        trust_boost = -2
        msg = "🎉 Вечеринка удалась! Усталость -15%, но болельщики немного недовольны."

    if "❌" not in msg:
        if p.get("money", 0) >= cost:
            p["money"] -= cost
            p["fatigue"] = max(0, p.get("fatigue", 0) - fatigue_reduction)
            p["trust"] = min(100, max(0, p.get("trust", 15) + trust_boost))
        else:
            msg = "❌ Не хватает денег."

    players[user_id] = p
    await save_data(PLAYERS_FILE, players)
    await callback.answer(msg, show_alert=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍽 В ресторан (-500$)", callback_data="personal:rest")],
        [InlineKeyboardButton(text="💃 Найти девушку (-2000$)" if p.get("girlfriend", "Нет") == "Нет" else "🎁 Подарок девушке (-1000$)", callback_data="personal:girl")],
        [InlineKeyboardButton(text="🧘 Йога (-300$)", callback_data="personal:yoga")],
        [InlineKeyboardButton(text="🪂 Парашют (-1500$)", callback_data="personal:parachute")],
        [InlineKeyboardButton(text="🎁 Благотворительность (-1000$)", callback_data="personal:charity")],
        [InlineKeyboardButton(text="🎉 Вечеринка (-800$)", callback_data="personal:party")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    text = (f"🍷 **ЛИЧНАЯ ЖИЗНЬ**\n━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Баланс: {p.get('money', 0)}$\n"
            f"🔋 Усталость: {p.get('fatigue', 0)}%\n"
            f"❤️ Доверие: {p.get('trust', 0)}%\n\n"
            f"Трать деньги, чтобы снижать усталость!")
    try:
        await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text=text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user.username or callback.from_user.username.replace("@", "") not in ADMINS:
        return await callback.answer("У вас нет доступа к этой панели.", show_alert=True)
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(
            "👑 **Админ-панель**\n\nОтправьте мне **ID пользователя** (например 123456_1) для управления:", 
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_menu")]])
        )
    else:
        await callback.message.edit_text(
            "👑 **Админ-панель**\n\nОтправьте мне **ID пользователя** для управления:", 
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_menu")]])
        )
    await state.set_state(AdminPanel.waiting_for_user_id)

# ========== ИСПРАВЛЕННАЯ АДМИН-ПАНЕЛЬ (ПОИСК ПО ID) ==========
@dp.message(AdminPanel.waiting_for_user_id)
async def admin_user_management(message: Message, state: FSMContext):
    target_input = message.text.strip()
    players = await load_data(PLAYERS_FILE)
    
    # Проверяем, есть ли игрок с таким ID
    if target_input in players and not players[target_input].get("retired"):
        target_id = target_input
    else:
        # Если не нашли, ищем по Telegram ID (без слота)
        found = []
        for uid, p in players.items():
            if uid.startswith(target_input + "_") and not p.get("retired"):
                found.append(uid)
        
        if not found:
            return await message.answer(
                "❌ Активный игрок с таким ID не найден.\n"
                "Попробуй скопировать полный ID из профиля (например: 123456789_1)",
                reply_markup=await main_menu_keyboard(message.from_user.username, await get_uid(message))
            )
        
        # Если нашли несколько слотов
        if len(found) > 1:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"Слот {uid.split('_')[1]}: {players[uid]['name']} ({players[uid].get('rating', 40)})", 
                    callback_data=f"admin_select:{uid}"
                )] for uid in found
            ])
            await message.answer("Найдено несколько профилей. Выбери нужный:", reply_markup=kb)
            return
        
        target_id = found[0]
    
    await show_admin_user_profile(message, target_id)
    await state.clear()

@dp.callback_query(F.data.startswith("admin_select:"))
async def admin_select_handler(callback: CallbackQuery, state: FSMContext):
    target_id = callback.data.split(":")[1]
    await show_admin_user_profile(callback, target_id)
    await state.clear()

# ========== ИСПРАВЛЕННОЕ ОТОБРАЖЕНИЕ ПРОФИЛЯ В АДМИНКЕ ==========
async def show_admin_user_profile(message_or_call, target_id):
    players = await load_data(PLAYERS_FILE)
    p = players[target_id]
    val = calculate_player_value(p["rating"], p["division"])
    
    parts = target_id.split("_")
    tg_id = parts[0]
    slot = parts[1] if len(parts) > 1 else "?"
    
    stats_text = ""
    if p["position"] == "GK": 
        stats_text = f"🧤 Сейвы: {p['stats_season'].get('saves', 0)}"
    elif p["position"] == "CB": 
        stats_text = f"🛡️ Отборы: {p['stats_season'].get('tackles', 0)} | ⚽ Голы: {p['stats_season'].get('goals', 0)}"
    else: 
        stats_text = f"⚽ Голы: {p['stats_season'].get('goals', 0)} | 🅰️ Ассисты: {p['stats_season'].get('assists', 0)}"
 
    text = (
        f"👑 ПРОФИЛЬ ИГРОКА\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📱 Telegram ID: `{tg_id}`\n"
        f"💾 Полный ID: `{target_id}`\n"
        f"📁 Слот: {slot}\n"
        f"🏃‍♂️ {p['name']} | 🌍 {p.get('nation', 'Россия')} | 🎂 {p.get('age', 17)} лет\n"
        f"⚡️ Рейтинг: {p['rating']}/100\n"
        f"🏢 Клуб: {p['club']} ({p['position']})\n"
        f"💵 Баланс: {p.get('money', 0)}$ | 🏷️ Стоимость: {val:,}$\n"
        f"🏟️ Сезон: {p['season']} | Тур: {p['tour']}/30\n"
        f"🌍 Еврокубки: {get_euro_name(p.get('euro_tournament', 'none'))}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n{stats_text}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Тур (+1)", callback_data=f"adm_tour:{target_id}"),
         InlineKeyboardButton(text="⏭ Сезон (+1)", callback_data=f"adm_season:{target_id}")],
        [InlineKeyboardButton(text="💰 Выдать деньги", callback_data=f"adm_money:{target_id}"),
         InlineKeyboardButton(text="⚡️ Выдать рейтинг", callback_data=f"adm_rating:{target_id}")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
    ])
    
    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await message_or_call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

# ========== ИСПРАВЛЕННАЯ АДМИН-ПАНЕЛЬ (ТУРЫ И СЕЗОНЫ) ==========
@dp.callback_query(F.data.startswith("adm_tour:"))
async def adm_skip_tour(callback: CallbackQuery):
    if not callback.from_user.username or callback.from_user.username.replace("@", "") not in ADMINS:
        return await callback.answer("Ошибка доступа.", show_alert=True)
    target_id = callback.data.split(":")[1]
    async with get_user_lock(target_id):
        players = await load_data(PLAYERS_FILE)
        if target_id in players:
            p = players[target_id]
            p["tour"] += 1
            p["money"] = p.get("money", 0) + p.get("contract_salary", 1500)
            p["train_done"] = False
            
            # СИМУЛИРУЕМ МАТЧ ДЛЯ СТАТИСТИКИ
            played_rivals = p.get("played_league_rivals", [])
            rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"] and c not in played_rivals]
            if not rival_pool:
                rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"]]
                p["played_league_rivals"] = []
            
            rival = random.choice(rival_pool)
            p["played_league_rivals"].append(rival)
            outcome = random.choice(["win", "draw", "loss"])
            
            p["stats_season"]["games"] += 1
            p["stats_total"]["games"] = p["stats_total"].get("games", 0) + 1
            
            # Случайная статистика
            if p["position"] == "ST" or p["position"] == "CM":
                goals = random.randint(0, 2) if outcome != "loss" else 0
                assists = random.randint(0, 1) if outcome != "loss" else 0
                p["stats_season"]["goals"] = p["stats_season"].get("goals", 0) + goals
                p["stats_season"]["assists"] = p["stats_season"].get("assists", 0) + assists
                p["stats_total"]["goals"] = p["stats_total"].get("goals", 0) + goals
                p["stats_total"]["assists"] = p["stats_total"].get("assists", 0) + assists
            elif p["position"] == "CB":
                tackles = random.randint(1, 5)
                goals = random.randint(0, 1) if outcome == "win" else 0
                p["stats_season"]["tackles"] = p["stats_season"].get("tackles", 0) + tackles
                p["stats_season"]["goals"] = p["stats_season"].get("goals", 0) + goals
                p["stats_total"]["tackles"] = p["stats_total"].get("tackles", 0) + tackles
                p["stats_total"]["goals"] = p["stats_total"].get("goals", 0) + goals
            elif p["position"] == "GK":
                saves = random.randint(1, 7)
                p["stats_season"]["saves"] = p["stats_season"].get("saves", 0) + saves
                p["stats_total"]["saves"] = p["stats_total"].get("saves", 0) + saves
            
            # Обновляем таблицу
            players[target_id] = p
            await save_data(PLAYERS_FILE, players)
            await simulate_table_tour(target_id, p["division"], p["club"], rival, outcome)
            
            await show_admin_user_profile(callback, target_id)

@dp.callback_query(F.data.startswith("adm_season:"))
async def adm_skip_season(callback: CallbackQuery):
    if not callback.from_user.username or callback.from_user.username.replace("@", "") not in ADMINS:
        return await callback.answer("Ошибка доступа.", show_alert=True)
    target_id = callback.data.split(":")[1]
    async with get_user_lock(target_id):
        players = await load_data(PLAYERS_FILE)
        if target_id in players:
            p = players[target_id]
            
            # Сезон увеличивается на 1
            p["season"] += 1
            p["tour"] = 1
            p["stats_season"] = {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0}
            p["played_league_rivals"] = []
            p["fatigue"] = max(0, p.get("fatigue", 0) - 30)
            
            # Пересоздаем таблицу для нового сезона
            await init_tables_for_user(target_id, p["division"], p["club"])
            
            players[target_id] = p
            await save_data(PLAYERS_FILE, players)
            
            await show_admin_user_profile(callback, target_id)

@dp.callback_query(F.data.startswith("adm_money:"))
async def adm_money_btn(callback: CallbackQuery, state: FSMContext):
    target_id = callback.data.split(":")[1]
    await state.update_data(adm_target_id=target_id)
    await callback.message.edit_text("💰 Введите сумму долларов для выдачи:", parse_mode="Markdown")
    await state.set_state(AdminPanel.waiting_for_money)

@dp.message(AdminPanel.waiting_for_money)
async def adm_process_money(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("adm_target_id")
    try: amount = int(message.text.strip())
    except: return await message.answer("❌ Число!")
    async with get_user_lock(target_id):
        players = await load_data(PLAYERS_FILE)
        if target_id in players:
            players[target_id]["money"] = players[target_id].get("money", 0) + amount
            await save_data(PLAYERS_FILE, players)
            await show_admin_user_profile(message, target_id)
    await state.clear()

@dp.callback_query(F.data.startswith("adm_rating:"))
async def adm_rating_btn(callback: CallbackQuery, state: FSMContext):
    target_id = callback.data.split(":")[1]
    await state.update_data(adm_target_id=target_id)
    await callback.message.edit_text("⚡️ Введите новый РЕЙТИНГ (1-100):", parse_mode="Markdown")
    await state.set_state(AdminPanel.waiting_for_rating)

@dp.message(AdminPanel.waiting_for_rating)
async def adm_process_rating(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("adm_target_id")
    try: rating = float(message.text.strip())
    except: return await message.answer("❌ Число!")
    async with get_user_lock(target_id):
        players = await load_data(PLAYERS_FILE)
        if target_id in players:
            players[target_id]["rating"] = rating
            await save_data(PLAYERS_FILE, players)
            await show_admin_user_profile(message, target_id)
    await state.clear()

@dp.message(F.text == "/start")
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    
    if not await check_sub(message.from_user.id):
        return await message.answer("❗️ **Для игры необходимо подписаться на нашего спонсора!**\nСначала подпишитесь, а затем нажмите кнопку проверки.", reply_markup=sub_keyboard(), parse_mode="Markdown")
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Слот 1", callback_data="select_slot:1"), InlineKeyboardButton(text="📁 Слот 2", callback_data="select_slot:2")]
    ])
    await message.answer("⚽ **Добро пожаловать в симулятор футболиста!**\nВыбери слот для игры:", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "check_sub_callback")
async def check_sub_handler(callback: CallbackQuery, state: FSMContext):
    if not await check_sub(callback.from_user.id):
        return await callback.answer("❌ Вы не подписались! Подпишитесь и попробуйте снова.", show_alert=True)
    
    await callback.message.delete()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Слот 1", callback_data="select_slot:1"), InlineKeyboardButton(text="📁 Слот 2", callback_data="select_slot:2")]
    ])
    await callback.message.answer("✅ Подписка подтверждена!\n\n⚽ **Добро пожаловать в симулятор футболиста!**\nВыбери слот для игры:", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("select_slot:"))
async def select_slot_handler(callback: CallbackQuery, state: FSMContext):
    slot = callback.data.split(":")[1]
    tg_id = str(callback.from_user.id)
    await set_active_slot(tg_id, slot)
    
    user_id = f"{tg_id}_{slot}"
    players = await load_data(PLAYERS_FILE)
    
    if user_id in players and not players[user_id].get("retired", False):
        players[user_id]["username_tg"] = callback.from_user.username
        await save_data(PLAYERS_FILE, players)
        await callback.message.edit_text(f"👋 **С возвращением, {players[user_id]['name']}!** (Слот {slot})\nТвой ID: `{user_id}`", reply_markup=await main_menu_keyboard(callback.from_user.username, user_id), parse_mode="Markdown")
    else:
        if user_id in players and players[user_id].get("retired", False):
            history = players[user_id].get("career_history", [])
            await state.update_data(career_history=history)
            await callback.message.edit_text(f"⚽ **Твоя прошлая карьера (Слот {slot}) окончена. Начнем новую!**\nДля начала введи Имя и Фамилию:", parse_mode="Markdown")
        else:
            await callback.message.edit_text(f"⚽ **Создаем профиль в Слоте {slot}!**\nДля начала введи Имя и Фамилию:", parse_mode="Markdown")
        await state.set_state(PlayerCreation.waiting_for_name)

@dp.message(PlayerCreation.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=NATIONS[i], callback_data=f"nat:{NATIONS[i]}"),
         InlineKeyboardButton(text=NATIONS[i+1] if i + 1 < len(NATIONS) else NATIONS[i], callback_data=f"nat:{NATIONS[i+1] if i + 1 < len(NATIONS) else NATIONS[i]}")]
        for i in range(0, min(len(NATIONS), 12), 2)
    ])
    await message.answer("🌍 **Выбери свою национальность (основные страны):**", reply_markup=kb, parse_mode="Markdown")
    await state.set_state(PlayerCreation.waiting_for_nation)

@dp.callback_query(PlayerCreation.waiting_for_nation, F.data.startswith("nat:"))
async def process_nation(callback: CallbackQuery, state: FSMContext):
    await state.update_data(nation=callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=pos, callback_data=f"pos:{POSITIONS[pos]}")] for pos in POSITIONS.keys()])
    await callback.message.edit_text("📋 **Выбери амплуа:**", reply_markup=kb, parse_mode="Markdown")
    await state.set_state(PlayerCreation.waiting_for_position)

@dp.callback_query(PlayerCreation.waiting_for_position, F.data.startswith("pos:"))
async def process_position(callback: CallbackQuery, state: FSMContext):
    await state.update_data(position=callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Россия", callback_data="league:Россия"), InlineKeyboardButton(text="🇫🇷 Франция", callback_data="league:Франция")],
        [InlineKeyboardButton(text="🏴󠁧󠁢󠁥󠁮󠁧󠁿 Англия", callback_data="league:Англия"), InlineKeyboardButton(text="🇪🇸 Испания", callback_data="league:Испания")],
        [InlineKeyboardButton(text="🇮🇹 Италия", callback_data="league:Италия"), InlineKeyboardButton(text="🇩🇪 Германия", callback_data="league:Германия")],
        [InlineKeyboardButton(text="🇵🇹 Португалия", callback_data="league:Португалия"), InlineKeyboardButton(text="🇳🇱 Нидерланды", callback_data="league:Нидерланды")],
        [InlineKeyboardButton(text="🇧🇪 Бельгия", callback_data="league:Бельгия"), InlineKeyboardButton(text="🇧🇾 Беларусь", callback_data="league:Беларусь")],
        [InlineKeyboardButton(text="🇹🇷 Турция", callback_data="league:Турция")],
        [InlineKeyboardButton(text="🇰🇿 Казахстан", callback_data="league:Казахстан")]
    ])
    await callback.message.edit_text("🌍 **В какой стране начнешь карьеру?**", reply_markup=kb, parse_mode="Markdown")
    await state.set_state(PlayerCreation.waiting_for_country_league)

@dp.callback_query(PlayerCreation.waiting_for_country_league, F.data.startswith("league:"))
async def process_country_league(callback: CallbackQuery, state: FSMContext):
    league_country = callback.data.split(":")[1]
    if league_country == "Россия": div = "ФНЛ 2"
    elif league_country == "Франция": div = "Насьональ"
    elif league_country == "Англия": div = "Первая лига Англии"
    elif league_country == "Испания": div = "Сегунда"
    elif league_country == "Германия": div = "Вторая Бундеслига"
    elif league_country == "Италия": div = "Серия Б"
    elif league_country == "Португалия": div = "Сегунда лига"
    elif league_country == "Нидерланды": div = "Эрстедивизи"
    elif league_country == "Бельгия": div = "Jupiler Pro League"
    elif league_country == "Беларусь": div = "Беларусь Первая лига"
    elif league_country == "Турция": div = "Турция Первая лига"
    elif league_country == "Казахстан": div = "Казахстан Премьер-лига"
    else: div = "ФНЛ 2"
    
    await state.update_data(start_division=div)
    await callback.message.edit_text("🔢 **Введи номер (1 - 99):**", parse_mode="Markdown")
    await state.set_state(PlayerCreation.waiting_for_number)

@dp.message(PlayerCreation.waiting_for_number)
async def process_number(message: Message, state: FSMContext):
    if not message.text.isdigit() or not (1 <= int(message.text) <= 99):
        return await message.answer("🚫 Выбери номер от 1 до 99:")
    
    await state.update_data(number=int(message.text))
    user_data = await state.get_data()
    start_div = user_data["start_division"]
    
    available_clubs = random.sample(CLUBS[start_div], 3)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🏢 {club}", callback_data=f"club:{club}")] for club in available_clubs])
    await message.answer(f"📉 Тобой интересуются клубы из лиги: **{start_div}**. Где начнешь?", reply_markup=kb, parse_mode="Markdown")
    await state.set_state(PlayerCreation.waiting_for_club)

@dp.callback_query(PlayerCreation.waiting_for_club, F.data.startswith("club:"))
@with_user_lock
async def process_club(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    user_id = await get_uid(callback)
    chosen_club = callback.data.split(":")[1]
    
    player_profile = {
        "name": user_data["name"],
        "nation": user_data.get("nation", "Россия"),
        "position": user_data["position"],
        "number": user_data["number"],
        "club": chosen_club,
        "division": get_division(chosen_club),
        "rating": 40.0,
        "trust": 15,
        "fatigue": 0,
        "girlfriend": "Нет",
        "age": 17,
        "season": 1,
        "tour": 1,
        "money": 5000,
        "contract_salary": 1500,
        "sponsor": None,
        "on_loan": False,
        "parent_club": None,
        "loan_tours_left": 0,
        "cup_out": False,
        "cup_stage": "1/16",
        "cup_rivals": [],
        "played_league_rivals": [],
        "trophies": [],
        "stats_season": {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0},
        "stats_total": {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0},
        "completed_quests": [],
        "train_done": False,
        "train_streak": 0,
        "train_count": 0,
        "train_tech_count": 0,
        "train_phys_count": 0,
        "train_special_count": 0,
        "train_achievements": [],
        "is_injured": False,
        "injury_tours": 0,
        "username_tg": callback.from_user.username,
        "career_history": user_data.get("career_history", []),
        "retired": False,
        "activity_minutes": 0,
        "activity_week": datetime.now().isocalendar()[1],
        "reputation": 50,
        "motivation": 50,
        "married": False,
        "children": 0,
        "wife_loyalty": 0,
        "business": None,
        "business_crisis": False,
        "business_crisis_timer": 0,
        "car": None,
        "has_yoga_bonus": False,
        "last_interview_tour": 0,
        "rating_performance": 0,
        "age_penalty_applied": False,
        "euro_tournament": None,
        "euro_goals": 0,
        "euro_assists": 0,
        "euro_matches": 0,
        "euro_playoff_stage": None
    }
    
    players = await load_data(PLAYERS_FILE)
    players[user_id] = player_profile
    await save_data(PLAYERS_FILE, players)
    await init_tables_for_user(user_id, player_profile["division"], player_profile["club"])
    
    await state.clear()
    await callback.message.edit_text(f"✍️ **КОНТРАКТ ПОДПИСАН!** Добро пожаловать в {player_profile['club']}!\n💰 Твоя зарплата: {player_profile['contract_salary']}$ за матч.", parse_mode="Markdown", reply_markup=await main_menu_keyboard(callback.from_user.username, user_id))

@dp.callback_query(F.data == "start_new_career")
@with_user_lock
async def start_new_career_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Слот 1", callback_data="select_slot:1"), 
         InlineKeyboardButton(text="📁 Слот 2", callback_data="select_slot:2")]
    ])
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(
            "⚽ **Добро пожаловать в симулятор футболиста!**\nВыбери слот для игры:",
            reply_markup=kb,
            parse_mode="Markdown"
        )
    else:
        try:
            await callback.message.edit_text(
                "⚽ **Добро пожаловать в симулятор футболиста!**\nВыбери слот для игры:",
                reply_markup=kb,
                parse_mode="Markdown"
            )
        except Exception:
            await callback.message.answer(
                "⚽ **Добро пожаловать в симулятор футболиста!**\nВыбери слот для игры:",
                reply_markup=kb,
                parse_mode="Markdown"
            )

@dp.callback_query(F.data == "delete_career")
@with_user_lock
async def delete_career_confirm(callback: CallbackQuery):
    user_id = await get_uid(callback)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data="delete_career_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(
        "🗑 **Вы уверены, что хотите удалить свою карьеру?**\nЭто действие необратимо!",
        parse_mode="Markdown", reply_markup=kb
    )

@dp.callback_query(F.data == "delete_career_yes")
@with_user_lock
async def delete_career_final(callback: CallbackQuery, state: FSMContext):
    players = await load_data(PLAYERS_FILE)
    user_id = await get_uid(callback)
    if user_id in players:
        del players[user_id]
        await save_data(PLAYERS_FILE, players)
    
    await state.clear()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Слот 1", callback_data="select_slot:1"), 
         InlineKeyboardButton(text="📁 Слот 2", callback_data="select_slot:2")]
    ])
    await callback.message.edit_text(
        "🗑 **Карьера удалена!**\n\n⚽ **Выбери слот для новой игры:**",
        reply_markup=kb,
        parse_mode="Markdown"
    )

# ========== ТРЕНИРОВКИ ==========

@dp.callback_query(F.data == "menu_train_choice")
@with_user_lock
async def train_choice_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    await track_activity(user_id)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if await deny_if_retired_cb(callback, p): return
    
    if p.get("injury_tours", 0) > 0:
        return await callback.answer(f"🚑 Вы травмированы! Осталось лечиться туров: {p['injury_tours']}.", show_alert=True)
    
    if p.get("train_done", False):
        return await callback.answer("🚫 Сыграй матч, чтобы открыть тренировку.", show_alert=True)
    
    fatigue = p.get("fatigue", 0)
    if fatigue >= 70:
        return await callback.answer(
            f"🚫 Ты слишком устал! Усталость: {fatigue}%\nСходи в ресторан или отдохни в личной жизни!",
            show_alert=True
        )
    
    cost = get_train_cost(p.get("rating", 40))
    if p.get("money", 0) < cost:
        return await callback.answer(f"❌ Не хватает денег! Нужно {cost}$, у тебя {p.get('money', 0)}$", show_alert=True)
    
    position = p.get("position", "ST")
    config = TRAINING_CONFIG.get(position, TRAINING_CONFIG["ST"])
    
    streak = p.get("train_streak", 0)
    streak_bonus = get_streak_bonus(streak)
    train_count = p.get("train_count", 0)
    
    fatigue_status = "✅ (можно тренироваться)" if fatigue < 70 else "❌ (отдохни!)"
    
    text = (
        f"🏋️‍♂️ **ТРЕНИРОВКА**\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Рейтинг: **{p['rating']}**\n"
        f"🔋 Усталость: **{fatigue}%** {fatigue_status}\n"
        f"🔥 Серия: **{streak}** тренировок подряд\n"
        f"💪 Бонус за серию: **+{streak_bonus}**\n"
        f"💰 Стоимость: **{cost}$**\n"
        f"📈 Всего тренировок: **{train_count}**\n\n"
        f"**Выбери направление:**"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎯 {config['tech']['name']}", callback_data="train:tech")],
        [InlineKeyboardButton(text=f"🏃 {config['phys']['name']}", callback_data="train:phys")],
        [InlineKeyboardButton(text=f"⭐ {config['special']['name']}", callback_data="train:special")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("train:"))
@with_user_lock
async def train_execute_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if await deny_if_retired_cb(callback, p): return
    
    train_type = callback.data.split(":")[1]
    
    if p.get("injury_tours", 0) > 0:
        return await callback.answer("🚑 Вы травмированы! Тренировка недоступна.", show_alert=True)
    
    if p.get("train_done", False):
        return await callback.answer("🚫 Сыграй матч, чтобы открыть тренировку.", show_alert=True)
    
    fatigue = p.get("fatigue", 0)
    if fatigue >= 70:
        return await callback.answer(f"🚫 Ты слишком устал! Усталость: {fatigue}%", show_alert=True)
    
    cost = get_train_cost(p.get("rating", 40))
    if p.get("money", 0) < cost:
        return await callback.answer(f"❌ Не хватает денег! Нужно {cost}$", show_alert=True)
    
    position = p.get("position", "ST")
    config = TRAINING_CONFIG.get(position, TRAINING_CONFIG["ST"])
    train_data = config.get(train_type, config["tech"])
    
    gain = train_data["base_gain"]
    
    streak = p.get("train_streak", 0)
    streak_bonus = get_streak_bonus(streak)
    total_gain = gain + streak_bonus
    
    golden = False
    if random.random() < 0.05:
        total_gain *= 2
        golden = True
    
    failed = False
    if random.random() < 0.03:
        total_gain = -0.2
        failed = True
    
    inspiration = False
    if random.random() < 0.08:
        inspiration = True
    
    injury_chance = 0.02 + (fatigue / 100) * 0.05
    injured = False
    injury_tours = 0
    
    if random.random() < injury_chance:
        injured = True
        injury_tours = random.randint(1, 3)
        p["injury_tours"] = injury_tours
        p["is_injured"] = True
        total_gain -= 0.5
    
    p["train_done"] = True
    p["fatigue"] = min(100, p.get("fatigue", 0) + train_data["fatigue"])
    p["money"] -= cost
    p["train_streak"] = streak + 1
    p["train_count"] = p.get("train_count", 0) + 1
    p["trust"] = min(100, p.get("trust", 15) + 3)
    
    p[f"train_{train_type}_count"] = p.get(f"train_{train_type}_count", 0) + 1
    
    if inspiration:
        p["fatigue"] = max(0, p["fatigue"] - 5)
    
    if not injured:
        p["rating"] = max(1.0, min(100.0, round(p["rating"] + total_gain, 1)))
    else:
        p["rating"] = max(1.0, min(100.0, round(p["rating"] + total_gain, 1)))
    
    new_achievements, ach_reward = check_train_achievements(
        p, 
        p.get("train_count", 0), 
        p.get("train_streak", 0)
    )
    
    if new_achievements:
        p["rating"] += ach_reward
        train_achievements = p.get("train_achievements", [])
        for ach in new_achievements:
            for key, val in TRAIN_ACHIEVEMENTS.items():
                if val["name"] == ach["name"] and key not in train_achievements:
                    train_achievements.append(key)
                    break
        p["train_achievements"] = train_achievements
    
    p["reputation"] = min(100, p.get("reputation", 50) + 0.5)
    
    players[user_id] = p
    await save_data(PLAYERS_FILE, players)
    await callback.message.delete()
    
    msg_lines = ["💪 **ТРЕНИРОВКА ЗАВЕРШЕНА!**", "━━━━━━━━━━━━━━━━━━━━"]
    msg_lines.append(f"📋 Направление: **{train_data['name']}**")
    
    if failed:
        msg_lines.append(f"😞 **ПРОВАЛ!** Рейтинг -0.2")
    elif injured:
        msg_lines.append(f"🚑 **ТРАВМА!** Выбытие на {injury_tours} тур(а)")
        msg_lines.append(f"📉 Рейтинг: -0.5 (штраф за травму)")
    else:
        msg_lines.append(f"📈 Прирост: +{gain}")
        if streak_bonus > 0:
            msg_lines.append(f"🔥 Бонус серии ({streak}): +{streak_bonus}")
        if golden:
            msg_lines.append(f"🌟 **ЗОЛОТАЯ ТРЕНИРОВКА! x2**")
        if inspiration:
            msg_lines.append(f"💡 Вдохновение! Усталость -5%")
    
    msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
    msg_lines.append(f"⚡ Рейтинг: **{p['rating']}**")
    msg_lines.append(f"❤️ Доверие: **{p['trust']}**")
    msg_lines.append(f"🔋 Усталость: **{p['fatigue']}%**")
    msg_lines.append(f"💰 Потрачено: **{cost}$**")
    msg_lines.append(f"💵 Баланс: **{p['money']}$**")
    msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
    msg_lines.append(f"🔥 Серия: **{p['train_streak']}** тренировок подряд")
    
    if new_achievements:
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append("🎉 **НОВЫЕ ДОСТИЖЕНИЯ!**")
        for ach in new_achievements:
            msg_lines.append(f"🏅 {ach['name']} (+{ach['reward']})")
    
    if injured:
        msg_lines.append("\n⏳ Ты пропустишь матчи до восстановления!")
    
    await callback.message.answer(
        text="\n".join(msg_lines), 
        parse_mode="Markdown", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Меню", callback_data="back_to_menu")]])
    )

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_handler(callback: CallbackQuery):
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer("🏠 Главное меню.", reply_markup=await main_menu_keyboard(callback.from_user.username, await get_uid(callback)))
    else:
        try:
            await callback.message.edit_text("🏠 Главное меню.", reply_markup=await main_menu_keyboard(callback.from_user.username, await get_uid(callback)))
        except Exception:
            await callback.message.answer("🏠 Главное меню.", reply_markup=await main_menu_keyboard(callback.from_user.username, await get_uid(callback)))

@dp.callback_query(F.data == "menu_table")
@with_user_lock
async def show_table_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    await track_activity(user_id)
    tables = await load_data(TABLES_FILE)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if await deny_if_retired_cb(callback, p): return

    if user_id not in tables or p["division"] not in tables[user_id]: 
        await init_tables_for_user(user_id, p["division"], p["club"])
        tables = await load_data(TABLES_FILE)
        
    table_data = tables[user_id][p["division"]]
    
    text = f"📊 **ТАБЛИЦА: {p['division']}**\n🏆 *Победа — 3 очка, Ничья — 1 очко, Поражение — 0*\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, row in enumerate(table_data, 1):
        is_p = "👉 " if row["club"] == p["club"] else "• "
        text += f"{i}. {is_p}**{row['club']}** — {row['points']} очков ({row['wins']}В / {row['draws']}Н / {row['losses']}П)\n"
        
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=await main_menu_keyboard(callback.from_user.username, user_id))
    else:
        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=await main_menu_keyboard(callback.from_user.username, user_id))
        except Exception:
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=await main_menu_keyboard(callback.from_user.username, user_id))

@dp.callback_query(F.data == "menu_profile")
@with_user_lock
async def profile_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    await track_activity(user_id)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if not p:
        await callback.message.answer("⚠️ Профиль не найден. Нажми /start, чтобы начать.", parse_mode="Markdown")
        return
 
    if p.get("retired"):
        history_str = "\n\n".join(p.get("career_history", [])) or "—"
        text = (
            f"🏁 **КАРЬЕРА ЗАВЕРШЕНА**\n━━━━━━━━━━━━━━━━━━━━\n"
            f"🏃‍♂️ {p['name']} | 🌍 {p.get('nation', 'Россия')}\n\n"
            f"📚 **Завершенные карьеры (Статистика):**\n{history_str}\n\n"
            f"Нажми кнопку ниже, чтобы начать новую историю."
        )
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=retired_keyboard())
        else:
            try:
                await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=retired_keyboard())
            except Exception:
                await callback.message.answer(text, parse_mode="Markdown", reply_markup=retired_keyboard())
        return
 
    val = calculate_player_value(p["rating"], p["division"])
    
    loan_status = f"\n⚠️ *В аренде из {p['parent_club']}* (Осталось: {p['loan_tours_left']} тур.)" if p.get("on_loan") else ""
    injury_status = f"\n🚑 *Травмирован!* (Лечиться еще: {p.get('injury_tours', 0)} тур.)" if p.get("injury_tours", 0) > 0 else ""
    
    if p["position"] == "GK": stats_text = f"🧤 Сейвы: {p['stats_season'].get('saves', 0)}"
    elif p["position"] == "CB": stats_text = f"🛡️ Отборы: {p['stats_season'].get('tackles', 0)} | ⚽ Голы: {p['stats_season'].get('goals', 0)}"
    else: stats_text = f"⚽ Голы: {p['stats_season'].get('goals', 0)} | 🅰️ Ассисты: {p['stats_season'].get('assists', 0)}"
    
    history_str = ""
    if p.get("career_history"):
        history_str = "\n\n📚 **Прошлые карьеры:**\n" + "\n\n".join(p["career_history"])
 
    season_display = min(p['season'], 13) 
    tour_display = min(p['tour'], 30)
 
    kb = await main_menu_keyboard(callback.from_user.username, user_id)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🗑 Удалить карьеру", callback_data="delete_career")])

    train_stats = (
        f"\n📊 **Тренировки:**\n"
        f"🔥 Серия: {p.get('train_streak', 0)}\n"
        f"📈 Всего: {p.get('train_count', 0)}\n"
        f"🎯 Техника: {p.get('train_tech_count', 0)} раз\n"
        f"🏃 Физика: {p.get('train_phys_count', 0)} раз\n"
        f"⭐ Специальная: {p.get('train_special_count', 0)} раз\n"
        f"🏅 Достижений: {len(p.get('train_achievements', []))}"
    )

    euro_stats = ""
    if p.get("euro_tournament") and p.get("euro_tournament") != "none":
        euro_stats = (
            f"\n🌍 **Еврокубки:** {get_euro_name(p['euro_tournament'])}\n"
            f"📈 Матчей: {p.get('euro_matches', 0)} | ⚽ Голов: {p.get('euro_goals', 0)} | 🅰️ Ассистов: {p.get('euro_assists', 0)}"
        )

    text = (
        f"👑 ПРОФИЛЬ ИГРОКА\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🏃‍♂️ {p['name']} | 🌍 {p.get('nation', 'Россия')} | 🎂 {p.get('age', 17)} лет\n"
        f"⚡️ Рейтинг: {p['rating']}/100\n"
        f"🏢 Клуб: {p['club']} ({p['position']}){loan_status}{injury_status}\n"
        f"💵 Баланс: {p.get('money', 0)}$ | 🏷️ Стоимость: {val:,}$\n"
        f"🤝 Зарплата: {p.get('contract_salary', 0)}$/матч\n"
        f"💎 Спонсор: {p.get('sponsor', 'Нет')}\n"
        f"📊 Статус: {get_status_by_trust(p['trust'])}\n"
        f"🔋 Усталость: {p.get('fatigue', 0)}%\n"
        f"💍 Девушка: {p.get('girlfriend', 'Нет')}\n"
        f"🏟️ Сезон: {season_display}/13 | Тур Лиги: {tour_display}/30\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 **Текущая карьера (за сезон):**\n{stats_text}\n"
        f"📈 **Общая статистика (текущий игрок):**\nВсего игр: {p.get('stats_total', {}).get('games', 0)} | Голов: {p.get('stats_total', {}).get('goals', 0)} | Ассистов: {p.get('stats_total', {}).get('assists', 0)}"
        f"{euro_stats}{train_stats}{history_str}"
    )
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb)
    else:
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except Exception:
            await callback.message.answer(text, reply_markup=kb)

# ========== ИСПРАВЛЕННЫЙ ПЕРЕХОД В КЛУБ (С ГЕНЕРАЦИЕЙ ТАБЛИЦЫ) ==========
@dp.callback_query(F.data.startswith("scandal_club:"))
@with_user_lock
async def scandal_club_choice_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if await deny_if_retired_cb(callback, p): return
    new_club = callback.data.split(":")[1]
    
    old_division = p.get("division")
    p["club"] = new_club
    p["division"] = get_division(new_club)
    p["trust"] = 15
    
    base_salaries = {
        "ФНЛ 2": 1500, "Насьональ": 1500, "Первая лига Англии": 1800,
        "ФНЛ": 6000, "Лига 2": 6000, "Чемпионшип": 8000, "Сегунда": 8000, "Серия Б": 8000, "Вторая Бундеслига": 7500,
        "РПЛ": 30000, "Лига 1": 30000, "АПЛ": 50000, "Ла Лига": 50000, "Серия А": 45000, "Бундеслига": 48000,
        "Примейра": 35000, "Сегунда лига": 7500,
        "Бразильская Серия А": 30000,
        "Эрстедивизи": 7500, "Эредивизи": 35000,
        "Jupiler Pro League": 35000,
        "Беларусь Первая лига": 2000,
        "Беларусь Высшая лига": 5000,
        "Турция Первая лига": 3000,
        "Турция Суперлига": 25000,
        "Казахстан Премьер-лига": 25000
    }
    p["contract_salary"] = int(base_salaries.get(p["division"], 1500) * (p["rating"] / 45))
    
    # Сбрасываем сыгранных соперников
    p["played_league_rivals"] = []
    
    players[user_id] = p
    await save_data(PLAYERS_FILE, players)

    # Генерируем таблицу для нового клуба с нуля
    await init_tables_for_user(user_id, p["division"], p["club"])
    
    # Проверяем, участвует ли новый клуб в еврокубках
    euro_data = await load_data(EURO_FILE)
    if euro_data and euro_data.get("status") == "group":
        tournament = None
        for t in ["champions_league", "europa_league", "conference_league"]:
            if p["club"] in euro_data[t]["clubs"]:
                tournament = t
                break
        
        if tournament:
            p["euro_tournament"] = tournament
        else:
            p["euro_tournament"] = "none"
    
    players[user_id] = p
    await save_data(PLAYERS_FILE, players)
    
    await callback.message.delete()
    await callback.message.answer(
        text=f"✍️ Ты успешно перешел в **{new_club}**!\n💵 Твоя новая зарплата: **{p['contract_salary']}$/матч**.\n📊 Таблица для новой лиги создана!\nПора доказывать фанатам свою преданность!",
        parse_mode="Markdown", reply_markup=await main_menu_keyboard(callback.from_user.username, user_id)
    )

# ========== ИСПРАВЛЕННЫЙ match_handler (БАГ С ПРЕДЛОЖЕНИЯМИ) ==========

@dp.callback_query(F.data == "menu_match")
@with_user_lock
async def match_handler(callback: CallbackQuery, state: FSMContext):
    if not await check_sub(callback.from_user.id):
        return await callback.message.answer("❗️ **Для игры необходимо подписаться на нашего спонсора!**\nСначала подпишитесь, а затем продолжите игру.", reply_markup=sub_keyboard(), parse_mode="Markdown")

    user_id = await get_uid(callback)
    
    await heal_injury_if_needed(user_id)
    
    await track_activity(user_id)
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if await deny_if_retired_cb(callback, p): return
    
    if p.get("train_done", False) == False:
        if p.get("train_streak", 0) > 0:
            p["train_streak"] = 0
            players[user_id] = p
            await save_data(PLAYERS_FILE, players)
            await send_auto_delete_message(
                callback.message,
                "⚠️ **СЕРИЯ ПРЕРВАНА!**\n"
                "Ты сыграл матч, но не потренировался.\n"
                "🔥 Серия тренировок сброшена до 0!",
                delay=3
            )
    
    trust = p.get("trust", 15)
    status = get_status_by_trust(trust)
    
    if trust < 21:
        p["tour"] += 1
        p["money"] = p.get("money", 0) + p.get("contract_salary", 1500)
        p["train_done"] = False
        p["fatigue"] = max(0, p.get("fatigue", 0) - 10)
        
        played_rivals = p.get("played_league_rivals", [])
        rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"] and c not in played_rivals]
        if not rival_pool:
            rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"]]
            p["played_league_rivals"] = []
        
        rival = random.choice(rival_pool)
        p["played_league_rivals"].append(rival)
        outcome = random.choice(["win", "draw", "loss"])
        
        p["stats_season"]["games"] += 1
        
        players[user_id] = p
        await save_data(PLAYERS_FILE, players)
        await simulate_table_tour(user_id, p["division"], p["club"], rival, outcome)
        
        if callback.message.photo:
            await callback.message.delete()
        
        await send_auto_delete_message(
            callback.message,
            f"🪑 **ТЫ В РЕЗЕРВЕ!**\n"
            f"Ты не попал в состав на матч против **{rival}**.\n"
            f"📊 Статус: {status}\n"
            f"💡 Подними доверие (trust) до 21, чтобы играть!\n"
            f"🔹 Итог матча: **{'Победа' if outcome=='win' else 'Ничья' if outcome=='draw' else 'Поражение'}**",
            delay=3
        )
        return
    
    if p.get("injury_tours", 0) > 0:
        p["tour"] += 1
        p["money"] = p.get("money", 0) + p.get("contract_salary", 1500)
        p["train_done"] = False
        p["fatigue"] = max(0, p.get("fatigue", 0) - 10)
        
        played_rivals = p.get("played_league_rivals", [])
        rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"] and c not in played_rivals]
        if not rival_pool:
            rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"]]
            p["played_league_rivals"] = []
        
        rival = random.choice(rival_pool)
        p["played_league_rivals"].append(rival)
        outcome = random.choice(["win", "draw", "loss"])
        
        p["stats_season"]["games"] += 1
        
        players[user_id] = p
        await save_data(PLAYERS_FILE, players)
        await simulate_table_tour(user_id, p["division"], p["club"], rival, outcome)
        
        if callback.message.photo:
            await callback.message.delete()
        
        msg = f"🚑 **ТЫ ПРОПУСТИЛ ТУР ИЗ-ЗА ТРАВМЫ**\nКоманда сыграла против **{rival}**. Итог: **{'Победа' if outcome=='win' else 'Ничья' if outcome=='draw' else 'Поражение'}**.\n"
        if p["injury_tours"] > 0:
            msg += f"⏳ Осталось лечиться: {p['injury_tours']} тур(а)."
        else:
            msg += "✅ **Ты полностью восстановился и готов к следующему матчу!**"
        
        await send_auto_delete_message(callback.message, msg, delay=3)
        return
    
    if p.get("fatigue", 0) >= 95:
        return await callback.answer("🚫 Ты смертельно устал! Сходи в ресторан.", show_alert=True)
    
    current_rating = p.get("rating", 40)
    
    if trust < 51:
        total_moments = random.randint(1, 2)
        await send_auto_delete_message(
            callback.message,
            f"🔄 **ТЫ НА ЗАМЕНЕ!**\n"
            f"Ты выйдешь на поле во втором тайме.\n"
            f"📊 Статус: {status}\n"
            f"💡 Играй лучше, чтобы попасть в старт!",
            delay=3
        )
    else:
        total_moments = random.randint(2, 4)
    
    # ========== ИСПРАВЛЕН БАГ С ПРЕДЛОЖЕНИЯМИ (ТОЛЬКО 1 РАЗ) ==========
    offer_made = False
    
    # Предложения из Германии (только 1 раз)
    if not offer_made and p["division"] not in ["Бундеслига", "Вторая Бундеслига"] and random.random() < 0.10:
        if current_rating >= 74:
            ger_offers = random.sample(CLUBS["Бундеслига"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇩🇪 {c}", callback_data=f"scandal_club:{c}")] for c in ger_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            offer_made = True
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** Твой высокий рейтинг ({current_rating}) привлек внимание клубов из Германии! Тебе предлагают контракт в **Бундеслиге**:",
                reply_markup=kb, parse_mode="Markdown"
            )
        elif current_rating >= 55:
            ger_offers = random.sample(CLUBS["Вторая Бундеслига"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇩🇪 {c}", callback_data=f"scandal_club:{c}")] for c in ger_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            offer_made = True
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** На основе твоего рейтинга ({current_rating}) команды из Германии предлагают тебе контракт во **Второй Бундеслиге**:",
                reply_markup=kb, parse_mode="Markdown"
            )

    # Предложения из Португалии (только 1 раз)
    if not offer_made and p["division"] not in ["Примейра", "Сегунда лига"] and random.random() < 0.10:
        if current_rating >= 74:
            pt_offers = random.sample(CLUBS["Примейра"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇵🇹 {c}", callback_data=f"scandal_club:{c}")] for c in pt_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            offer_made = True
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** Твой высокий рейтинг ({current_rating}) привлек внимание клубов из Португалии! Тебе предлагают контракт в **Примейре**:",
                reply_markup=kb, parse_mode="Markdown"
            )
        elif current_rating >= 55:
            pt_offers = random.sample(CLUBS["Сегунда лига"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇵🇹 {c}", callback_data=f"scandal_club:{c}")] for c in pt_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            offer_made = True
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** На основе твоего рейтинга ({current_rating}) команды из Португалии предлагают тебе контракт в **Сегунда лиге**:",
                reply_markup=kb, parse_mode="Markdown"
            )

    # Предложения из Бразилии (только 1 раз)
    if not offer_made and p["division"] not in ["Бразильская Серия А"] and random.random() < 0.10:
        if current_rating >= 74:
            br_offers = random.sample(CLUBS["Бразильская Серия А"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇧🇷 {c}", callback_data=f"scandal_club:{c}")] for c in br_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            offer_made = True
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** Твой высокий рейтинг ({current_rating}) привлек внимание клубов из Бразилии! Тебе предлагают контракт в **Бразильской Серии А**:",
                reply_markup=kb, parse_mode="Markdown"
            )

    # Предложения из Нидерландов (только 1 раз)
    if not offer_made and p["division"] not in ["Эредивизи", "Эрстедивизи"] and random.random() < 0.10:
        if current_rating >= 74:
            nl_offers = random.sample(CLUBS["Эредивизи"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇳🇱 {c}", callback_data=f"scandal_club:{c}")] for c in nl_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            offer_made = True
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** Твой высокий рейтинг ({current_rating}) привлек внимание клубов из Нидерландов! Тебе предлагают контракт в **Эредивизи**:",
                reply_markup=kb, parse_mode="Markdown"
            )
        elif current_rating >= 55:
            nl_offers = random.sample(CLUBS["Эрстедивизи"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇳🇱 {c}", callback_data=f"scandal_club:{c}")] for c in nl_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            offer_made = True
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** На основе твоего рейтинга ({current_rating}) команды из Нидерландов предлагают тебе контракт в **Эрстедивизи**:",
                reply_markup=kb, parse_mode="Markdown"
            )

    # Предложения из Бельгии (только 1 раз)
    if not offer_made and p["division"] not in ["Jupiler Pro League"] and random.random() < 0.10:
        if current_rating >= 74:
            be_offers = random.sample(CLUBS["Jupiler Pro League"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇧🇪 {c}", callback_data=f"scandal_club:{c}")] for c in be_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            offer_made = True
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** Твой высокий рейтинг ({current_rating}) привлек внимание клубов из Бельгии! Тебе предлагают контракт в **Jupiler Pro League**:",
                reply_markup=kb, parse_mode="Markdown"
            )

    # Предложения из Беларуси (только 1 раз)
    if not offer_made and p["division"] not in ["Беларусь Высшая лига"] and random.random() < 0.10:
        if current_rating >= 65:
            by_offers = random.sample(CLUBS["Беларусь Высшая лига"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇧🇾 {c}", callback_data=f"scandal_club:{c}")] for c in by_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            offer_made = True
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** Твой рейтинг ({current_rating}) привлек внимание клубов из Беларуси! Тебе предлагают контракт в **Высшей лиге**:",
                reply_markup=kb, parse_mode="Markdown"
            )

    # Предложения из Турции (только 1 раз)
    if not offer_made and p["division"] not in ["Турция Суперлига"] and random.random() < 0.10:
        if current_rating >= 68:
            tr_offers = random.sample(CLUBS["Турция Суперлига"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇹🇷 {c}", callback_data=f"scandal_club:{c}")] for c in tr_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            offer_made = True
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** Твой рейтинг ({current_rating}) привлек внимание клубов из Турции! Тебе предлагают контракт в **Суперлиге**:",
                reply_markup=kb, parse_mode="Markdown"
            )

    # Предложения из Казахстана (только 1 раз)
    if not offer_made and p["division"] not in ["Казахстан Премьер-лига"] and random.random() < 0.10:
        if current_rating >= 55:
            kz_offers = random.sample(CLUBS["Казахстан Премьер-лига"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇰🇿 {c}", callback_data=f"scandal_club:{c}")] for c in kz_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            offer_made = True
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** Твой рейтинг ({current_rating}) привлек внимание клубов из Казахстана! Тебе предлагают контракт в **Премьер-лиге**:",
                reply_markup=kb, parse_mode="Markdown"
            )

    if p["tour"] > 30:
        return await season_results_handler(callback)
    
    # ========== ОСТАЛЬНАЯ ЧАСТЬ МАТЧА (БЕЗ ИЗМЕНЕНИЙ) ==========
    if random.random() < 0.01:
        div_clubs = [c for c in CLUBS[p["division"]] if c != p["club"]]
        available_clubs = random.sample(div_clubs, min(len(div_clubs), 2))
        
        top_leagues = ["РПЛ", "Лига 1", "АПЛ", "Ла Лига", "Серия А", "Бундеслига", "Примейра", "Бразильская Серия А", "Эредивизи", "Jupiler Pro League", "Беларусь Высшая лига", "Турция Суперлига", "Казахстан Премьер-лига"]
        my_top_league = "РПЛ"
        if p["division"] in ["Насьональ", "Лига 2", "Лига 1"]: my_top_league = "Лига 1"
        elif p["division"] in ["Первая лига Англии", "Чемпионшип", "АПЛ"]: my_top_league = "АПЛ"
        elif p["division"] in ["Сегунда", "Ла Лига"]: my_top_league = "Ла Лига"
        elif p["division"] in ["Серия Б", "Серия А"]: my_top_league = "Серия А"
        elif p["division"] in ["Вторая Бундеслига", "Бундеслига"]: my_top_league = "Бундеслига"
        elif p["division"] in ["Сегунда лига", "Примейра"]: my_top_league = "Примейра"
        elif p["division"] in ["Бразильская Серия А"]: my_top_league = "Бразильская Серия А"
        elif p["division"] in ["Эрстедивизи", "Эредивизи"]: my_top_league = "Эредивизи"
        elif p["division"] in ["Jupiler Pro League"]: my_top_league = "Jupiler Pro League"
        elif p["division"] in ["Беларусь Первая лига", "Беларусь Высшая лига"]: my_top_league = "Беларусь Высшая лига"
        elif p["division"] in ["Турция Первая лига", "Турция Суперлига"]: my_top_league = "Турция Суперлига"
        elif p["division"] in ["Казахстан Премьер-лига"]: my_top_league = "Казахстан Премьер-лига"
        
        alt_leagues = [l for l in top_leagues if l != my_top_league]
        alt_league = random.choice(alt_leagues) if alt_leagues else "РПЛ"
        available_clubs.append(random.choice(CLUBS[alt_league]))
        random.shuffle(available_clubs)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[[InlineKeyboardButton(text=f"🏢 {club}", callback_data=f"scandal_club:{club}")] for club in available_clubs]])
        
        await callback.message.delete()
        return await callback.message.answer(
            text=f"🤬 **СКАНДАЛ С РУКОВОДСТВОМ!** Твой контракт с {p['club']} разорван.\nИнтерес к тебе проявили клубы. Выбери новую команду:",
            reply_markup=kb, parse_mode="Markdown"
        )
        
    p["stats_season"]["games"] += 1
    p["fatigue"] = min(100, p.get("fatigue", 0) + 15)
    
    cup_stg = p.get("cup_stage", "1/16")
    is_cup_match = (not p.get("cup_out", False)) and (cup_stg in CUP_STAGES) and random.random() < 0.20
    
    if is_cup_match:
        country_leagues = []
        if p["division"] in ["ФНЛ 2", "ФНЛ", "РПЛ"]: country_leagues = ["ФНЛ 2", "ФНЛ", "РПЛ"]
        elif p["division"] in ["Насьональ", "Лига 2", "Лига 1"]: country_leagues = ["Насьональ", "Лига 2", "Лига 1"]
        elif p["division"] in ["Первая лига Англии", "Чемпионшип", "АПЛ"]: country_leagues = ["Первая лига Англии", "Чемпионшип", "АПЛ"]
        elif p["division"] in ["Сегунда", "Ла Лига"]: country_leagues = ["Сегунда", "Ла Лига"]
        elif p["division"] in ["Серия Б", "Серия А"]: country_leagues = ["Серия Б", "Серия А"]
        elif p["division"] in ["Вторая Бундеслига", "Бундеслига"]: country_leagues = ["Вторая Бундеслига", "Бундеслига"]
        elif p["division"] in ["Сегунда лига", "Примейра"]: country_leagues = ["Сегунда лига", "Примейра"]
        elif p["division"] in ["Бразильская Серия А"]: country_leagues = ["Бразильская Серия А"]
        elif p["division"] in ["Эрстедивизи", "Эредивизи"]: country_leagues = ["Эрстедивизи", "Эредивизи"]
        elif p["division"] in ["Jupiler Pro League"]: country_leagues = ["Jupiler Pro League"]
        elif p["division"] in ["Беларусь Первая лига", "Беларусь Высшая лига"]: country_leagues = ["Беларусь Первая лига", "Беларусь Высшая лига"]
        elif p["division"] in ["Турция Первая лига", "Турция Суперлига"]: country_leagues = ["Турция Первая лига", "Турция Суперлига"]
        elif p["division"] in ["Казахстан Премьер-лига"]: country_leagues = ["Казахстан Премьер-лига"]
        
        rival_pool = []
        for l in country_leagues:
            rival_pool.extend(CLUBS[l])
            
        played_cup_rivals = p.get("cup_rivals", [])
        rival_pool = [c for c in rival_pool if c != p["club"] and c not in played_cup_rivals]
        
        if not rival_pool:
            rival_pool = ["Случайная команда"]
    else:
        played_rivals = p.get("played_league_rivals", [])
        rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"] and c not in played_rivals]
        
        if not rival_pool: 
            rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"]]
            p["played_league_rivals"] = []
            
        players[user_id] = p
        await save_data(PLAYERS_FILE, players)
        
    match_data = {
        "rival": random.choice(rival_pool),
        "total_moments": total_moments,
        "current_moment": 1,
        "minute": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0, "yellow_cards": 0,
        "my_team_score": 0, "rival_team_score": 0,
        "is_cup": is_cup_match, "cup_stage": cup_stg if is_cup_match else None,
        "log": ""
    }
    await state.update_data(match=match_data)
    
    match_title = f"🏆 НАЦИОНАЛЬНЫЙ КУБОК ({cup_stg}) 🏆" if is_cup_match else f"🏟️ РЕГУЛЯРНЫЙ ЧЕМПИОНАТ ({p['division']})"
    intro_text = ""
    
    if callback.message.photo: await callback.message.delete()
    
    msg = await callback.message.answer(f"{intro_text}⚽ **{match_title}**\n⚔️ **{p['club']}** vs **{match_data['rival']}**\nСудья дает свисток к началу игры!", parse_mode="Markdown")
    await asyncio.sleep(2)
    await msg.delete()
    await generate_moment(callback, state, user_id)

# ========== ФУНКЦИИ МАТЧА ==========

# ... (все функции generate_moment, gk_act, cb_act, shoot, pass, penalty, finish_match остаются без изменений)

async def generate_moment(callback: CallbackQuery, state: FSMContext, user_id: str):
    data = await state.get_data()
    if "match" not in data:
        return
    m = data["match"]
    p = (await load_data(PLAYERS_FILE)).get(user_id)
 
    m["minute"] += random.randint(15, 25)
    if m["minute"] > 90: m["minute"] = 90
    
    my_rating = CLUB_RATINGS.get(p["club"], 50)
    rival_rating = CLUB_RATINGS.get(m["rival"], 50)
    rating_diff = my_rating - rival_rating
 
    if random.random() < 0.65:
        if random.random() < 0.5:
            rival_score_chance = 0.40 - (rating_diff * 0.02)
            if random.random() < max(0.05, min(0.95, rival_score_chance)):
                m["rival_team_score"] += 1
                m["log"] += f"⚡ **{m['minute']}'** | ГОЛ! Соперник забивает мяч в ваши ворота.\n"
        else:
            team_score_chance = 0.40 + (rating_diff * 0.02)
            if random.random() < max(0.05, min(0.95, team_score_chance)):
                m["my_team_score"] += 1
                m["log"] += f"⚽ **{m['minute']}'** | ГОЛ! Твоя команда забивает отличный гол!\n"

    if random.random() < 0.4:
        flavor = random.choice([
            "🔥 Красивый финт в центре поля обостряет игру.", 
            "📐 Подача углового, но защита выносит мяч.", 
            "🟨 Судья показывает желтую карточку игроку соперника.",
            "⚔️ Жесткий стык, но судья не дает свисток.",
            "👐 Вратарь уверенно забирает мяч после навеса."
        ])
        m["log"] += f"⏱ **{m['minute']}'** | {flavor}\n"

    if random.random() < 0.08:
        card_roll = random.random()
        if card_roll < 0.15:
            m["log"] += f"🟥 **{m['minute']}'** | ПРЯМАЯ КРАСНАЯ! Грубейший фол, ты удален с поля!\n"
            m["minute"] = 90
        else:
            m["log"] += f"🟨 **{m['minute']}'** | Судья показывает тебе желтую карточку за срыв атаки.\n"
            m["yellow_cards"] = m.get("yellow_cards", 0) + 1
            if m["yellow_cards"] >= 2:
                m["log"] += f"🟥 **{m['minute']}'** | ВТОРАЯ ЖЕЛТАЯ! ТЕБЯ УДАЛЯЮТ С ПОЛЯ!\n"
                m["minute"] = 90
 
    if m["current_moment"] > m["total_moments"] or m["minute"] == 90:
        is_knockout = False
        if m["is_cup"]:
            is_knockout = True
                
        if is_knockout and m["my_team_score"] == m["rival_team_score"]:
            await start_penalty_shootout(callback, state, user_id)
        else:
            await finish_match(callback, state, user_id)
        return
        
    text = (f"⏱ **{m['minute']}' МИНУТА** | Момент {m['current_moment']}/{m['total_moments']}\n"
            f"⚔️ **{p['club']}** vs **{m['rival']}**\n"
            f"Счет: **{m['my_team_score']} : {m['rival_team_score']}**\n\n"
            f"📝 **События матча:**\n{m['log'] or 'Идет плотная позиционная борьба...'}\n")
    
    m["log"] = "" 
    
    if p["position"] == "GK":
        text += "🚨 **Опасность! Нападающий соперника выходит один на один с тобой! Твои действия?**"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧤 Прыгнуть в левый угол", callback_data="gk_act:left"), InlineKeyboardButton(text="🧤 Прыгнуть в правый угол", callback_data="gk_act:right")],
            [InlineKeyboardButton(text="🏃 Сблизить дистанцию", callback_data="gk_act:rush")]
        ])
    elif p["position"] == "CB":
        if random.random() < 0.75:
            text += "🛡️ **Форвард соперника идет на дриблинге прямо в твою зону!**"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧲 Жесткий подкат", callback_data="cb_act:tackle_hard"), InlineKeyboardButton(text="🕴️ Встретить корпусом", callback_data="cb_act:tackle_smart")],
                [InlineKeyboardButton(text="📐 Отдать пас ближнему", callback_data="act:pass")]
            ])
        else:
            text += "🔥 **Ты подключился на угловой! Мяч летит к тебе!**"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎯 Пробить головой", callback_data="act:shoot_menu"), InlineKeyboardButton(text="📐 Сбросить под удар партнеру", callback_data="act:pass")]
            ])
    else:
        text += "🔥 **Ты контролируешь мяч на подступах к штрафной! Твое решение?**"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Пробить по воротам", callback_data="act:shoot_menu"), InlineKeyboardButton(text="📐 Отдать пас", callback_data="act:pass")]
        ])
        
    await state.update_data(match=m)
    
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data.startswith("gk_act:"))
@with_user_lock
async def gk_action_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "match" not in data:
        return await callback.answer("⏳ Матч уже завершен!", show_alert=True)
    m = data["match"]
    action = callback.data.split(":")[1]
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    
    rival_rating = CLUB_RATINGS.get(m["rival"], 50)
    save_chance = 0.30 + ((p["rating"] - rival_rating) * 0.015) + (p["rating"] * 0.004)
    save_chance = max(0.1, min(0.95, save_chance))
    
    opp_shoot_dir = random.choice(["left", "right", "center"])
    
    is_saved = False
    if action == "rush":
        if random.random() < (save_chance + 0.1): is_saved = True
    else:
        if action == opp_shoot_dir or random.random() < save_chance * 0.8: is_saved = True
        
    if is_saved:
        m["saves"] += 1
        m["log"] += f"🧤 **{m['minute']}'** | БЕЗУМНЫЙ СЕЙВ! Ты вытаскиваешь мертвейший мяч!\n"
    else:
        m["rival_team_score"] += 1
        m["log"] += f"⚡ **{m['minute']}'** | Гол... Оппонент технично переиграл тебя на противоходе.\n"
        
    m["current_moment"] += 1
    await state.update_data(match=m)
    await generate_moment(callback, state, user_id)

@dp.callback_query(F.data.startswith("cb_act:"))
@with_user_lock
async def cb_action_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "match" not in data:
        return await callback.answer("⏳ Матч уже завершен!", show_alert=True)
    m = data["match"]
    action = callback.data.split(":")[1]
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    
    rival_rating = CLUB_RATINGS.get(m["rival"], 50)
    tackle_chance = 0.30 + ((p["rating"] - rival_rating) * 0.015) + (p["rating"] * 0.003)
    tackle_chance = max(0.1, min(0.90, tackle_chance))
    
    if action == "tackle_hard":
        if random.random() < 0.15:
            m["rival_team_score"] += 1
            m["log"] += f"⚡ **{m['minute']}'** | Фол в штрафной! Ты сфолил, соперник забивает пенальти.\n"
        elif random.random() < tackle_chance:
            m["tackles"] += 1
            m["log"] += f"🛡️ **{m['minute']}'** | Мощнейший чистый подкат! Форвард лежит, мяч отобран!\n"
        else:
            m["rival_team_score"] += 1
            m["log"] += f"⚡ **{m['minute']}'** | Ошибка! Нападающий пробросил мяч мимо тебя и забил.\n"
    else:
        if random.random() < tackle_chance:
            m["tackles"] += 1
            m["log"] += f"🛡️ **{m['minute']}'** | Отличный выбор позиции. Ты заблокировал продвижение соперника.\n"
        else:
            m["rival_team_score"] += 1
            m["log"] += f"⚡ **{m['minute']}'** | Тебя легко обыграли на замахе. Гол.\n"
            
    m["current_moment"] += 1
    await state.update_data(match=m)
    await generate_moment(callback, state, user_id)

@dp.callback_query(F.data == "act:shoot_menu")
@with_user_lock
async def act_shoot_menu_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "match" not in data:
        return await callback.answer("⏳ Матч уже завершен!", show_alert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📐 Левый верхний (Девятка)", callback_data="shoot_dir:в левую девятку"), InlineKeyboardButton(text="📐 Правый верхний (Девятка)", callback_data="shoot_dir:в правую девятку")],
        [InlineKeyboardButton(text="👇 Левый нижний", callback_data="shoot_dir:низом в левый угол"), InlineKeyboardButton(text="👇 Правый нижний", callback_data="shoot_dir:низом в правый угол")]
    ])
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass

@dp.callback_query(F.data.startswith("shoot_dir:"))
@with_user_lock
async def act_shoot_execute_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "match" not in data:
        return await callback.answer("⏳ Матч уже завершен!", show_alert=True)
    m = data["match"]
    target_dir = callback.data.split(":")[1]
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    
    rival_rating = CLUB_RATINGS.get(m["rival"], 50)
    score_chance = 0.60 + ((p["rating"] - rival_rating) * 0.015)
    
    gk_dive = random.choice(["в левую девятку", "в правую девятку", "низом в левый угол", "низом в правый угол"])
    
    if gk_dive == target_dir:
        score_chance -= 0.15
        gk_guessed = True
    else:
        score_chance += 0.10
        gk_guessed = False
        
    score_chance = max(0.05, min(0.95, score_chance))
    
    if random.random() < score_chance:
        m["goals"] += 1; m["my_team_score"] += 1
        try:
            await callback.message.edit_text(
                f"⚽ **{m['minute']}'** | ГОЛ! Твой шикарный удар {target_dir} разрывает сетку ворот!",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        await asyncio.sleep(2)
        m["log"] += f"⚽ **{m['minute']}'** | ГОЛ! Твой шикарный удар {target_dir}!\n"
    else:
        if gk_guessed:
            m["log"] += f"❌ **{m['minute']}'** | Ты пробил {target_dir}, но голкипер парировал удар!\n"
        else:
            m["log"] += f"❌ **{m['minute']}'** | Целился {target_dir}, но мяч пролетел мимо!\n"
            
    m["current_moment"] += 1
    await state.update_data(match=m)
    await generate_moment(callback, state, user_id)

@dp.callback_query(F.data == "act:pass")
@with_user_lock
async def act_pass_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "match" not in data:
        return await callback.answer("⏳ Матч уже завершен!", show_alert=True)
    m = data["match"]
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    
    rival_rating = CLUB_RATINGS.get(m["rival"], 50)
    pass_chance = 0.60 + ((p["rating"] - rival_rating) * 0.015)
    pass_chance = max(0.05, min(0.95, pass_chance))
    
    if random.random() < pass_chance:
        m["assists"] += 1
        m["my_team_score"] += 1
        m["log"] += f"✅ **{m['minute']}'** | Шикарный точный пас на партнера, и он вколачивает мяч в сетку! ГОЛ!\n"
    else:
        m["log"] += f"❌ **{m['minute']}'** | Пас оказался неточным, перехват соперника.\n"
        
    m["current_moment"] += 1
    await state.update_data(match=m)
    await generate_moment(callback, state, user_id)

async def _clear_match_state(state: FSMContext):
    data = await state.get_data()
    data.pop("match", None)
    await state.set_data(data)

async def start_penalty_shootout(callback: CallbackQuery, state: FSMContext, user_id: str):
    data = await state.get_data()
    m = data.get("match")
    if not m:
        return await _clear_match_state(state)

    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if not p:
        return await _clear_match_state(state)

    rival_rating = CLUB_RATINGS.get(m["rival"], 50)
    my_chance = 0.5 + ((p.get("rating", 40) - rival_rating) * 0.01)
    my_chance = max(0.25, min(0.75, my_chance))

    my_score, rival_score = 0, 0
    for _ in range(5):
        if random.random() < 0.75:
            my_score += 1
        if random.random() < 0.75:
            rival_score += 1
    while my_score == rival_score:
        if random.random() < my_chance:
            my_score += 1
        else:
            rival_score += 1

    won_shootout = my_score > rival_score
    m["log"] += f"\n🥅 **СЕРИЯ ПЕНАЛЬТИ:** {my_score} : {rival_score} — {'ТЫ ПРОШЕЛ ДАЛЬШЕ!' if won_shootout else 'вы вылетаете...'}\n"

    if won_shootout:
        m["my_team_score"] += 1
    else:
        m["rival_team_score"] += 1

    await state.update_data(match=m)
    await finish_match(callback, state, user_id, penalty_result=(my_score, rival_score, won_shootout))

async def finish_match(callback: CallbackQuery, state: FSMContext, user_id: str, penalty_result=None):
    data = await state.get_data()
    m = data.get("match")
    if not m:
        return await callback.message.answer(
            "⚠️ Данные матча были потеряны. Возвращаю в главное меню.",
            reply_markup=await main_menu_keyboard(callback.from_user.username, user_id)
        )

    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if not p:
        await _clear_match_state(state)
        return

    if m["my_team_score"] > m["rival_team_score"]:
        outcome = "win"
        outcome_text = "🏆 **ПОБЕДА!**"
        p["trust"] = min(100, p.get("trust", 0) + 5)
    elif m["my_team_score"] == m["rival_team_score"]:
        outcome = "draw"
        outcome_text = "🤝 **НИЧЬЯ**"
        p["trust"] = min(100, p.get("trust", 0) + 1)
    else:
        outcome = "loss"
        outcome_text = "❌ **ПОРАЖЕНИЕ**"
        p["trust"] = max(0, p.get("trust", 0) - 4)

    p.setdefault("stats_season", {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0})
    p.setdefault("stats_total", {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0})
    for stat in ("goals", "assists", "saves", "tackles"):
        p["stats_season"][stat] = p["stats_season"].get(stat, 0) + m.get(stat, 0)
        p["stats_total"][stat] = p["stats_total"].get(stat, 0) + m.get(stat, 0)
    p["stats_total"]["games"] = p["stats_total"].get("games", 0) + 1

    goals   = m.get("goals", 0)
    assists = m.get("assists", 0)
    saves   = m.get("saves", 0)
    tackles = m.get("tackles", 0)
    conceded = m.get("rival_team_score", 0)

    raw = (goals * 0.35 + assists * 0.25 + saves * 0.25 + tackles * 0.15
           - conceded * 0.10
           + (0.20 if outcome == "win" else (-0.15 if outcome == "loss" else 0.0)))
    raw = max(-1.0, min(1.0, raw))
    
    rating_delta = round(raw * 0.06, 2)

    p["rating"] = round(max(1.0, min(100.0, p.get("rating", 40.0) + rating_delta)), 2)

    money_gain = p.get("contract_salary", 1500)
    sponsor_income = 0
    sp_name = p.get("sponsor")
    if sp_name and sp_name in SPONSORS_DATA:
        sponsor_income = SPONSORS_DATA[sp_name]["income_per_match"]
        money_gain += sponsor_income
    p["money"] = p.get("money", 0) + money_gain
    p["train_done"] = False

    cup_summary = ""
    if m.get("is_cup"):
        p["cup_rivals"] = p.get("cup_rivals", []) + [m["rival"]]
        if outcome == "win":
            stages = CUP_STAGES
            current_stage = m.get("cup_stage") or p.get("cup_stage", "1/16")
            idx = stages.index(current_stage) if current_stage in stages else -1
            if idx == len(stages) - 1:
                p["trophies"] = p.get("trophies", []) + [f"🏆 Кубок сезона {p.get('season', 1)}"]
                p["money"] += 100000
                p["rating"] = max(1.0, min(100.0, round(p["rating"] + 0.5, 1)))
                p["cup_out"] = True
                cup_summary = "\n\n🏆 **ТЫ ВЫИГРАЛ НАЦИОНАЛЬНЫЙ КУБОК!!!** 🎉"
            else:
                p["cup_stage"] = stages[idx + 1]
                cup_summary = f"\n\n➡️ Ты прошел в стадию **{p['cup_stage']}** Кубка!"
        else:
            p["cup_out"] = True
            cup_summary = "\n\n🚫 Твоя команда вылетела из Кубка на этой стадии."
    else:
        p["tour"] = p.get("tour", 1) + 1
        p["played_league_rivals"] = p.get("played_league_rivals", []) + [m["rival"]]
        await simulate_table_tour(user_id, p["division"], p["club"], m["rival"], outcome)
        if p.get("on_loan") and p.get("parent_club"):
            parent_div = get_division(p["parent_club"])
            if parent_div != p["division"]:
                await simulate_background_division(user_id, parent_div)

    age = p.get("age", 17)
    if age >= 36:
        p["rating"] = max(1.0, round(p["rating"] - 0.3, 1))
    elif age >= 33:
        p["rating"] = max(1.0, round(p["rating"] - 0.2, 1))
    elif age >= 30:
        p["rating"] = max(1.0, round(p["rating"] - 0.1, 1))

    players[user_id] = p
    await save_data(PLAYERS_FILE, players)
    await _clear_match_state(state)

    penalty_line = ""
    if penalty_result:
        my_pen, rival_pen, _ = penalty_result
        penalty_line = f"🥅 Пенальти: {my_pen} : {rival_pen}\n"

    sponsor_line = (f"💼 Доход от {p.get('sponsor')}: +{sponsor_income}$\n"
                    if sponsor_income else "")

    rating_performance = 5.0
    rating_performance += goals * 1.0
    rating_performance += assists * 0.8
    rating_performance += saves * 0.5
    rating_performance += tackles * 0.5
    if outcome == "win":
        rating_performance += 1.0
    elif outcome == "draw":
        rating_performance += 0.5
    rating_performance -= conceded * 0.3
    rating_performance = max(5.0, min(10.0, rating_performance))
    rating_performance = round(rating_performance, 1)
    
    p["rating_performance"] = rating_performance

    text = (
        f"🏁 **МАТЧ ЗАВЕРШЕН!**\n"
        f"⚔️ **{p['club']} {m['my_team_score']} : {m['rival_team_score']} {m['rival']}**\n"
        f"{penalty_line}{outcome_text}\n\n"
        f"📊 **Оценка за матч: {rating_performance} / 10**\n"
        f"⚽ Голы: {m.get('goals', 0)} | 🅰️ Ассисты: {m.get('assists', 0)} | "
        f"🧤 Сейвы: {m.get('saves', 0)} | 🛡️ Отборы: {m.get('tackles', 0)}\n"
        f"💰 Зарплата: +{p.get('contract_salary', 1500)}$\n"
        f"{sponsor_line}"
        f"📈 Рейтинг: {p['rating']} ({'+' if rating_delta >= 0 else ''}{rating_delta})"
        f"{cup_summary}"
    )

    kb = await main_menu_keyboard(callback.from_user.username, user_id)
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        if callback.message.photo:
            await callback.message.delete()
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)

    if rating_performance >= 9.0:
        await start_interview(callback, state, user_id, p)

def _pick_offers_by_rating(rating: float, current_club: str, current_division: str) -> list[dict]:
    low  = max(0,   int(rating) - 15)
    high = min(100, int(rating) + 20)

    candidates = []
    for div, clubs in CLUBS.items():
        for club in clubs:
            cr = CLUB_RATINGS.get(club, 50)
            if low <= cr <= high and club != current_club:
                candidates.append({"club": club, "division": div, "club_rating": cr})

    if len(candidates) < 4:
        candidates = [
            {"club": c, "division": d, "club_rating": CLUB_RATINGS.get(c, 50)}
            for d, clubs in CLUBS.items()
            for c in clubs
            if c != current_club
        ]

    random.shuffle(candidates)
    seen_divs: set = set()
    offers: list[dict] = []
    for cand in candidates:
        if cand["division"] not in seen_divs:
            seen_divs.add(cand["division"])
            salary = max(1500, int(cand["club_rating"] * 150 + rating * 50))
            cand["salary"] = salary
            offers.append(cand)
        if len(offers) == 4:
            break

    if len(offers) < 4:
        used = {o["club"] for o in offers}
        for cand in candidates:
            if cand["club"] not in used:
                salary = max(1500, int(cand["club_rating"] * 150 + rating * 50))
                cand["salary"] = salary
                offers.append(cand)
                used.add(cand["club"])
            if len(offers) == 4:
                break

    return offers

async def start_interview(callback: CallbackQuery, state: FSMContext, user_id: str, p: dict):
    questions = [
        {
            "question": "Как ты оцениваешь свой вклад в сегодняшнюю победу?",
            "a": "Я был лидером и вёл команду за собой",
            "b": "Я просто выполнял свою работу на поле",
            "trust_a": 5,
            "trust_b": 2
        },
        {
            "question": "Что бы ты сказал болельщикам после такого матча?",
            "a": "Спасибо за вашу невероятную поддержку!",
            "b": "Мы ещё не всё показали, впереди много побед!",
            "trust_a": 3,
            "trust_b": 4
        },
        {
            "question": "Какой момент матча ты запомнил больше всего?",
            "a": "Мой забитый мяч / сейв / отбор",
            "b": "Командная работа и дух борьбы",
            "trust_a": 4,
            "trust_b": 3
        }
    ]

    await state.set_state(InterviewState.waiting_for_answer)
    await state.update_data(interview={
        "questions": questions,
        "trust_gain": 0
    })

    q0 = questions[0]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=q0["a"], callback_data="interview:0:a")],
        [InlineKeyboardButton(text=q0["b"], callback_data="interview:0:b")]
    ])
    await callback.message.answer(
        f"🎙️ **Поздравляем с выдающимся матчем! Твоя оценка {p.get('rating_performance', 9.0)}!**\n"
        f"Журналисты хотят задать тебе несколько вопросов.\n\n"
        f"**Вопрос 1/3:**\n_{q0['question']}_",
        parse_mode="Markdown", reply_markup=kb
    )

# ========== season_results_handler И season_choice_handler (БЕЗ ИЗМЕНЕНИЙ) ==========

async def season_results_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if await deny_if_retired_cb(callback, p):
        return

    async with get_table_lock():
        tables = await load_data(TABLES_FILE)
        table = tables.get(user_id, {}).get(p["division"], [])
    table_sorted = sorted(table, key=lambda x: x["points"], reverse=True)
    total_clubs = max(len(table_sorted), 1)
    position = next((i + 1 for i, row in enumerate(table_sorted) if row["club"] == p["club"]), total_clubs)

    season_num = p.get("season", 1)

    ladder = get_ladder(p["division"])
    idx_in_ladder = ladder.index(p["division"]) if p["division"] in ladder else 0

    promotion_div = None
    relegation_div = None

    if position == 1:
        result_text = f"🥇 **ЧЕМПИОНСТВО!** 1 место из {total_clubs} в **{p['division']}**!"
        p["trophies"] = p.get("trophies", []) + [f"🥇 Чемпион «{p['division']}» (Сезон {season_num})"]
        if idx_in_ladder < len(ladder) - 1:
            promotion_div = ladder[idx_in_ladder + 1]
            result_text += f"\n📈 Ваша команда получила путевку в **{promotion_div}**!"
    elif position <= 2 and idx_in_ladder < len(ladder) - 1:
        promotion_div = ladder[idx_in_ladder + 1]
        result_text = (f"🎉 **ВЫХОД В ВЫСШИЙ ДИВИЗИОН!** {position} место из {total_clubs}.\n"
                       f"Команда пробилась в **{promotion_div}**!")
        p["trophies"] = p.get("trophies", []) + [f"⬆️ Выход в «{promotion_div}» (Сезон {season_num})"]
    elif position >= total_clubs - 1 and total_clubs > 2 and idx_in_ladder > 0:
        relegation_div = ladder[idx_in_ladder - 1]
        result_text = (f"📉 **ВЫЛЕТ!** {position} место из {total_clubs}.\n"
                       f"Команда падает в **{relegation_div}**.")
    else:
        result_text = f"📊 {position} место из {total_clubs} в **{p['division']}**."

    stats = p.get("stats_season", {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0})
    pos_code = p.get("position", "ST")
    if pos_code == "GK":
        stats_text = f"🎮 {stats.get('games',0)} матчей | 🧤 {stats.get('saves',0)} сейвов"
    elif pos_code == "CB":
        stats_text = f"🎮 {stats.get('games',0)} матчей | 🛡️ {stats.get('tackles',0)} отборов | ⚽ {stats.get('goals',0)} голов"
    else:
        stats_text = f"🎮 {stats.get('games',0)} матчей | ⚽ {stats.get('goals',0)} голов | 🅰️ {stats.get('assists',0)} ассистов"

    p["age"] = p.get("age", 17) + 1
    retired_now = False
    
    if season_num > 13 or (p["age"] >= 36 and random.random() < 0.35):
        retired_now = True
        p["retired"] = True
        career_summary = (f"📌 {p['name']} | Рейтинг: {p['rating']} | "
                          f"Клуб: {p['club']} | Трофеев: {len(p.get('trophies', []))}")
        p["career_history"] = p.get("career_history", []) + [career_summary]
        await add_to_retired_leaderboard(p["name"], p["rating"], len(p.get("trophies", [])))

    if retired_now:
        _apply_new_season_reset(p)
        players[user_id] = p
        await save_data(PLAYERS_FILE, players)
        text = (
            f"🏁 **ИТОГИ СЕЗОНА {season_num}**\n━━━━━━━━━━━━━━━━━━━━\n"
            f"{result_text}\n\n"
            f"📊 {stats_text}\n\n"
            f"🏁 **Карьера завершена! Ты провел великий путь и уходишь на заслуженную пенсию.**"
        )
        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=retired_keyboard())
        except Exception:
            if callback.message.photo: await callback.message.delete()
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=retired_keyboard())
        return

    rating = p.get("rating", 40.0)
    offers = _pick_offers_by_rating(rating, p["club"], p["division"])

    forced_div = promotion_div or relegation_div
    if forced_div:
        forced_club = random.choice([c for c in CLUBS.get(forced_div, []) if c != p["club"]] or CLUBS.get(forced_div, [p["club"]]))
        forced_salary = max(1500, int(CLUB_RATINGS.get(forced_club, 50) * 150 + rating * 50))
        forced_offer = {"club": forced_club, "division": forced_div,
                        "club_rating": CLUB_RATINGS.get(forced_club, 50), "salary": forced_salary}
        offers = [o for o in offers if o["division"] != forced_div][:3]
        offers.insert(0, forced_offer)

    p["_season_offers"] = offers
    p["_season_num"]    = season_num
    p["_season_forced_div"] = forced_div
    p["_season_result_text"] = result_text
    p["_season_stats_text"]  = stats_text
    players[user_id] = p
    await save_data(PLAYERS_FILE, players)

    current_salary = p.get("contract_salary", 1500)
    renew_salary   = max(current_salary, int(current_salary * 1.15))
    buttons = []
    for i, o in enumerate(offers):
        label = f"🏟 {o['club']} ({o['division']}) — {o['salary']}$/матч"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"season_choice:{i}")])
    buttons.append([InlineKeyboardButton(
        text=f"🔄 Продлить контракт с {p['club']} — {renew_salary}$/матч",
        callback_data="season_choice:renew"
    )])

    text = (
        f"🏁 **ИТОГИ СЕЗОНА {season_num}**\n━━━━━━━━━━━━━━━━━━━━\n"
        f"{result_text}\n\n"
        f"📊 {stats_text}\n\n"
        f"📋 **Выбери, где продолжить карьеру:**"
    )

    try:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="Markdown",
                                          reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else:
            await callback.message.edit_text(text, parse_mode="Markdown",
                                             reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except Exception as e:
        logging.warning(f"season_results_handler send error: {e}")
        await callback.message.answer(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

def _apply_new_season_reset(p: dict):
    p["season"]   = p.get("_season_num", p.get("season", 1)) + 1
    p["tour"]     = 1
    p["stats_season"]          = {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0}
    p["played_league_rivals"]  = []
    p["cup_out"]   = False
    p["cup_stage"] = "1/16"
    p["cup_rivals"] = []
    p["train_done"] = False
    p["fatigue"]    = max(0, p.get("fatigue", 0) - 30)
    for key in ("_season_offers", "_season_num", "_season_result_text", "_season_stats_text", "_season_forced_div"):
        p.pop(key, None)

@dp.callback_query(F.data.startswith("season_choice:"))
@with_user_lock
async def season_choice_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if not p:
        return await callback.answer("⚠️ Профиль не найден. Нажми /start.", show_alert=True)

    offers = p.get("_season_offers", [])
    choice = callback.data.split(":")[1]
    season_num = p.get("_season_num", p.get("season", 1))
    forced_div = p.get("_season_forced_div")

    if choice == "renew":
        old_salary = p.get("contract_salary", 1500)
        p["contract_salary"] = max(old_salary, int(old_salary * 1.15))
        
        if forced_div:
            p["division"] = forced_div
            club_line = f"🔄 Ты продлил контракт с **{p['club']}**!\n📈 Твоя команда переходит в **{forced_div}**!\n💰 Новая зарплата: **{p['contract_salary']}$/матч**"
        else:
            club_line = f"🔄 Ты продлил контракт с **{p['club']}**!\n💰 Новая зарплата: **{p['contract_salary']}$/матч**"
    else:
        try:
            idx = int(choice)
        except ValueError:
            return await callback.answer("❌ Неверный выбор.", show_alert=True)
        if idx < 0 or idx >= len(offers):
            return await callback.answer("❌ Предложение недоступно.", show_alert=True)
        offer = offers[idx]
        p["club"]            = offer["club"]
        p["division"]        = offer["division"]
        p["contract_salary"] = offer["salary"]
        p["trust"] = 15
        club_line = (f"✍️ Контракт подписан!\n"
                     f"🏟 Клуб: **{p['club']}** ({p['division']})\n"
                     f"💰 Зарплата: **{p['contract_salary']}$/матч**")

    # ========== ОПРЕДЕЛЯЕМ ЕВРОКУБКИ ДЛЯ НОВОГО КЛУБА ==========
    euro_data = await load_data(EURO_FILE)
    if euro_data and euro_data.get("status") == "group":
        tournament = None
        for t in ["champions_league", "europa_league", "conference_league"]:
            if p["club"] in euro_data[t]["clubs"]:
                tournament = t
                break
        
        if tournament:
            p["euro_tournament"] = tournament
            p["euro_goals"] = 0
            p["euro_assists"] = 0
            p["euro_matches"] = 0
            p["euro_playoff_stage"] = None
            club_line += f"\n\n🌍 {get_euro_name(tournament)}!"
        else:
            p["euro_tournament"] = "none"
    # ===========================================================

    _apply_new_season_reset(p)
    players[user_id] = p
    await save_data(PLAYERS_FILE, players)
    await init_tables_for_user(user_id, p["division"], p["club"])

    text = (
        f"🎉 **СЕЗОН {season_num} ЗАВЕРШЁН!**\n━━━━━━━━━━━━━━━━━━━━\n"
        f"{club_line}\n\n"
        f"➡️ Начинается **Сезон {p['season']}**!\n"
        f"Удачи!"
    )
    kb = await main_menu_keyboard(callback.from_user.username, user_id)
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logging.warning(f"season_choice_handler edit error: {e}")
        if callback.message.photo: await callback.message.delete()
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)

# ========== ЗАПУСК ==========

async def main():
    print("🚀 Бот запущен и ожидает сообщений...")
    print("📌 ДОБАВЛЕНЫ ЕВРОКУБКИ В НОВОМ ФОРМАТЕ!")
    print("📌 Лига Чемпионов - 36 клубов, 8 туров, швейцарская система")
    print("📌 Лига Европы - 36 клубов, 8 туров, швейцарская система")
    print("📌 Лига Конференций - 36 клубов, 8 туров, швейцарская система")
    print("📌 Плей-офф: 1/8, 1/4, 1/2, Финал")
    print("📌 Награды: деньги, рейтинг, трофеи")
    print("📌 trust обнуляется до 15 при переходе в новый клуб")
    print("📌 Автоудаление сообщений через 3 секунды")
    print("📌 ИСПРАВЛЕНО: только 1 предложение о переходе за матч")
    print("📌 ИСПРАВЛЕНО: при переходе в клуб создается таблица с нуля")
    print("📌 ИСПРАВЛЕНО: админ-панель считает статистику и таблицу")
    # Перед запуском восстанавливаем/создаем еврокубки. Это автоматически
    # чинит старый euro_qualification.json, где могло быть только 20 клубов
    # или отсутствовать календарь матчей.
    try:
        await ensure_euro_data()
        print("📌 Еврокубки проверены: по 36 клубов и по 8 матчей на клуб")
    except Exception as e:
        logging.exception(f"Ошибка инициализации еврокубков: {e}")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
