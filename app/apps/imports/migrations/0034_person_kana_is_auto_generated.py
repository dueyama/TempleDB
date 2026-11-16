from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0033_householdprofile_general_notice_opt_out"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="kana_is_auto_generated",
            field=models.BooleanField(default=False),
        ),
    ]
