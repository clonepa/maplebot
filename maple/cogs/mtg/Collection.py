import collections
import random
import sqlite3
import re
import logging
# import random

from discord.ext import commands

from ... import brains, util_mtg

import mapleconfig


logger = logging.getLogger('maple.cogs.mtg.Collection')


class MTG_Collection():
    def __init__(self, bot):
        self.bot = bot

    @commands.command(pass_context=True)
    async def updatecollection(self, context, target: str, card_id: str, amount: int = 1):
        brains.check_debug(self, context)
        target_record = brains.get_record(target)
        if not target_record:
            return await self.bot.reply("invalid user")

        try:
            card_name = brains.get_card(card_id)['card_name']
        except TypeError:
            return await self.bot.reply("card with multiverse_id {} not found!".format(card_id))

        updated = brains.update_collection(target_record['discord_id'], card_id, amount)
        target_name = target_record['name']
        if not updated:
            return await self.bot.reply("no changes made to cards `{0}` owned by {1}.".format(card_name, target_name))
        return await self.bot.reply("changed amount of cards `{0}` owned by {1} by {2}."
                                    .format(card_name, target_name, updated))

    @commands.command(pass_context=True, no_pm=True, aliases=['sendcard'])
    async def givecard(self, context):
        brains.check_registered(self, context)
        user = context.message.author.id
        # format: !givecard clonepa Swamp 2
        target, card = context.message.content.split(maxsplit=2)[1:]  # target = 'clonepa', card= 'Swamp 2'
        amount_re = re.search(r'\s+(\d+)$', card)
        if amount_re:
            amount = int(amount_re.group(1))
            card = card[:-len(amount_re.group(0))]
        else:
            amount = 1

        result_dict = brains.give_card(user, target, card, amount)

        reply_dict = {
            0: "gave {0} {1} to <@{2}>!".format(amount,
                                                result_dict['card_name'],
                                                result_dict['target_id']),
            1: "that's not a valid recipient!!",
            2: "hey, you don't have that card at all!",
            3: "hold up, you only have {0} of {1}!!".format(result_dict['amount_owned'],
                                                            result_dict['card_name']),
            4: "now that's just silly",
            5: "you only have {0} of that printing of {1}!".format(result_dict['amount_owned'],
                                                                   result_dict['card_name'])
        }

        await self.bot.reply(reply_dict[result_dict['code']])

    @commands.command(pass_context=True, aliases=['validatedeck', 'deckcheck'])
    async def checkdeck(self, context):
        brains.check_registered(self, context)
        message = context.message
        deck = message.content[len(message.content.split()[0]):].strip()
        missing_cards = brains.validate_deck(deck, message.author.id)

        if missing_cards:
            needed_cards_str = '\n'.join(["{0} {1}".format(missing_cards[card], card)
                                          for card in missing_cards])
            await self.bot.reply(("you don't have the cards for that deck!! " +
                                  "You need:\n```{1}```").format(message.author.id, needed_cards_str))
        else:
            hashed_deck = util_mtg.make_deck_hash(*util_mtg.convert_deck_to_boards(deck))
            await self.bot.send_message(self.bot.get_channel(mapleconfig.get_mainchannel_id()),
                                        "<@{0}> has submitted a collection-valid deck! hash: `{1}`"
                                        .format(message.author.id, hashed_deck))

    @commands.command(pass_context=True, aliases=['mtglinks'])
    async def maplelinks(self, context):
        brains.check_registered(self, context)
        username = brains.get_record(context.message.author.id, 'name')
        await self.bot.reply(("\nCollection: http://qubeley.biz/mtg/collection/{0}" +
                              "\nDeckbuilder: http://qubeley.biz/mtg/deckbuilder/{0}"
                              ).format(username))

    @commands.command(pass_context=True)
    async def draftadd(self, context, target, sets, deck):
        brains.check_debug(self, context)
        await self.bot.type()
        deck = deck.strip()
        deck = util_mtg.convert_deck_to_boards(deck)
        deck = collections.Counter(deck[0] + deck[1])

        sets = sets.split()

        target_id = brains.get_record(target, 'discord_id')

        ids_to_add = []

        conn = sqlite3.connect('maple.db')
        cursor = conn.cursor()

        logger.info('have deck with {} cards'.format(sum(deck.values())))
        for card in deck:
            logger.info('adding {0}x{1}'.format(card, deck[card]))

            cursor.execute("SELECT multiverse_id FROM cards WHERE card_name LIKE :name AND card_set IN ({0})"
                           .format(','.join(["'{}'".format(s) for s in sets])),
                           {'name': card})
            result = cursor.fetchall()
            if not result:
                print('Could not find {}'.format(card))
                raise KeyError
            for i in range(deck[card]):
                ids_to_add.append(random.choice(result)[0])
        ids_to_add = collections.Counter(ids_to_add)
        logger.info('have ids_to_add with {} cards'.format(sum(ids_to_add.values())))

        logger.info('adding...')
        counter = 0
        for mvid in ids_to_add:
            added = brains.update_collection(target_id, mvid, ids_to_add[mvid], conn)
            counter += added

        await self.bot.reply('added {0} cards from sets `{1}` to collection of <@{2}>'.format(counter, sets, target_id))

    @commands.command(pass_context=True)
    async def hascard(self, context, target, card):
        ''' Check if target user has card and if so how many. '''
        card = context.message.content.split(maxsplit=2)[2]

        target_record = brains.get_record(target)

        if card.isdigit():
            card_name = brains.get_card(int(card))['card_name']
            card_printings = brains.get_card(int(card), as_list=True)
        else:
            # if query is not a multiverseid there might be multiple
            card_name = brains.get_card(card)['card_name']
            card_printings = brains.get_card(card_name, as_list=True)

        amt_owned = 0
        for printing in card_printings:
            collection_entry = brains.get_collection_entry(printing['multiverse_id'], target_record['discord_id'])
            if collection_entry:
                amt_owned += collection_entry['amount_owned']

        if amt_owned == 0:
            await self.bot.reply('{0} has no card `{1}`'.format(target_record['name'], card))
            return

        if card.isdigit():
            card_name += ' ({})'.format(card)

        await self.bot.reply('{target} has {amount} of `{card}`'.format(target=target_record['name'],
                                                                        amount=amt_owned,
                                                                        card=card_name))


def setup(bot):
    bot.add_cog(MTG_Collection(bot))
