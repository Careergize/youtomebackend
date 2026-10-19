from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from .models import Profile, Shortlist, Interest, Message

DEFAULTS = {'height': '', 'maritalStatus': 'Never Married', 'community': '', 'subCaste': '', 'motherTongue': 'English', 'state': '', 'country': 'India', 'diet': 'Vegetarian', 'smoke': 'Never', 'drink': 'Never', 'bio': '', 'hobbies': [], 'values': [], 'languagesSpoken': [], 'education': {'degree': '', 'college': '', 'field': ''}, 'occupation': {'title': '', 'companySector': 'Technology', 'employer': '', 'annualIncome': '', 'incomeBracket': '10-20L'}, 'family': {'type': 'Nuclear', 'fatherOccupation': '', 'motherOccupation': '', 'siblings': '', 'nativePlace': '', 'values': 'Progressive', 'affluenceLevel': 'Upper Middle Class'}, 'horoscope': {'nakshatra': '', 'rasi': '', 'manglik': "Doesn't Matter", 'birthTime': '', 'birthPlace': ''}, 'partnerPreferences': {'ageRange': [21,45], 'heightRange': [58,76], 'maritalStatus': [], 'religion': [], 'motherTongue': [], 'education': [], 'occupationSectors': [], 'preferredLocations': [], 'diet': [], 'manglikPreference': "Doesn't Matter"}, 'tags': [], 'photos': []}

DEFAULTS.update(weightKg='', bodyType='', profileCreatedBy='', gothram='', dateOfBirth='')
DEFAULTS['family'].update(sisters='', brothers='', ancestralOrigin='')
DEFAULTS['horoscope'].update(horoscopeUrl='')
DEFAULTS['occupation'].update(employmentType='')

class ProfileSerializer(serializers.ModelSerializer):
    age = serializers.IntegerField(min_value=18, max_value=100, allow_null=True)
    heightInches = serializers.IntegerField(min_value=36, max_value=96)
    class Meta:
        model = Profile
        fields = ['id', 'name', 'gender', 'age', 'heightInches', 'city', 'religion', 'details']
        read_only_fields = ['id']

    def to_internal_value(self, data):
        data = dict(data)
        details = {key: data[key] for key in DEFAULTS if key in data}
        if self.instance:
            for key, value in details.items():
                if isinstance(value, dict):
                    details[key] = {**self.instance.details.get(key, {}), **value}
            details = {**self.instance.details, **details}
        data['details'] = details
        return super().to_internal_value(data)

    def validate_details(self, details):
        for key, default in DEFAULTS.items():
            if key not in details: continue
            value = details[key]
            if not isinstance(value, type(default)):
                raise serializers.ValidationError(f'{key} has an invalid type.')
            if isinstance(default, dict):
                for nested, expected in default.items():
                    if nested in value and not isinstance(value[nested], type(expected)):
                        raise serializers.ValidationError(f'{key}.{nested} has an invalid type.')
            if isinstance(default, list) and not all(isinstance(item, str) for item in value):
                raise serializers.ValidationError(f'{key} must contain strings.')
        prefs = details.get('partnerPreferences', {})
        for key, choices in {'bodyType': ['Slim', 'Average', 'Athletic', 'Heavy'], 'profileCreatedBy': ['Self', 'Parents', 'Sibling', 'Relative', 'Friend']}.items():
            if details.get(key) and details[key] not in choices:
                raise serializers.ValidationError(f'{key} has an invalid choice.')
        if details.get('weightKg'):
            serializers.FloatField(min_value=20, max_value=300).run_validation(details['weightKg'])
        if details.get('dateOfBirth'):
            dob = serializers.DateField().run_validation(details['dateOfBirth'])
            today = timezone.localdate()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            if not 18 <= age <= 100:
                raise serializers.ValidationError('Date of birth must be for an adult aged 18–100.')
        for key, default in DEFAULTS['partnerPreferences'].items():
            if isinstance(default, list) and key not in ['ageRange', 'heightRange'] and key in prefs:
                if not all(isinstance(item, str) for item in prefs[key]):
                    raise serializers.ValidationError(f'{key} must contain strings.')
        for key in ['ageRange', 'heightRange']:
            if key in prefs and (len(prefs[key]) != 2 or not all(type(n) is int for n in prefs[key]) or prefs[key][0] > prefs[key][1]):
                raise serializers.ValidationError(f'{key} must be an ordered pair of integers.')
            if key in prefs:
                low, high = (18, 100) if key == 'ageRange' else (36, 96)
                if not low <= prefs[key][0] <= prefs[key][1] <= high:
                    raise serializers.ValidationError(f'{key} must be between {low} and {high}.')
        url = details.get('horoscope', {}).get('horoscopeUrl')
        if url:
            serializers.URLField().run_validation(url)
            if not url.startswith(('https://', 'http://')):
                raise serializers.ValidationError('Horoscope requires an HTTP or HTTPS URL.')
        for url in details.get('photos', []):
            serializers.URLField().run_validation(url)
            if not url.startswith(('https://', 'http://')): raise serializers.ValidationError('Photos require HTTP or HTTPS URLs.')
        return details

    def validate(self, attrs):
        dob = attrs.get('details', {}).get('dateOfBirth')
        if dob:
            dob = serializers.DateField().run_validation(dob)
            today = timezone.localdate()
            attrs['age'] = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        return attrs

    def to_representation(self, obj):
        result = {**DEFAULTS, **obj.details, **super().to_representation(obj)}
        result.pop('details')
        result['age'] = obj.age or 0
        if not result['height'] and obj.heightInches:
            result['height'] = f"{obj.heightInches // 12}' {obj.heightInches % 12}\""
        for key, default in DEFAULTS.items():
            if isinstance(default, dict): result[key] = {**default, **result[key]}
        result.update(verification={'isVerified': obj.is_verified, 'idVerified': obj.is_verified, 'mobileVerified': False, 'workVerified': False, 'badgeText': 'Verified' if obj.is_verified else 'Not verified'}, compatibilityScore=0, isOnline=False, lastActive=obj.updated_at.isoformat(), isShortlisted=False, interestStatus='none')
        result['isOnline'] = bool(obj.is_active and obj.last_seen_at and (timezone.now() - obj.last_seen_at).total_seconds() < 75)
        result['lastActive'] = obj.last_seen_at.isoformat() if obj.last_seen_at else None
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            result['isShortlisted'] = Shortlist.objects.filter(user=request.user, profile=obj).exists()
            own = getattr(request.user, 'profile', None)
            if own:
                interest = Interest.objects.filter(Q(sender=own, recipient=obj) | Q(sender=obj, recipient=own)).first()
                if interest: result['interestStatus'] = interest.status if interest.status != 'pending' else ('sent' if interest.sender_id == own.id else 'received')
                prefs = own.details.get('partnerPreferences', {})
                checks = []
                for pref, field in [('religion','religion'), ('motherTongue','motherTongue'), ('diet','diet'), ('preferredLocations','city'), ('maritalStatus','maritalStatus')]:
                    if prefs.get(pref): checks.append(result[field] in prefs[pref])
                if prefs.get('education'): checks.append(result['education']['degree'] in prefs['education'])
                if prefs.get('occupationSectors'): checks.append(result['occupation']['companySector'] in prefs['occupationSectors'])
                if prefs.get('manglikPreference') and prefs['manglikPreference'] != "Doesn't Matter":
                    checks.append(result['horoscope']['manglik'] == prefs['manglikPreference'])
                for pref, value in [('ageRange', obj.age), ('heightRange', obj.heightInches)]:
                    if prefs.get(pref) and value is not None: checks.append(prefs[pref][0] <= value <= prefs[pref][1])
                result['compatibilityScore'] = round(100 * sum(checks) / len(checks)) if checks else 0
            if obj.user_id == request.user.id:
                account = getattr(request.user, 'mobile_account', None)
                result['mobile'] = account.mobile if account else ''
                result['verification']['mobileVerified'] = account is not None
        return result

class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=150)
    password = serializers.CharField(write_only=True, max_length=128)
    firstName = serializers.CharField(max_length=60)
    lastName = serializers.CharField(max_length=60)
    gender = serializers.ChoiceField(choices=['Bride', 'Groom'])
    age = serializers.IntegerField(min_value=18, max_value=100)
    city = serializers.CharField(max_length=100)
    religion = serializers.CharField(max_length=50, default='Hindu')
    def validate(self, data):
        data['email'] = data['email'].lower()
        if User.objects.filter(username=data['email']).exists(): raise serializers.ValidationError({'email': 'An account with this email already exists.'})
        user = User(username=data['email'], email=data['email'], first_name=data['firstName'], last_name=data['lastName'])
        try: validate_password(data['password'], user)
        except ValidationError as exc: raise serializers.ValidationError({'password': exc.messages})
        return data

class MessageSerializer(serializers.ModelSerializer):
    sender = serializers.SerializerMethodField()
    time = serializers.DateTimeField(source='created_at', read_only=True)
    class Meta:
        model = Message
        fields = ['id', 'sender', 'text', 'time']
    def get_sender(self, obj):
        return 'me' if obj.sender.user_id == self.context['request'].user.id else 'them'
