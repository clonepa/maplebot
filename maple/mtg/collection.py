import collections
import re
import logging
import random

from discord.ext import commands

from .. import db, users, req
from . import deckhash
import mapleconfig


logger = logging.getLogger('maple.mtg.collection')


@db.operation
def update(user, multiverse_id, amount=1, conn=None, cursor=None):
    '''Updates the entry on table `collection` for card of multiverse id arg(multiverse_id),
    owned by arg(user) (discord_id string).
    If no entry and arg(amount) is positive, creates entry with amount_owned = arg(amount).
    If entry already exists, changes its amount_owned by arg(amount), down to zero.
    Allows for passing an existing sqlite3 connection to arg(conn) for mass card updatings.
    Returns amount of cards actually added/removed.'''

    # amount = 0 is pointless, so return 0 cards added
    if amount == 0:
        return 0

    cursor.execute('''SELECT amount_owned FROM collection WHERE owner_id=:name
                   AND multiverse_id=:mvid AND amount_owned > 0''',
                   {"name": user, "mvid": multiverse_id})
    has_already = cursor.fetchone()

    # if we're trying to remove a card that isn't there, return 0 cards added
    if amount < 0 and not has_already:
        return 0
    # otherwise, we're adding the card, so if it isn't there, create the entry
    elif not has_already:
        amount_to_change = amount
        cursor.execute("INSERT INTO collection VALUES (:name, :mvid, :amount, CURRENT_TIMESTAMP)",
                       {"name": user,
                        "mvid": multiverse_id,
                        "amount": amount})
    # at this point we know the user already has some of the card,
    # so update the amount_owned, increasing it or decreasing it
    else:
        amount_owned = has_already[0]
        # select the real amount to change
        # if amount < 0, pick amount_owned if amount would remove more than that, else just amount
        # if amount > 0, it's just amount
        if amount < 0:
            amount_to_change = -amount_owned if (-amount > amount_owned) else amount
        else:
            amount_to_change = amount
        cursor.execute('''UPDATE collection SET amount_owned = amount_owned + :amount
                       WHERE owner_id=:name AND multiverse_id=:mvid''',
                       {"name": user,
                        "mvid": multiverse_id,
                        "amount": amount_to_change})
    conn.commit()

    return amount_to_change


@db.operation
def give_card(user, target, card, amount=1, conn=None, cursor=None):
    # check that amount > 0:
    return_dict = dict.fromkeys(['code', 'card_name', 'amount_owned', 'target_id'])
    if amount < 1:
        return_dict['code'] = 4  # = invalid amount
        return return_dict
    # user is guaranteed valid by the command parser
    # check that target is valid:
    cursor.execute("SELECT discord_id FROM users WHERE discord_id=:target OR name=:target", {"target": target})
    r = cursor.fetchone()
    # if target exists and is not user:
    if r and r[0] != user:
        target_id = r[0]
    else:
        return_dict['code'] = 1  # = target invalid
        return return_dict
    # check that user has card & get all instances of it:
    cursor.execute('''SELECT collection.rowid, collection.multiverse_id, amount_owned, card_name FROM collection
                   INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id
                   WHERE owner_id = :user AND (card_name LIKE :card OR collection.multiverse_id LIKE :card)''',
                   {"user": user, "card": card})
    origin_cards = cursor.fetchall()
    if origin_cards:
        origin_amountowned = sum([row[2] for row in origin_cards])
        card_name = origin_cards[0][3]
    else:
        return_dict['code'] = 2  # = card not in collection
        return return_dict

    # check that user has enough of card:
    if amount > origin_amountowned:
        if str(card) == str(origin_cards[0][1]):  # if input card is a multiverse id:
            return_dict['code'] = 5  # = not enough of printing
        else:
            return_dict['code'] = 3  # = not enough of card
        return_dict['card_name'] = card_name
        return_dict['amount_owned'] = origin_amountowned
        return return_dict

    # copy amount to use as a counter
    counter = amount
    # for every instance of card found:
    for card in origin_cards:
        origin_rowid, multiverse_id, iter_amountowned, card_name = card

        iter_amount = min(counter, iter_amountowned)
        # check if target owns any of multiverse_id and get rowid and amt owned if so:
        cursor.execute('''SELECT rowid, amount_owned FROM collection
                       WHERE owner_id = :target AND multiverse_id = :multiverse_id''',
                       {"target": target_id, "multiverse_id": multiverse_id})
        r = cursor.fetchone()
        if r:
            target_rowid, target_amountowned = r
            cursor.execute("UPDATE collection SET amount_owned = :new_amount WHERE rowid = :rowid",
                           {"new_amount": (target_amountowned + iter_amount), "rowid": target_rowid})
        # otherwise, create new row with that amount
        else:
            cursor.execute("INSERT INTO collection VALUES (:target_id, :multiverse_id, :amount, CURRENT_TIMESTAMP)",
                           {"target_id": target_id, "multiverse_id": multiverse_id, "amount": iter_amount})
        # remove amount owned from user
        cursor.execute("UPDATE collection SET amount_owned = :new_amount WHERE rowid = :rowid",
                       {"new_amount": (iter_amountowned - iter_amount), "rowid": origin_rowid})
        conn.commit()
        counter -= iter_amount
        if counter == 0:
            conn.commit()
            break

    # set up the return dict
    return_dict['code'] = 0  # = success!
    return_dict['card_name'] = card_name
    return_dict['target_id'] = target_id
    return return_dict


@db.operation
def export_to_list(user, cursor=None, conn=None):
    who = users.get_record(user)
    cursor.execute('''SELECT amount_owned, card_name, card_set, card_type, rarity,
                   cards.multiverse_id, cards.colors, cards.cmc, collection.date_obtained
                   FROM collection INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id
                   WHERE owner_id = :ownerid''',
                   {"ownerid": who['discord_id']})
    out = []
    for card in cursor.fetchall():
        out.append({"amount": card[0], "name": card[1], "set": card[2], "type": card[3],
                    "rarity": card[4], "multiverseid": card[5], "color": card[6], "cmc": card[7], "date": card[8]})
    return out


@db.operation
def give_homie_some_lands(who, conn=None, cursor=None):
    '''give 60 lands to new user'''
    user_record = users.get_record(who)
    if not user_record:
        raise KeyError
    mvid = [439857, 439859, 439856, 439858, 439860]
    for i in mvid:
        cursor.execute("INSERT OR IGNORE INTO collection VALUES (:name,:mvid,60,CURRENT_TIMESTAMP)",
                       {"name": user_record['discord_id'], "mvid": i})
        print(cursor.rowcount)
    conn.commit()


@db.operation
def validate_deck(deckstring, user, conn=None, cursor=None):
    deck = deckhash.convert_deck_to_boards(deckstring)

    # flatten tuple of deck and sb into repeating list of all cards,
    # then turn list of repeated card names into dict in format {"name": amount}
    deck = collections.Counter(deck[0] + deck[1])

    missing_cards = {}

    cursor.execute('''SELECT card_name, sum(amount_owned) FROM collection
                   INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id
                   WHERE owner_id=:ownerid GROUP BY card_name''',
                   {"ownerid": user})
    collection = cursor.fetchall()
    collection = dict((n, a) for n, a in collection)  # turn list of tuples to dict in same format as deck

    for card in deck:
        # if user has card in collection, check difference between required amt and owned amt
        # if amt required by deck > amt owned, set the key for card in missing_cards to the difference
        if card in collection:
            deck_collection_diff = deck[card] - collection[card]
            if deck_collection_diff > 0:
                missing_cards[card] = deck_collection_diff
        # if they don't have it, add the full amount of card required to missing_cards
        else:
            missing_cards[card] = deck[card]

    return missing_cards


class MTGCollection():
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @req.debug
    @db.operation_async
    async def updatecollection(self, target: str, card_id: str, amount: int = 1, conn=None, cursor=None):
        target_record = users.get_record(target)
        if not target_record:
            return await self.bot.reply("invalid user")
        cursor.execute('SELECT card_name FROM cards WHERE multiverse_id = ?', (card_id,))
        result = cursor.fetchone()
        if not result:
            return await self.bot.reply("no card with multiverse id {0} found!".format(card_id))
        card_name = result[0]
        updated = update(target_record['discord_id'], card_id, amount, conn)
        target_name = target_record['name']
        if not updated:
            return await self.bot.reply("no changes made to cards `{0}` owned by {1}.".format(card_name, target_name))
        return await self.bot.reply("changed amount of cards `{0}` owned by {1} by {2}."
                                    .format(card_name, target_name, updated))

    @commands.command(pass_context=True, no_pm=True, aliases=['sendcard'])
    @req.registration
    async def givecard(self, context):
        user = context.message.author.id
        # format: !givecard clonepa Swamp 2
        target, card = context.message.content.split(maxsplit=2)[1:]  # target = 'clonepa', card= 'Swamp 2'
        amount_re = re.search(r'\s+(\d+)$', card)
        if amount_re:
            amount = int(amount_re.group(1))
            card = card[:-len(amount_re.group(0))]
        else:
            amount = 1

        result_dict = give_card(user, target, card, amount)

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
    @req.registration
    async def checkdeck(self, context):
        message = context.message
        deck = message.content[len(message.content.split()[0]):].strip()
        missing_cards = validate_deck(deck, message.author.id)

        if missing_cards:
            needed_cards_str = '\n'.join(["{0} {1}".format(missing_cards[card], card)
                                          for card in missing_cards])
            await self.bot.reply(("you don't have the cards for that deck!! " +
                                  "You need:\n```{1}```").format(message.author.id, needed_cards_str))
        else:
            hashed_deck = deckhash.make_deck_hash(*deckhash.convert_deck_to_boards(deck))
            await self.bot.send_message(mapleconfig.get_mainchannel_id(),
                                        "<@{0}> has submitted a collection-valid deck! hash: `{1}`"
                                        .format(message.author.id, hashed_deck))

    @commands.command(pass_context=True, aliases=['mtglinks'])
    @req.registration
    async def maplelinks(self, context):
        username = users.get_record(context.message.author.id, 'name')
        await self.bot.reply(("\nCollection: http://qubeley.biz/mtg/collection/{0}" +
                              "\nDeckbuilder: http://qubeley.biz/mtg/deckbuilder/{0}"
                              ).format(username))

    @commands.command()
    @req.debug
    @db.operation_async
    async def draftadd(self, target, sets, deck, conn=None, cursor=None):
        await self.bot.type()
        deck = deck.strip()
        deck = deckhash.convert_deck_to_boards(deck)
        deck = collections.Counter(deck[0] + deck[1])

        sets = sets.split()

        target_id = users.get_record(target, 'discord_id')

        ids_to_add = []

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
            added = update(target_id, mvid, ids_to_add[mvid], conn)
            counter += added

        await self.bot.reply('added {0} cards from sets `{1}` to collection of <@{2}>'.format(counter, sets, target_id))

    @commands.command(pass_context=True)
    @db.operation_async
    async def hascard(self, context, target, card, conn=None, cursor=None):
        card = context.message.content.split(maxsplit=2)[2]
        target_record = users.get_record(target)
        if not target_record:
            return await self.bot.reply("user {0} doesn't exist!".format(target))
        cursor.execute('''SELECT cards.card_name, users.name, SUM(collection.amount_owned) FROM collection
                       INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id
                       INNER JOIN users ON collection.owner_id      = users.discord_id
                       WHERE (cards.card_name LIKE :card OR cards.multiverse_id = :card)
                       AND (users.name = :target COLLATE NOCASE OR  users.discord_id = :target)
                       GROUP BY cards.card_name''',
                       {'card': card, 'target': target})
        result = cursor.fetchone()
        if not result:
            await self.bot.reply('{0} has no card `{1}`'.format(target_record['name'], card))
            return
        await self.bot.reply('{target} has {amount} of `{card}`'.format(target=result[1],
                                                                        amount=result[2],
                                                                        card=result[0]))


def setup(bot):
    bot.add_cog(MTGCollection(bot))
