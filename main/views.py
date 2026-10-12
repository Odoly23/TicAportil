from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from custom.models import Fare
from ticketing.models import Announcement, Sailing


def landing(request):
	"""Public page: upcoming sailings, fares and announcements. Passengers need no account."""
	sailings = (
		Sailing.objects.filter(departure__gte=timezone.now() - timedelta(hours=1))
		.exclude(status=Sailing.Status.COMPLETED)
		.select_related("vessel__operator", "route__origin", "route__destination")[:30]
	)
	fares = (
		Fare.objects.filter(item__is_active=True, route__is_active=True)
		.select_related("route__origin", "route__destination", "item")
		.order_by("route__origin__name", "item__quota_group", "item__sort_order")
	)
	return render(request, "home/home.html", {
		"title": "Horáriu",
		"sailings": sailings,
		"fares": fares,
		"announcements": Announcement.objects.filter(is_public=True, created_at__gte=timezone.now() - timedelta(days=7))[:5],
	})


@login_required
def dashboard(request):
	group = request.user.groups.all()[0].name if request.user.groups.exists() else 'admin'
	return render(request, "main/dashboard.html", {"group": group, "title": "Painel", "legend": "Painel"})


def error_403(request, exception=None):
	return render(request, "home/403.html", status=403)


def error_404(request, exception=None):
	return render(request, "home/404.html", status=404)


def error_500(request):
	return render(request, "home/500.html", status=500)
