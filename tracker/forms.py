from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import DailyLog, Metric, MetricValue, Profile
from .utils import format_decimal

DATE_FORMAT = "%Y-%m-%d"


class RegisterForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username",)


class StartDateForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["start_date"]
        labels = {"start_date": "First day of tracking (Day 1)"}
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"}, format=DATE_FORMAT)}


class MetricForm(forms.ModelForm):
    """Create or rename a parameter. The type can't change once it exists."""

    class Meta:
        model = Metric
        fields = ["name", "metric_type", "unit"]
        labels = {"name": "Name", "metric_type": "Type", "unit": "Unit (optional)"}
        widgets = {
            "name": forms.TextInput(attrs={"maxlength": 60, "placeholder": "Hours slept"}),
            "metric_type": forms.Select(attrs={"data-metric-type": ""}),
            "unit": forms.TextInput(attrs={"maxlength": 20, "placeholder": "hours"}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if self.instance.pk:
            # Changing the type would leave old values meaning something else.
            self.fields["metric_type"].disabled = True

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if not name:
            raise ValidationError("Enter a name.")
        duplicates = Metric.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("You already have a parameter with this name.")
        return name

    def clean(self):
        cleaned = super().clean()
        # Units only make sense for numbers.
        if cleaned.get("metric_type") != Metric.Type.NUMBER:
            cleaned["unit"] = ""
        else:
            cleaned["unit"] = (cleaned.get("unit") or "").strip()
        return cleaned


class DailyLogForm(forms.ModelForm):
    """
    The daily check-in. One extra field per metric is added at runtime, named
    metric_<id>. Only metrics owned by `user` can ever appear, so a posted id
    that belongs to someone else is simply ignored.
    """

    class Meta:
        model = DailyLog
        fields = ["date", "notes", "wins", "challenges", "tomorrow_priority"]
        labels = {
            "date": "Date",
            "notes": "How the day went",
            "wins": "Wins",
            "challenges": "Challenges or mistakes",
            "tomorrow_priority": "Priority for tomorrow",
        }
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format=DATE_FORMAT),
            "notes": forms.Textarea(attrs={"rows": 7}),
            "wins": forms.Textarea(attrs={"rows": 3}),
            "challenges": forms.Textarea(attrs={"rows": 3}),
            "tomorrow_priority": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.metrics = self._metrics_for_form()
        self.metric_values = {}

        existing = {}
        if self.instance.pk:
            existing = {
                v.metric_id: v for v in self.instance.values.select_related("metric")
            }
        for metric in self.metrics:
            name = f"metric_{metric.pk}"
            self.fields[name] = self._build_field(metric)
            if metric.pk in existing:
                self.initial[name] = self._initial_for(metric, existing[metric.pk])

    # -- building the dynamic fields ---------------------------------------
    def _metrics_for_form(self):
        """
        Active metrics, plus inactive ones that already hold a value on the
        entry being edited, so recorded history stays visible and editable.
        """
        owned = Metric.objects.filter(user=self.user)
        if self.instance.pk:
            return list(
                owned.filter(Q(is_active=True) | Q(values__log=self.instance)).distinct()
            )
        return list(owned.filter(is_active=True))

    def _build_field(self, metric):
        common = {"required": False, "label": metric.name}
        kind = metric.metric_type
        if kind == Metric.Type.NUMBER:
            return forms.DecimalField(
                max_digits=12,
                decimal_places=3,
                widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}),
                **common,
            )
        if kind == Metric.Type.SCALE:
            choices = [(str(n), str(n)) for n in range(1, 11)] + [("", "Not recorded")]
            return forms.ChoiceField(choices=choices, widget=forms.RadioSelect, **common)
        if kind == Metric.Type.BOOLEAN:
            choices = [("yes", "Yes"), ("no", "No"), ("", "Not recorded")]
            return forms.ChoiceField(choices=choices, widget=forms.RadioSelect, **common)
        return forms.CharField(max_length=255, **common)

    @staticmethod
    def _initial_for(metric, stored):
        value = stored.value
        if value is None:
            return None
        kind = metric.metric_type
        if kind == Metric.Type.NUMBER:
            return format_decimal(value)
        if kind == Metric.Type.SCALE:
            return str(value)
        if kind == Metric.Type.BOOLEAN:
            return "yes" if value else "no"
        return value

    def metric_rows(self):
        """What the template loops over: the metric, its bound field, and whether it's inactive."""
        return [
            {"metric": m, "field": self[f"metric_{m.pk}"], "inactive": not m.is_active}
            for m in self.metrics
        ]

    # -- validation ------------------------------------------------------------
    def clean_date(self):
        date = self.cleaned_data["date"]
        if date > timezone.localdate():
            raise ValidationError("Entries can't be dated in the future.")
        others = DailyLog.objects.filter(user=self.user, date=date)
        if self.instance.pk:
            others = others.exclude(pk=self.instance.pk)
        if others.exists():
            raise ValidationError("You already have an entry for this date.")
        return date

    @staticmethod
    def _normalise(metric, raw):
        """Turn a cleaned form value into the stored value; empty means 'not recorded' (None)."""
        kind = metric.metric_type
        if kind == Metric.Type.NUMBER:
            return raw  # Decimal or None
        if kind == Metric.Type.SCALE:
            return int(raw) if raw not in (None, "") else None
        if kind == Metric.Type.BOOLEAN:
            return {"yes": True, "no": False}.get(raw)
        text = (raw or "").strip()
        return text or None

    def clean(self):
        cleaned = super().clean()
        self.metric_values = {
            m.pk: self._normalise(m, cleaned.get(f"metric_{m.pk}")) for m in self.metrics
        }
        return cleaned

    # -- saving ------------------------------------------------------------------
    def save(self):
        """Save the log and all its metric values together, or nothing at all."""
        with transaction.atomic():
            log = super().save(commit=False)
            log.user = self.user
            log.save()
            for metric in self.metrics:
                self._store_value(log, metric, self.metric_values[metric.pk])
        return log

    @staticmethod
    def _store_value(log, metric, value):
        if value is None:
            MetricValue.objects.filter(log=log, metric=metric).delete()
            return
        columns = {
            "number_value": None,
            "scale_value": None,
            "boolean_value": None,
            "text_value": "",
        }
        columns[MetricValue.FIELD_FOR_TYPE[metric.metric_type]] = value
        MetricValue.objects.update_or_create(log=log, metric=metric, defaults=columns)
