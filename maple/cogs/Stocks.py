import requests
from .. import util, brains, deco

from bs4 import BeautifulSoup as Soup

from discord.ext import commands


URL = "https://www.google.com/search?q=stocks%3A{}&hl=en&gl=en#safe=active&hl=en&gl=en&q=%s"
HEADERS = {'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36"}


def get_stock(symbol):
    symbol = symbol.upper()
    soup = Soup(requests.get(URL.format(symbol), headers=HEADERS).content, 'html.parser')
    exists = soup.find(id="knowledge-finance-wholepage__entity-summary")
    if not exists:
        raise KeyError(symbol)
    name = soup.select('div#knowledge-finance-wholepage__entity-summary g-card-section g-card-section div div')[0].contents[0]
    current = soup.select('div#knowledge-finance-wholepage__entity-summary g-card-section g-card-section div span span span')[0].contents[0]
    diff = soup.select('div#knowledge-finance-wholepage__entity-summary g-card-section g-card-section div span span')[3].contents[0].strip()
    diff_pc = (soup.select('div#knowledge-finance-wholepage__entity-summary g-card-section g-card-section div span span span'))[2].contents[0][:-2][1:]
    current = float(current.replace(',', ''))
    diff = float(diff.replace('−', '-').replace(',', ''))
    diff_pc = float(diff_pc.replace('−', '-'))
    diff_sign = (diff > 0) - (diff < 0)
    diff_pc = diff_sign * diff_pc
    return {
        "name": name,
        "current": round(current, 2),
        "diff": round(diff, 2),
        "diff_pc": round(diff_pc, 2)
    }


@deco.db_operation
def setup_db(*, conn, cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stocks
        (owner_id TEXT, symbol TEXT, amount INTEGER, price_bought FLOAT,
        FOREIGN KEY(owner_id) REFERENCES users(discord_id),
        PRIMARY KEY(owner_id, symbol, price_bought))
    ''')
    cursor.execute('''CREATE TRIGGER IF NOT EXISTS delete_from_stocks_on_zero
                   AFTER UPDATE OF amount ON stocks BEGIN
                   DELETE FROM stocks WHERE rowid = new.rowid AND amount = 0;
                   END''')
    conn.commit()

@deco.db_operation
def get_stock_amounts(user_id, *, conn, cursor):
    cursor.execute('''SELECT symbol, sum(amount) FROM stocks WHERE owner_id = :user_id GROUP BY symbol''',
                   {"user_id": user_id})
    results = cursor.fetchall()
    return {x[0]: x[1] for x in results}


@deco.db_operation
def get_stock_inv(user_id, *, conn, cursor):
    cursor.execute('''SELECT symbol, price_bought, amount FROM stocks WHERE owner_id = :user_id''',
                   {"user_id": user_id})
    results = cursor.fetchall()
    out_dict = {}
    for result in results:
        symbol = result[0]
        if symbol not in out_dict:
            out_dict[symbol] = []
        out_dict[symbol].append((result[1], result[2]))
    return out_dict


@deco.db_operation
def get_stock_value(user_id, symbol, amount, *, conn, cursor):
    cursor.execute('''SELECT amount, price_bought as price FROM stocks WHERE SYMBOL = :symbol AND owner_id = :user_id ORDER BY CASE
                   WHEN price_bought IS NULL THEN 9999999999999999999
                   ELSE price_bought
                   END ASC''',
                   {"user_id": user_id, "symbol": symbol})
    results = cursor.fetchall()
    results = [{"amount": x[0], "price": x[1]} for x in results]
    counter = amount
    value = 0
    values_to_take = []
    for result in results:
        if counter == 0:
            break
        if not result["price"]:
            return None, None
        amt_to_take = min(counter, result["amount"])
        value += result["price"] * amt_to_take
        counter -= amt_to_take
        values_to_take.append((result["price"], amt_to_take))
    if counter > 0:
        conn.close()
        raise ValueError("not enough of that stock!")
    return (value, values_to_take)



@deco.db_operation
def update_stock(user_id, symbol, amount, bought_at, *, conn, cursor):
    symbol = symbol.upper()
    if amount == 0:
        return 0
    cursor.execute('''INSERT OR IGNORE INTO stocks VALUES
                   (:user_id, :symbol, 0, :boughtat)''',
                   {"user_id": user_id, "symbol": symbol, "boughtat": bought_at})
    cursor.execute('''UPDATE stocks
                   SET amount = amount + :amt
                   WHERE owner_id = :user_id AND symbol = :symbol AND price_bought = :price_bought''',
                   {"amt": amount, "user_id": user_id, "symbol": symbol, "price_bought": bought_at})
    # make sure this doesn't put us at a negative amount owned
    cursor.execute('''SELECT amount FROM stocks
                   WHERE owner_id = :user_id AND symbol = :symbol AND price_bought = :price_bought''',
                   {"user_id": user_id, "symbol": symbol, "price_bought": bought_at})
    f = cursor.fetchone()
    final_amt = f and f[0]
    if final_amt and final_amt < 0:
        conn.close()
        raise ValueError("not enough stocks to remove")
    else:
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
        except KeyError:
            return await self.bot.reply('invalid symbol!')
        increased = stock['diff'] > 0
        emoji = '📈' if increased else '📉'
        sign = '+' if increased else ''
        outstr = ("{0} ({name}) stock: {current}¢ {1}\n{2}{diff}¢ ({2}{diff_pc}%) since closing time yesterday"
                  .format(symbol, emoji, sign, **stock))
        # TODO: adjust this for the new price column
        # if brains.is_registered(context.message.author.id):
        #     try:
        #         owned = get_stock_inv(context.message.author.id)[symbol]
        #         outstr += "\nyou own {} (currently worth {:.2f}¢)".format(owned, owned * stock['current'])
        #     except KeyError:
        #         pass
        outstr = '\n' + util.codeblock(outstr)
        await self.bot.reply(outstr)

    # TODO: adjust this for the new price column
    @commands.command(pass_context=True, aliases=['mystocks', 'mystock', 'stockinv', 'stockinventory'])
    async def maplestockinventory(self, context):
        await self.bot.type()
        inventory = get_stock_inv(context.message.author.id)
        if not inventory:
            await self.bot.reply("you don't have any stocks!!!")
        outstr = ""
        for stock in inventory:
            outstr += f"\n**{stock}**"
            for instance in inventory[stock]:
                amount = instance[1]
                value = instance[0]
                if value is not None:
                    total_value = amount * value
                    outstr += f"\n -{amount}x bought at ${value} (total: ${total_value})"
                else:
                    outstr += f"\n -{amount}x (legacy stock, price bought at not recorded)"
        outstr = util.codeblock(outstr)
        await self.bot.reply("your stocks:\n{}".format(outstr))

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
            stock_price = get_stock(symbol)['current']
        except KeyError:
            return await self.bot.reply('invalid symbol!')
        total_price = (stock_price * amount) / 100
        has_enough, cash_needed = brains.enough_cash(user_id, total_price)
        if not has_enough:
            return await self.bot.reply("hey idiot why don't you come back with ${:.2f} more".format(cash_needed))
        await self.bot.reply("buy {}x {} stock for ${:.2f}?".format(amount, symbol, total_price))

        self.transactions.append(user_id)
        result = None
        while not result:
            msg = await self.bot.wait_for_message(timeout=30, author=context.message.author)
            if not msg:
                self.transactions.remove(user_id)
                return
            if msg.content.lower().startswith('y'):
                result = update_stock(user_id, symbol, amount, stock_price)
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
        try:
            owned = get_stock_amounts(context.message.author.id)[symbol]
        except KeyError:
            return await self.bot.reply("you don't have any of those!")
        if amount > owned:
            return await self.bot.reply("you don't have enough!")

        await self.bot.type()
        try:
            stock_price = get_stock(symbol)['current']
        except KeyError:
            return await self.bot.reply('invalid symbol!')
        total_price = (stock_price * amount) / 100
        bought_at_value, values_to_take = get_stock_value(context.message.author.id, symbol, amount)
        profit = None
        if bought_at_value:
            bought_at_value = bought_at_value / 100
            profit = total_price - bought_at_value

        out = f"sell {amount}x {symbol} stock for ${total_price:.2f}?"
        if profit is not None:
            out += f"\n Profit: ${profit:.2f} (total spent: ${bought_at_value:.2f})"
        else:
            out += "\nProfit could not be calculated (you have legacy stocks)"

        await self.bot.reply(out)

        self.transactions.append(user_id)
        result = None
        while not result:
            msg = await self.bot.wait_for_message(timeout=30, author=context.message.author)
            if not msg:
                self.transactions.remove(user_id)
                return
            if msg.content.lower().startswith('y'):
                result = 0
                for val in values_to_take:

                    result += update_stock(user_id, symbol, -val[1], val[0])
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
