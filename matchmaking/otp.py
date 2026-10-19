"""Mobile authentication. Local test delivery is unavailable in production."""
import re
import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import OtpChallenge, MobileAccount, Profile
from .views import AuthThrottle
from rest_framework.authtoken.models import Token
from .sms import send_msg91_otp, SmsDeliveryError

def delivery_available():
    return settings.OTP_DELIVERY_MODE == 'msg91' or (settings.DEBUG and settings.OTP_DELIVERY_MODE == 'local')

def normalize_mobile(value):
    value = serializers.CharField(max_length=30).run_validation(value)
    value = re.sub(r'[\s()\-]', '', value)
    if re.fullmatch(r'[6-9]\d{9}', value): value = '+91' + value
    if not re.fullmatch(r'\+[1-9]\d{7,14}', value):
        raise serializers.ValidationError({'mobile': 'Enter a valid mobile number with country code (e.g. +91). Indian numbers can use 10 digits.'})
    return value

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def request_otp(request):
    mobile = normalize_mobile(request.data.get('mobile'))
    name = serializers.CharField(max_length=120, allow_blank=True).run_validation(request.data.get('name', ''))
    existing = MobileAccount.objects.filter(mobile=mobile).exists()
    if not existing and not name:
        return Response({'nameRequired': True, 'detail': 'Enter your name to create your account.'}, status=200)
    if not delivery_available():
        return Response({'detail': 'SMS login is not configured yet. Please try again once SMS delivery is enabled.'}, status=503)
    now = timezone.now()
    with transaction.atomic():
        challenge, _ = OtpChallenge.objects.get_or_create(mobile=mobile)
        challenge = OtpChallenge.objects.select_for_update().get(pk=challenge.pk)
        if challenge.last_sent_at and now - challenge.last_sent_at < timedelta(seconds=60):
            return Response({'detail': 'Wait 60 seconds before requesting another code.'}, status=429)
        if not challenge.window_started_at or now - challenge.window_started_at >= timedelta(hours=1):
            challenge.window_started_at = now
            challenge.sends = 0
        if challenge.sends >= 5:
            return Response({'detail': 'Too many codes requested. Try again in an hour.'}, status=429)
        local = settings.OTP_DELIVERY_MODE == 'local'
        code = '1234' if local else f'{secrets.randbelow(1000000):06d}'
        if not local:
            try:
                send_msg91_otp(mobile, code)
            except SmsDeliveryError as exc:
                return Response({'detail': str(exc)}, status=503)
        challenge.delivery = settings.OTP_DELIVERY_MODE
        challenge.code_hash = make_password(code)
        challenge.name = name
        challenge.last_sent_at = now
        challenge.expires_at = now + timedelta(minutes=5)
        challenge.sends += 1
        challenge.attempts = 0
        challenge.consumed = False
        challenge.save()
    result = {'challengeId': str(challenge.pk), 'mobile': mobile, 'expiresIn': 300, 'resendAfter': 60, 'delivery': challenge.delivery, 'otpLength': len(code), 'detail': 'Local test code only. No SMS was sent.' if local else 'Verification code sent to your mobile.'}
    if local: result['devOtp'] = code
    return Response(result)

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def verify_otp(request):
    if not delivery_available():
        return Response({'detail': 'SMS login is not configured yet.'}, status=503)
    pk = serializers.UUIDField().run_validation(request.data.get('challengeId'))
    mobile = normalize_mobile(request.data.get('mobile'))
    length = 4 if settings.OTP_DELIVERY_MODE == 'local' else 6
    code = serializers.RegexField(r'^\d{' + str(length) + r'}$').run_validation(request.data.get('code'))
    with transaction.atomic():
        challenge = OtpChallenge.objects.select_for_update().filter(pk=pk, mobile=mobile).first()
        if not challenge or challenge.delivery != settings.OTP_DELIVERY_MODE or challenge.consumed or not challenge.expires_at or timezone.now() >= challenge.expires_at or challenge.attempts >= 5:
            return Response({'detail': 'Code expired or unavailable. Request a new code.'}, status=400)
        challenge.attempts += 1
        challenge.save(update_fields=['attempts'])
        if not check_password(code, challenge.code_hash):
            return Response({'detail': 'Incorrect code. Please try again.'}, status=400)
        account = MobileAccount.objects.select_related('user').filter(mobile=mobile).first()
        created = account is None
        if created:
            user = User.objects.create_user(username=f'mobile:{mobile}', password=None, first_name=challenge.name[:150])
            account = MobileAccount.objects.create(user=user, mobile=mobile, verified_at=timezone.now())
            Profile.objects.create(user=user, name=challenge.name, gender='', age=None, heightInches=0, religion='')
        if not account.user.is_active:
            return Response({'detail': 'This account is inactive.'}, status=403)
        challenge.consumed = True
        challenge.code_hash = ''
        challenge.save(update_fields=['consumed', 'code_hash'])
        token, _ = Token.objects.get_or_create(user=account.user)
    return Response({'token': token.key, 'isNewUser': created})
