import os
import logging
import traceback
import sys

import coloredlogs
from discord.ext import commands

import bottalk
import mapleconfig

from maple import brains, util_mtg  # , collection, booster



TOKEN = mapleconfig.get_token()
MTGOX_CHANNEL_ID = mapleconfig.get_mainchannel_id()
DEBUG_WHITELIST = mapleconfig.get_debug_whitelist()

logger = logging.getLogger('maplebot')


maplebot = commands.Bot(command_prefix='!',
                        description='maple the gamification cat',
                        help_attrs={"name": "maplehelp"})


# ------------------- COMMANDS ------------------- #


@maplebot.command(pass_context=True)
async def hash(context):
    thing_to_hash = context.message.content[len(context.message.content.split()[0]):]
    hashed_thing = util_mtg.make_deck_hash(*util_mtg.convert_deck_to_boards(thing_to_hash))
    await maplebot.reply('hashed deck: {0}'.format(hashed_thing))


@maplebot.event
async def on_ready():
    logger.info('maplebot is ready')
    logger.info('[username: {0.name} || id: {0.id}]'.format(maplebot.user))


@maplebot.event
async def on_message(message):
    if message.author == maplebot.user:
        return
    if message.content.startswith(maplebot.command_prefix):
        await maplebot.process_commands(message)
    else:
        bottalk_request = await bottalk.get_request(maplebot, message)
        if bottalk_request:
            try:
                await bottalk.respond_request(maplebot, message.author, bottalk_request[0], eval(bottalk_request[1]))
            except Exception as exc:
                await bottalk.respond_request(maplebot, message.author, bottalk_request[0], exc)


class ErrorHandling():
    def __init__(self, bot):
        self.bot = bot

    async def on_command_error(self, error, context):
        if hasattr(context.command, 'on_error'):
            return

        error = getattr(error, 'original', error)

        ignored = (commands.CommandNotFound, commands.NoPrivateMessage)

        notify_str = 'please fix it.' if context.message.author.id in DEBUG_WHITELIST else 'please notify a dev.'

        if isinstance(error, ignored):
            return
        elif isinstance(error, brains.MapleCheckError):
            return await self.bot.send_message(context.message.channel,
                                               '{} {}'.format(context.message.author.mention,
                                                              error.message))
        else:
            await self.bot.send_message(context.message.channel,
                                        'unhandled exception in command `{0}`:\n```\n{1}: {2}\n```\n{3}'
                                        .format(context.command.name, type(error).__name__, error, notify_str))
            traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)
            return


if __name__ == "__main__":
    os.environ['COLOREDLOGS_LOG_FORMAT'] = "%(asctime)s %(name)s %(levelname)s %(message)s"
    coloredlogs.install(level='INFO')
    start_cogs = ['UserManagement', 'Debug', 'Blackjack',
                  'mtg.CardSearch', 'mtg.Collection', 'mtg.Booster']
    maplebot.add_cog(ErrorHandling(maplebot))
    for cog in start_cogs:
        try:
            maplebot.load_extension('maple.cogs.' + cog)
            print('loaded extension {}'.format(cog))
        except Exception as e:
            exc = '{}: {}'.format(type(e).__name__, e)
            print('Failed to load extension {}\n{}'.format(cog, exc))
    maplebot.run(TOKEN)
