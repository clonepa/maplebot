import requests
from .. import util, brains, deco

from bs4 import BeautifulSoup as Soup

from discord.ext import commands


URL = "https://finance.yahoo.com/quote/{}"
HEADERS = {
    'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36"}

CURRENCY_RATIOS = {
    "USD": 1,
    "USX": 0.01,
    "GBP": 1.30,
    "GBX": 0.013,
    "JPY": 0.01
}


class UnsupportedCurrencyError(Exception):
    def __init__(self, currency):
        super().__init__(currency)
        self.message = f'The currency of this stock ({currency}) is not supported. Please contact a developer to add support for it.'


def format_cash_delta(number):
    sign = '' if number >= 0 else '-'
    absolute_value = abs(number)
    return f'{sign}${absolute_value:.2f}'


def get_stock(symbol):
    symbol = symbol.upper()
    soup = Soup(requests.get(URL.format(symbol),
                             headers=HEADERS).content, 'html.parser')
    exists = soup.find(id="quote-header-info")
    if not exists:
        raise KeyError(symbol)
    metadata = soup.select(
        "#quote-header-info > div.Mt\\(15px\\) > div.Mt\\(-5px\\) > div")

    name = metadata[0].find_all(
        'h1')[0].contents[0].rsplit(' (', maxsplit=1)[0]
    currency = metadata[1].find_all('span')[0].contents[0]

    currency = currency[currency.find('Currency in') + 12:]

    name += f' [{currency}]'

    data = soup.select(
        '#quote-header-info > div.My\\(6px\\) > div.D\\(ib\\) > div > span')
    current = data[0].contents[0]
    diff_data = data[1].contents[0]
    diff, diff_pc = diff_data.split(' (')
    current = float(current.replace(',', ''))
    diff = float(diff.replace('−', '-').replace(',', ''))
    diff_pc = float(diff_pc.replace('−', '-')[:-2])
    diff_sign = (diff > 0) - (diff < 0)
    diff_pc = diff_sign * diff_pc

    try:
        currency_ratio = CURRENCY_RATIOS[currency]
        current *= currency_ratio
    except KeyError as e:
        raise UnsupportedCurrencyError(currency) from e

    return {
        "name": name,
        "currency": currency,
        "current": current,
        "diff": diff,
        "diff_pc": diff_pc,
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
                   DELETE FROM stocks WHERE amount = 0;
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
    legacy = False
    for result in results:
        if counter == 0:
            break
        if not result["price"]:
            legacy = True
            value = None
        amt_to_take = min(counter, result["amount"])
        if not legacy:
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
    @commands.command(pass_context=True, aliases=['mystocks', 'mystock', 'stockinv', 'stockinventory', 'maplestocks', 'checkstocks'])
    async def maplestockinventory(self, context, mode=None):
        profitmode = mode and mode.lower() == 'profit'
        await self.bot.type()
        inventory = get_stock_inv(context.message.author.id)
        if not inventory:
            return await self.bot.reply("you don't have any stocks!!!")
        outstr = ""
        total_profit = 0
        for stock in inventory:
            stock_total_profit = 0
            current_value = 0
            if profitmode:
                data = get_stock(stock)
                current_value = data['current']/100
                stockinfo = '{0} [{1}] - currently valued at ${2:.2f}'.format(
                    stock, data['name'], current_value)
            else:
                stockinfo = stock
            outstr += f"\n**{stockinfo}**"
            for instance in inventory[stock]:
                amount = instance[1]
                if instance[0] is not None:
                    value = instance[0] / 100
                    total_value = amount * value
                    outstr += f"\n -{amount}x bought at ${value:.2f} (total: ${total_value:.2f})"
                    if profitmode:
                        profit = (current_value * amount) - total_value
                        emoji = '📈' if profit >= 0 else '📉'
                        outstr += f" -- total profit: {format_cash_delta(profit)} {emoji}"
                        stock_total_profit = stock_total_profit + profit
                else:
                    outstr += f"\n -{amount}x $(legacy stock, price bought at not recorded)"
            if profitmode:
                emoji = '📈' if stock_total_profit >= 0 else '📉'
                outstr += f"\n total profit: {format_cash_delta(stock_total_profit)} {emoji}"
                total_profit += stock_total_profit
        if profitmode:
            emoji = '📈' if total_profit >= 0 else '📉'
            outstr += f"\n\n grand total profit: {format_cash_delta(total_profit)} {emoji}"
        outstr = util.codeblock(outstr)
        await self.bot.reply("your stocks:\n{}".format(outstr))

    @commands.command(pass_context=True, aliases=['buystock', 'buystocks'])
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

    @commands.command(pass_context=True, aliases=['sellstock', 'sellstocks'])
    async def maplesellstock(self, context, symbol: util.to_upper, amount: int = 1):
        brains.check_registered(self, context)
        user_id = context.message.author.id
        # TODO: sell all
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
        bought_at_value, values_to_take = get_stock_value(
            context.message.author.id, symbol, amount)
        print(bought_at_value, values_to_take)
        profit = None
        if bought_at_value:
            bought_at_value = bought_at_value / 100
            profit = total_price - bought_at_value

        out = f"sell {amount}x {symbol} stock for ${total_price:.2f}?"
        if profit is not None:
            roi = (profit/bought_at_value) * 100
            out += f"\n Profit: ${profit:.2f}, RoI: {roi:.1f}% (total spent: ${bought_at_value:.2f})"
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

    @commands.command(pass_context=True)
    async def mapleassets(self, context):
        await self.bot.type()
        brains.check_registered(self, context)
        user_id = context.message.author.id

        cash = brains.get_record(user_id, 'cash')

        errored = set()

        stocks_value = 0
        inventory = get_stock_inv(user_id)
        print(inventory)
        for symbol in inventory:
            amount = 0
            for instance in inventory[symbol]:
                amount += instance[1]
            print(amount)
            try:
                stocks_value += get_stock(symbol)['current'] * amount
            except KeyError:
                print('errored', symbol)
                errored.add(symbol)

        stocks_value_in_bux = stocks_value / 100

        assets_worth = cash + stocks_value_in_bux

        cash_percentage = (cash / assets_worth) * 100
        stocks_percentage = (stocks_value_in_bux / assets_worth) * 100

        output = f'''```
Your MapleAssets
TOTAL: ${assets_worth:.2f}
${cash:.2f} cash/${stocks_value_in_bux:.2f} stocks
{cash_percentage:.1f}% cash/{stocks_percentage:.1f}% stocks'''

        if errored:
            output += '\n\n*Could not get stock values for symbol(s): ' + ', '.join(
                errored) + '. Please have it looked into.'

        output += '\n```'
        await self.bot.reply(output)


def setup(bot):
    bot.add_cog(MapleStocks(bot))
