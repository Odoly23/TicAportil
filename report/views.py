from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from config.decorators import perm_required
from users.models import AuditLog

from . import exports, services as S
from .forms import ReportFilterForm

VIEW = 'ticketing.view_reports'


def _group(request):
	return request.user.groups.all()[0].name if request.user.groups.exists() else 'admin'


def _kpis(user):
	today = timezone.localdate()
	out = []
	for key, (a, b) in (('today', (today, today)), ('month', S.period_bounds('monthly', today)),
			('year', S.period_bounds('yearly', today))):
		out.append({'key': key, **S.summary(S.Filters(user, a, b))})
	return out


@login_required
@perm_required(VIEW)
def ReportDash(request):
	context = {'group': _group(request), 'kpis': _kpis(request.user), 'title': 'Relatóriu', 'legend': 'Dashboard Relatóriu Vendas'}
	return render(request, 'report/chart_dash.html', context)


@login_required
@perm_required(VIEW)
def SalesReport(request):
	form = ReportFilterForm(request.GET or None, user=request.user)
	f = form.filters()
	fmt = request.GET.get('fmt')
	if fmt in ('xlsx', 'pdf') and (not form.is_bound or form.is_valid()):
		data = exports.to_xlsx(f) if fmt == 'xlsx' else exports.to_pdf(f)
		AuditLog.record('report_export', user=request.user, request=request, detail=f'{fmt} {f.start}..{f.end}')
		ctype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if fmt == 'xlsx' else 'application/pdf'
		resp = HttpResponse(data, content_type=ctype)
		resp['Content-Disposition'] = f'attachment; filename="aportil-vendas-{f.start:%Y%m%d}-{f.end:%Y%m%d}.{fmt}"'
		return resp
	ok = not form.is_bound or form.is_valid()
	context = {
		'group': _group(request), 'form': form, 'title': 'Relatóriu', 'legend': 'Relatóriu Vendas', 'f': f, 'ok': ok,
		'summary': S.summary(f) if ok else None,
		'tables': [(t, rows) for t, rows in exports.sections(f)] if ok else [],
		'query': request.GET.urlencode(),
	}
	return render(request, 'report/sales.html', context)


@login_required
@perm_required('ticketing.issue_ticket')
def CashierReport(request):
	try:
		day = date.fromisoformat(request.GET.get('date', ''))
	except ValueError:
		day = timezone.localdate()
	own_only = not request.user.has_perm(VIEW)  # a clerk sees only their own shift; admins see every cashier
	rows = S.cashier_day(request.user, day, cashier=request.user if own_only else None)
	totals = {k: sum(r[k] for r in rows) for k in ('tickets', 'cash', 'transfer', 'refunds', 'drawer')}
	context = {'group': _group(request), 'day': day, 'rows': rows, 'totals': totals, 'own_only': own_only,
		'title': 'Relatóriu', 'legend': 'Relatóriu Kaixa'}
	return render(request, 'report/cashier.html', context)


@login_required
@perm_required(VIEW)
def BoardingReport(request):
	today = timezone.localdate()
	try:
		start = date.fromisoformat(request.GET.get('start', ''))
	except ValueError:
		start = today - timedelta(days=7)
	try:
		end = date.fromisoformat(request.GET.get('end', ''))
	except ValueError:
		end = today
	rows = S.boarding(request.user, start, end)
	context = {'group': _group(request), 'rows': rows, 'start': start, 'end': end, 'title': 'Relatóriu', 'legend': 'Relatóriu Embarke'}
	return render(request, 'report/boarding.html', context)
