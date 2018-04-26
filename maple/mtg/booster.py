from .. import db
import time
import base64
import logging
import re
import json
import collections
import random

import requests
from discord.ext import commands

from . import mtgutil, collection
from maple import users, req, util

logger = logging.getLogger('maple.mtg.booster')


IN_TRANSACTION = []


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


# ----------------------------------------------------------------------------------------------


@db.operation
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


@db.operation
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

    set_info = mtgutil.get_set_info(card_set)
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


@db.operation
def gen_booster(card_set, seeds, cursor=None, conn=None):
    '''generates boosters for a card set from a list of seeds'''
    cardobj = mtgutil.load_mtgjson()
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
    return outbooster


@db.operation
def give_booster(owner, card_set, amount=1, cursor=None, conn=None):
    card_set = card_set.upper()  # just in case

    cardobj = mtgutil.load_mtgjson()
    cursor.execute("SELECT card_set FROM cards WHERE card_set LIKE :cardset", {"cardset": card_set})
    if not (card_set in cardobj):
        raise KeyError
    owner_id = users.get_record(owner, 'discord_id')
    rowcount = 0
    for i in range(amount):
        random.seed()
        booster_seed = random.getrandbits(32)
        cursor.execute("INSERT INTO booster_inventory VALUES (:owner, :cset, :seed)",
                       {"owner": owner_id, "cset": card_set, "seed": booster_seed})
        rowcount += cursor.rowcount
    conn.commit()
    return rowcount


@db.operation
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


class MTGBoosters():
    def __init__(self, bot):
        self.bot = bot

    @commands.command(pass_context=True, aliases=['packprice', 'checkprice'])
    async def boosterprice(self, context, card_set: str):
        '''shows booster price of set'''
        setname = mtgutil.get_set_info(card_set)['name']

        await self.bot.type()
        price = get_booster_price(card_set)
        if price:
            out = "{0} booster pack price: ${1}".format(setname, price)
        else:
            out = "no prices found for that set brah"

        await self.bot.reply(out)

    @commands.command(pass_context=True, aliases=['buypack'])
    @req.registration
    async def buybooster(self, context, card_set: util.to_upper, amount: int = 1):
        '''purchase any amount of booster packs of set'''
        user = context.message.author.id
        if user in IN_TRANSACTION:
            await self.bot.reply("you're currently in a transaction! ...guess I'll cancel it for you"
                                 .format(user))
            IN_TRANSACTION.remove(user)

        set_info = mtgutil.get_set_info(card_set)

        if not set_info:
            return await self.bot.reply("I don't know what set that is...")

        setname = set_info['name']
        pack_price = get_booster_price(card_set)
        price = pack_price * amount

        if users.get_record(user, 'cash') < price:
            await self.bot.reply("hey idiot why don't you come back with more money")
            return

        IN_TRANSACTION.append(user)
        await self.bot.reply("Buy {0} {1} booster{plural} for ${2}?"
                             .format(amount, setname, round(price, 2), plural=("s" if amount > 1 else "")))

        msg = await self.bot.wait_for_message(timeout=15.0, author=context.message.author)
        if not msg:
            return
        if (msg.content.startswith('y') or msg.content.startswith('Y')):
            users.adjust_cash(user, float(price) * -1)
            result = give_booster(user, card_set, amount)
        elif (msg.content.startswith('n') or msg.content.startswith('N')):
            result = "well ok"
        else:
            result = None
        if result:
            await self.bot.reply("{0}".format(result))
        IN_TRANSACTION.remove(user)

    @commands.command(pass_context=True, aliases=['openpack', 'obooster', 'opack'])
    @req.registration
    async def openbooster(self, context, card_set: util.to_upper, amount: int = 1):
        '''open amount of owned boosters of set'''
        user = context.message.author.id
        await self.bot.type()

        boosters_list = open_booster(user, card_set, amount)
        boosters_opened = len(boosters_list)
        if boosters_opened == 1:
            await self.bot.reply("\n```{0}```\nhttp://qubeley.biz/mtg/booster/{1}/{2}"
                                 .format(boosters_list[0]['cards'], card_set, boosters_list[0]['seed']))
        elif boosters_opened > 1:
            outstring = "{0} opened {1} boosters by {2}:\n\n".format(boosters_opened,
                                                                     card_set,
                                                                     context.message.author.display_name)
            for i, booster in enumerate(boosters_list):
                outstring += "------- Booster #{0} -------\n".format(i + 1)
                outstring += booster['cards'] + '\n'
            pb_url = util.make_ptpb(outstring)
            await self.bot.reply("your {1} opened {2} boosters: {3}"
                                 .format(user, boosters_opened, card_set, pb_url))
        else:
            await self.bot.reply("don't have any of those homie!!"
                                 .format(user))

    @commands.command(pass_context=True, aliases=["givepack"])
    @req.debug
    async def givebooster(self, context, card_set, target=None, amount: int = 1):
        card_set = card_set.upper()
        if not target:
            target = context.message.author.id
        logger.info('giving {0} booster(s) of set {1} to {2}'.format(amount, card_set, target))
        try:
            give_booster(target, card_set, amount)
        except KeyError:
            return await self.bot.reply("{0} is not a valid set!!".format(card_set))
        target_id = users.get_record(target, 'discord_id')
        await self.bot.reply("{0} {1} booster(s) added to <@{2}>'s inventory!"
                             .format(amount, card_set, target_id))


def setup(bot):
    bot.add_cog(MTGBoosters(bot))
