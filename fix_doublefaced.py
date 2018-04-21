import sqlite3
import maplebot

set_dict = maplebot.load_mtgjson()

fix_dict = {}

for cardset in set_dict:
    print('doing', cardset)
    card_list = set_dict[cardset]['cards']
    for card in card_list:
        number_to_use = 'mciNumber' if 'mciNumber' in card else 'number'
        if number_to_use in card:
            if card[number_to_use].endswith('b') and card['layout'] == 'double-faced':
                try:
                    print('found back of double-faced with name', card['name'])
                    real_card = next((x for x in card_list if x[number_to_use] == card[number_to_use].replace('b', 'a')), None)
                    if real_card:
                        print('real card is', real_card['name'])
                        print(card['multiverseid'])
                        print(real_card['multiverseid'])
                        fix_dict[card['multiverseid']] = real_card['multiverseid']
                    else:
                        print('what the fuck')
                        raise Exception
                except KeyError:
                    print('stupid card with no id')
print(fix_dict)


org_dict = fix_dict
fix_dict = {int(k): org_dict[k] for k in org_dict}


conn = sqlite3.connect('maple.db')
cursor = conn.cursor()

for mv_id in fix_dict:
    fix_id = fix_dict[mv_id]
    print(mv_id, '=>', fix_id)
    cursor.execute("SELECT card_name FROM cards WHERE multiverse_id = :fix",
                   {'fix': fix_id})
    fix_name = cursor.fetchone()[0]
    print(mv_id, '=>', fix_name)
    cursor.execute("UPDATE collection SET multiverse_id = :fix WHERE multiverse_id = :orig",
                   {'fix': fix_id, 'orig': mv_id})
    if cursor.rowcount > 0:
        print("Done", cursor.rowcount)

conn.commit()
conn.close()
