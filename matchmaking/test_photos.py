import io
from PIL import Image
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase, APIClient
from .models import Profile


class PhotoUploadTests(APITestCase):
    def setUp(self):
        settings = override_settings(STORAGES={
            'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        })
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = User.objects.create_user(username='photo-member')
        self.profile = Profile.objects.create(user=self.user, name='Photo Member', age=25, gender='Bride')
        self.client.force_authenticate(self.user)

    def test_upload_save_and_retrieve_photo(self):
        output = io.BytesIO()
        Image.new('RGB', (2000, 1000), 'red').save(output, 'PNG')
        photo = SimpleUploadedFile('photo.png', output.getvalue(), content_type='image/png')
        response = self.client.post('/api/me/photo/', {'photo': photo}, format='multipart', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 201, response.data)
        url = response.data['url']
        saved = self.client.patch('/api/me/', {'photos': [url]}, format='json')
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(self.client.get('/api/me/').data['photos'], [url])
        image_response = APIClient().get(url)
        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response['Content-Type'], 'image/jpeg')
        with Image.open(io.BytesIO(b''.join(image_response.streaming_content))) as image:
            self.assertEqual(image.size, (1600, 800))
        image_response.close()

    def test_rejects_invalid_oversized_and_unauthenticated_uploads(self):
        self.assertEqual(APIClient().post('/api/me/photo/').status_code, 401)
        self.assertEqual(self.client.post('/api/me/photo/', {}, format='multipart').status_code, 400)
        invalid = SimpleUploadedFile('fake.jpg', b'not an image', content_type='image/jpeg')
        self.assertEqual(self.client.post('/api/me/photo/', {'photo': invalid}, format='multipart').status_code, 400)
        oversized = SimpleUploadedFile('large.jpg', b'x' * (5 * 1024 * 1024 + 1), content_type='image/jpeg')
        self.assertEqual(self.client.post('/api/me/photo/', {'photo': oversized}, format='multipart').status_code, 400)

    def test_missing_photo_returns_404(self):
        self.assertEqual(APIClient().get('/api/photos/00000000-0000-0000-0000-000000000000/').status_code, 404)
