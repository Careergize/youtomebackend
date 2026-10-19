from django.contrib.auth.models import User
from rest_framework.test import APITestCase, APIClient
from .models import Profile


class PublicPreviewTests(APITestCase):
    def test_preview_is_public_limited_and_omits_private_details(self):
        for index in range(14):
            user = User.objects.create_user(username=f'preview-{index}')
            Profile.objects.create(user=user, name=f'Member {index}', gender='Bride', age=25,
                details={'photos': ['https://example.com/photo.jpg', 'https://example.com/private.jpg'],
                         'dateOfBirth': '2000-01-01', 'bio': 'Private biography',
                         'family': {'fatherOccupation': 'Private occupation'},
                         'occupation': {'title': 'Engineer', 'employer': 'Private employer'}})
        hidden_user = User.objects.create_user(username='hidden')
        Profile.objects.create(user=hidden_user, name='Hidden', gender='Groom', age=30, is_active=False)
        incomplete_user = User.objects.create_user(username='incomplete')
        Profile.objects.create(user=incomplete_user, name='Incomplete', gender='', age=None)
        response = self.client.get('/api/profiles/preview/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 12)
        for profile in response.data:
            self.assertNotIn(profile['name'], ['Hidden', 'Incomplete'])
            self.assertNotIn('mobile', profile)
            self.assertEqual(profile['dateOfBirth'], '')
            self.assertEqual(profile['bio'], '')
            self.assertNotEqual(profile['family']['fatherOccupation'], 'Private occupation')
            self.assertEqual(profile['occupation']['title'], 'Engineer')
            self.assertEqual(profile['occupation']['employer'], '')
            self.assertEqual(profile['photos'], ['https://example.com/photo.jpg'])
        member_id = response.data[0]['id']
        self.assertEqual(APIClient().get('/api/profiles/').status_code, 401)
        self.assertEqual(APIClient().get(f'/api/profiles/{member_id}/').status_code, 401)
        self.assertEqual(APIClient().post(f'/api/profiles/{member_id}/interest/').status_code, 401)

    def test_empty_preview_is_empty(self):
        self.assertEqual(self.client.get('/api/profiles/preview/').data, [])
