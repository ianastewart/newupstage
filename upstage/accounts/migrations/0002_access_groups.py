from django.db import migrations


def create_groups(apps, schema_editor):
    """Create the backstage and sandbox groups, and put the existing staff users in the backstage group."""
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("accounts", "CustomUser")
    backstage, _ = Group.objects.get_or_create(name="backstage")
    Group.objects.get_or_create(name="sandbox")
    for user in User.objects.filter(is_staff=True):
        user.groups.add(backstage)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(create_groups, migrations.RunPython.noop)]
