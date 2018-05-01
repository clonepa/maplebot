import logging
import sqlite3

from discord.ext import commands

from maple import brains, util


logger = logging.getLogger('maple.mtg.booster')


def booster_price_disc(price, amount):
    boxes = amount // 36
    packs = amount % (boxes * 36) if boxes else amount
    total_price = boxes * (29 * price) + packs * price
    return (total_price, boxes)


class MTG_Boosters():
    def __init__(self, bot):
        self.bot = bot
        self.transactions = []

    @commands.command(pass_context=True, aliases=['packprice', 'checkprice'])
    async def boosterprice(self, context, card_set: str):
        '''shows booster price of set'''
        setinfo = brains.get_set_info(card_set)

        await self.bot.type()
        price = brains.get_booster_price(setinfo['code'])
        if price:
            out = "{0} booster pack price: ${1}\nbooster box (36 packs) price:".format(setinfo['name'],
                                                                                       price, price * 29)
        else:
            out = "no prices found for that set brah"

        await self.bot.reply(out)

    @commands.command(pass_context=True, aliases=['buypack'])
    async def buybooster(self, context, card_set: util.to_upper, amount: int = 1):
        '''purchase any amount of booster packs of set'''
        brains.check_registered(self, context)
        user = context.message.author.id
        if user in self.transactions:
            await self.bot.reply("you're currently in a transaction! ...guess I'll cancel it for you"
                                 .format(user))
            self.transactions.remove(user)

        setinfo = brains.get_set_info(card_set)

        pack_price = brains.get_booster_price(setinfo['code'])
        total_price, boxes = booster_price_disc(pack_price, amount)

        has_enough, cash_needed = brains.enough_cash(user, total_price)
        if not has_enough:
            await self.bot.reply("hey idiot why don't you come back with ${} more".format(round(cash_needed, 2)))
            return

        out = "Buy {0} {1} booster{plural} for ${2}?"
        if boxes:
            out += " ({}x Booster Box Discount - {} Packs (${}) Off!!)".format(boxes, 5 * boxes,
                                                                               round(5 * boxes * pack_price, 2))

        self.transactions.append(user)
        await self.bot.reply(out.format(amount,
                                        setinfo['name'], round(total_price, 2),
                                        plural=("s" if amount > 1 else "")))

        msg = await self.bot.wait_for_message(timeout=30, author=context.message.author)
        result = None
        while not result:
            if not msg:
                self.transactions.remove(user)
                return
            if msg.content.lower().startswith('y'):
                result = brains.give_booster(user, card_set, amount)
                if result == amount:
                    brains.adjust_cash(user, -total_price)
                else:
                    raise Exception('failed to give boosters')
            elif msg.content.lower().startswith('n'):
                return await self.bot.reply("well ok")

        await self.bot.reply("{} {} booster(s) added to inventory!".format(result, setinfo['name']))
        self.transactions.remove(user)

    @commands.command(pass_context=True, aliases=['openpack', 'obooster', 'opack'])
    async def openbooster(self, context, card_set: util.to_upper, amount: int = 1):
        '''open amount of owned boosters of set'''
        brains.check_registered(self, context)
        user = context.message.author.id
        await self.bot.type()

        boosters_list = brains.open_booster(user, card_set, amount)
        boosters_opened = len(boosters_list)
        if boosters_opened == 1:
            await self.bot.reply("\n```{0}```\nhttp://qubeley.biz/mtg/booster/{1}/{2}"
                                 .format(boosters_list[0]['cards'], card_set, boosters_list[0]['seed']))
        elif boosters_opened > 1:
            outstring = "{0} opened {1} boosters by {2}:\n\n".format(boosters_opened,
                                                                     card_set,
                                                                     context.message.author.display_name)
            for i, booster in enumerate(boosters_list):
                outstring += "------- Booster #{0} -------\n".format(i + 1)
                outstring += booster['cards'] + '\n'
            pb_url = util.make_ptpb(outstring)
            await self.bot.reply("your {1} opened {2} boosters: {3}"
                                 .format(user, boosters_opened, card_set, pb_url))
        else:
            await self.bot.reply("don't have any of those homie!!"
                                 .format(user))

    @commands.command(pass_context=True, aliases=["givepack"])
    async def givebooster(self, context, card_set, target=None, amount: int = 1):
        brains.check_debug(self, context)
        card_set = card_set.upper()
        if not target:
            target = context.message.author.id
        logger.info('giving {0} booster(s) of set {1} to {2}'.format(amount, card_set, target))
        amt_added = brains.give_booster(target, card_set, amount)
        target_id = brains.get_record(target, 'discord_id')
        await self.bot.reply("{0} {1} booster(s) added to <@{2}>'s inventory!"
                             .format(amt_added, card_set, target_id))

    @commands.command(pass_context=True, aliases=["boosterinv", "myboosters"])
    async def boosterinventory(self, context):
        conn = sqlite3.connect('maple.db')
        cursor = conn.cursor()

        cursor.execute('''SELECT card_set, count(*) FROM booster_inventory
                       WHERE owner_id = ?
                       GROUP BY card_set''',
                       (context.message.author.id,))

        result = cursor.fetchall()
        conn.close()

        outstr = 'your boosters:\n'
        outstr += '\n'.join(['{0[1]}x {0[0]}'.format(x) for x in sorted(result)])

        await self.bot.reply(outstr)

    @commands.command(pass_context=True)
    async def setcode(self, context, set_name: str):
        conn = sqlite3.connect('maple.db')
        cursor = conn.cursor()
        set_name = context.message.content.split(maxsplit=1)[1]
        cursor.execute("SELECT name, code FROM set_map WHERE name LIKE :set_name",
                       {"set_name": '%{0}%'.format(set_name)})
        results = cursor.fetchall()
        conn.close()
        if not results:
            return await self.bot.reply("no sets matchin *{0}* were found...".format(set_name))
        if len(results) > 14:
            return await self.bot.reply("too many matching sets!! narrow it down a little")
        outstring = '\n'.join(["code for set *{0[0]}* is **{0[1]}**".format(result) for result in results])
        await self.bot.reply(outstring)


def setup(bot):
    bot.add_cog(MTG_Boosters(bot))
