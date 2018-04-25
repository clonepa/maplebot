import random

import requests
from discord.ext import commands


# --- UTIL FUNCTIONS --- #


def search_card(query, page=1):
    response = requests.get('https://api.scryfall.com/cards/search', params={'q': query, 'page': page}).json()
    if response['object'] == 'list':
        return response
    if response['object'] == 'error':
        return False


def scryfall_card_format(card):
    all_printings = search_card('!"{0}" unique:prints'.format(card['name']))['data']
    other_printings = []
    for printing in all_printings:
        if printing['set'] == card['set'] or printing['set'] in other_printings:
            continue
        other_printings.append(printing['set'].upper())
    printings_list_string = ', '.join(other_printings[:8]) + \
                            (' and {0} others'.format(len(other_printings) - 8) if len(other_printings) > 8 else '')
    printings_string = 'Also printed in: {0}'.format(printings_list_string) if other_printings else ''
    multiverse_id = card['multiverse_ids'][0] if card['multiverse_ids'] else None
    if multiverse_id:
        gatherer_string = 'http://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid={0}'.format(
                          multiverse_id)
    else:
        gatherer_string = "this card has no gatherer page. must be something weird or new...!"
    lines_dict = ['**{card_name}**',
                  'Set: {card_set}',
                  printings_string,
                  gatherer_string,
                  card['image_uris']['large'] if 'image_uris' in card
                  else card['card_faces'][0]['image_uris']['large']]
    return '\n'.join(lines_dict).format(card_name=card['name'],
                                        card_set=card['set'].upper())


#    --- COMMANDS ---    #


class CardInfo():
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
        search_results = search_card(query)
        if not search_results:
            await self.bot.reply('No results found for *"{0}"*'.format(query))
            return
        card = search_results['data'][0]
        total_found = search_results['total_cards']
        if total_found > 1:
            more_string = '\n*{0} other cards matching that query were found.*\n'.format(total_found - 1)
        else:
            more_string = ''
        reply_string = more_string + scryfall_card_format(card)
        await self.bot.reply(reply_string)

    @commands.command(pass_context=True, aliases=["maplecardsearch", "maplesearch"])
    async def cardsearch(self, context):
        query = context.message.content.split(maxsplit=1)
        if len(query) == 1:
            return None
        else:
            query = query[1]
        await self.bot.type()
        response = search_card(query)
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
            search_result = search_card(query, page)
            while random.uniform(0, 1) > 0.25:
                if search_result['has_more']:
                    print('goin to next page...')
                    page += 1
                    search_result = search_card(query, page=page)
                else:
                    break
            card = random.choice(search_result['data'])
        await self.bot.reply(scryfall_card_format(card))


def setup(bot):
    bot.add_cog(CardInfo(bot))
