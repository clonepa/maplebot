import math

import requests
from datetime import datetime, timedelta
from .. import util, brains, deco

from discord.ext import commands


AV_TIMEFORMAT = "%Y-%m-%d %H:%M:%S"


def get_stock(symbol):
    endpoint = "https://www.alphavantage.co/query"
    params = {"function": "TIME_SERIES_INTRADAY",
              "symbol": symbol,
              "interval": "15min",
              "apikey": "XJ7NZIAYQJMR6EGO"}
    response = requests.get(endpoint, params).json()
    try:
        time_series = response["Time Series (15min)"]
    except KeyError as exc:
        if exc.args[0] == 'Time Series (15min)':
            raise ValueError(symbol)
        else:
            raise exc
    current_date, current = list(time_series.items())[0]
    current = float(current['4. close'])
    yesterday_date = datetime.strptime(current_date, AV_TIMEFORMAT) - timedelta(1)
    yesterday_date = yesterday_date.replace(hour=16, minute=0)
    yesterday_date = yesterday_date.strftime(AV_TIMEFORMAT)
    try:
        last = time_series[yesterday_date]['4. close']
    except KeyError as exc:
        if exc.args[0].endswith('16:00:00'):
            raise LookupError(symbol)
        else:
            raise exc
    last = float(last)

    diff = current - last
    diff_pc = (diff / last) * 100
    return_dict = {
        "current": round(current, 2),
        "diff": round(diff, 2),
        "diff_pc": round(diff_pc, 2)
    }
    return(return_dict)


@deco.db_operation
def setup_db(*, conn, cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stocks
        (owner_id TEXT, symbol TEXT, amount INTEGER,
        FOREIGN KEY(owner_id) REFERENCES users(discord_id),
        PRIMARY KEY(owner_id, symbol))
    ''')
    cursor.execute('''CREATE TRIGGER IF NOT EXISTS delete_from_stocks_on_zero
                   AFTER UPDATE OF amount ON stocks BEGIN
                   DELETE FROM stocks WHERE amount < 1;
                   END''')
    conn.commit()


@deco.db_operation
def get_stock_inv(user_id, symbol, *, conn, cursor):
    symbol = symbol.upper()
    cursor.execute('''SELECT amount FROM stocks
                      WHERE owner_id = :user_id AND symbol = :symbol''',
                   {"user_id": user_id, "symbol": symbol})
    fetch = cursor.fetchone()
    return fetch[0] if fetch else 0


@deco.db_operation
def update_stock(user_id, symbol, amount, *, conn, cursor):
    symbol = symbol.upper()
    if amount == 0:
        return 0
    cursor.execute('''SELECT amount FROM stocks
                      WHERE owner_id = :user_id AND symbol = :symbol''',
                   {"user_id": user_id, "symbol": symbol})
    amount_owned = cursor.fetchone()
    if amount_owned:
        amount_owned = amount_owned[0]
        amount_to_change = -min(-amount, amount_owned) if amount < 0 else amount
        cursor.execute('''UPDATE stocks
                          SET amount = amount + :amt
                          WHERE owner_id = :user_id AND symbol = :symbol''',
                       {"amt": amount_to_change, "user_id": user_id, "symbol": symbol})
        conn.commit()
        return amount_to_change
    else:
        cursor.execute('''INSERT INTO stocks VALUES
                       (:user_id, :symbol, :amt)''',
                       {"amt": amount, "user_id": user_id, "symbol": symbol})
        conn.commit()
        return amount


class MapleStocks:
    def __init__(self, bot):
        self.bot = bot
        self.transactions = []

    @commands.command(pass_context=True)
    async def setupstockdb(self, context):
        brains.check_debug(self, context)
        setup_db()

    @commands.command(pass_context=True, aliases=['checkstock'])
    async def maplestock(self, context, symbol: util.to_upper):
        await self.bot.type()
        try:
            stock = get_stock(symbol)
        except ValueError:
            return await self.bot.reply('invalid symbol!')
        except LookupError:
            return await self.bot.reply('sorry, i only support markets that close at 4 EST for now...')
        increased = stock['diff'] > 0
        emoji = '📈' if increased else '📉'
        sign = '+' if increased else ''
        outstr = ("{0} stock: {current}¢ {1}\n{2}{diff}¢ ({2}{diff_pc}%) since closing time yesterday"
                  .format(symbol, emoji, sign, **stock))
        if brains.is_registered(context.message.author.id):
            owned = get_stock_inv(context.message.author.id, symbol)
            if owned:
                outstr += "\nyou own {} (currently worth {:.2f}¢)".format(owned, owned * stock['current'])
        outstr = '\n' + util.codeblock(outstr)
        await self.bot.reply(outstr)

    @commands.command(pass_context=True, aliases=['buystock'])
    async def maplebuystock(self, context, symbol: util.to_upper, amount: int = 1):
        brains.check_registered(self, context)
        user_id = context.message.author.id
        if user_id in self.transactions:
            return await self.bot.reply("you're currently in a transaction!")

        await self.bot.type()
        if amount < 1:
            return await self.bot.reply("don't be silly!")
        try:
            stock_price = (math.ceil(get_stock(symbol)['current'])) / 100
        except ValueError:
            return await self.bot.reply('invalid symbol!')
        total_price = stock_price * amount
        has_enough, cash_needed = brains.enough_cash(user_id, total_price)
        if not has_enough:
            return await self.bot.reply("hey idiot why don't you come back with ${:.2f} more".format(cash_needed))
        await self.bot.reply("buy {}x{} stock for ${:.2f}?".format(amount, symbol, total_price))

        self.transactions.append(user_id)
        result = None
        while not result:
            msg = await self.bot.wait_for_message(timeout=30, author=context.message.author)
            if not msg:
                self.transactions.remove(user_id)
                return
            if msg.content.lower().startswith('y'):
                result = update_stock(user_id, symbol, amount)
                if result == amount:
                    brains.adjust_cash(user_id, -total_price)
                else:
                    raise Exception('failed to give stock')
            elif msg.content.lower().startswith('n'):
                self.transactions.remove(user_id)
                return await self.bot.reply("well ok")

        await self.bot.reply("{} {} stocks purchased!".format(result, symbol))
        self.transactions.remove(user_id)

    @commands.command(pass_context=True, aliases=['sellstock'])
    async def maplesellstock(self, context, symbol: util.to_upper, amount: int = 1):
        brains.check_registered(self, context)
        user_id = context.message.author.id
        if amount < 1:
            return await self.bot.reply("don't be silly!")
        owned = get_stock_inv(context.message.author.id, symbol)
        if amount > owned:
            return await self.bot.reply("you don't have enough!")

        try:
            stock_price = (math.floor(get_stock(symbol)['current'])) / 100
        except ValueError:
            return await self.bot.reply('invalid symbol!')
        total_price = stock_price * amount

        await self.bot.reply("sell {}x{} stock for ${:.2f}?".format(amount, symbol, total_price))

        self.transactions.append(user_id)
        result = None
        while not result:
            msg = await self.bot.wait_for_message(timeout=30, author=context.message.author)
            if not msg:
                self.transactions.remove(user_id)
                return
            if msg.content.lower().startswith('y'):
                result = update_stock(user_id, symbol, -amount)
                if result == -amount:
                    brains.adjust_cash(user_id, total_price)
                else:
                    raise Exception('failed to sell stock')
            elif msg.content.lower().startswith('n'):
                self.transactions.remove(user_id)
                return await self.bot.reply("well ok")

        await self.bot.reply("{} {} stocks sold!".format(-result, symbol))
        self.transactions.remove(user_id)


def setup(bot):
    bot.add_cog(MapleStocks(bot))
