import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Profile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("start_date", models.DateField(default=django.utils.timezone.localdate)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="Metric",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=60)),
                ("metric_type", models.CharField(choices=[("number", "Number"), ("scale", "Scale from 1 to 10"), ("boolean", "Yes or no"), ("text", "Short text")], max_length=10)),
                ("unit", models.CharField(blank=True, max_length=20)),
                ("is_active", models.BooleanField(default=True)),
                ("order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="metrics", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["order", "name"],
            },
        ),
        migrations.CreateModel(
            name="DailyLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("notes", models.TextField(blank=True)),
                ("wins", models.TextField(blank=True)),
                ("challenges", models.TextField(blank=True)),
                ("tomorrow_priority", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-date"],
            },
        ),
        migrations.CreateModel(
            name="MetricValue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("number_value", models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True)),
                ("scale_value", models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(10)])),
                ("boolean_value", models.BooleanField(blank=True, null=True)),
                ("text_value", models.CharField(blank=True, default="", max_length=255)),
                ("log", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="values", to="tracker.dailylog")),
                ("metric", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="values", to="tracker.metric")),
            ],
        ),
        migrations.AddConstraint(
            model_name="metric",
            constraint=models.UniqueConstraint(fields=("user", "name"), name="unique_metric_name_per_user"),
        ),
        migrations.AddConstraint(
            model_name="dailylog",
            constraint=models.UniqueConstraint(fields=("user", "date"), name="unique_log_per_user_per_date"),
        ),
        migrations.AddConstraint(
            model_name="metricvalue",
            constraint=models.UniqueConstraint(fields=("log", "metric"), name="unique_value_per_metric_per_log"),
        ),
    ]
