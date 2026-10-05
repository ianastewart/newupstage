from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("backstage", "0022_listen_url_to_broadcast_events"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="production",
            name="listen_url",
        ),
    ]
