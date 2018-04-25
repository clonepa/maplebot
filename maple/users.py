import collections
from . import db


@db.operation
def is_registered(discord_id, conn=None, cursor=None):
    cursor.execute("SELECT discord_id FROM users WHERE discord_id=:id", {"id": discord_id})
    r = cursor.fetchone()
    if r:
        return True
    else:
        return False


@db.operation
def get_record(target, field=None, conn=None, cursor=None):
    cursor.execute("SELECT * FROM users WHERE discord_id=:target OR name=:target COLLATE NOCASE",
                   {"target": target})
    columns = [description[0] for description in cursor.description]
    r = cursor.fetchone()
    if not r:
        raise KeyError

    out_dict = collections.OrderedDict.fromkeys(columns)
    for i, key in enumerate(out_dict):
        out_dict[key] = r[i]

    return out_dict[field] if field else out_dict


@db.operation
def set_record(target, field, value, conn=None, cursor=None):
    target_record = get_record(target)
    if field not in target_record:
        raise KeyError
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


@db.operation
def verify_nick(nick, conn=None, cursor=None):
    '''returns True if nick doesn't exist in db, False if it does'''
    cursor.execute("SELECT * FROM users WHERE name = :name COLLATE NOCASE",
                   {"name": nick})
    result = cursor.fetchone()
    return False if result else True


def adjust_cash(target, delta: float):
    target_record = get_record(target)
    new_bux = target_record['cash'] + delta
    print(new_bux)
    response = set_record(target_record['discord_id'], 'cash', new_bux)
    return True if response == new_bux else False
