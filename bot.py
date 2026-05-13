"""
Бот «Запомни навсегда» — MVP v2
Поддерживает: фото + текст
Стек: python-telegram-bot + supabase-py + apscheduler
"""

import os
import logging
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client, Client
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─── Настройки ────────────────────────────────────────────────────────────────
BOT_TOKEN    = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

# Интервалы повторений в днях: 1й → 3й → 7й → 21й → 60й
INTERVALS = [1, 3, 7, 21, 60]

# ─── Инициализация ────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ─── Вспомогательные функции ──────────────────────────────────────────────────

def next_review_date(repetition_number: int) -> str:
    """Возвращает дату следующего повторения в формате YYYY-MM-DD."""
    days = INTERVALS[repetition_number] if repetition_number < len(INTERVALS) else 90
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


def get_cards_due_today(user_id: int) -> list:
    today = datetime.now(timezone.utc).date().isoformat()
    result = (
        supabase.table("cards")
        .select("*")
        .eq("user_id", user_id)
        .eq("completed", "false")
        .lte("next_review", today)
        .execute()
    )
    return result.data or []


def get_all_active_users() -> list:
    result = supabase.table("cards").select("user_id").eq("completed", "false").execute()
    return list({row["user_id"] for row in (result.data or [])})


def save_card(user_id: int, card_type: str, file_id: str = None, text_content: str = None, caption: str = "") -> None:
    """Сохраняет карточку любого типа в базу."""
    supabase.table("cards").insert({
        "user_id":          user_id,
        "card_type":        card_type,       # "photo" или "text"
        "file_id":          file_id,         # только для фото
        "text_content":     text_content,    # только для текста
        "caption":          caption,
        "added_at":         datetime.now(timezone.utc).isoformat(),
        "next_review":      next_review_date(0),
        "repetition_count": 0,
        "completed":        False,
    }).execute()


# ─── Отправка карточки пользователю ──────────────────────────────────────────

async def send_card(bot, user_id: int, card: dict, header: str) -> None:
    """Отправляет одну карточку — фото или текст — с заголовком."""
    if card["card_type"] == "photo":
        caption = header
        if card.get("caption"):
            caption += f"\n\n{card['caption']}"
        await bot.send_photo(chat_id=user_id, photo=card["file_id"], caption=caption)

    elif card["card_type"] == "text":
        text = f"{header}\n\n{card['text_content']}"
        await bot.send_message(chat_id=user_id, text=text)


async def send_due_cards(bot, user_id: int, cards: list) -> None:
    """Отправляет все карточки на сегодня и обновляет расписание."""
    for card in cards:
        try:
            await send_card(bot, user_id, card, header="📚 Сегодня мы повторяем вот это:")

            rep_count = card["repetition_count"] + 1

            if rep_count >= len(INTERVALS):
                # Все повторения пройдены
                supabase.table("cards").update({
                    "repetition_count": rep_count,
                    "next_review":      None,
                    "completed":        True,
                }).eq("id", card["id"]).execute()

                await bot.send_message(
                    chat_id=user_id,
                    text="✅ Эта карточка завершила все повторения — материал в долгосрочной памяти!"
                )
            else:
                supabase.table("cards").update({
                    "repetition_count": rep_count,
                    "next_review":      next_review_date(rep_count),
                }).eq("id", card["id"]).execute()

        except Exception as e:
            logger.error(f"Ошибка при отправке карточки {card.get('id')}: {e}")


# ─── Обработчики команд ───────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот для запоминания 🧠\n\n"
        "Работает просто:\n"
        "Пришли мне фото конспекта или напиши текст — "
        "я буду возвращать его тебе в нужный момент, пока не запомнишь.\n\n"
        "Интервалы повторений основаны на науке о памяти:\n"
        "через 1 день → 3 → 7 → 21 → 60\n\n"
        "Каждое повторение — материал держится дольше.\n\n"
        "Попробуй прямо сейчас — пришли что-нибудь 👇"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/start — начать\n"
        "/list — все мои карточки\n"
        "/today — повторить сегодняшние карточки вручную\n"
        "/help — эта справка\n\n"
        "Просто пришли фото или текст — я сохраню и буду напоминать."
    )


def review_schedule_text() -> str:
    """Возвращает текст с реальными датами повторений."""
    today = datetime.now(timezone.utc)
    lines = []
    for i, days in enumerate(INTERVALS):
        date = (today + timedelta(days=days)).strftime("%-d %b")
        lines.append(f"  {i+1}. Через {days} д. — {date}")
    return "\n".join(lines)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает фото и сохраняет как карточку типа photo."""
    user_id = update.effective_user.id
    photo   = update.message.photo[-1]
    caption = update.message.caption or ""

    try:
        save_card(user_id, card_type="photo", file_id=photo.file_id, caption=caption)
        await update.message.reply_text(
            "📷 Фото сохранено!\n\n"
            "Буду присылать его тебе:\n"
            f"{review_schedule_text()}\n\n"
            "Можешь добавлять ещё материал — фото или текст."
        )
    except Exception as e:
        logger.error(f"Ошибка сохранения фото для user {user_id}: {e}")
        await update.message.reply_text(
            "⚠️ Не удалось сохранить фото. Попробуй ещё раз через минуту."
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает текстовое сообщение и сохраняет как карточку типа text."""
    user_id = update.effective_user.id
    text    = update.message.text.strip()

    if len(text) < 5:
        await update.message.reply_text(
            "Слишком короткое сообщение.\n"
            "Пришли текст который хочешь запомнить, или фото конспекта."
        )
        return

    try:
        save_card(user_id, card_type="text", text_content=text)
        await update.message.reply_text(
            "✍️ Текст сохранён!\n\n"
            "Буду присылать его тебе:\n"
            f"{review_schedule_text()}\n\n"
            "Можешь добавлять ещё материал — фото или текст."
        )
    except Exception as e:
        logger.error(f"Ошибка сохранения текста для user {user_id}: {e}")
        await update.message.reply_text(
            "⚠️ Не удалось сохранить текст. Попробуй ещё раз через минуту."
        )


async def list_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все карточки пользователя."""
    user_id = update.effective_user.id
    result  = (
        supabase.table("cards")
        .select("*")
        .eq("user_id", user_id)
        .order("added_at")
        .execute()
    )
    cards = result.data or []

    if not cards:
        await update.message.reply_text(
            "У тебя пока нет карточек.\n"
            "Пришли фото или текст — начнём!"
        )
        return

    active    = [c for c in cards if not c.get("completed")]
    completed = [c for c in cards if c.get("completed")]

    lines = [f"Всего карточек: {len(cards)} ({len(active)} активных, {len(completed)} завершённых)\n"]

    for i, card in enumerate(active, 1):
        icon    = "📷" if card["card_type"] == "photo" else "✍️"
        preview = card.get("caption") or (card.get("text_content") or "")[:40] or "без подписи"
        next_r  = card.get("next_review", "—")
        count   = card.get("repetition_count", 0)
        lines.append(f"{i}. {icon} {preview[:35]}...\n   Повторений: {count}/5 · Следующее: {next_r}\n")

    await update.message.reply_text("\n".join(lines))


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повторение по запросу пользователя."""
    user_id = update.effective_user.id
    cards   = get_cards_due_today(user_id)

    if not cards:
        await update.message.reply_text(
            "На сегодня всё готово 🎉\n"
            "Следующее повторение придёт само — жди уведомления."
        )
        return

    await update.message.reply_text(f"На сегодня {len(cards)} карточек:")
    await send_due_cards(context.bot, user_id, cards)


# ─── Ежедневная рассылка ──────────────────────────────────────────────────────

async def daily_reminder(bot) -> None:
    """Запускается каждый день в 9:00 UTC — рассылает повторения всем пользователям."""
    logger.info("Запуск ежедневной рассылки...")
    for user_id in get_all_active_users():
        cards = get_cards_due_today(user_id)
        if not cards:
            continue
        try:
            await bot.send_message(
                chat_id=user_id,
                text=f"Привет! Время повторить материал 🧠\nНа сегодня {len(cards)} карточек:"
            )
            await send_due_cards(bot, user_id, cards)
        except Exception as e:
            logger.error(f"Ошибка рассылки для user {user_id}: {e}")


# ─── Запуск ───────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("help",   help_command))
    app.add_handler(CommandHandler("list",   list_cards))
    app.add_handler(CommandHandler("today",  today_command))
    app.add_handler(MessageHandler(filters.PHOTO,                    handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,  handle_text))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(daily_reminder, trigger="cron", hour=9, minute=0, args=[app.bot])
    scheduler.start()

    logger.info("Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
