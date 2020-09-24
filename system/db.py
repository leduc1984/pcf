import sqlite3
# from supersqlite import sqlite3
from system.config_load import config_dict
from system.crypto_functions import *
import json
from os import remove, path
import time
import ipaddress
import threading
import re
from base64 import b64encode


class Database:
    db_path = config_dict()['database']['path']
    cursor = None
    conn = None
    config = None
    current_user = {}
    current_team = {}
    current_project = {}

    def __init__(self, config):
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.create_function("REGEXP", 2, self.regexp)
        self.cursor = self.conn.cursor()
        self.config = config
        self.lock = threading.Lock()
        return

    def regexp(self, expr, item):
        reg = re.compile(expr)
        return reg.search(item) is not None

    def config_update(self, current_user, current_team={}, current_project={}):
        self.current_user = current_user
        self.current_team = current_team
        self.current_project = current_project

    def execute(self, sql, arg1=()):
        self.lock.acquire()
        self.cursor.execute(sql, arg1)
        self.lock.release()

    def return_arr_dict(self):
        self.lock.acquire()
        try:
            ncols = len(self.cursor.description)
            colnames = [self.cursor.description[i][0] for i in range(ncols)]
            results = []
            for row in self.cursor.fetchall():
                res = {}
                for i in range(ncols):
                    res[colnames[i]] = row[i]
                results.append(res)
        finally:
            self.lock.release()
        return results

    def insert_user(self, email, password):
        password_hash = hash_password(password)
        self.execute(
            "INSERT INTO Users(`id`,`email`,`password`) VALUES (?,?,?)",
            (gen_uuid(), email, password_hash)
        )
        self.conn.commit()
        return

    def select_user_by_email(self, email):
        self.execute('SELECT * FROM Users WHERE email=?', (email,))
        result = self.return_arr_dict()
        return result

    def select_user_by_id(self, user_id):
        # TODO: fix threads
        self.execute('SELECT * FROM Users WHERE id=?', (user_id,))
        result = self.return_arr_dict()
        return result

    def update_user_info(self, user_id, fname, lname, email, company):
        self.execute('''UPDATE Users SET fname=?, 
                                                lname=?, 
                                                email=?, 
                                                company=? 
                               WHERE id=?''',
                     (fname, lname, email, company, user_id))
        self.conn.commit()
        return

    def update_user_password(self, id, password):
        password_hash = hash_password(password)
        self.execute('''UPDATE Users SET password=? WHERE id=?''',
                     (password_hash, id))
        self.conn.commit()
        return

    def insert_team(self, name, description, user_id):
        team_id = gen_uuid()
        self.execute(
            "INSERT INTO Teams(`id`,`admin_id`,`name`,`description`,`admin_email`,`users`) "
            "VALUES (?,?,?,?,(SELECT `email` FROM Users WHERE `id`=? LIMIT 1),?)",
            (team_id,
             user_id,
             name,
             description,
             user_id,
             '{{"{}":"admin"}}'.format(user_id))  # initiation of json dict
        )
        self.conn.commit()

        self.insert_log('Team "{}" was created!'.format(name), teams=[team_id])

        return

    def select_user_teams(self, user_id):
        self.execute(
            'SELECT * FROM Teams WHERE '
            '`admin_id`=? OR '
            '`users` LIKE \'%\' || ? ||\'%\' ',
            (user_id, user_id))
        result = self.return_arr_dict()
        return result

    def update_team_info(self, team_id, name, admin_email, description,
                         user_id):
        self.execute(
            '''UPDATE Teams SET name=?,admin_email=?,description=? WHERE id=?''',
            (name, admin_email, description, team_id))
        self.conn.commit()
        self.insert_log('Team information was updated!')
        return

    def select_team_by_id(self, team_id):
        self.execute('SELECT * FROM Teams WHERE id=?', (team_id,))
        result = self.return_arr_dict()
        return result

    def update_new_team_user(self, team_id, user_email, user_id, role='tester'):
        curr_users_data = json.loads(
            self.select_team_by_id(team_id)[0]['users'])
        curr_user = self.select_user_by_email(user_email)[0]
        curr_users_data[curr_user['id']] = role
        self.execute(
            '''UPDATE Teams SET users=? WHERE id=?''',
            (json.dumps(curr_users_data), team_id))
        self.conn.commit()
        self.insert_log('User {} role was changed to {}!'.format(user_email,
                                                                 role))
        return

    def get_log_by_team_id(self, team_id):
        # TODO: need to optimise
        self.execute(
            '''SELECT * FROM Logs WHERE teams LIKE '%' || ? || '%' ORDER BY date DESC''',
            (team_id,))
        result = self.return_arr_dict()
        return result

    def insert_log(self, description, user_id='', teams=[], project_id='',
                   date=-1):
        if date == -1:
            date = int(time.time())
        if not project_id and 'id' in self.current_project:
            project_id = self.current_project['id']

        if not teams and 'id' in self.current_team:
            teams = [self.current_team]

        if not user_id and 'id' in self.current_user:
            user_id = self.current_user['id']

        if project_id and project_id == self.current_project['id'] \
                and not teams:
            teams = json.dumps(self.current_project['teams'])
        self.execute(
            '''INSERT INTO Logs(`id`,`teams`,`description`,`date`,`user_id`,`project`) 
               VALUES (?,?,?,?,?,?)''',
            (gen_uuid(), json.dumps(teams), description, date, user_id,
             project_id)
        )
        self.conn.commit()
        return

    def select_user_teams(self, user_id):
        self.execute(
            'SELECT * FROM Teams WHERE admin_id=? or users like "%" || ? || "%" ',
            (user_id, user_id))
        result = self.return_arr_dict()
        return result

    def select_user_team_members(self, user_id):
        teams = self.select_user_teams(user_id)
        members = []
        for team in teams:
            current_team = self.select_team_by_id(team['id'])[0]
            users = json.loads(current_team['users'])
            members += [user for user in users]
        members = list(set(members))

        members_info = []
        for member in members:
            members_info += self.select_user_by_id(member)
        return members_info

    def insert_new_project(self, name, description, project_type, scope,
                           start_date, end_date, auto_archive, testers,
                           teams, admin_id, user_id):
        project_id = gen_uuid()
        self.execute(
            "INSERT INTO Projects(`id`,`name`,`description`,`type`,`scope`,`start_date`,"
            "`end_date`,`auto_archive`,`status`,`testers`,`teams`,`admin_id`) "
            "VALUES (?,?,?,?,?,?,?,?,1,?,?,?)",
            (project_id,
             name,
             description,
             project_type,
             scope,
             int(start_date),
             int(end_date),
             int(auto_archive),
             json.dumps(testers),
             json.dumps(teams),
             admin_id)  # initiation of json dict
        )
        self.conn.commit()
        self.insert_log('Project {} was created!'.format(name), teams=teams)
        return project_id

    def check_admin_team(self, team_id, user_id):
        team = self.select_team_by_id(team_id)
        if not team:
            return False
        team = team[0]
        users = json.loads(team['users'])
        return team['admin_id'] == user_id or (
                user_id in users and users[user_id] == 'admin')

    def delete_user_from_team(self, team_id, user_id_delete, user_id):
        self.execute('SELECT * FROM Teams WHERE id=?', (team_id,))
        team = self.return_arr_dict()
        if not team:
            return 'Team does not exist.'
        team = team[0]
        if team['admin_id'] == user_id_delete:
            return 'Can\'t kick team creator.'
        users = json.loads(team['users'])
        if user_id_delete not in users:
            return 'User is not in team'
        del users[user_id_delete]

        self.execute(
            "UPDATE Teams set `users`=? WHERE id=?",
            (json.dumps(users), team_id)
        )
        self.conn.commit()
        current_user = self.select_user_by_id(user_id_delete)[0]
        self.insert_log('User {} was removed from team!'.format(
            current_user['email']))

        return ''

    def devote_user_from_team(self, team_id, user_id_devote, user_id):

        self.execute('SELECT * FROM Teams WHERE id=?', (team_id,))
        team = self.return_arr_dict()
        if not team:
            return 'Team does not exist.'
        team = team[0]
        if team['admin_id'] == user_id_devote:
            return 'Can\'t devote team creator.'
        users = json.loads(team['users'])
        if user_id_devote not in users:
            return 'User is not in team'
        if users[user_id_devote] != 'admin':
            return 'User is not team administrator.'

        users[user_id_devote] = 'tester'

        self.execute(
            "UPDATE Teams set `users`=? WHERE id=?",
            (json.dumps(users), team_id)
        )
        self.conn.commit()
        current_user = self.select_user_by_id(user_id_devote)[0]
        self.insert_log(
            'User {} was devoted to tester!'.format(current_user['email']))

        return ''

    def set_admin_team_user(self, team_id, user_id_admin, user_id):

        self.execute('SELECT * FROM Teams WHERE id=?', (team_id,))
        team = self.return_arr_dict()
        if not team:
            return 'Team does not exist.'
        team = team[0]
        if team['admin_id'] == user_id_admin:
            return 'Can\'t devote team creator.'
        users = json.loads(team['users'])
        if user_id_admin not in users:
            return 'User is not in team'
        if users[user_id_admin] != 'tester':
            return 'User is not team tester.'

        if users[user_id_admin] == 'admin':
            return 'User is already admin.'

        users[user_id_admin] = 'admin'

        self.execute(
            "UPDATE Teams set `users`=? WHERE id=?",
            (json.dumps(users), team_id)
        )
        self.conn.commit()
        current_user = self.select_user_by_id(user_id_admin)[0]
        self.insert_log(
            'User {} was promoted to admin!'.format(current_user['email']))
        return ''

    def select_team_projects(self, team_id):
        self.execute(
            '''SELECT * FROM Projects WHERE teams LIKE '%' || ? || '%' ''',
            (team_id,))
        result = self.return_arr_dict()
        return result

    def select_projects(self, project_id):
        self.execute(
            '''SELECT * FROM Projects WHERE id=? ''',
            (project_id,))
        result = self.return_arr_dict()
        return result

    def select_user_projects(self, user_id):
        projects = []
        user_teams = self.select_user_teams(user_id)
        for team in user_teams:
            team_projects = self.select_team_projects(team['id'])
            for team_project in team_projects:
                found = 0
                for added_project in projects:
                    if added_project['id'] == team_project['id']:
                        found = 1
                if not found:
                    projects.append(team_project)
        self.execute(
            '''SELECT * FROM Projects WHERE testers LIKE '%' || ? || '%' or admin_id=? ''',
            (user_id, user_id))
        user_projects = self.return_arr_dict()
        for user_project in user_projects:
            found = 0
            for added_project in projects:
                if added_project['id'] == user_project['id']:
                    found = 1
            if not found:
                projects.append(user_project)
        return projects

    def check_user_project_access(self, project_id, user_id):
        user_projects = self.select_user_projects(user_id)
        for user_project in user_projects:
            if user_project['id'] == project_id:
                return user_project
        return None

    def select_project_hosts(self, project_id):
        self.execute(
            '''SELECT * FROM Hosts WHERE project_id=? ORDER BY ip ASC''',
            (project_id,))
        result = self.return_arr_dict()
        return result

    def select_ip_hostnames(self, host_id):
        self.execute(
            '''SELECT * FROM Hostnames WHERE host_id=?''',
            (host_id,))
        result = self.return_arr_dict()
        return result

    def select_ip_from_project(self, project_id, ip):
        self.execute(
            '''SELECT * FROM Hosts WHERE project_id=? and ip=?''',
            (project_id, ip))
        result = self.return_arr_dict()
        return result

    def insert_host(self, project_id, ip, user_id, current_project,
                    comment=''):
        # todo refactor later - delete project_id and set current_project
        ip_id = gen_uuid()
        self.execute(
            '''INSERT INTO Hosts(`id`,`project_id`,`ip`,`comment`,`user_id`,`threats`) 
               VALUES (?,?,?,?,?,'[]')''',
            (ip_id, project_id, ip, comment, user_id)
        )
        self.conn.commit()
        self.insert_log('Added ip {}'.format(ip))
        self.insert_host_port(str(ip_id), 0, 1, 'info',
                              'Information about whole host', user_id,
                              project_id)

        return ip_id

    def select_project_host(self, project_id, host_id):
        self.execute(
            '''SELECT * FROM Hosts WHERE id=? AND project_id=?''',
            (host_id, project_id,))
        result = self.return_arr_dict()
        return result

    def select_host(self, host_id):
        self.execute(
            '''SELECT * FROM Hosts WHERE id=?''',
            (host_id,))
        result = self.return_arr_dict()
        return result

    def update_host_comment_threats(self, host_id, comment, threats):
        self.execute(
            '''UPDATE Hosts SET comment=?,threats=? WHERE id=?''',
            (comment, json.dumps(threats), host_id))
        self.conn.commit()
        self.insert_log('Updated ip {} description'.format(
            self.select_host(host_id)[0]['ip'])
        )
        return

    def delete_host(self, host_id):
        current_host = self.select_host(host_id)[0]
        self.execute(
            '''DELETE FROM Hosts WHERE id=?''',
            (host_id,))
        self.conn.commit()
        self.insert_log('Deleted ip {}'.format(current_host['ip']))
        return

    def delete_host_safe(self, project_id, host_id):
        host = self.select_project_host(project_id, host_id)
        if not host:
            return
        current_host = host[0]
        # delete ports
        ports = self.select_host_ports(current_host['id'], full=True)
        for current_port in ports:
            self.delete_port_safe(current_port['id'])

        # delete hostnames
        hostnames = self.select_ip_hostname(host_id)
        for hostname in hostnames:
            self.delete_hostname_safe(hostname['id'])

        # delete host
        self.delete_host(host_id)
        return

    def delete_hostname_safe(self, hostname_id):

        current_hostname = self.select_hostname(hostname_id)
        if not current_hostname:
            return

        # delete issue & pocs connection

        self.delete_issues_with_hostname(hostname_id)

        # delete files

        self.update_files_services_hostnames(hostname_id)

        # delete creds
        self.update_creds_hostnames(hostname_id)

        # delete hostname

        self.delete_hostname(hostname_id)

    def insert_host_port(self, host_id, port, is_tcp, service, description,
                         user_id, project_id):
        # check port in host
        curr_port = self.select_ip_port(host_id, port, is_tcp)
        if curr_port:
            return 'exist'
        port_id = gen_uuid()
        self.execute(
            '''INSERT INTO Ports(
            `id`,`host_id`,`port`,`is_tcp`,`service`,`description`,`user_id`,`project_id`) 
               VALUES (?,?,?,?,?,?,?,?)''',
            (port_id, host_id, port, int(is_tcp), service, description, user_id,
             project_id)
        )
        self.conn.commit()
        if port != 0:
            self.insert_log('Added port {}({}) to ip {}'.format(
                port,
                'tcp' if is_tcp else 'udp',
                self.select_host(host_id)[0]['ip']))
        return port_id

    def select_host_ports(self, host_id, full=False):
        if not full:
            self.execute(
                '''SELECT * FROM Ports WHERE host_id=? and port != 0 ORDER BY port''',
                (host_id,))
        else:
            self.execute(
                '''SELECT * FROM Ports WHERE host_id=? ORDER BY port''',
                (host_id,))
        result = self.return_arr_dict()
        return result

    def find_ip_hostname(self, host_id, hostname):
        self.execute(
            '''SELECT * FROM Hostnames WHERE host_id=? AND hostname=?''',
            (host_id, hostname))
        result = self.return_arr_dict()
        return result

    def insert_hostname(self, host_id, hostname, description, user_id):
        hostname_id = gen_uuid()
        self.execute(
            '''INSERT INTO Hostnames(
            `id`,`host_id`,`hostname`,`description`,`user_id`) 
               VALUES (?,?,?,?,?)''',
            (hostname_id, host_id, hostname, description, user_id)
        )
        self.conn.commit()
        self.insert_log(
            'Added hostname {} to host {}'.format(
                hostname, self.select_host(host_id)[0]['ip']))
        return hostname_id

    def update_hostname(self, hostname_id, description):
        self.execute(
            '''UPDATE Hostnames SET description=? WHERE id=?''',
            (description, hostname_id))
        self.conn.commit()
        self.insert_log('Updated hostname {} description'.format(
            self.select_hostname(hostname_id)[0]['hostname'])
        )
        return

    def check_host_hostname_id(self, host_id, hostname_id):
        self.execute(
            '''SELECT * FROM Hostnames WHERE host_id=? AND id=?''',
            (host_id, hostname_id))
        result = self.return_arr_dict()
        return result

    def delete_hostname(self, hostname_id):
        current_hostname = self.select_hostname(hostname_id)[0]
        self.execute(
            '''DELETE FROM Hostnames WHERE id=?''',
            (hostname_id,))
        self.conn.commit()
        self.insert_log(
            'Deleted hostname {}'.format(current_hostname['hostname']))
        return

    def check_port_in_project(self, project_id, port_id):
        self.execute(
            '''SELECT project_id FROM Hosts WHERE 
            id=(SELECT host_id FROM Ports WHERE id=? LIMIT 1) 
            and project_id=? ''',
            (port_id, project_id))
        result = self.return_arr_dict()
        return result != []

    def select_port(self, port_id):
        self.execute(
            '''SELECT * FROM Ports WHERE id=?''',
            (port_id,))
        result = self.return_arr_dict()
        return result

    def select_hostname(self, hostname_id):
        self.execute(
            '''SELECT * FROM Hostnames WHERE id=?''',
            (hostname_id,))
        result = self.return_arr_dict()
        return result

    def insert_new_issue(self, name, description, url_path, cvss, user_id,
                         services, status, project_id, cve=0, cwe=0,
                         issue_type='custom', fix='', param=''):
        issue_id = gen_uuid()
        self.execute(
            '''INSERT INTO Issues(
            `id`,`name`,`description`,`url_path`,`cvss`,`user_id`,`services`,`status`, `project_id`, `cve`,`cwe`,`type`,`fix`,`param`) 
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (issue_id, name, description, url_path, cvss, user_id,
             json.dumps(services), status, project_id, cve, cwe, issue_type,
             fix, param)
        )
        self.conn.commit()
        self.insert_log('Added issue "{}"'.format(name))
        return issue_id

    def select_project_issues(self, project_id):
        self.execute(
            '''SELECT * FROM Issues WHERE project_id=? ORDER BY cvss DESC''',
            (project_id,))
        result = self.return_arr_dict()
        return result

    def select_port_issues(self, port_id):
        self.execute(
            '''SELECT * FROM Issues WHERE services LIKE '%' || ? || '%' ORDER BY cvss DESC''',
            (port_id,))
        result = self.return_arr_dict()
        return result

    def select_host_by_port_id(self, port_id):
        self.execute(
            '''SELECT * FROM Hosts WHERE 
            id=(SELECT host_id FROM Ports WHERE id=?)''',
            (port_id,))
        result = self.return_arr_dict()
        return result

    def select_issue(self, issue_id):
        self.execute(
            '''SELECT * FROM Issues WHERE id=?''',
            (issue_id,))
        result = self.return_arr_dict()
        return result

    def update_issue(self, issue_id, name, description, url_path, cvss,
                     services, status, cve, cwe, fix, issue_type, param):
        self.execute(
            '''UPDATE Issues SET name=?, description=?, url_path=?, cvss=?, 
            services=?, status=?, cve=?, cwe=?, fix=?, type=?, param=? WHERE id=?''',
            (name, description, url_path, cvss,
             json.dumps(services), status, cve, cwe, fix, issue_type,
             param,  issue_id)
        )
        self.conn.commit()
        self.insert_log('Updated issue {}'.format(name))

    def check_hostname_port_in_issue(self, hostname_id, port_id, issue_id):
        current_issue = self.select_issue(issue_id)[0]
        services = json.loads(current_issue['services'])
        if port_id not in services:
            return False
        if hostname_id not in services[port_id]:
            return False
        return True

    def insert_new_poc(self, port_id, description, file_type, filename,
                       issue_id,
                       user_id, hostname_id, poc_id=gen_uuid()):
        self.execute(
            '''INSERT INTO PoC(
            `id`,`port_id`,`description`,`type`,`filename`,
            `issue_id`,`user_id`,`hostname_id`) 
               VALUES (?,?,?,?,?,?,?,?)''',
            (poc_id, port_id, description, file_type, filename, issue_id,
             user_id,
             hostname_id)
        )
        self.conn.commit()
        current_issue = self.select_issue(issue_id)[0]
        self.insert_log('Added PoC {} to issue {}'.format(poc_id,
                                                          current_issue[
                                                              'name']))
        return poc_id

    def select_issue_pocs(self, issue_id):
        self.execute(
            '''SELECT * FROM PoC WHERE issue_id=?''',
            (issue_id,))
        result = self.return_arr_dict()
        return result

    def select_poc(self, poc_id):
        self.execute(
            '''SELECT * FROM PoC WHERE id=?''',
            (poc_id,))
        result = self.return_arr_dict()
        return result

    def delete_poc(self, poc_id):
        self.execute(
            '''DELETE FROM PoC WHERE id=?''',
            (poc_id,))
        self.conn.commit()
        if self.config['main']['auto_delete_poc'] == '1':
            poc_path = path.join('./static/files/poc/', poc_id)
            remove(poc_path)
            self.insert_log('Deleted PoC {} with file'.format(poc_id))
        self.insert_log('Deleted PoC {} without file.'.format(poc_id))
        return

    def delete_issue(self, issue_id):
        current_issue = self.select_issue(issue_id)[0]
        self.execute(
            '''DELETE FROM Issues WHERE id=?''',
            (issue_id,))
        self.conn.commit()
        self.insert_log('Deleted Issue {}'.format(current_issue['name']))
        return

    def insert_new_network(self, ip, mask, asn, comment, project_id, user_id,
                           is_ipv6):
        network_id = gen_uuid()
        self.execute(
            '''INSERT INTO Networks(
            `id`,`ip`,`mask`,`comment`,`project_id`,`user_id`,`is_ipv6`,`asn`) 
               VALUES (?,?,?,?,?,?,?,?)''',
            (network_id, ip, mask, comment, project_id, user_id, int(is_ipv6),
             asn)
        )
        self.conn.commit()
        self.insert_log('Added new network {}/{}'.format(ip, mask))
        return network_id

    def select_project_networks(self, project_id):
        self.execute(
            '''SELECT * FROM Networks WHERE project_id=?''',
            (project_id,))
        result = self.return_arr_dict()
        return result

    def delete_network(self, network_id):
        current_network = self.select_network(network_id)[0]
        self.execute(
            '''DELETE FROM Networks WHERE id=?''',
            (network_id,))
        self.conn.commit()
        self.insert_log('Deleted network {}/{}'.format(current_network['ip'],
                                                       current_network['mask']))
        return

    def select_network(self, network_id):
        self.execute(
            '''SELECT * FROM Networks WHERE id=?''',
            (network_id,))
        result = self.return_arr_dict()
        return result

    def insert_new_cred(self, login, password_hash, hash_type,
                        cleartext_passwd, description, source,
                        services, user_id, project_id):
        cred_id = gen_uuid()
        self.execute(
            '''INSERT INTO Credentials(
            `id`,`login`,`hash`,`hash_type`,`cleartext`,
            `description`,`source`,`services`, `user_id`, `project_id`)
             VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (cred_id, login, password_hash, hash_type, cleartext_passwd,
             description, source, json.dumps(services), user_id, project_id)
        )
        self.conn.commit()
        self.insert_log('Added new credentials {}'.format(cred_id))
        return cred_id

    def select_project_creds(self, project_id):
        self.execute(
            '''SELECT * FROM Credentials WHERE project_id=?''',
            (project_id,))
        result = self.return_arr_dict()
        return result

    def select_creds(self, creds_id):
        self.execute(
            '''SELECT * FROM Credentials WHERE id=?''',
            (creds_id,))
        result = self.return_arr_dict()
        return result

    def delete_creds(self, creds_id):
        self.execute(
            '''DELETE FROM Credentials WHERE id=?''',
            (creds_id,))
        self.conn.commit()
        self.insert_log('Deleted credentials {}'.format(creds_id))
        return

    def update_creds(self, creds_id, login, password_hash, hash_type,
                     cleartext_passwd, description, source,
                     services):
        self.execute(
            '''UPDATE Credentials SET `login`=?,`hash`=?,`hash_type`=?,`cleartext`=?,
            `description`=?,`source`=?,`services`=? WHERE id=?''',
            (login, password_hash, hash_type, cleartext_passwd,
             description, source, json.dumps(services), creds_id)
        )
        self.conn.commit()
        self.insert_log('Updated credentials {}'.format(creds_id))
        return

    def select_project_notes(self, project_id):
        self.execute(
            '''SELECT * FROM Notes WHERE project_id=?''',
            (project_id,))
        result = self.return_arr_dict()
        return result

    def select_note(self, note_id):
        self.execute(
            '''SELECT * FROM Notes WHERE id=?''',
            (note_id,))
        result = self.return_arr_dict()
        return result

    def insert_new_note(self, project_id, name, user_id):
        note_id = gen_uuid()
        self.execute(
            '''INSERT INTO Notes(
            `id`,`project_id`,`name`,`text`,`user_id`) 
               VALUES (?,?,?,'',?)''',
            (note_id, project_id, name, user_id)
        )
        self.conn.commit()
        self.insert_log('Created new note "{}"'.format(name))
        return note_id

    def update_note(self, note_id, text_data, project_id):
        current_note = self.select_note(note_id)[0]
        self.execute(
            '''UPDATE Notes SET `text`=? WHERE `id`=? AND `project_id`=?''',
            (text_data, note_id, project_id)
        )
        self.conn.commit()
        self.insert_log('Edited note {}'.format(current_note['name']))
        return

    def delete_note(self, note_id, project_id):
        current_note = self.select_note(note_id)[0]
        self.execute(
            '''DELETE FROM Notes WHERE `id`=? AND `project_id`=?''',
            (note_id, project_id)
        )
        self.conn.commit()
        self.insert_log('Deleted note {}'.format(current_note['name']))
        return

    def insert_new_file(self, file_id, project_id, filename, description,
                        services, filetype, user_id):
        # todo: fix file_id param
        self.execute(
            '''INSERT INTO Files(
            `id`,`project_id`,`filename`,`description`,
            `services`,`type`,`user_id`) VALUES (?,?,?,?,?,?,?)''',
            (file_id, project_id, filename, description,
             json.dumps(services), filetype, user_id)
        )
        self.conn.commit()
        self.insert_log('Added new file {}'.format(filename))
        return

    def select_files(self, file_id):
        self.execute(
            '''SELECT * FROM Files WHERE id=?''',
            (file_id,))
        result = self.return_arr_dict()
        return result

    def select_project_files(self, project_id):
        self.execute(
            '''SELECT * FROM Files WHERE project_id=?''',
            (project_id,))
        result = self.return_arr_dict()
        return result

    def delete_file(self, file_id):
        current_file = self.select_files(file_id)[0]
        self.execute(
            '''DELETE FROM Files WHERE id=?''',
            (file_id,))
        self.conn.commit()
        self.insert_log('Deleted file {}'.format(current_file['filename']))
        return

    def update_project_status(self, project_id, status):
        # TODO: add data types to functions status: int
        self.execute(
            '''UPDATE Projects SET status=? WHERE `id`=? ''',
            (status, project_id)
        )
        self.conn.commit()
        self.insert_log('Updated project status to {}'.format(int(status)))
        return

    def update_project_settings(self, project_id, name, description,
                                project_type, scope,
                                start_date, end_date, auto_archive, testers,
                                teams):
        self.execute(
            "UPDATE Projects set `name`=?,`description`=?,`type`=?,"
            "`scope`=?,`start_date`=?,"
            "`end_date`=?,`auto_archive`=?,"
            "`testers`=?,`teams`=? WHERE `id`=? ",
            (name,
             description,
             project_type,
             scope,
             int(start_date),
             int(end_date),
             int(auto_archive),
             json.dumps(testers),
             json.dumps(teams),
             project_id)
        )
        self.conn.commit()
        self.insert_log('Updated project settings ')
        return

    def update_project_autoarchive(self, project_id, autoarchive):
        self.execute(
            '''UPDATE Projects SET auto_archive=? WHERE `id`=? ''',
            (autoarchive, project_id)
        )
        self.conn.commit()
        self.insert_log(
            'Updated project autoarchive param to {}'.format(int(autoarchive)))
        return

    def select_project_host_by_ip(self, project_id, ip):
        self.execute(
            '''SELECT * FROM Hosts WHERE project_id=? and ip=?''',
            (project_id, ip))
        result = self.return_arr_dict()
        return result

    def select_ip_hostname(self, host_id, hostname):
        self.execute(
            '''SELECT * FROM Hostnames WHERE host_id=? and hostname=?''',
            (host_id, hostname))
        result = self.return_arr_dict()
        return result

    def select_ip_port(self, host_id, port, is_tcp=True):
        self.execute(
            '''SELECT * FROM Ports WHERE host_id=? and port=? and is_tcp=?''',
            (host_id, port, is_tcp))
        result = self.return_arr_dict()
        return result

    def update_port_proto_description(self, port_id, service, description):
        current_port = self.select_port(port_id)[0]
        current_host = self.select_host(current_port['host_id'])[0]
        self.execute(
            '''UPDATE Ports SET service=?, description=? WHERE `id`=? ''',
            (service, description, port_id)
        )
        self.conn.commit()
        self.insert_log('Updated port {}:{}({}) info'.format(
            current_host['ip'],
            current_port['port'],
            'tcp' if current_port['is_tcp'] else 'udp')
        )
        return

    def update_port_service(self, port_id, service):
        current_port = self.select_port(port_id)[0]
        current_host = self.select_host(current_port['host_id'])[0]
        self.execute(
            '''UPDATE Ports SET service=? WHERE `id`=? ''',
            (service, port_id)
        )
        self.conn.commit()
        self.insert_log('Updated {}:{}({}) service info'.format(
            current_host['ip'],
            current_port['port'],
            'tcp' if current_port['is_tcp'] else 'udp'))
        return

    def select_host_issues(self, host_id):
        self.execute(
            '''SELECT * FROM Ports WHERE host_id=?''',
            (host_id,))
        ports = self.return_arr_dict()
        result = []
        for port in ports:
            issues = self.select_port_issues(port['id'])
            for issue in issues:
                if issue not in result:
                    result.append(issue)
        return result

    def select_port_issues_stats(self, port_id):
        port_issues = self.select_port_issues(port_id)
        criticality = {'info': [], 'low': [], 'medium': [], 'high': [],
                       'critical': []}
        for issue in port_issues:
            if issue['cvss'] == 0:
                criticality['info'].append(issue)
            elif issue['cvss'] <= 3.9:
                criticality['low'].append(issue)
            elif issue['cvss'] <= 6.9:
                criticality['medium'].append(issue)
            elif issue['cvss'] <= 8.9:
                criticality['high'].append(issue)
            else:
                criticality['critical'].append(issue)
        return criticality

    def update_issue_services(self, issue_id, services):
        current_issue = self.select_issue(issue_id)[0]
        self.execute(
            '''UPDATE Issues SET services=? WHERE `id`=? ''',
            (json.dumps(services), issue_id)
        )
        self.conn.commit()
        self.insert_log(
            'Updated issue {} services'.format(current_issue['name']))
        return

    def delete_issue_host(self, issue_id, host_id):
        ports = self.select_host_ports(host_id, full=True)
        issue = self.select_issue(issue_id)
        if not issue:
            return
        issue = issue[0]
        issue_services = json.loads(issue['services'])
        old_services = issue_services.copy()
        for port in ports:
            if port['id'] in issue_services:
                del issue_services[port['id']]
        if old_services != issue_services:
            self.update_issue_services(issue_id, issue_services)
        current_issue = self.select_issue(issue_id)[0]
        self.insert_log('Updated issue {} hosts'.format(current_issue['name']))
        return

    def delete_issues_with_port(self, port_id):
        issues = self.select_port_issues(port_id)
        for issue in issues:
            services = json.loads(issue['services'])
            del services[port_id]
            self.execute(
                '''UPDATE Issues SET services=? WHERE `id`=? ''',
                (json.dumps(services), issue['id'])
            )
            self.conn.commit()

            self.insert_log('Updated issue {} ports'.format(issue['name']))

            pocs = self.select_issue_pocs(issue['id'])

            for poc in pocs:
                if poc['port_id'] == port_id:
                    self.delete_poc(poc['id'])
        return

    def select_hostname_issues(self, hostname_id):
        self.execute(
            '''SELECT * FROM Issues WHERE services LIKE '%' || ? || '%' ORDER BY cvss DESC''',
            (hostname_id,))
        result = self.return_arr_dict()
        return result

    def delete_issues_with_hostname(self, hostname_id):
        if hostname_id == '0':
            return
        issues = self.select_hostname_issues(hostname_id)
        for issue in issues:
            services = json.loads(issue['services'])
            for port_id in services:
                if hostname_id in services[port_id]:
                    del services[port_id][services[port_id].index(hostname_id)]
            self.execute(
                '''UPDATE Issues SET services=? WHERE `id`=? ''',
                (json.dumps(services), issue['id'])
            )
            self.conn.commit()

            self.insert_log('Updated issue {} hosts'.format(issue['name']))

            pocs = self.select_issue_pocs(issue['id'])

            for poc in pocs:
                if poc['hostname_id'] == hostname_id:
                    self.delete_poc(poc['id'])
        return

    def select_files_by_port(self, port_id):
        self.execute(
            '''SELECT * FROM Files WHERE services LIKE '%' || ? || '%' ''',
            (port_id,))
        files = self.return_arr_dict()
        return files

    def select_files_by_hostname(self, hostname_id):
        self.execute(
            '''SELECT * FROM Files WHERE services LIKE '%' || ? || '%' ''',
            (hostname_id,))
        files = self.return_arr_dict()
        return files

    def update_files_services_ports(self, port_id):
        files = self.select_files_by_port(port_id)

        for file in files:
            file_services = json.loads(file['services'])
            del file_services[port_id]
            self.execute(
                '''UPDATE Files SET services=? WHERE `id`=? ''',
                (json.dumps(file_services), file['id'])
            )
            self.conn.commit()
            self.insert_log('Updated file {} services'.format(file['filename']))

        return

    def update_files_services_hostnames(self, hostname_id):
        if hostname_id == '0':
            return
        files = self.select_files_by_hostname(hostname_id)

        for file in files:
            file_services = json.loads(file['services'])
            for port_id in file_services:
                if hostname_id in file_services[port_id]:
                    del file_services[port_id][
                        file_services[port_id].index(hostname_id)]
            self.execute(
                '''UPDATE Files SET services=? WHERE `id`=? ''',
                (json.dumps(file_services), file['id'])
            )
            self.conn.commit()
            self.insert_log(
                'Updated file {} hostnames'.format(file['filename']))

        return

    def select_creds_by_port(self, port_id):
        self.execute(
            '''SELECT * FROM Credentials WHERE services LIKE '%' || ? || '%' ''',
            (port_id,))
        result = self.return_arr_dict()
        return result

    def select_creds_by_host(self, project_id, host_id):
        host_port_ids = [port['id'] for port in self.select_host_ports(host_id)]
        project_creds = self.select_project_creds(project_id)
        if not project_creds or not host_port_ids:
            return []
        creds_array = []

        for current_creds in project_creds:
            services = json.loads(current_creds['services'])
            found = 0
            for port_id in services:
                if port_id in host_port_ids:
                    found = 1
            if found:
                creds_array.append(current_creds)
        return creds_array

    def select_creds_by_hostname(self, hostname_id):
        self.execute(
            '''SELECT * FROM Credentials WHERE services LIKE '%' || ? || '%' ''',
            (hostname_id,))
        result = self.return_arr_dict()
        return result

    def update_creds_services(self, port_id):

        creds = self.select_creds_by_port(port_id)

        for cred in creds:
            cred_services = json.loads(cred['services'])
            del cred_services[port_id]
            self.execute(
                '''UPDATE Credentials SET services=? WHERE `id`=? ''',
                (json.dumps(cred_services), cred['id'])
            )
            self.conn.commit()
            self.insert_log('Updated credentials {} ports'.format(cred['id']))
        return

    def update_creds_hostnames(self, hostname_id):

        creds = self.select_creds_by_hostname(hostname_id)

        for cred in creds:
            cred_services = json.loads(cred['services'])
            for port_id in cred_services:
                if hostname_id in cred_services[port_id]:
                    del cred_services[port_id][
                        cred_services[port_id].index(hostname_id)]
            self.execute(
                '''UPDATE Credentials SET services=? WHERE `id`=? ''',
                (json.dumps(cred_services), cred['id'])
            )
            self.conn.commit()
            self.insert_log(
                'Updated credentials {} hostnames'.format(cred['id']))
        return

    def delete_port_safe(self, port_id):

        # delete port

        self.execute(
            '''DELETE FROM Ports WHERE `id`=? ''',
            (port_id,)
        )
        self.conn.commit()

        # delete issue & pocs connection

        self.delete_issues_with_port(port_id)

        # delete files

        self.update_files_services_ports(port_id)

        # delete creds
        self.update_creds_services(port_id)

    def select_project_hosts_by_port(self, project_id, port):

        self.execute(
            '''SELECT * FROM Hosts WHERE id IN 
            (SELECT host_id FROM Ports WHERE port=? AND 
            host_id IN (SELECT id FROM Hosts WHERE project_id=? )) ''',
            (port, project_id))
        result = self.return_arr_dict()
        return result

    def select_project_hosts_by_subnet(self, project_id, subnet):

        # subnet = 127.0.0.1/2
        subnet_obj = ipaddress.ip_network(subnet, False)

        result = []
        hosts = self.select_project_hosts(project_id)
        for current_host in hosts:
            ip_obj = ipaddress.ip_address(current_host['ip'])
            if ip_obj in subnet_obj:
                result.append(current_host)
        return result

    def search_host(self, project_id, search_request):

        search_request = search_request.strip()

        all_hosts = self.select_project_hosts(project_id)

        if not search_request:
            return all_hosts

        # split by params

        params_dict = {}
        try:
            params_arr = search_request.split(' ')
            for param in params_arr:
                param_data = param.split('=')
                params_dict[param_data[0]] = param_data[1]
        except:
            pass

        if params_dict:
            if 'port' in params_dict:
                return self.select_project_hosts_by_port(project_id,
                                                         params_dict['port'])
            if 'subnet' in params_dict:
                return self.select_project_hosts_by_subnet(project_id,
                                                           params_dict[
                                                               'subnet'])

        # find by ip/comment

        self.execute(
            '''SELECT * FROM Hosts WHERE project_id=? and (ip LIKE '%' || ? || '%' or 
            comment LIKE '%' || ? || '%') ''',
            (project_id, search_request, search_request))
        hosts = self.return_arr_dict()

        # find by hostname

        for host in all_hosts:
            hostname = self.select_ip_hostnames(host['id'])
            if hostname and search_request in hostname[0]['hostname']:
                found = 0
                # check if host_id in hosts
                for check_host in hosts:
                    if check_host['id'] == hostname[0]['host_id']:
                        found = 1
                if not found:
                    hosts += self.select_project_host(project_id,
                                                      hostname[0]['host_id'])
        return hosts

    def search_hostlist(self, project_id=None, network='', ip_hostname='',
                        issue_name='', port='', service='', comment='',
                        threats=''):

        all_hosts = self.select_project_hosts(project_id)

        if not network and not ip_hostname and not issue_name and not port and \
                not service and not comment and not threats:
            return all_hosts

        # host filter
        if not ip_hostname:
            ip_hostname_result = all_hosts
        else:
            self.execute(
                '''SELECT * FROM Hosts WHERE ((ip LIKE '%' || ? || '%') and 
                (project_id = ?)) or id IN (SELECT host_id FROM Hostnames WHERE 
                project_id=? and hostname LIKE '%' || ? || '%' COLLATE NOCASE) COLLATE NOCASE''',
                (ip_hostname, project_id, project_id, ip_hostname))
            ip_hostname_result = self.return_arr_dict()

        # network filter
        if not network or not is_valid_uuid(network):
            network_result = all_hosts
        else:
            network = self.select_network(network)[0]
            ip = network['ip']
            mask = network['mask']
            subnet = '{}/{}'.format(ip, mask)
            network_result = []
            for host in all_hosts:
                if ipaddress.ip_address(host['ip']) in \
                        ipaddress.ip_network(subnet, False):
                    network_result.append(host)

        # issue filter
        if not issue_name:
            issue_result = all_hosts
        else:
            self.execute(
                '''SELECT * FROM Issues WHERE ((name LIKE '%' || ? || '%') and 
                (project_id = ?)) COLLATE NOCASE''',
                (issue_name, project_id))
            issues = self.return_arr_dict()
            issue_result = []
            for issue in issues:
                services = [service for service in
                            json.loads(issue['services'])]
                for curr_service in services:
                    host_id = self.select_port(curr_service)[0]['host_id']
                    host = self.select_host(host_id)[0]
                    issue_result.append(host)

        # comment filter
        if not comment:
            comment_result = all_hosts
        else:
            comment_result = []
            for host in all_hosts:
                if comment.lower() in host['comment'].lower():
                    comment_result.append(host)

        # threats filter
        if not threats:
            threats_result = all_hosts
        else:
            threats_set = set(threats)
            threats_result = []
            for host in all_hosts:
                host_theats = set(json.loads(host['threats']))
                if host_theats & threats_set:
                    threats_result.append(host)

        # port_service
        if (not port) and (not service):
            port_service_result = all_hosts
        else:
            service = service.lower() if service else ''
            service_regex = '|'.join(service.split(','))
            if port:
                port_array = port.split(',')
                port_regexp = '|'.join([str(int(port.split('/')[0])) + '/' + \
                                        str(int(port.split('/')[1] == 'tcp')) \
                                        for port in port_array])

                self.execute(
                    '''SELECT * FROM Hosts WHERE project_id=? and id IN 
                    (SELECT host_id FROM Ports WHERE (port || '/' || is_tcp) REGEXP ? and 
                    LOWER(service) REGEXP ?)''',
                    (project_id, port_regexp, service_regex))
                port_service_result = self.return_arr_dict()
            else:
                self.execute(
                    '''SELECT * FROM Hosts WHERE project_id=? and id IN 
                    (SELECT host_id FROM Ports WHERE 
                    service REGEXP ?)''',
                    (project_id, service_regex))
                port_service_result = self.return_arr_dict()

        # summary
        unique_results = []
        for host in all_hosts:
            if all(host in i for i in
                   (all_hosts, ip_hostname_result, network_result,
                    issue_result, comment_result, threats_result,
                    port_service_result)):
                unique_results.append(host)

        return unique_results

    def search_issues(self, project_id, search_request):
        all_issues = self.select_project_issues(project_id)
        if not search_request:
            return all_issues

        # find name, description, status

        self.execute(
            '''SELECT * FROM Issues WHERE project_id = ? and (
                name LIKE '%' || ? || '%' or 
                description LIKE '%' || ? || '%' or 
                url_path LIKE '%' || ? || '%' or 
                cve LIKE '%' || ? || '%' or 
                status LIKE '%' || ? || '%' or 
                type LIKE '%' || ? || '%' or 
                fix LIKE '%' || ? || '%' or
                param LIKE '%' || ? || '%') ORDER BY cvss DESC''',
            (project_id, search_request, search_request,
             search_request, search_request, search_request))
        issues = self.return_arr_dict()

        # find host issues

        self.execute(
            '''SELECT * FROM Hosts WHERE project_id=? and (ip LIKE '%' || ? || '%')  ''',
            (project_id, search_request))
        hosts = self.return_arr_dict()

        for host in hosts:
            host_issues = self.select_host_issues(host['id'])
            for current_issue in host_issues:
                found = 0
                for added_issue in issues:
                    if added_issue['id'] == current_issue['id']:
                        found = 1
                if not found:
                    issues.append(current_issue)
        return issues

    def search_issues_port_ids(self, project_id, issues_name):
        self.execute(
            '''SELECT * FROM Issues WHERE project_id = ? and 
                name LIKE '%' || ? || '%' ''',
            (project_id, issues_name))
        issues = self.return_arr_dict()

        ports_result = []

        for issue in issues:
            ports_result += [port for port in
                             json.loads(issue['services'])]

        return ports_result

    def select_project_ports(self, project_id):
        self.execute(
            '''SELECT * FROM Ports WHERE project_id=? ORDER BY port,is_tcp''',
            (project_id,))
        result = self.return_arr_dict()
        return result

    def select_project_ports_unique(self, project_id):
        results = self.select_project_ports(project_id)
        unique_results = []
        for port in results:
            found = 0
            for added_port in unique_results:
                if added_port['port'] == port['port'] and \
                        added_port['is_tcp'] == port['is_tcp']:
                    found = 1
            if not found and port['port'] != 0:
                unique_results.append(port)
        return unique_results

    def select_project_ports_grouped(self, project_id):
        all_ports = self.select_project_ports(project_id)
        # port, is_tcp, service, description, host_id:[]
        grouped_ports = []
        for port in all_ports:
            found = 0
            for added_port in grouped_ports:
                if added_port['port'] == port['port'] and \
                        added_port['is_tcp'] == port['is_tcp'] and \
                        added_port['service'] == port['service'] and \
                        added_port['description'] == port['description'] and \
                        port['host_id'] not in added_port['host_id']:
                    added_port['host_id'].append(port['host_id'])
                    issues = self.select_port_issues(port['id'])
                    for issue in issues:
                        if issue['cvss'] == 0 and \
                                'info' not in added_port['issues']:
                            added_port['issues'].append('info')
                        elif issue['cvss'] <= 3.9 and \
                                'low' not in added_port['issues']:
                            added_port['issues'].append('low')
                        elif issue['cvss'] <= 6.9 and \
                                'medium' not in added_port['issues']:
                            added_port['issues'].append('medium')
                        elif issue['cvss'] <= 8.9 and \
                                'high' not in added_port['issues']:
                            added_port['issues'].append('high')
                        elif 'critical' not in added_port['issues']:
                            added_port['issues'].append('critical')
                    found = 1
            if not found and port['port'] != 0:
                new_port = {}
                new_port['port'] = port['port']
                new_port['is_tcp'] = port['is_tcp']
                new_port['service'] = port['service']
                new_port['description'] = port['description']
                new_port['host_id'] = [port['host_id']]
                new_port['issues'] = []
                issues = self.select_port_issues(port['id'])
                for issue in issues:
                    if issue['cvss'] == 0 and \
                            'info' not in new_port['issues']:
                        new_port['issues'].append('info')
                    elif issue['cvss'] <= 3.9 and \
                            'low' not in new_port['issues']:
                        new_port['issues'].append('low')
                    elif issue['cvss'] <= 6.9 and \
                            'medium' not in new_port['issues']:
                        new_port['issues'].append('medium')
                    elif issue['cvss'] <= 8.9 and \
                            'high' not in new_port['issues']:
                        new_port['issues'].append('medium')
                    elif 'critical' not in new_port['issues']:
                        new_port['issues'].append('critical')
                grouped_ports.append(new_port)
        return grouped_ports

    def update_host_description(self, host_id, comment):
        self.execute(
            '''UPDATE Hosts SET comment=? WHERE `id`=? ''',
            (comment, host_id)
        )
        self.conn.commit()
        current_host = self.select_host(host_id)[0]
        self.insert_log(
            'Updated host {} description'.format(current_host['ip']))
        return

    def select_project_chats(self, project_id, js=False):
        self.cursor.close()
        self.cursor = self.conn.cursor()
        self.execute(
            '''SELECT * FROM Chats WHERE project_id=? ''',
            (project_id,))
        result = self.return_arr_dict()
        if js:
            return [x['id'] for x in result]
        return result

    def select_project_chat(self, project_id, chat_id):
        self.execute(
            '''SELECT * FROM Chats WHERE project_id=? and id=? ''',
            (project_id, chat_id))
        result = self.return_arr_dict()
        return result

    def select_chat(self, chat_id):
        self.execute(
            '''SELECT * FROM Chats WHERE id=? ''',
            (chat_id,))
        result = self.return_arr_dict()
        return result

    def select_chat_messages(self, chat_id, date=-1):
        self.execute(
            '''SELECT * FROM Messages WHERE chat_id=? AND time>? ORDER BY time''',
            (chat_id, date))
        result = self.return_arr_dict()
        return result

    def insert_chat(self, project_id, name, user_id):
        chat_id = gen_uuid()
        self.execute(
            '''INSERT INTO Chats(
            `id`,`project_id`,`name`,`user_id`) 
               VALUES (?,?,?,?)''',
            (chat_id, project_id, name, user_id)
        )
        self.conn.commit()
        self.insert_log('Created new chat {}'.format(name))
        return chat_id

    def insert_new_message(self, chat_id, message, user_id):
        message_id = gen_uuid()
        message_time = int(time.time() * 1000)
        self.execute(
            '''INSERT INTO Messages(
            `id`,`chat_id`,`message`,`user_id`,`time`) 
               VALUES (?,?,?,?,?)''',
            (message_id, chat_id, message, user_id, message_time)
        )
        self.conn.commit()
        current_chat = self.select_chat(chat_id)
        self.insert_log('Wrote a message to chat "{}"'.format(
            current_chat[0]['name'])
        )
        return message_time

    def insert_new_http_sniffer(self, name, project_id):
        sniffer_id = gen_uuid()
        self.execute(
            '''INSERT INTO tool_sniffer_http_info(
            `id`,`project_id`,`name`,`status`,
            `location`,`body`) VALUES (?,?,?,?,?,?)''',
            (sniffer_id, project_id, name, 200, '', '')
        )
        self.conn.commit()
        self.insert_log('Added new HTTP-sniffer {}'.format(name))
        return

    def select_project_http_sniffers(self, project_id):
        self.execute(
            '''SELECT * FROM tool_sniffer_http_info WHERE project_id=?''',
            (project_id,))
        result = self.return_arr_dict()
        return result

    def select_http_sniffer_by_id(self, sniffer_id):
        self.execute(
            '''SELECT * FROM tool_sniffer_http_info WHERE id=?''',
            (sniffer_id,))
        result = self.return_arr_dict()
        return result

    def update_http_sniffer(self, sniffer_id, status, location, body):
        self.execute(
            '''UPDATE tool_sniffer_http_info SET status=?,
                  location=?,body=? WHERE `id`=? ''',
            (status, location, body, sniffer_id)
        )
        self.conn.commit()
        current_sniffer = self.select_http_sniffer_by_id(sniffer_id)[0]
        self.insert_log(
            'Updated HTTP-sniffer {} info'.format(current_sniffer['name']))
        return

    def insert_new_http_sniffer_package(self, sniffer_id, date, ip, request):
        package_id = gen_uuid()
        self.execute(
            '''INSERT INTO tool_sniffer_http_data(
            `id`,`sniffer_id`,`date`,`ip`,`request`) VALUES (?,?,?,?,?)''',
            (package_id, sniffer_id, date, ip, request)
        )
        self.conn.commit()
        self.insert_log('Captured HTTP-sniffer package')
        return

    def select_http_sniffer_requests(self, sniffer_id):
        self.execute(
            '''SELECT * FROM tool_sniffer_http_data WHERE sniffer_id=? ORDER BY date''',
            (sniffer_id,))
        result = self.return_arr_dict()
        return result

    def delete_http_sniffer_requests(self, sniffer_id):
        self.execute(
            '''DELETE FROM tool_sniffer_http_data WHERE sniffer_id=?''',
            (sniffer_id,))
        current_sniffer = self.select_http_sniffer_by_id(sniffer_id)[0]
        self.insert_log(
            'Cleared HTTP-sniffer {} requests'.format(current_sniffer['name']))

    def delete_http_sniffer(self, sniffer_id):
        current_sniffer = self.select_http_sniffer_by_id(sniffer_id)[0]
        self.execute(
            '''DELETE FROM tool_sniffer_http_info WHERE id=?''',
            (sniffer_id,))
        self.insert_log(
            'Removed HTTP-sniffer {}'.format(current_sniffer['name']))

    def safe_delete_http_sniffer(self, sniffer_id):
        self.delete_http_sniffer_requests(sniffer_id)
        self.delete_http_sniffer(sniffer_id)
        return

    def insert_config(self, team_id='0', user_id='0', name='', display_name='',
                      data='', visible=0):
        config_id = gen_uuid()
        self.execute(
            '''INSERT INTO Configs(
            `id`,`team_id`,`user_id`,`name`,`display_name`,
            `data`,`visible`) VALUES (?,?,?,?,?,?,?)''',
            (config_id, team_id, user_id, name, display_name, data, visible)
        )
        self.conn.commit()
        self.insert_log('Added "{}" config value'.format(display_name))
        return config_id

    def select_configs(self, team_id='0', user_id='0', name=''):
        self.execute(
            '''SELECT * FROM Configs WHERE team_id=? and user_id=? and 
            name LIKE '%' || ? || '%' ''',
            (team_id, user_id, name))
        result = self.return_arr_dict()
        return result

    def update_config(self, team_id='0', user_id='0', name='', value=''):
        self.execute(
            '''UPDATE Configs SET data = ? WHERE team_id=? and user_id=? and 
            name= ?  ''',
            (value, team_id, user_id, name))
        self.conn.commit()
        self.insert_log('Updated "{}" config value'.format(name))
        return

    def delete_config(self, team_id='0', user_id='0', name=''):
        self.execute(
            '''DELETE FROM Configs WHERE team_id=? and user_id=? and 
            name= ?  ''',
            (team_id, user_id, name))
        self.conn.commit()
        self.insert_log('Deleted "{}" config value'.format(name))
        return

    def insert_template(self, template_id='', team_id='0', user_id='0', name='',
                        filename=''):
        self.execute(
            '''INSERT INTO ReportTemplates(
            `id`,`team_id`,`user_id`,`name`,`filename`) VALUES (?,?,?,?,?)''',
            (template_id, team_id, user_id, name, filename)
        )
        self.conn.commit()
        self.insert_log('Added "{}" report template.'.format(name))

    def select_templates(self, team_id='', user_id='', template_id=''):
        self.execute(
            '''SELECT * FROM ReportTemplates WHERE team_id LIKE '%' || ? || '%'
            and user_id LIKE '%' || ? || '%' and 
            id LIKE '%' || ? || '%' ''',
            (team_id, user_id, template_id))
        result = self.return_arr_dict()
        return result

    def delete_template_safe(self, template_id, team_id='0', user_id='0'):

        template = self.select_templates(template_id=template_id,
                                         team_id=team_id,
                                         user_id=user_id)
        if not template:
            return
        template = template[0]

        remove('./static/files/templates/{}'.format(template['id']))

        self.execute(
            '''DELETE FROM ReportTemplates WHERE id = ?  ''',
            (template['id'],))
        self.conn.commit()
        self.insert_log('Deleted "{}" template'.format(template['name']))
        return

    def select_project_users(self, project_id):
        current_project = self.select_projects(project_id)[0]

        all_user_ids = []

        all_user_ids = json.loads(current_project['testers'])
        teams_ids = json.loads(current_project['teams'])

        teams = [self.select_team_by_id(team_id)[0] for team_id in teams_ids]
        for team in teams:
            all_user_ids += json.loads(team['users'])

        all_user_ids = list(set(all_user_ids))

        all_users = [self.select_user_by_id(x)[0] for x in all_user_ids]

        return all_users

    def select_project_pocs(self, project_id):
        self.execute(
            '''SELECT * FROM PoC WHERE issue_id in 
            (SELECT id FROM Issues WHERE project_id=?)''',
            (project_id,))
        result = self.return_arr_dict()
        return result

    def select_report_info_sorted(self, project_id):

        result = {}
        tmp_result = {}

        # project

        tmp_sql_result = self.select_projects(project_id)
        current_project = tmp_sql_result[0]
        tmp_result['name'] = current_project['name']
        tmp_result['start_date'] = current_project['start_date']
        tmp_result['end_date'] = current_project['end_date']
        result['project'] = tmp_result
        result['project']['testers'] = {}
        tmp_sql_result = self.select_project_users(project_id)
        for user in tmp_sql_result:
            user_obj = {'email': user['email'],
                        'fname': user['fname'],
                        'lname': user['lname']}
            result['project']['testers'][user['id']] = user_obj

        # hostnames

        result['hostnames'] = {}

        self.execute(
            '''SELECT * FROM Hostnames WHERE host_id in 
            (SELECT id FROM Hosts WHERE project_id=?)''',
            (project_id,))
        tmp_sql_result = self.return_arr_dict()
        for hostname in tmp_sql_result:
            hostname_obj = {
                'hostname': hostname['hostname'],
                'comment': hostname['description']
            }
            result['hostnames'][hostname['id']] = hostname_obj

        # port
        result['ports'] = {}
        project_ports = self.select_project_ports(project_id)
        for port in project_ports:
            port_obj = {
                'port': port['port'],
                'is_tcp': bool(port['port']),
                'comment': port['description'],
                'service': port['service']
            }
            result['ports'][port['id']] = port_obj

        # hosts
        result['hosts'] = {}
        project_hosts = self.select_project_hosts(project_id)
        for host in project_hosts:
            host_obj = {
                'hostnames': [x['id'] for x in
                              self.select_ip_hostnames(host['id'])],
                'ports': [x['id'] for x in self.select_host_ports(host['id'])],
                'comment': host['comment'],
                'issues': [x['id'] for x in self.select_host_issues(host['id'])]
            }
            result['hosts'][host['ip']] = host_obj

        # issues
        result['issues'] = {}
        project_issues = self.select_project_issues(project_id)
        for issue in project_issues:
            issue_obj = {
                'name': issue['name'],
                'description': issue['description'],
                'cve': issue['cve'],
                'cwe': issue['cwe'],
                'cvss': issue['cvss'],
                'url_path': issue['url_path'],
                'pocs': [x['id'] for x in self.select_issue_pocs(issue['id'])],
                'status': issue['status'],
                'fix': issue['fix'],
                'type': issue['type'],
                'param': issue['param']
            }

            # criticality
            if issue['cvss'] == 0:
                issue_obj['criticality'] = 'info'
            elif issue['cvss'] <= 3.9:
                issue_obj['criticality'] = 'low'
            elif issue['cvss'] <= 6.9:
                issue_obj['criticality'] = 'medium'
            elif issue['cvss'] <= 8.9:
                issue_obj['criticality'] = 'high'
            else:
                issue_obj['criticality'] = 'critical'

            services = json.loads(issue['services'])

            issue_obj['services'] = {}

            for port_id in services:
                service_obj = {}
                host = self.select_host_by_port_id(port_id)[0]
                service_obj['ip'] = host['ip']
                service_obj['is_ip'] = '0' in services[port_id]
                service_obj['hostnames'] = [x for x in services[port_id]
                                            if x != '0']
                issue_obj['services'][port_id] = service_obj

            result['issues'][issue['id']] = issue_obj

        # pocs

        result['pocs'] = {}

        project_pocs = self.select_project_pocs(project_id)
        for curr_poc in project_pocs:
            poc_obj = {'filename': curr_poc['filename'],
                       'url': '/static/files/poc/' + curr_poc['id'],
                       'comment': curr_poc['description'],
                       'path': '',
                       'services': {},
                       'filetype': curr_poc['type']}

            if curr_poc['port_id'] != '0':
                service_obj = {}
                host = self.select_host_by_port_id(curr_poc['port_id'])[0]
                service_obj['ip'] = host['ip']
                service_obj['is_ip'] = ('0' == curr_poc['hostname_id'])
                service_obj['hostnames'] = []
                if curr_poc['hostname_id'] != '0':
                    service_obj['hostnames'] = [curr_poc['hostname_id']]
                poc_obj['services'][curr_poc['port_id']] = service_obj

            f = open(path.join('./static/files/poc/', curr_poc['id']), 'rb')
            content_b = f.read().decode('charmap')
            f.close()
            poc_obj['content'] = content_b
            poc_obj['content_base64'] = b64encode(content_b.encode("charmap"))
            poc_obj['content_hex'] = content_b.encode("charmap").hex()
            result['pocs'][curr_poc['id']] = poc_obj

        # grouped_issues

        result['grouped_issues'] = {}

        for issue_id in result['issues']:
            if result['issues'][issue_id]['name'] not \
                    in result['grouped_issues']:
                result['grouped_issues'][result['issues'][issue_id]['name']] = \
                    [issue_id]
            else:
                result['grouped_issues'][result['issues'][issue_id]['name']].append(issue_id)

        return result
