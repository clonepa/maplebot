from flask import Flask
from flask import render_template
app = Flask(__name__)

@app.route('/')
@app.route('/<user>')
def index(user=None):
    return render_template('index.html',user=user)
