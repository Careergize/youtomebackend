from django.contrib import admin
from .models import Profile, Shortlist, Interest, Message, MobileAccount

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['name','gender','age','city','is_verified','is_active']
    list_filter = ['gender','is_verified','is_active']
    search_fields = ['name','city','user__email']

admin.site.register([Shortlist, Interest, Message])
@admin.register(MobileAccount)
class MobileAccountAdmin(admin.ModelAdmin):
    list_display = ['mobile', 'user', 'verified_at']
    search_fields = ['mobile', 'user__username']
    readonly_fields = ['mobile', 'user', 'verified_at']
