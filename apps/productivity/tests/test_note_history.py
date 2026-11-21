"""A note's edit history: kept 2, 4, 6, 12 or any number of months (the note's own choice or the default in Work
settings), or off for one note; old copies thin out; a copy can be kept for good; and each copy says what changed."""
from datetime import datetime, timedelta, timezone as dt_tz

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .. import note_history as nh, services
from ..models import Note, NoteVersion, WorkSettings

PW = "Str0ng-pass-123"


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_superuser("me", "me@example.com", PW)
        self.client.force_login(self.me)
        self.note = Note.objects.create(owner=self.me, title="Plan", body="# Setup\n\nInstall python.\n\n# Use\n\nRun it.")
        self.now = timezone.now()

    def copy(self, days, body="text", **kw):
        return NoteVersion.objects.create(note=self.note, title="Plan", body=body, created_at=self.now - timedelta(days=days), **kw)

    def act(self, **data):
        return self.client.post(reverse("work:api_note_action", args=[self.note.pk]), data).json()

    def listed(self):
        return self.client.get(reverse("work:api_note_versions", args=[self.note.pk])).json()


class KeepingTests(Base):
    def test_a_copy_every_few_minutes_as_set(self):
        ws = WorkSettings.for_user(self.me)
        ws.note_history_minutes = 30
        ws.save()
        self.assertIsNotNone(nh.remember(self.note))
        self.note.body += " more"
        self.assertIsNone(nh.remember(self.note))                          # same sitting
        NoteVersion.objects.update(created_at=self.now - timedelta(minutes=31))
        self.assertIsNotNone(nh.remember(self.note))

    def test_off_keeps_nothing_but_a_conflict(self):
        self.note.history_off = True
        self.note.save()
        self.assertIsNone(nh.remember(self.note, force=True))
        self.assertIsNotNone(nh.remember(self.note, force=True, reason="conflict"))      # nothing is ever lost

    def test_a_new_note_follows_the_default_and_a_copy_keeps_the_setting(self):
        ws = WorkSettings.for_user(self.me)
        ws.note_history_new = False
        ws.save()
        res = self.client.post(reverse("work:api_note_save"), {"title": "New", "body": "hello"}).json()
        self.assertTrue(Note.objects.get(pk=res["id"]).history_off)
        self.note.history_months = 6
        self.note.save()
        res = self.act(action="duplicate")
        self.assertEqual(Note.objects.get(pk=res["id"]).history_months, 6)


class HowLongTests(Base):
    def test_months_back_in_the_calendar(self):
        self.assertEqual(nh.months_ago(datetime(2026, 5, 31, tzinfo=dt_tz.utc), 3).date().isoformat(), "2026-02-28")
        self.assertEqual(nh.months_ago(datetime(2026, 1, 15, tzinfo=dt_tz.utc), 12).date().isoformat(), "2025-01-15")
        self.assertEqual(nh.months_ago(datetime(2026, 1, 15, tzinfo=dt_tz.utc), -2).date().isoformat(), "2026-03-15")

    def test_default_two_months_then_the_notes_own(self):
        recent, old, older = self.copy(40), self.copy(75), self.copy(150)
        kept = self.copy(300, pinned=True, label="Before the rewrite")
        nh.prune(self.note)
        left = set(self.note.versions.values_list("pk", flat=True))
        self.assertEqual(left, {recent.pk, kept.pk})                      # 2 months by default; kept-for-good stays
        self.note.history_months = 12
        self.note.save()
        self.assertEqual(nh.months(self.note), 12)
        ws = WorkSettings.for_user(self.me)
        ws.note_history_months = 4
        ws.save()
        self.note.history_months = None
        self.assertEqual(nh.months(self.note), 4)

    def test_old_copies_thin_out(self):
        for h in range(0, 48, 3):                                         # 2 days ago: 16 copies that day
            self.copy(2, body=f"a{h}").created_at
        for d in (10, 10, 10, 12):                                        # 10 days ago: three that day → the last one
            self.copy(d + 0.001 * len(self.note.versions.all()), body=f"b{d}")
        for d in (40, 41, 42, 43):                                        # over a month: one a week
            self.copy(d, body=f"c{d}")
        self.note.history_months = 3
        self.note.save()
        nh.prune(self.note)
        ages = [(self.now - c).days for c in self.note.versions.values_list("created_at", flat=True)]
        self.assertEqual(sum(1 for a in ages if a <= 7), 16)               # the last week: every copy
        self.assertEqual(sum(1 for a in ages if 7 < a <= 30), 2)          # one a day: day 10 and day 12
        self.assertLessEqual(sum(1 for a in ages if a > 30), 2)           # one a week

    def test_a_note_not_written_in_still_runs_out(self):
        self.copy(100)
        other = Note.objects.create(owner=self.me, title="Other", body="x", history_months=6)
        NoteVersion.objects.create(note=other, body="y", created_at=self.now - timedelta(days=100))
        self.assertEqual(nh.sweep(self.me, force=True), 1)                # 100 days > 2 months; the 6-month note's stays
        self.assertEqual(other.versions.count(), 1)


class WhatChangedTests(Base):
    def test_words_lines_and_where(self):
        old = "# Setup\n\nInstall python 3.11 now.\n\nKeep this.\n\n# Use\n\nRun it.\nDelete me."
        new = "# Setup\n\nInstall python 3.12 today.\n\nKeep this.\n\n# Use\n\nRun it.\nA brand new line here."
        d = nh.diff("Plan", old, "Plan v2", new)
        self.assertEqual(d["title"], ["Plan", "Plan v2"])
        self.assertEqual(d["sections"], ["Setup", "Use"])
        mod = [r for r in d["rows"] if r["op"] == "mod"][0]
        self.assertIn(["-", "11"], mod["parts"])                          # just what changed, not the whole line
        self.assertIn(["+", "12"], mod["parts"])
        self.assertIn(["+", "today"], mod["parts"])
        self.assertTrue(any(r["op"] == "del" and r["text"] == "Delete me." for r in d["rows"]))
        self.assertTrue(any(r["op"] == "add" and r["text"] == "A brand new line here." for r in d["rows"]))
        self.assertEqual((d["added"], d["removed"]), (2 + 5, 2 + 2))

    def test_long_unchanged_stretches_fold(self):
        body = "\n".join(f"line {i}" for i in range(100))
        d = nh.diff("", body, "", body.replace("line 50", "line fifty"))
        folds = [r for r in d["rows"] if r["op"] == "fold"]
        self.assertEqual(len(folds), 2)
        self.assertEqual(sum(len(f["lines"]) for f in folds) + sum(1 for r in d["rows"] if r["op"] == "same"), 99)

    def test_bangla_words_stay_whole(self):
        d = nh.diff("", "আমি কি জানি।", "", "আমি এখন জানি।")
        self.assertEqual((d["added"], d["removed"]), (1, 1))
        self.assertIn(["-", "কি"], d["rows"][0]["parts"])

    def test_a_long_unchanged_stretch_says_where_it_is_instead(self):
        body = "\n".join(f"line {i}" for i in range(300))
        d = nh.diff("", body, "", body.replace("line 250", "line two-fifty"))
        fold = d["rows"][0]
        self.assertEqual((fold["op"], fold["count"], fold["start"]), ("fold", 248, 0))
        self.assertNotIn("lines", fold)
        later = nh.diff("", "new first line\n" + body, "", body, side="i")       # pointing into the older text
        self.assertEqual(later["rows"][-1]["start"], 1 + 2)

    def test_a_copy_says_what_changed_when_it_is_made(self):
        n = self.note
        nh.remember(n, force=True)
        n.body += "\n\nTwo more words."
        v = nh.remember(n, force=True)
        self.assertEqual((v.added, v.removed, v.sections["under"]), (3, 0, ["Use"]))

    def test_headings_inside_code_are_not_headings(self):
        old = "# Real\n\n```\n# not a heading\nx = 1\n```"
        d = nh.diff("", old, "", old.replace("x = 1", "x = 2"))
        self.assertEqual(d["sections"], ["Real"])


class PagesTests(Base):
    def test_the_list_says_what_changed_without_sending_every_text(self):
        a = self.copy(3, body="# Setup\n\nInstall python.")
        b = self.copy(2, body="# Setup\n\nInstall python and node.\n\n# Use\n\nRun.")
        res = self.listed()
        newest, oldest = res["versions"]
        self.assertEqual(newest["id"], b.pk)
        self.assertEqual((newest["added"], newest["removed"], newest["sections"]), (4, 0, ["Setup", "Use"]))
        self.assertTrue(oldest["oldest"])
        self.assertNotIn("body", newest)
        self.assertEqual(res["history"]["months"], 2)
        self.assertFalse(res["history"]["own"])
        self.assertIsNotNone(res["now"])
        self.assertTrue(newest["expires"])

    def test_one_copy_three_ways(self):
        self.copy(3, body="Install python.")
        b = self.copy(2, body="Install python and node.")
        url = reverse("work:api_note_version_diff", args=[self.note.pk, b.pk])
        prev = self.client.get(url).json()
        self.assertEqual(prev["added"], 2)
        now = self.client.get(url, {"with": "now"}).json()
        self.assertTrue(any(r["op"] in ("add", "mod") for r in now["rows"]))
        self.assertEqual(self.client.get(url, {"with": "text"}).json()["body"], "Install python and node.")
        first = NoteVersion.objects.order_by("created_at").first()
        self.assertTrue(self.client.get(reverse("work:api_note_version_diff", args=[self.note.pk, first.pk])).json()["first"])

    def test_settings_for_one_note(self):
        self.copy(100)
        self.copy(10)
        res = self.act(action="history", months="4")
        self.assertEqual((res["history"]["months"], res["history"]["own"], res["history"]["count"]), (4, True, 2))
        res = self.act(action="history", months="2")
        self.assertEqual((res["history"]["count"], res["gone"]), (1, 1))      # shorter: the older copy goes
        res = self.act(action="history", months="default")
        self.assertFalse(res["history"]["own"])
        self.assertTrue(self.act(action="history", months="500")["history"]["months"] == 120)
        self.assertFalse(self.act(action="history", months="soon")["ok"])
        res = self.act(action="history", off="1", forget_all="1")
        self.assertTrue(res["history"]["off"])
        self.assertEqual(res["history"]["count"], 0)
        self.note.refresh_from_db()
        self.assertTrue(self.note.history_off)

    def test_keep_for_good_and_save_now(self):
        v = self.copy(1)
        res = self.act(action="keep", version=v.pk, pinned="1", label="Before the rewrite")
        self.assertEqual((res["pinned"], res["label"]), (True, "Before the rewrite"))
        res = self.act(action="save_version", label="Today")
        kept = NoteVersion.objects.get(pk=res["version"])
        self.assertTrue(kept.pinned and kept.body == self.note.body)
        again = self.act(action="save_version", label="Same text")       # nothing changed: the same copy, renamed
        self.assertEqual(again["version"], kept.pk)
        self.copy(2)
        self.assertEqual(self.act(action="forget_all")["gone"], 1)        # the kept-for-good ones stay
        self.assertEqual(self.note.versions.count(), 2)

    def test_deleting_one_copy_redoes_the_next_ones_summary(self):
        a, b, c = self.copy(3, body="one"), self.copy(2, body="one two"), self.copy(1, body="one two three")
        self.listed()
        self.act(action="forget", version=b.pk)
        self.assertIsNone(NoteVersion.objects.get(pk=c.pk).added)
        res = self.listed()
        self.assertEqual(res["versions"][0]["added"], 2)                   # now against "one"

    def test_restore_keeps_what_was_there(self):
        v = self.copy(1, body="old text")
        self.act(action="restore", version=v.pk)
        self.note.refresh_from_db()
        self.assertEqual(self.note.body, "old text")
        self.assertEqual(NoteVersion.objects.filter(reason="restore").count(), 1)

    def test_not_someone_elses(self):
        v = self.copy(1)
        other = User.objects.create_superuser("other", "o@example.com", PW)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("work:api_note_version_diff", args=[self.note.pk, v.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("work:api_note_action", args=[self.note.pk]), {"action": "history", "off": "1"}).status_code, 404)

    def test_work_settings_page(self):
        r = self.client.get(reverse("work:settings"))
        self.assertContains(r, 'id="note-history"')
        form = r.context["form"]
        data = {f"s-{k}": v for k, v in form.initial.items() if v is not None and not isinstance(v, (list, dict))}
        self.assertIn("note_history_months", form.fields)

    def test_the_editor_has_the_history_screen(self):
        r = self.client.get(reverse("work:note", args=[self.note.pk]))
        for part in ("Keep edit history for this note", "What changed then", "Compare with now", "Keep this version now"):
            self.assertContains(r, part)


class BackupTests(Base):
    def test_settings_and_copies_come_back_from_a_backup(self):
        self.note.history_months, self.note.history_off = 6, True
        self.note.save()
        ws = WorkSettings.for_user(self.me)
        ws.note_history_months, ws.note_history_minutes, ws.note_history_new = 12, 30, False
        ws.save()
        v = self.copy(1, body="kept", pinned=True, label="Before", reason="saved")
        nh.fill_summaries(self.note)
        self.copy(2, body="older")
        nh.fill_summaries(self.note)
        v.refresh_from_db()
        rows, _files = services.backup_rows(self.me)
        other = User.objects.create_superuser("other", "o@example.com", PW)
        services.restore(other, rows)
        note = Note.objects.get(owner=other, title="Plan")
        self.assertEqual((note.history_months, note.history_off), (6, True))
        back = note.versions.get(label="Before")
        self.assertEqual((back.pinned, back.reason, back.body, back.added, back.sections), (True, "saved", "kept", v.added, v.sections))
        self.assertEqual(back.created_at, v.created_at)
        ows = WorkSettings.for_user(other)
        self.assertEqual((ows.note_history_months, ows.note_history_minutes, ows.note_history_new), (12, 30, False))
