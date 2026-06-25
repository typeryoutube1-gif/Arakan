"""
Main entry point for Rakhine Air Raid Alert Bot
"""

import telebot

from config import get_config
from logger import logger

from handlers.user import register_user_handlers
from handlers.admin import register_admin_handlers


def main():
    config = get_config()

    bot = telebot.TeleBot(
        config.BOT_TOKEN,
        parse_mode="Markdown"
    )

    register_user_handlers(bot)
    register_admin_handlers(bot)

    logger.info("===================================")
    logger.info("Rakhine Alert Bot Started")
    logger.info("===================================")

    try:
        bot.infinity_polling(
            timeout=60,
            long_polling_timeout=30,
            skip_pending=True
        )

    except KeyboardInterrupt:
        logger.warning("Bot stopped by user")

    except Exception:
        logger.exception("Unexpected error")


if __name__ == "__main__":
    main()