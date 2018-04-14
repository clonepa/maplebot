import asyncio
import sqlite3
import math
import sys
import random
import json
import re
import time
import base64
import collections

import requests
import discord

import bottalk
import mtg
import deckhash
import mapleconfig


CLIENT = discord.Client()
TOKEN = mapleconfig.get_token()
MTGOX_CHANNEL_ID = mapleconfig.get_mainchannel_id()
DEBUG_WHITELIST = mapleconfig.get_debug_whitelist()

IN_TRANSACTION = []

print('Loading booster price overrides...')
try:
    with open('pack_price_override.json', 'r') as override_file:
        BOOSTER_OVERRIDE = json.load(override_file)
    print('Loaded {amount} booster price overrides'.format(amount=len(BOOSTER_OVERRIDE)))
except FileNotFoundError:
    print('No booster price override file found')
    BOOSTER_OVERRIDE = {}


print('Loading rarity cache...')
try:
    with open('rarity_cache.json', 'r') as raritycache_file:
        RARITY_CACHE = collections.defaultdict(str, json.load(raritycache_file))
    print('Loaded rarity cache with {sets} sets'.format(sets=len(RARITY_CACHE)))
except FileNotFoundError:
    print('No rarity cache found')
    RARITY_CACHE = collections.defaultdict(str)





def load_mtgjson():
    '''Reads AllSets.json from mtgjson and returns the resulting dict'''
    with open('AllSets.json', encoding="utf8") as allsets_file:
        cardobj = json.load(allsets_file)
    #force set codes to caps
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
        if result[2] + 86400 < time.time(): #close enough to a day
            goldfish_html = requests.get('https://www.mtggoldfish.com/prices/online/boosters').text
            b64html = base64.b64encode(str.encode(goldfish_html))
            cursor.execute('''UPDATE timestamped_base64_strings
                            SET b64str=:b64str, timestamp=:timestamp WHERE name="mtggoldfish"''',
                           {"b64str": b64html, "timestamp": time.time()})
            print("mtggoldfish data stale, fetched new data")
        else:
            goldfish_html = base64.b64decode(result[1]).decode()
            print("mtggoldfish data fresh!")
    else:
        goldfish_html = requests.get('https://www.mtggoldfish.com/prices/online/boosters').text
        b64html = base64.b64encode(str.encode(goldfish_html))
        cursor.execute('''INSERT INTO timestamped_base64_strings
                          values ('mtggoldfish', :b64str, :timestamp)''',
                       {"b64str": b64html, "timestamp": time.time()})
        print("No mtggoldfish cache, created new record...")

    conn.commit()
    conn.close()

    set_info = get_set_info(card_set)
    if set_info:
        setname = set_info['name']
    #this is hideous
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
    cursor.execute("SELECT * FROM users WHERE name='" + nick + "'")
    if cursor.fetchone():
        conn.close()
        return False
    conn.close()
    return True

def calc_elo_change(winner, loser):
    '''calculates elo change for given winner and loser values'''
    k = 32
    r1 = math.pow(10, winner/400)
    r2 = math.pow(10, loser/400)

    e1 = r1/(r1 + r2)
    e2 = r2/(r1 + r2)

    rr1 = winner + k * (1.0 - e1)
    rr2 = loser + k * (0 - e2)

    return math.ceil(rr1), math.ceil(rr2)

def get_set_info(set_code):
    '''returns setmap values for a given setcode'''
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM set_map WHERE code like :scode", {"scode":set_code})
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
    print("just cached", cached_count, "card rarities from", card_set)
    print("saving cache to disk...")
    with open('rarity_cache.json', 'w') as outfile:
        json.dump(RARITY_CACHE, outfile)
    print("saved cache with {sets} sets".format(sets=len(RARITY_CACHE)))

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
            if not 'booster' in cardobj[card_set]:
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
                print(card_set, "rarities not cached, workin on it...")
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
                    print('WARNING no cards of rarity {0} in set {1}'.format(rarity_card, card_set))
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
                       {"name": user_record[0], "mvid": i})
    conn.commit()
    conn.close()

def give_booster(owner, card_set, amount=1):
    start_time = time.time()
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()

    outmessage = ""
    card_set = card_set.upper() #just in case
    cardobj = load_mtgjson()
    cursor.execute("SELECT card_set FROM cards WHERE card_set LIKE :cardset", {"cardset": card_set})
    
    if not (card_set in cardobj):
        outmessage = "I don't know where to find that kind of booster..."
        return outmessage
    elif not cursor.fetchone():
        outmessage = "that set's not in my brain!!"
        return outmessage
    elif not ('booster' in cardobj[card_set]):
        outmessage = "I've heard of that set but I've never seen a booster for it, I'll see what I can do..."

    #we don't need to give other people boosters now
    cursor.execute("SELECT discord_id FROM users WHERE name LIKE :name OR discord_id LIKE :name", {"name": owner})
    u = cursor.fetchone()[0]
    for i in range(amount):
        random.seed()
        booster_seed = random.getrandbits(32)
        cursor.execute("INSERT INTO booster_inventory VALUES (:owner, :cset, :seed)", {"owner": u, "cset": card_set, "seed": booster_seed})
    conn.commit()
    conn.close()
    if outmessage == "":
        outmessage = "booster added to inventory!"
    print(time.time() - start_time)
    return outmessage

def adjustbux(who, how_much):
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET cash = cash + :how_much WHERE discord_id=:who OR name=:who", {"how_much":'%.2f'%how_much,"who":who})
    conn.commit()
    conn.close()

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
    if boosters == None:
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
                      {"name": owner, "mvid": card[0] })
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
            if card['layout'] == 'double-faced' and not card['mciNumber'].endswith('a'):
                print('card {0} is double-faced and not front, skipping'.format(card['name']))
                continue
            # if multiverseID doesn't exist, generate fallback negative multiverse ID using set and name as seed
            if 'multiverseid' in card:
                mvid = card['multiverseid']
            else:
                random.seed(card['name'] + card_set)
                mvid = -random.randrange(100000000)
                # print('IDless card {0} assigned fallback ID {1}'.format(card['name'], mvid))
            if not 'colors' in card:
                colors = "Colorless"
            else:
                colors = ",".join(card['colors'])
            cursor.execute("INSERT OR IGNORE INTO cards VALUES(?, ?, ?, ?, ?, ?, ?)",
                           (mvid, card['name'], card_set, card['type'], card['rarity'], colors, card['cmc']))
            count += 1
        conn.commit()
        conn.close()
        return count
    else:
        conn.close()
        print(card_set + " not in cardobj!")
        return 0
    
def check_bux(who):
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT cash FROM users WHERE discord_id=:who OR name=:who", {"who": who} )
    result = cursor.fetchone()
    conn.close()
    if result:
        return result[0]
    return 0

def validate_deck(deckstring, user):
    deck = deckhash.convert_deck_to_boards(deckstring)

    #flatten tuple of deck and sb into repeating list of all cards, 
    #then turn list of repeated card names into dict in format {"name": amount}
    deck = collections.Counter(deck[0] + deck[1]) 

    missing_cards = {}

    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT card_name, sum(amount_owned) FROM collection INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id WHERE owner_id=:ownerid GROUP BY card_name", {"ownerid": user})
    collection = cursor.fetchall()
    conn.close()
    collection = dict((n, a) for n, a in collection) #turn list of tuples to dict in same format as deck

    for card in deck:
        #if user has card in collection, check difference between required amt and owned amt
        #if amt required by deck > amt owned, set the key for card in missing_cards to the difference
        if card in collection:
            deck_collection_diff = deck[card] - collection[card]
            if deck_collection_diff > 0:
                missing_cards[card] = deck_collection_diff
        #if they don't have it, add the full amount of card required to missing_cards
        else:
            missing_cards[card] = deck[card]

    return missing_cards

def export_collection_to_sideboard(user):
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(amount_owned), card_name FROM collection INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id WHERE owner_id = :ownerid GROUP BY card_name ORDER BY SUM(amount_owned) DESC", {"ownerid": user})
    outstring = '\n'.join(['SB: {0} {1}'.format(card[0], card[1]) for card in cursor.fetchall()])
    conn.close()
    return outstring
            
def export_collection_to_list(user):
    who = get_user_record(user)
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT amount_owned, card_name, card_set, card_type, rarity, cards.multiverse_id, cards.colors, cards.cmc, collection.date_obtained FROM collection INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id WHERE owner_id = :ownerid", {"ownerid": who[0]})
    out = []
    for card in cursor.fetchall():
        out.append( {"amount": card[0], "name": card[1], "set": card[2], "type": card[3], "rarity": card[4], "multiverseid": card[5], "color": card[6], "cmc": card[7], "date": card[8]} )
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
    if field == None:
        field = "*"
    cursor.execute("SELECT {0} FROM users WHERE discord_id='{1}' OR name='{1}'".format(field, who))
    r = cursor.fetchone()
    conn.close()
    return r

def update_elo(who, elo):
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET elo_rating =:elo WHERE discord_id=:who OR name=:who",{"elo": elo, "who": who})
    conn.commit()
    conn.close()
    

def give_card(user, target, card, amount):
    # check that amount > 0:
    return_dict = dict.fromkeys(['code', 'card_name', 'amount_owned', 'target_id'])
    if amount < 1:
        return_dict['code'] = 4 # = invalid amount
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
        return_dict['code'] = 1 # = target invalid
        return return_dict
    # check that user has card & get all instances of it:
    cursor.execute("SELECT collection.rowid, collection.multiverse_id, amount_owned, card_name FROM collection INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id WHERE owner_id = :user AND (card_name LIKE :card OR collection.multiverse_id LIKE :card)", {"user": user,"card": card})
    origin_cards = cursor.fetchall()
    if origin_cards:
        origin_amountowned = sum([row[2] for row in origin_cards])
        card_name = origin_cards[0][3]
    else:
        conn.close()
        return_dict['code'] = 2 # = card not in collection
        return return_dict

    # check that user has enough of card:
    if amount > origin_amountowned:
        conn.close()
        if str(card) == str(origin_cards[0][1]): # if input card is a multiverse id:
            return_dict['code'] = 5 # = not enough of printing
        else:
            return_dict['code'] = 3 # = not enough of card
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
        cursor.execute("SELECT rowid, amount_owned FROM collection WHERE owner_id = :target AND multiverse_id = :multiverse_id", {"target": target_id,"multiverse_id": multiverse_id})
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
            print('you fucked something up dogg, counter is', counter)
            break
        if counter == 0:
            conn.commit()
            break

    # set up the return dict
    return_dict['code'] = 0 # = success!
    return_dict['card_name'] = card_name
    return_dict['target_id'] = target_id
    conn.close()
    return return_dict

def make_ptpb(text):
    response = requests.post('https://ptpb.pw/', data={"content": text})
    return next(i.split()[1] for i in response.text.split('\n') if i.startswith('url:'))

async def cmd_register(user, message, client=CLIENT):
    nickname = message.content.split()[1]
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE discord_id=' + user)
    if cursor.fetchall():
        await CLIENT.send_message(message.channel, 'user with discord ID ' + user +
                                  ' already exists. don\'t try to pull a fast one on old maple!!')
    elif not verify_nick(nickname):
        await CLIENT.send_message(message.channel, 'user with nickname ' + nickname +
                                  ' already exists. don\'t try to confuse old maple you hear!!')
    else:
        cursor.execute("INSERT INTO users VALUES ('" + user + "','" + nickname + "',1500,50.00)")
        conn.commit()
        conn.close()
        give_homie_some_lands(user)
        give_booster(user, "M13", 15)
        await CLIENT.send_message(message.channel, 'created user in database with ID ' + user +
                                  ' and nickname ' + nickname +
                                  '!\nI gave homie 60 of each Basic Land and 15 Magic 2013 Booster Packs!!')
    conn.close()
    return 

async def cmd_givecard(user, message, client=CLIENT):
    #format: !givecard clonepa Swamp 2
    target, card = message.content.split(maxsplit=2)[1:] # = target = 'clonepa', card= 'Swamp 2'
    amount_re = re.search(r'\seed+(\d+)$', card)
    if amount_re:
        amount = int(amount_re[1])
        card = card[:-len(amount_re[0])]
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

    await CLIENT.send_message(message.channel,
                              "<@{0}> {1}".format(user, reply_dict[result_dict['code']]))

async def cmd_exportcollection(user, message, client=CLIENT):
    await CLIENT.send_typing(message.channel)
    exported_collection = export_collection_to_sideboard(user)

    pb_url = make_ptpb(exported_collection)

    await CLIENT.send_message(
        message.channel,
        "<@{0}>, here's your exported collection: {1}\ncopy it into cockatrice to build a deck!!"
        .format(user, pb_url)
    )

async def cmd_checkdeck(user, message, client=CLIENT):
    deck = message.content[len(message.content.split()[0]):].strip()
    missing_cards = validate_deck(deck, user)

    if missing_cards:
        needed_cards_str = '\n'.join(["{0} {1}".format(missing_cards[card], card)
                                      for card in missing_cards])
        await CLIENT.send_message(message.channel,
                                  ("<@{0}>, you don't have the cards for that deck!! " +
                                   "You need:\n```{1}```").format(user, needed_cards_str))
    else:
        hashed_deck = deckhash.make_deck_hash(*deckhash.convert_deck_to_boards(deck))
        await CLIENT.send_message(CLIENT.get_channel(MTGOX_CHANNEL_ID),
                                  "<@{0}> has submitted a collection-valid deck! hash: `{1}`"
                                  .format(user, hashed_deck))
        
async def cmd_packprice(user, message, client=CLIENT):
    '''!packprice [setcode]
    returns mtgo booster pack price for the set via mtggoldfish'''
    card_set = message.content.split()[1].upper()
    setname = get_set_info(card_set)['name']

    await CLIENT.send_typing(message.channel)
    price = get_booster_price(card_set)
    if price:
        out = "{0} booster pack price: ${1}".format(setname, price)
    else:
        out = "no prices found for that set brah"

    await CLIENT.send_message(message.channel, out)

async def cmd_checkbux(user, message, client=CLIENT):
    await CLIENT.send_message(message.channel,
                              "<@{0}> your maplebux balance is: ${1}"
                              .format(user, '%.2f'%check_bux(user)))

async def cmd_givebux(user, message, client=CLIENT):
    player_1 = message.content.split()[1]
    player_2 = float('%.2f'%float(message.content.split()[2]))
    myself = user
    mycash = check_bux(myself)
    otherperson = ""
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM users WHERE discord_id=:who OR name=:who",
                   {"who":player_1})
    result = cursor.fetchone()
    if result:
        otherperson = result[0]
    else:
        await CLIENT.send_message(message.channel,
                                  "I'm not sure who you're trying to give money to...")
        return

    cursor.execute("SELECT name FROM users WHERE discord_id=:who OR name=:who", {"who":myself})
    result = cursor.fetchone()
    if result:
        if result[0] == otherperson:
            await CLIENT.send_message(message.channel,
                                      "sending money to yourself... that's shady...")
            return

    if player_2 < 0:
        await CLIENT.send_message(message.channel, "wait a minute that's a robbery!")
        return
    if mycash == 0 or mycash - player_2 < 0:
        await CLIENT.send_message(message.channel, "not enough bux to ride this trux :surfer:")
        return
    adjustbux(myself, player_2 * -1)
    adjustbux(otherperson, player_2)
    await CLIENT.send_message(message.channel, "sent ${0} to {1}".format(player_2, player_1))
    conn.close()

async def cmd_openbooster(user, message, client=CLIENT):
    args = message.content.split(maxsplit=2)[1:]
    if len(args) < 2:
        amount = 1
    elif args[1] == "all":
        amount = "all"
    elif args[1].isdigit():
        amount = int(args[1])
    else:
        await CLIENT.send_message(message.channel, "<@{0}> that's nonsense bro!!".format(user))
        return
    card_set = args[0].upper()

    await CLIENT.send_typing(message.channel)
    boosters_list = open_booster(user, card_set, amount)
    boosters_opened = len(boosters_list)
    print (boosters_list)
    if boosters_opened == 1:
        await CLIENT.send_message(message.channel,
                                  "<@{0}>\n```{1}```\nhttp://qubeley.biz/mtg/booster/{2}/{3}".format(user, boosters_list[0]['cards'], card_set, boosters_list[0]['seed']))
    elif boosters_opened > 1:
        outstring = "{0} opened {1} boosters by {2}:\n\n".format(boosters_opened,
                                                                 card_set,
                                                                 message.author.display_name)
        for i, booster in enumerate(boosters_list):
            outstring += "------- Booster #{0} -------\n".format(i + 1)
            outstring += booster['cards'] + '\n'
        pb_url = make_ptpb(outstring)
        await CLIENT.send_message(message.channel,
                                  "<@{0}>, your {1} opened {2} boosters: {3}"
                                  .format(user, boosters_opened, card_set, pb_url))
        
    else:
        await CLIENT.send_message(message.channel, "<@{0}> don't have any of those homie!!"
                                  .format(user))
    
async def cmd_maplecard(user, message, client=CLIENT):
    cname = message.content[len(message.content.split()[0]):]
    cname = cname.replace(" ", "%20")
    await CLIENT.send_message(message.channel,
                              "https://api.scryfall.com/cards/named?fuzzy=!{0}!&format=image"
                              .format(cname))
    
async def cmd_buybooster(user, message, client=CLIENT):
    if user in IN_TRANSACTION:
        await CLIENT.send_message(message.channel, "<@{0}> you're currently in a transaction! ...guess I'll cancel it for you".format(user))
        IN_TRANSACTION.remove(user)
    args = message.content.split(maxsplit=2)[1:] # !buybooster set amount
    card_set = args[0].upper()
    amount = int(args[1]) if len(args) == 2 else 1

    cardobj = load_mtgjson()
    if card_set not in cardobj:
        await CLIENT.send_message(message.channel,
                                  "<@{0}> I don't know what set that is...".format(user))
        return

    setname = get_set_info(card_set)['name']
    pack_price = get_booster_price(card_set)
    price = pack_price * amount

    if check_bux(user) < price:
        await CLIENT.send_message(message.channel, "<@{0}> hey idiot why don't you come back with more money".format(user))
        return

    IN_TRANSACTION.append(user)
    await CLIENT.send_message(message.channel, "<@{0}> Buy {1} {2} booster{plural} for ${3}?"
                              .format(user,
                                      amount,
                                      setname,
                                      '%.2f' % float(price),
                                      plural=("s" if amount > 1 else "")))

    msg = await CLIENT.wait_for_message(timeout=15.0, author=message.author)
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
        await CLIENT.send_message(message.channel, "<@{0}> {1}".format(user, result))
    IN_TRANSACTION.remove(user)

async def cmd_recordmatch(user, message, client=CLIENT):
    player_1, player_2 = message.content.split()[1:]
    player_1_elo = get_user_record(player_1, "elo_rating")[0]
    player_2_elo = get_user_record(player_2, "elo_rating")[0]

    newelo = calc_elo_change(player_1_elo, player_2_elo)
    bux_adjustment = 3.00 * (newelo[0] - player_1_elo)/32
    bux_adjustment = float('%.2f'%bux_adjustment)

    update_elo(player_1, newelo[0])
    update_elo(player_2, newelo[1])

    adjustbux(player_1, bux_adjustment)
    adjustbux(player_2, bux_adjustment/3)
    await CLIENT.send_message(message.channel, player_1 + " new elo: " + str(newelo[0])
                              + "\n" +
                              player_2 + " new elo: " + str(newelo[1]) +
                              "\npayout: $" + str(bux_adjustment))
    
async def cmd_hash(user, message, client=CLIENT):
    thing_to_hash = message.content[len(message.content.split()[0]):]
    hashed_thing = deckhash.make_deck_hash(*deckhash.convert_deck_to_boards(thing_to_hash))
    await CLIENT.send_message(message.channel, 'hashed deck: ' + hashed_thing)

async def cmd_changenick(user, message, client=CLIENT):
    nick = message.content.split()[1]
    if not verify_nick(nick):
        await CLIENT.send_message(message.channel,
                                  ("user with nickname {0} already exists. " +
                                   "don't try to confuse old maple you hear!!").format(nick))
    else:
        conn = sqlite3.connect('maple.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET name='" + nick + "' WHERE discord_id='" + user + "'")
        conn.commit()
        await CLIENT.send_message(message.channel, message.author.mention + " updated nickname")
        conn.close()

async def cmd_userinfo(user, message, client=CLIENT):
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE discord_id='" + user + "'")
    result = cursor.fetchone()
    outstring = '''*nickname*: {nick}
                *discord id*: {discord_id}
                *elo rating*: {elo}
                *maplebux*: {maplebux}'''.format(nick=result[1],
                                                 discord_id=result[0],
                                                 elo=result[2],
                                                 maplebux=result[3])
    outstring = re.sub(r'\n\s+', '\n', outstring)

    await CLIENT.send_message(message.channel, outstring)
    conn.close()

async def cmd_query(user, message, client=CLIENT):
    query = message.content[len(message.content.split()[0]):]
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    if ('DROP' in query.upper() and user != '234042140248899587'):
        await CLIENT.send_message(message.channel, "pwease be careful wif dwoppy u_u")
    outstring = ""
    try:
        cursor.execute(query)
        for i in cursor.fetchall():
            if len(outstring) > 1500:
                await CLIENT.send_message(message.channel, "```" + outstring + "\n```")
                outstring = ""
            outstring += str(i) + "\n"
    except sqlite3.OperationalError:
        outstring = "sqlite operational error homie...\n" + str(sys.exc_info()[1])

    if outstring == "":
        outstring = "No output so it probably worked"
    await CLIENT.send_message(message.channel, "```" + outstring + "```")
    conn.commit()
    conn.close()
    
async def cmd_gutdump(user, message, client=CLIENT):
    table = ""
    if len(message.content.split()) < 2:
        table = "users"
    else:
        table = message.content.split()[1]

    if table == "maple":
        with open(__file__) as file:
            out = file.read(1024)
            while out:
                await CLIENT.send_message(message.channel,
                                          "```"  + out.replace("```", "[codeblock]") + "```")
                out = file.read(1024)
                await asyncio.sleep(0.25)
        return
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM " + table)
    outstring = ""
    names = [description[0] for description in cursor.description]
    for i in cursor.fetchall():
        if len(outstring) > 1500:
            await CLIENT.send_message(message.channel,
                                      "```" + str(names) + "\n\n" + outstring + "\n```")
            outstring = ""
        outstring += str(i) + "\n"
    if outstring:
        await CLIENT.send_message(message.channel,
                                  "```" + str(names) + "\n\n" + outstring + "\n```")
    conn.close()

async def cmd_setupdb(user, message, client=CLIENT):
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                 (discord_id TEXT, name TEXT, elo_rating INTEGER, cash REAL)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS match_history
                 (winner TEXT, loser TEXT, winner_deckhash TEXT, loser_deckhash TEXT, FOREIGN KEY(winner) REFERENCES users(discord_id), FOREIGN KEY(loser) REFERENCES users(discord_id))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS cards
                 (multiverse_id INTEGER PRIMARY KEY, card_name TEXT, card_set TEXT, card_type TEXT, rarity TEXT, colors TEXT, cmc TEXT)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS collection
                 (owner_id TEXT, multiverse_id INTEGER, amount_owned INTEGER, date_obtained TIMESTAMP,
                 FOREIGN KEY(owner_id) REFERENCES users(discord_id), FOREIGN KEY(multiverse_id) REFERENCES cards(multiverse_id),
                 PRIMARY KEY (owner_id, multiverse_id))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS booster_inventory
                 (owner_id TEXT, card_set TEXT, seed INTEGER, FOREIGN KEY(owner_id) REFERENCES users(discord_id), FOREIGN KEY(card_set) REFERENCES set_map(code))''')

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

async def cmd_populatesetinfo(user, message, client=CLIENT):
    #do not use load_mtgjson() here
    with open ('AllSets.json', encoding="utf8") as f:
        cardobj = json.load(f)
    conn = sqlite3.connect('maple.db')
    cursor = conn.cursor()
    for card_set in cardobj:
        print(cardobj[card_set]["name"])
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
    
async def cmd_populatecardinfo(user, message, client=CLIENT, set=None):
    #bot will time out while waiting for this to finish, so you know be careful out there
    outstring = ""
    cardobj = load_mtgjson()
    setcount = 0
    count = 0
    for card_set in cardobj:
        if "code" not in cardobj[card_set]:
            continue
        count += load_set_json(cardobj[card_set]['code'].upper())
        setcount += 1
        print(count, setcount)
    print('added {0} cards from {1} sets'.format(count, setcount))
    
async def cmd_givebooster(user, message, client=CLIENT):
    card_set = message.content.split()[1].upper()
    if len(message.content.split()) > 2:
        person_getting_booster = message.content.split()[2]
    if len(message.content.split()) > 3:
        amount = int(message.content.split()[3])
    else:
        amount = 1
        person_getting_booster = user


    result = give_booster(person_getting_booster, card_set, amount)
    await CLIENT.send_message(message.channel, result)
        
async def cmd_adjustbux(user, message, client=CLIENT):
    p1 = message.content.split()[1]
    p2 = float(message.content.split()[2])
    adjustbux(p1, p2)
    await CLIENT.send_message(message.channel, "updated bux")
        
async def cmd_loadsetjson(user, message, client=CLIENT):
    card_set = message.content.split()[1].upper()

    result = load_set_json(card_set)
    if result > -1:
        await CLIENT.send_message(message.channel, 'added {0} cards from set {1}.'.format(result, card_set))
    else:
        await CLIENT.send_message(message.channel, 'set code {0} not found'.format(card_set))


async def cmd_mapletest(user, message, client=CLIENT):
    await CLIENT.send_message(message.channel, "i'm {0} and my guts are made of python 3.6, brah :surfer:".format(CLIENT.user.name))

async def cmd_coinbet(user, message, client=CLIENT):
    pcall = message.content.split()[1]
    pbet = float(message.content.split()[2])

    if not pbet:
        await CLIENT.send_message(message.channel, 'gotta pony up cowboy')
        return
    if pbet < 0.01:
        await CLIENT.send_message(message.channel, 'no microtrading allowed')
        return
    if check_bux(user) < pbet:
        await CLIENT.send_message(message.channel, "you don't have that kind of cash!")
        return
    
    rigged_coin = ["heads"] * 5 + ["tails"] * 5 + ["side"]
    if pcall.lower() not in rigged_coin:
        await CLIENT.send_message(message.channel, 'heads or tails only, dirtbag')
        return
    if pcall == "side":
        await CLIENT.send_message(message.channel, "<@{0}> you called... {1}? ok well, I'm flipping the coin.".format(user, pcall.lower()))
    else:
        await CLIENT.send_message(message.channel, "<@{0}> you called {1}. I'm flipping the coin...".format(user, pcall.lower()))
    await CLIENT.send_typing(message.channel)
    await asyncio.sleep(1.25)
    result = random.choice(rigged_coin)
    outstring = ""
    payout = 0
    winner = (pcall.lower() == result)
    if winner:
        if result == "side":
            payout = pbet * len(rigged_coin)
            outstring = "somehow, you called it!! you won ${0}! big time gambler bonus!".format('%.2f'%payout)
        else:
            payout = pbet
            outstring = "you called it!! you won ${0}! enjoy your fat stack ".format('%.2f'%payout)
    else:
        payout = pbet * -1
        if result == "side":
            outstring = "wow, guess I win!"
        else:
            outstring = "you beefed it!!"
    adjustbux(user, payout)

    if result != "side":
        await CLIENT.send_message(message.channel, "<@{0}> it was {1}... {2}".format(user,result,outstring))
    else:
        await CLIENT.send_message(message.channel, "<@{0}> it landed on its side?!... {1}".format(user, outstring))

async def cmd_blackjack(user, message, client=CLIENT):
    await CLIENT.send_message(message.channel, "```\n\nholy shit piss\n\n```")
        
COMMANDS = {"register": cmd_register,
            "givecard": cmd_givecard,
            "exportcollection": cmd_exportcollection,
            "checkdeck": cmd_checkdeck,
            "packprice": cmd_packprice,
            "checkbux": cmd_checkbux,
            "givebux": cmd_givebux,
            "openbooster": cmd_openbooster,
            "maplecard": mtg.cmd_cardinfo,
            "cardsearch": mtg.cmd_cardsearch,
            "buybooster": cmd_buybooster,
            "hascard": mtg.cmd_hascard,
            "recordmatch": cmd_recordmatch,
            "hash": cmd_hash,
            "changenick": cmd_changenick,
            "userinfo": cmd_userinfo,
            "mapletest": cmd_mapletest}
            #"coinbet": cmd_coinbet}

DEBUG_COMMANDS = {"query": cmd_query,
                  "gutdump": cmd_gutdump,
                  "setupdb": cmd_setupdb,
                  "populatesetinfo": cmd_populatesetinfo,
                  "populatecardinfo": cmd_populatecardinfo,
                  "givebooster": cmd_givebooster,
                  "adjustbux": cmd_adjustbux,
                  "loadsetjson": cmd_loadsetjson,
                  "blackjack": cmd_blackjack}


@CLIENT.event
async def on_ready():
    print('Logged in as')
    print(CLIENT.user.name)
    print(CLIENT.user.id)
    print('------')


@CLIENT.event
async def on_message(message):
    if message.author == CLIENT.user:
        return
    if message.content.startswith('!'):
        user = str(message.author.id)
        command = message.content.split()[0][1:]

        if command in COMMANDS:
            if command == "register" or is_registered(user):
                await COMMANDS[command](user, message, client=CLIENT)
            else:
                await CLIENT.send_message(message.channel, "<@{0}>, you ain't registered!!".format(user))
        elif command in DEBUG_COMMANDS:
            if (user in DEBUG_WHITELIST):
                await DEBUG_COMMANDS[command](user, message, client=CLIENT)
            else:
                await CLIENT.send_message(message.channel, "<@{0}> that's a debug command, you rascal!".format(user))
    else:
        bottalk_request = await bottalk.get_request(CLIENT, message)
        if bottalk_request:
            try:
                await bottalk.respond_request(CLIENT, message.author, bottalk_request[0], eval(bottalk_request[1]))
            except Exception as exc:
                await bottalk.respond_request(CLIENT, message.author, bottalk_request[0], exc)

if __name__ == "__main__":
    CLIENT.run(TOKEN)
