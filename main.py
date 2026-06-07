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

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

raw_clients = {}

class AuthStates(StatesGroup):
    waiting_for_api_id = State()
    waiting_for_api_hash = State()
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()

class BroadcastStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_chats = State()

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💻 Создать сессию", callback_data="btn_create_session")
    builder.button(text="🎛 Логи", callback_data="btn_view_logs")
    builder.button(text="⚡️ Рассылка", callback_data="btn_start_broadcast")
    builder.adjust(2, 1)
    return builder.as_markup()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    _, _, _, status = db.get_session()
    cooldown = db.get_cooldown()
    
    text = (
        '<tg-emoji emoji-id="5958376256788502078">⭐️</tg-emoji> <b>Добро пожаловать в Marketer Bot!</b>\n\n'
        'Бот нужен для рассылки сообщений.\n\n'
        f'<b>Статус:</b> {status}\n'
        f'<b>Задержка (CoolDown):</b> {cooldown} сек.'
    )
    await message.answer(text=text, reply_markup=get_main_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "btn_create_session")
async def start_auth(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("1️⃣ Введите ваш <b>API_ID</b> (можно получить на my.telegram.org):", parse_mode="HTML")
    await state.set_state(AuthStates.waiting_for_api_id)
    await callback.answer()

@dp.message(AuthStates.waiting_for_api_id)
async def process_api_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ API_ID должен состоять только из цифр. Введите корректный API_ID:")
        return
    await state.update_data(user_api_id=int(message.text.strip()))
    await message.answer("2️⃣ Теперь введите ваш <b>API_HASH</b>:", parse_mode="HTML")
    await state.set_state(AuthStates.waiting_for_api_hash)

@dp.message(AuthStates.waiting_for_api_hash)
async def process_api_hash(message: types.Message, state: FSMContext):
    await state.update_data(user_api_hash=message.text.strip())
    await message.answer("3️⃣ Введите номер телефона аккаунта в международном формате (например, +79991234567):")
    await state.set_state(AuthStates.waiting_for_phone)

@dp.message(AuthStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "")
    await message.answer("⏳ Соединение с Telegram и отправка кода...")
    
    data = await state.get_data()
    user_api_id = data.get("user_api_id")
    user_api_hash = data.get("user_api_hash")
    
    client = Client(
        f"temp_{message.from_user.id}",
        api_id=user_api_id,
        api_hash=user_api_hash,
        in_memory=True
    )
    await client.connect()
    
    try:
        code_info = await client.send_code(phone)
        raw_clients[message.from_user.id] = {
            "client": client,
            "phone": phone,
            "api_id": user_api_id,
            "api_hash": user_api_hash,
            "phone_code_hash": code_info.phone_code_hash
        }
        await message.answer("📩 Код подтверждения отправлен. Введите код из приложения Telegram:")
        await state.set_state(AuthStates.waiting_for_code)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}\nПроверьте правильность API_ID/API_HASH и начните заново через /start")
        await client.disconnect()
        await state.clear()

@dp.message(AuthStates.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in raw_clients:
        await message.answer("🚨 Ошибка контекста сессии. Пропишите /start")
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
        session_str = await client.export_session_string()
        db.save_session(user_data["phone"], user_data["api_id"], user_data["api_hash"], session_str)
        db.add_log(f"👤 Аккаунт {user_data['phone']} успешно привязан.")
        
        await message.answer("🎉 Авторизация успешна! Аккаунт со своими API ключами добавлен.", reply_markup=get_main_keyboard())
        await client.disconnect()
        raw_clients.pop(user_id, None)
        await state.clear()
        
    except SessionPasswordNeeded:
        await message.answer("🔐 Аккаунт защищен 2FA. Введите ваш облачный пароль:")
        await state.set_state(AuthStates.waiting_for_2fa)
        
    except PhoneCodeInvalid:
        await message.answer("❌ Неверный код. Попробуйте ещё раз:")

@dp.message(AuthStates.waiting_for_2fa)
async def process_2fa(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = raw_clients.get(user_id)
    if not user_data:
        await message.answer("🚨 Ошибка сессии. Начните заново с /start")
        await state.clear()
        return

    client = user_data["client"]
    password = message.text.strip()
    
    try:
        await client.check_password(password=password)
        session_str = await client.export_session_string()
        db.save_session(user_data["phone"], user_data["api_id"], user_data["api_hash"], session_str)
        db.add_log(f"👤 Аккаунт {user_data['phone']} успешно привязан с 2FA.")
        
        await message.answer("🎉 Авторизация успешна! Аккаунт с 2FA добавлен.", reply_markup=get_main_keyboard())
        await client.disconnect()
        raw_clients.pop(user_id, None)
        await state.clear()
    except PasswordHashInvalid:
        await message.answer("❌ Неверный облачный пароль. Попробуйте ещё раз:")

@dp.callback_query(F.data == "btn_view_logs")
async def view_logs(callback: types.CallbackQuery):
    logs_list = db.get_logs(12)
    logs_text = "<b>📋 Последние события системы:</b>\n\n" + "\n".join(logs_list) if logs_list else "📭 Логи пустые."
    await callback.message.answer(logs_text, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "btn_start_broadcast")
async def start_broadcast_init(callback: types.CallbackQuery, state: FSMContext):
    session_str, _, _, _ = db.get_session()
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
    await message.answer("📂 Теперь отправьте список чатов (каждый чат с новой строки, например @username):")
    await state.set_state(BroadcastStates.waiting_for_chats)

@dp.message(BroadcastStates.waiting_for_chats)
async def process_broadcast_chats(message: types.Message, state: FSMContext):
    chats_data = message.text.split("\n")
    state_data = await state.get_data()
    broadcast_text = state_data.get("broadcast_text")
    
    await message.answer("🚀 Рассылка запущена в фоновом режиме. Чекайте кнопку 'Логи'.")
    await state.clear()
    
    asyncio.create_task(userbot_worker.start_broadcast_task(broadcast_text, chats_data))

async def main():
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    print("Marketer Bot успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
