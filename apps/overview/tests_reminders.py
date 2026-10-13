"""Morning money reminders: what's late and due soon, by email, only when
there is something, once a day."""
from datetime import datetime, timedelta
from decimal import Decimal as D
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.creditors.models import Creditor, Transaction as CT
from apps.debtors.models import Debtor, Transaction as DT

from . import reminders

TODAY = timezone.localdate()


def at(hour):
    return timezone.make_aware(datetime.combine(TODAY, datetime.min.time()).replace(hour=hour))


class ReminderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rahim", "rahim@example.com", "pw-123456789", first_name="Rahim")
        self.client.force_login(self.user)

    def owe(self, name, amount, due_in):
        c = Creditor.objects.create(user=self.user, name=name, due_date=TODAY + timedelta(days=due_in))
        CT.objects.create(creditor=c, transaction_type=CT.BORROW, amount=D(amount), date=TODAY - timedelta(days=40))
        return c

    def lent(self, name, amount, due_in):
        d = Debtor.objects.create(user=self.user, name=name, due_date=TODAY + timedelta(days=due_in))
        DT.objects.create(debtor=d, transaction_type=DT.LEND, amount=D(amount), date=TODAY - timedelta(days=40))
        return d

    def turn_on(self):
        UserProfile.objects.filter(user=self.user).update(money_reminders=True)

    def test_what_it_says(self):
        self.owe("Karim bhai", "5000", -3)
        self.lent("Salam", "2000", 0)
        self.owe("Grocery shop", "1200", 5)
        r = reminders.build(self.user, TODAY)
        self.assertEqual([i.title for i in r.late], ["Karim bhai"])
        self.assertEqual([i.title for i in r.due_today], ["Salam"])
        self.assertEqual([i.title for d in r.soon for i in d.items], ["Grocery shop"])
        self.assertEqual(r.to_pay, D("5000"))
        self.assertEqual(r.to_collect, D("2000"))
        self.assertEqual(r.headline(), "1 late · 1 due today · 1 more this week")
        self.assertTrue(r.worth_sending)

    def test_quiet_days_send_nothing(self):
        self.owe("Far away", "5000", 20)
        r = reminders.build(self.user, TODAY)
        self.assertFalse(r.worth_sending)
        self.assertEqual(reminders.send(self.user, TODAY), "nothing")
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(UserProfile.objects.get(user=self.user).reminders_sent_on, TODAY)   # not worked out again today

    def test_due_in_a_few_days_is_enough(self):
        self.owe("Karim bhai", "5000", 3)
        self.assertTrue(reminders.build(self.user, TODAY).worth_sending)

    def test_the_email(self):
        self.owe("Karim bhai", "5000", -3)
        self.assertEqual(reminders.send(self.user, TODAY), "sent")
        m = mail.outbox[0]
        self.assertIn("1 late", m.subject)
        self.assertIn("Good morning Rahim", m.body)
        self.assertIn("Karim bhai", m.body)
        self.assertIn("−৳5,000", m.body)
        html = m.alternatives[0][0]
        self.assertIn("Karim bhai", html)
        self.assertIn(reverse("upcoming"), html)

    def test_bangla(self):
        UserProfile.objects.filter(user=self.user).update(language="bn")
        self.owe("Karim bhai", "5000", -3)
        reminders.send(self.user, TODAY)
        self.assertIn("দেরি", mail.outbox[0].subject)

    def test_home_sends_it_once_after_the_hour(self):
        self.turn_on()
        self.owe("Karim bhai", "5000", -3)
        with mock.patch("apps.overview.reminders.timezone.localtime", return_value=at(6)):
            self.client.get(reverse("home"))
        self.assertEqual(len(mail.outbox), 0)                     # too early
        with mock.patch("apps.overview.reminders.timezone.localtime", return_value=at(9)):
            self.client.get(reverse("home"))
            self.client.get(reverse("home"))
        self.assertEqual(len(mail.outbox), 1)

    def test_not_when_off_or_without_email(self):
        self.owe("Karim bhai", "5000", -3)
        with mock.patch("apps.overview.reminders.timezone.localtime", return_value=at(9)):
            self.client.get(reverse("home"))
            self.turn_on()
            User.objects.filter(pk=self.user.pk).update(email="")
            self.client.get(reverse("home"))
        self.assertEqual(len(mail.outbox), 0)

    def test_command(self):
        self.turn_on()
        self.owe("Karim bhai", "5000", -3)
        quiet = User.objects.create_user("quiet", "quiet@example.com", "pw-123456789")
        UserProfile.objects.filter(user=quiet).update(money_reminders=True)
        User.objects.create_user("off", "off@example.com", "pw-123456789")
        out = StringIO()
        call_command("send_money_reminders", stdout=out)
        self.assertIn("sent 1, nothing to say 1", out.getvalue())
        self.assertEqual([m.to for m in mail.outbox], [["rahim@example.com"]])
        out = StringIO()
        call_command("send_money_reminders", stdout=out)                # again: nobody twice
        self.assertIn("sent 0, nothing to say 0", out.getvalue())

    def test_turn_on_off_and_send_now(self):
        r = self.client.get(reverse("upcoming"))
        self.assertContains(r, 'data-reminders="off"')
        r = self.client.post(reverse("money_reminders"), {"action": "on"}, follow=True)
        self.assertContains(r, "Morning reminders are on")
        self.assertContains(r, 'data-reminders="on"')
        r = self.client.post(reverse("money_reminders"), {"action": "send"}, follow=True)   # even with nothing due
        self.assertContains(r, "Sent to rahim@example.com")
        self.assertIn("Nothing due this week", mail.outbox[0].subject)
        self.client.post(reverse("money_reminders"), {"action": "off"})
        self.assertFalse(UserProfile.objects.get(user=self.user).money_reminders)

    def test_needs_an_email(self):
        User.objects.filter(pk=self.user.pk).update(email="")
        r = self.client.get(reverse("upcoming"))
        self.assertContains(r, "Add your email under Account")
        r = self.client.post(reverse("money_reminders"), {"action": "on"}, follow=True)
        self.assertContains(r, "Add your email first")
        self.assertFalse(UserProfile.objects.get(user=self.user).money_reminders)

    def test_only_your_own_money(self):
        other = User.objects.create_user("other", "other@example.com", "pw-123456789")
        self.owe("Karim bhai", "5000", -3)
        self.assertEqual(reminders.build(other, TODAY).late, [])
