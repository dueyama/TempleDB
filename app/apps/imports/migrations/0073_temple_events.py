from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("imports", "0072_annualmembershipfeechecksheetscan")]

    operations = [
        migrations.AddField(
            model_name="serviceschedule",
            name="event_scope",
            field=models.CharField(
                choices=[("household", "家の予定"), ("temple", "寺の予定")],
                db_index=True,
                default="household",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="offeringpayment",
            name="payer_name",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
