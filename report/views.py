from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from config.decorators import allowed_users


@login_required
@allowed_users(allowed_roles=['admin', 'operator'])
def ReportDash(request):
	group = request.user.groups.all()[0].name if request.user.groups.exists() else 'admin'
	context = {
		'group': group,
		'title': 'Relatóriu', 'legend': 'Dashboard Relatóriu Vendas',
	}
	return render(request, 'report/chart_dash.html', context)
