import mapleconfig
from . import db

DEBUG_WHITELIST = mapleconfig.get_debug_whitelist()


@db.operation
def is_registered(discord_id, conn=None, cursor=None):
    cursor.execute("SELECT discord_id FROM users WHERE discord_id=:id", {"id": discord_id})
    r = cursor.fetchone()
    if r:
        return True
    else:
        return False


def debug(func):

    async def wrapped(self, context, *args, **kwargs):
        is_debugger = context.message.author.id in DEBUG_WHITELIST
        if not is_debugger:
            await self.bot.reply("that's a debug command, you rascal!")
            return
        else:
            await func(self, context, *args, **kwargs)
            return await func(self, context, *args, **kwargs)

    wrapped.__name__ = func.__name__
    return wrapped


def registration(func):

    async def wrapped(self, context, *args, **kwargs):
        registered = is_registered(context.message.author.id)
        if not registered:
            await self.bot.reply("you ain't registered!!")
            return
        else:
            await func(self, context, *args, **kwargs)
            return await func(self, context, *args, **kwargs)

    wrapped.__name__ = func.__name__
    return wrapped
