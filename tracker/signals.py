from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    """Every new user gets a Profile whose start date is the day they joined."""
    if created:
        Profile.objects.get_or_create(user=instance)
