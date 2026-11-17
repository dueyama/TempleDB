from __future__ import annotations

import json
import shutil
from datetime import date, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.models import DatabaseRuntimeIdentity
from apps.imports.models import (
    AnnualMembershipFeePayment,
    AnnualMembershipFeeSetting,
    DeceasedProfile,
    District,
    ExportSnapshot,
    Household,
    HouseholdProfile,
    ImportBatch,
    LegacySource,
    MemoTagAssignment,
    OfferingPayment,
    Person,
    RecordEditLog,
    ServiceSchedule,
    VisitNote,
)
from apps.imports.source_registry_runtime import export_root


class Command(BaseCommand):
    help = "Load a file-backed synthetic dataset into a disposable TempleDB demo database."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--dataset-id", default="synthetic_demo_v1", help="Dataset directory name.")
        parser.add_argument(
            "--dataset-root",
            default="",
            help="Dataset directory. Defaults to demo/datasets/<dataset-id> under BASE_DIR.",
        )
        parser.add_argument("--username", default="demo", help="Demo admin username.")
        parser.add_argument("--password", default="demo", help="Demo admin password.")
        parser.add_argument("--reference-date", default="", help="Synthetic date basis (YYYY-MM-DD); defaults to today.")
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Allow loading in a disposable test SQLite database outside demo mode. "
                "Product databases remain rejected."
            ),
        )

    def handle(self, *args, **options) -> None:
        del args
        self._guard_disposable_database(force=bool(options["force"]))
        try:
            reference_date = str(options.get("reference_date") or "")
            self.reference_date = date.fromisoformat(reference_date) if reference_date else timezone.localdate()
        except ValueError as exc:
            raise CommandError("reference-date must be YYYY-MM-DD") from exc
        dataset_root = self._resolve_dataset_root(
            dataset_id=str(options["dataset_id"]),
            dataset_root=str(options["dataset_root"] or ""),
        )
        dataset = self._load_dataset(dataset_root)
        manifest = dataset["manifest"]
        source_id = self._required_str(manifest, "source_id", context="manifest")
        prepared_snapshot_id = self._required_str(
            manifest,
            "prepared_snapshot_id",
            context="manifest",
        )

        with transaction.atomic():
            self._mark_demo_runtime()
            self._ensure_demo_user(str(options["username"]), str(options["password"]))
            self._reset_source(source_id)
            source = self._create_source(manifest)
            export_snapshot = self._create_export_snapshot(source, manifest)
            batch = self._create_batch(source, manifest, export_snapshot)
            districts = self._create_districts(dataset["households"])
            households, people = self._create_households_and_people(
                source=source,
                batch=batch,
                households_payload=dataset["households"],
                people_payload=dataset["people"],
                districts=districts,
                prepared_snapshot_id=prepared_snapshot_id,
            )
            self._create_memorials(dataset["memorials"], people)
            schedules = self._create_service_schedules(
                batch=batch,
                schedules_payload=dataset["service_schedules"],
                households=households,
                people=people,
            )
            self._create_offering_payments(
                batch=batch,
                payments_payload=dataset["offering_payments"],
                households=households,
                people=people,
                schedules=schedules,
                source_id=source_id,
            )
            self._create_visit_notes(
                batch=batch,
                notes_payload=dataset["visit_notes"],
                households=households,
                people=people,
                schedules=schedules,
                source_id=source_id,
            )
            self._create_membership_fees(
                source=source,
                payload=dataset["membership_fees"],
                households=households,
            )
            self._create_history_seed(source_id=source_id, households=households)
            self._update_batch_counts(batch=batch, households=households, people=people)

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded demo dataset {manifest.get('dataset_id', dataset_root.name)!r}. "
                f"Login with {options['username']}/{options['password']}."
            )
        )

    def _guard_disposable_database(self, *, force: bool) -> None:
        engine = settings.DATABASES["default"]["ENGINE"]
        if engine == "django.db.backends.postgresql":
            if not (
                getattr(settings, "TEMPLEDB_DEMO_MODE", False)
                and getattr(settings, "TEMPLEDB_POSTGRESQL_DEMO_MODE", False)
            ):
                raise CommandError("load_demo_dataset refuses to modify a PostgreSQL database.")
            try:
                identity = DatabaseRuntimeIdentity.objects.get(singleton_key=1)
            except DatabaseRuntimeIdentity.DoesNotExist as exc:
                raise CommandError(
                    "PostgreSQL demo runtime identity is missing."
                ) from exc
            if identity.runtime_kind != "demo":
                raise CommandError("PostgreSQL demo runtime identity must be demo.")
            return
        if engine != "django.db.backends.sqlite3":
            raise CommandError("load_demo_dataset refuses to modify a PostgreSQL database.")
        if getattr(settings, "TEMPLEDB_PRODUCT_SQLITE_MODE", False):
            raise CommandError("load_demo_dataset refuses to modify a product SQLite database.")
        if not force and not getattr(settings, "TEMPLEDB_DEMO_MODE", False):
            raise CommandError("load_demo_dataset requires TEMPLEDB_DEMO_MODE=1.")

    def _resolve_dataset_root(self, *, dataset_id: str, dataset_root: str) -> Path:
        if dataset_root:
            path = Path(dataset_root)
        else:
            path = Path(settings.BASE_DIR) / "demo" / "datasets" / dataset_id
        if not path.exists():
            raise CommandError(f"Demo dataset directory not found: {path}")
        if not path.is_dir():
            raise CommandError(f"Demo dataset path is not a directory: {path}")
        return path

    def _load_dataset(self, dataset_root: Path) -> dict[str, Any]:
        files = {
            "manifest": "manifest.json",
            "households": "households.json",
            "people": "people.json",
            "memorials": "memorials.json",
            "service_schedules": "service_schedules.json",
            "offering_payments": "offering_payments.json",
            "visit_notes": "visit_notes.json",
            "membership_fees": "membership_fees.json",
        }
        dataset = {key: self._read_json(dataset_root / filename) for key, filename in files.items()}
        for key in [
            "households",
            "people",
            "memorials",
            "service_schedules",
            "offering_payments",
            "visit_notes",
        ]:
            if not isinstance(dataset[key], list):
                raise CommandError(f"{files[key]} must contain a JSON array.")
        if not isinstance(dataset["manifest"], dict):
            raise CommandError("manifest.json must contain a JSON object.")
        if not isinstance(dataset["membership_fees"], dict):
            raise CommandError("membership_fees.json must contain a JSON object.")
        return dataset

    def _read_json(self, path: Path) -> Any:
        if not path.exists():
            raise CommandError(f"Required demo dataset file is missing: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON in {path}: {exc}") from exc

    def _ensure_demo_user(self, username: str, password: str) -> None:
        User = get_user_model()
        user, _created = User.objects.get_or_create(username=username)
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save(update_fields=["is_staff", "is_superuser", "password"])

    def _mark_demo_runtime(self) -> None:
        if not getattr(settings, "TEMPLEDB_DEMO_MODE", False):
            return
        identity, _created = DatabaseRuntimeIdentity.objects.get_or_create(singleton_key=1)
        if identity.runtime_kind != "demo":
            identity.runtime_kind = "demo"
            identity.save(update_fields=["runtime_kind", "updated_at"])

    def _reset_source(self, source_id: str) -> None:
        source = LegacySource.objects.filter(source_id=source_id).first()
        if source is None:
            return
        batch_ids = list(ImportBatch.objects.filter(source=source).values_list("id", flat=True))
        ServiceSchedule.objects.filter(related_batch_id__in=batch_ids).delete()
        ServiceSchedule.objects.filter(legacy_source_id=source_id).delete()
        OfferingPayment.objects.filter(related_batch_id__in=batch_ids).delete()
        OfferingPayment.objects.filter(legacy_source_id=source_id).delete()
        VisitNote.objects.filter(related_batch_id__in=batch_ids).delete()
        VisitNote.objects.filter(legacy_source_id=source_id).delete()
        AnnualMembershipFeePayment.objects.filter(source=source).delete()
        AnnualMembershipFeeSetting.objects.filter(source=source).delete()
        HouseholdProfile.objects.filter(source=source).delete()
        RecordEditLog.objects.filter(legacy_source_id=source_id).delete()
        MemoTagAssignment.objects.filter(legacy_source_id=source_id).delete()
        DeceasedProfile.objects.filter(person__batch_id__in=batch_ids).delete()
        Person.objects.filter(batch_id__in=batch_ids).delete()
        Household.objects.filter(batch_id__in=batch_ids).delete()
        ImportBatch.objects.filter(id__in=batch_ids).delete()
        source.delete()
        self._remove_export_marker_files(source_id)

    def _create_source(self, manifest: dict[str, Any]) -> LegacySource:
        source_id = self._required_str(manifest, "source_id", context="manifest")
        LegacySource.objects.filter(is_primary=True).exclude(source_id=source_id).update(is_primary=False)
        return LegacySource.objects.create(
            source_id=source_id,
            label=str(manifest.get("source_label") or "TempleDB demo synthetic source"),
            file_path=str(manifest.get("source_path") or "demo://synthetic"),
            file_name=str(manifest.get("source_file_name") or "synthetic-demo"),
            status="primary",
            notes=str(manifest.get("description") or "Synthetic demo data."),
            is_primary=True,
        )

    def _create_export_snapshot(
        self,
        source: LegacySource,
        manifest: dict[str, Any],
    ) -> ExportSnapshot:
        snapshot_id = self._required_str(manifest, "prepared_snapshot_id", context="manifest")
        root = export_root(source.source_id)
        snapshot_dir = root / snapshot_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        export_manifest = {
            "snapshot": {
                "snapshot_id": snapshot_id,
                "source_id": source.source_id,
                "created_at": timezone.now().isoformat(),
            },
            "export_settings": {
                "table_count": 8,
                "adapter_key": "demo-synthetic",
                "dataset_id": manifest.get("dataset_id", ""),
            },
            "demo": {
                "file_backed_dataset": True,
                "dataset_version": manifest.get("version", ""),
            },
        }
        manifest_path = snapshot_dir / "manifest.json"
        log_path = snapshot_dir / "export.log"
        latest_path = root / "latest.json"
        manifest_path.write_text(
            json.dumps(export_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        log_path.write_text("Synthetic demo export marker.\n", encoding="utf-8")
        latest_path.write_text(
            json.dumps({"latest_snapshot_id": snapshot_id}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return ExportSnapshot.objects.create(
            source=source,
            snapshot_id=snapshot_id,
            export_dir=str(snapshot_dir),
            manifest_path=str(manifest_path),
            log_path=str(log_path),
            table_count=8,
            manifest=export_manifest,
        )

    def _remove_export_marker_files(self, source_id: str) -> None:
        root = export_root(source_id)
        if not root.exists():
            return
        shutil.rmtree(root)

    def _create_batch(
        self,
        source: LegacySource,
        manifest: dict[str, Any],
        export_snapshot: ExportSnapshot,
    ) -> ImportBatch:
        now = timezone.now()
        batch = ImportBatch.objects.create(
            source=source,
            export_snapshot=export_snapshot,
            scope=str(manifest.get("scope") or "demo_synthetic"),
            mode=ImportBatch.Mode.REHEARSAL,
            status=ImportBatch.Status.SUCCEEDED,
            prepared_snapshot_id=self._required_str(
                manifest,
                "prepared_snapshot_id",
                context="manifest",
            ),
            started_at=now,
            finished_at=now,
            summary={
                "dataset_id": manifest.get("dataset_id", ""),
                "dataset_version": manifest.get("version", ""),
            },
            notes="Synthetic demo seed batch.",
        )
        return batch

    def _create_districts(self, households_payload: list[dict[str, Any]]) -> dict[str, District]:
        districts: dict[str, District] = {}
        for household in households_payload:
            district_payload = household.get("district") or {}
            if not isinstance(district_payload, dict):
                raise CommandError("household.district must be an object.")
            district_name = self._required_str(district_payload, "name", context="household.district")
            if district_name in districts:
                continue
            district, _created = District.objects.update_or_create(
                name=district_name,
                defaults={
                    "short_name": str(district_payload.get("short_name") or district_name),
                    "sort_order": int(district_payload.get("sort_order") or 100),
                    "is_active": True,
                },
            )
            districts[district_name] = district
        return districts

    def _create_households_and_people(
        self,
        *,
        source: LegacySource,
        batch: ImportBatch,
        households_payload: list[dict[str, Any]],
        people_payload: list[dict[str, Any]],
        districts: dict[str, District],
        prepared_snapshot_id: str,
    ) -> tuple[dict[str, Household], dict[str, Person]]:
        households: dict[str, Household] = {}
        for row_number, payload in enumerate(households_payload, start=1):
            household_id = self._required_str(payload, "household_id", context="households")
            head_name = self._required_str(payload, "head_name", context=f"household {household_id}")
            head_kana = str(payload.get("head_kana") or "")
            household = Household.objects.create(
                batch=batch,
                legacy_source_id=source.source_id,
                source_mdb_file=source.file_path,
                source_export_batch=prepared_snapshot_id,
                source_table="demo_households",
                source_row_number=row_number,
                legacy_pk_text=household_id,
                household_uid=household_id,
                postal_code=str(payload.get("postal_code") or ""),
                address_line1=str(payload.get("address_line1") or ""),
                address_line2=str(payload.get("address_line2") or ""),
                address_line3=str(payload.get("address_line3") or ""),
                phone=str(payload.get("phone") or ""),
                ledger_category=str(payload.get("ledger_category") or ""),
                notes=str(payload.get("notes") or ""),
                raw_record={"氏名": head_name, "ﾌﾘｶﾞﾅ": head_kana},
            )
            district_name = self._required_str(
                payload.get("district") or {},
                "name",
                context=f"household {household_id}.district",
            )
            HouseholdProfile.objects.create(
                source=source,
                household_uid=household_id,
                delivery_method=str(payload.get("delivery_method") or ""),
                district=districts[district_name],
                mailing_name=str(payload.get("mailing_name") or head_name),
                mailing_postal_code=str(payload.get("postal_code") or ""),
                mailing_address_line1=str(payload.get("address_line1") or ""),
                mailing_phone=str(payload.get("phone") or ""),
            )
            households[household_id] = household

        people: dict[str, Person] = {}
        for row_number, payload in enumerate(people_payload, start=1):
            person_id = self._required_str(payload, "person_id", context="people")
            household_id = self._required_str(payload, "household_id", context=f"person {person_id}")
            household = self._lookup(households, household_id, "household")
            person = Person.objects.create(
                batch=batch,
                household=household,
                legacy_source_id=source.source_id,
                source_mdb_file=source.file_path,
                source_export_batch=prepared_snapshot_id,
                source_table="demo_people",
                source_row_number=row_number,
                legacy_pk_text=person_id,
                person_uid=person_id,
                legacy_household_id=household_id,
                name=str(payload.get("name") or ""),
                kana=str(payload.get("kana") or ""),
                relationship_label=str(payload.get("relationship_label") or ""),
                family_category=str(payload.get("family_category") or ""),
                is_deceased=bool(payload.get("is_deceased") or False),
                person_note=str(payload.get("person_note") or ""),
                raw_record={
                    "氏名": str(payload.get("name") or ""),
                    "ﾌﾘｶﾞﾅ": str(payload.get("kana") or ""),
                },
            )
            people[person_id] = person

        head_ids = {
            self._required_str(payload, "household_id", context="households"): self._required_str(
                payload,
                "head_person_id",
                context="households",
            )
            for payload in households_payload
        }
        for household_id, head_person_id in head_ids.items():
            household = households[household_id]
            household.head_person = self._lookup(people, head_person_id, "person")
            household.save(update_fields=["head_person"])
        return households, people

    def _create_memorials(self, memorials_payload: list[dict[str, Any]], people: dict[str, Person]) -> None:
        for payload in memorials_payload:
            person_id = self._required_str(payload, "person_id", context="memorials")
            person = self._lookup(people, person_id, "person")
            death_date = self._payload_date(payload, "death_date", "death_offset_days")
            kaimyo = str(payload.get("kaimyo") or "")
            age_at_death = payload.get("age_at_death")
            person.is_deceased = True
            person.death_date = death_date
            person.death_date_raw = death_date.isoformat() if death_date else ""
            person.kaimyo = kaimyo
            person.age_at_death = int(age_at_death) if age_at_death not in (None, "") else None
            person.age_at_death_raw = str(age_at_death or "")
            person.save(
                update_fields=[
                    "is_deceased",
                    "death_date",
                    "death_date_raw",
                    "kaimyo",
                    "age_at_death",
                    "age_at_death_raw",
                ]
            )
            DeceasedProfile.objects.create(
                person=person,
                death_date=death_date,
                death_date_raw=death_date.isoformat() if death_date else "",
                kaimyo=kaimyo,
                age_at_death=person.age_at_death,
                age_at_death_raw=person.age_at_death_raw,
                memorial_payload=dict(payload),
            )

    def _create_service_schedules(
        self,
        *,
        batch: ImportBatch,
        schedules_payload: list[dict[str, Any]],
        households: dict[str, Household],
        people: dict[str, Person],
    ) -> dict[str, ServiceSchedule]:
        schedules: dict[str, ServiceSchedule] = {}
        for payload in schedules_payload:
            schedule_id = self._required_str(payload, "schedule_id", context="service_schedules")
            household_id = self._required_str(
                payload,
                "household_id",
                context=f"schedule {schedule_id}",
            )
            person_id = str(payload.get("person_id") or "")
            household = self._lookup(households, household_id, "household")
            person = self._lookup(people, person_id, "person") if person_id else None
            head_person = household.head_person
            schedule = ServiceSchedule.objects.create(
                related_batch=batch,
                household=household,
                person=person,
                legacy_source_id=batch.source.source_id,
                household_uid=household_id,
                person_uid=person.person_uid if person else "",
                household_name_snapshot=head_person.name if head_person else household_id,
                person_name_snapshot=person.name if person else "",
                record_origin=ServiceSchedule.Origin.MANUAL,
                source_table="demo_service_schedules",
                legacy_pk_text=schedule_id,
                schedule_uid=schedule_id,
                category=str(payload.get("category") or ServiceSchedule.Category.MEMORIAL),
                service_label=str(payload.get("service_label") or ""),
                subject_name=str(payload.get("subject_name") or ""),
                target_date=self._payload_date(payload, "target_date", "target_offset_days"),
                scheduled_date=self._payload_date(payload, "scheduled_date", "scheduled_offset_days"),
                scheduled_time=self._payload_time(payload.get("scheduled_time")),
                location=str(payload.get("location") or ""),
                status=str(payload.get("status") or ServiceSchedule.Status.SCHEDULED),
                notes=str(payload.get("notes") or ""),
                is_demo_data=True,
            )
            schedules[schedule_id] = schedule
        return schedules

    def _create_offering_payments(
        self,
        *,
        batch: ImportBatch,
        payments_payload: list[dict[str, Any]],
        households: dict[str, Household],
        people: dict[str, Person],
        schedules: dict[str, ServiceSchedule],
        source_id: str,
    ) -> None:
        for payload in payments_payload:
            household_id = self._required_str(payload, "household_id", context="offering_payments")
            person_id = str(payload.get("person_id") or "")
            schedule_id = str(payload.get("schedule_id") or "")
            household = self._lookup(households, household_id, "household")
            person = self._lookup(people, person_id, "person") if person_id else None
            schedule = self._lookup(schedules, schedule_id, "schedule") if schedule_id else None
            head_person = household.head_person
            OfferingPayment.objects.create(
                related_batch=batch,
                household=household,
                person=person,
                service_schedule=schedule,
                legacy_source_id=source_id,
                household_uid=household_id,
                person_uid=person.person_uid if person else "",
                household_name_snapshot=head_person.name if head_person else household_id,
                person_name_snapshot=person.name if person else "",
                received_on=self._payload_date(payload, "received_on", "received_offset_days")
                or self.reference_date,
                amount=Decimal(str(payload.get("amount") or "0")),
                payment_category=str(payload.get("payment_category") or OfferingPayment.Category.OFFERING),
                payment_method=str(payload.get("payment_method") or OfferingPayment.Method.CASH),
                received_by=str(payload.get("received_by") or ""),
                notes=str(payload.get("notes") or ""),
                is_demo_data=True,
            )

    def _create_visit_notes(
        self,
        *,
        batch: ImportBatch,
        notes_payload: list[dict[str, Any]],
        households: dict[str, Household],
        people: dict[str, Person],
        schedules: dict[str, ServiceSchedule],
        source_id: str,
    ) -> None:
        for payload in notes_payload:
            household_id = self._required_str(payload, "household_id", context="visit_notes")
            person_id = str(payload.get("person_id") or "")
            schedule_id = str(payload.get("schedule_id") or "")
            household = self._lookup(households, household_id, "household")
            person = self._lookup(people, person_id, "person") if person_id else household.head_person
            schedule = self._lookup(schedules, schedule_id, "schedule") if schedule_id else None
            head_person = household.head_person
            VisitNote.objects.create(
                related_batch=batch,
                household=household,
                person=person,
                service_schedule=schedule,
                legacy_source_id=source_id,
                household_uid=household_id,
                person_uid=person.person_uid if person else "",
                household_name_snapshot=head_person.name if head_person else household_id,
                person_name_snapshot=person.name if person else "",
                visited_on=self._payload_date(payload, "visited_on", "visited_offset_days")
                or self.reference_date,
                title=str(payload.get("title") or ""),
                body=str(payload.get("body") or ""),
                next_action=str(payload.get("next_action") or ""),
                author_label=str(payload.get("author_label") or "demo"),
                pinned_for_household=bool(payload.get("pinned_for_household") or False),
                is_demo_data=True,
            )

    def _create_membership_fees(
        self,
        *,
        source: LegacySource,
        payload: dict[str, Any],
        households: dict[str, Household],
    ) -> None:
        current_year = self.reference_date.year
        for setting in payload.get("settings") or []:
            year = int(setting.get("year") or current_year + int(setting.get("year_offset") or 0))
            AnnualMembershipFeeSetting.objects.create(
                source=source,
                year=year,
                default_amount=Decimal(str(setting.get("default_amount") or "0")),
                note=str(setting.get("note") or ""),
            )
        for payment in payload.get("payments") or []:
            household_id = self._required_str(payment, "household_id", context="membership_fees.payments")
            household = self._lookup(households, household_id, "household")
            head_person = household.head_person
            profile = HouseholdProfile.objects.filter(
                source=source,
                household_uid=household_id,
            ).select_related("district").first()
            year = int(payment.get("year") or current_year + int(payment.get("year_offset") or 0))
            AnnualMembershipFeePayment.objects.create(
                source=source,
                household_uid=household_id,
                household_name_snapshot=head_person.name if head_person else household_id,
                delivery_method_snapshot=profile.delivery_method if profile else "",
                district_name_snapshot=profile.district.name if profile and profile.district else "",
                year=year,
                received_on=self._payload_date(payment, "received_on", "received_offset_days")
                or self.reference_date,
                amount=Decimal(str(payment.get("amount") or "0")),
                is_exception=bool(payment.get("is_exception") or False),
                received_by=str(payment.get("received_by") or ""),
                note=str(payment.get("note") or ""),
            )

    def _create_history_seed(self, *, source_id: str, households: dict[str, Household]) -> None:
        first_household = next(iter(households.values()), None)
        if first_household is None:
            return
        RecordEditLog.objects.create(
            record_type=RecordEditLog.RecordType.HOUSEHOLD,
            action_kind=RecordEditLog.ActionKind.UPDATE,
            record_id=first_household.id,
            legacy_source_id=source_id,
            legacy_household_id=first_household.household_uid,
            record_label=first_household.display_head_name(),
            changed_fields=["notes"],
            before_data={"notes": ""},
            after_data={"notes": first_household.notes},
            editor_label="demo",
            change_note="Synthetic demo seed history.",
        )

    def _update_batch_counts(
        self,
        *,
        batch: ImportBatch,
        households: dict[str, Household],
        people: dict[str, Person],
    ) -> None:
        batch.records_read = len(households) + len(people)
        batch.households_imported = len(households)
        batch.persons_imported = len(people)
        batch.deceased_profiles_imported = DeceasedProfile.objects.filter(
            person__batch=batch,
        ).count()
        batch.service_schedules_imported = ServiceSchedule.objects.filter(related_batch=batch).count()
        batch.save(
            update_fields=[
                "records_read",
                "households_imported",
                "persons_imported",
                "deceased_profiles_imported",
                "service_schedules_imported",
            ]
        )

    def _payload_date(
        self,
        payload: dict[str, Any],
        date_key: str,
        offset_key: str,
    ) -> date | None:
        if payload.get(date_key):
            return date.fromisoformat(str(payload[date_key]))
        if payload.get(offset_key) not in (None, ""):
            return self.reference_date + timedelta(days=int(payload[offset_key]))
        return None

    def _payload_time(self, value: Any) -> time | None:
        if not value:
            return None
        return time.fromisoformat(str(value))

    def _required_str(self, payload: dict[str, Any], key: str, *, context: str) -> str:
        value = payload.get(key)
        if value is None or str(value).strip() == "":
            raise CommandError(f"Missing required {context}.{key}.")
        return str(value).strip()

    def _lookup(self, mapping: dict[str, Any], key: str, label: str) -> Any:
        try:
            return mapping[key]
        except KeyError as exc:
            raise CommandError(f"Unknown demo {label}: {key}") from exc
