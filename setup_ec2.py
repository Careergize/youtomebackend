"""Initialize a persistent production secret without changing database credentials."""

import secrets
from pathlib import Path

from dotenv import dotenv_values, set_key


def main():
    env_path = Path(__file__).resolve().parent / '.env'
    values = dotenv_values(env_path)
    key = values.get('DJANGO_SECRET_KEY') or ''
    if not key.strip() or key.startswith(('development-only', 'django-insecure-', 'replace-with-')):
        set_key(env_path, 'DJANGO_SECRET_KEY', secrets.token_urlsafe(64))
        print('Saved a generated production secret in .env.')
    else:
        print('Kept the existing secret in .env.')
    env_path.chmod(0o600)
    print('Unset any exported DJANGO_SECRET_KEY, then restart Django.')


if __name__ == '__main__':
    main()
