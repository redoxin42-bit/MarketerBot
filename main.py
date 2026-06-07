import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PasswordHashInvalid

import config
import database as db
import userbot_worker

# Инициализация aiogram
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Временное хранилище запущенных сессий авторизации Pyrogram
# Ключ: user_id, Значение: временный инстанс Client
raw_clients = {}

# Состояния FSM для добавления аккаунта
class AuthStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()

# Состояния FSM для запуска рассылки
class BroadcastStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_chats = State()

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    # Конструктор кнопок с кастомными премиум-эмодзи
    builder.button(text="💻 Создать сессию", callback_data="btn_create_session")
    builder.button(text="🎛 Логи", callback_data="btn_view_logs")
    builder.button(text="⚡️ Рассылка", callback_data="btn_start_broadcast")
    builder.adjust(2, 1)
    return builder.as_markup()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    _, status = db.get_session()
    cooldown = db.get_cooldown()
    
    # Текст приветствия с использованием HTML-тегов для кастомных премиум-эмодзи
    text = (
        '<tg-emoji emoji-id="5958376256788502078">⭐️</tg-emoji> <b>Добро пожаловать в Marketer Bot!</b>\n\n'
        'Бот нужен для рассылки сообщений.\n\n'
        f'<b>Статус:</b> {status}\n'
        f'<b>Задержка (CoolDown):</b> {cooldown} сек.'
    )
    await message.answer(text=text, reply_markup=get_main_keyboard(), parse_mode="HTML")

# --- КНОПКА: СОЗДАТЬ СЕССИЮ ---
@dp.callback_query(F.data == "btn_create_session")
async def start_auth(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("☎️ Введите номер телефона аккаунта для рассылки в международном формате (например, +79991234567):")
    await state.set_state(AuthStates.waiting_for_phone)
    await callback.answer()

@dp.message(AuthStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "")
    await message.answer("⏳ Отправка запроса в Telegram...")
    
    # Создаем временный клиент Pyrogram для авторизации
    client = Client(
        f"temp_{message.from_user.id}",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        in_memory=True
    )
    await client.connect()
    
    try:
        code_info = await client.send_code(phone)
        raw_clients[message.from_user.id] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": code_info.phone_code_hash
        }
        await message.answer("📩 Код подтверждения отправлен. Введите полученный код из приложения Telegram:")
        await state.set_state(AuthStates.waiting_for_code)
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки кода: {e}\nПопробуйте заново через /start")
        await client.disconnect()
        await state.clear()

@dp.message(AuthStates.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in raw_clients:
        await message.answer("🚨 Ошибка контекста сессии. Начните заново через /start")
        await state.clear()
        return
        
    user_data = raw_clients[user_id]
    client = user_data["client"]
    code = message.text.strip()
    
    try:
        await client.sign_in(
            phone_number=user_data["phone"],
            phone_code_hash=user_data["phone_code_hash"],
            phone_code=code
        )
        # Если вошли без 2FA
        session_str = await client.export_session_string()
        db.save_session(user_data["phone"], session_str)
        db.add_log(f"👤 Аккаунт {user_data['phone']} успешно привязан.")
        await message.answer("🎉 Авторизация успешна! Аккаунт подключен к движку рассыльщика.", reply_markup=get_main_keyboard())
        await client.disconnect()
        raw_clients.pop(user_id, None)
        await state.clear()
        
    except SessionPasswordNeeded:
        await message.answer("🔐 Ваш аккаунт защищен облачным паролем (2FA). Пожалуйста, введите ваш пароль:")
        await state.set_state(AuthStates.waiting_for_2FA)
        
    except PhoneCodeInvalid:
        await message.answer("❌ Неверный код подтверждения. Введите код ещё раз:")

@dp.message(AuthStates.waiting_for_2fa)
async def process_2fa(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = raw_clients.get(user_id)
    if not user_data:
        await message.answer("🚨 Ошибка сессии. Пропишите /start")
        await state.clear()
        return

    client = user_data["client"]
    password = message.text.strip()
    
    try:
        await client.check_password(password=password)
        session_str = await client.export_session_string()
        db.save_session(user_data["phone"], session_str)
        db.add_log(f"👤 Аккаунт {user_data['phone']} успешно привязан с 2FA.")
        await message.answer("🎉 Авторизация успешна! Аккаунт с 2FA успешно подключен.", reply_markup=get_main_keyboard())
        await client.disconnect()
        raw_clients.pop(user_id, None)
        await state.clear()
    except PasswordHashInvalid:
        await message.answer("❌ Неверный облачный пароль. Попробуйте ввести ещё раз:")

# --- КНОПКА: ЛОГИ ---
@dp.callback_query(F.data == "btn_view_logs")
async def view_logs(callback: types.CallbackQuery):
    logs_list = db.get_logs(12)
    if not logs_list:
        logs_text = "📭 Логи пустые. Рассылка ещё не запускалась."
    else:
        logs_text = "<b>📋 Последние события системы:</b>\n\n" + "\n".join(logs_list)
        
    await callback.message.answer(logs_text, parse_mode="HTML")
    await callback.answer()

# --- КНОПКА: РАССЫЛКА ---
@dp.callback_query(F.data == "btn_start_broadcast")
async def start_broadcast_init(callback: types.CallbackQuery, state: FSMContext):
    session_str, _ = db.get_session()
    if not session_str:
        await callback.message.answer("🛑 Сначала необходимо авторизовать аккаунт через кнопку 'Создать сессию'!")
        await callback.answer()
        return
        
    await callback.message.answer("📝 Введите рекламный текст, который нужно разослать:")
    await state.set_state(BroadcastStates.waiting_for_text)
    await callback.answer()

@dp.message(BroadcastStates.waiting_for_text)
async def process_broadcast_text(message: types.Message, state: FSMContext):
    await state.update_data(broadcast_text=message.text)
    await message.answer("📂 Теперь отправьте список юзернеймов или ID чатов (каждый чат с новой строки, например @chat_username или -100123456):")
    await state.set_state(BroadcastStates.waiting_for_chats)

@dp.message(BroadcastStates.waiting_for_chats)
async def process_broadcast_chats(message: types.Message, state: FSMContext):
    chats_data = message.text.split("\n")
    state_data = await state.get_data()
    broadcast_text = state_data.get("broadcast_text")
    
    await message.answer("🚀 Движок рассылки запущен в фоновом режиме. Вы можете следить за процессом в кнопке 'Логи'.")
    await state.clear()
    
    # Запускаем фоновую задачу рассылки, чтобы не вешать основного бота
    asyncio.create_task(userbot_worker.start_broadcast_task(broadcast_text, chats_data))

# Запуск проекта
async def main():
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    print("Marketer Bot успешно запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
