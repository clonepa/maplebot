import asyncio

import requests


def search_card(query, page=1):
    response = requests.get('https://api.scryfall.com/cards/search', params={'q': query, 'page': page}).json()
    if response['object'] == 'list':
        return response
    if response['object'] == 'error':
        return False


async def cmd_cardinfo(user, message, client=None):
    query = message.content.split(maxsplit=1)
    if len(query) == 1:
        return None
    else:
        query = query[1]
    await client.send_typing(message.channel)
    search_results = search_card(query)
    if not search_results:
        await client.send_message(message.channel, 'No results found for *"{0}"*'.format(query))
        return
    card = search_results['data'][0]
    total_found = search_results['total_cards']
    if total_found > 1:
        more_string = '*{0} other cards matching that query were found.*'.format(total_found - 1)
    else:
        more_string = ''
    all_printings = search_card('!"{0}" unique:prints'.format(card['name']))['data']
    other_printings = []
    for printing in all_printings:
        if printing['set'] == card['set'] or printing['set'] in other_printings:
            continue
        other_printings.append(printing['set'].upper())
    printings_list_string = ', '.join(other_printings[:8]) + \
                            (' and {0} others'.format(len(other_printings) - 8) if len(other_printings) > 8 else '')
    printings_string = 'Also printed in: {0}'.format(printings_list_string) if other_printings else ''
    reply_string = ['<@{user}>',
                    more_string,
                    '**{card_name}**',
                    'Set: {card_set}',
                    printings_string,
                    'http://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid={multiverse_id}',
                    '{card_image}']
    reply_string = '\n'.join(reply_string).format(user=user,
                                                  card_name=card['name'],
                                                  card_set=card['set'].upper(),
                                                  multiverse_id=card['multiverse_ids'][0],
                                                  card_image=card['image_uris']['large'])
    await client.send_message(message.channel, reply_string)


async def cmd_cardsearch(user, message, client=None):
    query = message.content.split(maxsplit=1)
    if len(query) == 1:
        return None
    else:
        query = query[1]
    await client.send_typing(message.channel)
    response = search_card(query)
    if not response:
        await client.send_message(message.channel, 'No results found for *"{0}"*'.format(query))
        return
    search_results = response['data']
    reply_string = '<@{0}> Cards found:'.format(user)
    for i, card in enumerate(search_results):
        if i > 10:
            reply_string += '\nand {0} more'.format(response['total_cards'] - 10)
            break
        reply_string += '\n**{name}** ({set}): {mana_cost} {type_line}'.format(name=card['name'],
                                                                               set=card['set'].upper(),
                                                                               mana_cost=card['mana_cost'],
                                                                               type_line=card['type_line'])
    await client.send_message(message.channel, reply_string)
