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
    waiting_for_target_type = State()  
    waiting_for_chats = State()        
    waiting_for_cooldown = State()

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

def get_target_choice_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text="🌍 По всем чатам", callback_data="target_all"),
        types.InlineKeyboardButton(text="🎯 По выбранным", callback_data="target_selected")
    )
    builder.adjust(2)
    return builder.as_markup()

def get_stop_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text="🛑 Остановить рассылку", callback_data="btn_stop_broadcast")
    )
    return builder.as_markup()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    _, _, _, status = db.get_session()
    status_html = '<tg-emoji emoji-id="5992199545151295755">🟢</tg-emoji> Активна' if "Активна" in status else '<tg-emoji emoji-id="5877413297170419326">🔴</tg-emoji> Не авторизован'
    
    text = (
        '<tg-emoji emoji-id="5958376256788502078">⭐️</tg-emoji> <b>Добро пожаловать в Marketer Bot!</b>\n\n'
        'Бот для автоматической рассылки сообщений.\n\n'
        f'<b>Статус аккаунта:</b> {status_html}'
    )
    await message.answer(text=text, reply_markup=get_main_keyboard(), parse_mode="HTML")

# --- ПРОЦЕСС АВТОРИЗАЦИИ СЕССИИ ---

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
    await message.answer('<tg-emoji emoji-id="5900104897885376843">⏳</tg-emoji> Подключение к серверам Telegram...', parse_mode="HTML")
    data = await state.get_data()
    client = Client(f"temp_{message.from_user.id}", api_id=data["user_api_id"], api_hash=data["user_api_hash"], in_memory=True)
    await client.connect()
    try:
        code_info = await client.send_code(phone)
        raw_clients[message.from_user.id] = {"client": client, "phone": phone, "api_id": data["user_api_id"], "api_hash": data["user_api_hash"], "phone_code_hash": code_info.phone_code_hash}
        await message.answer('<tg-emoji emoji-id="6034962180875490251">🔓</tg-emoji> Код подтверждения отправлен. Введите его:', parse_mode="HTML")
        await state.set_state(AuthStates.waiting_for_code)
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки кода: {e}")
        await client.disconnect()
        await state.clear()

@dp.message(AuthStates.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    user_data = raw_clients.get(message.from_user.id)
    try:
        await user_data["client"].sign_in(user_data["phone"], user_data["phone_code_hash"], message.text.strip())
        db.save_session(user_data["phone"], user_data["api_id"], user_data["api_hash"], await user_data["client"].export_session_string())
        await message.answer('<tg-emoji emoji-id="5920052658743283381">✅</tg-emoji> Сессия успешно создана и сохранена!', reply_markup=get_main_keyboard(), parse_mode="HTML")
        await user_data["client"].disconnect()
        raw_clients.pop(message.from_user.id)
        await state.clear()
    except SessionPasswordNeeded:
        await message.answer('<tg-emoji emoji-id="6005570495603282482">🔑</tg-emoji> Обнаружена двухфакторная аутентификация (2FA). Введите ваш пароль:', parse_mode="HTML")
        await state.set_state(AuthStates.waiting_for_2fa)
    except Exception as e:
        await message.answer(f"❌ Ошибка входа: {e}")

@dp.message(AuthStates.waiting_for_2fa)
async def process_2fa(message: types.Message, state: FSMContext):
    user_data = raw_clients.get(message.from_user.id)
    try:
        await user_data["client"].check_password(message.text.strip())
        db.save_session(user_data["phone"], user_data["api_id"], user_data["api_hash"], await user_data["client"].export_session_string())
        await message.answer('<tg-emoji emoji-id="5920052658743283381">✅</tg-emoji> Пароль 2FA принят! Авторизация успешна.', reply_markup=get_main_keyboard(), parse_mode="HTML")
        await user_data["client"].disconnect()
        raw_clients.pop(message.from_user.id)
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Неверный пароль 2FA: {e}")

# --- ПРОСМОТР ЛОГОВ ---

@dp.callback_query(F.data == "btn_view_logs")
async def view_logs(callback: types.CallbackQuery):
    logs = db.get_logs(15)
    text = '<tg-emoji emoji-id="5875431869842985304">🎛</tg-emoji> <b>Логи работы системы:</b>\n\n' + "\n".join(logs) if logs else '<tg-emoji emoji-id="5881702736843511327">⚠️</tg-emoji> История логов пуста.'
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

# --- НАСТРОЙКА И ЗАПУСК РАССЫЛКИ ---

@dp.callback_query(F.data == "btn_start_broadcast")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    # ИСПРАВЛЕНО: Проверка наличия активной сессии перед запуском
    session_string, _, _, _ = db.get_session()
    if not session_string:
        await callback.message.answer('<tg-emoji emoji-id="5954175920506933873">❌</tg-emoji> <b>Ошибка: Подключите сессию!</b> перед созданием рассылки.', parse_mode="HTML")
        await callback.answer()
        return

    await callback.message.answer('<tg-emoji emoji-id="5877396173135811032">⌨️</tg-emoji> Введите текст вашего рекламного сообщения:', parse_mode="HTML")
    await state.set_state(BroadcastStates.waiting_for_text)
    await callback.answer()

@dp.message(BroadcastStates.waiting_for_text)
async def process_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer('<tg-emoji emoji-id="5891080694855111159">🎭</tg-emoji> Желаете вшить скрытый тег @allwa?', reply_markup=get_tag_choice_keyboard(), parse_mode="HTML")
    await state.set_state(BroadcastStates.waiting_for_tag_choice)

@dp.callback_query(BroadcastStates.waiting_for_tag_choice)
async def process_tag(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = f'{data["text"]}<a href="tg://resolve?domain=allwa">&#8203;</a>' if callback.data == "tag_yes" else data["text"]
    await state.update_data(text=text)
    
    await callback.message.answer('🎯 <b>Выберите область действия рассылки:</b>', reply_markup=get_target_choice_keyboard(), parse_mode="HTML")
    await state.set_state(BroadcastStates.waiting_for_target_type)
    await callback.answer()

@dp.callback_query(BroadcastStates.waiting_for_target_type)
async def process_target_type(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "target_all":
        await state.update_data(target_type="all")
        await callback.message.answer('<tg-emoji emoji-id="5900104897885376843">⏳</tg-emoji> Укажите время задержки (CoolDown) между чатами в секундах:', parse_mode="HTML")
        await state.set_state(BroadcastStates.waiting_for_cooldown)
    elif callback.data == "target_selected":
        await state.update_data(target_type="selected")
        await callback.message.answer('<tg-emoji emoji-id="5877680341057015789">📁</tg-emoji> Введите ID чатов для рассылки (<b>каждый ID пишите с новой строки</b>):', parse_mode="HTML")
        await state.set_state(BroadcastStates.waiting_for_chats)
    await callback.answer()

@dp.message(BroadcastStates.waiting_for_chats)
async def process_chats(message: types.Message, state: FSMContext):
    raw_ids = [line.strip() for line in message.text.split("\n") if line.strip()]
    if not raw_ids:
        await message.answer("⚠️ Вы не ввели ни одного ID.")
        return

    status_msg = await message.answer('<tg-emoji emoji-id="5900104897885376843">⏳</tg-emoji> <b>Проверяю существование указанных чатов...</b>', parse_mode="HTML")
    
    session_string, api_id, api_hash, _ = db.get_session()
    app = Client("validator_session", api_id=api_id, api_hash=api_hash, session_string=session_string, in_memory=True)
    
    invalid_chats = []
    try:
        await app.start()
        for chat_item in raw_ids:
            chat_target = chat_item
            if chat_target.startswith("-100") or chat_target.isdigit() or (chat_target.startswith("-") and chat_target[1:].isdigit()):
                chat_target = int(chat_target)
            
            try:
                # Попытка получить информацию о чате для валидации его существования
                await app.get_chat(chat_target)
            except Exception:
                invalid_chats.append(chat_item)
        await app.stop()
    except Exception as e:
        await status_msg.delete()
        await message.answer(f"❌ Критическая ошибка при валидации сессии: {e}")
        return

    await status_msg.delete()

    # ИСПРАВЛЕНО: Если найдены некорректные ID / слова, выводим ошибку
    if invalid_chats:
        await message.answer(
            f'<tg-emoji emoji-id="5954175920506933873">❌</tg-emoji> <b>Ошибка: Такого чата не существует</b> (или юзербот в нём не состоит):\n'
            f'<code>' + ", ".join(invalid_chats) + '</code>\n\n'
            f'Пожалуйста, введите список корректных ID заново:', 
            parse_mode="HTML"
        )
        return

    await state.update_data(chats=raw_ids)
    await message.answer('<tg-emoji emoji-id="5900104897885376843">⏳</tg-emoji> Укажите время задержки (CoolDown) между чатами в секундах:', parse_mode="HTML")
    await state.set_state(BroadcastStates.waiting_for_cooldown)

@dp.message(BroadcastStates.waiting_for_cooldown)
async def process_cooldown(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("⚠️ Ошибка: укажите корректное число секунд.")
        return
    cooldown_val = int(message.text)
    data = await state.get_data()
    
    asyncio.create_task(
        userbot_worker.start_broadcast_task(
            message_text=data["text"], 
            cooldown=cooldown_val, 
            target_type=data["target_type"], 
            chat_list=data.get("chats"),
            user_id=message.from_user.id
        )
    )
    
    await message.answer(
        '<tg-emoji emoji-id="5825794181183836432">✔️</tg-emoji> Рассылка добавлена в очередь и успешно запущена!', 
        reply_markup=get_stop_keyboard(), 
        parse_mode="HTML"
    )
    await state.clear()

@dp.callback_query(F.data == "btn_stop_broadcast")
async def stop_broadcast_handler(callback: types.CallbackQuery):
    was_stopped = userbot_worker.stop_broadcast_task(callback.from_user.id)
    
    if was_stopped:
        await callback.message.edit_text(
            "🛑 <b>Рассылка принудительно остановлена пользователем!</b>", 
            parse_mode="HTML", 
            reply_markup=None
        )
        db.add_log(f"👤 Пользователь {callback.from_user.id} нажал кнопку экстренной остановки.")
    else:
        await callback.message.edit_text(
            "⚠️ <b>Процесс рассылки не найден:</b> возможно, она уже завершилась самостоятельно.", 
            parse_mode="HTML", 
            reply_markup=None
        )
    await callback.answer()

async def main():
    db.init_db()
    print("Marketer Bot запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
