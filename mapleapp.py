from flask import Flask
from flask import render_template
from maple import brains
app = Flask(__name__)


@app.route('/')
@app.route('/collection/<user>')
def index(user=None):
    user_record = None
    user_collection = None
    if user:
        user_record = brains.get_record(user)
        user_collection = brains.export_to_list(user)
    return render_template('index.html', user=user_record, collection=user_collection)


@app.route('/booster/<cset>/<seed>')
def booster_page(cset=None, seed=None):
    if cset and seed:
        cards = brains.gen_booster(cset, [{"rowid": 0, "seed": int(seed)}])[0]['booster']
        print(cards)
    return render_template('booster.html', cards=cards)


@app.route('/deckbuilder/<user>')
def deckbuilder(user=None):
    user_record = None
    user_collection = None
    if user:
        user_record = brains.get_record(user)
        user_collection = brains.export_to_list(user)
    return render_template('deck.html', user=user_record, collection=user_collection)


if __name__ == "__main__":
    app.run(port=7172)
