import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("imports", "0034_person_kana_is_auto_generated"),
    ]

    operations = [
        migrations.CreateModel(
            name="MemoTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("slug", models.SlugField(allow_unicode=True, max_length=64, unique=True)),
                ("label", models.CharField(max_length=64, unique=True)),
                ("description", models.CharField(blank=True, max_length=255)),
                (
                    "origin",
                    models.CharField(
                        choices=[("seed", "初期"), ("ai", "AI"), ("manual", "手動")],
                        default="seed",
                        max_length=16,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "ordering": ["label"],
            },
        ),
        migrations.CreateModel(
            name="MemoTagAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("object_id", models.PositiveBigIntegerField()),
                ("field_name", models.CharField(max_length=64)),
                ("note_type", models.CharField(max_length=64)),
                ("note_label", models.CharField(max_length=100)),
                ("legacy_source_id", models.CharField(blank=True, max_length=100)),
                ("legacy_household_id", models.CharField(blank=True, max_length=255)),
                ("legacy_person_id", models.CharField(blank=True, max_length=255)),
                ("legacy_schedule_id", models.CharField(blank=True, max_length=255)),
                (
                    "source_kind",
                    models.CharField(
                        choices=[("rule", "キーワード"), ("ai", "AI"), ("manual", "手動")],
                        default="rule",
                        max_length=16,
                    ),
                ),
                ("confidence", models.FloatField(blank=True, null=True)),
                ("note_checksum", models.CharField(blank=True, max_length=64)),
                ("note_excerpt", models.CharField(blank=True, max_length=255)),
                (
                    "content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="imports_memo_tag_assignments",
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "tag",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignments",
                        to="imports.memotag",
                    ),
                ),
            ],
            options={
                "ordering": ["tag__label", "note_type", "content_type_id", "object_id", "field_name"],
            },
        ),
        migrations.AddConstraint(
            model_name="memotagassignment",
            constraint=models.UniqueConstraint(
                fields=("tag", "content_type", "object_id", "field_name"),
                name="imports_memotagassignment_unique_tag_target_field",
            ),
        ),
        migrations.AddIndex(
            model_name="memotagassignment",
            index=models.Index(fields=["content_type", "object_id"], name="imports_mem_content_00ef9c_idx"),
        ),
        migrations.AddIndex(
            model_name="memotagassignment",
            index=models.Index(fields=["note_type", "field_name"], name="imports_mem_note_ty_a2388f_idx"),
        ),
        migrations.AddIndex(
            model_name="memotagassignment",
            index=models.Index(fields=["legacy_household_id"], name="imports_mem_legacy__adadc5_idx"),
        ),
        migrations.AddIndex(
            model_name="memotagassignment",
            index=models.Index(fields=["legacy_person_id"], name="imports_mem_legacy__981493_idx"),
        ),
        migrations.AddIndex(
            model_name="memotagassignment",
            index=models.Index(fields=["legacy_schedule_id"], name="imports_mem_legacy__157491_idx"),
        ),
        migrations.AddIndex(
            model_name="memotagassignment",
            index=models.Index(fields=["tag", "source_kind"], name="imports_mem_tag_id_d2a14f_idx"),
        ),
    ]
