from flask import Flask, session, render_template, url_for, request
from flask import Markup, send_from_directory, jsonify
from flask_session import Session
from flask_compress import Compress
from datetime import timedelta
from system.config_load import config_dict
import json
import calendar
import time
import urllib.parse
from functools import wraps

from system.db import Database

from flask_wtf.csrf import CSRFProtect, CSRFError

from system.crypto_functions import check_hash

from forms import *

from os import environ

from routes import *

global db

csrf = CSRFProtect()
csrf.exempt("routes.tools.http_sniffer_capture_page")

config = config_dict()

compress = Compress()

db = Database(config)

app = Flask(__name__,
            static_url_path='',
            static_folder='static',
            template_folder='templates')

app.config['SESSION_PERMANENT'] = False
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=5)
app.config['SECRET_KEY'] = config['main']['secret']

app.register_blueprint(routes)

sess = Session()

sess.init_app(app)

csrf.init_app(app)

compress.init_app(app)


def ok_user_and_password(username, password):
    return username == config['security']['basic_login'] and \
           password == config['security']['basic_password']


def authenticate():
    message = {'message': "Authenticate."}
    resp = jsonify(message)

    resp.status_code = 401
    resp.headers['WWW-Authenticate'] = 'Basic realm="Main"'

    return resp


def requires_authorization(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if config['security']['basic_auth'] == '0':
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not ok_user_and_password(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)

    return decorated


@app.errorhandler(404)
def page_not_found(e):
    # note that we set the 404 status explicitly
    return render_template('page404.html'), 404


def redirect(redirect_path):
    response = jsonify()
    response.status_code = 302
    response.headers['location'] = redirect_path
    response.autocorrect_location_header = False
    return response


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    return render_template('csrf_error.html', reason=e.description), 400


def check_session(fn):
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        url = request.path
        if 'id' not in session:
            return redirect(
                '/logout?redirect={}'.format(urllib.parse.quote_plus(url)))
        current_user = db.select_user_by_id(session['id'])
        if not db.select_user_by_id(session['id']):
            return redirect('/logout')
        kwargs['current_user'] = current_user[0]
        return fn(*args, **kwargs)

    return decorated_view


def check_team_access(fn):
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        team_id = kwargs['team_id']
        user_teams = db.select_user_teams(session['id'])
        current_team = {}
        for found_team in user_teams:
            if found_team['id'] == str(team_id):
                current_team = found_team
        if not current_team:
            return redirect(url_for('create_team'))
        kwargs['current_team'] = current_team
        return fn(*args, **kwargs)

    return decorated_view


def send_log_data(fn):
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        current_team = {}
        current_project = {}
        if 'current_team' in kwargs:
            current_team = kwargs['current_team']
        if 'current_project' in kwargs:
            current_project = kwargs['current_project']
        db.config_update(kwargs['current_user'],
                         current_team=current_team,
                         current_project=current_project)
        return fn(*args, **kwargs)

    return decorated_view


# init some global variables
@app.context_processor
def inject_stage_and_region():
    return dict(db=db,
                escape=Markup.escape,
                json_unpack=json.loads,
                json_pack=json.dumps,
                format_date=lambda unix_time,
                                   str_format: datetime.datetime.fromtimestamp(
                    int(unix_time)).strftime(str_format),
                urlencode=urllib.parse.quote,
                time=time.time,
                open=open,
                len=len,
                is_valid_uuid=is_valid_uuid
                )


if __name__ == '__main__':
    if config['ssl']['ssl'] == '1':
        app.run(
            ssl_context=(config['ssl']['cert'],
                         config['ssl']['priv_key']),
            host=config['network']['host'],
            port=config['network']['port'],
            debug=(config['main']['debug'] == '1'))
    # bugfix for heroku TODO: fix later
    elif 'PORT' in environ:
        app.run(
            host=config['network']['host'],
            port=environ['PORT'],
            debug=(config['main']['debug'] == '1'))
    else:
        app.run(
            host=config['network']['host'],
            port=config['network']['port'],
            debug=(config['main']['debug'] == '1'))
