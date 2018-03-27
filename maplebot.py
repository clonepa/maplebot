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

client = discord.Client()
token = mapletoken.get_token()

def get_booster_price(setcode, altsetcode=None):
    goldfish_html = requests.get('https://www.mtggoldfish.com/prices/online/boosters').text
    
    regex = r"<div class='priceList-set'>\n<h3 class='priceList-set-header'>\n<a class=\"priceList-set-header-link\" href=\"\/index\/{setcode}\">[\s\S]*?href=\"/index/{setcode}\">(.*)</a>[\s\S]*?<div class='priceList-price-price-wrapper'>\n([\d.]+)[\s\S]*?<\/div>".format(setcode=setcode.upper())

    print(setcode)
    div_match = re.search(regex, goldfish_html)
    if (div_match):
        set_name = div_match.group(1)
        price = div_match.group(2)
        return set_name + " booster pack price: $" + price
    elif altsetcode != None:
        return get_booster_price(altsetcode)
    else:
        return "no prices found for that set brah"

def verify_nick(nick):
    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE name='" + nick + "'")
    if c.fetchone():
        return False
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
        return {"name": r[0], "code": r[1], "altcode": r[2]}
    else:
        return None
    
def gen_booster(card_set, seed=0):
    random.seed(seed)
    with open ('AllSets.json', encoding="utf8") as f:
        cardobj = json.load(f)
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
                mybooster += [random.choice(i)]
        gbooster = []
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        rarities = ["rare","mythic rare","uncommon","common"]
        other_shit = ["token","marketing"]
        
        for cd in mybooster:
            if cd in rarities:
                c.execute("SELECT * FROM cards WHERE rarity like :rarity AND card_set=:cardset", {"rarity": cd, "cardset": card_set})
            elif cd == "land":
                c.execute("SELECT * FROM cards WHERE rarity='Basic Land' AND card_set=:cardset", {"cardset": card_set})
            elif cd == "power nine":
                c.execute("SELECT * FROM cards WHERE rarity='Special' AND card_set=:cardset", {"cardset": card_set})
            elif cd in other_shit:
                 c.execute("SELECT * FROM cards WHERE rarity like :rarity AND card_set=:cardset", {"rarity": "common", "cardset": card_set})
            else:
                c.execute("SELECT * FROM cards WHERE card_name=:name AND card_set=:cardset", {"name": cd, "cardset": card_set})
            r_all = c.fetchall()
            if r_all:
                r = random.choice(r_all)
                gbooster += [r]        
        conn.close()
        return gbooster
    
def give_booster(owner, card_set):
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        c.execute("SELECT discord_id FROM users WHERE name LIKE :name OR discord_id LIKE :name", {"name": owner})
        did = c.fetchone()
        random.seed()
        booster_seed = random.random()
        c.execute("INSERT INTO booster_inventory VALUES (:did, :cset, :seed)", {"did": did[0], "cset": card_set, "seed": booster_seed})
        conn.commit()
        conn.close()   

@client.event
async def on_ready():
    print('Logged in as')
    print(client.user.name)
    print(client.user.id)
    print('------')

@client.event
async def on_message(message):
    if message.content.startswith('!debugbooster'):
        card_set = message.content.split(' ')[1].upper()
        seed = float(message.content.split(' ')[2])
        await client.send_message(message.channel, "```" + str(gen_booster(card_set,seed)) + "```" )

    if message.content.startswith('!packprice'):
        card_set = message.content.split(' ')[1].upper()
        set_info = get_set_info(card_set)
        if set_info:
            out = get_booster_price(set_info['altcode'], card_set)
        else:
            out = get_booster_price(card_set)

        await client.send_message(message.channel, out)
    if message.content.startswith('!openbooster'):
        card_set = message.content.split(' ')[1].upper()
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        c.execute("SELECT * FROM booster_inventory WHERE owner_id=:name AND card_set LIKE :cset", {"name": str(message.author.id), "cset": card_set})
        mybooster = c.fetchone()
        if mybooster == None:
            await client.send_message(message.channel, "don't have any of those homie!!" )
            return
        generated_booster = gen_booster(mybooster[1], mybooster[2])
        outstring = ""
        for card in generated_booster:
            c.execute("SELECT * FROM collection WHERE owner_id=:name AND multiverse_id=:mvid AND card_name LIKE :cname AND card_set LIKE :cset AND amount_owned > 0", {"name": str(message.author.id), "mvid": card[0], "cname": card[1], "cset": card[2] })
            cr = c.fetchone()
            if not cr:
                c.execute("INSERT INTO collection VALUES (:name,:mvid,:cname,:cset,1)", {"name": str(message.author.id), "mvid": card[0], "cname": card[1], "cset": card[2] })
            else:
                c.execute("UPDATE collection SET amount_owned = amount_owned + 1 WHERE owner_id=:name AND multiverse_id=:mvid AND card_name LIKE :cname AND card_set LIKE :cset", {"name": str(message.author.id), "mvid": card[0], "cname": card[1], "cset": card[2] })
            
            outstring += card[1] + " -- " + card[4] + "\n"
        await client.send_message(message.channel, "```" + outstring + "```" )
        c.execute("DELETE FROM booster_inventory WHERE owner_id=:name AND card_set=:cset AND seed=:seed", {"name": mybooster[0], "cset": mybooster[1], "seed":mybooster[2]}) 
        conn.commit()
        conn.close()

    if message.content.startswith("!maplecard"):
        cname = message.content[len("!maplecard "):]
        cname = cname.replace(" ","%20")
        await client.send_message(message.channel, "https://api.scryfall.com/cards/named?fuzzy=!" + cname + "!&format=image")
    
    if message.content.startswith('!givebooster'):
        card_set = message.content.split(' ')[1].upper()
        if len(message.content.split(' ')) > 2 :
            person_getting_booster = message.content.split(' ')[2]
        if len(message.content.split(' ')) > 3 :
            amount = int(message.content.split(' ')[3])
        else:
            amount = 1
            person_getting_booster = str(message.author.id)
            
        for i in range(amount):
            give_booster(person_getting_booster, card_set)
        await client.send_message(message.channel, "booster added to inventory!" )
        
    if message.content.startswith('!loadsetjson'):
        card_set = message.content.split(' ')[1].upper()
        count = 0
        with open ('AllSets.json', encoding="utf8") as f:
            cardobj = json.load(f)
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        if card_set in cardobj:
            for card in cardobj[card_set]['cards']:               
                c.execute("INSERT OR IGNORE INTO cards VALUES(?, ?, ?, ?, ?)", (card['multiverseid'], card['name'], card_set, card['type'], card['rarity']) )
                count += 1
            conn.commit()
            await client.send_message(message.channel, 'added ' + str(count) + ' cards from set ' + card_set)
        else:
            await client.send_message(message.channel, 'set code ' + card_set + ' not found')
        conn.close()

    if message.content.startswith('!mapletest'):
        await client.send_message(message.channel, 'I am maple-bot and my guts are made of python 3.6')

    if message.content.startswith('!adjustbux'):
        p1 = message.content.split(' ')[1]
        p2 = message.content.split(' ')[2]
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        c.execute("UPDATE users SET cash = cash + " + p2 + " WHERE discord_id='" + p1 + "' OR name='" + p1 + "'")
        conn.commit()
        await client.send_message(message.channel, "updated bux")
        conn.close()

    if message.content.startswith('!populatesetinfo'):
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
    if message.content.startswith('!recordmatch'):
        p1 = message.content.split(' ')[1]
        p2 = message.content.split(' ')[2]
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        c.execute("SELECT elo_rating FROM users WHERE discord_id='" + p1 + "' OR name='" + p1 + "'")
        p1elo = c.fetchone()[0]

        c.execute("SELECT elo_rating FROM users WHERE discord_id='" + p2 + "' OR name='" + p2 + "'")
        p2elo = c.fetchone()[0]

        newelo = calc_elo_change(p1elo, p2elo)
        c.execute("UPDATE users SET elo_rating =" + str(newelo[0]) + " WHERE discord_id='" + p1 + "' OR name='" + p1 + "'")
        c.execute("UPDATE users SET elo_rating =" + str(newelo[1]) + " WHERE discord_id='" + p2 + "' OR name='" + p2 + "'")
        conn.commit()
        await client.send_message(message.channel,"" + p1 + " new elo: " + str(newelo[0]) + "\n" + p2 + " new elo: " + str(newelo[1]))
        
        conn.close()
        
    if message.content.startswith('!setupdb'):
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (discord_id text, name text, elo_rating integer, cash real)''')
        conn.commit()
        c.execute('''CREATE TABLE IF NOT EXISTS match_history
                     (p1 text, p2 text, p1_old_rating integer, p2_old_rating, p1_new_rating integer, p2_new_rating integer, p1_deckhash text, p2_deckash text)''')
        conn.commit()
        c.execute('''CREATE TABLE IF NOT EXISTS collection
                     (owner_id text, multiverse_id integer, card_name text, card_set text, amount_owned integer)''')    
        conn.commit()
        c.execute('''CREATE TABLE IF NOT EXISTS cards
                     (multiverse_id integer, card_name text, card_set text, card_type text, rarity text, primary key (multiverse_id, card_name, card_set))''')    
        conn.commit()
        c.execute('''CREATE TABLE IF NOT EXISTS booster_inventory
                     (owner_id text, card_set text, seed real)''')
        conn.commit()
        #TODO: populate this table
        c.execute('''CREATE TABLE IF NOT EXISTS set_map
                     (name text, code text, alt_code text, primary key (code, alt_code))''')
        conn.commit()
        conn.close()

    
    if message.content.startswith('!gutdump'):
        table = message.content.split(' ')[1]
        if table == None:
            table = "users"
        elif table == "maple":
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
        
    if message.content.startswith('!hash'):
        thing_to_hash = message.content[len("!hash "):]
        hashed_thing = deckhash.make_deck_hash(*deckhash.convert_deck_to_boards(thing_to_hash))
        await client.send_message(message.channel, 'hashed deck: ' + hashed_thing)
        
    if message.content.startswith('!register'):
        nickname = message.content.split(' ')[1]
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE discord_id=' + message.author.id)
        if (len(c.fetchall()) > 0):
            await client.send_message(message.channel, 'user with discord ID ' + message.author.id + ' already exists. don\'t try to pull a fast one on old maple!!')
        elif (not verify_nick(nickname)):
            await client.send_message(message.channel, 'user with nickname ' + nickname + ' already exists. don\'t try to confuse old maple you hear!!')
        else:
            c.execute("INSERT INTO users VALUES ('" + message.author.id + "','" + nickname + "',1500,50.00)")
            conn.commit()
            await client.send_message(message.channel, 'created user in database with ID ' + message.author.id + ' and nickname ' + nickname)
            c.execute("SELECT * FROM users WHERE discord_id='" + message.author.id + "'")
            f = c.fetchone()
            outstring = "Nickname: " + f[1] + "\nDiscord ID: " + f[0] + "\nElo Rating: " + str(f[2]) + "\nMaplebux: " + str(f[3])
            await client.send_message(message.channel, outstring)
        conn.close()
    
    if message.content.startswith('!changenick'):
        nickname = message.content.split(' ')[1]
        if (not verify_nick(nickname)):
            await client.send_message(message.channel, 'user with nickname ' + nickname + ' already exists. don\'t try to confuse old maple you hear!!')
        else:
            conn = sqlite3.connect('maple.db')
            c = conn.cursor()
            c.execute("UPDATE users SET name='" + nickname + "' WHERE discord_id='" + message.author.id + "'")
            conn.commit()
            await client.send_message(message.channel, message.author.mention + " updated nickname")
            conn.close()
            
    if message.content.startswith('!userinfo'):
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE discord_id='" + message.author.id + "'")
        f = c.fetchone()
        outstring = "Nickname: " + f[1] + "\nDiscord ID: " + f[0] + "\nElo Rating: " + str(f[2]) + "\nMaplebux: " + str(f[3])
        await client.send_message(message.channel, outstring)
        conn.close()
        
    if message.content.startswith('!query'):
        query = message.content[len("!query "):]
        conn = sqlite3.connect('maple.db')
        c = conn.cursor()
        if ('DROP' in query.upper() and str(message.author.id) != '234042140248899587'):
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
        
    if message.content.startswith('!elotest'):
        w = int(message.content.split(' ')[1])
        l = int(message.content.split(' ')[2])
        new_r = calc_elo_change(w,l)
        await client.send_message(message.channel, "```old winner rating: " + str(w) + "\nold loser rating: " + str(l) + "\n\nnew winner rating: " + str(new_r[0])  + "\nnew loser rating: " + str(new_r[1]) + "```")
        
client.run(token)
