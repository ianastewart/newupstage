from django.db import migrations


def create_palette(apps, schema_editor):
    apps.get_model("backstage", "Palette").objects.get_or_create(name="Background 1")


class Migration(migrations.Migration):
    dependencies = [("backstage", "0028_palette")]
    operations = [migrations.RunPython(create_palette, migrations.RunPython.noop)]
