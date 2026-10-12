from django.urls import path

from . import views

urlpatterns = [
	path('venda/rota/', views.APIVendaRota.as_view(), name='api-venda-rota'),
	path('venda/diaria/', views.APIVendaDiaria.as_view(), name='api-venda-diaria'),
]
