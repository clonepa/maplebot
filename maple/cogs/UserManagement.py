import sqlite3
import re

from discord.ext import commands

from .. import brains, util


class UserManagement():
    def __init__(self, bot):
        self.bot = bot

    @commands.command(pass_context=True, no_pm=True, aliases=['mapleregister'])
    async def register(self, context, nickname: str):
        '''Register to maplebot with provided nick.'''
        conn = sqlite3.connect('maple.db')
        cursor = conn.cursor()
        user = context.message.author.id
        cursor.execute('SELECT * FROM users WHERE discord_id=?', (user,))
        if cursor.fetchall():
            await self.bot.reply("user with discord ID {0} already exists. don't try to pull a fast one on old maple!!"
                                 .format(user))
        elif not brains.verify_nick(nickname):
            await self.bot.reply("user with nickname {0} already exists. don't try to confuse old maple you hear!!"
                                 .format(nickname))
        else:
            cursor.execute("INSERT INTO users VALUES (?,?,1500,50.00)", (user, nickname))
            conn.commit()
            # collection.give_homie_some_lands(user)
            # booster.give_booster(user, "M13", 15)
            await self.bot.reply('created user in database with ID {0} and nickname {1}!\n'.format(user, nickname) +
                                 'i gave homie 60 of each Basic Land and 15 Magic 2013 Booster Packs!!')
        conn.close()
        return

    @commands.command(pass_context=True, aliases=['givemaplebux', 'sendbux'])
    async def givebux(self, context, target: str, amount: float):
        '''Give someone an amount of your maplebux'''
        brains.check_registered(self, context)
        conn = sqlite3.connect('maple.db')
        cursor = conn.cursor()
        amount = float('%.2f' % amount)
        my_id = context.message.author.id
        mycash = brains.get_record(my_id, 'cash')
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
        conn.close()
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
        sent, received = brains.adjust_cash(my_id, -amount), brains.adjust_cash(otherperson, amount)
        if sent is received is True:
            await self.bot.reply("sent ${0} to {1}"
                                 .format(amount, target))

    @commands.command(pass_context=True, aliases=['maplebux', 'maplebalance'])
    async def checkbux(self, context):
        '''Check your maplebux balance'''
        brains.check_registered(self, context)
        await self.bot.reply("your maplebux balance is: ${0}"
                             .format('%.2f' % brains.get_record(context.message.author.id, 'cash')))

    @commands.command(pass_context=True)
    async def recordmatch(self, context, winner, loser):
        '''Record a match between two users (winner, loser).
        Adjust elo/give payout accordingly.'''
        brains.check_registered(self, context)
        winner_record = brains.get_record(winner)
        loser_record = brains.get_record(loser)
        winner_elo = winner_record['elo_rating']
        loser_elo = loser_record['elo_rating']
        new_winner_elo, new_loser_elo = util.calc_elo_change(winner_elo, loser_elo)
        bux_adjustment = 6.00 * (new_winner_elo - winner_elo) / 32
        bux_adjustment = round(bux_adjustment, 2)
        loser_bux_adjustment = round(bux_adjustment / 3, 2)

        winnerid, loserid = winner_record['discord_id'], loser_record['discord_id']

        brains.set_record(winnerid, 'elo_rating', new_winner_elo)
        brains.set_record(loserid, 'elo_rating', new_loser_elo)

        brains.adjust_cash(winnerid, bux_adjustment)
        brains.adjust_cash(loserid, bux_adjustment / 3)
        await self.bot.reply("{0} new elo: {1}\n{2} new elo: {3}\n{0} payout: ${4}\n{2} payout: ${5}"
                             .format(winner_record['name'],
                                     new_winner_elo,
                                     loser_record['name'],
                                     new_loser_elo,
                                     bux_adjustment,
                                     loser_bux_adjustment))

    @commands.command(pass_context=True)
    async def changenick(self, context, nick):
        '''Change your nick to something else'''
        brains.check_registered(self, context)
        conn = sqlite3.connect('maple.db')
        cursor = conn.cursor()
        if not brains.verify_nick(nick):
            await self.bot.reply(("user with nickname {0} already exists. " +
                                  "don't try to confuse old maple you hear!!").format(nick))
        else:
            cursor.execute("UPDATE users SET name=:nick WHERE discord_id=:user",
                           {"nick": nick, "user": context.message.author.id})
            conn.commit()
            await self.bot.reply("updated nickname to {0}".format(nick))
        conn.close()
        return

    @commands.command(pass_context=True)
    async def userinfo(self, context, user=None):
        '''Get user details (defaults to you if no user provided)'''
        user = user if user else context.message.author.id
        record = brains.get_record(user)
        outstring = ('*nickname*: {name}' +
                     '\n*discord id*: {discord_id}' +
                     '\n*elo rating*: {elo_rating}' +
                     '\n*maplebux*: {cash}').format(**record)
        outstring = re.sub(r'\n\s+', '\n', outstring)

        await self.bot.say(outstring)


def setup(bot):
    bot.add_cog(UserManagement(bot))
