"""Personal-DM delivery helpers used by the main routine bot."""

import asyncio
import logging
import os
from datetime import timedelta
from io import BytesIO

from telegram import InputFile, InputMediaPhoto
from telegram.error import Forbidden, RetryAfter, TelegramError

from db_utils import async_get_all_values, users_sheet


LOGGER = logging.getLogger("routine_bot.notifications")
_DELIVERY_LOCK = asyncio.Lock()


def _private_user_id(value) -> str:
    """Accept only a positive Telegram user ID, never a group/channel ID."""
    user_id = str(value or "").strip()
    return user_id if user_id.isdigit() and int(user_id) > 0 else ""


def recipients_from_users(users_records):
    """Build one direct-message target per registered main-bot user."""
    recipients = []
    seen_user_ids = set()
    for row_number, row in enumerate(users_records[1:], start=2):
        if not row:
            continue
        user_id = _private_user_id(row[0] if row else "")
        if not user_id:
            LOGGER.warning("Ignoring invalid Users row %s for personal notification", row_number)
            continue
        if user_id in seen_user_ids:
            LOGGER.warning("Ignoring duplicate Users row for user_id=%s", user_id)
            continue
        seen_user_ids.add(user_id)
        recipients.append({"user_id": user_id, "chat_id": user_id})
    return recipients


async def get_personal_dm_recipients():
    """Load registered members who can be targeted through the main bot."""
    return recipients_from_users(await async_get_all_values(users_sheet))


def _delivery_interval_seconds() -> float:
    try:
        return max(
            0.04,
            float(os.environ.get("PERSONAL_NOTIFICATION_SEND_INTERVAL_SECONDS", "0.05")),
        )
    except ValueError:
        LOGGER.warning("Invalid PERSONAL_NOTIFICATION_SEND_INTERVAL_SECONDS; using 0.05")
        return 0.05


def _retry_after_seconds(error: RetryAfter) -> float:
    value = getattr(error, "retry_after", 1)
    if isinstance(value, timedelta):
        return max(1.0, value.total_seconds())
    try:
        return max(1.0, float(value))
    except (TypeError, ValueError):
        return 1.0


async def _send_with_retry(operation, *, label: str, user_id: str):
    try:
        return await operation()
    except RetryAfter as error:
        delay = _retry_after_seconds(error)
        LOGGER.warning(
            "%s rate-limited for user_id=%s; retrying in %.1f seconds",
            label,
            user_id,
            delay,
        )
        await asyncio.sleep(delay)
        return await operation()


def _trim_message(value: str, limit: int = 4096) -> str:
    value = str(value or "").strip()
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


async def send_text_notifications(
    context,
    message_factory,
    *,
    label: str,
    parse_mode: str | None = None,
    recipients=None,
) -> int:
    """Send individually constructed text from the already-running main bot."""
    targets = list(recipients) if recipients is not None else await get_personal_dm_recipients()
    if not targets:
        LOGGER.info("No registered direct-message recipients for %s", label)
        return 0

    bot = getattr(context, "bot", None)
    if bot is None:
        LOGGER.error("Main bot context is unavailable; skipped %s", label)
        return 0

    delivered = 0
    interval = _delivery_interval_seconds()
    async with _DELIVERY_LOCK:
        for index, recipient in enumerate(targets):
            user_id = recipient["user_id"]
            try:
                text = _trim_message(message_factory(recipient))
                if not text:
                    LOGGER.warning("Skipped empty %s message for user_id=%s", label, user_id)
                    continue
                await _send_with_retry(
                    lambda: bot.send_message(
                        chat_id=recipient["chat_id"],
                        text=text,
                        parse_mode=parse_mode,
                    ),
                    label=label,
                    user_id=user_id,
                )
            except TelegramError as error:
                LOGGER.error(
                    "%s delivery failed for user_id=%s: %s",
                    label,
                    user_id,
                    error,
                )
            except Exception as error:
                LOGGER.error(
                    "%s message construction failed for user_id=%s",
                    label,
                    user_id,
                    exc_info=(type(error), error, error.__traceback__),
                )
            else:
                delivered += 1
                LOGGER.info("Delivered %s through main bot to user_id=%s", label, user_id)

            if index < len(targets) - 1:
                await asyncio.sleep(interval)

    LOGGER.info("%s delivery complete: %s/%s recipients", label, delivered, len(targets))
    return delivered


async def _send_card_fallback(bot, recipient, image_payloads, caption: str, label: str) -> bool:
    """Fall back to individual photos when Telegram rejects a media group."""
    sent = 0
    interval = _delivery_interval_seconds()
    for index, (_, payload) in enumerate(image_payloads):
        try:
            await _send_with_retry(
                lambda payload=payload, index=index: bot.send_photo(
                    chat_id=recipient["chat_id"],
                    photo=InputFile(
                        BytesIO(payload),
                        filename=f"weekly_card_{index + 1}.png",
                    ),
                    caption=_trim_message(caption, limit=1024) if index == 0 else None,
                ),
                label=f"{label} fallback",
                user_id=recipient["user_id"],
            )
        except TelegramError as error:
            LOGGER.error(
                "%s fallback photo %s failed for user_id=%s: %s",
                label,
                index + 1,
                recipient["user_id"],
                error,
            )
        else:
            sent += 1
        if index < len(image_payloads) - 1:
            await asyncio.sleep(interval)
    return sent > 0


async def send_media_group_notifications(
    context,
    card_images,
    *,
    caption: str,
    label: str,
    recipients=None,
) -> int:
    """Send fresh card-news uploads from the main bot to each member's DM."""
    image_payloads = [
        (f"weekly_card_{index + 1}.png", image.getvalue())
        for index, image in enumerate(card_images)
        if image is not None
    ]
    if len(image_payloads) < 2:
        LOGGER.error("%s requires at least two generated card images", label)
        return 0

    targets = list(recipients) if recipients is not None else await get_personal_dm_recipients()
    if not targets:
        LOGGER.info("No registered direct-message recipients for %s", label)
        return 0

    bot = getattr(context, "bot", None)
    if bot is None:
        LOGGER.error("Main bot context is unavailable; skipped %s", label)
        return 0

    delivered = 0
    interval = _delivery_interval_seconds()
    async with _DELIVERY_LOCK:
        for index, recipient in enumerate(targets):
            user_id = recipient["user_id"]

            async def send_group():
                media = [
                    InputMediaPhoto(
                        media=InputFile(BytesIO(payload), filename=filename),
                        caption=_trim_message(caption, limit=1024) if item_index == 0 else None,
                    )
                    for item_index, (filename, payload) in enumerate(image_payloads)
                ]
                return await bot.send_media_group(chat_id=recipient["chat_id"], media=media)

            try:
                await _send_with_retry(send_group, label=label, user_id=user_id)
            except Forbidden as error:
                LOGGER.error(
                    "%s delivery blocked for user_id=%s: %s",
                    label,
                    user_id,
                    error,
                )
            except TelegramError as error:
                LOGGER.warning(
                    "%s media group failed for user_id=%s; trying individual photos: %s",
                    label,
                    user_id,
                    error,
                )
                if await _send_card_fallback(bot, recipient, image_payloads, caption, label):
                    delivered += 1
                    LOGGER.info("Delivered %s fallback to user_id=%s", label, user_id)
            except Exception as error:
                LOGGER.error(
                    "%s image delivery failed for user_id=%s",
                    label,
                    user_id,
                    exc_info=(type(error), error, error.__traceback__),
                )
            else:
                delivered += 1
                LOGGER.info("Delivered %s through main bot to user_id=%s", label, user_id)

            if index < len(targets) - 1:
                await asyncio.sleep(interval)

    LOGGER.info("%s delivery complete: %s/%s recipients", label, delivered, len(targets))
    return delivered
