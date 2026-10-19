# YOU2ME Django backend

Python 3.12+; Django 5.2 and Django REST Framework. SQLite is the default local development database. The backend loads backend/.env automatically; setting DB_HOST selects PostgreSQL. The local RDS configuration requires access to its private VPC network (for example through a VPN or EC2 tunnel).

## Run locally

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8001
```

In a second terminal:

```powershell
cd UI
npm install
npm run dev
```

Open http://127.0.0.1:5174. Vite forwards `/api` requests to Django at http://127.0.0.1:8001. These dedicated ports avoid conflicts with other local projects. The welcome popup uses name, mobile number, and OTP; debug mode displays a local test code. Complete profile details after login. Existing email/password accounts can log in at `/login/email`. Create a second account in a different browser session to test sending and accepting interests. The database starts empty; existing fictional UI profiles are not imported as real members. Admin is at http://127.0.0.1:8001/admin/ and can verify or deactivate profiles.

If Windows' Python app alias does not work, use the full path to your installed Python executable. On the development machine used for this project, that is `C:\Users\server\AppData\Local\Python\pythoncore-3.14-64\python.exe`.

## API

### Profile details

`PATCH /api/me/` accepts personal, education, career, family, horoscope, biography, photos, and partner-preference fields shown by My Profile. Additional fields include `weightKg` (optional numeric string, 20–300 kg), `bodyType`, `profileCreatedBy`, `gothram`, and `dateOfBirth` (ISO date; calculates adult age on save). Family details include sisters, brothers, ancestral origin, and family status. Career details include employment type, teaching/academia, and income brackets below 10 lakhs. Horoscope documents use an HTTP/HTTPS `horoscope.horoscopeUrl`; file upload is not implemented. These optional details use the existing JSON storage, so no database migration is required. Nested updates preserve other saved fields. Blank partner-preference lists mean any; age and height ranges are validated. Mobile numbers remain owner-only, and no paid contact-unlock behavior is added.

### Mobile OTP signup and login

Temporary current behavior: settings force local delivery and enable the fixed code `1234` for all users, including with debug disabled. No SMS is sent. The popup prefills the code, and new users continue to profile registration after verification. Restore the environment-based OTP_DELIVERY_MODE and OTP_ALLOW_TEST_CODE settings in config/settings.py to resume the delivery configuration described below.

The welcome popup collects only name and mobile number. `POST /api/auth/otp/request/` accepts `mobile` and optional `name` (required for a new number). `POST /api/auth/otp/verify/` accepts `challengeId`, `mobile`, and a `code` (four digits locally, six digits with MSG91). Verification creates a minimal account only once and returns `token` and `isNewUser`. New users continue to `/profile` to add remaining details. Incomplete profiles are excluded from discovery until age and profile type are supplied. Mobile numbers are visible only in the owner's `/api/me/` response and Django admin, not other members' profile responses.

MSG91 delivery is supported. With Django debug mode enabled, the default remains local test delivery. In production, select MSG91 and configure its credentials; local test access requires explicitly setting OTP_ALLOW_TEST_CODE=true. You can also select local delivery explicitly in the terminal that starts Django:

```powershell
$env:OTP_DELIVERY_MODE = 'local'
python manage.py runserver 127.0.0.1:8001
```

This displays the fixed development OTP `1234` in the popup; no SMS is sent. For temporary testing with `DJANGO_DEBUG=false`, set `OTP_DELIVERY_MODE=local` and `OTP_ALLOW_TEST_CODE=true`, then restart the backend. This permits access using the public test code `1234`; set `OTP_ALLOW_TEST_CODE=false` when testing ends. MSG91 mode generates a random six-digit OTP, sends it using SendOTP, and verifies the saved hash in Django. Provider failure prevents issuing a usable new challenge. `.env.example` documents variables; backend/.env is loaded automatically, while existing process environment variables take precedence. Existing email accounts remain available at `/login/email`; mobile signup does not automatically link them.

Codes expire after five minutes, are stored as hashes, allow five verification attempts, and are consumed on success. Resends reset the challenge lifetime and attempts, require a 60-second wait, and are capped at five per mobile number per hour. The local code remains `1234`. API authentication endpoints also use IP throttling. Use PostgreSQL for production row locking and a shared cache for multi-worker throttles.

All paths begin with `/api/`. Send `Authorization: Token <token>` for protected requests. Registration and login return a token; logout revokes it. The UI keeps it in sessionStorage.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | health/ | Health check, public |
| POST | auth/register/ | Create account and profile, public |
| POST | auth/login/ | Email/password login, public |
| POST | auth/logout/ | Revoke token |
| GET, PATCH | me/ | Read/update own profile |
| GET | profiles/ | Paginated discovery, excludes own/inactive profiles |
| GET | profiles/{uuid}/ | Profile detail |
| POST, DELETE | profiles/{uuid}/shortlist/ | Save/remove shortlist, idempotent |
| POST | profiles/{uuid}/interest/ | Send interest, idempotent |
| GET | interests/ | Own sent/received interests |
| PATCH | interests/{id}/ | Recipient accepts/declines pending interest |
| GET, POST | interests/{id}/messages/ | Paginated messages; accepted participants only |
| GET | plans/ | Plan identifiers, public |

Registration body: `email`, `password`, `firstName`, `lastName`, `gender` (`Bride`/`Groom`), `age` (18–100), `city`, optional `religion`. Login uses `email` and `password`. Interest response uses `{"status":"accepted"}` or `{"status":"declined"}`. Message creation uses `{"text":"Hello"}`.

Profiles use the UI's camelCase shape, including education, occupation, family, horoscope, partnerPreferences and photo URL arrays. Only the current user's profile is writable; verification flags and derived relationship fields are server controlled. Photos are URLs; binary upload and document verification are not implemented.

Discovery query parameters: `searchQuery`, `gender`, `city`, `religion`, `minAge`, `maxAge`, `minHeightInches`, `maxHeightInches`, `verifiedOnly=true`, `shortlisted=true`, `manglikOnly=true`, and repeated `maritalStatuses`, `educationList`, `occupationSectors`, `incomeBrackets`, `dietList`. `sortBy=ageAsc` or `ageDesc` sorts server results. The UI loads pages and applies its existing compatibility sort and filters. Compatibility is the percentage of stated preference checks satisfied, or zero when no preferences exist; it is not a horoscope prediction.

Chat polls every five seconds. Profile pass/undo stays local to the UI. Premium purchase, payment processing, real SMS delivery, email verification, password reset, photo upload, and real contact sharing need separate integrations; no backend payment activation is exposed.

## Validate

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test matchmaking
```

For deployment set `DJANGO_DEBUG=false`, a unique `DJANGO_SECRET_KEY`, and comma-separated `DJANGO_ALLOWED_HOSTS`. Configure HTTPS and same-origin routing for `/api` and `/admin`, collect static files, use a production WSGI/ASGI server, and provision a production database and shared cache. Development throttles use Django's local cache. Never serve production with `runserver`.

### Enable MSG91 SMS delivery

Set these server environment variables before restarting Django:

```powershell
$env:OTP_DELIVERY_MODE = 'msg91'
$env:MSG91_AUTH_KEY = 'your-private-auth-key'
$env:MSG91_TEMPLATE_ID = 'your-otp-template-id'
python manage.py runserver 127.0.0.1:8001
```

Keep credentials on the server; never put them in Vite variables or commit them. Configure your OTP template and sender/DLT requirements in your MSG91 dashboard. See [MSG91 OTP template setup](https://msg91.com/help/sendotp/where-to-find-the-sendotp-api-how-to-get-template-id) and [OTP API documentation](https://docs.msg91.com/otp). The code supports the SendOTP product, not OTP Widget. No live SMS test has been performed without credentials. The `1234` bypass works only with debug mode and `OTP_DELIVERY_MODE=local`, and cannot authenticate a MSG91 challenge.


## Browser voice and video calls

Open a chat with an accepted connection and select the phone or camera button. The recipient sees an incoming-call panel anywhere on the site while logged in, with Accept and Decline controls. Both participants can hang up or mute their microphone; video calls also have a camera toggle. Allow microphone/camera access when the browser asks. Incoming calls are polled every 2.5 seconds and require the site to remain open; there are no push notifications for closed browsers.

Calls use WebRTC media between browsers. Django provides authenticated signaling at `GET/POST /api/calls/`, `GET/PATCH /api/calls/{uuid}/`, and `GET /api/calls/config/`. Only accepted connection participants can start calls or exchange descriptions and ICE candidates. Simultaneous calls are rejected as busy. Unanswered calls expire after 60 seconds; a participant missing heartbeats ends the call after 90 seconds. Audio/video is not uploaded or recorded by this backend. Signaling polling has a separate request budget from normal API actions.

Local development works at http://127.0.0.1:5174. Deployed calling requires HTTPS and browser media permissions. The default configuration supplies a STUN server. For reliable calls between different networks, configure a TURN relay through the server environment, for example:

```powershell
$env:WEBRTC_ICE_SERVERS = '[{"urls":"stun:stun.l.google.com:19302"},{"urls":"turn:YOUR-TURN-HOST:3478","username":"YOUR-USERNAME","credential":"YOUR-CREDENTIAL"}]'
python manage.py runserver 127.0.0.1:8001
```

The backend loads `backend/.env` automatically; existing process environment variables take precedence. Restart Django after setting variables. TURN credentials are delivered to authenticated browsers as required by WebRTC; use short-lived relay credentials for production. A real TURN service is not provisioned by this project. Media connectivity across restrictive networks must be checked with that service configured.

If an accepted call stays on Connecting, test both devices on the same Wi-Fi. A successful same-network call followed by failure across networks points to a relay/connectivity problem. Configure a real TURN service in `WEBRTC_ICE_SERVERS` on the deployed backend, including the URLs, username, and credential supplied by that service. Include TURN over TLS on port 443 if the provider supports it for restrictive networks. Restart the backend and test across Wi-Fi and mobile data. Do not substitute placeholder credentials or assume a STUN-only setup provides relay support. The frontend ends an accepted call after 30 seconds without a media connection and shows a connection timeout message.
