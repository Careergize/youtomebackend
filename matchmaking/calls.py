import base64
import hashlib
import hmac
import time
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from .models import Call, Interest, Profile


class CallThrottle(UserRateThrottle):
    # Signaling polling has a separate budget from chat and profile actions.
    rate = '6000/hour'
    scope = 'calls'


def expire_calls():
    now = timezone.now()
    Call.objects.filter(status='ringing', created_at__lt=now-timedelta(seconds=60)).update(status='missed')
    cutoff = now-timedelta(seconds=90)
    Call.objects.filter(Q(caller_seen_at__lt=cutoff) | Q(recipient_seen_at__lt=cutoff), status='active').update(status='ended')


def payload(call, user):
    outgoing = call.caller.user_id == user.id
    other = call.recipient if outgoing else call.caller
    return {'id': str(call.pk), 'kind': call.kind, 'status': call.status,
            'outgoing': outgoing, 'peer': {'id': str(other.pk), 'name': other.name},
            'offer': call.offer, 'answer': call.answer,
            'candidates': call.recipient_candidates if outgoing else call.caller_candidates}


def description(data, expected):
    if not isinstance(data, dict) or data.get('type') != expected:
        raise serializers.ValidationError('Invalid call description.')
    # SDP's final CRLF is significant; normal CharField trimming breaks WebRTC.
    sdp = serializers.CharField(max_length=100000, trim_whitespace=False).run_validation(data.get('sdp'))
    return {'type': expected, 'sdp': sdp}


@api_view(['GET', 'POST'])
@throttle_classes([CallThrottle])
def calls(request):
    expire_calls()
    own = get_object_or_404(Profile, user=request.user, is_active=True)
    if request.method == 'GET':
        qs = Call.objects.filter(Q(caller=own) | Q(recipient=own), status__in=['ringing', 'active']).select_related('caller__user', 'recipient__user')
        return Response([payload(call, request.user) for call in qs.order_by('-created_at')])
    kind = serializers.ChoiceField(choices=['voice', 'video']).run_validation(request.data.get('kind'))
    offer = description(request.data.get('offer'), 'offer')
    interest_id = serializers.IntegerField().run_validation(request.data.get('interestId'))
    interest = get_object_or_404(Interest.objects.filter(Q(sender=own) | Q(recipient=own)), pk=interest_id, status__in=['pending', 'accepted'])
    other = interest.recipient if interest.sender_id == own.pk else interest.sender
    with transaction.atomic():
        # Serialize calls sharing either member, including simultaneous dial attempts.
        members = list(Profile.objects.select_for_update().filter(pk__in=[own.pk, other.pk]).order_by('pk'))
        if not all(member.is_active for member in members):
            raise serializers.ValidationError('This connection is unavailable.')
        if Call.objects.filter(Q(caller__in=members) | Q(recipient__in=members), status__in=['ringing', 'active']).exists():
            return Response({'detail': 'One of you is already in a call.'}, status=409)
        call = Call.objects.create(interest=interest, caller=own, recipient=other, kind=kind, offer=offer)
    return Response(payload(call, request.user), status=201)


@api_view(['GET', 'PATCH'])
@throttle_classes([CallThrottle])
def call_detail(request, pk):
    expire_calls()
    with transaction.atomic():
        call = get_object_or_404(Call.objects.select_for_update().select_related('caller__user', 'recipient__user'),
                                 Q(caller__user=request.user) | Q(recipient__user=request.user), pk=pk)
        if call.interest.status not in ['pending', 'accepted'] or not call.caller.is_active or not call.recipient.is_active:
            call.status = 'ended'
            call.save(update_fields=['status', 'updated_at'])
        if request.method == 'GET':
            return Response(payload(call, request.user))
        action = serializers.ChoiceField(choices=['answer', 'candidate', 'decline', 'end', 'heartbeat']).run_validation(request.data.get('action'))
        if call.status not in ['ringing', 'active']:
            return Response({'detail': 'This call has ended.'}, status=409)
        outgoing = call.caller.user_id == request.user.id
        fields = ['updated_at']
        if action in ['answer', 'decline']:
            if outgoing or call.status != 'ringing':
                return Response({'detail': 'Only the recipient can answer a ringing call.'}, status=403)
            if action == 'answer':
                call.answer = description(request.data.get('answer'), 'answer')
                call.status = 'active'
                call.caller_seen_at = call.recipient_seen_at = timezone.now()
                fields += ['answer', 'status', 'caller_seen_at', 'recipient_seen_at']
            else:
                call.status = 'declined'
                fields += ['status']
        elif action == 'end':
            call.status = 'ended'
            fields += ['status']
        elif action == 'heartbeat':
            field = 'caller_seen_at' if outgoing else 'recipient_seen_at'
            setattr(call, field, timezone.now())
            fields += [field]
        elif action == 'candidate':
            candidate = request.data.get('candidate')
            if not isinstance(candidate, dict):
                raise serializers.ValidationError('Invalid ICE candidate.')
            cleaned = {'candidate': serializers.CharField(max_length=4096, allow_blank=True, trim_whitespace=False).run_validation(candidate.get('candidate')),
                       'sdpMid': serializers.CharField(max_length=100, allow_null=True).run_validation(candidate.get('sdpMid')),
                       'sdpMLineIndex': serializers.IntegerField(min_value=0, max_value=100, allow_null=True).run_validation(candidate.get('sdpMLineIndex'))}
            field = 'caller_candidates' if outgoing else 'recipient_candidates'
            candidates = getattr(call, field)
            if len(candidates) >= 100:
                raise serializers.ValidationError('Too many ICE candidates.')
            setattr(call, field, [*candidates, cleaned])
            fields += [field]
        call.save(update_fields=fields)
        return Response(payload(call, request.user))


@api_view(['GET'])
@throttle_classes([CallThrottle])
def call_config(request):
    servers = list(settings.WEBRTC_ICE_SERVERS)
    if settings.WEBRTC_TURN_URLS and settings.WEBRTC_TURN_SECRET:
        username = f'{int(time.time()) + settings.WEBRTC_TURN_TTL}:{request.user.pk}'
        credential = base64.b64encode(hmac.new(
            settings.WEBRTC_TURN_SECRET.encode(), username.encode(), hashlib.sha1,
        ).digest()).decode()
        servers.append({'urls': settings.WEBRTC_TURN_URLS, 'username': username, 'credential': credential})
    response = Response({'iceServers': servers})
    response['Cache-Control'] = 'no-store, private'
    return response
