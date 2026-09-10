# MIRA su PythonAnywhere con Git e SQLite

## 1. Scaricare il codice

Creare un repository GitHub privato e, nella console Bash di PythonAnywhere:

```bash
git clone URL_REPOSITORY ~/MIRA
cd ~/MIRA
```

## 2. Ambiente Python

```bash
python3.13 -m venv ~/.virtualenvs/mira
source ~/.virtualenvs/mira/bin/activate
pip install --upgrade pip
pip install -r requirements-pythonanywhere.txt
```

## 3. Configurazione privata

Creare `/home/USERNAME/MIRA/.env`:

```text
MIRA_DEBUG=0
MIRA_SECRET_KEY=CHIAVE_CASUALE
MIRA_ALLOWED_HOSTS=USERNAME.pythonanywhere.com
MIRA_CSRF_TRUSTED_ORIGINS=https://USERNAME.pythonanywhere.com
MIRA_DB_ENGINE=sqlite
MIRA_DB_NAME=db.sqlite3
```

Per il sistema europeo usare `USERNAME.eu.pythonanywhere.com`. Generare la chiave con:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## 4. Database e file statici

```bash
cd ~/MIRA
source ~/.virtualenvs/mira/bin/activate
python manage.py migrate
python manage.py bootstrap_roles
python manage.py createsuperuser
python manage.py collectstatic --noinput
python manage.py check
```

## 5. Web App

Creare una Web App con **Manual configuration** e Python 3.13.

- Source code: `/home/USERNAME/MIRA`
- Working directory: `/home/USERNAME/MIRA`
- Virtualenv: `/home/USERNAME/.virtualenvs/mira`
- Static URL: `/static/`
- Static directory: `/home/USERNAME/MIRA/staticfiles`

Nel file WSGI indicato dalla scheda Web usare il contenuto di `deploy/pythonanywhere_wsgi.py.example`, sostituendo `USERNAME`, quindi premere **Reload**.

## Aggiornamenti successivi

```bash
cd ~/MIRA
git pull
source ~/.virtualenvs/mira/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
```

Infine premere **Reload** nella scheda Web.
