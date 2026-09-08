#!/usr/bin/env python3
"""Offline draft artwork archive. No generation, upload, activation or network API."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone


SCHEMA = "historical-background-draft/1"
ID_PATTERN = re.compile(r"bg_[0-9a-f]{24}\Z")
KINDS = ("event", "person", "place", "period", "theme")
BRIEF_FIELDS = {
    "title", "subject", "era", "region", "style", "palette", "composition",
    "origin", "tags", "proposed_placement", "derived_from",
}
IMAGE_NAMES = {"image.png", "image.jpg", "image.webp"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate_brief(brief):
    if not isinstance(brief, dict) or set(brief) - BRIEF_FIELDS:
        raise ValueError("brief must contain only documented fields; approval/display state is not accepted")
    for key in ("title", "era", "region", "style", "composition", "proposed_placement"):
        if not nonempty(brief.get(key)):
            raise ValueError(f"brief.{key} must be a nonempty string")
    subject = brief.get("subject")
    if not isinstance(subject, dict) or subject.get("kind") not in KINDS or not nonempty(subject.get("name")):
        raise ValueError("brief.subject requires kind and name")
    palette = brief.get("palette")
    if not isinstance(palette, list) or not 1 <= len(palette) <= 8 or any(
        not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color) for color in palette
    ):
        raise ValueError("brief.palette must contain 1–8 HEX colors")
    origin = brief.get("origin")
    if not isinstance(origin, dict) or origin.get("kind") not in ("generated", "uploaded"):
        raise ValueError("brief.origin.kind must be generated or uploaded")
    if not nonempty(origin.get("rights")):
        raise ValueError("brief.origin.rights must describe the actual rights/source information")
    tags = brief.get("tags")
    if not isinstance(tags, list) or any(not nonempty(tag) for tag in tags):
        raise ValueError("brief.tags must be a string list")
    parent = brief.get("derived_from")
    if parent is not None and (not isinstance(parent, str) or not ID_PATTERN.fullmatch(parent)):
        raise ValueError("brief.derived_from must be an existing asset ID or null")


def image_name(data):
    # Signature detection for an offline archive, not an HTTP upload decoder.
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        return "image.png"
    if len(data) >= 4 and data.startswith(b"\xff\xd8\xff"):
        return "image.jpg"
    if len(data) >= 16 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image.webp"
    raise ValueError("expected PNG, JPEG or WebP bytes")


def checked_drafts(library, create=False):
    library = Path(library).resolve()
    drafts = library / "drafts"
    if drafts.is_symlink():
        raise ValueError("drafts directory must not be a symlink")
    if create:
        drafts.mkdir(parents=True, exist_ok=True)
    return drafts


def read_record(library, asset_id, verify=False):
    if not ID_PATTERN.fullmatch(asset_id):
        raise ValueError("invalid asset ID")
    directory = checked_drafts(library) / asset_id
    if directory.is_symlink():
        raise ValueError("asset directory must not be a symlink")
    for filename in ("manifest.json", "brief.json", "prompt.txt"):
        if (directory / filename).is_symlink():
            raise ValueError(f"{asset_id}: unexpected symlink {filename}")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA or manifest.get("asset_id") != asset_id or manifest.get("status") != "draft":
        raise ValueError(f"{asset_id}: invalid draft manifest")
    files = manifest.get("files", {})
    images = set(files) & IMAGE_NAMES
    if len(images) != 1 or set(files) != images | {"brief.json", "prompt.txt"}:
        raise ValueError(f"{asset_id}: unexpected archive filenames")
    image_file = next(iter(images))
    if (directory / image_file).is_symlink():
        raise ValueError(f"{asset_id}: image must not be a symlink")
    brief = json.loads((directory / "brief.json").read_text(encoding="utf-8"))
    validate_brief(brief)
    if verify:
        for filename, expected in files.items():
            data = (directory / filename).read_bytes()
            if len(data) != expected.get("bytes") or sha(data) != expected.get("sha256"):
                raise ValueError(f"{asset_id}: integrity mismatch in {filename}")
        image_bytes = (directory / image_file).read_bytes()
        prompt_bytes = (directory / "prompt.txt").read_bytes()
        digest = sha(image_bytes + b"\0" + canonical(brief) + b"\0" + prompt_bytes)
        if image_name(image_bytes) != image_file or manifest.get("content_sha256") != digest or asset_id != "bg_" + digest[:24]:
            raise ValueError(f"{asset_id}: content identity mismatch")
    return {
        "manifest": manifest, "brief": brief,
        "image_path": str(directory / image_file),
        "prompt_path": str(directory / "prompt.txt"),
        "manifest_path": str(directory / "manifest.json"),
    }


def archive(library, image_path, brief, prompt=None):
    validate_brief(brief)
    if prompt is None:
        if brief["origin"]["kind"] == "generated":
            raise ValueError("generated artwork requires its actual final prompt")
        prompt = "用户上传图片，未提供原始生成提示词。\n"
    if not nonempty(prompt):
        raise ValueError("prompt must be nonempty")
    image_bytes = Path(image_path).read_bytes()
    filename = image_name(image_bytes)
    prompt_bytes = prompt.encode("utf-8")
    digest = sha(image_bytes + b"\0" + canonical(brief) + b"\0" + prompt_bytes)
    asset_id = "bg_" + digest[:24]
    parent = brief.get("derived_from")
    if parent:
        read_record(library, parent, verify=True)
    drafts = checked_drafts(library, create=True)
    destination = drafts / asset_id
    if destination.exists() or destination.is_symlink():
        result = read_record(library, asset_id, verify=True)
        if result["manifest"]["content_sha256"] != digest:
            raise ValueError("asset ID collision")
        return {**result, "duplicate": True}

    files = {filename: image_bytes, "prompt.txt": prompt_bytes, "brief.json": canonical(brief) + b"\n"}
    manifest = {
        "schema": SCHEMA, "asset_id": asset_id, "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(), "content_sha256": digest,
        "files": {name: {"bytes": len(data), "sha256": sha(data)} for name, data in files.items()},
    }
    temporary = Path(tempfile.mkdtemp(prefix=".pending-", dir=drafts))
    try:
        for name, data in {**files, "manifest.json": canonical(manifest) + b"\n"}.items():
            with (temporary / name).open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        try:
            temporary.rename(destination)
            duplicate = False
        except OSError:
            # A concurrent identical archive may have won; never replace it.
            if not destination.exists():
                raise
            existing = read_record(library, asset_id, verify=True)
            if existing["manifest"]["content_sha256"] != digest:
                raise ValueError("asset ID collision")
            duplicate = True
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {**read_record(library, asset_id, verify=True), "duplicate": duplicate}


def list_records(library, query="", era="", kind=None, verify=False):
    records = []
    for path in sorted(checked_drafts(library).glob("bg_*")):
        record = read_record(library, path.name, verify=verify)
        brief = record["brief"]
        if query.casefold() not in canonical(brief).decode("utf-8").casefold():
            continue
        if era.casefold() not in brief["era"].casefold() or kind and brief["subject"]["kind"] != kind:
            continue
        records.append(record)
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("archive", help="archive an existing image as an inactive draft")
    add.add_argument("--image", required=True, type=Path)
    add.add_argument("--brief", required=True, type=Path)
    add.add_argument("--prompt", type=Path)
    listing = commands.add_parser("list", help="find draft images by metadata")
    listing.add_argument("--query", default="")
    listing.add_argument("--era", default="")
    listing.add_argument("--kind", choices=KINDS)
    show = commands.add_parser("show", help="verify and locate one draft")
    show.add_argument("asset_id")
    commands.add_parser("verify", help="verify all archived draft files")
    args = parser.parse_args(argv)
    try:
        if args.command == "archive":
            brief = json.loads(args.brief.read_text(encoding="utf-8"))
            prompt = args.prompt.read_text(encoding="utf-8") if args.prompt else None
            result = archive(args.library, args.image, brief, prompt)
        elif args.command == "show":
            result = read_record(args.library, args.asset_id, verify=True)
        elif args.command == "verify":
            records = list_records(args.library, verify=True)
            result = {"verified_drafts": len(records), "valid": True}
        else:
            result = [
                {"asset_id": record["manifest"]["asset_id"], "status": "draft",
                 "title": record["brief"]["title"], "era": record["brief"]["era"],
                 "subject": record["brief"]["subject"], "style": record["brief"]["style"],
                 "image_path": record["image_path"]}
                for record in list_records(args.library, args.query, args.era, args.kind)
            ]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"background draft archive: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
