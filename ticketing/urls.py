from django.urls import path

from . import views, views_sched as sched, views_scan as scan

urlpatterns = [
	path('sell/', views.SellSailings, name='sell-sailings'),
	path('sell/<int:sailing_id>/', views.TicketSell, name='ticket-sell'),
	path('tickets/', views.TicketList, name='ticket-list'),
	path('tickets/<int:pk>/', views.TicketDetail, name='ticket-detail'),
	path('tickets/<int:pk>/print/', views.TicketPrint, name='ticket-print'),
	path('tickets/<int:pk>/document/', views.TicketDocument, name='ticket-document'),
	path('tickets/<int:pk>/proof/', views.TicketProof, name='ticket-proof'),
	path('sailings/', sched.SailingList, name='sailing-list'),
	path('sailings/add/', sched.SailingAdd, name='sailing-add'),
	path('sailings/<int:pk>/', sched.SailingDetail, name='sailing-detail'),
	path('sailings/<int:pk>/edit/', sched.SailingEdit, name='sailing-edit'),
	path('sailings/<int:pk>/delay/', sched.SailingDelay, name='sailing-delay'),
	path('sailings/<int:pk>/cancel/', sched.SailingCancel, name='sailing-cancel'),
	path('sailings/<int:pk>/move/', sched.SailingMove, name='sailing-move'),
	path('sailings/<int:pk>/<str:action>/', sched.SailingStatus, name='sailing-status'),
	path('announcements/', sched.AnnouncementList, name='announcement-list'),
	path('announcements/add/', sched.AnnouncementAdd, name='announcement-add'),
	path('announcements/<int:pk>/delete/', sched.AnnouncementDelete, name='announcement-delete'),
	path('notifications/', sched.NotificationList, name='notifications'),
	path('tickets/<int:pk>/cancel/', sched.TicketCancel, name='ticket-cancel'),
	path('scan/', scan.ScanPage, name='scan'),
	path('scan/sw.js', scan.ServiceWorker, name='scan-sw'),
	path('scan/manifest.webmanifest', scan.WebManifest, name='scan-manifest'),
	path('scan/api/validate/', scan.ApiValidate, name='scan-validate'),
	path('scan/api/sync/', scan.ApiSync, name='scan-sync'),
	path('scan/api/manifest/<int:sailing_id>/', scan.ApiManifest, name='scan-sailing-manifest'),
]
