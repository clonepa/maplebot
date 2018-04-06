import requests


def search_card(query, page=1):
    response = requests.get('https://api.scryfall.com/cards/search', params={'q': query, 'page': page}).json()
    if response['object'] == 'list':
        return response
    if response['object'] == 'error':
        return False


async def cmd_cardinfo(user, message, client=None):
    query = message.content.split(maxsplit=1)
    # if len(query) == 1:
    #     return None
    # else:
    #     query = query[1]
    # search_results = search_card(query)
    # if not search_results:
    #     await client.send_message(message.channel, 'No results found for *"{0}"*'.format(query))
    #     return
    # card = search_results['data'][0]
    # total_found = search_results['total_cards']
    # if total_found > 1:
    #     more_string = '*{0} other cards matching that query were found.*'.format(total_found - 1)
    # all_printings = search.card('!"{card_name}" unique:prints'.format(card['name']))
    # other_printings = []
    # for printing in all_printings:
    #     if printing['set'] == card['set']:
    #         continue
    #     other_printings.append(printing['set'])

    # reply_string = [more_string,
    #                 '**{card_name}**',
    #                 'Set: {card_set}',
    #                 'Also printed in: {other_printings}',
    #                 ''
