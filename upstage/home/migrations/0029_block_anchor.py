from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("home", "0028_block_full_width"),
    ]

    operations = [
        migrations.AddField(
            model_name="block",
            name="anchor",
            field=models.SlugField(
                blank=True,
                help_text="Optional. Link to this block from a link or button with #anchor, e.g. #tickets; the page scrolls smoothly to it.",
            ),
        ),
    ]
