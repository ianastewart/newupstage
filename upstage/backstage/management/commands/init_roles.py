import os

from django.conf import settings
from django.core.management.base import BaseCommand
from backstage.init_roles import init_roles


class Command(BaseCommand):
    help = "Initialize Roles"

    def handle(self, *args, **options):
        init_roles()