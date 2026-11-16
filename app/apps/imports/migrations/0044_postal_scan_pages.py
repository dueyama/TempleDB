from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0043_annualmembershipfeepostalscan"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="annualmembershipfeepostalscan",
            name="imports_annualmembershipfeepostalscan_unique_source_year_pdf",
        ),
        migrations.AddField(
            model_name="annualmembershipfeepostalscan",
            name="page_number",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="annualmembershipfeepostalscan",
            name="page_count",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="annualmembershipfeepostalscan",
            name="page_image_storage_key",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="annualmembershipfeepostalscan",
            name="page_image_sha256",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddConstraint(
            model_name="annualmembershipfeepostalscan",
            constraint=models.UniqueConstraint(
                fields=("source", "year", "pdf_sha256", "page_number"),
                name="imports_annualmembershipfeepostalscan_unique_source_year_pdf_page",
            ),
        ),
        migrations.AddIndex(
            model_name="annualmembershipfeepostalscan",
            index=models.Index(
                fields=["pdf_sha256", "page_number"],
                name="imports_ann_pdf_sha_41f13f_idx",
            ),
        ),
        migrations.AlterModelOptions(
            name="annualmembershipfeepostalscan",
            options={
                "ordering": [
                    "source__source_id",
                    "-year",
                    "status",
                    "original_filename",
                    "page_number",
                    "id",
                ],
            },
        ),
    ]
