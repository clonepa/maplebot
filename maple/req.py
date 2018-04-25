import mapleconfig
from . import users

import asyncio

from discord.ext import commands

DEBUG_WHITELIST = mapleconfig.get_debug_whitelist()


def debug(bot):
    def predicate(context):
        is_debugger = context.message.author.id in DEBUG_WHITELIST
        if not is_debugger and context.command.name != "maplehelp":
            asyncio.ensure_future(bot.reply("that's a debug command, you rascal!"))
        return is_debugger
    return commands.check(predicate)


def registration(bot):
    def predicate(context):
        registered = users.is_registered(context.message.author.id)
        if not registered and context.command.name != "maplehelp":
            asyncio.ensure_future(bot.reply("you ain't registered!!!"))
        return registered
    return commands.check(predicate)
