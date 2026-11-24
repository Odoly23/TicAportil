from django.contrib import admin

from .models import Announcement, Sailing, SailingQuota, Ticket


class QuotaInline(admin.TabularInline):
    model = SailingQuota
    extra = 0


@admin.register(Sailing)
class SailingAdmin(admin.ModelAdmin):
    list_display = ("vessel", "route", "departure", "status")
    list_filter = ("status", "route", "vessel__operator")
    inlines = [QuotaInline]


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("serial", "sailing", "item", "full_name", "status", "created_at")
    list_filter = ("status", "item__quota_group")
    search_fields = ("serial", "full_name", "document_number")
    readonly_fields = ("serial", "created_at")


admin.site.register(Announcement)

