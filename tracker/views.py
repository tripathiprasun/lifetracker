import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import DailyLogForm, MetricForm, RegisterForm, StartDateForm
from .models import DailyLog, Metric
from .services import annotate_days, get_profile, weekly_summary
from .utils import day_label, day_number, week_window


def healthz(request):
    """Plain 'ok' for Render's health check. No login, no database."""
    return HttpResponse("ok", content_type="text/plain")


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if not settings.ALLOW_REGISTRATION:
        return render(request, "registration/register.html", {"closed": True}, status=403)
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Your account is ready. Day 1 is today.")
            return redirect("dashboard")
    else:
        form = RegisterForm()
    return render(request, "registration/register.html", {"form": form})


# --------------------------------------------------------------------------
# Dashboard, journal, entries
# --------------------------------------------------------------------------
@login_required
def dashboard(request):
    user = request.user
    profile = get_profile(user)
    today = timezone.localdate()
    today_number = day_number(profile.start_date, today)

    logs = DailyLog.objects.filter(user=user)
    recent = annotate_days(list(logs[:5]), profile.start_date)
    context = {
        "today": today,
        "profile": profile,
        "today_number": today_number,
        "today_label": day_label(today_number),
        "total_recorded": logs.count(),
        "today_log": logs.filter(date=today).first(),
        "metrics": Metric.objects.filter(user=user, is_active=True),
        "recent": recent,
    }
    return render(request, "tracker/dashboard.html", context)


@login_required
def journal(request):
    profile = get_profile(request.user)
    paginator = Paginator(DailyLog.objects.filter(user=request.user), 30)
    page = paginator.get_page(request.GET.get("page"))
    annotate_days(page.object_list, profile.start_date)
    return render(request, "tracker/journal.html", {"page": page})


def _parse_date(raw, fallback):
    try:
        return datetime.date.fromisoformat(raw)
    except (TypeError, ValueError):
        return fallback


def _log_form_page(request, form, log, profile):
    chosen = form["date"].value()
    shown = chosen if isinstance(chosen, datetime.date) else _parse_date(chosen, timezone.localdate())
    number = day_number(profile.start_date, shown)
    return render(
        request,
        "tracker/log_form.html",
        {
            "form": form,
            "log": log,
            "profile": profile,
            "day_label": day_label(number),
        },
    )


@login_required
def log_new(request):
    profile = get_profile(request.user)
    today = timezone.localdate()
    if request.method == "POST":
        form = DailyLogForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                log = form.save()
            except IntegrityError:
                # Two saves for the same date raced each other.
                form.add_error("date", "You already have an entry for this date.")
            else:
                messages.success(request, "Entry saved.")
                return redirect("log_detail", pk=log.pk)
        return _log_form_page(request, form, None, profile)

    chosen = _parse_date(request.GET.get("date"), today)
    if chosen > today:
        chosen = today
    existing = DailyLog.objects.filter(user=request.user, date=chosen).first()
    if existing:
        return redirect("log_edit", pk=existing.pk)
    form = DailyLogForm(user=request.user, initial={"date": chosen})
    return _log_form_page(request, form, None, profile)


@login_required
def log_detail(request, pk):
    profile = get_profile(request.user)
    log = get_object_or_404(DailyLog, pk=pk, user=request.user)
    annotate_days([log], profile.start_date)
    values = list(
        log.values.filter(metric__user=request.user)
        .select_related("metric")
        .order_by("metric__order", "metric__name")
    )
    owned = DailyLog.objects.filter(user=request.user)
    context = {
        "log": log,
        "values": [v for v in values if v.value is not None],
        "older": owned.filter(date__lt=log.date).order_by("-date").first(),
        "newer": owned.filter(date__gt=log.date).order_by("date").first(),
    }
    return render(request, "tracker/log_detail.html", context)


@login_required
def log_edit(request, pk):
    profile = get_profile(request.user)
    log = get_object_or_404(DailyLog, pk=pk, user=request.user)
    if request.method == "POST":
        form = DailyLogForm(request.POST, instance=log, user=request.user)
        if form.is_valid():
            try:
                form.save()
            except IntegrityError:
                form.add_error("date", "You already have an entry for this date.")
            else:
                messages.success(request, "Entry updated.")
                return redirect("log_detail", pk=log.pk)
    else:
        form = DailyLogForm(instance=log, user=request.user)
    return _log_form_page(request, form, log, profile)


# --------------------------------------------------------------------------
# Weekly review
# --------------------------------------------------------------------------
@login_required
def review(request):
    profile = get_profile(request.user)
    today = timezone.localdate()
    start, end = week_window(today)
    summary = weekly_summary(request.user, start, end)

    owned = {
        log.date: log
        for log in DailyLog.objects.filter(user=request.user, date__range=(start, end))
    }
    days = []
    for offset in range(7):
        date = start + datetime.timedelta(days=offset)
        days.append({"date": date, "log": owned.get(date), "is_today": date == today})

    reflections = annotate_days(summary["reflections"], profile.start_date)
    context = {
        "start": start,
        "end": end,
        "days": days,
        "recorded_days": summary["recorded_days"],
        "rows": summary["rows"],
        "reflections": reflections,
    }
    return render(request, "tracker/review.html", context)


# --------------------------------------------------------------------------
# Settings and parameters
# --------------------------------------------------------------------------
def _settings_page(request, start_form=None, metric_form=None, status=200):
    profile = get_profile(request.user)
    metrics = Metric.objects.filter(user=request.user).annotate(value_count=Count("values"))
    context = {
        "start_form": start_form or StartDateForm(instance=profile),
        "metric_form": metric_form or MetricForm(user=request.user),
        "metrics": list(metrics),
        "profile": profile,
    }
    return render(request, "tracker/settings.html", context, status=status)


@login_required
def settings_view(request):
    return _settings_page(request)


@login_required
@require_POST
def settings_start_date(request):
    profile = get_profile(request.user)
    form = StartDateForm(request.POST, instance=profile)
    if form.is_valid():
        form.save()
        messages.success(request, "Start date updated. Day numbers have been recalculated.")
        return redirect("settings")
    return _settings_page(request, start_form=form, status=400)


@login_required
@require_POST
def metric_create(request):
    form = MetricForm(request.POST, user=request.user)
    if form.is_valid():
        metric = form.save(commit=False)
        metric.user = request.user
        highest = Metric.objects.filter(user=request.user).aggregate(top=Max("order"))["top"]
        metric.order = (highest or 0) + 1
        metric.save()
        messages.success(request, f"Added “{metric.name}”.")
        return redirect("settings")
    return _settings_page(request, metric_form=form, status=400)


@login_required
def metric_edit(request, pk):
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    if request.method == "POST":
        form = MetricForm(request.POST, instance=metric, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Parameter updated.")
            return redirect("settings")
    else:
        form = MetricForm(instance=metric, user=request.user)
    return render(request, "tracker/metric_form.html", {"form": form, "metric": metric})


@login_required
@require_POST
def metric_toggle(request, pk):
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    metric.is_active = not metric.is_active
    metric.save(update_fields=["is_active"])
    state = "active again" if metric.is_active else "inactive. Past values are kept"
    messages.success(request, f"“{metric.name}” is {state}.")
    return redirect("settings")


@login_required
@require_POST
def metric_move(request, pk):
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    direction = request.POST.get("direction")
    ordered = list(Metric.objects.filter(user=request.user))
    index = next(i for i, m in enumerate(ordered) if m.pk == metric.pk)
    swap_with = index - 1 if direction == "up" else index + 1 if direction == "down" else None
    if swap_with is not None and 0 <= swap_with < len(ordered):
        ordered[index], ordered[swap_with] = ordered[swap_with], ordered[index]
    # Renumber everything so equal or gapped order values can't cause surprises.
    for position, item in enumerate(ordered):
        item.order = position
    Metric.objects.bulk_update(ordered, ["order"])
    return redirect("settings")


@login_required
def metric_delete(request, pk):
    metric = get_object_or_404(Metric, pk=pk, user=request.user)
    if request.method == "POST":
        name = metric.name
        metric.delete()  # its recorded values are deleted with it
        messages.success(request, f"Deleted “{name}” and its recorded values.")
        return redirect("settings")
    return render(
        request,
        "tracker/metric_confirm_delete.html",
        {"metric": metric, "value_count": metric.values.count()},
    )
