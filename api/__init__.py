from flask import Blueprint
api_bp = Blueprint('api', __name__)


from api.v1.routes import *
