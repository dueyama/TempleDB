from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.db.models import Count
from django.utils import timezone

from apps.imports.models import (
    AnnualMembershipFeePayment,
    DeceasedProfile,
    Household,
    HouseholdProfile,
    OfferingPayment,
    Person,
    ServiceSchedule,
    VisitNote,
)

DEFAULT_SEED = 20260425
DEFAULT_HOUSEHOLDS = 120
MAX_PROFILE_HOUSEHOLDS = 160
MIN_PROFILE_HOUSEHOLDS = 80

SURNAMES = [
    ("青山", "アオヤマ"),
    ("石田", "イシダ"),
    ("上田", "ウエダ"),
    ("遠藤", "エンドウ"),
    ("大橋", "オオハシ"),
    ("加藤", "カトウ"),
    ("川端", "カワバタ"),
    ("北村", "キタムラ"),
    ("小林", "コバヤシ"),
    ("坂井", "サカイ"),
    ("佐伯", "サエキ"),
    ("島田", "シマダ"),
    ("杉本", "スギモト"),
    ("高田", "タカダ"),
    ("田辺", "タナベ"),
    ("中川", "ナカガワ"),
    ("西村", "ニシムラ"),
    ("野口", "ノグチ"),
    ("橋本", "ハシモト"),
    ("藤井", "フジイ"),
    ("前田", "マエダ"),
    ("松井", "マツイ"),
    ("森田", "モリタ"),
    ("山岸", "ヤマギシ"),
    ("吉岡", "ヨシオカ"),
]

MALE_NAMES = [
    ("太郎", "タロウ"),
    ("一郎", "イチロウ"),
    ("正信", "ショウシン"),
    ("隆", "タカシ"),
    ("弘", "ヒロシ"),
    ("誠", "マコト"),
    ("和夫", "カズオ"),
    ("清", "キヨシ"),
    ("健一", "ケンイチ"),
    ("良信", "リョウシン"),
    ("智也", "トモヤ"),
    ("直樹", "ナオキ"),
]

FEMALE_NAMES = [
    ("花子", "ハナコ"),
    ("妙子", "タエコ"),
    ("久美", "クミ"),
    ("和子", "カズコ"),
    ("恵子", "ケイコ"),
    ("美代", "ミヨ"),
    ("幸子", "サチコ"),
    ("節子", "セツコ"),
    ("由美", "ユミ"),
    ("真理", "マリ"),
    ("千代", "チヨ"),
    ("明美", "アケミ"),
]

KAIMYO_PARTS = [
    "正信",
    "妙光",
    "浄心",
    "恵照",
    "法泉",
    "智光",
    "清風",
    "徳雲",
    "照信",
    "慈照",
    "明信",
    "静徳",
]

DEFAULT_DISTRICTS = [
    {"name": "第一地区", "short_name": "一", "sort_order": 10, "weight": 16},
    {"name": "第二地区", "short_name": "二", "sort_order": 20, "weight": 14},
    {"name": "第三地区", "short_name": "三", "sort_order": 30, "weight": 13},
    {"name": "第四地区", "short_name": "四", "sort_order": 40, "weight": 12},
    {"name": "第五地区", "short_name": "五", "sort_order": 50, "weight": 10},
    {"name": "第六地区", "short_name": "六", "sort_order": 60, "weight": 9},
    {"name": "第七地区", "short_name": "七", "sort_order": 70, "weight": 7},
    {"name": "第八地区", "short_name": "八", "sort_order": 80, "weight": 6},
]

DEFAULT_AMOUNT_RANGES = {
    "offering": [10000, 20000, 30000, 50000],
    "eitaikyo": [50000, 100000, 150000, 200000],
    "ozenryo": [5000, 7000, 10000],
    "kurumadai": [3000, 5000, 10000],
    "hanadai": [5000, 10000, 15000],
    "nokotsudan": [50000, 80000, 120000, 150000],
    "other": [3000, 5000, 10000],
}


@dataclass(frozen=True)
class PersonSeed:
    person_id: str
    household_id: str
    surname: str
    surname_kana: str
    given: str
    given_kana: str
    relationship_label: str
    family_category: str
    is_deceased: bool

    @property
    def name(self) -> str:
        return f"{self.surname} {self.given}"

    @property
    def kana(self) -> str:
        return f"{self.surname_kana} {self.given_kana}"


class Command(BaseCommand):
    help = "Generate reusable, realistic synthetic demo JSON from aggregate-only production profile."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--dataset-id", default="synthetic_demo_v1")
        parser.add_argument(
            "--output-dir",
            default="",
            help="Output directory. Defaults to demo/datasets/<dataset-id> under BASE_DIR.",
        )
        parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
        parser.add_argument(
            "--households",
            type=int,
            default=0,
            help="Override generated household count. Defaults to a clamped aggregate profile count.",
        )
        parser.add_argument(
            "--no-db-profile",
            action="store_true",
            help="Use built-in fallback profile instead of reading aggregate counts from the configured DB.",
        )

    def handle(self, *args, **options) -> None:
        del args
        dataset_id = str(options["dataset_id"])
        output_dir = Path(options["output_dir"] or Path(settings.BASE_DIR) / "demo" / "datasets" / dataset_id)
        seed = int(options["seed"])
        profile = self._fallback_profile()
        profile_source = "fallback"
        if not options["no_db_profile"]:
            try:
                profile = self._profile_from_database()
                profile_source = "aggregate_database_profile"
            except DatabaseError as exc:
                self.stderr.write(f"Could not read aggregate profile from DB; using fallback profile: {exc}")

        household_count = int(options["households"] or profile["household_count"])
        household_count = max(20, min(household_count, MAX_PROFILE_HOUSEHOLDS))
        dataset = self._generate_dataset(
            dataset_id=dataset_id,
            seed=seed,
            household_count=household_count,
            profile=profile,
            profile_source=profile_source,
        )
        self._write_dataset(output_dir, dataset)
        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {dataset_id} at {output_dir} "
                f"({len(dataset['households'])} households, {len(dataset['people'])} people)."
            )
        )

    def _profile_from_database(self) -> dict[str, Any]:
        fallback = self._fallback_profile()
        household_count = Household.objects.count()
        if household_count < 20:
            household_count = DEFAULT_HOUSEHOLDS
        else:
            household_count = max(MIN_PROFILE_HOUSEHOLDS, min(household_count, MAX_PROFILE_HOUSEHOLDS))

        district_counts = list(
            HouseholdProfile.objects.exclude(district__isnull=True)
            .values("district__id")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )
        district_weights = [int(row["count"]) for row in district_counts if int(row["count"]) > 0]

        death_years = self._bucket_counts(
            DeceasedProfile.objects.exclude(death_date__isnull=True).values_list("death_date", flat=True),
            lambda value: str(value.year),
        )
        age_buckets = self._bucket_counts(
            DeceasedProfile.objects.exclude(age_at_death__isnull=True).values_list("age_at_death", flat=True),
            self._age_bucket,
        )
        service_months = self._bucket_counts(
            ServiceSchedule.objects.exclude(scheduled_date__isnull=True).values_list("scheduled_date", flat=True),
            lambda value: str(value.month),
        )
        offering_amounts = self._amount_ranges_by_category()
        membership_paid_ratio = self._membership_paid_ratio()

        return {
            "household_count": household_count,
            "district_weights": district_weights or [entry["weight"] for entry in DEFAULT_DISTRICTS],
            "death_year_weights": self._blended_weights(
                death_years,
                fallback["death_year_weights"],
                actual_ratio=0.45,
            ),
            "age_bucket_weights": self._blended_weights(
                age_buckets,
                fallback["age_bucket_weights"],
                actual_ratio=0.30,
            ),
            "service_month_weights": self._blended_weights(
                service_months,
                fallback["service_month_weights"],
                actual_ratio=0.35,
            ),
            "offering_amounts": offering_amounts,
            "membership_paid_ratio": membership_paid_ratio,
            "source_counts": {
                "households": self._safe_count(Household),
                "people": self._safe_count(Person),
                "deceased_profiles": self._safe_count(DeceasedProfile),
                "service_schedules": self._safe_count(ServiceSchedule),
                "offering_payments": self._safe_count(OfferingPayment),
                "visit_notes": self._safe_count(VisitNote),
            },
        }

    def _fallback_profile(self) -> dict[str, Any]:
        return {
            "household_count": DEFAULT_HOUSEHOLDS,
            "district_weights": [entry["weight"] for entry in DEFAULT_DISTRICTS],
            "death_year_weights": {
                str(year): weight
                for year, weight in [
                    (1998, 2),
                    (2001, 3),
                    (2004, 4),
                    (2007, 5),
                    (2010, 6),
                    (2013, 7),
                    (2016, 9),
                    (2019, 10),
                    (2021, 12),
                    (2022, 12),
                    (2023, 13),
                    (2024, 12),
                    (2025, 10),
                    (2026, 5),
                ]
            },
            "age_bucket_weights": {
                "0-49": 2,
                "50-64": 5,
                "65-74": 14,
                "75-84": 32,
                "85-94": 38,
                "95+": 9,
            },
            "service_month_weights": {
                "1": 9,
                "2": 7,
                "3": 12,
                "4": 8,
                "5": 8,
                "6": 7,
                "7": 8,
                "8": 13,
                "9": 12,
                "10": 7,
                "11": 5,
                "12": 9,
            },
            "offering_amounts": dict(DEFAULT_AMOUNT_RANGES),
            "membership_paid_ratio": 0.78,
            "source_counts": {},
        }

    def _generate_dataset(
        self,
        *,
        dataset_id: str,
        seed: int,
        household_count: int,
        profile: dict[str, Any],
        profile_source: str,
    ) -> dict[str, Any]:
        rng = random.Random(seed)
        today = timezone.localdate()
        districts = self._demo_districts(profile)
        households: list[dict[str, Any]] = []
        people: list[dict[str, Any]] = []
        memorials: list[dict[str, Any]] = []
        schedules: list[dict[str, Any]] = []
        payments: list[dict[str, Any]] = []
        visit_notes: list[dict[str, Any]] = []
        membership_payments: list[dict[str, Any]] = []

        current_people: list[PersonSeed] = []
        deceased_people: list[tuple[PersonSeed, date, int, str]] = []

        for index in range(1, household_count + 1):
            surname, surname_kana = SURNAMES[(index - 1) % len(SURNAMES)]
            head_given, head_given_kana = rng.choice(MALE_NAMES if rng.random() < 0.58 else FEMALE_NAMES)
            household_id = f"SD{index:04d}"
            head_id = f"{household_id}-01"
            district = self._weighted_choice(rng, districts, [entry["weight"] for entry in districts])
            household = {
                "household_id": household_id,
                "head_person_id": head_id,
                "head_name": f"{surname} {head_given}",
                "head_kana": f"{surname_kana} {head_given_kana}",
                "postal_code": f"100-{index % 9000:04d}",
                "address_line1": f"東京都千代田区架空町{(index % 12) + 1}-{(index % 20) + 1}",
                "address_line2": "" if index % 5 else f"デモハイツ{100 + index}",
                "phone": f"03-9000-{index % 10000:04d}",
                "ledger_category": "1",
                "delivery_method": self._delivery_method(rng),
                "district": {
                    "name": district["name"],
                    "short_name": district["short_name"],
                    "sort_order": district["sort_order"],
                },
                "notes": self._household_note(rng),
            }
            households.append(household)
            head = PersonSeed(
                person_id=head_id,
                household_id=household_id,
                surname=surname,
                surname_kana=surname_kana,
                given=head_given,
                given_kana=head_given_kana,
                relationship_label="戸主",
                family_category="0",
                is_deceased=False,
            )
            current_people.append(head)
            people.append(self._person_payload(head))

            if rng.random() < 0.72:
                spouse_given, spouse_given_kana = rng.choice(FEMALE_NAMES if head_given in dict(MALE_NAMES) else MALE_NAMES)
                spouse = PersonSeed(
                    person_id=f"{household_id}-02",
                    household_id=household_id,
                    surname=surname,
                    surname_kana=surname_kana,
                    given=spouse_given,
                    given_kana=spouse_given_kana,
                    relationship_label="配偶者",
                    family_category="0",
                    is_deceased=False,
                )
                current_people.append(spouse)
                people.append(self._person_payload(spouse))

            for child_no in range(rng.choice([0, 0, 1, 1, 2])):
                child_given, child_given_kana = rng.choice(MALE_NAMES + FEMALE_NAMES)
                child = PersonSeed(
                    person_id=f"{household_id}-{10 + child_no:02d}",
                    household_id=household_id,
                    surname=surname,
                    surname_kana=surname_kana,
                    given=child_given,
                    given_kana=child_given_kana,
                    relationship_label="子",
                    family_category="0",
                    is_deceased=False,
                )
                current_people.append(child)
                people.append(self._person_payload(child))

            deceased_count = rng.choices([1, 1, 2, 2, 3], weights=[30, 28, 22, 12, 8], k=1)[0]
            for deceased_no in range(deceased_count):
                gender_names = MALE_NAMES if rng.random() < 0.52 else FEMALE_NAMES
                given, given_kana = rng.choice(gender_names)
                person_id = f"{household_id}-{90 + deceased_no:02d}"
                person = PersonSeed(
                    person_id=person_id,
                    household_id=household_id,
                    surname=surname,
                    surname_kana=surname_kana,
                    given=given,
                    given_kana=given_kana,
                    relationship_label=rng.choice(["父", "母", "祖父", "祖母", "先代"]),
                    family_category="1",
                    is_deceased=True,
                )
                death_date = self._sample_death_date(rng, profile)
                age_at_death = self._sample_age_at_death(rng, profile)
                kaimyo = f"釋{rng.choice(KAIMYO_PARTS)}"
                deceased_people.append((person, death_date, age_at_death, kaimyo))
                people.append(self._person_payload(person))
                memorials.append(
                    {
                        "person_id": person.person_id,
                        "death_date": death_date.isoformat(),
                        "kaimyo": kaimyo,
                        "age_at_death": age_at_death,
                    }
                )

        schedule_index = 1
        payment_index = 1
        for person, death_date, _age, _kaimyo in deceased_people:
            anniversary = self._anniversary_label(rng, today.year - death_date.year)
            if anniversary and rng.random() < 0.82:
                scheduled_offset = self._sample_service_offset(rng, profile)
                schedule_id = f"S{schedule_index:05d}"
                schedule_index += 1
                schedules.append(
                    {
                        "schedule_id": schedule_id,
                        "household_id": person.household_id,
                        "person_id": person.person_id,
                        "category": "memorial",
                        "service_label": anniversary,
                        "subject_name": person.name,
                        "target_offset_days": scheduled_offset,
                        "scheduled_offset_days": scheduled_offset + rng.choice([-7, -3, 0, 0, 0, 7]),
                        "scheduled_time": rng.choice(["09:30", "10:00", "11:00", "13:30", "14:00"]),
                        "location": rng.choice(["本堂", "門徒会館", "墓前", "自宅"]),
                        "status": rng.choices(
                            ["scheduled", "completed", "candidate", "deferred"],
                            weights=[42, 36, 15, 7],
                            k=1,
                        )[0],
                        "notes": "架空デモ用の年忌法要予定です。",
                    }
                )
                for payment in self._payments_for_schedule(
                    rng,
                    profile,
                    person=person,
                    schedule_id=schedule_id,
                    payment_index_start=payment_index,
                    received_offset=scheduled_offset - rng.choice([0, 1, 2, 7, 14]),
                ):
                    payments.append(payment)
                    payment_index += 1

            if death_date.year >= today.year - 2 and rng.random() < 0.35:
                schedule_id = f"S{schedule_index:05d}"
                schedule_index += 1
                offset = rng.randint(-90, 120)
                schedules.append(
                    {
                        "schedule_id": schedule_id,
                        "household_id": person.household_id,
                        "person_id": person.person_id,
                        "category": "hatsubon",
                        "service_label": "初盆",
                        "subject_name": person.name,
                        "target_offset_days": offset,
                        "scheduled_offset_days": offset,
                        "scheduled_time": rng.choice(["10:00", "13:30", "14:00"]),
                        "location": rng.choice(["本堂", "自宅"]),
                        "status": rng.choice(["scheduled", "completed"]),
                        "notes": "架空デモ用の初盆予定です。",
                    }
                )

        for household in rng.sample(households, k=max(10, household_count // 5)):
            head_id = household["head_person_id"]
            if rng.random() < 0.45:
                payments.append(
                    self._payment_payload(
                        payment_index,
                        household["household_id"],
                        head_id,
                        "",
                        "eitaikyo",
                        self._sample_amount(rng, profile, "eitaikyo"),
                        rng.randint(-420, 30),
                        "永代経懇志。",
                    )
                )
                payment_index += 1
            if rng.random() < 0.25:
                payments.append(
                    self._payment_payload(
                        payment_index,
                        household["household_id"],
                        head_id,
                        "",
                        "nokotsudan",
                        self._sample_amount(rng, profile, "nokotsudan"),
                        rng.randint(-730, 10),
                        "納骨壇関連の架空入金。",
                    )
                )
                payment_index += 1

        for household in rng.sample(households, k=max(20, household_count // 3)):
            visit_notes.append(
                {
                    "note_id": f"V{len(visit_notes) + 1:05d}",
                    "household_id": household["household_id"],
                    "person_id": household["head_person_id"],
                    "visited_offset_days": rng.randint(-240, 30),
                    "title": rng.choice(["法要日程の相談", "護持会費の確認", "墓参の相談", "近況確認"]),
                    "body": "架空デモ用の訪問メモです。実在の記録ではありません。",
                    "next_action": rng.choice(["前日に電話確認する。", "案内状を送付する。", "次回訪問時に確認する。"]),
                    "author_label": "demo",
                    "pinned_for_household": rng.random() < 0.18,
                }
            )

        paid_ratio = float(profile.get("membership_paid_ratio") or 0.78)
        for year_offset in [-2, -1, 0]:
            for household in households:
                if rng.random() <= paid_ratio - (0.08 if year_offset == 0 else 0):
                    amount = 12000 if rng.random() < 0.92 else rng.choice([6000, 10000, 15000, 24000])
                    membership_payments.append(
                        {
                            "household_id": household["household_id"],
                            "year_offset": year_offset,
                            "received_offset_days": rng.randint(-330, -5) if year_offset == 0 else rng.randint(-700, -40),
                            "amount": str(amount),
                            "is_exception": amount != 12000,
                            "received_by": "demo",
                            "note": "架空デモ用の護持会費入金です。",
                        }
                    )

        profile_summary = self._public_profile_summary(profile, profile_source, household_count, seed)
        return {
            "manifest": {
                "dataset_id": dataset_id,
                "version": 1,
                "source_id": "demo-synthetic-rich",
                "source_label": "TempleDB rich synthetic demo source",
                "source_path": f"demo://{dataset_id}",
                "source_file_name": dataset_id,
                "prepared_snapshot_id": f"{dataset_id}-snapshot",
                "scope": "demo_synthetic_rich",
                "description": "Reusable aggregate-profile synthetic data for portable TempleDB demos. No real names, addresses, notes, or row-level source records are included.",
                "generator_seed": seed,
                "profile_source": profile_source,
            },
            "profile": profile_summary,
            "households": households,
            "people": people,
            "memorials": memorials,
            "service_schedules": schedules,
            "offering_payments": payments,
            "visit_notes": visit_notes,
            "membership_fees": {
                "settings": [
                    {
                        "year_offset": -2,
                        "default_amount": "12000",
                        "note": "架空デモ用の護持会費既定額です。",
                    },
                    {
                        "year_offset": -1,
                        "default_amount": "12000",
                        "note": "架空デモ用の護持会費既定額です。",
                    },
                    {
                        "year_offset": 0,
                        "default_amount": "12000",
                        "note": "架空デモ用の護持会費既定額です。",
                    },
                ],
                "payments": membership_payments,
            },
        }

    def _write_dataset(self, output_dir: Path, dataset: dict[str, Any]) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        files = {
            "manifest.json": dataset["manifest"],
            "profile.json": dataset["profile"],
            "households.json": dataset["households"],
            "people.json": dataset["people"],
            "memorials.json": dataset["memorials"],
            "service_schedules.json": dataset["service_schedules"],
            "offering_payments.json": dataset["offering_payments"],
            "visit_notes.json": dataset["visit_notes"],
            "membership_fees.json": dataset["membership_fees"],
        }
        for filename, payload in files.items():
            (output_dir / filename).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        (output_dir / "README.md").write_text(
            f"# {dataset['manifest']['dataset_id']}\n\n"
            "Aggregate-profile synthetic dataset for TempleDB demos.\n\n"
            "- Generated records are fully fictional.\n"
            "- Real names, addresses, notes, and row-level source records are not copied.\n"
            "- `profile.json` keeps only coarse aggregate hints used for reproducible generation.\n",
            encoding="utf-8",
        )

    def _demo_districts(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        weights = list(profile.get("district_weights") or [])
        if not weights:
            return list(DEFAULT_DISTRICTS)
        count = max(6, min(len(weights), 10))
        districts = []
        for index in range(count):
            base = DEFAULT_DISTRICTS[index % len(DEFAULT_DISTRICTS)]
            districts.append(
                {
                    "name": base["name"],
                    "short_name": base["short_name"],
                    "sort_order": (index + 1) * 10,
                    "weight": int(weights[index]) if index < len(weights) else int(base["weight"]),
                }
            )
        return districts

    def _delivery_method(self, rng: random.Random) -> str:
        return rng.choices(["district", "postal", ""], weights=[68, 26, 6], k=1)[0]

    def _household_note(self, rng: random.Random) -> str:
        return rng.choice(
            [
                "架空デモ用の戸主です。",
                "法要案内は郵送希望という想定です。",
                "地区配布対象の架空戸主です。",
                "会計デモで使う架空戸主です。",
            ]
        )

    def _person_payload(self, person: PersonSeed) -> dict[str, Any]:
        return {
            "person_id": person.person_id,
            "household_id": person.household_id,
            "name": person.name,
            "kana": person.kana,
            "relationship_label": person.relationship_label,
            "family_category": person.family_category,
            "is_deceased": person.is_deceased,
            "person_note": "架空デモ用の人物です。",
        }

    def _sample_death_date(self, rng: random.Random, profile: dict[str, Any]) -> date:
        year_weights = profile.get("death_year_weights") or self._fallback_profile()["death_year_weights"]
        years = [int(year) for year in year_weights.keys()]
        weights = [max(1, int(weight)) for weight in year_weights.values()]
        year = self._weighted_choice(rng, years, weights)
        month = rng.choices(
            list(range(1, 13)),
            weights=[10, 9, 9, 8, 7, 7, 8, 10, 10, 8, 7, 10],
            k=1,
        )[0]
        day = rng.randint(1, 28)
        candidate = date(year, month, day)
        today = timezone.localdate()
        if candidate > today:
            candidate = date(today.year - 1, month, day)
        return candidate

    def _sample_age_at_death(self, rng: random.Random, profile: dict[str, Any]) -> int:
        buckets = profile.get("age_bucket_weights") or self._fallback_profile()["age_bucket_weights"]
        bucket = self._weighted_choice(rng, list(buckets.keys()), [max(1, int(value)) for value in buckets.values()])
        ranges = {
            "0-49": (35, 49),
            "50-64": (50, 64),
            "65-74": (65, 74),
            "75-84": (75, 84),
            "85-94": (85, 94),
            "95+": (95, 102),
        }
        low, high = ranges.get(bucket, (75, 94))
        return rng.randint(low, high)

    def _sample_service_offset(self, rng: random.Random, profile: dict[str, Any]) -> int:
        month_weights = profile.get("service_month_weights") or self._fallback_profile()["service_month_weights"]
        month = int(self._weighted_choice(rng, list(month_weights.keys()), list(month_weights.values())))
        today = timezone.localdate()
        candidates = []
        for year_delta in [-1, 0, 1]:
            candidate = date(today.year + year_delta, month, rng.randint(1, 24))
            offset = (candidate - today).days
            if -420 <= offset <= 220:
                candidates.append(offset)
        return rng.choice(candidates or [rng.randint(-180, 180)])

    def _anniversary_label(self, rng: random.Random, elapsed_years: int) -> str:
        labels = {
            1: "一周忌",
            2: "三回忌",
            6: "七回忌",
            12: "十三回忌",
            16: "十七回忌",
            24: "二十五回忌",
            32: "三十三回忌",
            49: "五十回忌",
        }
        if elapsed_years in labels:
            return labels[elapsed_years]
        if elapsed_years <= 2:
            return rng_label(elapsed_years)
        return rng.choice(["年忌", "祥月命日"])

    def _payments_for_schedule(
        self,
        rng: random.Random,
        profile: dict[str, Any],
        *,
        person: PersonSeed,
        schedule_id: str,
        payment_index_start: int,
        received_offset: int,
    ) -> list[dict[str, Any]]:
        rows = [
            self._payment_payload(
                payment_index_start,
                person.household_id,
                person.person_id,
                schedule_id,
                "offering",
                self._sample_amount(rng, profile, "offering"),
                received_offset,
                "年忌法要のお布施。",
            )
        ]
        index = payment_index_start + 1
        for category, label, probability in [
            ("ozenryo", "お膳料。", 0.45),
            ("kurumadai", "お車代。", 0.28),
            ("hanadai", "お花代。", 0.22),
        ]:
            if rng.random() < probability:
                rows.append(
                    self._payment_payload(
                        index,
                        person.household_id,
                        person.person_id,
                        schedule_id,
                        category,
                        self._sample_amount(rng, profile, category),
                        received_offset,
                        label,
                    )
                )
                index += 1
        return rows

    def _payment_payload(
        self,
        payment_index: int,
        household_id: str,
        person_id: str,
        schedule_id: str,
        category: str,
        amount: int,
        received_offset: int,
        notes: str,
    ) -> dict[str, Any]:
        payload = {
            "payment_id": f"P{payment_index:05d}",
            "household_id": household_id,
            "person_id": person_id,
            "received_offset_days": received_offset,
            "amount": str(amount),
            "payment_category": category,
            "payment_method": "bank_transfer" if category in {"eitaikyo", "nokotsudan"} else "cash",
            "received_by": "demo",
            "notes": notes,
        }
        if schedule_id:
            payload["schedule_id"] = schedule_id
        return payload

    def _sample_amount(self, rng: random.Random, profile: dict[str, Any], category: str) -> int:
        ranges = profile.get("offering_amounts") or DEFAULT_AMOUNT_RANGES
        choices = ranges.get(category) or DEFAULT_AMOUNT_RANGES.get(category) or [5000]
        return int(rng.choice(choices))

    def _amount_ranges_by_category(self) -> dict[str, list[int]]:
        ranges: dict[str, list[int]] = {}
        for category in DEFAULT_AMOUNT_RANGES:
            amounts = [
                self._safe_int_amount(value)
                for value in OfferingPayment.objects.filter(payment_category=category)
                .exclude(amount__isnull=True)
                .values_list("amount", flat=True)[:1000]
            ]
            amounts = [amount for amount in amounts if amount > 0]
            if len(amounts) < 3:
                ranges[category] = DEFAULT_AMOUNT_RANGES[category]
                continue
            rounded = sorted({self._round_amount(amount) for amount in amounts})
            if len(rounded) > 5:
                indexes = [0, len(rounded) // 4, len(rounded) // 2, (len(rounded) * 3) // 4, len(rounded) - 1]
                rounded = [rounded[index] for index in indexes]
            ranges[category] = rounded
        return ranges

    def _membership_paid_ratio(self) -> float:
        rows = AnnualMembershipFeePayment.objects.values("year").annotate(
            count=Count("household_uid")
        )
        counts = [int(row["count"]) for row in rows if int(row["count"]) > 0]
        households = self._safe_count(Household)
        if not counts or households <= 0:
            return 0.78
        ratio = max(counts) / households
        return max(0.45, min(0.92, ratio))

    def _public_profile_summary(
        self,
        profile: dict[str, Any],
        profile_source: str,
        household_count: int,
        seed: int,
    ) -> dict[str, Any]:
        return {
            "profile_source": profile_source,
            "privacy": "aggregate-only; no real names, addresses, row notes, exact source rows, or credentials",
            "generator_seed": seed,
            "generated_household_count": household_count,
            "source_counts_bucketed": {
                key: self._bucket_count(int(value))
                for key, value in (profile.get("source_counts") or {}).items()
            },
            "district_weight_count": len(profile.get("district_weights") or []),
            "age_bucket_weights": profile.get("age_bucket_weights") or {},
            "service_month_weights": profile.get("service_month_weights") or {},
            "membership_paid_ratio": round(float(profile.get("membership_paid_ratio") or 0), 2),
        }

    def _bucket_counts(self, values, key_func) -> dict[str, int]:
        counter: Counter[str] = Counter()
        for value in values:
            if value in (None, ""):
                continue
            counter[key_func(value)] += 1
        return dict(counter)

    def _blended_weights(
        self,
        actual: dict[str, int],
        fallback: dict[str, int],
        *,
        actual_ratio: float,
    ) -> dict[str, int]:
        if not actual:
            return dict(fallback)
        actual_ratio = max(0.0, min(actual_ratio, 1.0))
        keys = list(dict.fromkeys([*fallback.keys(), *actual.keys()]))
        actual_total = sum(max(0, int(value)) for value in actual.values()) or 1
        fallback_total = sum(max(0, int(value)) for value in fallback.values()) or 1
        blended: dict[str, int] = {}
        for key in keys:
            actual_weight = max(0, int(actual.get(key, 0))) / actual_total
            fallback_weight = max(0, int(fallback.get(key, 0))) / fallback_total
            blended[key] = max(
                1,
                int(round((actual_weight * actual_ratio + fallback_weight * (1 - actual_ratio)) * 1000)),
            )
        return blended

    def _age_bucket(self, value: int | str) -> str:
        age = int(value)
        if age < 50:
            return "0-49"
        if age < 65:
            return "50-64"
        if age < 75:
            return "65-74"
        if age < 85:
            return "75-84"
        if age < 95:
            return "85-94"
        return "95+"

    def _safe_count(self, model) -> int:
        try:
            return int(model.objects.count())
        except DatabaseError:
            return 0

    def _safe_int_amount(self, value: Any) -> int:
        try:
            return int(Decimal(value))
        except (InvalidOperation, TypeError, ValueError):
            return 0

    def _round_amount(self, amount: int) -> int:
        if amount < 10000:
            return int(round(amount / 1000) * 1000)
        return int(round(amount / 5000) * 5000)

    def _bucket_count(self, value: int) -> str:
        if value <= 0:
            return "0"
        if value < 50:
            return "1-49"
        if value < 100:
            return "50-99"
        if value < 250:
            return "100-249"
        if value < 500:
            return "250-499"
        if value < 1000:
            return "500-999"
        return "1000+"

    def _weighted_choice(self, rng: random.Random, values: list[Any], weights: list[int]) -> Any:
        if not values:
            raise CommandError("Cannot sample from an empty value list.")
        return rng.choices(values, weights=[max(1, int(weight)) for weight in weights], k=1)[0]


def rng_label(elapsed_years: int) -> str:
    if elapsed_years <= 1:
        return "一周忌"
    return "三回忌"
