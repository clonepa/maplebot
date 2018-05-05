import sqlite3
from functools import wraps

DB_NAME = 'maple.db'


def db_operation(func):
    '''Decorator for functions that access the maple database'''
    @wraps(func)
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
