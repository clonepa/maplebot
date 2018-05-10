import requests
from datetime import datetime, timedelta
from .. import util

from discord.ext import commands


AV_TIMEFORMAT = "%Y-%m-%d %H:%M:%S"


def get_stock(symbol):

    endpoint = "https://www.alphavantage.co/query"
    params = {"function": "TIME_SERIES_INTRADAY",
              "symbol": symbol,
              "interval": "15min",
              "apikey": "XJ7NZIAYQJMR6EGO"}
    response = requests.get(endpoint, params).json()
    time_series = response["Time Series (15min)"]
    current_date, current = list(time_series.items())[0]
    current = float(current['4. close'])
    yesterday_date = datetime.strptime(current_date, AV_TIMEFORMAT) - timedelta(1)
    yesterday_date = yesterday_date.strftime(AV_TIMEFORMAT)
    last = time_series[yesterday_date]['4. close']
    last = float(last)

    diff = current - last
    diff_pc = (diff / last) * 100
    return_dict = {
        "current": round(current, 2),
        "diff": round(diff, 2),
        "diff_pc": round(diff_pc, 2)
    }
    return(return_dict)


class MapleStocks:
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def maplestock(self, symbol: util.to_upper):
        await self.bot.type()
        stock = get_stock(symbol)
        increased = stock['diff'] > 0
        emoji = '📈' if increased else '📉'
        sign = '+' if increased else ''
        await self.bot.reply("{0} stock: {current}¢, {1} {2}{diff}¢ ({2}{diff_pc}%)".format(symbol, emoji, sign, **stock))


def setup(bot):
    bot.add_cog(MapleStocks(bot))
