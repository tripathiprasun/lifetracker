import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import DailyLogForm, MetricForm
from .models import DailyLog, Metric, MetricValue, Profile
from .services import weekly_summary
from .utils import day_label, day_number, format_decimal, week_window

User = get_user_model()
PASSWORD = "a-long-test-passphrase-91"


def make_user(name="alice"):
    return User.objects.create_user(username=name, password=PASSWORD)


def make_metric(user, name, kind, **extra):
    return Metric.objects.create(user=user, name=name, metric_type=kind, **extra)


def make_log(user, date, **extra):
    return DailyLog.objects.create(user=user, date=date, **extra)


def set_value(log, metric, **columns):
    return MetricValue.objects.create(log=log, metric=metric, **columns)


class AuthTests(TestCase):
    def test_register_creates_user_profile_and_logs_in(self):
        response = self.client.post(
            reverse("register"),
            {"username": "newuser", "password1": PASSWORD, "password2": PASSWORD},
        )
        self.assertRedirects(response, reverse("dashboard"))
        user = User.objects.get(username="newuser")
        self.assertEqual(user.profile.start_date, timezone.localdate())
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_register_rejects_mismatched_passwords(self):
        response = self.client.post(
            reverse("register"),
            {"username": "newuser", "password1": PASSWORD, "password2": "different-one-77"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    @override_settings(ALLOW_REGISTRATION=False)
    def test_registration_can_be_closed(self):
        response = self.client.post(
            reverse("register"),
            {"username": "newuser", "password1": PASSWORD, "password2": PASSWORD},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_login_and_logout(self):
        make_user()
        response = self.client.post(reverse("login"), {"username": "alice", "password": PASSWORD})
        self.assertRedirects(response, reverse("dashboard"))
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_login_with_wrong_password_fails(self):
        make_user()
        response = self.client.post(reverse("login"), {"username": "alice", "password": "nope-nope-nope"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_protected_pages_redirect_anonymous_users(self):
        names = ["dashboard", "journal", "log_new", "review", "settings"]
        for name in names:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse("login"), response["Location"], name)

    def test_health_check_needs_no_login(self):
        response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")


class DayNumberTests(TestCase):
    def test_start_date_is_day_one_and_next_day_is_day_two(self):
        start = datetime.date(2026, 3, 1)
        self.assertEqual(day_number(start, start), 1)
        self.assertEqual(day_number(start, datetime.date(2026, 3, 2)), 2)

    def test_missed_days_do_not_reset_the_count(self):
        start = datetime.date(2026, 3, 1)
        self.assertEqual(day_number(start, datetime.date(2026, 3, 31)), 31)

    def test_dates_before_start_have_no_day(self):
        start = datetime.date(2026, 3, 10)
        self.assertEqual(day_number(start, datetime.date(2026, 3, 9)), 0)
        self.assertEqual(day_label(0), "Before Day 1")
        self.assertEqual(day_label(5), "Day 5")

    def test_day_number_ignores_how_many_logs_exist(self):
        user = make_user()
        user.profile.start_date = datetime.date(2026, 1, 1)
        user.profile.save()
        make_log(user, datetime.date(2026, 1, 20))  # a single, backfilled log
        self.client.force_login(user)
        response = self.client.get(reverse("journal"))
        self.assertContains(response, "Day 20")

    def test_changing_start_date_renumbers_entries(self):
        user = make_user()
        user.profile.start_date = datetime.date(2026, 1, 1)
        user.profile.save()
        log = make_log(user, datetime.date(2026, 1, 10))
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("log_detail", args=[log.pk])), "Day 10")

        response = self.client.post(reverse("settings_start_date"), {"start_date": "2026-01-05"})
        self.assertRedirects(response, reverse("settings"))
        self.assertContains(self.client.get(reverse("log_detail", args=[log.pk])), "Day 6")

    def test_week_window_is_seven_calendar_days(self):
        start, end = week_window(datetime.date(2026, 3, 10))
        self.assertEqual(start, datetime.date(2026, 3, 4))
        self.assertEqual(end, datetime.date(2026, 3, 10))
        self.assertEqual((end - start).days + 1, 7)

    def test_format_decimal_trims_zeros(self):
        self.assertEqual(format_decimal(Decimal("7.500")), "7.5")
        self.assertEqual(format_decimal(Decimal("10.000")), "10")
        self.assertEqual(format_decimal(Decimal("0.250")), "0.25")


class DailyLogTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def post_data(self, **extra):
        data = {
            "date": self.today.isoformat(),
            "notes": "A steady day.",
            "wins": "",
            "challenges": "",
            "tomorrow_priority": "",
        }
        data.update(extra)
        return data

    def test_one_log_per_user_per_date_in_database(self):
        make_log(self.user, self.today)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_log(self.user, self.today)

    def test_two_users_can_log_the_same_date(self):
        other = make_user("bob")
        make_log(self.user, self.today)
        make_log(other, self.today)
        self.assertEqual(DailyLog.objects.filter(date=self.today).count(), 2)

    def test_form_rejects_duplicate_date(self):
        make_log(self.user, self.today)
        response = self.client.post(reverse("log_new"), self.post_data())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You already have an entry for this date.")
        self.assertEqual(DailyLog.objects.filter(user=self.user).count(), 1)

    def test_new_entry_page_for_existing_date_redirects_to_edit(self):
        log = make_log(self.user, self.today)
        response = self.client.get(reverse("log_new"))
        self.assertRedirects(response, reverse("log_edit", args=[log.pk]))

    def test_create_log_with_all_metric_types(self):
        sleep = make_metric(self.user, "Sleep", Metric.Type.NUMBER, unit="hours")
        mood = make_metric(self.user, "Mood", Metric.Type.SCALE)
        ran = make_metric(self.user, "Ran", Metric.Type.BOOLEAN)
        word = make_metric(self.user, "Word", Metric.Type.TEXT)
        data = self.post_data(**{
            f"metric_{sleep.pk}": "7.5",
            f"metric_{mood.pk}": "8",
            f"metric_{ran.pk}": "no",
            f"metric_{word.pk}": "  calm ",
        })
        response = self.client.post(reverse("log_new"), data)
        log = DailyLog.objects.get(user=self.user, date=self.today)
        self.assertRedirects(response, reverse("log_detail", args=[log.pk]))
        values = {v.metric_id: v for v in log.values.all()}
        self.assertEqual(values[sleep.pk].number_value, Decimal("7.5"))
        self.assertEqual(values[mood.pk].scale_value, 8)
        self.assertIs(values[ran.pk].boolean_value, False)
        self.assertEqual(values[word.pk].text_value, "calm")

    def test_incomplete_log_is_allowed(self):
        make_metric(self.user, "Sleep", Metric.Type.NUMBER)
        make_metric(self.user, "Mood", Metric.Type.SCALE)
        response = self.client.post(reverse("log_new"), self.post_data(notes=""))
        self.assertEqual(response.status_code, 302)
        log = DailyLog.objects.get(user=self.user)
        self.assertEqual(log.values.count(), 0)

    def test_unrecorded_yes_no_stores_nothing(self):
        ran = make_metric(self.user, "Ran", Metric.Type.BOOLEAN)
        self.client.post(reverse("log_new"), self.post_data(**{f"metric_{ran.pk}": ""}))
        self.assertEqual(MetricValue.objects.count(), 0)

    def test_zero_is_a_real_value_not_missing(self):
        drinks = make_metric(self.user, "Drinks", Metric.Type.NUMBER)
        self.client.post(reverse("log_new"), self.post_data(**{f"metric_{drinks.pk}": "0"}))
        value = MetricValue.objects.get()
        self.assertEqual(value.number_value, Decimal("0"))
        self.assertEqual(value.value, Decimal("0"))

    def test_invalid_scale_value_keeps_entered_data(self):
        mood = make_metric(self.user, "Mood", Metric.Type.SCALE)
        response = self.client.post(
            reverse("log_new"),
            self.post_data(notes="Keep this sentence.", **{f"metric_{mood.pk}": "11"}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Keep this sentence.")
        self.assertFalse(DailyLog.objects.exists())

    def test_invalid_number_is_rejected(self):
        sleep = make_metric(self.user, "Sleep", Metric.Type.NUMBER)
        response = self.client.post(
            reverse("log_new"), self.post_data(**{f"metric_{sleep.pk}": "lots"})
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DailyLog.objects.exists())

    def test_future_date_is_rejected(self):
        tomorrow = self.today + datetime.timedelta(days=1)
        response = self.client.post(reverse("log_new"), self.post_data(date=tomorrow.isoformat()))
        self.assertContains(response, "can&#x27;t be dated in the future")
        self.assertFalse(DailyLog.objects.exists())

    def test_backfilling_a_past_date_works(self):
        past = self.today - datetime.timedelta(days=12)
        response = self.client.post(reverse("log_new"), self.post_data(date=past.isoformat()))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(DailyLog.objects.filter(user=self.user, date=past).exists())

    def test_edit_updates_values_and_clearing_removes_them(self):
        sleep = make_metric(self.user, "Sleep", Metric.Type.NUMBER)
        mood = make_metric(self.user, "Mood", Metric.Type.SCALE)
        log = make_log(self.user, self.today, notes="Before")
        set_value(log, sleep, number_value=Decimal("6"))
        set_value(log, mood, scale_value=4)

        response = self.client.post(
            reverse("log_edit", args=[log.pk]),
            self.post_data(notes="After", **{f"metric_{sleep.pk}": "8", f"metric_{mood.pk}": ""}),
        )
        self.assertRedirects(response, reverse("log_detail", args=[log.pk]))
        log.refresh_from_db()
        self.assertEqual(log.notes, "After")
        self.assertEqual(MetricValue.objects.get(log=log, metric=sleep).number_value, Decimal("8"))
        self.assertFalse(MetricValue.objects.filter(log=log, metric=mood).exists())
        self.assertEqual(DailyLog.objects.filter(user=self.user).count(), 1)

    def test_edit_form_shows_existing_values(self):
        sleep = make_metric(self.user, "Sleep", Metric.Type.NUMBER)
        log = make_log(self.user, self.today)
        set_value(log, sleep, number_value=Decimal("7.500"))
        response = self.client.get(reverse("log_edit", args=[log.pk]))
        self.assertContains(response, 'value="7.5"')

    def test_edit_can_move_to_another_free_date_but_not_a_taken_one(self):
        yesterday = self.today - datetime.timedelta(days=1)
        log = make_log(self.user, self.today)
        make_log(self.user, yesterday)
        response = self.client.post(reverse("log_edit", args=[log.pk]), self.post_data(date=yesterday.isoformat()))
        self.assertContains(response, "You already have an entry for this date.")

    def test_failed_save_rolls_back_the_whole_entry(self):
        sleep = make_metric(self.user, "Sleep", Metric.Type.NUMBER)
        form = DailyLogForm(self.post_data(**{f"metric_{sleep.pk}": "7"}), user=self.user)
        self.assertTrue(form.is_valid())
        with mock.patch.object(DailyLogForm, "_store_value", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                form.save()
        self.assertFalse(DailyLog.objects.exists())


class MetricTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_create_metric_via_settings(self):
        response = self.client.post(
            reverse("metric_create"), {"name": "Sleep", "metric_type": "number", "unit": "hours"}
        )
        self.assertRedirects(response, reverse("settings"))
        metric = Metric.objects.get(user=self.user)
        self.assertEqual((metric.name, metric.unit, metric.is_active), ("Sleep", "hours", True))

    def test_new_metrics_get_increasing_order(self):
        for name in ("A", "B", "C"):
            self.client.post(reverse("metric_create"), {"name": name, "metric_type": "text"})
        orders = list(Metric.objects.filter(user=self.user).order_by("order").values_list("name", flat=True))
        self.assertEqual(orders, ["A", "B", "C"])

    def test_name_must_be_unique_per_user_ignoring_case(self):
        make_metric(self.user, "Sleep", Metric.Type.NUMBER)
        response = self.client.post(reverse("metric_create"), {"name": "  sleep ", "metric_type": "number"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "already have a parameter", status_code=400)
        self.assertEqual(Metric.objects.filter(user=self.user).count(), 1)

    def test_another_user_may_use_the_same_name(self):
        make_metric(make_user("bob"), "Sleep", Metric.Type.NUMBER)
        response = self.client.post(reverse("metric_create"), {"name": "Sleep", "metric_type": "number"})
        self.assertEqual(response.status_code, 302)

    def test_database_enforces_unique_name_per_user(self):
        make_metric(self.user, "Sleep", Metric.Type.NUMBER)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_metric(self.user, "Sleep", Metric.Type.TEXT)

    def test_blank_name_is_rejected(self):
        response = self.client.post(reverse("metric_create"), {"name": "   ", "metric_type": "number"})
        self.assertEqual(response.status_code, 400)

    def test_unit_is_dropped_for_non_number_types(self):
        self.client.post(reverse("metric_create"), {"name": "Mood", "metric_type": "scale", "unit": "points"})
        self.assertEqual(Metric.objects.get().unit, "")

    def test_rename_keeps_type(self):
        metric = make_metric(self.user, "Sleep", Metric.Type.NUMBER, unit="hours")
        self.client.post(
            reverse("metric_edit", args=[metric.pk]),
            {"name": "Sleep time", "metric_type": "text", "unit": "hrs"},
        )
        metric.refresh_from_db()
        self.assertEqual(metric.name, "Sleep time")
        self.assertEqual(metric.metric_type, Metric.Type.NUMBER)
        self.assertEqual(metric.unit, "hrs")

    def test_rename_to_own_name_is_allowed(self):
        metric = make_metric(self.user, "Sleep", Metric.Type.NUMBER)
        form = MetricForm({"name": "Sleep", "unit": ""}, instance=metric, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_toggle_activation(self):
        metric = make_metric(self.user, "Sleep", Metric.Type.NUMBER)
        self.client.post(reverse("metric_toggle", args=[metric.pk]))
        metric.refresh_from_db()
        self.assertFalse(metric.is_active)
        self.client.post(reverse("metric_toggle", args=[metric.pk]))
        metric.refresh_from_db()
        self.assertTrue(metric.is_active)

    def test_toggle_requires_post(self):
        metric = make_metric(self.user, "Sleep", Metric.Type.NUMBER)
        self.assertEqual(self.client.get(reverse("metric_toggle", args=[metric.pk])).status_code, 405)
        metric.refresh_from_db()
        self.assertTrue(metric.is_active)

    def test_inactive_metric_is_missing_from_new_entry_form(self):
        make_metric(self.user, "Sleep", Metric.Type.NUMBER, is_active=False)
        make_metric(self.user, "Mood", Metric.Type.SCALE)
        form = DailyLogForm(user=self.user)
        self.assertEqual([m.name for m in form.metrics], ["Mood"])

    def test_inactive_metric_with_value_still_appears_when_editing_that_entry(self):
        old = make_metric(self.user, "Old habit", Metric.Type.NUMBER, is_active=False)
        log = make_log(self.user, timezone.localdate())
        set_value(log, old, number_value=Decimal("3"))
        other_log = make_log(self.user, timezone.localdate() - datetime.timedelta(days=1))
        self.assertIn(old, DailyLogForm(instance=log, user=self.user).metrics)
        self.assertNotIn(old, DailyLogForm(instance=other_log, user=self.user).metrics)

    def test_deactivating_keeps_history(self):
        metric = make_metric(self.user, "Sleep", Metric.Type.NUMBER)
        log = make_log(self.user, timezone.localdate())
        set_value(log, metric, number_value=Decimal("7"))
        self.client.post(reverse("metric_toggle", args=[metric.pk]))
        self.assertEqual(MetricValue.objects.count(), 1)

    def test_delete_asks_for_confirmation_before_deleting(self):
        metric = make_metric(self.user, "Sleep", Metric.Type.NUMBER)
        log = make_log(self.user, timezone.localdate())
        set_value(log, metric, number_value=Decimal("7"))
        response = self.client.get(reverse("metric_delete", args=[metric.pk]))
        self.assertContains(response, "permanently deletes")
        self.assertTrue(Metric.objects.filter(pk=metric.pk).exists())

    def test_delete_removes_metric_and_its_values_but_not_the_log(self):
        metric = make_metric(self.user, "Sleep", Metric.Type.NUMBER)
        keep = make_metric(self.user, "Mood", Metric.Type.SCALE)
        log = make_log(self.user, timezone.localdate(), notes="Stays")
        set_value(log, metric, number_value=Decimal("7"))
        set_value(log, keep, scale_value=6)
        self.client.post(reverse("metric_delete", args=[metric.pk]))
        self.assertFalse(Metric.objects.filter(pk=metric.pk).exists())
        self.assertEqual(list(MetricValue.objects.values_list("metric_id", flat=True)), [keep.pk])
        self.assertTrue(DailyLog.objects.filter(pk=log.pk, notes="Stays").exists())

    def test_move_swaps_order(self):
        a = make_metric(self.user, "A", Metric.Type.TEXT, order=0)
        b = make_metric(self.user, "B", Metric.Type.TEXT, order=0)  # tied on purpose
        self.client.post(reverse("metric_move", args=[b.pk]), {"direction": "up"})
        names = [m.name for m in Metric.objects.filter(user=self.user)]
        self.assertEqual(names, ["B", "A"])

    def test_metric_value_rejects_a_metric_from_another_user(self):
        other = make_user("bob")
        foreign_metric = make_metric(other, "Sleep", Metric.Type.NUMBER)
        log = make_log(self.user, timezone.localdate())
        with self.assertRaises(ValidationError):
            set_value(log, foreign_metric, number_value=Decimal("7"))
        self.assertEqual(MetricValue.objects.count(), 0)

    def test_metric_value_rejects_wrong_column_for_type(self):
        metric = make_metric(self.user, "Mood", Metric.Type.SCALE)
        log = make_log(self.user, timezone.localdate())
        with self.assertRaises(ValidationError):
            set_value(log, metric, number_value=Decimal("5"))

    def test_one_value_per_metric_per_log(self):
        metric = make_metric(self.user, "Mood", Metric.Type.SCALE)
        log = make_log(self.user, timezone.localdate())
        set_value(log, metric, scale_value=5)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                set_value(log, metric, scale_value=6)


class IsolationTests(TestCase):
    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.today = timezone.localdate()
        self.metric = make_metric(self.alice, "Sleep", Metric.Type.NUMBER)
        self.log = make_log(self.alice, self.today, notes="Alice's private note")
        set_value(self.log, self.metric, number_value=Decimal("7"))
        self.client.force_login(self.bob)

    def test_other_users_log_returns_404(self):
        self.assertEqual(self.client.get(reverse("log_detail", args=[self.log.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("log_edit", args=[self.log.pk])).status_code, 404)

    def test_cannot_edit_other_users_log_by_posting(self):
        response = self.client.post(
            reverse("log_edit", args=[self.log.pk]),
            {"date": self.today.isoformat(), "notes": "Hijacked"},
        )
        self.assertEqual(response.status_code, 404)
        self.log.refresh_from_db()
        self.assertEqual(self.log.notes, "Alice's private note")

    def test_other_users_metric_endpoints_return_404(self):
        for name in ("metric_edit", "metric_delete"):
            self.assertEqual(self.client.get(reverse(name, args=[self.metric.pk])).status_code, 404, name)
        for name in ("metric_toggle", "metric_move", "metric_delete", "metric_edit"):
            self.assertEqual(self.client.post(reverse(name, args=[self.metric.pk])).status_code, 404, name)
        self.metric.refresh_from_db()
        self.assertTrue(self.metric.is_active)
        self.assertEqual(Metric.objects.filter(pk=self.metric.pk).count(), 1)

    def test_journal_dashboard_and_review_show_only_own_data(self):
        for name in ("journal", "dashboard", "review", "settings"):
            response = self.client.get(reverse(name))
            self.assertNotContains(response, "Alice&#x27;s private note", msg_prefix=name)
            self.assertNotContains(response, "Sleep", msg_prefix=name)

    def test_posting_another_users_metric_id_stores_nothing(self):
        response = self.client.post(
            reverse("log_new"),
            {"date": self.today.isoformat(), "notes": "Bob's day", f"metric_{self.metric.pk}": "9"},
        )
        self.assertEqual(response.status_code, 302)
        bobs_log = DailyLog.objects.get(user=self.bob)
        self.assertEqual(bobs_log.values.count(), 0)
        self.assertEqual(MetricValue.objects.filter(metric=self.metric).count(), 1)  # Alice's only

    def test_each_user_has_their_own_start_date(self):
        self.client.post(reverse("settings_start_date"), {"start_date": "2020-01-01"})
        self.assertEqual(Profile.objects.get(user=self.bob).start_date, datetime.date(2020, 1, 1))
        self.assertNotEqual(Profile.objects.get(user=self.alice).start_date, datetime.date(2020, 1, 1))


class WeeklyReviewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.end = datetime.date(2026, 6, 10)
        self.start = datetime.date(2026, 6, 4)
        self.sleep = make_metric(self.user, "Sleep", Metric.Type.NUMBER, unit="hours")
        self.mood = make_metric(self.user, "Mood", Metric.Type.SCALE)
        self.ran = make_metric(self.user, "Ran", Metric.Type.BOOLEAN)

    def day(self, offset):
        return self.start + datetime.timedelta(days=offset)

    def row(self, summary, metric):
        return next(r for r in summary["rows"] if r["metric"] == metric)

    def test_missing_values_are_not_counted_as_zero(self):
        a = make_log(self.user, self.day(0))
        b = make_log(self.user, self.day(1))
        make_log(self.user, self.day(2))  # logged, but no sleep value
        set_value(a, self.sleep, number_value=Decimal("8"))
        set_value(b, self.sleep, number_value=Decimal("6"))
        summary = weekly_summary(self.user, self.start, self.end)
        row = self.row(summary, self.sleep)
        self.assertEqual(row["average"], "7")
        self.assertEqual(row["count"], 2)
        self.assertEqual(summary["recorded_days"], 3)

    def test_explicit_zero_is_included_in_the_average(self):
        a = make_log(self.user, self.day(0))
        b = make_log(self.user, self.day(1))
        set_value(a, self.sleep, number_value=Decimal("0"))
        set_value(b, self.sleep, number_value=Decimal("4"))
        self.assertEqual(self.row(weekly_summary(self.user, self.start, self.end), self.sleep)["average"], "2")

    def test_scale_average_has_one_decimal(self):
        for offset, value in enumerate((7, 8, 8)):
            set_value(make_log(self.user, self.day(offset)), self.mood, scale_value=value)
        row = self.row(weekly_summary(self.user, self.start, self.end), self.mood)
        self.assertEqual(row["average"], "7.7")
        self.assertEqual(row["unit"], "out of 10")

    def test_entries_outside_the_window_are_ignored(self):
        before = make_log(self.user, self.start - datetime.timedelta(days=1))
        after = make_log(self.user, self.end + datetime.timedelta(days=1))
        set_value(before, self.sleep, number_value=Decimal("1"))
        set_value(after, self.sleep, number_value=Decimal("1"))
        summary = weekly_summary(self.user, self.start, self.end)
        self.assertEqual(summary["recorded_days"], 0)
        self.assertIsNone(self.row(summary, self.sleep)["average"])

    def test_no_values_means_no_average_not_zero(self):
        summary = weekly_summary(self.user, self.start, self.end)
        self.assertIsNone(self.row(summary, self.sleep)["average"])

    def test_yes_no_counts(self):
        for offset, value in enumerate((True, False, True)):
            set_value(make_log(self.user, self.day(offset)), self.ran, boolean_value=value)
        row = self.row(weekly_summary(self.user, self.start, self.end), self.ran)
        self.assertEqual((row["yes_count"], row["count"]), (2, 3))

    def test_inactive_metric_appears_only_when_it_has_data(self):
        self.mood.is_active = False
        self.mood.save()
        summary = weekly_summary(self.user, self.start, self.end)
        self.assertNotIn(self.mood, [r["metric"] for r in summary["rows"]])
        set_value(make_log(self.user, self.day(0)), self.mood, scale_value=5)
        summary = weekly_summary(self.user, self.start, self.end)
        self.assertIn(self.mood, [r["metric"] for r in summary["rows"]])

    def test_reflections_only_include_entries_with_writing(self):
        make_log(self.user, self.day(0), notes="Wrote something")
        make_log(self.user, self.day(1))
        summary = weekly_summary(self.user, self.start, self.end)
        self.assertEqual(len(summary["reflections"]), 1)

    def test_averages_never_mix_users(self):
        other = make_user("bob")
        other_metric = make_metric(other, "Sleep", Metric.Type.NUMBER)
        set_value(make_log(other, self.day(0)), other_metric, number_value=Decimal("1"))
        set_value(make_log(self.user, self.day(0)), self.sleep, number_value=Decimal("9"))
        row = self.row(weekly_summary(self.user, self.start, self.end), self.sleep)
        self.assertEqual(row["average"], "9")

    def test_review_page_renders_with_labels_and_units(self):
        today = timezone.localdate()
        log = make_log(self.user, today, notes="Steady.")
        set_value(log, self.sleep, number_value=Decimal("7.5"))
        self.client.force_login(self.user)
        response = self.client.get(reverse("review"))
        self.assertContains(response, "Average 7.5 hours")
        self.assertContains(response, "1 of 7 days recorded")
        self.assertContains(response, "not counted as zero")
        self.assertContains(response, "Steady.")

    def test_review_page_empty_state(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("review"))
        self.assertContains(response, "0 of 7 days recorded")
        self.assertContains(response, "No written reflections")


class DashboardTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def test_empty_dashboard_guides_the_user(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Write today’s entry")
        self.assertContains(response, "Add your first parameter")
        self.assertContains(response, "No entries yet")
        self.assertContains(response, "Day 1")

    def test_dashboard_reflects_real_data(self):
        self.user.profile.start_date = self.today - datetime.timedelta(days=9)
        self.user.profile.save()
        make_metric(self.user, "Sleep", Metric.Type.NUMBER, unit="hours")
        make_metric(self.user, "Hidden", Metric.Type.TEXT, is_active=False)
        make_log(self.user, self.today, notes="Today went fine.")
        make_log(self.user, self.today - datetime.timedelta(days=3), notes="Older entry.")
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Day 10")
        self.assertContains(response, "2 recorded of 10 days")
        self.assertContains(response, "Edit today’s entry")
        self.assertContains(response, "Sleep")
        self.assertNotContains(response, "Hidden")
        self.assertContains(response, "Today went fine.")
        self.assertContains(response, "Older entry.")

    def test_journal_lists_newest_first_with_day_numbers(self):
        self.user.profile.start_date = self.today - datetime.timedelta(days=4)
        self.user.profile.save()
        make_log(self.user, self.today - datetime.timedelta(days=2), notes="Second entry")
        make_log(self.user, self.today, notes="Latest entry")
        response = self.client.get(reverse("journal"))
        content = response.content.decode()
        self.assertLess(content.index("Latest entry"), content.index("Second entry"))
        self.assertContains(response, "Day 5")
        self.assertContains(response, "Day 3")

    def test_journal_empty_state(self):
        self.assertContains(self.client.get(reverse("journal")), "The journal is empty")

    def test_log_detail_shows_values_and_text(self):
        metric = make_metric(self.user, "Sleep", Metric.Type.NUMBER, unit="hours")
        mood = make_metric(self.user, "Mood", Metric.Type.SCALE)
        log = make_log(self.user, self.today, notes="Quiet day", wins="Finished the draft")
        set_value(log, metric, number_value=Decimal("7.5"))
        set_value(log, mood, scale_value=8)
        response = self.client.get(reverse("log_detail", args=[log.pk]))
        self.assertContains(response, "7.5 hours")
        self.assertContains(response, "8 out of 10")
        self.assertContains(response, "Quiet day")
        self.assertContains(response, "Finished the draft")

    def test_unknown_page_uses_custom_404(self):
        response = self.client.get(reverse("log_detail", args=[99999]))
        self.assertEqual(response.status_code, 404)
