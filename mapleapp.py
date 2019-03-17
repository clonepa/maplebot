from flask import Flask
from flask import render_template
from functools import wraps
from maple import brains
import mapleconfig
app = Flask(__name__)

def check_auth(username, password):
    #not doing anything with the username yet... or ever?
    return (password in mapleconfig.get_api_keys())

def authenticate():
    return Response(
    'come back wiht the right api key idiot', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

@app.route('/api/users/<userid>', methods=['GET'])
@requires_auth
def rest_api_test:
    return jsonify(brains.get_record(userid))
    

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


@app.route('/boosters/<cset>/<seeds>')
def multibooster_page(cset=None, seeds=None):
    seeds = seeds.split(';')
    boosters = []
    if cset:
        for seed in seeds:
            cards = brains.gen_booster(cset, [{"rowid": 0, "seed": int(seed)}])[0]['booster']
            booster = [{'mvid': card[0], 'name': card[1], 'rarity': card[2],
                        'rar_class':card[2].lower().replace(' ', '_')} for card in cards]
            boosters.append(booster)
    return render_template('boosters.html', boosters=boosters)


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
