import asyncio
import re
from pyrogram import Client
from pyrogram.errors import FloodWait, PeerFlood, UserBannedInChannel, ChatWriteForbidden
import database as db
import config

async def check_and_handle_op(client: Client, chat_id: str or int):
    """
    Сканирует последние сообщения в чате. Если защитный бот требует ОП,
    юзербот переходит по ссылке, подписывается и убирает канал в архив.
    """
    try:
        async for message in client.get_chat_history(chat_id, limit=3):
            if message.from_user and message.from_user.is_bot:
                text = message.text or message.caption or ""
                # Ищем триггеры обязательной подписки и ссылки на каналы
                if "подпиш" in text.lower() or "sub" in text.lower():
                    links = re.findall(r"(?:t\.me/|@)([\w_]+)", text)
                    for link in links:
                        if link.lower() not in ["bot", "channel"]: # Исключаем мусорные совпадения
                            try:
                                # Вступаем в канал ОП
                                joined_chat = await client.join_chat(link)
                                db.add_log(f"🔗 Найдена ОП! Вступил в канал: @{link}")
                                
                                # Отправляем канал в архив
                                await client.archive_chats(chat_ids=[joined_chat.id])
                                db.add_log(f"📦 Канал @{link} успешно убран в архив.")
                                return True
                            except Exception as e:
                                db.add_log(f"❌ Не удалось обработать ОП для @{link}: {e}")
    except Exception:
        pass
    return False

async def start_broadcast_task(message_text: str, chat_list: list):
    """
    Основной асинхронный цикл рассылки по списку чатов
    """
    session_data = db.get_session()
    if not session_data[0]:
        db.add_log("❌ Ошибка рассылки: Отсутствует активная сессия аккаунта.")
        return

    session_string = session_data[0]
    cooldown = db.get_cooldown()

    # Запускаем клиент Pyrogram через String Session
    app = Client(
        "sender_session",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=session_string,
        in_memory=True
    )

    try:
        await app.start()
        db.add_log(f"🚀 Рассылка запущена! Всего целей: {len(chat_list)}")
        
        for target_chat in chat_list:
            target_chat = target_chat.strip()
            if not target_chat:
                continue
                
            try:
                # Пытаемся отправить сообщение в чат
                await app.send_message(chat_id=target_chat, text=message_text)
                db.add_log(f"✅ Отправлено в чат: {target_chat}")
                
                # Небольшая пауза и проверка на появление требований ОП от локальных ботов-модераторов
                await asyncio.sleep(2)
                has_op = await check_and_handle_op(app, target_chat)
                if has_op:
                    # Если была ОП, пробуем продублировать пост на случай, если первый удалили
                    await app.send_message(chat_id=target_chat, text=message_text)
                    db.add_log(f"🔄 Повторно отправлено в {target_chat} после выполнения ОП.")

            except FloodWait as e:
                db.add_log(f"⚠️ FloodWait от Telegram! Пауза на {e.value} сек.")
                await asyncio.sleep(e.value)
                # Повторная попытка после ожидания флуда
                await app.send_message(chat_id=target_chat, text=message_text)
                db.add_log(f"✅ Отправлено после FloodWait: {target_chat}")
                
            except (PeerFlood, UserBannedInChannel, ChatWriteForbidden):
                db.add_log(f"🚫 Ограничение в чате {target_chat} (Бан или Флудблок аккаунта).")
            except Exception as e:
                db.add_log(f"❌ Ошибка отправки в {target_chat}: {str(e)[:50]}")

            # Соблюдение заданного CoolDown между чатами
            await asyncio.sleep(cooldown)
            
        db.add_log("🏁 Рассылка успешно завершена!")
    except Exception as general_error:
        db.add_log(f"🚨 Критическая ошибка движка рассылки: {general_error}")
    finally:
        await app.stop()
