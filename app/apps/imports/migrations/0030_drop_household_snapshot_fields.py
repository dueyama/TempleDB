from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0029_district_member_sheet_state"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="household",
            name="head_name",
        ),
        migrations.RemoveField(
            model_name="household",
            name="head_name_kana",
        ),
        migrations.RemoveField(
            model_name="householdprofile",
            name="household_name_snapshot",
        ),
        migrations.RemoveField(
            model_name="householdprofile",
            name="household_name_kana_snapshot",
        ),
    ]
