from django.urls import path

from . import views

urlpatterns = [
	path('dash/', views.ReportDash, name='report-dash'),
	path('sales/', views.SalesReport, name='report-sales'),
	path('cashier/', views.CashierReport, name='report-cashier'),
	path('boarding/', views.BoardingReport, name='report-boarding'),
]
