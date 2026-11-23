"""A note's card shows its lines with their shape: a heading bold, a list as a list. An empty "- " line
(a template's gap, like "Learnt today:\\n- ") used to leave a lone dot pressed against the next line."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from ..templatetags.work import note_card_lines


def card(body, title="Daily"):
    return note_card_lines(SimpleNamespace(title=title, body=body))


class NoteCardLinesTests(SimpleTestCase):
    def test_a_list_keeps_its_bullets(self):
        rows = card("## Notes\n- milk\n- bread")
        self.assertEqual([(r["kind"], r["text"]) for r in rows], [("h", "Notes"), ("li", "milk"), ("li", "bread")])

    def test_an_empty_bullet_is_a_gap_not_a_dot(self):
        rows = card("## Notes\n- \n## Learnt today")
        self.assertEqual([r["kind"] for r in rows], ["h", "", "h"])
        self.assertNotIn("li", [r["kind"] for r in rows])

    def test_numbered_blanks_still_count_up(self):
        rows = card("## Top 3 today\n1. \n2. \n3. ")
        self.assertEqual([r["text"] for r in rows[1:]], ["1. ", "2. ", "3. "])
