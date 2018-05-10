import sqlite3

USERS_DB = 'maple.db'
USERS_TABLE = 'users'


class MapleInvalidUser(Exception):
    pass


class MapleUserExists(Exception):
    pass


class MapleUser:
    def __init__(self, id):
        conn = sqlite3.connect(USERS_DB)
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT discord_id FROM {} WHERE discord_id = ?'.format(USERS_TABLE),
                           (id,))
        except sqlite3.OperationalError:
            conn.close()
            raise Exception('error accessing users table')
        exists = cursor.fetchone()
        if not exists:
            conn.close()
            raise MapleInvalidUser('user with discord_id {} does not exist'.format(id))
        self.conn = conn
        self.id = exists[0]

    def __enter__(self):
        return self

    def __exit__(self):
        self.conn.close()

    def _field_get(self, field):
        cursor = self.conn.cursor()
        cursor.execute('SELECT {} FROM {} WHERE discord_id = ?'.format(field, USERS_TABLE),
                       (self.id,))
        return cursor.fetchone()[0]

    def _field_set(self, field, value):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE {} SET {} = ? WHERE discord_id = ?'.format(USERS_TABLE, field),
                       (value, self.id))
        self.conn.commit()

    @property
    def name(self):
        return self._field_get('name')

    @name.setter
    def name(self, value):
        try:
            self._field_set('name', 'value')

    @property
    def cash(self):
        return round(self._field_get('cash'), 2)

    @cash.setter
    def cash(self, value):
        value = max(value, 0)
        self._field_set('cash', value)

    @property
    def elo(self):
        return self._field_get('elo_rating')

    @elo.setter
    def elo(self, value):
        self._field_set('elo_rating', value)
