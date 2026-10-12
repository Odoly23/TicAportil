from django.urls import path

from . import views

urlpatterns = [
	path('dash/', views.ReportDash, name='report-dash'),
]
