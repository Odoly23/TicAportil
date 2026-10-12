from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from config.decorators import perm_required


@login_required
@perm_required('ticketing.view_reports')
def ReportDash(request):
	group = request.user.groups.all()[0].name if request.user.groups.exists() else 'admin'
	context = {
		'group': group,
		'title': 'Relatóriu', 'legend': 'Dashboard Relatóriu Vendas',
	}
	return render(request, 'report/chart_dash.html', context)
