from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase, APIClient
from .models import Profile, Interest, Shortlist, Message, MobileAccount, OtpChallenge, Call
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock
import io
from urllib.error import URLError
from .sms import send_msg91_otp, SmsDeliveryError

@override_settings(REST_FRAMEWORK={'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.TokenAuthentication'], 'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'], 'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination', 'PAGE_SIZE': 50})
class ApiTests(APITestCase):
    def setUp(self):
        self.a = User.objects.create_user('a@example.com', password='Strong-example-37')
        self.b = User.objects.create_user('b@example.com', password='Strong-example-38')
        self.c = User.objects.create_user('c@example.com', password='Strong-example-39')
        self.pa = Profile.objects.create(user=self.a,name='Alice',gender='Bride',age=25,city='Kochi')
        self.pb = Profile.objects.create(user=self.b,name='Bob',gender='Groom',age=28,city='Kochi')
        self.pc = Profile.objects.create(user=self.c,name='Chris',gender='Groom',age=35,city='Delhi')
        self.client.force_authenticate(self.a)

    def test_incomplete_sender_interest_reaches_recipient(self):
        self.pa.age = None
        self.pa.gender = ''
        self.pa.save()
        sent = self.client.post(f'/api/profiles/{self.pb.pk}/interest/')
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(Interest.objects.count(), 1)
        self.client.force_authenticate(self.b)
        discovery = self.client.get('/api/profiles/').data['results']
        self.assertNotIn(str(self.pa.pk), [p['id'] for p in discovery])
        inbox = self.client.get('/api/profiles/?connections=true').data['results']
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]['id'], str(self.pa.pk))
        self.assertEqual(inbox[0]['interestStatus'], 'received')
        self.assertNotIn('mobile', inbox[0])
        response = self.client.patch(f"/api/interests/{sent.data['id']}/", {'status': 'accepted'})
        self.assertEqual(response.status_code, 200)
        self.client.force_authenticate(self.a)
        connections = self.client.get('/api/profiles/?connections=true').data['results']
        self.assertEqual(connections[0]['interestStatus'], 'accepted')
        self.client.force_authenticate(self.c)
        self.assertEqual(self.client.get('/api/profiles/?connections=true').data['results'], [])
        self.assertEqual(self.client.get('/api/interests/').data, [])

    def test_call_permissions_signaling_and_lifecycle(self):
        connection = Interest.objects.create(sender=self.pa, recipient=self.pb)
        offer = {'type': 'offer', 'sdp': 'v=0\r\na=test offer\r\n'}
        data = {'interestId': connection.pk, 'kind': 'video', 'offer': offer}
        self.assertEqual(self.client.post('/api/calls/', data, format='json').status_code, 404)
        connection.status = 'accepted'
        connection.save()
        self.assertEqual(self.client.post('/api/calls/', {**data, 'offer': {}}, format='json').status_code, 400)
        result = self.client.post('/api/calls/', data, format='json')
        self.assertEqual(result.status_code, 201, result.data)
        url = f"/api/calls/{result.data['id']}/"
        self.assertEqual(self.client.post('/api/calls/', data, format='json').status_code, 409)
        self.assertEqual(self.client.patch(url, {'action': 'answer', 'answer': {'type': 'answer', 'sdp': 'answer'}}, format='json').status_code, 403)
        candidate = {'candidate': 'candidate:1 1 udp 1 127.0.0.1 12345 typ host', 'sdpMid': '0', 'sdpMLineIndex': 0}
        self.assertEqual(self.client.patch(url, {'action': 'candidate', 'candidate': candidate}, format='json').status_code, 200)
        self.client.force_authenticate(self.c)
        self.assertEqual(self.client.get('/api/calls/').data, [])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.patch(url, {'action': 'end'}).status_code, 404)
        self.client.force_authenticate(self.b)
        incoming = self.client.get('/api/calls/').data[0]
        self.assertFalse(incoming['outgoing'])
        self.assertEqual(incoming['offer'], offer)
        self.assertEqual(incoming['candidates'], [candidate])
        answer = self.client.patch(url, {'action': 'answer', 'answer': {'type': 'answer', 'sdp': 'answer'}}, format='json')
        self.assertEqual(answer.data['status'], 'active')
        self.assertEqual(self.client.patch(url, {'action': 'heartbeat'}).status_code, 200)
        self.client.force_authenticate(self.a)
        self.assertEqual(self.client.get(url).data['answer']['sdp'], 'answer')
        self.assertEqual(self.client.patch(url, {'action': 'end'}).data['status'], 'ended')
        self.assertEqual(self.client.patch(url, {'action': 'candidate', 'candidate': candidate}, format='json').status_code, 409)
        self.assertEqual(self.client.get('/api/calls/').data, [])

    def test_call_timeout_decline_and_voice(self):
        connection = Interest.objects.create(sender=self.pa, recipient=self.pb, status='accepted')
        data = {'interestId': connection.pk, 'kind': 'voice', 'offer': {'type': 'offer', 'sdp': 'offer'}}
        result = self.client.post('/api/calls/', data, format='json')
        self.assertEqual(result.status_code, 201)
        call = Call.objects.get(pk=result.data['id'])
        Call.objects.filter(pk=call.pk).update(created_at=timezone.now()-timedelta(seconds=61))
        self.assertEqual(self.client.get(f'/api/calls/{call.pk}/').data['status'], 'missed')
        result = self.client.post('/api/calls/', data, format='json')
        self.client.force_authenticate(self.b)
        self.assertEqual(self.client.patch(f"/api/calls/{result.data['id']}/", {'action': 'decline'}).data['status'], 'declined')
        Call.objects.filter(pk=result.data['id']).update(status='active', caller_seen_at=timezone.now()-timedelta(seconds=91))
        self.assertEqual(self.client.get(f"/api/calls/{result.data['id']}/").data['status'], 'ended')
        self.assertEqual(APIClient().get('/api/calls/').status_code, 401)

    def test_registration_login_logout(self):
        client = APIClient()
        data = {'email':'NEW@example.com','password':'A-long-secret-591!','firstName':'New','lastName':'Member','gender':'Bride','age':24,'city':'Kochi'}
        response = client.post('/api/auth/register/',data)
        self.assertEqual(response.status_code,201,response.data)
        user = User.objects.get(username='new@example.com')
        self.assertTrue(user.check_password(data['password']))
        self.assertEqual(client.post('/api/auth/register/',data).status_code,400)
        self.assertEqual(client.post('/api/auth/login/',{'email':data['email'],'password':'bad'}).status_code,400)
        result = client.post('/api/auth/login/',{'email':data['email'],'password':data['password']})
        client.credentials(HTTP_AUTHORIZATION='Token '+result.data['token'])
        self.assertEqual(client.get('/api/me/').status_code,200)
        self.assertEqual(client.post('/api/auth/logout/').status_code,204)
        self.assertEqual(client.get('/api/me/').status_code,401)

    def test_invalid_signup_and_anonymous_access(self):
        client = APIClient()
        self.assertEqual(client.get('/api/profiles/').status_code,401)
        response = client.post('/api/auth/register/',{'email':'x@example.com','password':'12345678','firstName':'X','lastName':'Y','gender':'Bride','age':17,'city':'Kochi'})
        self.assertEqual(response.status_code,400)
        self.assertFalse(User.objects.filter(username='x@example.com').exists())

    def test_profile_validation_and_ownership(self):
        response = self.client.patch('/api/me/',{'name':'Changed','verification':{'isVerified':True},'is_verified':True,'bio':'Hello'},format='json')
        self.assertEqual(response.status_code,200,response.data)
        self.pa.refresh_from_db()
        self.assertFalse(self.pa.is_verified)
        self.assertEqual(self.pa.details['bio'],'Hello')
        self.assertEqual(self.client.patch(f'/api/profiles/{self.pb.pk}/',{'name':'Stolen'}).status_code,405)
        for data in [{'age':17}, {'photos':['javascript:alert(1)']}, {'partnerPreferences':{'ageRange':[45,21]}}, {'education':'invalid'}]:
            self.assertEqual(self.client.patch('/api/me/',data,format='json').status_code,400)

    def test_search_and_shortlist(self):
        result = self.client.get('/api/profiles/?city=Kochi&minAge=26')
        self.assertEqual(len(result.data['results']),1)
        self.assertEqual(result.data['results'][0]['name'],'Bob')
        self.assertEqual(self.client.get('/api/profiles/?minAge=bad').status_code,400)
        for _ in range(2): self.assertEqual(self.client.post(f'/api/profiles/{self.pb.pk}/shortlist/').status_code,200)
        self.assertEqual(Shortlist.objects.count(),1)
        self.assertEqual(self.client.get('/api/profiles/?shortlisted=true').data['count'],1)
        self.client.delete(f'/api/profiles/{self.pb.pk}/shortlist/')
        self.assertEqual(Shortlist.objects.count(),0)

    def test_extended_profile_fields_and_nested_patch(self):
        payload = {'weightKg': '45', 'bodyType': 'Slim', 'profileCreatedBy': 'Parents',
                   'gothram': 'Example', 'dateOfBirth': '1999-01-01', 'subCaste': 'Example',
                   'family': {'affluenceLevel': 'Middle Class', 'sisters': '1 sister', 'ancestralOrigin': 'Kerala'},
                   'occupation': {'companySector': 'Teaching / Academia', 'employmentType': 'Private Sector', 'incomeBracket': '0-2L'},
                   'horoscope': {'horoscopeUrl': 'https://example.com/chart.pdf', 'nakshatra': 'Rohini'},
                   'partnerPreferences': {'ageRange': [27, 32], 'heightRange': [60, 75], 'religion': ['Hindu']}}
        response = self.client.patch('/api/me/', payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        for key, value in payload.items():
            if isinstance(value, dict):
                for nested, expected in value.items(): self.assertEqual(response.data[key][nested], expected)
            else: self.assertEqual(response.data[key], value)
        response = self.client.patch('/api/me/', {'family': {'brothers': '2 brothers'}, 'horoscope': {'rasi': 'Taurus'}}, format='json')
        self.assertEqual(response.data['family']['sisters'], '1 sister')
        self.assertEqual(response.data['horoscope']['nakshatra'], 'Rohini')
        self.client.force_authenticate(self.b)
        public = self.client.get(f'/api/profiles/{self.pa.pk}/').data
        self.assertEqual(public['bodyType'], 'Slim')
        self.assertNotIn('mobile', public)

    def test_extended_profile_validation(self):
        for payload in [{'weightKg': '-1'}, {'bodyType': 'Invalid'}, {'profileCreatedBy': 'Invalid'},
                        {'dateOfBirth': '2099-01-01'}, {'dateOfBirth': 'bad'},
                        {'horoscope': {'horoscopeUrl': 'javascript:alert(1)'}},
                        {'partnerPreferences': {'religion': [12]}}, {'partnerPreferences': {'ageRange': [17, 32]}}]:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.patch('/api/me/', payload, format='json').status_code, 400)

    def test_profile_page_details_persist(self):
        payload = {
            'name': 'Alice Updated', 'age': 26, 'height': '165 cm', 'heightInches': 65,
            'state': 'Kerala', 'country': 'India', 'community': 'Community', 'diet': 'Vegan',
            'education': {'degree': 'Masters', 'college': 'College', 'field': 'Design'},
            'occupation': {'title': 'Designer', 'companySector': 'Creative & Design', 'employer': 'Studio', 'annualIncome': '20 Lakhs', 'incomeBracket': '10-20L'},
            'family': {'type': 'Joint', 'values': 'Progressive', 'fatherOccupation': 'Teacher', 'motherOccupation': 'Doctor', 'siblings': 'One brother', 'nativePlace': 'Kochi'},
            'horoscope': {'nakshatra': 'Rohini', 'rasi': 'Taurus'},
            'bio': 'My updated biography', 'photos': ['https://example.com/photo.jpg'],
        }
        self.assertEqual(self.client.patch('/api/me/', payload, format='json').status_code, 200)
        saved = self.client.get('/api/me/').data
        for key, value in payload.items():
            if isinstance(value, dict):
                for nested, expected in value.items(): self.assertEqual(saved[key][nested], expected)
            else: self.assertEqual(saved[key], value)
        self.assertEqual(self.client.patch('/api/me/', {'bio': 'Only bio changed'}, format='json').status_code, 200)
        self.assertEqual(self.client.get('/api/me/').data['education']['degree'], 'Masters')

    def test_interests_and_message_privacy(self):
        self.assertEqual(self.client.post(f'/api/profiles/{self.pa.pk}/interest/').status_code,400)
        result = self.client.post(f'/api/profiles/{self.pb.pk}/interest/')
        pk = result.data['id']
        self.client.post(f'/api/profiles/{self.pb.pk}/interest/')
        self.assertEqual(Interest.objects.count(),1)
        self.assertEqual(self.client.patch(f'/api/interests/{pk}/',{'status':'accepted'}).status_code,404)
        self.assertEqual(self.client.post(f'/api/interests/{pk}/messages/',{'text':'Hello'}).status_code,404)
        self.client.force_authenticate(self.b)
        self.assertEqual(self.client.patch(f'/api/interests/{pk}/',{'status':'accepted'}).status_code,200)
        self.assertEqual(self.client.post(f'/api/interests/{pk}/messages/',{'text':'Hello'}).status_code,201)
        self.assertEqual(self.client.post(f'/api/interests/{pk}/messages/',{'text':' '}).status_code,400)
        self.client.force_authenticate(self.c)
        self.assertEqual(self.client.get(f'/api/interests/{pk}/messages/').status_code,404)
        self.assertEqual(self.client.post(f'/api/interests/{pk}/messages/',{'text':'Intrusion'}).status_code,404)
        self.assertEqual(Message.objects.count(),1)
        self.client.force_authenticate(self.a)
        self.assertEqual(self.client.get(f'/api/interests/{pk}/messages/').data['results'][0]['sender'],'them')

@override_settings(DEBUG=True, OTP_DELIVERY_MODE='local', OTP_ALLOW_TEST_CODE=False)
class OtpTests(APITestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def request_code(self, mobile='9876543210', name='Test Member'):
        return self.client.post('/api/auth/otp/request/', {'mobile': mobile, 'name': name}, format='json')

    def verify(self, response, code=None):
        return self.client.post('/api/auth/otp/verify/', {'challengeId': response.data['challengeId'], 'mobile': response.data['mobile'], 'code': code or response.data['devOtp']}, format='json')

    def test_minimal_registration_and_returning_login(self):
        response = self.request_code()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['devOtp'], '1234')
        self.assertEqual(User.objects.count(), 0)
        challenge = OtpChallenge.objects.get()
        self.assertNotEqual(challenge.code_hash, response.data['devOtp'])
        result = self.verify(response)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertTrue(result.data['isNewUser'])
        self.assertEqual(MobileAccount.objects.get().mobile, '+919876543210')
        self.assertFalse(User.objects.get().has_usable_password())
        self.assertIsNone(Profile.objects.get().age)
        self.assertEqual(self.verify(response).status_code, 400)
        self.client.credentials(HTTP_AUTHORIZATION='Token '+result.data['token'])
        own = self.client.get('/api/me/').data
        self.assertEqual(own['name'], 'Test Member')
        self.assertEqual(own['mobile'], '+919876543210')
        self.assertTrue(own['verification']['mobileVerified'])
        OtpChallenge.objects.update(last_sent_at=timezone.now()-timedelta(seconds=61))
        response = self.request_code(name='')
        self.assertEqual(response.status_code, 200, response.data)
        result = self.verify(response)
        self.assertFalse(result.data['isNewUser'])
        self.assertEqual(User.objects.count(), 1)

    def test_wrong_code_lockout_and_expiry(self):
        response = self.request_code()
        wrong = '9999'
        for _ in range(5): self.assertEqual(self.verify(response, wrong).status_code, 400)
        self.assertEqual(self.verify(response).status_code, 400)
        self.assertEqual(User.objects.count(), 0)
        OtpChallenge.objects.update(last_sent_at=timezone.now()-timedelta(seconds=61))
        response = self.request_code()
        OtpChallenge.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.verify(response).status_code, 400)

    def test_resend_limits_and_input_validation(self):
        response = self.request_code()
        self.assertEqual(self.request_code().status_code, 429)
        for _ in range(4):
            OtpChallenge.objects.update(last_sent_at=timezone.now()-timedelta(seconds=61))
            self.assertEqual(self.request_code().status_code, 200)
        OtpChallenge.objects.update(last_sent_at=timezone.now()-timedelta(seconds=61))
        self.assertEqual(self.request_code().status_code, 429)
        self.assertEqual(self.request_code(mobile='invalid').status_code, 400)
        self.assertTrue(self.request_code(mobile='9876543211',name='').data['nameRequired'])

    def test_local_codes_are_never_enabled_in_production(self):
        with override_settings(DEBUG=False):
            self.assertEqual(self.request_code().status_code, 503)
        with override_settings(OTP_DELIVERY_MODE='disabled'):
            self.assertEqual(self.request_code().status_code, 503)

    @override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False, OTP_ALLOW_TEST_CODE=True)
    def test_explicit_test_code_with_debug_disabled(self):
        response = self.request_code()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['devOtp'], '1234')
        self.assertEqual(self.verify(response, code='9999').status_code, 400)
        self.assertEqual(self.verify(response, code='1234').status_code, 200)

    def test_incomplete_profiles_hidden_and_mobile_private(self):
        first = self.verify(self.request_code())
        self.client.credentials(HTTP_AUTHORIZATION='Token '+first.data['token'])
        other = User.objects.create_user('other@example.com', password='Some-password-748!')
        other_profile = Profile.objects.create(user=other, name='Other Member', age=25, gender='Groom')
        MobileAccount.objects.create(user=other, mobile='+919876543212',verified_at=timezone.now())
        page = self.client.get('/api/profiles/')
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('mobile', page.data['results'][0])
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get('/api/profiles/').data['count'], 0)

@override_settings(DEBUG=False, OTP_DELIVERY_MODE='msg91', MSG91_AUTH_KEY='test-only-key', MSG91_TEMPLATE_ID='test-template')
class Msg91Tests(APITestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    @patch('matchmaking.otp.send_msg91_otp')
    @patch('matchmaking.otp.secrets.randbelow', return_value=567890)
    def test_sms_code_login_and_no_local_bypass(self, random_code, send):
        response = self.client.post('/api/auth/otp/request/', {'name':'SMS User','mobile':'9876543210'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn('devOtp', response.data)
        self.assertEqual(response.data['otpLength'], 6)
        send.assert_called_once_with('+919876543210', '567890')
        payload = {'challengeId':response.data['challengeId'], 'mobile':response.data['mobile'], 'code':'1234'}
        self.assertEqual(self.client.post('/api/auth/otp/verify/', payload).status_code, 400)
        self.assertEqual(User.objects.count(), 0)
        payload['code'] = '567890'
        self.assertEqual(self.client.post('/api/auth/otp/verify/', payload).status_code, 200)

    @patch('matchmaking.otp.send_msg91_otp', side_effect=SmsDeliveryError('Delivery unavailable.'))
    def test_failed_delivery_does_not_create_account_or_usable_challenge(self, send):
        response = self.client.post('/api/auth/otp/request/', {'name':'SMS User','mobile':'9876543210'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('challengeId', response.data)
        self.assertEqual(User.objects.count(), 0)
        self.assertFalse(OtpChallenge.objects.exclude(code_hash='').exists())

    @patch('matchmaking.sms.urlopen')
    def test_adapter_success_error_and_timeout(self, open_url):
        from urllib.parse import urlparse, parse_qs
        context = MagicMock()
        context.__enter__.return_value = io.BytesIO(b'{"type":"success","message":"queued"}')
        open_url.return_value = context
        send_msg91_otp('+919876543210', '567890')
        request = open_url.call_args.args[0]
        params = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(params['mobile'], ['919876543210'])
        self.assertEqual(params['otp'], ['567890'])
        self.assertNotIn('authkey', params)
        self.assertEqual(request.get_header('Authkey'), 'test-only-key')
        context.__enter__.return_value = io.BytesIO(b'{"type":"error","message":"private-provider-error"}')
        with self.assertRaises(SmsDeliveryError) as error: send_msg91_otp('+919876543210', '567890')
        self.assertNotIn('private-provider-error', str(error.exception))
        open_url.side_effect = URLError('sensitive URL')
        with self.assertRaises(SmsDeliveryError): send_msg91_otp('+919876543210', '567890')
        with override_settings(MSG91_AUTH_KEY=''):
            with self.assertRaises(SmsDeliveryError): send_msg91_otp('+919876543210', '567890')
