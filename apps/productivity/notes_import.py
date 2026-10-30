"""Notes brought in from other apps: Markdown or text files, or a .zip of them —
an Obsidian vault, a Bear export, Notion's "Markdown & CSV" export.

Each file is one note:
- its title: `title:` in a front matter block (--- … --- at the top), else a
  first line "# Heading" (taken out of the text), else the file's name
  (without Notion's 32-character id at the end);
- its tags: `tags:` in the front matter, the folder it was in (an Obsidian
  vault's folders), and #tags in the text (as any note's — services.hashtags);
- [[links]] between notes keep working: they go by title.

Zips are read with limits (files, sizes) so a huge or hostile one can't
fill the server; a note already here (same title and text) isn't added twice."""
import io
import re
import zipfile
from pathlib import PurePosixPath

from django.db import transaction
from django.utils.translation import gettext as _

from . import services
from .models import Note

TEXT_TYPES = (".md", ".markdown", ".txt")
MAX_FILES = 2000
MAX_FILE = 1024 * 1024               # one note: 1 MB of text
MAX_TOTAL = 30 * 1024 * 1024         # all of it, unpacked
NOTION_ID = re.compile(r"\s+[0-9a-f]{32}$", re.I)
FRONT = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


class ImportError_(Exception):
    pass


def _tags_from(value):
    value = value.strip().strip("[]")
    return [t.strip().strip("'\"").lstrip("#") for t in re.split(r"[,\s]+", value) if t.strip().strip("'\"#")]


def front_matter(text):
    """(fields, the text after it). Reads the simple `key: value` and `tags:` (inline or as a "- x" list) lines."""
    m = FRONT.match(text)
    if not m:
        return {}, text
    fields, key = {}, None
    for line in m.group(1).splitlines():
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and key == "tags":
            fields.setdefault("tags", []).extend(_tags_from(item.group(1)))
            continue
        kv = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not kv:
            continue
        key, value = kv.group(1).lower(), kv.group(2)
        if key in ("tags", "tag", "keywords"):
            key = "tags"
            fields.setdefault("tags", []).extend(_tags_from(value))
        elif key == "title":
            value = value.strip()
            quoted = len(value) > 1 and value[0] == value[-1] == '"'      # (as a note's download writes it)
            fields["title"] = value[1:-1].replace('\\"', '"').replace("\\\\", "\\") if quoted else value.strip("'\"")
    return fields, text[m.end():]


def parse(path, raw):
    """One file → {"title", "body", "tags"}, or None when there's nothing in it."""
    text = raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    fields, body = front_matter(text)
    title = fields.get("title", "")
    if not title:
        first = re.match(r"\A\s*#[ \t]+(.+?)[ \t]*#*[ \t]*(?:\n|\Z)", body)
        if first:
            title, body = first.group(1).strip(), body[first.end():]
    p = PurePosixPath(path)
    if not title:
        title = NOTION_ID.sub("", p.stem).strip()
    body = body.strip("\n")
    if not title and not body.strip():
        return None
    tags = list(fields.get("tags", []))
    folders = [NOTION_ID.sub("", f).strip() for f in p.parts[:-1] if f not in (".", "")]
    if folders:
        tags.append(folders[-1])          # the folder it was in
    tags = [re.sub(r"\s+", "-", t.lower())[:40] for t in tags if t]
    return {"title": title[:200], "body": body, "tags": list(dict.fromkeys(tags))}


def _wanted(name):
    p = PurePosixPath(name)
    return (p.suffix.lower() in TEXT_TYPES and not any(part.startswith(".") or part == "__MACOSX" for part in p.parts))


def read(uploads):
    """Uploaded files (each .md / .txt / .zip) → the notes in them. Raises ImportError_ with a message for the person."""
    out, total = [], 0
    for up in uploads:
        name = up.name or ""
        if name.lower().endswith(".zip"):
            try:
                z = zipfile.ZipFile(io.BytesIO(up.read()))
            except zipfile.BadZipFile:
                raise ImportError_(_("“%(name)s” isn't a zip file that can be opened.") % {"name": name})
            members = [i for i in z.infolist() if not i.is_dir() and _wanted(i.filename)]
            if len(members) > MAX_FILES:
                raise ImportError_(_("Too many files in one go (%(n)s) — at most %(max)s.") % {"n": len(members), "max": MAX_FILES})
            for info in members:
                if info.file_size > MAX_FILE:
                    continue
                total += info.file_size
                if total > MAX_TOTAL:
                    raise ImportError_(_("That's more than 30 MB of notes — split it into smaller zips."))
                note = parse(info.filename, z.read(info))
                if note:
                    out.append(note)
        elif _wanted(name):
            raw = up.read(MAX_FILE + 1)
            if len(raw) > MAX_FILE:
                continue
            total += len(raw)
            note = parse(name, raw)
            if note:
                out.append(note)
        if len(out) > MAX_FILES:
            raise ImportError_(_("Too many files in one go (%(n)s) — at most %(max)s.") % {"n": len(out), "max": MAX_FILES})
    return out


@transaction.atomic
def save(user, notes):
    """Adds them (skipping one that's already here, same title and text). Returns (added, skipped)."""
    have = set(Note.objects.filter(owner=user).values_list("title", "body"))
    added = skipped = 0
    for n in notes:
        if (n["title"], n["body"]) in have:
            skipped += 1
            continue
        have.add((n["title"], n["body"]))
        note = Note.objects.create(owner=user, title=n["title"], body=n["body"])
        names = n["tags"] + services.hashtags(n["body"])
        if names:
            note.tags.set(services.tags_named(user, names))
        added += 1
    return added, skipped
