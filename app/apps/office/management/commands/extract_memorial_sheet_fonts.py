from __future__ import annotations

from pathlib import Path
from struct import unpack_from

from django.core.management.base import BaseCommand, CommandError

from apps.office.services.memorial_sheet_web_fonts import (
    MEMORIAL_SHEET_WEB_FONTS,
    MemorialSheetWebFont,
    memorial_sheet_private_font_dir,
)


def _resource_fork_path(path: Path) -> Path:
    return path / "..namedfork" / "rsrc"


def _extract_sfnt_payload(resource_fork: Path, resource_id: int) -> bytes:
    data = resource_fork.read_bytes()
    if len(data) < 16:
        raise CommandError(f"resource fork is too short: {resource_fork}")
    data_offset, map_offset, _data_length, map_length = unpack_from(">IIII", data, 0)
    resource_map = data[map_offset : map_offset + map_length]
    if len(resource_map) < 28:
        raise CommandError(f"resource map is too short: {resource_fork}")

    type_list_offset = unpack_from(">H", resource_map, 24)[0]
    type_count = unpack_from(">H", resource_map, type_list_offset)[0] + 1
    type_pos = type_list_offset + 2
    for _index in range(type_count):
        resource_type = resource_map[type_pos : type_pos + 4]
        resource_count = unpack_from(">H", resource_map, type_pos + 4)[0] + 1
        ref_offset = unpack_from(">H", resource_map, type_pos + 6)[0]
        if resource_type == b"sfnt":
            ref_base = type_list_offset + ref_offset
            for ref_index in range(resource_count):
                entry = ref_base + (ref_index * 12)
                current_resource_id = unpack_from(">h", resource_map, entry)[0]
                if current_resource_id != resource_id:
                    continue
                font_data_offset = int.from_bytes(resource_map[entry + 5 : entry + 8], "big")
                font_length = unpack_from(">I", data, data_offset + font_data_offset)[0]
                payload_start = data_offset + font_data_offset + 4
                payload_end = payload_start + font_length
                payload = data[payload_start:payload_end]
                if payload[:4] not in {b"\x00\x01\x00\x00", b"OTTO", b"true"}:
                    raise CommandError(
                        f"sfnt resource {resource_id} is not TrueType/OpenType data: {resource_fork}"
                    )
                return payload
        type_pos += 8
    raise CommandError(f"sfnt resource {resource_id} was not found: {resource_fork}")


class Command(BaseCommand):
    help = "Extract memorial sheet fonts from old Mac resource-fork fonts into private runtime TTF files."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source-dir",
            default=str(Path.home() / "Library" / "Fonts"),
            help="Directory containing the original Mac resource-fork font files.",
        )
        parser.add_argument(
            "--font",
            action="append",
            choices=sorted(MEMORIAL_SHEET_WEB_FONTS),
            help="Font slug to extract. Defaults to all known memorial sheet fonts.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing private runtime font files.",
        )

    def handle(self, *args, **options) -> None:
        source_dir = Path(options["source_dir"]).expanduser()
        font_slugs = options["font"] or list(MEMORIAL_SHEET_WEB_FONTS)
        output_dir = memorial_sheet_private_font_dir()
        output_dir.mkdir(parents=True, exist_ok=True)

        for font_slug in font_slugs:
            font = MEMORIAL_SHEET_WEB_FONTS[font_slug]
            self._extract_font(font=font, source_dir=source_dir, output_dir=output_dir, overwrite=options["overwrite"])

    def _extract_font(
        self,
        *,
        font: MemorialSheetWebFont,
        source_dir: Path,
        output_dir: Path,
        overwrite: bool,
    ) -> None:
        source_path = source_dir / font.mac_resource_name
        if not source_path.exists():
            raise CommandError(f"{font.display_name} source font was not found: {source_path}")
        output_path = output_dir / font.filename
        if output_path.exists() and not overwrite:
            self.stdout.write(f"skip existing {output_path}")
            return
        payload = _extract_sfnt_payload(_resource_fork_path(source_path), font.resource_id)
        output_path.write_bytes(payload)
        self.stdout.write(
            self.style.SUCCESS(
                f"extracted {font.display_name}: {source_path} -> {output_path}"
            )
        )
