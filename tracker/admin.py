from django.contrib import admin

from .models import DailyLog, Metric, MetricValue, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "start_date")


@admin.register(Metric)
class MetricAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "metric_type", "unit", "is_active", "order")
    list_filter = ("metric_type", "is_active")


class MetricValueInline(admin.TabularInline):
    model = MetricValue
    extra = 0


@admin.register(DailyLog)
class DailyLogAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "updated_at")
    inlines = [MetricValueInline]
