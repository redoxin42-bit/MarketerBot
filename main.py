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

# Инициализация бота
bot = Bot(token="7727553460:AAHWkV9Skzw9oQRDWV51P2OLe7m9-UaInV4")
dp = Dispatcher(storage=MemoryStorage())

raw_clients = {}

# Состояния авторизации
class AuthStates(StatesGroup):
    waiting_for_api_id = State()
    waiting_for_api_hash = State()
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()

# Состояния рассылки
class BroadcastStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_tag_choice = State()
    waiting_for_cooldown = State()
    waiting_for_chats = State()

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text="Создать сессию", callback_data="btn_create_session", icon_custom_emoji_id="5877530150345641603"),
        types.InlineKeyboardButton(text="Логи", callback_data="btn_view_logs", icon_custom_emoji_id="5877332341331857066"),
        types.InlineKeyboardButton(text="Рассылка", callback_data="btn_start_broadcast", icon_custom_emoji_id="6005570495603282482")
    )
    builder.adjust(2, 1)
    return builder.as_markup()

def get_tag_choice_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text="Да, добавить @allwa", callback_data="tag_yes"),
        types.InlineKeyboardButton(text="Нет, без тега", callback_data="tag_no")
    )
    builder.adjust(2)
    return builder.as_markup()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    _, _, _, status = db.get_session()
    status_html = '<tg-emoji emoji-id="5992199545151295755">🟢</tg-emoji> Активна' if "Активна" in status else '<tg-emoji emoji-id="5877413297170419326">🔴</tg-emoji> Не авторизован'
    
    text = (
        '<tg-emoji emoji-id="5958376256788502078">⭐️</tg-emoji> <b>Добро пожаловать в Marketer Bot!</b>\n\n'
        'Бот для рассылки сообщений.\n\n'
        f'<b>Статус:</b> {status_html}'
    )
    await message.answer(text=text, reply_markup=get_main_keyboard(), parse_mode="HTML")

# --- ЛОГИКА АВТОРИЗАЦИИ ---

@dp.callback_query(F.data == "btn_create_session")
async def start_auth(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer('<tg-emoji emoji-id="5794182096603847292">1️⃣</tg-emoji> Введите ваш <b>API_ID</b>:', parse_mode="HTML")
    await state.set_state(AuthStates.waiting_for_api_id)
    await callback.answer()

@dp.message(AuthStates.waiting_for_api_id)
async def process_api_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer('<tg-emoji emoji-id="5954175920506933873">❌</tg-emoji> API_ID должен состоять только из цифр.', parse_mode="HTML")
        return
    await state.update_data(user_api_id=int(message.text.strip()))
    await message.answer('<tg-emoji emoji-id="5794303034292968945">2️⃣</tg-emoji> Теперь введите ваш <b>API_HASH</b>:', parse_mode="HTML")
    await state.set_state(AuthStates.waiting_for_api_hash)

@dp.message(AuthStates.waiting_for_api_hash)
async def process_api_hash(message: types.Message, state: FSMContext):
    await state.update_data(user_api_hash=message.text.strip())
    await message.answer('<tg-emoji emoji-id="5794031944547178894">3️⃣</tg-emoji> Введите номер телефона:', parse_mode="HTML")
    await state.set_state(AuthStates.waiting_for_phone)

@dp.message(AuthStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "")
    await message.answer('<tg-emoji emoji-id="5900104897885376843">⏳</tg-emoji> Соединение с сервером...', parse_mode="HTML")
    data = await state.get_data()
    client = Client(f"temp_{message.from_user.id}", api_id=data["user_api_id"], api_hash=data["user_api_hash"], in_memory=True)
    await client.connect()
    try:
        code_info = await client.send_code(phone)
        raw_clients[message.from_user.id] = {"client": client, "phone": phone, "api_id": data["user_api_id"], "api_hash": data["user_api_hash"], "phone_code_hash": code_info.phone_code_hash}
        await message.answer('<tg-emoji emoji-id="6034962180875490251">🔓</tg-emoji> Код подтверждения отправлен. Введите его:', parse_mode="HTML")
        await state.set_state(AuthStates.waiting_for_code)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        await client.disconnect()
        await state.clear()

@dp.message(AuthStates.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    user_data = raw_clients.get(message.from_user.id)
    try:
        await user_data["client"].sign_in(user_data["phone"], user_data["phone_code_hash"], message.text.strip())
        db.save_session(user_data["phone"], user_data["api_id"], user_data["api_hash"], await user_data["client"].export_session_string())
        await message.answer('<tg-emoji emoji-id="5920052658743283381">✅</tg-emoji> Успешная авторизация!', reply_markup=get_main_keyboard(), parse_mode="HTML")
        await user_data["client"].disconnect()
        raw_clients.pop(message.from_user.id)
        await state.clear()
    except SessionPasswordNeeded:
        await message.answer('<tg-emoji emoji-id="6005570495603282482">🔑</tg-emoji> Требуется 2FA пароль. Введите его:', parse_mode="HTML")
        await state.set_state(AuthStates.waiting_for_2fa)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(AuthStates.waiting_for_2fa)
async def process_2fa(message: types.Message, state: FSMContext):
    user_data = raw_clients.get(message.from_user.id)
    await user_data["client"].check_password(message.text.strip())
    db.save_session(user_data["phone"], user_data["api_id"], user_data["api_hash"], await user_data["client"].export_session_string())
    await message.answer('<tg-emoji emoji-id="5920052658743283381">✅</tg-emoji> 2FA успешно пройдена!', reply_markup=get_main_keyboard(), parse_mode="HTML")
    await user_data["client"].disconnect()
    raw_clients.pop(message.from_user.id)
    await state.clear()

# --- ЛОГИКА РАССЫЛКИ ---

@dp.callback_query(F.data == "btn_view_logs")
async def view_logs(callback: types.CallbackQuery):
    logs = db.get_logs(12)
    text = '<tg-emoji emoji-id="5875431869842985304">🎛</tg-emoji> <b>Последние события системы:</b>\n\n' + "\n".join(logs) if logs else '<tg-emoji emoji-id="5881702736843511327">⚠️</tg-emoji> Логи пусты.'
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "btn_start_broadcast")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer('<tg-emoji emoji-id="5877396173135811032">⌨️</tg-emoji> Введите рекламный текст:', parse_mode="HTML")
    await state.set_state(BroadcastStates.waiting_for_text)
    await callback.answer()

@dp.message(BroadcastStates.waiting_for_text)
async def process_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer('<tg-emoji emoji-id="5891080694855111159">🎭</tg-emoji> Добавить @allwa?', reply_markup=get_tag_choice_keyboard(), parse_mode="HTML")
    await state.set_state(BroadcastStates.waiting_for_tag_choice)

@dp.callback_query(BroadcastStates.waiting_for_tag_choice)
async def process_tag(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = f'{data["text"]} <a href="tg://resolve?domain=allwa">.</a>' if callback.data == "tag_yes" else data["text"]
    await state.update_data(text=text)
    await callback.message.answer('<tg-emoji emoji-id="5900104897885376843">⏳</tg-emoji> Укажите задержку (секунды):', parse_mode="HTML")
    await state.set_state(BroadcastStates.waiting_for_cooldown)
    await callback.answer()

@dp.message(BroadcastStates.waiting_for_cooldown)
async def process_cooldown(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("⚠️ Введите целое число.")
        return
    await state.update_data(cooldown=int(message.text))
    await message.answer('<tg-emoji emoji-id="5877680341057015789">📁</tg-emoji> Теперь список чатов:', parse_mode="HTML")
    await state.set_state(BroadcastStates.waiting_for_chats)

@dp.message(BroadcastStates.waiting_for_chats)
async def process_chats(message: types.Message, state: FSMContext):
    data = await state.get_data()
    asyncio.create_task(userbot_worker.start_broadcast_task(data["text"], message.text.split("\n"), data["cooldown"]))
    await message.answer('<tg-emoji emoji-id="5825794181183836432">✔️</tg-emoji> Рассылка запущена!', parse_mode="HTML")
    await state.clear()

async def main():
    db.init_db()
    print("Marketer Bot запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
