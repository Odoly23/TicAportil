from django.urls import path

from . import views

urlpatterns = [
	path('venda/rota/', views.APIVendaRota.as_view(), name='api-venda-rota'),
	path('venda/diaria/', views.APIVendaDiaria.as_view(), name='api-venda-diaria'),
	path('venda/navio/', views.APIVendaNavio.as_view(), name='api-venda-navio'),
	path('venda/pagamentu/', views.APIVendaPagamentu.as_view(), name='api-venda-pagamentu'),
	path('venda/kategoria/', views.APIVendaKategoria.as_view(), name='api-venda-kategoria'),
]
