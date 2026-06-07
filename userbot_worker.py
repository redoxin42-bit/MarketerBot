import asyncio
import re
from pyrogram import Client
from pyrogram.errors import FloodWait, PeerFlood, UserBannedInChannel, ChatWriteForbidden
import database as db

async def check_and_handle_op(client: Client, chat_id: str or int):
    try:
        async for message in client.get_chat_history(chat_id, limit=3):
            if message.from_user and message.from_user.is_bot:
                text = message.text or message.caption or ""
                if "подпиш" in text.lower() or "sub" in text.lower():
                    links = re.findall(r"(?:t\.me/|@)([\w_]+)", text)
                    for link in links:
                        if link.lower() not in ["bot", "channel"]:
                            try:
                                joined_chat = await client.join_chat(link)
                                db.add_log(f"🔗 Найдена ОП! Вступил в канал: @{link}")
                                await client.archive_chats(chat_ids=[joined_chat.id])
                                db.add_log(f"📦 Канал @{link} успешно убран в архив.")
                                return True
                            except Exception as e:
                                db.add_log(f"❌ Не удалось обработать ОП для @{link}: {e}")
    except Exception:
        pass
    return False

async def start_broadcast_task(message_text: str, chat_list: list):
    session_string, api_id, api_hash, _ = db.get_session()
    if not session_string:
        db.add_log("❌ Ошибка рассылки: Отсутствует активная сессия аккаунта.")
        return

    cooldown = db.get_cooldown()

    app = Client(
        "sender_session",
        api_id=api_id,
        api_hash=api_hash,
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
                await app.send_message(chat_id=target_chat, text=message_text)
                db.add_log(f"✅ Отправлено в чат: {target_chat}")
                
                await asyncio.sleep(2)
                has_op = await check_and_handle_op(app, target_chat)
                if has_op:
                    await app.send_message(chat_id=target_chat, text=message_text)
                    db.add_log(f"🔄 Повторно отправлено в {target_chat} после выполнения ОП.")

            except FloodWait as e:
                db.add_log(f"⚠️ FloodWait от Telegram! Пауза на {e.value} сек.")
                await asyncio.sleep(e.value)
                await app.send_message(chat_id=target_chat, text=message_text)
                db.add_log(f"✅ Отправлено после FloodWait: {target_chat}")
                
            except (PeerFlood, UserBannedInChannel, ChatWriteForbidden):
                db.add_log(f"🚫 Ограничение в чате {target_chat} (Бан или Флудблок).")
            except Exception as e:
                db.add_log(f"❌ Ошибка отправки в {target_chat}: {str(e)[:50]}")

            await asyncio.sleep(cooldown)
            
        db.add_log("🏁 Рассылка успешно завершена!")
    except Exception as general_error:
        db.add_log(f"🚨 Критическая ошибка движка рассылки: {general_error}")
    finally:
        await app.stop()
