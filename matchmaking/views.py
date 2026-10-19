from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, serializers
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework.throttling import AnonRateThrottle
from .models import Profile, Shortlist, Interest
from .serializers import ProfileSerializer, RegisterSerializer, MessageSerializer

class AuthThrottle(AnonRateThrottle):
    scope = 'auth'

@api_view(['GET'])
@permission_classes([AllowAny])
def health(request):
    return Response({'status': 'ok', 'service': 'you2me'})

@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
        with transaction.atomic():
            user = User.objects.create_user(username=data['email'], email=data['email'], password=data['password'], first_name=data['firstName'], last_name=data['lastName'])
            profile = Profile.objects.create(user=user, name=f"{data['firstName']} {data['lastName']}", **{key: data[key] for key in ['gender', 'age', 'city', 'religion']})
            token = Token.objects.create(user=user)
    except IntegrityError: raise serializers.ValidationError({'email': 'An account with this email already exists.'})
    return Response({'token': token.key, 'profile': ProfileSerializer(profile).data}, status=201)

@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def login(request):
    email = serializers.EmailField().run_validation(request.data.get('email'))
    password = serializers.CharField(max_length=128).run_validation(request.data.get('password'))
    user = authenticate(username=email.lower(), password=password)
    if user is None: return Response({'detail': 'Invalid email or password.'}, status=400)
    token, _ = Token.objects.get_or_create(user=user)
    return Response({'token': token.key})

@api_view(['POST'])
def logout(request):
    Profile.objects.filter(user=request.user).update(last_seen_at=None)
    Token.objects.filter(user=request.user).delete()
    return Response(status=204)

@api_view(['POST'])
def presence(request):
    get_object_or_404(Profile, user=request.user, is_active=True)
    Profile.objects.filter(user=request.user).update(last_seen_at=timezone.now())
    return Response(status=204)

class Me(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    def get_object(self): return get_object_or_404(Profile, user=self.request.user)

class Profiles(generics.ListAPIView):
    serializer_class = ProfileSerializer
    def get_queryset(self):
        qs = Profile.objects.filter(is_active=True).exclude(user=self.request.user)
        if self.request.query_params.get('connections') == 'true':
            qs = qs.filter(Q(sent_interests__recipient__user=self.request.user) | Q(received_interests__sender__user=self.request.user)).distinct()
        else:
            qs = qs.filter(age__gte=18, gender__in=['Bride', 'Groom'])
        p = self.request.query_params
        for key in ['gender','religion','city']:
            if p.get(key) and p[key] != 'All': qs = qs.filter(**{key: p[key]})
        for key, lookup in [('minAge','age__gte'),('maxAge','age__lte'),('minHeightInches','heightInches__gte'),('maxHeightInches','heightInches__lte')]:
            if p.get(key): qs = qs.filter(**{lookup: serializers.IntegerField(min_value=0, max_value=150).run_validation(p[key])})
        if p.get('verifiedOnly') == 'true': qs = qs.filter(is_verified=True)
        if p.get('shortlisted') == 'true': qs = qs.filter(shortlist__user=self.request.user)
        if p.get('searchQuery'): qs = qs.filter(Q(name__icontains=p['searchQuery']) | Q(city__icontains=p['searchQuery']) | Q(details__bio__icontains=p['searchQuery']) | Q(details__community__icontains=p['searchQuery']) | Q(details__occupation__title__icontains=p['searchQuery']) | Q(details__education__degree__icontains=p['searchQuery']))
        for key, lookup in [('maritalStatuses','maritalStatus'),('occupationSectors','occupation__companySector'),('incomeBrackets','occupation__incomeBracket'),('dietList','diet')]:
            if p.getlist(key): qs = qs.filter(**{f'details__{lookup}__in': p.getlist(key)})
        if p.getlist('educationList'):
            query = Q()
            for degree in p.getlist('educationList'): query |= Q(details__education__degree__icontains=degree)
            qs = qs.filter(query)
        if p.get('manglikOnly') == 'true': qs = qs.exclude(details__horoscope__manglik='Manglik')
        return qs.order_by('-age' if p.get('sortBy') == 'ageDesc' else 'age', 'id')

class ProfileDetail(generics.RetrieveAPIView):
    serializer_class = ProfileSerializer
    queryset = Profile.objects.filter(is_active=True)

@api_view(['POST','DELETE'])
def shortlist(request, pk):
    profile = get_object_or_404(Profile, pk=pk, is_active=True)
    if profile.user_id == request.user.id: raise serializers.ValidationError('Cannot shortlist yourself.')
    if request.method == 'POST': Shortlist.objects.get_or_create(user=request.user, profile=profile)
    else: Shortlist.objects.filter(user=request.user, profile=profile).delete()
    return Response({'isShortlisted': request.method == 'POST'})

@api_view(['POST'])
def send_interest(request, pk):
    own = get_object_or_404(Profile, user=request.user)
    other = get_object_or_404(Profile, pk=pk, is_active=True)
    if own == other: raise serializers.ValidationError('Cannot send interest to yourself.')
    with transaction.atomic():
        list(Profile.objects.select_for_update().filter(pk__in=[own.pk,other.pk]).order_by('pk'))
        obj = Interest.objects.filter(Q(sender=own,recipient=other) | Q(sender=other,recipient=own)).first()
        if obj is None: obj = Interest.objects.create(sender=own,recipient=other)
    return Response({'id': obj.id, 'status': obj.status})

@api_view(['GET'])
def interests(request):
    qs = Interest.objects.filter(Q(sender__user=request.user) | Q(recipient__user=request.user)).order_by('-created_at')
    return Response([{'id': obj.id, 'sender': str(obj.sender_id), 'recipient': str(obj.recipient_id), 'status': obj.status} for obj in qs])

@api_view(['PATCH'])
def respond_interest(request, pk):
    obj = get_object_or_404(Interest, pk=pk, recipient__user=request.user)
    value = serializers.ChoiceField(choices=['accepted','declined']).run_validation(request.data.get('status'))
    with transaction.atomic():
        obj = Interest.objects.select_for_update().get(pk=obj.pk)
        if obj.status != 'pending': raise serializers.ValidationError('This interest has already been answered.')
        obj.status = value
        obj.save(update_fields=['status'])
    return Response({'id': obj.id, 'status': obj.status})

class Messages(generics.ListCreateAPIView):
    serializer_class = MessageSerializer
    def connection(self):
        return get_object_or_404(Interest.objects.filter(Q(sender__user=self.request.user) | Q(recipient__user=self.request.user)), pk=self.kwargs['pk'], status='accepted')
    def get_queryset(self): return self.connection().messages.select_related('sender')
    def perform_create(self, serializer):
        serializer.save(interest=self.connection(), sender=get_object_or_404(Profile,user=self.request.user))

@api_view(['GET'])
@permission_classes([AllowAny])
def plans(request):
    return Response([
        {'id': 'gold', 'name': 'YOU2ME Gold', 'currency': 'INR', 'price': 500, 'originalPrice': 4999, 'durationMonths': 3, 'freeTrialMonths': 2},
        {'id': 'elite', 'name': 'YOU2ME Royale VIP', 'currency': 'INR', 'price': 2000, 'originalPrice': 4999, 'durationMonths': 6, 'freeTrialMonths': 2},
    ])
