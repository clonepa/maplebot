import sqlite3

DB_NAME = 'maple.db'


def operation(func):
    '''Decorator for functions that access the maple database'''
    def wrapped(*args, conn=None, **kwargs):
        if not conn:
            conn = sqlite3.connect(DB_NAME)
            self_conn = True
        else:
            self_conn = False
        cursor = conn.cursor()
        return_value = func(*args, **kwargs, conn=conn, cursor=cursor)
        if self_conn:
            conn.close()
        return return_value
    return wrapped


def operation_async(func):
    '''Decorator for functions that access the maple database'''
    async def wrapped(self, context, *args, conn=None, **kwargs):
        if not conn:
            conn = sqlite3.connect(DB_NAME)
            self_conn = True
        else:
            self_conn = False
        cursor = conn.cursor()
        newargs = [context.command.transform(context, arg) for arg in args]
        return_value = await func(self, context, *newargs, conn=conn, cursor=cursor, **kwargs)
        if self_conn:
            conn.close()
        return return_value
    wrapped.__name__ = func.__name__
    return wrapped


@operation
def setup(conn=None, cursor=None):
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
