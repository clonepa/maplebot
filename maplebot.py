import discord
import asyncio
import deckhash
import sqlite3
import math
import sys
import mapletoken
import random
import json
import requests
import re
import time
import base64
import collections

client = discord.Client()
token = mapletoken.get_token()
mtgox_channel_id = mapletoken.get_mainchannel_id()
in_transaction = []

def load_mtgjson():
    with open ('AllSets.json', encoding="utf8") as f:
        cardobj = json.load(f)
    #force set codes to caps
    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    c.execute("SELECT code FROM set_map")
    sets = c.fetchall()
    for s in sets:
        if s[0] in cardobj:
            cardobj[s[0].upper()] = cardobj.pop(s[0])
    conn.close()
    return cardobj

def get_booster_price(setname):
    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    c.execute("SELECT * FROM timestamped_base64_strings WHERE name='mtggoldfish'")
    r = c.fetchone()
    if r:
        if r[2] + 86400  < time.time(): #close enough to a day
            goldfish_html = requests.get('https://www.mtggoldfish.com/prices/online/boosters').text
            b64html = base64.b64encode(str.encode(goldfish_html))
            c.execute("UPDATE timestamped_base64_strings SET b64str=:b64str, timestamp=:timestamp WHERE name='mtggoldfish'", {"b64str": b64html, "timestamp": time.time() })
            print("mtggoldfish data stale, fetched new data")
        else:
            goldfish_html = base64.b64decode(r[1]).decode()
            print("mtggoldfish data fresh!")
    else:
        goldfish_html = requests.get('https://www.mtggoldfish.com/prices/online/boosters').text
        b64html = base64.b64encode(str.encode(goldfish_html))
        c.execute("INSERT INTO timestamped_base64_strings values ('mtggoldfish', :b64str, :timestamp)", {"b64str": b64html, "timestamp": time.time() })
        print("No mtggoldfish cache, created new record...")
    
    conn.commit()
    conn.close()  
    
    #this is hideous
    regex = r"<a class=\"priceList-set-header-link\" href=\"\/index\/\w+\"><img class=\"[\w\- ]+\" alt=\"\w+\" src=\"[\w.\-\/]+\" \/>\n<\/a><a class=\"priceList-set-header-link\" href=\"[\w\/]+\">{setname}<\/a>[\s\S]*?<div class='priceList-price-price-wrapper'>\n([\d.]+)[\s\S]*?<\/div>".format(setname=setname)

    div_match = re.search(regex, goldfish_html)
    if (div_match):
        return div_match.group(1)
    return None

def verify_nick(nick):
    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE name='" + nick + "'")
    if c.fetchone():
        conn.close()
        return False
    conn.close()
    return True

def calc_elo_change(winner, loser):
    k = 32
    r1 = math.pow(10,(winner/400))
    r2 = math.pow(10,(loser/400))

    e1 = r1/(r1 + r2)
    e2 = r2/(r1 + r2)

    rr1 = winner + k * (1.0 - e1)
    rr2 = loser + k * (0 - e2)

    return math.ceil(rr1),math.ceil(rr2)

def get_set_info(set_code):
    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    c.execute("SELECT * FROM set_map WHERE code=:scode", {"scode":set_code})
    r = c.fetchone()
    if r:
        conn.close()
        return {"name": r[0], "code": r[1], "altcode": r[2]}
    else:
        conn.close()
        return None
    
def gen_booster(card_set, seed=0):
    random.seed(seed)
    cardobj = load_mtgjson()
    if card_set in cardobj:
        mybooster = []
        if not ('booster' in cardobj[card_set]):
            booster = ["rare","uncommon","uncommon","uncommon","common","common","common","common","common","common","common","common","common","common"]
        else:
            booster = cardobj[card_set]['booster']
        for i in booster:
            if isinstance(i, str):
                mybooster += [i]
            elif isinstance(i, list):
                if set(i) == {"rare", "mythic rare"}:
                    mybooster += [random.choice(["rare"] * 875 + ["mythic rare"] * 125)]
                elif set(i) == {"foil", "power nine"}:
                    mybooster += [random.choice((["mythic rare"] + ["rare"] * 4 + ["uncommon"] * 6 + ["common"] * 9) * 98 + ["power nine"] * 2)]
                else:
                    mybooster += [random.choice(i)]
        gbooster = []
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        rarities = ["rare","mythic rare","uncommon","common","special"]
        other_shit = ["token","marketing"]
        
        for cd in mybooster:
            if cd in rarities:
                c.execute("SELECT * FROM cards WHERE rarity like :rarity AND card_set LIKE :cardset", {"rarity": cd, "cardset": card_set})
            elif cd == "land":
                c.execute("SELECT * FROM cards WHERE rarity='Basic Land' AND card_set LIKE :cardset", {"cardset": card_set})
            elif cd == "power nine":
                c.execute("SELECT * FROM cards WHERE rarity='Special' AND card_set LIKE :cardset", {"cardset": card_set})
            elif cd in other_shit:
                 c.execute("SELECT * FROM cards WHERE rarity like :rarity AND card_set LIKE :cardset", {"rarity": "common", "cardset": card_set})
            else:
                c.execute("SELECT * FROM cards WHERE card_name=:name AND card_set LIKE :cardset", {"name": cd, "cardset": card_set})
            r_all = c.fetchall()
            if r_all:
                r = random.choice(r_all)
                gbooster += [r]        
        conn.close()
        return gbooster

def give_booster(owner, card_set):
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()

        outmessage = ""
        card_set = card_set.upper() #just in case
        cardobj = load_mtgjson()
        c.execute("SELECT card_set FROM cards WHERE card_set LIKE :cardset", {"cardset": card_set})
        
        if not (card_set in cardobj):
            outmessage = "I don't know where to find that kind of booster..."
            return outmessage
        elif not c.fetchone():
            outmessage = "that set's not in my brain!!"
            return outmessage
        elif not ('booster' in cardobj[card_set]):
            outmessage = "I've heard of that set but I've never seen a booster for it, I'll see what I can do..."
        
        c.execute("SELECT discord_id FROM users WHERE name LIKE :name OR discord_id LIKE :name", {"name": owner})
        owner = c.fetchone()[0]
        random.seed()
        booster_seed = random.random()
        c.execute("INSERT INTO booster_inventory VALUES (:owner, :cset, :seed)", {"owner": owner, "cset": card_set, "seed": booster_seed})
        conn.commit()
        conn.close()
        if outmessage == "":
            outmessage = "booster added to inventory!"
        return outmessage

def adjustbux(who, how_much):
    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    c.execute("UPDATE users SET cash = cash + :how_much WHERE discord_id=:who OR name=:who", {"how_much":'%.2f'%how_much,"who":who})
    conn.commit()
    conn.close()

def open_booster(owner, set):
    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    c.execute("SELECT *, rowid FROM booster_inventory WHERE owner_id=:name AND card_set LIKE :set", {"name": owner, "set": set})
    mybooster = c.fetchone()
    if mybooster == None:
        return None
    generated_booster = gen_booster(mybooster[1], mybooster[2])
    rid = mybooster[3]
    outstring = ""
    for card in generated_booster:
        c.execute("SELECT * FROM collection WHERE owner_id=:name AND multiverse_id=:mvid AND amount_owned > 0", {"name": owner, "mvid": card[0], "cname": card[1], "cset": card[2] })
        cr = c.fetchone()
        if not cr:
            c.execute("INSERT INTO collection VALUES (:name,:mvid,1)", {"name": owner, "mvid": card[0]})
        else:
            c.execute("UPDATE collection SET amount_owned = amount_owned + 1 WHERE owner_id=:name AND multiverse_id=:mvid", {"name": owner, "mvid": card[0]})
        
        outstring += card[1] + " -- " + card[4] + "\n"
    if outstring == "":
        outstring = "It was empty... !"
    c.execute("DELETE FROM booster_inventory WHERE rowid=:rowid", {"rowid": int(rid)}) 
    conn.commit()
    conn.close()
    return outstring

def load_set_json(card_set):
    count = 0
    cardobj = load_mtgjson()

    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    if card_set in cardobj:
        for card in cardobj[card_set]['cards']:
            # if multiverseID doesn't exist, generate fallback negative multiverse ID using set and name as seed
            if 'multiverseid' in card:
                mvid = card['multiverseid']
            else:
                random.seed(card['name'] + card_set)
                mvid = -random.randrange(100000000)
                #print('IDless card {0} assigned fallback ID {1}'.format(card['name'], mvid))
            c.execute("INSERT OR IGNORE INTO cards VALUES(?, ?, ?, ?, ?)", (mvid, card['name'], card_set, card['type'], card['rarity']) )
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
    c = conn.cursor()
    c.execute("SELECT cash FROM users WHERE discord_id=:who OR name=:who", {"who": who} )
    result = c.fetchone()
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
    c = conn.cursor()
    c.execute("SELECT card_name, amount_owned FROM collection INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id WHERE owner_id=:ownerid", {"ownerid": user})
    collection = c.fetchall()
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
    c = conn.cursor()
    c.execute("SELECT SUM(amount_owned), card_name FROM collection INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id WHERE owner_id = :ownerid GROUP BY card_name ORDER BY SUM(amount_owned) DESC", {"ownerid": user})
    outstring = '\n'.join(['SB: {0} {1}'.format(card[0], card[1]) for card in c.fetchall()])
    conn.close()
    return outstring

def export_collection_to_list(user):
    who = get_user_record(user)
    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    c.execute("SELECT SUM(amount_owned), card_name FROM collection INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id WHERE owner_id = :ownerid GROUP BY card_name ORDER BY SUM(amount_owned) DESC", {"ownerid": who[0]})
    out = []
    for card in c.fetchall():
        out.append( {"amount": card[0], "name": card[1]} )
    conn.close()
    return out    

def is_registered(discord_id):
    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    c.execute("SELECT discord_id FROM users WHERE discord_id=:id", {"id": discord_id})
    r = c.fetchone()
    conn.close()
    if r:
        return True
    else:
        return False
    
def get_user_record(who, field=None):
    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    if field == None:
        field = "*"
    c.execute("SELECT {0} FROM users WHERE discord_id='{1}' OR name='{1}'".format(field, who))
    r = c.fetchone()
    conn.close()
    return r

def update_elo(who, elo):
    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    c.execute("UPDATE users SET elo_rating =:elo WHERE discord_id=:who OR name=:who",{"elo": elo, "who": who})
    conn.commit()
    conn.close()
    

def give_card(user, target, card, amount):
    # check that amount > 0:
    return_dict = dict.fromkeys(['code', 'card_name', 'amount_owned', 'target_id'])
    if amount < 1:
        return_dict['code'] = 4 # = invalid amount
        return return_dict
    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    # user is guaranteed valid by the command parser
    # check that target is valid:
    c.execute("SELECT discord_id FROM users WHERE discord_id=:target OR name=:target", {"target": target})
    r = c.fetchone()
    # if target exists and is not user:
    if r and r[0] != user:
        target_id = r[0]
    else:
        conn.close()
        return_dict['code'] = 1 # = target invalid
        return return_dict
    # check that user has card & get all instances of it:
    c.execute("SELECT collection.rowid, collection.multiverse_id, amount_owned, card_name FROM collection INNER JOIN cards ON collection.multiverse_id = cards.multiverse_id WHERE owner_id = :user AND (card_name LIKE :card OR collection.multiverse_id LIKE :card)", {"user": user,"card": card})
    origin_cards = c.fetchall()
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
        c.execute("SELECT rowid, amount_owned FROM collection WHERE owner_id = :target AND multiverse_id = :multiverse_id", {"target": target_id,"multiverse_id": multiverse_id})
        r = c.fetchone()
        if r:
            target_rowid, target_amountowned = r
            c.execute("UPDATE collection SET amount_owned = :new_amount WHERE rowid = :rowid", 
                      {"new_amount": (target_amountowned + iter_amount), "rowid": target_rowid})
        # otherwise, create new row with that amount
        else:
            c.execute("INSERT INTO collection VALUES (:target_id, :multiverse_id, :amount)",
                      {"target_id": target_id, "multiverse_id": multiverse_id, "amount": iter_amount})
        # remove amount owned from user
        c.execute("UPDATE collection SET amount_owned = :new_amount WHERE rowid = :rowid",
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




@client.event
async def on_ready():
    print('Logged in as')
    print(client.user.name)
    print(client.user.id)
    print('------')

@client.event
async def on_message(message):
    user = str(message.author.id)

    #------------------------------------------------------------------------------------------------------------#

    if message.content.startswith('!givecard'):
        if not is_registered(user):
            await client.send_message(message.channel, "<@{0}>, you ain't registered!!".format(user))
            return

        #format: !givecard clonepa Swamp 2
        target, card = message.content.split(maxsplit=2)[1:] # = target = 'clonepa', card= 'Swamp 2'
        amount_re = re.search(r'\s+(\d+)$', card)
        if amount_re:
            amount = int(amount_re[1])
            card = card[:-len(amount_re[0])]
        else:
            amount = 1

        result_dict = give_card(user, target, card, amount)

        reply_dict = {0: "gave {0} {1} to <@{2}>!".format(amount, result_dict['card_name'], result_dict['target_id']),
                      1: "that's not a valid recipient!!",
                      2: "hey, you don't have that card at all!",
                      3: "hold up, you only have {0} of {1}!!".format(result_dict['amount_owned'], result_dict['card_name']),
                      4: "now that's just silly",
                      5: "you only have {0} of that printing of {1}!".format(result_dict['amount_owned'], result_dict['card_name'])}

        await client.send_message(message.channel, "<@{0}> {1}".format(user, reply_dict[ result_dict['code'] ]))

    #------------------------------------------------------------------------------------------------------------#
    
    if message.content.startswith('!exportcollection') or message.content.startswith('!exportcollectiom'):

        if not is_registered(user):
            await client.send_message(message.channel, "<@{0}>, you ain't registered!!".format(user))
            return
        
        await client.send_typing(message.channel)
        exported_collection = export_collection_to_sideboard(user)

        r = requests.post('https://ptpb.pw/', data={"content": exported_collection})
        pb_url = next(i.split(' ')[1] for i in r.text.split('\n') if i.startswith('url:'))

        await client.send_message(message.channel, "<@{0}>, here's your exported collection: {1}\ncopy it into cockatrice to build a deck!!".format(user, pb_url))

    #------------------------------------------------------------------------------------------------------------#
 
    elif message.content.startswith('!checkdeck'):
        if not is_registered(user):
            await client.send_message(message.channel, "<@{0}>, you ain't registered!!".format(user))
            return

        deck = message.content[len(message.content.split(' ')[0]):].strip()
        missing_cards = validate_deck(deck, user)

        if missing_cards:
            needed_cards_str = '\n'.join(["{0} {1}".format(missing_cards[card], card) for card in missing_cards])
            await client.send_message(message.channel, "<@{0}>, you don't have the cards for that deck!! You need:\n```{1}```".format(user, needed_cards_str))
        else:
            hashed_deck = deckhash.make_deck_hash(*deckhash.convert_deck_to_boards(deck))
            await client.send_message(client.get_channel(mtgox_channel_id), "<@{0}> has submitted a collection-valid deck! hash: `{1}`".format(user, hashed_deck))

    #------------------------------------------------------------------------------------------------------------#
    
    elif message.content.startswith('!packprice'): #!packprice [setcode] returns mtgo booster pack price for the set via mtggoldfish
        card_set = message.content.split(' ')[1].upper()
        setname = get_set_info(card_set)['name']

        await client.send_typing(message.channel)

        price = get_booster_price(setname)
        if price:
            out = "{0} booster pack price: ${1}".format(setname, price)
        else:
            out = "no prices found for that set brah"

        await client.send_message(message.channel, out)

    #------------------------------------------------------------------------------------------------------------#
    
    elif message.content.startswith('!checkbux') or message.content.startswith('!checkvux'):
        await client.send_message(message.channel, "<@{0}> your maplebux balance is: ${1}".format(user, '%.2f'%check_bux(user)))

    #------------------------------------------------------------------------------------------------------------#

    elif message.content.startswith('!givebux') or message.content.startswith('!givevux'):
            p1 = message.content.split(' ')[1]
            p2 = float('%.2f'%float(message.content.split(' ')[2]))
            myself = user
            mycash = check_bux(myself)
            otherperson = ""
            conn = sqlite3.connect('maple.db')
            c = conn.cursor()
            c.execute("SELECT name FROM users WHERE discord_id=:who OR name=:who", {"who":p1} )
            result = c.fetchone()
            if result:
                otherperson = result[0]
            else:
                await client.send_message(message.channel, "I'm not sure who you're trying to give money to...")
                return

            c.execute("SELECT name FROM users WHERE discord_id=:who OR name=:who", {"who":myself} )
            result = c.fetchone()
            if result:
                if result[0] == otherperson:
                    await client.send_message(message.channel, "sending money to yourself... that's shady...")
                    return
               
            if p2 < 0:
                await client.send_message(message.channel, "wait a minute that's a robbery!")
                return
            if mycash == 0 or mycash - p2 < 0:
                await client.send_message(message.channel, "not enough bux to ride this trux :surfer:")
                return
            adjustbux(myself, p2 * -1)
            adjustbux(otherperson, p2)
            await client.send_message(message.channel, "sent ${0} to {1}".format(p2, p1))
            conn.close()

    #------------------------------------------------------------------------------------------------------------#
    
    elif message.content.startswith('!openbooster') or message.content.startswith('!opemvooster'):
        if not is_registered(user):
            await client.send_message(message.channel, "<@{0}>, you ain't registered!!".format(user))
            return

        card_set = message.content.split(' ')[1].upper()
        opener = user
        outstring = open_booster(opener, card_set)
        if outstring:
            await client.send_message(message.channel, "```" + outstring + "```" )
        else:
            await client.send_message(message.channel, "don't have any of those homie!!" )

    #------------------------------------------------------------------------------------------------------------#
    
    elif message.content.startswith("!maplecard"):
        cname = message.content[len(message.content.split(' ')[0]):]
        cname = cname.replace(" ","%20")
        await client.send_message(message.channel, "https://api.scryfall.com/cards/named?fuzzy=!" + cname + "!&format=image")

    #------------------------------------------------------------------------------------------------------------#
        
    elif message.content.startswith('!buybooster') or message.content.startswith('!vuyvooster'):
        if user in in_transaction:
            await client.send_message(message.channel, "<@{0}> you're currently in a transaction! ...guess I'll cancel it for you".format(user))
            in_transaction.remove(user)
        card_set = message.content.split(' ')[1].upper()
        cardobj = load_mtgjson()
        if not (card_set in cardobj):
            await client.send_message(message.channel, "<@{0}> I don't know what set that is...".format(user))
            return
        setname = get_set_info(card_set)['name']
        price = get_booster_price(setname)
        if not price:
            price = 15.00

        in_transaction.append(user)    
        await client.send_message(message.channel, "<@{2}> Buy {0} booster for ${1}?".format(setname, '%.2f'%float(price), user))

        msg = await client.wait_for_message(timeout=15.0, author=message.author)
        if not msg:
            return
        if (msg.content.startswith('y') or msg.content.startswith('Y')):
            adjustbux(user, float(price) * -1)
            result = give_booster(user, card_set)
        elif (msg.content.startswith('n') or msg.content.startswith('N')):
            result = "well ok"

        if result:
            await client.send_message(message.channel, "<@{0}> {1}".format(user, result) )
        in_transaction.remove(user)

    #------------------------------------------------------------------------------------------------------------#
                                          
    elif message.content.startswith('!recordmatch'):
        p1 = message.content.split(' ')[1]
        p2 = message.content.split(' ')[2]
        p1elo = get_user_record(p1,"elo_rating")[0]
        p2elo = get_user_record(p2,"elo_rating")[0]

        newelo = calc_elo_change(p1elo, p2elo)
        bux_adjustment = 3.00 * (newelo[0] - p1elo)/32
        bux_adjustment = float('%.2f'%bux_adjustment)
        
        update_elo(p1, newelo[0])
        update_elo(p2, newelo[1])

        adjustbux(p1, bux_adjustment)
        await client.send_message(message.channel,"" + p1 + " new elo: " + str(newelo[0]) + "\n" + p2 + " new elo: " + str(newelo[1]) + "\npayout: $" + str(bux_adjustment))           

    #------------------------------------------------------------------------------------------------------------#
        
    elif message.content.startswith('!hash'):
        thing_to_hash = message.content[len(message.content.split(' ')[0]):]
        hashed_thing = deckhash.make_deck_hash(*deckhash.convert_deck_to_boards(thing_to_hash))
        await client.send_message(message.channel, 'hashed deck: ' + hashed_thing)

    #------------------------------------------------------------------------------------------------------------#
        
    elif message.content.startswith('!register'):
        nickname = message.content.split(' ')[1]
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE discord_id=' + user)
        if (len(c.fetchall()) > 0):
            await client.send_message(message.channel, 'user with discord ID ' + user + ' already exists. don\'t try to pull a fast one on old maple!!')
        elif (not verify_nick(nickname)):
            await client.send_message(message.channel, 'user with nickname ' + nickname + ' already exists. don\'t try to confuse old maple you hear!!')
        else:
            c.execute("INSERT INTO users VALUES ('" + user + "','" + nickname + "',1500,50.00)")
            conn.commit()
            await client.send_message(message.channel, 'created user in database with ID ' + user + ' and nickname ' + nickname)
            c.execute("SELECT * FROM users WHERE discord_id='" + user + "'")
            f = c.fetchone()
            outstring = "Nickname: " + f[1] + "\nDiscord ID: " + f[0] + "\nElo Rating: " + str(f[2]) + "\nMaplebux: " + str(f[3])
            await client.send_message(message.channel, outstring)
        conn.close()

    #------------------------------------------------------------------------------------------------------------#
    
    elif message.content.startswith('!changenick') or message.content.startswith('!chamgemick'):
        if not is_registered(user):
            await client.send_message(message.channel, "<@{0}>, you ain't registered!!".format(user))
            return

        nickname = message.content.split(' ')[1]
        if (not verify_nick(nickname)):
            await client.send_message(message.channel, 'user with nickname ' + nickname + ' already exists. don\'t try to confuse old maple you hear!!')
        else:
            conn = sqlite3.connect('maple.db')
            c = conn.cursor()
            c.execute("UPDATE users SET name='" + nickname + "' WHERE discord_id='" + user + "'")
            conn.commit()
            await client.send_message(message.channel, message.author.mention + " updated nickname")
            conn.close()

    #------------------------------------------------------------------------------------------------------------#
            
    elif message.content.startswith('!userinfo') or message.content.startswith('!userimfo'):
        if not is_registered(user):
            await client.send_message(message.channel, "<@{0}>, you aren't registered!! :surfer:".format(user))
            return

        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE discord_id='" + user + "'")
        f = c.fetchone()
        outstring = "Nickname: " + f[1] + "\nDiscord ID: " + f[0] + "\nElo Rating: " + str(f[2]) + "\nMaplebux: " + str(f[3])
        await client.send_message(message.channel, outstring)
        conn.close()
        
    ##############################################################################################################    
    ################------------------------#### DEBUG/SETUP COMMANDS ####------------------------################
    ##############################################################################################################
        
    #------------------------------------------------------------------------------------------------------------#
        
    elif message.content.startswith('!query'):
        query = message.content[len(message.content.split(' ')[0]):]
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        if ('DROP' in query.upper() and user != '234042140248899587'):
            await client.send_message(message.channel,"pwease no droppy u_u")
            return
        outstring = ""
        try:
            c.execute(query)
            for i in c.fetchall():
                if len(outstring) > 1500:
                    await client.send_message(message.channel,"```" + outstring + "\n```")
                    outstring = ""
                outstring += str(i) + "\n"
        except sqlite3.OperationalError:
            outstring = "sqlite operational error homie...\n" + str(sys.exc_info()[1])
            
        if outstring == "":
            outstring = "No output so it probably worked"
        await client.send_message(message.channel,"```" + outstring + "```")
        conn.commit()
        conn.close()
        
    #------------------------------------------------------------------------------------------------------------#
        
    elif message.content.startswith('!elotest'):
        w = int(message.content.split(' ')[1])
        l = int(message.content.split(' ')[2])
        new_r = calc_elo_change(w,l)
        await client.send_message(message.channel, "```old winner rating: " + str(w) + "\nold loser rating: " + str(l) + "\n\nnew winner rating: " + str(new_r[0])  + "\nnew loser rating: " + str(new_r[1]) + "```")
        
    #------------------------------------------------------------------------------------------------------------#
        
    elif message.content.startswith('!gutdump'):
        table = ""
        if len(message.content.split(' ')) < 2:
            table = "users"
        else:
            table = message.content.split(' ')[1]
            
        if table == "maple":
            with open(__file__) as f:
                out = f.read(1024)
                while (out):
                    await client.send_message(message.channel,"```"  + out.replace("```","[codeblock]") + "```")
                    out = f.read(1024)
                    await asyncio.sleep(0.25)
            return
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        c.execute("SELECT * FROM " + table)
        outstring = ""
        names = [description[0] for description in c.description]
        for i in c.fetchall():
            if len(outstring) > 1500:
                await client.send_message(message.channel,"```" + str(names) + "\n\n" + outstring + "\n```")
                outstring = ""
            outstring += str(i) + "\n"
        if len(outstring) > 0:
            await client.send_message(message.channel,"```" + str(names) + "\n\n" + outstring + "\n```")
        conn.close()
        
    #------------------------------------------------------------------------------------------------------------#
        
    elif message.content.startswith('!setupdb') or message.content.startswith('!setupdv'):
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (discord_id TEXT, name TEXT, elo_rating INTEGER, cash REAL)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS match_history
                     (winner TEXT, loser TEXT, winner_deckhash TEXT, loser_deckhash TEXT, FOREIGN KEY(winner) REFERENCES users(discord_id), FOREIGN KEY(loser) REFERENCES users(discord_id))''')

        c.execute('''CREATE TABLE IF NOT EXISTS cards
                     (multiverse_id INTEGER PRIMARY KEY, card_name TEXT, card_set TEXT, card_type TEXT, rarity TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS collection
                     (owner_id TEXT, multiverse_id INTEGER, amount_owned INTEGER,
                     FOREIGN KEY(owner_id) REFERENCES users(discord_id), FOREIGN KEY(multiverse_id) REFERENCES cards(multiverse_id),
                     PRIMARY KEY (owner_id, multiverse_id))''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS booster_inventory
                     (owner_id TEXT, card_set TEXT, seed REAL, FOREIGN KEY(owner_id) REFERENCES users(discord_id), FOREIGN KEY(card_set) REFERENCES set_map(code))''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS set_map
                     (name TEXT, code TEXT, alt_code TEXT, PRIMARY KEY (code, alt_code))''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS timestamped_base64_strings
                     (name TEXT PRIMARY KEY, b64str TEXT, timestamp REAL)''')
        
        c.execute('''CREATE TRIGGER IF NOT EXISTS delete_from_collection_on_zero 
                    AFTER UPDATE OF amount_owned ON collection BEGIN 
                    DELETE FROM collection WHERE amount_owned < 1; 
                    END''')
        conn.commit()
        conn.close()
        
    #------------------------------------------------------------------------------------------------------------#
        
    elif message.content.startswith('!populatesetinfo') or message.content.startswith('!populatesetimfo'):
        #do not use load_mtgjson() here
        with open ('AllSets.json', encoding="utf8") as f:
            cardobj = json.load(f)
        conn = sqlite3.connect('maple.db')
        c = conn.cursor() 
        for cs in cardobj:
            print(cardobj[cs]["name"])
            name = ""
            code = ""
            alt_code = ""
            if "name" in cardobj[cs]:
                name = cardobj[cs]["name"]
            if "code" in cardobj[cs]:
                code = cardobj[cs]["code"]
            if "magicCardsInfoCode" in cardobj[cs]:
                alt_code = cardobj[cs]["magicCardsInfoCode"]
            if code != "" and name != "":
                c.execute("INSERT OR IGNORE INTO set_map VALUES (?, ?, ?)", (name, code, alt_code))
        conn.commit()
        conn.close()
        
    #------------------------------------------------------------------------------------------------------------#
        
    elif message.content.startswith('!populatecardinfo') or message.content.startswith('!populatecardimfo'):
        #bot will time out while waiting for this to finish, so you know be careful out there
        outstring = ""
        cardobj = load_mtgjson()
        setcount = 0
        count = 0
        for cs in cardobj:
            if not ("code" in cardobj[cs]):
                continue
            count += load_set_json(cardobj[cs]['code'].upper())
            setcount += 1
            print(count, setcount)
        print('added {0} cards from {1} sets'.format(count, setcount))
        
    #------------------------------------------------------------------------------------------------------------#
        
    elif message.content.startswith('!debugbooster') or message.content.startswith('!devugvooster'):
        card_set = message.content.split(' ')[1].upper()
        seed = float(message.content.split(' ')[2])
        await client.send_message(message.channel, "```" + str(gen_booster(card_set,seed)) + "```" )
        
        
    #------------------------------------------------------------------------------------------------------------#
        
    elif message.content.startswith('!mapletest'):
        await client.send_message(message.channel, 'i\'m {0} and my guts are made of python 3.6, brah'.format(client.user.name))
        
    #------------------------------------------------------------------------------------------------------------#
        
    elif message.content.startswith('!adjustbux') or message.content.startswith('!adjustvux'):
        p1 = message.content.split(' ')[1]
        p2 = float(message.content.split(' ')[2])
        adjustbux(p1, p2)
        await client.send_message(message.channel, "updated bux")
        
    #------------------------------------------------------------------------------------------------------------#
        
    elif message.content.startswith('!givebooster') or message.content.startswith('!givevooster'):
        if not is_registered(user):
            await client.send_message(message.channel, "<@{0}>, you ain't registered!!".format(user))
            return
        
        card_set = message.content.split(' ')[1].upper()
        if len(message.content.split(' ')) > 2 :
            person_getting_booster = message.content.split(' ')[2]
        if len(message.content.split(' ')) > 3 :
            amount = int(message.content.split(' ')[3])
        else:
            amount = 1
            person_getting_booster = user
            
        for i in range(amount):
            result = give_booster(person_getting_booster, card_set)
        await client.send_message(message.channel, result )
        
    #------------------------------------------------------------------------------------------------------------#
    
    elif message.content.startswith('!loadsetjson') or message.content.startswith('!loadsetjsom'):
        card_set = message.content.split(' ')[1].upper()

        result = load_set_json(card_set)
        if result > -1:
            await client.send_message(message.channel, 'added {0} cards from set {1}'.format(result, card_set))
        else:
            await client.send_message(message.channel, 'set code {0} not found'.format(card_set))

    #------------------------------------------------------------------------------------------------------------#
if __name__ == "__main__":            
    client.run(token)
