from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="order_details",
            field=models.JSONField(default=dict),
        ),
    ]
