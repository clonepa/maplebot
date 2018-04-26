import os
import logging

import coloredlogs
from discord.ext import commands

import bottalk
import mapleconfig

from maple import db, users
from maple.mtg import deckhash

import blackjack


TOKEN = mapleconfig.get_token()
MTGOX_CHANNEL_ID = mapleconfig.get_mainchannel_id()
DEBUG_WHITELIST = mapleconfig.get_debug_whitelist()

logger = logging.getLogger('maplebot')


maplebot = commands.Bot(command_prefix='!',
                        description='maple the gamification cat',
                        help_attrs={"name": "maplehelp"})


# ------------------- COMMANDS ------------------- #


@maplebot.command(pass_context=True, no_pm=True, aliases=['mapleregister'])
@db.operation_async
async def register(self, context, nickname: str, conn=None, cursor=None):
    user = context.message.author.id
    cursor.execute('SELECT * FROM users WHERE discord_id=?', (user))
    if cursor.fetchall():
        await self.bot.reply("user with discord ID {0} already exists. don't try to pull a fast one on old maple!!"
                             .format(user))
    elif not users.verify_nick(nickname):
        await self.bot.reply("user with nickname {0} already exists. don't try to confuse old maple you hear!!"
                             .format(nickname))
    else:
        cursor.execute("INSERT INTO users VALUES (?,?,1500,50.00)", (user, nickname))
        conn.commit()
        # mtg.collection.give_homie_some_lands(user)
        # mtg.booster.give_booster(user, "M13", 15)
        await self.bot.reply('created user in database with ID {0} and nickname {1}!\n'.format(user, nickname) +
                             'i gave homie 60 of each Basic Land and 15 Magic 2013 Booster Packs!!')
    return


@maplebot.command(pass_context=True)
async def hash(context):
    thing_to_hash = context.message.content[len(context.message.content.split()[0]):]
    hashed_thing = deckhash.make_deck_hash(*deckhash.convert_deck_to_boards(thing_to_hash))
    await maplebot.reply('hashed deck: {0}'.format(hashed_thing))


@maplebot.command()
async def blackjacktest():
    hand = blackjack.deal_hand()
    score = blackjack.eval_hand(hand)
    outstring = ""
    for h in hand:
        outstring += h + " "
    await maplebot.say(outstring + "\nHand Score: " + str(score))


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


if __name__ == "__main__":
    os.environ['COLOREDLOGS_LOG_FORMAT'] = "%(asctime)s %(name)s %(levelname)s %(message)s"
    coloredlogs.install(level='INFO')
    start_cogs = ['maple.users', 'maple.debug', 'maple.mtg.scryfall', 'maple.mtg.collection', 'maple.mtg.booster']
    for cog in start_cogs:
        try:
            maplebot.load_extension(cog)
            print('loaded extension {}'.format(cog))
        except Exception as e:
            exc = '{}: {}'.format(type(e).__name__, e)
            print('Failed to load extension {}\n{}'.format(cog, exc))
    commands = list(maplebot.commands.keys())[:]
    maplebot.run(TOKEN)
