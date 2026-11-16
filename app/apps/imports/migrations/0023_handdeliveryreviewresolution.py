from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0022_alter_offeringpayment_payment_category_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="HandDeliveryReviewResolution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("folder_name", models.CharField(blank=True, max_length=255)),
                ("row_number", models.PositiveIntegerField()),
                (
                    "resolution_kind",
                    models.CharField(
                        choices=[
                            ("replace_head", "戸主差し替え"),
                            ("create_household", "新しい家を作成"),
                        ],
                        max_length=32,
                    ),
                ),
                ("legacy_household_id", models.CharField(blank=True, max_length=255)),
                ("entry_head_name", models.CharField(blank=True, max_length=255)),
                ("target_household_name_snapshot", models.CharField(blank=True, max_length=255)),
                ("editor_label", models.CharField(blank=True, max_length=100)),
                ("note", models.TextField(blank=True)),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="hand_delivery_review_resolutions",
                        to="imports.legacysource",
                    ),
                ),
            ],
            options={
                "ordering": ["source__source_id", "folder_name", "row_number"],
            },
        ),
        migrations.AddConstraint(
            model_name="handdeliveryreviewresolution",
            constraint=models.UniqueConstraint(
                fields=("source", "folder_name", "row_number"),
                name="imports_handdeliveryreviewresolution_unique_row",
            ),
        ),
    ]
