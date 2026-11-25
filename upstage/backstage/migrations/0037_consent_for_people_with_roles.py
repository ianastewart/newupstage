from django.db import migrations


def grant_consent(apps, schema_editor):
    """Everyone who already has at least one role has email and publish consent."""
    Person = apps.get_model("backstage", "Person")
    Person.objects.filter(roles__isnull=False).update(email_consent=True, publish_consent=True)


class Migration(migrations.Migration):

    dependencies = [
        ("backstage", "0036_person_acting_interest_person_backstage_interest_and_more"),
    ]

    operations = [
        # Going back changes nothing: the fields are dropped by the previous migration.
        migrations.RunPython(grant_consent, migrations.RunPython.noop),
    ]
