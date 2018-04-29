import collections
import logging
import json
import os
import random
import time
import base64
import re

import requests
from . import deco, util, util_mtg

import mapleconfig


DEBUG_WHITELIST = mapleconfig.get_debug_whitelist()


logger = logging.getLogger('maple.brains')


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


# --- checks


class MapleCheckError(Exception):
    def __init__(self, message):
        self.message = message


class MapleInvalidUser(Exception):
    def __init__(self, user):
        self.user = user


# --- check decorator


def maple_check(func):

    def wrapped(self, context, *args, **kwargs):
        check_success = func(self, context, *args, **kwargs)
        if not check_success[0]:
            raise MapleCheckError(check_success[1])
        else:
            pass
    return wrapped


# --- users.py


@deco.db_operation
def get_record(target, field=None, conn=None, cursor=None):
    cursor.execute("SELECT * FROM users WHERE discord_id=:target OR name=:target COLLATE NOCASE",
                   {"target": target})
    columns = [description[0] for description in cursor.description]
    r = cursor.fetchone()
    if not r:
        raise MapleInvalidUser(target)

    out_dict = collections.OrderedDict.fromkeys(columns)
    for i, key in enumerate(out_dict):
        out_dict[key] = r[i]

    return out_dict[field] if field else out_dict


@deco.db_operation
def set_record(target, field, value, conn=None, cursor=None):
    target_record = get_record(target)
    if field not in target_record:
        raise KeyError(field)
    cursor.execute('''UPDATE users SET {} = :value
                   WHERE discord_id=:target OR name=:target COLLATE NOCASE'''
                   .format(field),
                   {"field": field,
                    "value": value,
                    "target": target})
    conn.commit()
    cursor.execute('''SELECT {} FROM users
                   WHERE discord_id=:target'''.format(field),
                   {"target": target_record['discord_id']})
    return cursor.fetchone()[0]


@deco.db_operation
def verify_nick(nick, conn=None, cursor=None):
    '''returns True if nick doesn't exist in db, False if it does'''
    cursor.execute("SELECT * FROM users WHERE name = :name COLLATE NOCASE",
                   {"name": nick})
    result = cursor.fetchone()
    return False if result else True


def adjust_cash(target, delta: float):
    delta = float(delta)
    target_record = get_record(target)
    new_bux = target_record['cash'] + delta
    print(new_bux)
    response = set_record(target_record['discord_id'], 'cash', new_bux)
    return True if response == new_bux else False


@deco.db_operation
def is_registered(discord_id, conn=None, cursor=None):
    cursor.execute("SELECT discord_id FROM users WHERE discord_id=:id", {"id": discord_id})
    r = cursor.fetchone()
    if r:
        return True
    else:
        return False


@maple_check
def check_registered(self, context):
    return (is_registered(context.message.author.id),
            "you ain't registered!!")


@maple_check
def check_debug(self, context):
    return (context.message.author.id in DEBUG_WHITELIST,
            "that's a debug command, you rascal!!")


# --- db.py


@deco.db_operation
def db_setup(conn=None, cursor=None):
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                 (discord_id TEXT, name TEXT, elo_rating INTEGER, cash REAL)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS match_history
                 (winner TEXT, loser TEXT, winner_deckhash TEXT, loser_deckhash TEXT,
                 FOREIGN KEY(winner) REFERENCES users(discord_id), FOREIGN KEY(loser) REFERENCES users(discord_id))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS cards
                 (multiverse_id INTEGER PRIMARY KEY, card_name TEXT, card_set TEXT,
                 card_type TEXT, rarity TEXT, colors TEXT, cmc TEXT)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS collection
                 (owner_id TEXT, multiverse_id INTEGER, amount_owned INTEGER, date_obtained TIMESTAMP,
                 FOREIGN KEY(owner_id) REFERENCES users(discord_id),
                 FOREIGN KEY(multiverse_id) REFERENCES cards(multiverse_id),
                 PRIMARY KEY(owner_id, multiverse_id))''')

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


# --- mtg/scryfall.py


def scryfall_search(query, page=1):
    response = requests.get('https://api.scryfall.com/cards/search', params={'q': query, 'page': page}).json()
    if response['object'] == 'list':
        return response
    if response['object'] == 'error':
        return False


def scryfall_format(card):
    all_printings = scryfall_search('!"{0}" unique:prints'.format(card['name']))['data']
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


# --- mtg/setup.py


@deco.db_operation
def load_mtgjson(cursor=None, conn=None):
    '''Reads AllSets.json from mtgjson and returns the resulting dict'''
    with open('AllSets.json', encoding="utf8") as allsets_file:
        cardobj = json.load(allsets_file)

    patch_dict = {}
    patch_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'json_patches')
    for patch_file in os.listdir(patch_dir):
        with open(os.path.join(os.path.join(patch_dir, patch_file)), encoding="utf8") as f:
            setname = patch_file[:-5]
            patch_dict[setname] = json.load(f)

    # force set codes to caps
    cursor.execute("SELECT code FROM set_map")
    sets = cursor.fetchall()

    for card_set in sets:
        if card_set[0] in patch_dict:
            logger.info('Patching JSON for {}'.format(card_set[0]))
            cardobj[card_set[0].upper()] = patch_dict[card_set[0]]
        elif card_set[0] in cardobj:
            cardobj[card_set[0].upper()] = cardobj.pop(card_set[0])

    return cardobj


@deco.db_operation
def get_set_info(set_code, conn=None, cursor=None):
    '''returns setmap values for a given setcode'''
    set_code = set_code.upper()
    cursor.execute("SELECT * FROM set_map WHERE code = :scode", {"scode": set_code})
    result = cursor.fetchone()

    if result:
        return {"name": result[0], "code": result[1], "altcode": result[2]}
    else:
        raise KeyError('set {} not found'.format(set_code))


@deco.db_operation
def load_set_json(card_set, cardobj=None, conn=None, cursor=None):
    count = 0
    if not cardobj:
        cardobj = load_mtgjson()

    if card_set in cardobj:
        for card in cardobj[card_set]['cards']:
            # skip card if it's the back side of a double-faced card or the second half of a split card
            if card['layout'] in ('double-faced', 'split', 'aftermath'):
                if card['name'] != card['names'][0]:
                    logger.info('{name} is of layout {layout} and is not main card {names[0]}, skipping'.format(**card))
            elif card['layout'] == 'meld':
                if card['name'] == card['names'][-1]:
                    logger.info('{name} is of layout {layout} and is final card, skipping'.format(**card))
            # if multiverseID doesn't exist, generate fallback negative multiverse ID using mtgjson id as seed
            if 'multiverseid' in card:
                mvid = card['multiverseid']
            else:
                random.seed(card['id'])
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
        return count
    else:
        logger.info(card_set + " not in cardobj!")
        return 0


# --- mtg/collection.py


@deco.db_operation
def get_card(query, card_set=None, as_list=False, name=None, conn=None, cursor=None):
    ''' Get a card from the cards db by its multiverse ID. '''

    if isinstance(query, str) and query.isdigit():
        query = int(query)

    # initial sql and param dict for multiverseID queries
    sql = '''SELECT * FROM cards WHERE (multiverse_id = :query OR card_name LIKE :query) '''

    sql_params = {"query": query}
    # if query is an int then we want mvid
    if isinstance(query, int):
        sql = '''SELECT * FROM cards WHERE multiverse_id = :query'''
        if card_set:
            raise ValueError('set provided with multiverse ID')
    # else if it's a string we're searching names ambiguously, returning first result if mulitple
    elif isinstance(query, str):
        sql = '''SELECT * FROM cards WHERE card_name LIKE :query'''
        if card_set:
            # if card_set was provided modify sql and params accordingly
            sql += '''AND card_set = :card_set'''
            sql_params['card_set'] = card_set
    # any other type and something is wrong
    else:
        raise TypeError('query should be int or str, was {}'.format(type(query).__name__))

    func_to_do = util.fetchall_dict if as_list else util.fetchone_dict
    result = func_to_do(cursor.execute(sql, sql_params))

    if not result:
        raise KeyError('no card found for query {}'.format(query))

    return result


@deco.db_operation
def get_collection_entry(multiverse_id, owner_id, conn=None, cursor=None):
    return util.fetchone_dict(
        cursor.execute('SELECT * FROM collection WHERE multiverse_id = ? AND owner_id = ?', (multiverse_id, owner_id))
    )


@deco.db_operation
def update_collection(user, multiverse_id, amount=1, conn=None, cursor=None):
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


@deco.db_operation
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


@deco.db_operation
def export_to_list(user, cursor=None, conn=None):
    who = get_record(user)
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


@deco.db_operation
def give_homie_some_lands(who, conn=None, cursor=None):
    '''give 60 lands to new user'''
    user_record = get_record(who)
    if not user_record:
        raise KeyError
    mvid = [439857, 439859, 439856, 439858, 439860]
    for i in mvid:
        cursor.execute("INSERT OR IGNORE INTO collection VALUES (:name,:mvid,60,CURRENT_TIMESTAMP)",
                       {"name": user_record['discord_id'], "mvid": i})
        print(cursor.rowcount)
    conn.commit()


@deco.db_operation
def validate_deck(deckstring, user, conn=None, cursor=None):
    deck = util_mtg.convert_deck_to_boards(deckstring)

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


# --- mtg/booster.py


#


@deco.db_operation
def cache_rarities(card_set, conn=None, cursor=None):
    '''Adds key to RARITY_CACHE named card_set,
    which is a dict of format {rarity: [list of multiverse_ids]}.
    Returns amount of cards cached'''
    rarity_map = {'Mythic Rare': 'mythic rare',
                  'Rare': 'rare',
                  'Uncommon': 'uncommon',
                  'Common': 'common',
                  'Basic Land': 'land'}

    set_rarity_dict = collections.defaultdict(list)

    cursor.execute("SELECT rarity, multiverse_id FROM cards WHERE card_set = :card_set",
                   {"card_set": card_set})
    cards = cursor.fetchall()

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


@deco.db_operation
def get_booster_price(card_set, conn=None, cursor=None):
    '''returns either mtggoldfish price,
    override price or the default of $3.25'''
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

    set_info = get_set_info(card_set)
    if set_info:
        setname = set_info['name']
    # this is hideous
    regex = (r"<a class=\"priceList-set-header-link\" href=\"\/index\/\w+\"><img class=\"[\w\- ]+\" alt=\"\w+\" src=\"[\w.\-\/]+\" \/>\n<\/a><a class=\"priceList-set-header-link\" href=\"[\w\/]+\">{setname}<\/a>[\s\S]*?<div class='priceList-price-price-wrapper'>\n([\d.]+)[\s\S]*?<\/div>"
             .format(setname=setname.replace("'", "&#39;")))  # html apostrophe bullshit
    div_match = re.search(regex, goldfish_html)

    if card_set in BOOSTER_OVERRIDE:
        return BOOSTER_OVERRIDE[card_set]
    if div_match:
        return float(div_match.group(1))
    return 3.25


@deco.db_operation
def gen_booster(card_set, seeds, cursor=None, conn=None):
    '''generates boosters for a card set from a list of seeds'''
    cardobj = load_mtgjson()
    outbooster = []

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
                logger.info("{} rarities not cached, workin on it...".format(card_set))
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
    return outbooster


@deco.db_operation
def give_booster(owner, card_set, amount=1, cursor=None, conn=None):

    card_set = get_set_info(card_set)['code']

    owner_id = get_record(owner, 'discord_id')
    rowcount = 0
    for i in range(amount):
        random.seed()
        booster_seed = random.getrandbits(32)
        cursor.execute("INSERT INTO booster_inventory VALUES (:owner, :cset, :seed)",
                       {"owner": owner_id, "cset": card_set, "seed": booster_seed})
        rowcount += cursor.rowcount
    conn.commit()
    return rowcount


@deco.db_operation
def open_booster(owner, card_set, amount, conn=None, cursor=None):
    opened_boosters = []
    if amount == "all":
        cursor.execute("SELECT *, rowid FROM booster_inventory WHERE owner_id=:name AND card_set LIKE :set",
                       {"name": owner, "set": card_set})
    else:
        cursor.execute('''SELECT *, rowid FROM booster_inventory
                       WHERE owner_id=:name AND card_set LIKE :set LIMIT :amount''',
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
                cursor.execute("INSERT INTO collection VALUES (:name,:mvid,1,CURRENT_TIMESTAMP)",
                               {"name": owner, "mvid": card[0]})
            else:
                cursor.execute('''UPDATE collection SET amount_owned = amount_owned + 1
                               WHERE owner_id=:name AND multiverse_id=:mvid''',
                               {"name": owner, "mvid": card[0]})
            outstring += "{name} -- {rarity}\n".format(name=card[1], rarity=card[2])

        if outstring == "":
            outstring = "It was empty... !"

        opened_boosters.append({"cards": outstring, "seed": generated_booster['seed']})
        cursor.execute("DELETE FROM booster_inventory WHERE rowid=:rowid", {"rowid": int(generated_booster["rowid"])})

    conn.commit()
    return opened_boosters
