import asyncio
import sqlite3
import math
import sys
import random
import json
import re
import os
import time
import base64
import collections
import logging

import coloredlogs
import requests
from discord.ext import commands

import bottalk
import deckhash
import mapleconfig


TOKEN = mapleconfig.get_token()
MTGOX_CHANNEL_ID = mapleconfig.get_mainchannel_id()
DEBUG_WHITELIST = mapleconfig.get_debug_whitelist()

os.environ['COLOREDLOGS_LOG_FORMAT'] = "%(asctime)s %(name)s %(levelname)s %(message)s"
coloredlogs.install(level='INFO')

IN_TRANSACTION = []

logger = logging.getLogger('maplebot')


logger.info('Loading booster price overrides...')
try:
    with open('pack_price_override.json', 'r') as override_file:
        BOOSTER_OVERRIDE = json.load(override_file)
    logger.info('Loaded {amount} booster price overrides'.format(amount=len(BOOSTER_OVERRIDE)))
except FileNotFoundError:
    logger.warn('No booster price override file found')
    BOOSTER_OVERRIDE = {}


logger.info('Loading rarity cache...')
try:
    with open('rarity_cache.json', 'r') as raritycache_file:
        RARITY_CACHE = collections.defaultdict(str, json.load(raritycache_file))
    logger.info('Loaded rarity cache with {sets} sets'.format(sets=len(RARITY_CACHE)))
except FileNotFoundError:
    logger.warn('No rarity cache found')
    RARITY_CACHE = collections.defaultdict(str)


maplebot = commands.Bot(command_prefix='!', description='maple the magic cat', help_attrs={"name": "maplehelp"})

# ---- decorators for commands ---- #


def poopese(cmd):
    oldaliases = [cmd.name] + cmd.aliases
    newaliases = []
    for alias in oldaliases:
        newalias = alias.replace('n', 'm').replace('b', 'v')
        if newalias != alias:
            newaliases.append(newalias)
    for newalias in newaliases:
        maplebot.commands[newalias] = cmd
        maplebot.get_command(cmd.name).aliases += [newalias]


def debug_command():
    def predicate(context):
        is_debugger = context.message.author.id in DEBUG_WHITELIST
        if not is_debugger and context.command.name != "maplehelp":
            asyncio.ensure_future(maplebot.reply("that's a debug command, you rascal!"))
        return is_debugger
    return commands.check(predicate)


def requires_registration():
    def predicate(context):
        registered = is_registered(context.message.author.id)
        if not registered and context.command.name != "maplehelp":
            asyncio.ensure_future(maplebot.reply("you ain't registered!!!"))
        return registered
    return commands.check(predicate)


# ---- type converters ---- #


def to_upper(argument):
    return argument.upper()


def to_lower(argument):
    return argument.lower()


# ---- utility functions ---- #


def update_user_collection(user, multiverse_id, amount=1, conn=None):
    '''Updates the entry on table `collection` for card of multiverse id arg(multiverse_id) owned by arg(user) (discord_id string).
    If no entry and arg(amount) is positive, creates entry with amount_owned = arg(amount).
    If entry already exists, changes its amount_owned by arg(amount), down to zero.
    Allows for passing an existing sqlite3 connection to arg(conn) for mass card updatings.
    Returns amount of cards actually added/removed.'''

    # check if an existing sqlite connection was provided, record whether it was, if it wasn't create one
    selfconn = False if conn else True
    if not conn:
        conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()

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
    # at this point we know the user already has some of the card, so update the amount_owned, increasing it or decreasing it
    else:
        amount_owned = has_already[0]
        # select the real amount to change
        # if amount < 0, pick amount_owned if amount would remove more than that, else just amount
        # if amount > 0, it's just amount
        if amount < 0:
            amount_to_change = -amount_owned if (-amount > amount_owned) else amount
        else:
            amount_to_change = amount
        cursor.execute("UPDATE collection SET amount_owned = amount_owned + :amount WHERE owner_id=:name AND multiverse_id=:mvid",
                       {"name": user,
                        "mvid": multiverse_id,
                        "amount": amount_to_change})
    conn.commit()

    # if sqlite connection was self-contained, close it
    if selfconn:
        conn.close()
    return amount_to_change


def search_card(query, page=1):
    response = requests.get('https://api.scryfall.com/cards/search', params={'q': query, 'page': page}).json()
    if response['object'] == 'list':
        return response
    if response['object'] == 'error':
        return False


def load_mtgjson():
    '''Reads AllSets.json from mtgjson and returns the resulting dict'''
    with open('AllSets.json', encoding="utf8") as allsets_file:
        cardobj = json.load(allsets_file)
    # force set codes to caps
    cursor = sqlite3.connect('maple.db').cursor()
    cursor.execute("SELECT code FROM set_map")
    sets = cursor.fetchall()

    for card_set in sets:
        if card_set[0] in cardobj:
            cardobj[card_set[0].upper()] = cardobj.pop(card_set[0])

    cursor.connection.close()
    return cardobj


def get_booster_price(card_set):
    '''returns either mtggoldfish price,
    override price or the default of $3.25'''
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM timestamped_base64_strings WHERE name='mtggoldfish'")
    result = cursor.fetchone()

    if result:
        if result[2] + 86400 < time.time():  # close enough to a day
            goldfish_html = requests.get('https://www.mtggoldfish.com/prices/online/boosters').text
            b64html = base64.b64encode(str.encode(goldfish_html))
            cursor.execute('''UPDATE timestamped_base64_strings
                            SET b64str=:b64str, timestamp=:timestamp WHERE name="mtggoldfish"''',
                           {"b64str": b64html, "timestamp": time.time()})
            logger.info("mtggoldfish data stale, fetched new data")
        else:
            goldfish_html = base64.b64decode(result[1]).decode()
            logger.info("mtggoldfish data fresh!")
    else:
        goldfish_html = requests.get('https://www.mtggoldfish.com/prices/online/boosters').text
        b64html = base64.b64encode(str.encode(goldfish_html))
        cursor.execute('''INSERT INTO timestamped_base64_strings
                          values ('mtggoldfish', :b64str, :timestamp)''',
                       {"b64str": b64html, "timestamp": time.time()})
        logger.info("No mtggoldfish cache, created new record...")

    conn.commit()
    conn.close()

    set_info = get_set_info(card_set)
    if set_info:
        setname = set_info['name']
    # this is hideous
    regex = r"<a class=\"priceList-set-header-link\" href=\"\/index\/\w+\"><img class=\"[\w\- ]+\" alt=\"\w+\" src=\"[\w.\-\/]+\" \/>\n<\/a><a class=\"priceList-set-header-link\" href=\"[\w\/]+\">{setname}<\/a>[\s\S]*?<div class='priceList-price-price-wrapper'>\n([\d.]+)[\s\S]*?<\/div>".format(setname=setname)
    div_match = re.search(regex, goldfish_html)

    if card_set in BOOSTER_OVERRIDE:
        return BOOSTER_OVERRIDE[card_set]
    if div_match:
        return float(div_match.group(1))
    return 3.25


def verify_nick(nick):
    '''returns True if nick doesn't exist in db, False if it does'''
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE name = :name COLLATE NOCASE",
                   {"name": nick})
    result = cursor.fetchone()
    conn.close()
    return False if result else True


def calc_elo_change(winner, loser):
    '''calculates elo change for given winner and loser values'''
    k = 32
    r1 = math.pow(10, winner / 400)
    r2 = math.pow(10, loser / 400)

    e1 = r1 / (r1 + r2)
    e2 = r2 / (r1 + r2)

    rr1 = winner + k * (1.0 - e1)
    rr2 = loser + k * (0 - e2)

    return math.ceil(rr1), math.ceil(rr2)


def get_set_info(set_code):
    '''returns setmap values for a given setcode'''
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM set_map WHERE code like :scode", {"scode": set_code})
    result = cursor.fetchone()
    conn.close()

    if result:
        return {"name": result[0], "code": result[1], "altcode": result[2]}
    return None


def cache_rarities(card_set):
    '''Adds key to RARITY_CACHE named card_set,
    which is a dict of format {rarity: [list of multiverse_ids]}.
    Returns amount of cards cached'''
    rarity_map = {'Mythic Rare': 'mythic rare',
                  'Rare': 'rare',
                  'Uncommon': 'uncommon',
                  'Common': 'common',
                  'Basic Land': 'land'}

    cursor = sqlite3.connect('maple.db').cursor()

    set_rarity_dict = collections.defaultdict(list)

    cursor.execute("SELECT rarity, multiverse_id FROM cards WHERE card_set = :card_set",
                   {"card_set": card_set})
    cards = cursor.fetchall()
    cursor.connection.close()

    if not cards:
        raise Exception('no cards for set {0} found'.format(card_set))

    for card in cards:
        try:
            mapped_rarity = rarity_map[card[0]]
        except KeyError:
            mapped_rarity = card[0].lower()

        set_rarity_dict[mapped_rarity].append(card[1])

    # turn it back into a normal dict so it can't be modified by other functions
    # when calling nonexisting keys
    RARITY_CACHE[card_set] = dict(set_rarity_dict)

    cached_count = sum([len(set_rarity_dict[rarity]) for rarity in set_rarity_dict])
    logger.info("just cached {0} card rarities from {1}".format(cached_count, card_set))
    logger.info("saving cache to disk...")
    with open('rarity_cache.json', 'w') as outfile:
        json.dump(RARITY_CACHE, outfile)
    logger.info("saved cache with {sets} sets".format(sets=len(RARITY_CACHE)))

    return cached_count


def gen_booster(card_set, seeds):
    '''generates boosters for a card set from a list of seeds'''
    cardobj = load_mtgjson()
    outbooster = []

    cursor = sqlite3.connect('maple.db').cursor()

    rarity_dict = {
        "rarities": ["rare", "mythic rare", "uncommon", "common", "special", "land"],
        "other_shit": ["token", "marketing"]
    }

    if card_set in cardobj:
        for seed in seeds:

            random.seed(seed['seed'])
            mybooster = []
            if 'booster' not in cardobj[card_set]:
                booster = ["rare", "uncommon", "uncommon", "uncommon", "common", "common", "common",
                           "common", "common", "common", "common", "common", "common", "common"]
            else:
                booster = cardobj[card_set]['booster']
            for i in booster:
                if isinstance(i, str):
                    mybooster.append(i)
                elif isinstance(i, list):
                    if set(i) == {"rare", "mythic rare"}:
                        mybooster.append(random.choice(["rare"] * 7 + ["mythic rare"] * 1))
                    elif set(i) == {"foil", "power nine"}:
                        mybooster.append(random.choice((["mythic rare"] + ["rare"] * 4 +
                                                        ["uncommon"] * 6 + ["common"] * 9) * 98 +
                                                       ["power nine"] * 2))
                    else:
                        mybooster.append(random.choice(i))

            if not RARITY_CACHE[card_set]:
                logger.info(card_set, "rarities not cached, workin on it...")
                cache_rarities(card_set)

            generated_booster = []
            for rarity_card in mybooster:
                try:
                    if rarity_card in rarity_dict["rarities"]:
                        card_pool = RARITY_CACHE[card_set][rarity_card]
                    elif rarity_card == "power nine":
                        card_pool = RARITY_CACHE[card_set]["special"]
                    elif rarity_card in rarity_dict["other_shit"]:
                        card_pool = RARITY_CACHE[card_set]["common"]
                    else:
                        # this flattens the rarity dict so we get all the cards
                        card_pool = sorted({x for v in RARITY_CACHE[card_set].values() for x in v})
                except KeyError:
                    logger.warn('no cards of rarity {0} in set {1}'.format(rarity_card, card_set))
                    card_pool = []
                if card_pool:
                    chosen_card_id = random.choice(card_pool)
                    cursor.execute("""SELECT multiverse_id, card_name, rarity FROM cards
                                   WHERE multiverse_id = :chosen_card_id""",
                                   {"chosen_card_id": chosen_card_id})
                    chosen_card = cursor.fetchone()
                    generated_booster.append(chosen_card)
            outbooster += [{"rowid": seed['rowid'], "booster": generated_booster, "seed": seed['seed']}]
    cursor.connection.close()
    return outbooster


def give_homie_some_lands(who):
    '''give 60 lands to new user'''
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    user_record = get_user_record(who)
    mvid = [439857, 439859, 439856, 439858, 439860]
    for i in mvid:
        cursor.execute("INSERT OR IGNORE INTO collection VALUES (:name,:mvid,60,CURRENT_TIMESTAMP)",
                       {"name": user_record['name'], "mvid": i})
    conn.commit()
    conn.close()


def give_booster(owner, card_set, amount=1):
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()

    outmessage = ""
    card_set = card_set.upper()  # just in case
    cardobj = load_mtgjson()
    cursor.execute("SELECT card_set FROM cards WHERE card_set LIKE :cardset", {"cardset": card_set})
    if not (card_set in cardobj):
        raise KeyError
    owner_id = get_user_record(owner, 'discord_id')
    for i in range(amount):
        random.seed()
        booster_seed = random.getrandbits(32)
        cursor.execute("INSERT INTO booster_inventory VALUES (:owner, :cset, :seed)", {"owner": owner_id, "cset": card_set, "seed": booster_seed})
    conn.commit()
    conn.close()
    if outmessage == "":
        outmessage = "booster added to inventory!"
    return outmessage


def adjustbux(who, how_much):
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET cash = cash + :how_much WHERE discord_id=:who OR name=:who",
                   {"how_much": '%.2f' % how_much, "who": who})
    rowcount = cursor.rowcount
    conn.commit()
    conn.close()
    return True if rowcount else False


def open_booster(owner, card_set, amount):
    opened_boosters = []
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    if amount == "all":
        cursor.execute("SELECT *, rowid FROM booster_inventory WHERE owner_id=:name AND card_set LIKE :set",
                       {"name": owner, "set": card_set})
    else:
        cursor.execute("SELECT *, rowid FROM booster_inventory WHERE owner_id=:name AND card_set LIKE :set LIMIT :amount",
                       {"name": owner, "set": card_set, "amount": amount})
    boosters = cursor.fetchall()
    if not boosters:
        return opened_boosters

    seed_list = []
    for mybooster in boosters:
        seed_list += [{"rowid": mybooster[3], "seed": mybooster[2]}]
    outboosters = gen_booster(card_set, seed_list)

    for generated_booster in outboosters:
        outstring = ""
        for card in generated_booster['booster']:
            cursor.execute('''SELECT * FROM collection WHERE owner_id=:name
                           AND multiverse_id=:mvid AND amount_owned > 0''',
                           {"name": owner, "mvid": card[0]})
            cr = cursor.fetchone()
            if not cr:
                cursor.execute("INSERT INTO collection VALUES (:name,:mvid,1,CURRENT_TIMESTAMP)", {"name": owner, "mvid": card[0]})
            else:
                cursor.execute("UPDATE collection SET amount_owned = amount_owned + 1 WHERE owner_id=:name AND multiverse_id=:mvid",
                               {"name": owner, "mvid": card[0]})
            outstring += "{name} -- {rarity}\n".format(name=card[1], rarity=card[2])

        if outstring == "":
            outstring = "It was empty... !"

        opened_boosters.append({"cards": outstring, "seed": generated_booster['seed']})
        cursor.execute("DELETE FROM booster_inventory WHERE rowid=:rowid", {"rowid": int(generated_booster["rowid"])})

    conn.commit()
    conn.close()
    return opened_boosters


def load_set_json(card_set):
    count = 0
    cardobj = load_mtgjson()

    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    if card_set in cardobj:
        for card in cardobj[card_set]['cards']:
            # skip card if it's the back side of a double-faced card
            if card['layout'] in ('double-faced', 'split', 'aftermath') and not card['number'].endswith('a'):
                logger.info('card {0} is double-faced or split and not main, skipping'.format(card['name']))
                continue
            # if multiverseID doesn't exist, generate fallback negative multiverse ID using set and name as seed
            if 'multiverseid' in card:
                mvid = card['multiverseid']
            else:
                random.seed(card['name'] + card_set)
                mvid = -random.randrange(100000000)
                logger.info('IDless card {0} assigned fallback ID {1}'.format(card['name'], mvid))
            if 'colors' not in card:
                colors = "Colorless"
            else:
                colors = ",".join(card['colors'])
            cname = ' // '.join(card['names']) if card['layout'] in ('split', 'aftermath') else card['name']
            cursor.execute("INSERT OR IGNORE INTO cards VALUES(?, ?, ?, ?, ?, ?, ?)",
                           (mvid, cname, card_set, card['type'], card['rarity'], colors, card['cmc']))
            count += 1
        conn.commit()
        conn.close()
        return count
    else:
        conn.close()
        logger.info(card_set + " not in cardobj!")
        return 0


def check_bux(who):
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT cash FROM users WHERE discord_id=:who OR name=:who", {"who": who})
    result = cursor.fetchone()
    conn.close()
    if result:
        return result[0]
    return 0


def validate_deck(deckstring, user):
    deck = deckhash.convert_deck_to_boards(deckstring)

    # flatten tuple of deck and sb into repeating list of all cards,
    # then turn list of repeated card names into dict in format {"name": amount}
    deck = collections.Counter(deck[0] + deck[1])

    missing_cards = {}

    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute('''SELECT card_name, sum(amount_owned) FROM collection
                   INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id
                   WHERE owner_id=:ownerid GROUP BY card_name''',
                   {"ownerid": user})
    collection = cursor.fetchall()
    conn.close()
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


def export_collection_to_sideboard(user):
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute('''SELECT SUM(amount_owned), card_name FROM collection
                   INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id
                   WHERE owner_id = :ownerid GROUP BY card_name ORDER BY SUM(amount_owned) DESC''',
                   {"ownerid": user})
    outstring = '\n'.join(['SB: {0} {1}'.format(card[0], card[1]) for card in cursor.fetchall()])
    conn.close()
    return outstring


def export_collection_to_list(user):
    who = get_user_record(user)
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute('''SELECT amount_owned, card_name, card_set, card_type, rarity,
                   cards.multiverse_id, cards.colors, cards.cmc, collection.date_obtained
                   FROM collection INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id
                   WHERE owner_id = :ownerid''',
                   {"ownerid": who['discord_id']})
    out = []
    for card in cursor.fetchall():
        out.append({"amount": card[0], "name": card[1], "set": card[2], "type": card[3],
                    "rarity": card[4], "multiverseid": card[5], "color": card[6], "cmc": card[7], "date": card[8]})
    conn.close()
    return out


def is_registered(discord_id):
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT discord_id FROM users WHERE discord_id=:id", {"id": discord_id})
    r = cursor.fetchone()
    conn.close()
    if r:
        return True
    else:
        return False


def get_user_record(who, field=None):
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE discord_id=:who OR name=:who COLLATE NOCASE",
                   {"who": who})
    columns = [description[0] for description in cursor.description]
    r = cursor.fetchone()
    conn.close()
    if not r:
        raise KeyError

    out_dict = collections.OrderedDict.fromkeys(columns)
    for i, key in enumerate(out_dict):
        out_dict[key] = r[i]

    return out_dict[field] if field else out_dict


def update_elo(who, elo):
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET elo_rating =:elo WHERE discord_id=:who OR name=:who",
                   {"elo": elo, "who": who})
    conn.commit()
    conn.close()


def give_card(user, target, card, amount):
    # check that amount > 0:
    return_dict = dict.fromkeys(['code', 'card_name', 'amount_owned', 'target_id'])
    if amount < 1:
        return_dict['code'] = 4  # = invalid amount
        return return_dict
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    # user is guaranteed valid by the command parser
    # check that target is valid:
    cursor.execute("SELECT discord_id FROM users WHERE discord_id=:target OR name=:target", {"target": target})
    r = cursor.fetchone()
    # if target exists and is not user:
    if r and r[0] != user:
        target_id = r[0]
    else:
        conn.close()
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
        conn.close()
        return_dict['code'] = 2  # = card not in collection
        return return_dict

    # check that user has enough of card:
    if amount > origin_amountowned:
        conn.close()
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
        if counter < 0:
            logger.warn('you fucked something up dogg, counter is ' + counter)
            break
        if counter == 0:
            conn.commit()
            break

    # set up the return dict
    return_dict['code'] = 0  # = success!
    return_dict['card_name'] = card_name
    return_dict['target_id'] = target_id
    conn.close()
    return return_dict


def make_ptpb(text):
    response = requests.post('https://ptpb.pw/', data={"content": text})
    return next(i.split()[1] for i in response.text.split('\n') if i.startswith('url:'))


def split_every_n(tosplit, n: int, preserve_newline=False):
    if preserve_newline:
        out_list = []
        out_string = ''
        for line in tosplit.splitlines(True):
            if len(out_string + line) < n:
                out_string += line
            else:
                out_list.append(out_string)
                out_string = line
        out_list.append(out_string)
        return out_list
    else:
        return [tosplit[i:i + n] for i in range(0, len(tosplit), n)]


def codeblock(string):
    return '```{0}```'.format(string)


# -------------------          ------------------- #


async def big_output_confirmation(context, output: str, max_len=1500, formatting=str):
    '''checks if some output is longer than max_len(default: 1500). if so, asks user for confirmation on sending,
        if confirmed, says output with formatting given by optional function parameter 'formatting' '''
    def check(message):
        msg = message.content.lower()
        return (msg.startswith('y') or msg.startswith('n'))

    output_length = len(output)
    if output_length > max_len:
        await maplebot.reply("do you really want me to send all this? it's {0} characters long... [y/n]".format(output_length))
        reply = await maplebot.wait_for_message(channel=context.message.channel,
                                                author=context.message.author,
                                                check=check,
                                                timeout=60)
        if not reply:
            return None
        reply_content = reply.content.lower()
        confirm = True if reply_content.startswith('y') else False
        if confirm:
            processed = split_every_n(output, max_len, True)
        else:
            await maplebot.reply("ok!")
            return False
    else:
        processed = [output]

    for split in processed:
        await maplebot.say(formatting(split))
        asyncio.sleep(0.05)
    return True


# ------------------- COMMANDS ------------------- #


@maplebot.command()
@debug_command()
async def updatecollection(target: str, card_id: str, amount: int = 1):
    target_record = get_user_record(target)
    if not target_record:
        return await maplebot.reply("invalid user")
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute('SELECT card_name FROM cards WHERE multiverse_id = ?', (card_id,))
    result = cursor.fetchone()
    if not result:
        conn.close()
        return await maplebot.reply("no card with multiverse id {0} found!".format(card_id))
    card_name = result[0]
    updated = update_user_collection(target_record['discord_id'], card_id, amount, conn)
    conn.close()
    target_name = target_record['name']
    if not updated:
        return await maplebot.reply("no changes made to cards `{0}` owned by {1}.".format(card_name, target_name))
    return await maplebot.reply("changed amount of cards `{0}` owned by {1} by {2}.".format(card_name, target_name, updated))


@maplebot.command(pass_context=True, no_pm=True, aliases=['mapleregister'])
async def register(context, nickname: str):
    user = context.message.author.id
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE discord_id=?', (user))
    if cursor.fetchall():
        await maplebot.reply("user with discord ID {0} already exists. don't try to pull a fast one on old maple!!"
                             .format(user))
    elif not verify_nick(nickname):
        await maplebot.reply("user with nickname {0} already exists. don't try to confuse old maple you hear!!"
                             .format(nickname))
    else:
        cursor.execute("INSERT INTO users VALUES (?,?,1500,50.00)", (user, nickname))
        conn.commit()
        conn.close()
        give_homie_some_lands(user)
        give_booster(user, "M13", 15)
        await maplebot.reply('created user in database with ID {0} and nickname {1}!\n'.format(user, nickname) +
                             'i gave homie 60 of each Basic Land and 15 Magic 2013 Booster Packs!!')
    conn.close()
    return


@maplebot.command(pass_context=True, no_pm=True, aliases=['sendcard'])
@requires_registration()
async def givecard(context):
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

    await maplebot.reply(reply_dict[result_dict['code']])


@maplebot.command(pass_context=True, aliases=['mtglinks'])
async def maplelinks(context):
    username = get_user_record(context.message.author.id, 'name')
    await maplebot.reply(("\nCollection: http://qubeley.biz/mtg/collection/{0}" +
                          "\nDeckbuilder: http://qubeley.biz/mtg/deckbuilder/{0}"
                          ).format(username))


@maplebot.command(pass_context=True, aliases=['getcollection'])
@requires_registration()
async def exportcollection(context):
    await maplebot.type()
    exported_collection = export_collection_to_sideboard(context.message.author.id)
    pb_url = make_ptpb(exported_collection)

    await maplebot.reply("here's your exported collection: {0}\ncopy it into cockatrice to build a deck!!"
                         .format(pb_url))


@maplebot.command(pass_context=True, aliases=['validatedeck', 'deckcheck'])
@requires_registration()
async def checkdeck(context):
    message = context.message
    deck = message.content[len(message.content.split()[0]):].strip()
    missing_cards = validate_deck(deck, message.author.id)

    if missing_cards:
        needed_cards_str = '\n'.join(["{0} {1}".format(missing_cards[card], card)
                                      for card in missing_cards])
        await maplebot.reply(("you don't have the cards for that deck!! " +
                              "You need:\n```{1}```").format(message.author.id, needed_cards_str))
    else:
        hashed_deck = deckhash.make_deck_hash(*deckhash.convert_deck_to_boards(deck))
        await maplebot.send_message(maplebot.get_channel(MTGOX_CHANNEL_ID),
                                    "<@{0}> has submitted a collection-valid deck! hash: `{1}`"
                                    .format(message.author.id, hashed_deck))


@maplebot.command()
@debug_command()
async def draftadd(target, sets, deck):
    # await maplebot.type()
    deck = deck.strip()
    deck = deckhash.convert_deck_to_boards(deck)
    deck = collections.Counter(deck[0] + deck[1])

    sets = sets.split()

    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()

    target_id = get_user_record(target, 'discord_id')

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
        update_user_collection
        added = update_user_collection(target_id, mvid, ids_to_add[mvid], conn)
        counter += added

    conn.close()
    await maplebot.reply('added {0} cards from sets `{1}` to collection of <@{2}?'.format(counter, sets, target_id))

    # update_user_collection()


@maplebot.command(pass_context=True, aliases=['boosterprice', 'checkprice'])
async def packprice(context, card_set: str):
    '''!packprice [setcode]
    returns mtgo booster pack price for the set via mtggoldfish'''
    setname = get_set_info(card_set)['name']

    await maplebot.type()
    price = get_booster_price(card_set)
    if price:
        out = "{0} booster pack price: ${1}".format(setname, price)
    else:
        out = "no prices found for that set brah"

    await maplebot.reply(out)


@maplebot.command(pass_context=True, aliases=['maplebux', 'maplebalance'])
@requires_registration()
async def checkbux(context):
    await maplebot.reply("your maplebux balance is: ${0}"
                         .format('%.2f' % check_bux(context.message.author.id)))


@maplebot.command(pass_context=True, aliases=['givemaplebux', 'sendbux'])
@requires_registration()
async def givebux(context, target: str, amount: float):
    amount = float('%.2f' % amount)
    myself = context.message.author.id
    mycash = check_bux(myself)
    otherperson = ""
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM users WHERE discord_id=:who OR name=:who",
                   {"who": target})
    result = cursor.fetchone()
    if result:
        otherperson = result[0]
    else:
        await maplebot.reply("I'm not sure who you're trying to give money to...")
        return

    cursor.execute("SELECT name FROM users WHERE discord_id=:who OR name=:who",
                   {"who": myself})

    result = cursor.fetchone()
    if result:
        if result[0] == otherperson:
            await maplebot.reply("sending money to yourself... that's shady...")
            return

    if amount < 0:
        await maplebot.reply("wait a minute that's a robbery!")
        return
    if mycash == 0 or mycash - amount < 0:
        await maplebot.reply("not enough bux to ride this trux :surfer:")
        return
    sent, received = adjustbux(myself, -amount), adjustbux(otherperson, amount)
    if sent is received is True:
        await maplebot.reply("sent ${0} to {1}"
                             .format(amount, target))
    conn.close()


@maplebot.command(pass_context=True, aliases=['openpack', 'obooster', 'opack'])
@requires_registration()
async def openbooster(context, card_set: to_upper, amount: int = 1):
    user = context.message.author.id
    await maplebot.type()

    boosters_list = open_booster(user, card_set, amount)
    boosters_opened = len(boosters_list)
    if boosters_opened == 1:
        await maplebot.reply("\n```{0}```\nhttp://qubeley.biz/mtg/booster/{1}/{2}".format(boosters_list[0]['cards'], card_set, boosters_list[0]['seed']))
    elif boosters_opened > 1:
        outstring = "{0} opened {1} boosters by {2}:\n\n".format(boosters_opened,
                                                                 card_set,
                                                                 context.message.author.display_name)
        for i, booster in enumerate(boosters_list):
            outstring += "------- Booster #{0} -------\n".format(i + 1)
            outstring += booster['cards'] + '\n'
        pb_url = make_ptpb(outstring)
        await maplebot.reply("your {1} opened {2} boosters: {3}"
                             .format(user, boosters_opened, card_set, pb_url))
    else:
        await maplebot.reply("don't have any of those homie!!"
                             .format(user))


@maplebot.command(pass_context=True, aliases=['buypack'])
@requires_registration()
async def buybooster(context, card_set: to_upper, amount: int = 1):
    user = context.message.author.id
    if user in IN_TRANSACTION:
        await maplebot.reply("you're currently in a transaction! ...guess I'll cancel it for you"
                             .format(user))
        IN_TRANSACTION.remove(user)

    cardobj = load_mtgjson()
    if card_set not in cardobj:
        return await maplebot.reply("I don't know what set that is...")

    setname = get_set_info(card_set)['name']
    pack_price = get_booster_price(card_set)
    price = pack_price * amount

    if check_bux(user) < price:
        await maplebot.reply("hey idiot why don't you come back with more money")
        return

    IN_TRANSACTION.append(user)
    await maplebot.reply("Buy {0} {1} booster{plural} for ${2}?"
                         .format(amount, setname, round(price, 2), plural=("s" if amount > 1 else "")))

    msg = await maplebot.wait_for_message(timeout=15.0, author=context.message.author)
    if not msg:
        return
    if (msg.content.startswith('y') or msg.content.startswith('Y')):
        adjustbux(user, float(price) * -1)
        result = give_booster(user, card_set, amount)
    elif (msg.content.startswith('n') or msg.content.startswith('N')):
        result = "well ok"
    else:
        result = None
    if result:
        await maplebot.reply("{0}".format(result))
    IN_TRANSACTION.remove(user)


@maplebot.command(pass_context=True)
@requires_registration()
async def recordmatch(context, winner, loser):
    winner_record = get_user_record(winner)
    loser_record = get_user_record(loser)
    winner_elo = winner_record['elo_rating']
    loser_elo = loser_record['elo_rating']
    new_elo = calc_elo_change(winner_elo, loser_elo)
    bux_adjustment = 3.00 * (new_elo[0] - winner_elo) / 32
    bux_adjustment = round(bux_adjustment, 2)
    loser_bux_adjustment = round(bux_adjustment / 3, 2)

    winnerid, loserid = winner_record['discord_id'], loser_record['discord_id']

    update_elo(winnerid, new_elo[0])
    update_elo(loserid, new_elo[1])

    adjustbux(winnerid, bux_adjustment)
    adjustbux(loserid, bux_adjustment / 3)
    await maplebot.reply("{0} new elo: {1}\n{2} new elo: {3}\n{0} payout: ${4}\n{2} payout: ${5}"
                         .format(winner_record['name'],
                                 new_elo[0],
                                 loser_record['name'],
                                 new_elo[1],
                                 bux_adjustment,
                                 loser_bux_adjustment))


@maplebot.command(pass_context=True)
async def hash(context):
    thing_to_hash = context.message.content[len(context.message.content.split()[0]):]
    hashed_thing = deckhash.make_deck_hash(*deckhash.convert_deck_to_boards(thing_to_hash))
    await maplebot.reply('hashed deck: {0}'.format(hashed_thing))


@maplebot.command(pass_context=True)
@requires_registration()
async def changenick(context, nick):
    if not verify_nick(nick):
        await maplebot.reply(("user with nickname {0} already exists. " +
                              "don't try to confuse old maple you hear!!").format(nick))
    else:
        conn = sqlite3.connect('maple.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET name=:nick WHERE discord_id=:user",
                       {"nick": nick, "user": context.message.author.id})
        conn.commit()
        await maplebot.reply("updated nickname to {0}".format(nick))
        conn.close()


@maplebot.command(pass_context=True)
async def userinfo(context, user=None):
    user = user if user else context.message.author.id
    record = get_user_record(user)
    outstring = ('*nickname*: {name}' +
                 '\n*discord id*: {discord_id}' +
                 '\n*elo rating*: {elo_rating}' +
                 '\n*maplebux*: {cash}').format(**record)
    outstring = re.sub(r'\n\s+', '\n', outstring)

    await maplebot.say(outstring)


# ---- That Debug Shit ---- #

@maplebot.command(pass_context=True)
@debug_command()
async def query(context):
    query = context.message.content.split(maxsplit=1)[1]
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    if ('DROP' in query.upper() and context.message.author.id != '234042140248899587'):
        await maplebot.reply("pwease be careful wif dwoppy u_u")
    outstring = ""
    try:
        cursor.execute(query)
        outstring = '\n'.join(str(x) for x in cursor.fetchall())
    except sqlite3.OperationalError:
        outstring = "sqlite operational error homie...\n{0}".format(sys.exc_info()[1])

    if outstring == "":
        outstring = "rows affected : {0}".format(cursor.rowcount)
    await big_output_confirmation(context, outstring, formatting=codeblock)
    conn.commit()
    conn.close()


@maplebot.command(pass_context=True)
@debug_command()
async def gutdump(context, table: str = "users", limit: int = 0):
    if table == "maple":
        with open(__file__) as file:
            output = file.read()
    else:
        conn = sqlite3.connect('maple.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM {0} {1}".format(table, 'LIMIT {0}'.format(limit) if limit else ''))
        output = "{names}\n\n{output}".format(names=[description[0] for description in cursor.description],
                                              output='\n'.join(str(x) for x in cursor.fetchall()))
        conn.close()
    await big_output_confirmation(context, output, formatting=codeblock)


@maplebot.command()
@debug_command()
async def setupdb():
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                 (discord_id TEXT, name TEXT, elo_rating INTEGER, cash REAL)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS match_history
                 (winner TEXT, loser TEXT, winner_deckhash TEXT, loser_deckhash TEXT,
                 FOREIGN KEY(winner) REFERENCES users(discord_id), FOREIGN KEY(loser) REFERENCES users(discord_id))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS cards
                 (multiverse_id INTEGER PRIMARY KEY, card_name TEXT, card_set TEXT, card_type TEXT, rarity TEXT, colors TEXT, cmc TEXT)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS collection
                 (owner_id TEXT, multiverse_id INTEGER, amount_owned INTEGER, date_obtained TIMESTAMP,
                 FOREIGN KEY(owner_id) REFERENCES users(discord_id), FOREIGN KEY(multiverse_id) REFERENCES cards(multiverse_id),
                 PRIMARY KEY (owner_id, multiverse_id))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS booster_inventory
                 (owner_id TEXT, card_set TEXT, seed INTEGER,
                 FOREIGN KEY(owner_id) REFERENCES users(discord_id), FOREIGN KEY(card_set) REFERENCES set_map(code))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS set_map
                 (name TEXT, code TEXT, alt_code TEXT, PRIMARY KEY (code, alt_code))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS timestamped_base64_strings
                 (name TEXT PRIMARY KEY, b64str TEXT, timestamp REAL)''')

    cursor.execute('''CREATE TRIGGER IF NOT EXISTS delete_from_collection_on_zero
                   AFTER UPDATE OF amount_owned ON collection BEGIN
                   DELETE FROM collection WHERE amount_owned < 1;
                   END''')

    cursor.execute('''CREATE TRIGGER IF NOT EXISTS update_date_obtained
                   AFTER UPDATE OF amount_owned ON collection
                   WHEN new.amount_owned > old.amount_owned BEGIN
                   UPDATE collection SET date_obtained = CURRENT_TIMESTAMP WHERE rowid = new.rowid;
                   END''')

    conn.commit()
    conn.close()


@maplebot.command()
@debug_command()
async def populatesetinfo():
    # do not use load_mtgjson() here
    with open('AllSets.json', encoding="utf8") as f:
        cardobj = json.load(f)
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    for card_set in cardobj:
        logger.info(cardobj[card_set]["name"])
        name = ""
        code = ""
        alt_code = ""
        if "name" in cardobj[card_set]:
            name = cardobj[card_set]["name"]
        if "code" in cardobj[card_set]:
            code = cardobj[card_set]["code"]
        if "magicCardsInfoCode" in cardobj[card_set]:
            alt_code = cardobj[card_set]["magicCardsInfoCode"]
        if code != "" and name != "":
            cursor.execute("INSERT OR IGNORE INTO set_map VALUES (?, ?, ?)", (name, code, alt_code))
    conn.commit()
    conn.close()


@maplebot.command()
@debug_command()
async def populatecardinfo():
    # maplebot will time out while waiting for this to finish, so you know be careful out there
    cardobj = load_mtgjson()
    setcount = 0
    count = 0
    await maplebot.say('conking out for a while while i slurp these sets...')
    for card_set in cardobj:
        if "code" not in cardobj[card_set]:
            continue
        count += load_set_json(cardobj[card_set]['code'].upper())
        setcount += 1
        logger.info("populated {1} cards from set #{0}".format(count, setcount))
    logger.info('added {0} cards from {1} sets'.format(count, setcount))
    await maplebot.say("i'm back!")


@maplebot.command()
@debug_command()
async def loadsetjson(cardset):
    load_set_json(cardset)


@maplebot.command(pass_context=True)
@debug_command()
async def givebooster(context, card_set, target=None, amount: int = 1):
    card_set = card_set.upper()
    if not target:
        target = context.message.author.id
    logger.info('giving {0} booster(s) of set {1} to {2}'.format(amount, card_set, target))
    try:
        give_booster(target, card_set, amount)
    except KeyError:
        return await maplebot.reply("{0} is not a valid set!!".format(card_set))
    target_id = get_user_record(target, 'discord_id')
    await maplebot.reply("{0} {1} booster(s) added to <@{2}>'s inventory!"
                         .format(amount, card_set, target_id))


@maplebot.command(aliases=["adjustbux"])
@debug_command()
async def changebux(target, amount: float):
    adjustbux(target, amount)
    await maplebot.reply("updated bux")


@maplebot.command()
async def mapletest():
    await maplebot.say("i'm {0} and my guts are made of python {1}, brah :surfer:"
                       .format(maplebot.user.name, sys.version.split()[0]))


@maplebot.command()
async def blackjack():
    await maplebot.say("```\n\nholy shit piss\n\n```")


@maplebot.command(pass_context=True, aliases=["maplecard", "maplecardinfo"])
async def cardinfo(context):
    message = context.message
    query = message.content.split(maxsplit=1)
    if len(query) == 1:
        return None
    else:
        query = query[1]
    await maplebot.type()
    search_results = search_card(query)
    if not search_results:
        await maplebot.reply('No results found for *"{0}"*'.format(query))
        return
    card = search_results['data'][0]
    total_found = search_results['total_cards']
    if total_found > 1:
        more_string = '\n*{0} other cards matching that query were found.*'.format(total_found - 1)
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
    multiverse_id = card['multiverse_ids'][0] if card['multiverse_ids'] else None
    if multiverse_id:
        gatherer_string = 'http://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid={0}'.format(multiverse_id)
    else:
        gatherer_string = "this card has no gatherer page. must be something weird or pretty new...!"
    reply_string = [more_string,
                    '**{card_name}**',
                    'Set: {card_set}',
                    printings_string,
                    gatherer_string,
                    card['image_uris']['large'] if 'image_uris' in card
                    else card['card_faces'][0]['image_uris']['large']]
    reply_string = '\n'.join(reply_string).format(card_name=card['name'],
                                                  card_set=card['set'].upper())
    await maplebot.reply(reply_string)


@maplebot.command(pass_context=True, aliases=["maplecardsearch", "maplesearch"])
async def cardsearch(context):
    query = context.message.content.split(maxsplit=1)
    if len(query) == 1:
        return None
    else:
        query = query[1]
    await maplebot.type()
    response = search_card(query)
    if not response:
        await maplebot.reply('No results found for *"{0}"*'.format(query))
        return
    search_results = response['data']
    reply_string = 'Cards found:'
    for i, card in enumerate(search_results):
        if i > 10:
            reply_string += '\nand {0} more'.format(response['total_cards'] - 10)
            break
        reply_string += '\n**{name}** ({set}): {mana_cost} {type_line}'.format(name=card['name'],
                                                                               set=card['set'].upper(),
                                                                               mana_cost=card['mana_cost'],
                                                                               type_line=card['type_line'] if 'type_line' in card else '?')
    await maplebot.reply(reply_string)


@maplebot.command(pass_context=True)
async def hascard(context, target, card):
    card = context.message.content.split(maxsplit=2)[2]
    cursor = sqlite3.connect('maple.db').cursor()
    target_record = get_user_record(target)
    if not target_record:
        return await maplebot.reply("user {0} doesn't exist!".format(target))
    cursor.execute('''SELECT cards.card_name, users.name, SUM(collection.amount_owned) FROM collection
                   INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id
                   INNER JOIN users ON collection.owner_id      = users.discord_id
                   WHERE (cards.card_name LIKE :card OR cards.multiverse_id = :card)
                   AND (users.name = :target COLLATE NOCASE OR  users.discord_id = :target)
                   GROUP BY cards.card_name''',
                   {'card': card, 'target': target})
    result = cursor.fetchone()
    cursor.connection.close()
    if not result:
        await maplebot.reply('{0} has no card `{1}`'.format(target_record['name'], card))
        return
    await maplebot.reply('{target} has {amount} of `{card}`'.format(target=result[1],
                                                                    amount=result[2],
                                                                    card=result[0]))


@maplebot.command(pass_context=True)
async def setcode(context, set_name: str):
    set_name = context.message.content.split(maxsplit=1)[1]
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name, code FROM set_map WHERE name LIKE :set_name", {"set_name": '%{0}%'.format(set_name)})
    results = cursor.fetchall()
    conn.close()
    if not results:
        return await maplebot.reply("no sets matchin *{0}* were found...".format(set_name))
    if len(results) > 14:
        return await maplebot.reply("too many matching sets!! narrow it down a little")
    outstring = '\n'.join(["code for set *{0[0]}* is **{0[1]}**".format(result) for result in results])
    await maplebot.reply(outstring)


@maplebot.event
async def on_ready():
    logger.info('maplebot is ready')
    logger.info('[username: {0.name} || id: {0.id}]'.format(maplebot.user))


@maplebot.event
async def on_message(message):
    if message.author == maplebot.user:
        return
    if message.content.startswith(maplebot.command_prefix):
        await maplebot.process_commands(message)
    else:
        bottalk_request = await bottalk.get_request(maplebot, message)
        if bottalk_request:
            try:
                await bottalk.respond_request(maplebot, message.author, bottalk_request[0], eval(bottalk_request[1]))
            except Exception as exc:
                await bottalk.respond_request(maplebot, message.author, bottalk_request[0], exc)


if __name__ == "__main__":
    commands = list(maplebot.commands.keys())[:]
    for command in commands:
        poopese(maplebot.commands[command])
    maplebot.run(TOKEN)
