from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """Users in the admin: the standard Django user screens (password changes, permissions, groups)."""

    list_display = ["username", "email", "first_name", "last_name", "is_staff", "is_active", "last_login"]
    list_filter = ["is_staff", "is_superuser", "is_active", "groups"]
