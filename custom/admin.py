from django.contrib import admin

from .models import Fare, FareItem, Operator, Port, Route, Vessel


class FareInline(admin.TabularInline):
	model = Fare
	extra = 0


@admin.register(FareItem)
class FareItemAdmin(admin.ModelAdmin):
	list_display = ("name_tet", "quota_group", "is_active", "sort_order")
	inlines = [FareInline]


for m in (Port, Route, Operator, Vessel):
	admin.site.register(m)
