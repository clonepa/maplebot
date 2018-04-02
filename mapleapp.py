from flask import Flask
from flask import render_template
import sqlite3
import maplebot
app = Flask(__name__)

@app.route('/')
@app.route('/<user>')
def index(user=None):
    user_record = None
    collection = None
    if user:
        user_record= maplebot.get_user_record(user)
        collection = maplebot.export_collection_to_list(user)
    return render_template('index.html',user=user_record,collection=collection)

if __name__ == "__main__":
    app.run(port=7172)
