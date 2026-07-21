import asyncio
import logging
import threading

import imap_listener
from bot import bot, post_new_mail
from config import DISCORD_BOT_TOKEN

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def start_imap_thread(loop: asyncio.AbstractEventLoop) -> None:
    """
    imap_listener.run_forever() is a blocking, synchronous loop (IMAP IDLE
    isn't async-native), so it runs in its own daemon thread. Its callback
    is plain/sync too -- run_coroutine_threadsafe hands the actual Discord
    post back to the bot's event loop, which is the only place it's safe
    to touch discord.py objects from.
    """

    def on_new_message(channel_id: int, message: dict) -> None:
        asyncio.run_coroutine_threadsafe(post_new_mail(channel_id, message), loop)

    thread = threading.Thread(
        target=imap_listener.run_forever, args=(on_new_message,), daemon=True
    )
    thread.start()


async def main():
    loop = asyncio.get_running_loop()
    start_imap_thread(loop)

    async with bot:
        await bot.start(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
