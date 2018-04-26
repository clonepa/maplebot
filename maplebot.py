import sqlite3
import json
import os
import logging
import asyncio

import coloredlogs
from discord.ext import commands

import bottalk
import mapleconfig

import maple.req
import maple.users

import blackjack


TOKEN = mapleconfig.get_token()
MTGOX_CHANNEL_ID = mapleconfig.get_mainchannel_id()
DEBUG_WHITELIST = mapleconfig.get_debug_whitelist()

logger = logging.getLogger('maplebot')


maplebot = commands.maplebot(command_prefix='!',
                             description='maple the gamification cat',
                             help_attrs={"name": "maplehelp"})


def debug():

    def predicate(context):
        is_debugger = context.message.author.id in DEBUG_WHITELIST
        if not is_debugger and context.command.name != "maplehelp" and maplebot:
            asyncio.ensure_future(maplebot.reply("that's a debug command, you rascal!"))
        return is_debugger
    return commands.check(predicate)


def registration():

    def predicate(context):
        registered = maple.users.is_registered(context.message.author.id)
        if not registered and context.command.name != "maplehelp":
                asyncio.ensure_future(maplebot.reply("you ain't registered!!!"))
        return registered
    return commands.check(predicate)



# ------------------- COMMANDS ------------------- #


@maplebot.command(pass_context=True)
async def hash(context):
    thing_to_hash = context.message.content[len(context.message.content.split()[0]):]
    hashed_thing = deckhash.make_deck_hash(*deckhash.convert_deck_to_boards(thing_to_hash))
    await maplebot.reply('hashed deck: {0}'.format(hashed_thing))


# ---- That Debug Shit ---- #


@maplebot.command()
@maple.req.debug()
async def populatesetinfo():
    # do not use load_mtgjson() here
    with open('AllSets.json', encoding="utf8") as f:
        cardobj = json.load(f)
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    for card_set in cardobj:
        logger.info(cardobj[card_set]["name"])
        name = ""
        code = ""
        alt_code = ""
        if "name" in cardobj[card_set]:
            name = cardobj[card_set]["name"]
        if "code" in cardobj[card_set]:
            code = cardobj[card_set]["code"]
        if "magicCardsInfoCode" in cardobj[card_set]:
            alt_code = cardobj[card_set]["magicCardsInfoCode"]
        if code != "" and name != "":
            cursor.execute("INSERT OR IGNORE INTO set_map VALUES (?, ?, ?)", (name, code, alt_code))
    conn.commit()
    conn.close()


@maplebot.command()
async def blackjacktest():
    hand = blackjack.deal_hand()
    score = blackjack.eval_hand(hand)
    outstring = ""
    for h in hand:
        outstring += h + " "
    await maplebot.say(outstring + "\nHand Score: " + str(score))


@maplebot.command(pass_context=True)
async def setcode(context, set_name: str):
    set_name = context.message.content.split(maxsplit=1)[1]
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name, code FROM set_map WHERE name LIKE :set_name", {"set_name": '%{0}%'.format(set_name)})
    results = cursor.fetchall()
    conn.close()
    if not results:
        return await maplebot.reply("no sets matchin *{0}* were found...".format(set_name))
    if len(results) > 14:
        return await maplebot.reply("too many matching sets!! narrow it down a little")
    outstring = '\n'.join(["code for set *{0[0]}* is **{0[1]}**".format(result) for result in results])
    await maplebot.reply(outstring)


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
    # for command in commands:
        # poopese(maplebot.commands[command])
    maplebot.run(TOKEN)
