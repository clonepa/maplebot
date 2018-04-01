from flask import Flask
from flask import render_template
import sqlite3
app = Flask(__name__)


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

def get_user_record(who, field=None):
    conn = sqlite3.connect('maple.db')
    c = conn.cursor()
    if field == None:
        field = "*"
    c.execute("SELECT {0} FROM users WHERE discord_id='{1}' OR name='{1}'".format(field, who))
    r = c.fetchone()
    conn.close()
    return r


@app.route('/')
@app.route('/<user>')
def index(user=None):
    if user:
        user_record=get_user_record(user)
        collection = export_collection_to_list(user)
    return render_template('index.html',user=user_record,collection=collection)
