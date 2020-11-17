from webargs import fields
from webargs import validate

token_create_args = {
    'email': fields.Email(required=True),
    'password': fields.Str(required=True),
    'name': fields.Str(required=False, missing=''),
    'duration': fields.Int(required=False,
                           missing=24 * 60 * 60,
                           validate=lambda p: p > 0)
    # validate=lambda p: (24 * 60 * 60 * 30) > p > 0)
}

only_token_args = {
    'access_token': fields.UUID(required=True)
}

project_logs_args = {
    'access_token': fields.UUID(required=True),
    'offset': fields.Int(required=False,
                         missing=0,
                         validate=lambda p: p >= 0),
    'limit': fields.Int(required=False,
                        missing=100,
                        validate=lambda p: p >= 0)
}

project_change_info_args = {
    'access_token': fields.UUID(required=True),
    'name': fields.String(required=False),
    'description': fields.String(required=False, ),
    'admin_email': fields.String(required=False)
}

project_add_user_args = {
    'access_token': fields.UUID(required=True),
    'email': fields.Email(required=True),
    'is_admin': fields.Boolean(required=False, missing=False)
}

project_user_action_args = {
    'access_token': fields.UUID(required=True),
    'user_id': fields.UUID(required=True)
}

project_update_args = {
    'access_token': fields.UUID(required=True),
    'name': fields.String(required=False, missing=None),
    'description': fields.String(required=False, missing=None),
    'type': fields.String(required=False, missing=None,
                          validate=validate.OneOf(["pentest"])),
    'scope': fields.String(required=False, missing=None),
    'start_date': fields.Integer(required=False, missing=None),
    'end_date': fields.Integer(required=False, missing=None),
    'auto_archive': fields.Boolean(required=False, missing=None),
    'status': fields.String(required=False, missing=None,
                            validate=validate.OneOf(["active", "archived"])),
    'testers': fields.List(fields.UUID(required=False), required=False,
                           missing=None),
    'teams': fields.List(fields.UUID(required=False), required=False,
                         missing=None)
}

new_project_args = {
    'access_token': fields.UUID(required=True),
    'name': fields.String(required=True),
    'description': fields.String(required=False, missing=''),
    'type': fields.String(required=True,
                          validate=validate.OneOf(["pentest"])),
    'scope': fields.String(required=False, missing=''),
    'start_date': fields.Integer(required=False, missing=None),
    'end_date': fields.Integer(required=False, missing=None),
    'auto_archive': fields.Boolean(required=False, missing=None),
    'testers': fields.List(fields.UUID(required=False), required=False,
                           missing=[]),
    'teams': fields.List(fields.UUID(required=False), required=False,
                         missing=[])
}

host_edit_args = {
    'access_token': fields.UUID(required=True),
    'description': fields.String(required=False, missing=None),
    'threats': fields.List(fields.String(required=False,
                                         validate=validate.OneOf(["critical",
                                                                  "high",
                                                                  "medium",
                                                                  "low",
                                                                  "info",
                                                                  "check",
                                                                  "checked"])),
                           required=False, missing=None)
}

port_edit_args = {
    'access_token': fields.UUID(required=True),
    'service': fields.String(required=False, missing=None),
    'description': fields.String(required=False, missing=None)
}

new_port_args = {
    'access_token': fields.UUID(required=True),
    'host_id': fields.UUID(required=True),
    'port': fields.Integer(required=True,
                           validate=lambda p: 25565 >= p > 0),
    'is_tcp': fields.Boolean(required=False,
                             missing=True),
    'service': fields.String(required=False,
                             missing=''),
    'description': fields.String(required=False,
                                 missing='')
}

new_host_args = {
    'access_token': fields.UUID(required=True),
    'ip': fields.IP(required=True),
    'description': fields.String(required=False, missing='')
}