from django.urls import path

from . import views

urlpatterns = [path('fares/', views.FareMatrix, name='fare-matrix')]
for c in views.CRUDS:
	urlpatterns += c.urls()
