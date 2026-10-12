from django.urls import path

from . import views

urlpatterns = [
	path('sell/', views.SellSailings, name='sell-sailings'),
	path('sell/<int:sailing_id>/', views.TicketSell, name='ticket-sell'),
	path('tickets/', views.TicketList, name='ticket-list'),
	path('tickets/<int:pk>/', views.TicketDetail, name='ticket-detail'),
	path('tickets/<int:pk>/print/', views.TicketPrint, name='ticket-print'),
	path('tickets/<int:pk>/document/', views.TicketDocument, name='ticket-document'),
	path('tickets/<int:pk>/proof/', views.TicketProof, name='ticket-proof'),
]
