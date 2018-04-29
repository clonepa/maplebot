import random

import requests
from discord.ext import commands

from ... import brains


class MTG_CardSearch():
    def __init__(self, bot):
        self.bot = bot

    @commands.command(pass_context=True, aliases=["maplecard", "maplecardinfo"])
    async def cardinfo(self, context):
        message = context.message
        query = message.content.split(maxsplit=1)
        if len(query) == 1:
            return None
        else:
            query = query[1]
        await self.bot.type()
        search_results = brains.scryfall_search(query)
        if not search_results:
            await self.bot.reply('No results found for *"{0}"*'.format(query))
            return
        card = search_results['data'][0]
        total_found = search_results['total_cards']
        if total_found > 1:
            more_string = '\n*{0} other cards matching that query were found.*\n'.format(total_found - 1)
        else:
            more_string = ''
        reply_string = more_string + brains.scryfall_format(card)
        await self.bot.reply(reply_string)

    @commands.command(pass_context=True, aliases=["maplecardsearch", "maplesearch"])
    async def cardsearch(self, context):
        query = context.message.content.split(maxsplit=1)
        if len(query) == 1:
            return None
        else:
            query = query[1]
        await self.bot.type()
        response = brains.scryfall_search(query)
        if not response:
            await self.bot.reply('No results found for *"{0}"*'.format(query))
            return
        search_results = response['data']
        reply_string = 'Cards found:'
        for i, card in enumerate(search_results):
            if i > 10:
                reply_string += '\nand {0} more'.format(response['total_cards'] - 10)
                break
            reply_string += ('\n**{name}** ({set}): {mana_cost} {type_line}'
                             .format(name=card['name'],
                                     set=card['set'].upper(),
                                     mana_cost=card['mana_cost'],
                                     type_line=card['type_line'] if
                                     'type_line' in card else '?'))
        await self.bot.reply(reply_string)

    @commands.command(pass_context=True)
    async def randomcard(self, context):
        await self.bot.type()
        query = context.message.content.split(maxsplit=1)
        if len(query) == 1:
            card = requests.get('https://api.scryfall.com/cards/random').json()
        else:
            query = query[1]
            page = 1
            search_result = brains.scryfall_search(query, page)
            while random.uniform(0, 1) > 0.25:
                if search_result['has_more']:
                    print('goin to next page...')
                    page += 1
                    search_result = brains.scryfall_search(query, page=page)
                else:
                    break
            card = random.choice(search_result['data'])
        await self.bot.reply(brains.scryfall_format(card))


def setup(bot):
    bot.add_cog(MTG_CardSearch(bot))
