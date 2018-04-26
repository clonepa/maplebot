from flask import Flask
from flask import render_template
import maplebot
import maple
app = Flask(__name__)


@app.route('/')
@app.route('/collection/<user>')
def index(user=None):
    user_record = None
    collection = None
    if user:
        user_record = maple.get_record(user)
        collection = maplebot.export_collection_to_list(user)
    return render_template('index.html', user=user_record, collection=collection)


@app.route('/booster/<cset>/<seed>')
def booster(cset=None, seed=None):
    if cset and seed:
        cards = maplebot.gen_booster(cset, [{"rowid": 0, "seed": int(seed)}])[0]['booster']
        print(cards)
    return render_template('booster.html', cards=cards)


@app.route('/deckbuilder/<user>')
def deckbuilder(user=None):
    user_record = None
    collection = None
    if user:
        user_record = maple.get_record(user)
        collection = maplebot.export_collection_to_list(user)
    return render_template('deck.html', user=user_record, collection=collection)


if __name__ == "__main__":
    app.run(port=7172)
