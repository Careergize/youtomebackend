import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone

class Profile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    name = models.CharField(max_length=120)
    gender = models.CharField(max_length=5, choices=[('Bride', 'Bride'), ('Groom', 'Groom')])
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    heightInches = models.PositiveSmallIntegerField(default=65)
    city = models.CharField(max_length=100, blank=True)
    religion = models.CharField(max_length=50, default='Hindu')
    details = models.JSONField(default=dict, blank=True)
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

class Shortlist(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'profile'], name='unique_shortlist')]

class Interest(models.Model):
    sender = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='sent_interests')
    recipient = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='received_interests')
    status = models.CharField(max_length=10, choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('declined', 'Declined')], default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['sender', 'recipient'], name='unique_interest'), models.CheckConstraint(condition=~models.Q(sender=models.F('recipient')), name='no_self_interest')]

class Message(models.Model):
    interest = models.ForeignKey(Interest, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(Profile, on_delete=models.CASCADE)
    text = models.CharField(max_length=4000)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['created_at', 'id']

class Call(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    interest = models.ForeignKey(Interest, on_delete=models.CASCADE, related_name='calls')
    caller = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='outgoing_calls')
    recipient = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='incoming_calls')
    kind = models.CharField(max_length=5, choices=[('voice', 'Voice'), ('video', 'Video')])
    status = models.CharField(max_length=10, default='ringing')
    offer = models.JSONField(default=dict)
    answer = models.JSONField(default=dict)
    caller_candidates = models.JSONField(default=list)
    recipient_candidates = models.JSONField(default=list)
    caller_seen_at = models.DateTimeField(default=timezone.now)
    recipient_seen_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class MobileAccount(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mobile_account')
    mobile = models.CharField(max_length=16, unique=True)
    verified_at = models.DateTimeField()

class OtpChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mobile = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=120, blank=True)
    code_hash = models.CharField(max_length=256, blank=True)
    expires_at = models.DateTimeField(null=True)
    last_sent_at = models.DateTimeField(null=True)
    window_started_at = models.DateTimeField(null=True)
    sends = models.PositiveSmallIntegerField(default=0)
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed = models.BooleanField(default=False)
    delivery = models.CharField(max_length=10, default='local')
