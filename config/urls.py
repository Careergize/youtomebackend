from django.contrib import admin
from django.urls import path
from matchmaking import views
from matchmaking import otp
from matchmaking import calls
urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', views.health),
    path('api/auth/register/', views.register),
    path('api/auth/login/', views.login),
    path('api/auth/logout/', views.logout),
    path('api/auth/otp/request/', otp.request_otp),
    path('api/auth/otp/verify/', otp.verify_otp),
    path('api/me/', views.Me.as_view()),
    path('api/presence/', views.presence),
    path('api/profiles/', views.Profiles.as_view()),
    path('api/profiles/<uuid:pk>/', views.ProfileDetail.as_view()),
    path('api/profiles/<uuid:pk>/shortlist/', views.shortlist),
    path('api/profiles/<uuid:pk>/interest/', views.send_interest),
    path('api/interests/', views.interests),
    path('api/interests/<int:pk>/', views.respond_interest),
    path('api/interests/<int:pk>/messages/', views.Messages.as_view()),
    path('api/plans/', views.plans),
    path('api/calls/config/', calls.call_config),
    path('api/calls/', calls.calls),
    path('api/calls/<uuid:pk>/', calls.call_detail),
]
