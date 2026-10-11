"""Queries and calculations that sit between the models and the views."""
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from .models import DailyLog, Metric, MetricValue, Profile
from .utils import day_label, day_number, format_decimal


def get_profile(user):
    """Return the user's profile, creating it if it somehow doesn't exist yet."""
    profile, _ = Profile.objects.get_or_create(
        user=user, defaults={"start_date": timezone.localdate()}
    )
    return profile


def annotate_days(logs, start_date):
    """Attach day_number and day_label to each log. Never stored, always calculated."""
    for log in logs:
        log.day_number = day_number(start_date, log.date)
        log.day_label = day_label(log.day_number)
    return logs


def _average(numbers, places):
    mean = sum(numbers, Decimal("0")) / len(numbers)
    return mean.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def weekly_summary(user, start, end):
    """
    Summarise the inclusive date range start..end for one user.

    Only recorded values are counted. A day with no value for a parameter is
    left out of that parameter's average; it is never treated as zero.
    """
    logs = DailyLog.objects.filter(user=user, date__range=(start, end))
    recorded_days = logs.count()

    values = MetricValue.objects.filter(
        log__user=user, metric__user=user, log__date__range=(start, end)
    ).select_related("metric")
    by_metric = {}
    for value in values:
        if value.value is not None:
            by_metric.setdefault(value.metric_id, []).append(value)

    rows = []
    for metric in Metric.objects.filter(user=user):
        recorded = by_metric.get(metric.id, [])
        # Inactive parameters only appear if they have data in this window.
        if not metric.is_active and not recorded:
            continue
        kind = metric.metric_type
        row = {"metric": metric, "kind": kind, "count": len(recorded), "unit": ""}
        if kind in (Metric.Type.NUMBER, Metric.Type.SCALE):
            numbers = [Decimal(v.value) for v in recorded]
            places = 2 if kind == Metric.Type.NUMBER else 1
            average = _average(numbers, places) if numbers else None
            row["average"] = format_decimal(average) if average is not None else None
            row["unit"] = metric.unit if kind == Metric.Type.NUMBER else "out of 10"
        elif kind == Metric.Type.BOOLEAN:
            row["yes_count"] = sum(1 for v in recorded if v.value is True)
        else:
            continue  # short text has nothing to average
        rows.append(row)

    reflections = [
        log
        for log in logs.order_by("-date")
        if log.has_writing
    ]
    return {
        "recorded_days": recorded_days,
        "rows": rows,
        "reflections": reflections,
        "logged_dates": set(logs.values_list("date", flat=True)),
    }
