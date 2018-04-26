import json
import os
import logging
import random

from .. import db

logger = logging.getLogger('maple.mtg.util')


@db.operation
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


@db.operation
def get_set_info(set_code, conn=None, cursor=None):
    '''returns setmap values for a given setcode'''
    cursor.execute("SELECT * FROM set_map WHERE code like :scode", {"scode": set_code})
    result = cursor.fetchone()

    if result:
        return {"name": result[0], "code": result[1], "altcode": result[2]}
    return None


@db.operation
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
        return count
    else:
        logger.info(card_set + " not in cardobj!")
        return 0
