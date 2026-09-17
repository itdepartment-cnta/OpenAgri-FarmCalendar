#!/usr/bin/env python3
"""Creates the initial Farm Calendar superuser if none exists.

The password is never hardcoded: it must come from FC_PASSWORD. If it is
missing the script aborts, which stops the container from starting. That is
deliberate — a container that fails to boot is preferable to one running with
a password that is published in the repository.
"""

import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "farm_calendar.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()
username = os.environ.get("FC_USERNAME", "sheepcare")
email = os.environ.get("FC_EMAIL", "sheepcare@sheepcare.local")
password = os.environ.get("FC_PASSWORD")

if User.objects.filter(username=username).exists():
    print(f"User '{username}' already exists")
    sys.exit(0)

if not password:
    sys.exit(
        f"ERROR: FC_PASSWORD is not set and user '{username}' does not exist. "
        "Set FC_PASSWORD in farmcalendar/.env and start again."
    )

User.objects.create_superuser(username, email, password)
print(f"Default user created: {username}")
