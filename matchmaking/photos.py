import io
import warnings
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Profile


@api_view(['POST'])
def upload_photo(request):
    get_object_or_404(Profile, user=request.user, is_active=True)
    photo = serializers.FileField(max_length=255).run_validation(request.FILES.get('photo'))
    if photo.size > 5 * 1024 * 1024:
        raise serializers.ValidationError({'photo': 'Choose a photo smaller than 5 MB.'})
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(photo) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise serializers.ValidationError({'photo': 'Choose a JPEG, PNG, or WebP photo.'})
                if source.width * source.height > 20000000:
                    raise serializers.ValidationError({'photo': 'Choose a photo with at most 20 megapixels.'})
                source.load()
                image = ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((1600, 1600))
                output = io.BytesIO()
                image.save(output, format='JPEG', quality=88)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise serializers.ValidationError({'photo': 'This image could not be read. Choose a valid JPEG, PNG, or WebP photo.'})
    photo_id = uuid4()
    default_storage.save(f'profile-photos/{photo_id}.jpg', ContentFile(output.getvalue()))
    return Response({'url': request.build_absolute_uri(reverse('profile-photo', kwargs={'photo_id': photo_id}))}, status=201)


def profile_photo(request, photo_id):
    try:
        photo = default_storage.open(f'profile-photos/{photo_id}.jpg', 'rb')
    except FileNotFoundError:
        raise Http404
    response = FileResponse(photo, content_type='image/jpeg')
    response['Cache-Control'] = 'public, max-age=31536000, immutable'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
