import django.db.models.deletion
from django.db import migrations, models


def sounds_from_productions(apps, schema_editor):
    """Each production's single sound file becomes a Sound of that production."""
    Production = apps.get_model("backstage", "Production")
    Sound = apps.get_model("backstage", "Sound")
    for production in Production.objects.exclude(sound=""):
        Sound.objects.create(production=production, file=production.sound.name)


def productions_from_sounds(apps, schema_editor):
    """Backwards: a production keeps its first sound."""
    Sound = apps.get_model("backstage", "Sound")
    for sound in Sound.objects.order_by("-uploaded", "-id"):
        sound.production.sound = sound.file.name
        sound.production.save(update_fields=["sound"])


class Migration(migrations.Migration):

    dependencies = [
        ("backstage", "0032_event_listen_url_local"),
    ]

    operations = [
        migrations.CreateModel(
            name="Sound",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to="sounds/")),
                ("uploaded", models.DateTimeField(auto_now_add=True)),
                (
                    "production",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="sounds", to="backstage.production"
                    ),
                ),
            ],
            options={"ordering": ["uploaded", "id"]},
        ),
        migrations.RunPython(sounds_from_productions, productions_from_sounds),
        migrations.RemoveField(model_name="production", name="sound"),
    ]
