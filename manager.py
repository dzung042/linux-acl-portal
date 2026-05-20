from flask import Flask, render_template_string, request, redirect, url_for, flash
import os
import subprocess
import grp
import pwd
from pathlib import Path

from flask import Flask, render_template_string, request, redirect, url_for, flash, session

app = Flask(__name__)
app.secret_key = '123456abc'

# =========================
# Simple Access Gate (Secret Key Login)
# =========================

@app.before_request
def auth_middleware():
    allowed_routes = ['login', 'static']

    if request.endpoint in allowed_routes or request.endpoint is None:
        return

    if not session.get('authenticated'):
        return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        key = request.form.get('key')

        if key == app.secret_key:
            session['authenticated'] = True
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid secret key')

    return '''
    <h2>Enter Access Key</h2>
    <form method="POST">
        <input type="password" name="key" placeholder="Secret key" required>
        <button type="submit">Login</button>
    </form>
    '''


BASE_PROJECT_PATH = '/srv/projects'

# =========================
# Helpers
# =========================

def run_command(cmd):
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=True,
            capture_output=True,
            text=True
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr


def get_linux_users():
    users = []

    for user in pwd.getpwall():
        if user.pw_uid >= 1000 and user.pw_name != 'nobody':
            users.append(user.pw_name)

    return sorted(users)


def create_linux_user(username):
    return run_command(f'id {username} || useradd -m -s /bin/bash {username}')


def create_group(group_name):
    return run_command(f'getent group {group_name} || groupadd {group_name}')


def add_user_to_group(username, group_name):
    return run_command(f'usermod -aG {group_name} {username}')


def remove_acl(path, group_name):
    commands = [
        f'setfacl -x g:{group_name} {path}',
        f'setfacl -d -x g:{group_name} {path}'
    ]

    for cmd in commands:
        run_command(cmd)

    return True, 'ACL removed'


def create_project_folder(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    return True, 'Folder created'


def apply_acl_entry(path, group_name, permission):
    permission_map = {
        'RW': 'rwx',
        'RO': 'rx'
    }

    acl_perm = permission_map.get(permission, permission)

    commands = [
        f'setfacl -R -m g:{group_name}:{acl_perm} {path}',
        f'setfacl -R -d -m g:{group_name}:{acl_perm} {path}',
        f'setfacl -R -m m:{acl_perm} {path}'
    ]

    for cmd in commands:
        ok, out = run_command(cmd)
        if not ok:
            return False, out

    return True, 'ACL Applied'


def get_acl(path):
    ok, out = run_command(f'getfacl -p {path}')
    if ok:
        return out
    return 'ACL not found'


def parse_acl(path):
    acl_output = get_acl(path)

    permissions = []

    for line in acl_output.splitlines():
        line = line.strip()

        if line.startswith('group:'):
            parts = line.split(':')

            if len(parts) >= 3:
                group_name = parts[1]

                # Handle owning group (group::rwx)
                if group_name == '':
                    try:
                        stat_info = os.stat(path)
                        group_name = grp.getgrgid(stat_info.st_gid).gr_name
                    except:
                        group_name = 'unknown'
                perm = parts[2]

                users = []

                try:
                    users = grp.getgrnam(group_name).gr_mem
                except:
                    pass

                permissions.append({
                    'group': group_name,
                    'permission': perm,
                    'users': users
                })

    return permissions


def get_projects():
    projects = []

    os.makedirs(BASE_PROJECT_PATH, exist_ok=True)

    for folder in sorted(os.listdir(BASE_PROJECT_PATH)):
        path = os.path.join(BASE_PROJECT_PATH, folder)

        if os.path.isdir(path):
            projects.append({
                'name': folder,
                'path': path,
                'acl': parse_acl(path)
            })

    return projects


# =========================
# HTML
# =========================

BASE_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Linux ACL Portal</title>
    <style>
        body {
            font-family: Arial;
            margin: 40px;
            background: #f5f5f5;
        }

        .container {
            background: white;
            padding: 20px;
            border-radius: 10px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }

        table, th, td {
            border: 1px solid #ddd;
        }

        th, td {
            padding: 10px;
            text-align: left;
            vertical-align: top;
        }

        input {
            padding: 8px;
            width: 100%;
            margin-top: 5px;
            margin-bottom: 10px;
        }

        button {
            padding: 10px 15px;
            cursor: pointer;
        }

        .menu a {
            margin-right: 20px;
        }

        pre {
            background: #111;
            color: #0f0;
            padding: 15px;
            overflow: auto;
        }
    </style>
</head>
<body>

<div class="menu">
    <a href="/">Dashboard</a>
    <a href="/users">Users</a>
    <a href="/groups">Groups</a>
    <a href="/projects">Projects</a>
</div>

<div class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for msg in messages %}
          <p>{{ msg }}</p>
        {% endfor %}
      {% endif %}
    {% endwith %}

    {{ content|safe }}
</div>

</body>
</html>
'''


# =========================
# Dashboard
# =========================

@app.route('/')
def dashboard():
    users = get_linux_users()
    projects = get_projects()

    content = f'''
    <h1>Linux ACL Management Portal</h1>

    <ul>
        <li>Total Users: {len(users)}</li>
        <li>Total Projects: {len(projects)}</li>
    </ul>
    '''

    return render_template_string(BASE_HTML, content=content)


# =========================
# Users
# =========================

@app.route('/users', methods=['GET', 'POST'])
def users():
    if request.method == 'POST':
        username = request.form['username']

        ok, out = create_linux_user(username)

        if ok:
            flash(f'User {username} created successfully')
        else:
            flash(out)

        return redirect(url_for('users'))

    users_data = get_linux_users()

    rows = ''

    for user in users_data:
        groups = []

        # Secondary groups
        for g in grp.getgrall():
            if user in g.gr_mem:
                groups.append(g.gr_name)

        # Primary group
        try:
            user_info = pwd.getpwnam(user)
            primary_group = grp.getgrgid(user_info.pw_gid).gr_name

            if primary_group not in groups:
                groups.append(primary_group)
        except:
            pass

        rows += f'''
        <tr>
            <td>{user}</td>
            <td>{', '.join(groups)}</td>
        </tr>
        '''

    content = f'''
    <h1>User Management</h1>

    <form method="POST">
        <label>Username</label>
        <input type="text" name="username" required>
        <button type="submit">Create User</button>
    </form>

    <table>
        <tr>
            <th>User</th>
            <th>Groups</th>
        </tr>
        {rows}
    </table>
    '''

    return render_template_string(BASE_HTML, content=content)


# =========================
# Groups
# =========================

@app.route('/groups', methods=['GET', 'POST'])
def groups():
    if request.method == 'POST':
        action = request.form['action']

        if action == 'create_group':
            group_name = request.form['group_name']
            ok, out = create_group(group_name)

            if ok:
                flash(f'Group {group_name} created successfully')
            else:
                flash(out)

        elif action == 'add_user_to_group':
            username = request.form['username']
            group_name = request.form['group_name']

            ok, out = add_user_to_group(username, group_name)

            if ok:
                flash(f'Added {username} to {group_name}')
            else:
                flash(out)

        return redirect(url_for('groups'))

    groups_data = []

    for g in sorted(grp.getgrall(), key=lambda x: x.gr_name):
        if g.gr_gid >= 1000:
            users = list(g.gr_mem)

            # Add primary group members
            for p in pwd.getpwall():
                if p.pw_gid == g.gr_gid and p.pw_name not in users:
                    users.append(p.pw_name)

            groups_data.append({
                'name': g.gr_name,
                'users': sorted(users)
            })

    user_options = ''
    for u in get_linux_users():
        user_options += f'<option value="{u}">{u}</option>'

    group_options = ''
    for g in groups_data:
        group_options += f'<option value="{g["name"]}">{g["name"]}</option>'

    rows = ''

    for g in groups_data:
        rows += f'''
        <tr>
            <td>{g['name']}</td>
            <td>{', '.join(g['users'])}</td>
        </tr>
        '''

    content = f'''
    <h1>Group Management</h1>

    <h3>Create Group</h3>

    <form method="POST">
        <input type="hidden" name="action" value="create_group">

        <label>Group Name</label>
        <input type="text" name="group_name" required>

        <button type="submit">Create Group</button>
    </form>

    <hr>

    <h3>Add User To Group</h3>

    <form method="POST">
        <input type="hidden" name="action" value="add_user_to_group">

        <label>User</label>
        <select name="username">
            {user_options}
        </select>

        <label>Group</label>
        <select name="group_name">
            {group_options}
        </select>

        <button type="submit">Add User</button>
    </form>

    <table>
        <tr>
            <th>Group</th>
            <th>Users</th>
        </tr>
        {rows}
    </table>
    '''

    return render_template_string(BASE_HTML, content=content)


# =========================
# Projects
# =========================

@app.route('/projects', methods=['GET', 'POST'])
def projects():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create_project':
            project_name = request.form['project_name']

            path = f'{BASE_PROJECT_PATH}/{project_name}'

            create_project_folder(path)

            flash(f'Project {project_name} created successfully')

        elif action == 'add_acl':
            project_name = request.form['project_name']
            group_name = request.form['group_name']
            permission = request.form['permission']

            path = f'{BASE_PROJECT_PATH}/{project_name}'

            ok, out = apply_acl_entry(path, group_name, permission)

            if ok:
                flash(f'ACL added: {group_name} -> {permission}')
            else:
                flash(out)

        elif action == 'remove_acl':
            project_name = request.form['project_name']
            group_name = request.form['group_name']

            path = f'{BASE_PROJECT_PATH}/{project_name}'

            ok, out = remove_acl(path, group_name)

            if ok:
                flash(f'ACL removed: {group_name}')
            else:
                flash(out)

        return redirect(url_for('projects'))

    projects_data = get_projects()

    available_groups = []

    for g in sorted(grp.getgrall(), key=lambda x: x.gr_name):
        if g.gr_gid >= 1000:
            available_groups.append(g.gr_name)

    project_options = ''
    for p in projects_data:
        project_options += f'<option value="{p["name"]}">{p["name"]}</option>'

    group_options = ''
    for g in available_groups:
        group_options += f'<option value="{g}">{g}</option>'

    rows = ''

    for p in projects_data:
        acl_html = '<table style="width:100%">'
        acl_html += '<tr><th>Group</th><th>Permission</th><th>Users</th></tr>'

        for acl in p['acl']:
            acl_html += f'''
            <tr>
                <td>
                    {acl['group']}
                    <br><br>
                    <form method="POST">
                        <input type="hidden" name="action" value="remove_acl">
                        <input type="hidden" name="project_name" value="{p['name']}">
                        <input type="hidden" name="group_name" value="{acl['group']}">

                        <button type="submit">Remove ACL</button>
                    </form>
                </td>
                <td>{acl['permission']}</td>
                <td>{', '.join(acl['users'])}</td>
            </tr>
            '''

        acl_html += '</table>'

        rows += f'''
        <tr>
            <td>{p['name']}</td>
            <td>{p['path']}</td>
            <td>{acl_html}</td>
            <td>
                <a href="/project/{p['name']}">View ACL</a>
                <br><br>
                <form method="POST">
                    <input type="hidden" name="action" value="remove_acl">
                    <input type="hidden" name="project_name" value="{p['name']}">

                    <select name="group_name">
                        {''.join([f'<option value="{acl["group"]}">{acl["group"]}</option>' for acl in p['acl']])}
                    </select>

                    <button type="submit">Remove ACL</button>
                </form>
            </td>
        </tr>
        '''

    content = f'''
    <h1>Project Management</h1>

    <h3>Create Project</h3>

    <form method="POST">
        <input type="hidden" name="action" value="create_project">

        <label>Project Name</label>
        <input type="text" name="project_name" required>

        <button type="submit">Create Project</button>
    </form>

    <hr>

    <h3>Attach Group To Project</h3>

    <form method="POST">
        <input type="hidden" name="action" value="add_acl">

        <label>Project</label>
        <select name="project_name">
            {project_options}
        </select>

        <label>Group</label>
        <select name="group_name">
            {group_options}
        </select>

        <label>Permission</label>
        <select name="permission">
            <option value="RW">RW</option>
            <option value="RO">RO</option>
        </select>

        <button type="submit">Apply ACL</button>
    </form>

    <table>
        <tr>
            <th>Project</th>
            <th>Path</th>
            <th>ACL Mapping</th>
            <th>Actions</th>
        </tr>
        {rows}
    </table>
    '''

    return render_template_string(BASE_HTML, content=content)


# =========================
# Project Detail
# =========================

@app.route('/project/<project_name>')
def project_detail(project_name):
    path = f'{BASE_PROJECT_PATH}/{project_name}'

    acl = get_acl(path)

    content = f'''
    <h1>Project ACL</h1>

    <h3>Project</h3>
    <p>{project_name}</p>

    <h3>Path</h3>
    <p>{path}</p>

    <h3>ACL</h3>

    <pre>{acl}</pre>
    '''

    return render_template_string(BASE_HTML, content=content)


# =========================
# Main
# =========================

if __name__ == '__main__':
    os.makedirs(BASE_PROJECT_PATH, exist_ok=True)

    app.run(host='0.0.0.0', port=5000, debug=True)

