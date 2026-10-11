from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("healthz/", views.healthz, name="healthz"),
    # Accounts
    path("register/", views.register, name="register"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html", redirect_authenticated_user=True
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Journal
    path("journal/", views.journal, name="journal"),
    path("log/new/", views.log_new, name="log_new"),
    path("log/<int:pk>/", views.log_detail, name="log_detail"),
    path("log/<int:pk>/edit/", views.log_edit, name="log_edit"),
    path("review/", views.review, name="review"),
    # Settings
    path("settings/", views.settings_view, name="settings"),
    path("settings/start-date/", views.settings_start_date, name="settings_start_date"),
    path("settings/parameters/new/", views.metric_create, name="metric_create"),
    path("settings/parameters/<int:pk>/", views.metric_edit, name="metric_edit"),
    path("settings/parameters/<int:pk>/toggle/", views.metric_toggle, name="metric_toggle"),
    path("settings/parameters/<int:pk>/move/", views.metric_move, name="metric_move"),
    path("settings/parameters/<int:pk>/delete/", views.metric_delete, name="metric_delete"),
]
