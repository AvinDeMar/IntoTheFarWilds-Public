#!/usr/bin/env python3
"""Prepare and verify explicitly selected public artwork; never synchronize sources.

Preparation is local. Publishing requires a separate, external owner-approval
receipt bound to the exact release catalog, allowlist and Git change summary.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
LIVE = (12, 112, 1012, 912)
PIPELINE = "rgba-lanczos-v1"
STATIC_FILES = {
    ".gitattributes", ".gitignore", "README.md", "LICENSE-ARTWORK.md",
    "LICENSE-CODE.md", "catalog.json", "docs/ARTWORK_CATALOG.md",
    "docs/PUBLISHING.md", "docs/RELEASES.md", "scripts/publish_art.py",
    "scripts/test_publishing.py", "requirements.txt", "site/index.html",
    "site/styles.css", "site/app.js", ".github/workflows/deploy-gallery.yml",
    ".agents/skills/far-wilds-public-art-publishing/SKILL.md",
}
CATALOG = "catalog.json"
ALLOWLIST = "publication-allowlist.json"


def fail(message):
    raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def safe_path(root, relative):
    p = Path(relative)
    if p.is_absolute() or "\\" in str(relative) or ".." in p.parts:
        fail(f"Unsafe publication path: {relative}")
    result = (root / p).resolve()
    if not result.is_relative_to(root.resolve()) or result == root.resolve():
        fail("Publication path escapes the workspace")
    return result


def private_path(path):
    p = Path(path).resolve()
    if p.is_relative_to(ROOT.resolve()):
        fail("Selection, cache and approval records must stay outside the public repository")
    return p


def write_changed(path, data):
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def sort_key(item):
    return item["group_order"], item["item_order"], item["id"]


def validate_release(release):
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", release) or ".." in release:
        fail("Unsafe release identifier")


def validate_order(items):
    positions, orders, identities = set(), {}, {}
    for item in items:
        identity = (item["category"], item["group_slug"])
        order = item["group_order"]
        if orders.setdefault(order, identity) != identity or identities.setdefault(identity, order) != order:
            fail("Collection order must identify exactly one stable group")
        position = (order, item["item_order"])
        if position in positions:
            fail("Duplicate item position within a collection")
        positions.add(position)


def read_catalog():
    p = ROOT / CATALOG
    return load(p) if p.exists() else {
        "schema_version": 1, "project": "Into the Far Wilds",
        "studio": "Crow Brain Games, LLC", "releases": [], "items": [], "retired": [],
    }


def png_bytes(image):
    # A new image drops EXIF, text chunks and potentially private author metadata.
    from PIL import Image
    clean = Image.new(image.mode, image.size)
    clean.paste(image)
    stream = io.BytesIO()
    clean.save(stream, format="PNG", optimize=True, compress_level=9)
    return stream.getvalue()


def derivatives(source, kind):
    from PIL import Image, ImageCms
    with Image.open(source) as original:
        if original.format not in {"PNG", "JPEG", "WEBP"}:
            fail("Unsupported artwork image format")
        if kind == "icon":
            if original.format != "PNG" or original.mode != "RGBA" or original.size != (1024, 1024):
                fail("Icon sources must be approved 1024-square RGBA PNG masters")
            bbox = original.getchannel("A").getbbox()
            if not bbox or bbox[0] < LIVE[0] or bbox[1] < LIVE[1] or bbox[2] > LIVE[2] or bbox[3] > LIVE[3]:
                fail("Icon subject extends outside the approved live area")
            image = original.crop(LIVE)
            sizes = [(100, 80), (400, 320)]
        else:
            image = original.convert("RGBA" if "A" in original.getbands() else "RGB")
            sizes = []
            for bound in [(320, 240), (1200, 1200)]:
                sample = image.copy()
                sample.thumbnail(bound, Image.Resampling.LANCZOS)
                sizes.append(sample.size)
        # Color management preserves appearance; untagged artwork is treated as sRGB.
        profile = original.info.get("icc_profile")
        if profile:
            inp = ImageCms.ImageCmsProfile(io.BytesIO(profile))
            if "srgb" not in ImageCms.getProfileDescription(inp).casefold():
                image = ImageCms.profileToProfile(image, inp, ImageCms.createProfile("sRGB"), outputMode=image.mode)
        output = []
        for size in sizes:
            # Pillow's RGBA LANCZOS path resamples premultiplied alpha internally.
            result = image.resize(size, Image.Resampling.LANCZOS)
            output.append((png_bytes(result), list(size)))
        return output


def image_path(item, suffix):
    kind = item["kind"]
    if kind == "icon":
        base = f"art/icons/{item['category']}/{item['group_slug']}"
    else:
        base = f"art/{item['category']}/{item['group_slug']}"
    return f"{base}/{item['id'].lower()}-{suffix}.png"


def validate_selection_item(item):
    required = {"id", "name", "display_name", "kind", "category", "group", "group_slug",
                "group_order", "item_order", "version", "source_path", "source_sha256",
                "approval_status", "rights_status"}
    if not required.issubset(item):
        fail("Selection record is incomplete")
    if item["approval_status"] != "Approved" or item["rights_status"] != "cleared":
        fail(f"Artwork approval or publication rights unresolved: {item['id']}")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,95}", item["id"]):
        fail("Use a stable canonical ID")
    if item["kind"] not in {"icon", "artwork"}:
        fail("Artwork kind must be icon or artwork")
    allowed = {"resources", "currencies"} if item["kind"] == "icon" else {
        "concepts", "characters", "creatures", "environments", "screenshots", "illustrations"}
    if item["category"] not in allowed or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", item["group_slug"]):
        fail("Unsupported category or unsafe public slug")
    if not all(isinstance(item[k], int) and item[k] >= 0 for k in ("group_order", "item_order")):
        fail("Source order must be explicit")
    if not re.fullmatch(r"[a-f0-9]{64}", item["source_sha256"]):
        fail("Source SHA-256 is required")
    for k in ("name", "display_name", "group", "version"):
        if not isinstance(item[k], str) or not item[k].strip() or len(item[k]) > 180 or "\n" in item[k]:
            fail("Invalid public label")


def prepare(args):
    selection_path = private_path(args.selection)
    state_path = private_path(args.state or selection_path.with_name("derivative-state.json"))
    selection = load(selection_path)
    requested = selection["items"]
    if not requested or len({i["id"] for i in requested}) != len(requested):
        fail("An explicit nonempty selection with unique IDs is required")
    validate_release(args.release)
    catalog = read_catalog()
    previous = {i["id"]: i for i in catalog["items"]}
    state = load(state_path) if state_path.exists() else {}
    next_items = dict(previous)
    files, next_state, changed_ids = {}, dict(state), []
    from PIL import __version__ as pillow_version
    pipeline = PIPELINE + "/Pillow-" + pillow_version
    # Validate and render the entire requested batch before changing public files.
    for item in requested:
        validate_selection_item(item)
        source = private_path(item["source_path"])
        if source.is_symlink() or not source.is_file() or sha(source.read_bytes()) != item["source_sha256"]:
            fail(f"Source hash mismatch or missing source: {item['id']}")
        key = sha(encoded({k: item[k] for k in sorted(item) if k != "source_path"}) + pipeline.encode())
        old = previous.get(item["id"])
        if old and state.get(item["id"], {}).get("key") == key and all(
            safe_path(ROOT, old[k]["path"]).is_file() and
            sha(safe_path(ROOT, old[k]["path"]).read_bytes()) == old[k]["sha256"]
            for k in ("thumbnail", "preview")
        ):
            continue
        outputs = derivatives(source, item["kind"])
        public = {k: item[k] for k in ("id", "name", "display_name", "kind", "category", "group",
                                      "group_slug", "group_order", "item_order", "version")}
        public["publication_version"] = args.release
        for label, (data, size) in zip(("thumbnail", "preview"), outputs):
            path = image_path(public, label)
            safe_path(ROOT, path)
            public[label] = {"path": path, "width": size[0], "height": size[1], "sha256": sha(data)}
            files[path] = data
        compare = dict(public)
        compare.pop("publication_version")
        old_compare = dict(old or {})
        old_compare.pop("publication_version", None)
        if compare == old_compare:
            public["publication_version"] = old["publication_version"]
        else:
            changed_ids.append(item["id"])
        next_items[item["id"]] = public
        next_state[item["id"]] = {"key": key}
    if not changed_ids:
        restored = sum(write_changed(safe_path(ROOT, path), data) for path, data in files.items())
        write_changed(state_path, encoded(next_state))
        print(json.dumps({"status": "unchanged", "changed_ids": [], "image_writes": restored}))
        return
    catalog["items"] = sorted(next_items.values(), key=sort_key)
    validate_order(catalog["items"])
    if args.release in catalog["releases"]:
        fail("A changed collection requires a new release identifier")
    catalog["retired"] = [i for i in catalog["retired"] if i["id"] not in next_items]
    if args.release not in catalog["releases"]:
        catalog["releases"].append(args.release)
    catalog["latest_release"] = args.release
    for path, data in files.items():
        write_changed(safe_path(ROOT, path), data)
    write_changed(ROOT / CATALOG, encoded(catalog))
    release = {"release": args.release, "date": args.date, "operation": "add-or-update",
               "changed_ids": changed_ids, "published_items": len(catalog["items"]),
               "selection": "Explicitly owner-authorized approved artwork; no automatic source synchronization"}
    write_changed(ROOT / "releases" / (args.release + ".json"), encoded(release))
    render(catalog)
    write_changed(state_path, encoded(next_state))
    print(json.dumps({"status": "prepared locally", "changed_ids": changed_ids,
                      "items": len(catalog["items"]), "network_publication": False}))


def url(image, prefix=""):
    return prefix + image["path"] + "?v=" + image["sha256"][:12]


def md_label(value):
    return html.escape(value).replace("|", "&#124;").replace("[", "&#91;").replace("]", "&#93;")


def groups(catalog):
    result = []
    for item in sorted(catalog["items"], key=sort_key):
        if not result or result[-1][0] != item["group_order"]:
            result.append((item["group_order"], []))
        result[-1][1].append(item)
    return result


def anchor(item):
    return f"{item['category']}-{item['group_slug']}"


def render(catalog):
    buckets = groups(catalog)
    resource_count = sum(i["category"] == "resources" for i in catalog["items"])
    currency_count = sum(i["category"] == "currencies" for i in catalog["items"])
    nav = [f"[{md_label(items[0]['group'])}](#{anchor(items[0])})" for _, items in buckets]
    md = ["# Into the Far Wilds — artwork catalog", "",
          f"**{len(catalog['items'])} published artworks** · {resource_count} resource icons · {currency_count} currency icons", "",
          "By Crow Brain Games. Select an image to open its larger public preview.", "",
          "[Project introduction](../README.md) · [Artwork rights](../LICENSE-ARTWORK.md)", "", "## Collections", ""]
    md.extend(" · ".join(nav[i:i + 5]) for i in range(0, len(nav), 5))
    for _, items in buckets:
        a = items[0]
        md += ["", f'<a id="{anchor(a)}"></a>', f"## {md_label(a['group'])}", ""]
        # Small tables preserve natural image sizes without forcing separate pages.
        for start in range(0, len(items), 7):
            row = items[start:start + 7]
            md += ["| " + " | ".join(md_label(i["display_name"]) for i in row) + " |",
                   "|" + "---|" * len(row),
                   "| " + " | ".join(f"[![{md_label(i['display_name'])}]({url(i['thumbnail'], '../')})]({url(i['preview'], '../')})" for i in row) + " |",
                   "| " + " | ".join(("Parent · " if i["kind"] == "icon" and i["category"] == "resources" and i["item_order"] == 0 else "") + i["version"] for i in row) + " |", ""]
        md += ["[Back to collections](#collections)"]
    md += ["", "Artwork for Into the Far Wilds. © Crow Brain Games, LLC. All rights reserved where applicable.",
           "Public viewing does not grant a license to reuse the artwork.", ""]
    write_changed(ROOT / "docs/ARTWORK_CATALOG.md", "\n".join(md).encode())
    count = len(catalog["items"])
    title = "Resource & Currency Artwork Collection" if all(i["kind"] == "icon" for i in catalog["items"]) else "Artwork & Media Collection"
    featured = [items[0] for _, items in buckets[:6]]
    readme = ["# Into the Far Wilds", "", f"## {title}", "",
              "An evolving visual identity, one material at a time.", "",
              "A curated collection of artwork for **Into the Far Wilds**, in development by **Crow Brain Games**. This showcase begins with resource and currency icons and can grow to include owner-selected concept art, environments, characters and screenshots.", "",
              f"**{count} published artworks** · {resource_count} resource icons · {currency_count} currency and portable-valuable icons", "",
              "**[Browse the complete labeled gallery](docs/ARTWORK_CATALOG.md)** · **[Open the interactive showcase](https://avindemar.github.io/IntoTheFarWilds-Public/)**", "",
              "Transparent previews, original family order, and larger images one click away.", "",
              "| " + " | ".join(md_label(i["display_name"]) for i in featured) + " |",
              "|" + "---|" * len(featured),
              "| " + " | ".join(f"[![{md_label(i['display_name'])}]({url(i['thumbnail'])})]({url(i['preview'])})" for i in featured) + " |", "",
              "### Explore the collection", ""]
    readme.extend(" · ".join(f"[{md_label(items[0]['group'])}](docs/ARTWORK_CATALOG.md#{anchor(items[0])})" for _, items in buckets[i:i + 5]) for i in range(0, len(buckets), 5))
    readme += ["", "### Artwork rights", "",
               "Artwork for Into the Far Wilds. © Crow Brain Games, LLC. All rights reserved where applicable. **This is a viewing gallery, not a free asset pack.** Public access grants no permission to reuse the artwork. See [artwork rights](LICENSE-ARTWORK.md).", "",
               "The collection includes AI-assisted imagery, owner art direction and edits. Rights in human contributions and other protectable material are reserved to the extent recognized by applicable law.", "",
               "Gallery/publishing code has a [separate code license](LICENSE-CODE.md), which does not cover the artwork or game branding.", "",
               "### For maintainers", "", "[Publishing procedure](docs/PUBLISHING.md) · [Releases](docs/RELEASES.md) · [Machine-readable catalog](catalog.json)", "",
               "New releases are selected and authorized by the owner. This repository has no connection that automatically imports development assets.", ""]
    write_changed(ROOT / "README.md", "\n".join(readme).encode())
    releases = ["# Public releases", "", "Only explicitly authorized artwork releases are published.", ""]
    releases += [f"- [{r}](../releases/{r}.json)" for r in catalog["releases"]]
    releases += ["", "The catalog records the selected artwork version and both derivative hashes for each active item. Earlier public revisions remain in Git history.", ""]
    write_changed(ROOT / "docs/RELEASES.md", "\n".join(releases).encode())


def retire(args):
    validate_release(args.release)
    catalog = read_catalog()
    if args.release in catalog["releases"]:
        fail("A retirement requires a new release identifier")
    ids = set(args.ids.split(","))
    items = {i["id"]: i for i in catalog["items"]}
    if not ids or not ids.issubset(items):
        fail("Retirement requires explicit existing IDs")
    for cid in sorted(ids):
        i = items.pop(cid)
        for label in ("thumbnail", "preview"):
            p = safe_path(ROOT, i[label]["path"])
            if sha(p.read_bytes()) != i[label]["sha256"]:
                fail("Do not discard a locally modified public image")
        catalog["retired"].append({"id": cid, "display_name": i["display_name"], "version": i["version"], "retired_in": args.release})
    # The allowlisted derivative paths are checked before these bounded removals.
    for cid in ids:
        original = next(i for i in catalog["items"] if i["id"] == cid)
        for label in ("thumbnail", "preview"):
            safe_path(ROOT, original[label]["path"]).unlink()
    catalog["items"] = sorted(items.values(), key=sort_key)
    if args.release not in catalog["releases"]:
        catalog["releases"].append(args.release)
    catalog["latest_release"] = args.release
    write_changed(ROOT / CATALOG, encoded(catalog))
    write_changed(ROOT / "releases" / (args.release + ".json"), encoded({"release": args.release, "date": args.date, "operation": "retire", "ids": sorted(ids)}))
    render(catalog)
    print(json.dumps({"status": "retired locally", "ids": sorted(ids), "publication": False}))


def expected_files(catalog):
    result = set(STATIC_FILES) | {ALLOWLIST}
    for i in catalog["items"]:
        for kind in ("thumbnail", "preview"):
            path = i[kind]["path"]
            safe_path(ROOT, path)
            result.add(path)
    for release in catalog["releases"]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", release) or ".." in release:
            fail("Unsafe release path")
        result.add(f"releases/{release}.json")
    return result


def disk_files():
    files = set()
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if rel.parts[0] == ".git":
            continue
        if p.is_symlink():
            fail("Symlinks are not publication inputs")
        if p.is_file():
            files.add(rel.as_posix())
    return files


def seal(_args):
    catalog = read_catalog()
    expected = expected_files(catalog)
    actual = disk_files()
    if actual - expected or expected - actual - {ALLOWLIST}:
        fail(f"Publication allowlist mismatch: unexpected={sorted(actual-expected)}, missing={sorted(expected-actual-{ALLOWLIST})}")
    record = {"schema_version": 1, "release": catalog["latest_release"],
              "self": ALLOWLIST, "files": [{"path": p, "sha256": sha(safe_path(ROOT, p).read_bytes())} for p in sorted(expected - {ALLOWLIST})]}
    write_changed(ROOT / ALLOWLIST, encoded(record))
    print(json.dumps({"status": "allowlist sealed locally", "files": len(expected)}))


def verify(args):
    from PIL import Image
    catalog = read_catalog()
    expected = expected_files(catalog)
    if disk_files() != expected:
        fail("Unexpected or missing files; publication is closed")
    allowlist = load(ROOT / ALLOWLIST)
    hashes = {r["path"]: r["sha256"] for r in allowlist["files"]}
    if set(hashes) != expected - {ALLOWLIST}:
        fail("Incomplete allowlist")
    for p, h in hashes.items():
        if sha(safe_path(ROOT, p).read_bytes()) != h:
            fail(f"Allowlist hash changed: {p}")
    items = catalog["items"]
    validate_order(items)
    if len({i["id"] for i in items}) != len(items) or items != sorted(items, key=sort_key):
        fail("Duplicate IDs or incorrect display order")
    output_paths = [i[label]["path"] for i in items for label in ("thumbnail", "preview")]
    if len(set(output_paths)) != len(output_paths):
        fail("Duplicate image paths")
    for item in items:
        for label in ("thumbnail", "preview"):
            r = item[label]
            p = safe_path(ROOT, r["path"])
            if p.read_bytes().startswith(b"version https://git-lfs") or sha(p.read_bytes()) != r["sha256"]:
                fail("Unresolved LFS pointer or mismatched derivative")
            with Image.open(p) as im:
                if im.format != "PNG" or list(im.size) != [r["width"], r["height"]] or im.mode not in {"RGB", "RGBA"}:
                    fail("Invalid public image")
                if im.info:
                    fail("Unexpected PNG metadata")
                if item["kind"] == "icon":
                    required = (100, 80) if label == "thumbnail" else (400, 320)
                    if im.size != required or im.mode != "RGBA" or im.getchannel("A").getextrema()[0] != 0 or im.getchannel("A").getextrema()[1] < 8:
                        fail("Icon derivative dimensions or transparency failed")
    # Public text must not contain personal paths, credentials or source artifacts.
    sensitive = [re.compile(r"\b[A-Za-z]:[\\/]"), re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
                 re.compile(r"github_pat_[A-Za-z0-9_]{40,}"), re.compile(r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----")]
    forbidden = []
    if getattr(args, "private_profile", None):
        forbidden = load(private_path(args.private_profile)).get("forbidden_text", [])
    for path in expected:
        if path.endswith(".png"):
            continue
        data = safe_path(ROOT, path).read_bytes()
        text = data.decode("utf-8")
        if any(pattern.search(text) for pattern in sensitive) or any(v.casefold() in text.casefold() for v in forbidden):
            fail(f"Private information or credentials detected: {path}")
        if b"\r" in data:
            fail("Public text must use LF line endings")
    # Check generated Markdown links against the actual public tree.
    for name in ("README.md", "docs/ARTWORK_CATALOG.md", "docs/PUBLISHING.md", "docs/RELEASES.md"):
        p = ROOT / name
        for link in re.findall(r"\]\(([^)]+)\)", p.read_text(encoding="utf-8")):
            u = urlsplit(link)
            if u.scheme or not u.path or "<" in u.path:
                continue
            target = (p.parent / unquote(u.path)).resolve()
            if not target.is_relative_to(ROOT.resolve()) or not target.exists():
                fail(f"Broken public link: {name}: {link}")
    if getattr(args, "expected_icons", None) is not None and sum(i["kind"] == "icon" for i in items) != args.expected_icons:
        fail("Incorrect authorized icon count")
    report = {"status": "pass", "items": len(items), "files": len(expected),
              "image_files": len(output_paths), "bytes": sum(safe_path(ROOT, p).stat().st_size for p in expected),
              "catalog_sha256": sha((ROOT / CATALOG).read_bytes()), "allowlist_sha256": sha((ROOT / ALLOWLIST).read_bytes())}
    return report


def build_site(args):
    verify(argparse.Namespace(private_profile=None, expected_icons=None))
    output = private_path(args.output)
    if output.exists():
        fail("Use a new empty build directory; do not overwrite unrelated files")
    output.mkdir(parents=True)
    for p in (ROOT / "site").iterdir():
        if p.name != "index.html":
            shutil.copyfile(p, output / p.name)
    template = (ROOT / "site/index.html").read_text(encoding="utf-8")
    for name, token in [(CATALOG, "CATALOG"), ("site/styles.css", "CSS"), ("site/app.js", "JS")]:
        template = template.replace("__" + token + "_HASH__", sha((ROOT / name).read_bytes())[:12])
    (output / "index.html").write_text(template, encoding="utf-8", newline="\n")
    shutil.copyfile(ROOT / CATALOG, output / CATALOG)
    shutil.copyfile(ROOT / "LICENSE-ARTWORK.md", output / "LICENSE-ARTWORK.md")
    shutil.copytree(ROOT / "art", output / "art")
    (output / ".nojekyll").write_text("", encoding="utf-8")
    print(json.dumps({"status": "static site built", "network_publication": False}))


def git(*args, input=None):
    return subprocess.check_output(["git", *args], cwd=ROOT, input=input)


def change_summary():
    # Porcelain v1 -z gives exact paths; renames are rejected rather than guessed.
    raw = git("status", "--porcelain", "-z", "-uall").decode("utf-8").split("\0")
    result = []
    for record in raw:
        if not record:
            continue
        code, path = record[:2], record[3:]
        if "R" in code or "C" in code:
            fail("Review renames explicitly before publishing")
        p = safe_path(ROOT, path)
        result.append({"path": path, "sha256": sha(p.read_bytes()) if p.exists() else None})
    return sorted(result, key=lambda x: x["path"])


def publish(args):
    if not args.approval:
        fail("Explicit owner release approval is required before any network publication")
    approval = load(private_path(args.approval))
    report = verify(args)
    changes = change_summary()
    ids = sorted(i["id"] for i in read_catalog()["items"])
    resuming = not changes and approval.get("committed_head") and git("rev-parse", "HEAD").decode().strip() == approval["committed_head"]
    if approval.get("approved") is not True or approval.get("catalog_sha256") != report["catalog_sha256"] or approval.get("allowlist_sha256") != report["allowlist_sha256"] or (not resuming and approval.get("diff_sha256") != sha(encoded(changes))) or approval.get("active_ids") != ids or not approval.get("owner_evidence"):
        fail("Owner approval does not cover the exact proposed release")
    if args.dry_run:
        print(json.dumps({"status": "authorized dry run", "changed_files": len(changes), "network_publication": False}))
        return
    remote = git("remote", "get-url", "origin").decode().strip()
    expected = "https://github.com/AvinDeMar/IntoTheFarWilds-Public.git"
    if remote != expected or git("branch", "--show-current").decode().strip() != "main":
        fail("Unexpected public destination or branch")
    repo = json.loads(subprocess.check_output(["gh", "repo", "view", "AvinDeMar/IntoTheFarWilds-Public", "--json", "visibility,isFork"], cwd=ROOT))
    if repo["visibility"] != "PUBLIC" or repo["isFork"]:
        fail("Destination must be the separate public repository, not a fork")
    if not changes:
        if resuming:
            subprocess.run(["git", "push", "-u", "origin", "main"], cwd=ROOT, check=True)
        print(json.dumps({"status": "validated commit pushed" if resuming else "unchanged; no publication needed"}))
        return
    paths = [x["path"] for x in changes]
    # Only approved changed paths are staged, including explicit retirements.
    subprocess.run(["git", "add", "--all", "--pathspec-from-file=-", "--pathspec-file-nul"], cwd=ROOT, input=("\0".join(paths) + "\0").encode(), check=True)
    staged = set(git("diff", "--cached", "--name-only", "-z").decode().strip("\0").split("\0"))
    if staged != set(paths):
        fail("Unexpected staged files")
    subprocess.run(["git", "diff", "--cached", "--check"], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", args.message], cwd=ROOT, check=True)
    approval["committed_head"] = git("rev-parse", "HEAD").decode().strip()
    write_changed(private_path(args.approval), encoded(approval))
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--selection", required=True); p.add_argument("--state")
    p.add_argument("--release", required=True); p.add_argument("--date", required=True)
    p.set_defaults(run=prepare)
    p = sub.add_parser("retire"); p.add_argument("--ids", required=True); p.add_argument("--release", required=True); p.add_argument("--date", required=True); p.set_defaults(run=retire)
    p = sub.add_parser("seal"); p.set_defaults(run=seal)
    p = sub.add_parser("verify"); p.add_argument("--private-profile"); p.add_argument("--expected-icons", type=int); p.set_defaults(run=lambda a: print(json.dumps(verify(a))))
    p = sub.add_parser("build-site"); p.add_argument("--output", required=True); p.set_defaults(run=build_site)
    p = sub.add_parser("publish"); p.add_argument("--approval"); p.add_argument("--private-profile"); p.add_argument("--expected-icons", type=int); p.add_argument("--dry-run", action="store_true"); p.add_argument("--message", default="Publish owner-authorized artwork release"); p.set_defaults(run=publish)
    args = parser.parse_args()
    try:
        args.run(args)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, f"Publication stopped: {error}\n")


if __name__ == "__main__":
    main()
