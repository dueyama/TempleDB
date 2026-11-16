import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0042_alter_serviceschedule_category"),
    ]

    operations = [
        migrations.CreateModel(
            name="AnnualMembershipFeePostalScan",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("year", models.PositiveIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "未処理"),
                            ("needs_review", "確認待ち"),
                            ("checked", "処理済み"),
                            ("move_error", "移動失敗"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("pdf_storage_key", models.CharField(max_length=500)),
                ("original_filename", models.CharField(max_length=255)),
                ("pdf_sha256", models.CharField(max_length=64)),
                ("pdf_size_bytes", models.PositiveBigIntegerField(default=0)),
                ("crop_storage_key", models.CharField(blank=True, max_length=500)),
                ("crop_sha256", models.CharField(blank=True, max_length=64)),
                ("crop_box", models.JSONField(blank=True, default=dict)),
                ("recognized_text", models.TextField(blank=True)),
                ("candidate_payload", models.JSONField(blank=True, default=dict)),
                ("selected_legacy_household_id", models.CharField(blank=True, max_length=255)),
                ("selected_household_name_snapshot", models.CharField(blank=True, max_length=255)),
                ("confirmed_by", models.CharField(blank=True, max_length=100)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("move_error", models.TextField(blank=True)),
                (
                    "payment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="postal_scans",
                        to="imports.annualmembershipfeepayment",
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="annual_membership_fee_postal_scans",
                        to="imports.legacysource",
                    ),
                ),
            ],
            options={
                "ordering": ["source__source_id", "-year", "status", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="annualmembershipfeepostalscan",
            constraint=models.UniqueConstraint(
                fields=("source", "year", "pdf_sha256"),
                name="imports_annualmembershipfeepostalscan_unique_source_year_pdf",
            ),
        ),
        migrations.AddIndex(
            model_name="annualmembershipfeepostalscan",
            index=models.Index(fields=["source", "year", "status"], name="imports_ann_source__6dac3c_idx"),
        ),
        migrations.AddIndex(
            model_name="annualmembershipfeepostalscan",
            index=models.Index(
                fields=["selected_legacy_household_id", "year"],
                name="imports_ann_selecte_b430f3_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="annualmembershipfeepostalscan",
            index=models.Index(fields=["payment"], name="imports_ann_payment_0c397a_idx"),
        ),
    ]
