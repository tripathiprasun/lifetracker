from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .utils import format_decimal


class Profile(models.Model):
    """Per-user settings. The start date is Day 1 of the user's tracking."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    start_date = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user}"


class Metric(models.Model):
    """A parameter the user tracks every day, such as sleep or mood."""

    class Type(models.TextChoices):
        NUMBER = "number", "Number"
        SCALE = "scale", "Scale from 1 to 10"
        BOOLEAN = "boolean", "Yes or no"
        TEXT = "text", "Short text"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="metrics"
    )
    name = models.CharField(max_length=60)
    metric_type = models.CharField(max_length=10, choices=Type.choices)
    unit = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"], name="unique_metric_name_per_user"
            )
        ]

    def __str__(self):
        return self.name


class DailyLog(models.Model):
    """One journal entry per user per calendar date."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="logs"
    )
    date = models.DateField()
    notes = models.TextField(blank=True)
    wins = models.TextField(blank=True)
    challenges = models.TextField(blank=True)
    tomorrow_priority = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "date"], name="unique_log_per_user_per_date"
            )
        ]

    def __str__(self):
        return f"{self.user} {self.date}"

    @property
    def has_writing(self):
        return any(
            text.strip()
            for text in (self.notes, self.wins, self.challenges, self.tomorrow_priority)
        )

    @property
    def preview(self):
        """First piece of writing in the entry, for list views."""
        for text in (self.notes, self.wins, self.challenges, self.tomorrow_priority):
            if text.strip():
                return text.strip()
        return ""


class MetricValue(models.Model):
    """
    A value recorded for one metric on one day.

    Only the column that matches the metric's type is used; the others stay
    empty. A metric with no recorded value simply has no row, so a missing
    value is never confused with zero.
    """

    log = models.ForeignKey(DailyLog, on_delete=models.CASCADE, related_name="values")
    metric = models.ForeignKey(Metric, on_delete=models.CASCADE, related_name="values")
    number_value = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True
    )
    scale_value = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    boolean_value = models.BooleanField(null=True, blank=True)
    text_value = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["log", "metric"], name="unique_value_per_metric_per_log"
            )
        ]

    def __str__(self):
        return f"{self.metric} on {self.log.date}"

    # Which column belongs to which metric type.
    FIELD_FOR_TYPE = {
        "number": "number_value",
        "scale": "scale_value",
        "boolean": "boolean_value",
        "text": "text_value",
    }

    def clean(self):
        super().clean()
        if self.log_id and self.metric_id and self.log.user_id != self.metric.user_id:
            raise ValidationError("A metric value must use a metric and a log from the same user.")
        if self.metric_id:
            own_field = self.FIELD_FOR_TYPE[self.metric.metric_type]
            for field in self.FIELD_FOR_TYPE.values():
                if field != own_field and getattr(self, field) not in (None, ""):
                    raise ValidationError(
                        f"A {self.metric.get_metric_type_display().lower()} parameter can't store {field}."
                    )

    def save(self, *args, **kwargs):
        # Ownership is enforced at the model level so no code path can mix users.
        self.clean()
        super().save(*args, **kwargs)

    @property
    def value(self):
        """The typed value, or None when nothing was recorded."""
        raw = getattr(self, self.FIELD_FOR_TYPE[self.metric.metric_type])
        return None if raw == "" else raw

    @property
    def display_value(self):
        value = self.value
        if value is None:
            return ""
        kind = self.metric.metric_type
        if kind == Metric.Type.NUMBER:
            text = format_decimal(value)
            return f"{text} {self.metric.unit}".strip()
        if kind == Metric.Type.SCALE:
            return f"{value} out of 10"
        if kind == Metric.Type.BOOLEAN:
            return "Yes" if value else "No"
        return value
