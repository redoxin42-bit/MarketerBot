import asyncio
import re
from pyrogram import Client
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import FloodWait, PeerFlood, UserBannedInChannel, ChatWriteForbidden
import database as db

# Словарь для отслеживания активных задач рассылки {user_id: asyncio.Task}
active_tasks = {}

def stop_broadcast_task(user_id: int) -> bool:
    """Отменяет выполнение активной задачи рассылки для указанного user_id."""
    task = active_tasks.get(user_id)
    if task and not task.done():
        task.cancel()
        return True
    return False

async def check_and_handle_op(client: Client, chat_id: str or int):
    try:
        async for message in client.get_chat_history(chat_id, limit=3):
            if (message.from_user and message.from_user.is_bot) or message.sender_chat:
                text = message.text or message.caption or ""
                
                if "подпис" in text.lower() or "sub" in text.lower():
                    links = []
                    
                    for m in re.finditer(r"(?:https?://)?t\.me/\+([\w_-]+)", text):
                        links.append(f"https://t.me/+{m.group(1)}")
                    
                    for m in re.finditer(r"(?:t\.me/|@)([\w_]+)", text):
                        username = m.group(1)
                        if username.lower() not in ["bot", "channel", "joinchat"] and username not in links:
                            links.append(username)
                    
                    for target_link in links:
                        try:
                            joined_chat = await client.join_chat(target_link)
                            db.add_log(f"🔗 Найдена ОП! Юзербот вступил в канал/чат: {target_link}")
                            
                            await client.archive_chats(chat_ids=[joined_chat.id])
                            db.add_log(f"📦 Канал {target_link} успешно отправлен в архив.")
                            return True
                        except Exception as join_err:
                            db.add_log(f"❌ Ошибка вступления/архивации ОП ({target_link}): {join_err}")
    except Exception as e:
        db.add_log(f"🛠 Ошибка проверки ОП: {e}")
    return False

async def start_broadcast_task(message_text: str, cooldown: int, target_type: str, chat_list: list = None, user_id: int = None):
    if user_id:
        active_tasks[user_id] = asyncio.current_task()

    session_string, api_id, api_hash, _ = db.get_session()
    if not session_string:
        db.add_log("❌ Критическая ошибка: В базе данных нет активной сессии.")
        if user_id:
            active_tasks.pop(user_id, None)
        return

    app = Client(
        "sender_session",
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
        in_memory=True
    )

    try:
        await app.start()
        
        if target_type == "all":
            db.add_log("🔍 Начат автоматический сбор всех групп аккаунта...")
            chat_list = []
            async for dialog in app.get_dialogs():
                if dialog.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
                    chat_list.append(dialog.chat.id)
        
        if not chat_list:
            db.add_log("⚠️ Отмена: Целевые чаты для запуска рассылки не найдены.")
            return

        db.add_log(f"🚀 Запуск рассылки! Всего объектов к обработке: {len(chat_list)}")
        
        for target_chat in chat_list:
            if isinstance(target_chat, str):
                target_chat = target_chat.strip()
                if not target_chat:
                    continue
                if target_chat.startswith("-100") or target_chat.isdigit() or (target_chat.startswith("-") and target_chat[1:].isdigit()):
                    target_chat = int(target_chat)
                
            try:
                await app.send_message(chat_id=target_chat, text=message_text, parse_mode=ParseMode.HTML)
                db.add_log(f"✅ Отправлено в чат: {target_chat}")
                
                await asyncio.sleep(2.5)
                
                has_op = await check_and_handle_op(app, target_chat)
                if has_op:
                    await app.send_message(chat_id=target_chat, text=message_text, parse_mode=ParseMode.HTML)
                    db.add_log(f"🔄 Реклама отправлена повторно в {target_chat} после успешного обхода ОП.")

            except FloodWait as e:
                db.add_log(f"⚠️ Ограничение FloodWait от Telegram! Пауза {e.value} сек.")
                await asyncio.sleep(e.value)
                await app.send_message(chat_id=target_chat, text=message_text, parse_mode=ParseMode.HTML)
                db.add_log(f"✅ Успешно отправлено после паузы FloodWait: {target_chat}")
                
            except (PeerFlood, UserBannedInChannel, ChatWriteForbidden):
                db.add_log(f"🚫 Пропуск чата {target_chat}: Нет прав писать / Спамблок / Бан.")
            except Exception as e:
                db.add_log(f"❌ Ошибка доставки в {target_chat}: {str(e)[:50]}")

            await asyncio.sleep(cooldown)
            
        db.add_log("🏁 Рассылка полностью завершена!")
        
    except asyncio.CancelledError:
        db.add_log("🛑 Процесс рассылки был принудительно прерван пользователем.")
    except Exception as general_error:
        db.add_log(f"🚨 Критический сбой движка рассылки: {general_error}")
    finally:
        if user_id:
            active_tasks.pop(user_id, None)
        try:
            await app.stop()
        except Exception:
            pass
