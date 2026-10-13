from datetime import date, timedelta

from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from report import services as S


class CanViewReports(BasePermission):
	def has_permission(self, request, view):
		return request.user.is_authenticated and request.user.has_perm('ticketing.view_reports')


class ReportAPI(APIView):
	"""Base: last 30 days by default, always limited to the caller's own scope (operators see only their vessels)."""
	authentication_classes = [SessionAuthentication]
	permission_classes = [IsAuthenticated, CanViewReports]

	def filters(self, request):
		today = timezone.localdate()
		def d(name, default):
			try:
				return date.fromisoformat(request.GET.get(name, ''))
			except ValueError:
				return default
		start, end = d('from', today - timedelta(days=29)), d('to', today)
		if end < start or (end - start).days > 1100:
			start, end = today - timedelta(days=29), today
		return S.Filters(request.user, start, end)

	def rows(self, f):
		raise NotImplementedError

	def get(self, request, format=None):
		rows = self.rows(self.filters(request))
		return Response({'label': [str(r['label']) for r in rows], 'obj': [float(r['net']) for r in rows],
			'obj2': [r['tickets'] for r in rows]})


class APIVendaRota(ReportAPI):
	def rows(self, f):
		return S.by_route(f)


class APIVendaNavio(ReportAPI):
	def rows(self, f):
		return S.by_vessel(f)


class APIVendaPagamentu(ReportAPI):
	def rows(self, f):
		return S.by_payment(f)


class APIVendaKategoria(ReportAPI):
	def rows(self, f):
		return S.by_item(f)


class APIVendaDiaria(ReportAPI):
	def rows(self, f):
		return [{'label': r['day'].strftime('%d/%m'), 'net': r['net'], 'tickets': r['tickets']} for r in S.daily_series(f)]
