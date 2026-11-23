from django.contrib.auth.models import Group

from .access import BACKSTAGE_GROUP
from .models import CustomUser


def backstage_user(*args, **kwargs):
    """`CustomUser.objects.create_user`, with the user in the backstage group so the backstage pages open for them."""
    user = CustomUser.objects.create_user(*args, **kwargs)
    user.groups.add(Group.objects.get_or_create(name=BACKSTAGE_GROUP)[0])
    return user
