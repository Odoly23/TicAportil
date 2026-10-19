from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuditLog, User


@admin.register(User)
class StaffUserAdmin(UserAdmin):
	fieldsets = UserAdmin.fieldsets + (("APORTIL", {"fields": ("preferred_language", "operator", "phone")}),)
	add_fieldsets = UserAdmin.add_fieldsets + (("APORTIL", {"fields": ("preferred_language", "operator", "phone")}),)
	list_display = ("username", "get_full_name", "operator", "is_active", "last_login")
	list_filter = ("groups", "is_active", "operator")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
	list_display = ("created_at", "username", "action", "ip")
	list_filter = ("action",)
	search_fields = ("username", "detail")

	def has_add_permission(self, request):
		return False

	def has_change_permission(self, request, obj=None):
		return False

	def has_delete_permission(self, request, obj=None):
		return False
