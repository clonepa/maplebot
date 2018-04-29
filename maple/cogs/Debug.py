import sys
import logging
import sqlite3
import json

from discord.ext import commands

from .. import brains, util


logger = logging.getLogger('maple.debug')


class Debug():
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def mapletest(self):
        await self.bot.say("i'm {0} and my guts are made of python {1}, brah :surfer:"
                           .format(self.bot.user.name, sys.version.split()[0]))

    @commands.command(pass_context=True)
    async def setupdb(self, context):
        brains.check_debug(self, context)
        try:
            brains.db_setup()
            await self.bot.reply('db set up with no errors!')
        except Exception as exc:
            await self.bot.reply('error setting up db: `{}`'.format(exc))

    @commands.command(pass_context=True)
    async def query(self, context, query: str):
        brains.check_debug(self, context)
        conn = sqlite3.connect('maple.db')
        cursor = conn.cursor()
        query = context.message.content.split(maxsplit=1)[1]
        if ('DROP' in query.upper() and context.message.author.id != '234042140248899587'):
            await self.bot.reply("pwease be careful wif dwoppy u_u")
        outstring = ""
        try:
            cursor.execute(query)
            outstring = '\n'.join(str(x) for x in cursor.fetchall())
        except sqlite3.OperationalError:
            outstring = "sqlite operational error homie...\n{0}".format(sys.exc_info()[1])

        if outstring == "":
            outstring = "rows affected : {0}".format(cursor.rowcount)
        await util.big_output_confirmation(context, outstring, formatting=util.codeblock, bot=self.bot)
        conn.commit()
        conn.close()

    @commands.command(pass_context=True)
    async def gutdump(self, context, *, table: str = "users", limit: int = 0):
        brains.check_debug(self, context)
        if table == "maple":
            with open(__file__) as file:
                output = file.read()
        else:
            conn = sqlite3.connect('maple.db')
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM {0} {1}".format(table, 'LIMIT {0}'.format(limit) if limit else ''))
            output = "{names}\n\n{output}".format(names=[description[0] for description in cursor.description],
                                                  output='\n'.join(str(x) for x in cursor.fetchall()))
            conn.close()
        await util.big_output_confirmation(context, output, formatting=util.codeblock, bot=self.bot)

    @commands.command(pass_context=True, aliases=["changebux"])
    async def adjustbux(self, context, target, amount: float):
        brains.check_debug(self, context)
        print(target, amount)
        brains.adjust_cash(target, amount)
        await self.bot.reply("updated bux")

    @commands.command(pass_context=True)
    async def populatesetinfo(self, context):
        brains.check_debug(self, context)
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
        await self.bot.reply('successfully populated set info for {} sets'.format(len(cardobj)))


def setup(bot):
    bot.add_cog(Debug(bot))
