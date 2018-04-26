import mapleconfig
from . import db

import asyncio

from discord.ext import commands

DEBUG_WHITELIST = mapleconfig.get_debug_whitelist()


@db.operation
def is_registered(discord_id, conn=None, cursor=None):
    cursor.execute("SELECT discord_id FROM users WHERE discord_id=:id", {"id": discord_id})
    r = cursor.fetchone()
    if r:
        return True
    else:
        return False


def debug(bot):

    def predicate(context):
        is_debugger = context.message.author.id in DEBUG_WHITELIST
        asyncio.ensure_future(bot.reply("that's a debug command, you rascal!"))
        return is_debugger
    return commands.check(predicate)


def registration(bot):

    def predicate(context):
        registered = is_registered(context.message.author.id)
        asyncio.ensure_future(bot.reply("you ain't registered!!!"))
        return registered
    return commands.check(predicate)
