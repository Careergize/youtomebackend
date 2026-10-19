"""Server-side MSG91 SendOTP adapter; never expose provider credentials or responses."""
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError
from django.conf import settings

class SmsDeliveryError(Exception):
    pass

def send_msg91_otp(mobile, code):
    if not settings.MSG91_AUTH_KEY or not settings.MSG91_TEMPLATE_ID:
        raise SmsDeliveryError('MSG91 configuration is incomplete.')
    query = urlencode({'template_id': settings.MSG91_TEMPLATE_ID, 'mobile': mobile.lstrip('+'), 'otp': code, 'otp_length': len(code), 'otp_expiry': 5, 'realTimeResponse': 1})
    request = Request('https://control.msg91.com/api/v5/otp?' + query, data=b'{}', method='POST', headers={'authkey': settings.MSG91_AUTH_KEY, 'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urlopen(request, timeout=10) as response:
            result = json.load(response)
    except (URLError, TimeoutError, OSError, ValueError):
        raise SmsDeliveryError('Unable to deliver SMS. Please try again later.') from None
    if not isinstance(result, dict) or result.get('type') != 'success':
        raise SmsDeliveryError('MSG91 could not send the code. Please try again later.')
