from backstage.models import Role

ROLES = [
    "Producer",
    "Director",
    "Writer",
    "Editor",
    "Actor",
    "Stage Manager",
    "Backstage",
    "Costumer",
    "Prop maker",
    "Photographer",
    "Sound",
    "Web admin",
    "Production Manager",
    "Marketing",
]

def init_roles():
    for role in ROLES:
        Role.objects.get_or_create(name=role)