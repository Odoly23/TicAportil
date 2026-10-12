from datetime import timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from custom.models import Route
from ticketing.models import Ticket

VALID = [Ticket.Status.ISSUED, Ticket.Status.BOARDED]


class APIVendaRota(APIView):
	"""Tickets sold per route (valid tickets only)."""
	authentication_classes = [SessionAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request, format=None):
		label, obj = list(), list()
		for r in Route.objects.filter(is_active=True):
			label.append(str(r))
			obj.append(Ticket.objects.filter(sailing__route=r, status__in=VALID).aggregate(n=Sum('quantity'))['n'] or 0)
		return Response({'label': label, 'obj': obj})


class APIVendaDiaria(APIView):
	"""Revenue (USD) per day for the last 30 days."""
	authentication_classes = [SessionAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request, format=None):
		since = timezone.now() - timedelta(days=30)
		rows = (Ticket.objects.filter(created_at__gte=since, status__in=VALID)
			.annotate(day=TruncDate('created_at')).values('day').annotate(n=Count('id')).order_by('day'))
		return Response({
			'label': [r['day'].strftime('%d/%m') for r in rows],
			'obj': [r['n'] for r in rows],
		})
