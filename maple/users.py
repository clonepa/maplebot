import collections


from . import db, req, util
# import mtg.collection
# import mtg.booster

from discord.ext import commands


@db.operation
def get_record(target, field=None, conn=None, cursor=None):
    cursor.execute("SELECT * FROM users WHERE discord_id=:target OR name=:target COLLATE NOCASE",
                   {"target": target})
    columns = [description[0] for description in cursor.description]
    r = cursor.fetchone()
    if not r:
        raise KeyError

    out_dict = collections.OrderedDict.fromkeys(columns)
    for i, key in enumerate(out_dict):
        out_dict[key] = r[i]

    return out_dict[field] if field else out_dict


@db.operation
def set_record(target, field, value, conn=None, cursor=None):
    target_record = get_record(target)
    if field not in target_record:
        raise KeyError
    cursor.execute('''UPDATE users SET {} = :value
                   WHERE discord_id=:target OR name=:target COLLATE NOCASE'''
                   .format(field),
                   {"field": field,
                    "value": value,
                    "target": target})
    conn.commit()
    cursor.execute('''SELECT {} FROM users
                   WHERE discord_id=:target'''.format(field),
                   {"target": target_record['discord_id']})
    return cursor.fetchone()[0]


@db.operation
def verify_nick(nick, conn=None, cursor=None):
    '''returns True if nick doesn't exist in db, False if it does'''
    cursor.execute("SELECT * FROM users WHERE name = :name COLLATE NOCASE",
                   {"name": nick})
    result = cursor.fetchone()
    return False if result else True


def adjust_cash(target, delta: float):
    target_record = get_record(target)
    new_bux = target_record['cash'] + delta
    print(new_bux)
    response = set_record(target_record['discord_id'], 'cash', new_bux)
    return True if response == new_bux else False


class UserManagement():
    def __init__(self, bot):
        self.bot = bot

    @commands.command(pass_context=True, aliases=['givemaplebux', 'sendbux'])
    @req.registration
    @db.operation_async
    async def givebux(self, context, target: str, amount: float, conn=None, cursor=None):
        amount = float('%.2f' % amount)
        my_id = context.message.author.id
        mycash = get_record(my_id, 'cash')
        otherperson = ""
        cursor.execute("SELECT name FROM users WHERE discord_id=:who OR name=:who COLLATE NOCASE",
                       {"who": target})
        result = cursor.fetchone()
        if result:
            otherperson = result[0]
        else:
            await self.bot.reply("I'm not sure who you're trying to give money to...")
            return

        cursor.execute("SELECT name FROM users WHERE discord_id=:who OR name=:who",
                       {"who": my_id})

        result = cursor.fetchone()
        if result:
            if result[0] == otherperson:
                await self.bot.reply("sending money to yourself... that's shady...")
                return

        if amount < 0:
            await self.bot.reply("wait a minute that's a robbery!")
            return
        if mycash == 0 or mycash - amount < 0:
            await self.bot.reply("not enough bux to ride this trux :surfer:")
            return
        sent, received = adjust_cash(my_id, -amount), adjust_cash(otherperson, amount)
        if sent is received is True:
            await self.bot.reply("sent ${0} to {1}"
                                 .format(amount, target))

    @commands.command(pass_context=True, aliases=['maplebux', 'maplebalance'])
    @req.registration
    async def checkbux(self, context):
        await self.bot.reply("your maplebux balance is: ${0}"
                             .format('%.2f' % get_record(context.message.author.id, 'cash')))

    @commands.command(pass_context=True)
    @req.registration
    async def recordmatch(self, context, winner, loser):
        winner_record = get_record(winner)
        loser_record = get_record(loser)
        winner_elo = winner_record['elo_rating']
        loser_elo = loser_record['elo_rating']
        new_winner_elo, new_loser_elo = util.calc_elo_change(winner_elo, loser_elo)
        bux_adjustment = 3.00 * (new_winner_elo - winner_elo) / 32
        bux_adjustment = round(bux_adjustment, 2)
        loser_bux_adjustment = round(bux_adjustment / 3, 2)

        winnerid, loserid = winner_record['discord_id'], loser_record['discord_id']

        set_record(winnerid, 'elo_rating', new_winner_elo)
        set_record(loserid, 'elo_rating', new_loser_elo)

        adjust_cash(winnerid, bux_adjustment)
        adjust_cash(loserid, bux_adjustment / 3)
        await self.bot.reply("{0} new elo: {1}\n{2} new elo: {3}\n{0} payout: ${4}\n{2} payout: ${5}"
                             .format(winner_record['name'],
                                     new_winner_elo,
                                     loser_record['name'],
                                     new_loser_elo,
                                     bux_adjustment,
                                     loser_bux_adjustment))

    @commands.command(pass_context=True)
    @req.registration
    @db.operation_async
    async def changenick(self, context, nick, conn=None, cursor=None):
        if not verify_nick(nick):
            await self.bot.reply(("user with nickname {0} already exists. " +
                                  "don't try to confuse old maple you hear!!").format(nick))
        else:
            cursor.execute("UPDATE users SET name=:nick WHERE discord_id=:user",
                           {"nick": nick, "user": context.message.author.id})
            conn.commit()
            await self.bot.reply("updated nickname to {0}".format(nick))
        return

    @commands.command(pass_context=True)
    async def userinfo(self, context, user=None):
        user = user if user else context.message.author.id
        record = get_record(user)
        outstring = ('*nickname*: {name}' +
                     '\n*discord id*: {discord_id}' +
                     '\n*elo rating*: {elo_rating}' +
                     '\n*maplebux*: {cash}').format(**record)
        outstring = re.sub(r'\n\s+', '\n', outstring)

        await self.bot.say(outstring)


def setup(bot):
    bot.add_cog(UserManagement(bot))
