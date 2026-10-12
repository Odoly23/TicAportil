from django.utils.translation import gettext_lazy as _

# (url name, label, FontAwesome 4 icon, roles allowed). Add new modules here; the desktop navbar
# and the mobile sidebar both render from this single list.
MENU = [
	('home', _("Painel"), 'fa-home', ('admin', 'resepsionista', 'inspector', 'operator')),
	('report-dash', _("Relatóriu"), 'fa-bar-chart', ('admin', 'operator')),
]


def role(request):
	"""Expose the user's role ('admin', 'resepsionista', 'inspector', 'operator') and its menu."""
	user = request.user
	if not user.is_authenticated:
		return {'role': None, 'menu': []}
	if user.is_superuser:
		r = 'admin'
	else:
		g = user.groups.first()
		r = g.name if g else None
	current = getattr(getattr(request, 'resolver_match', None), 'url_name', None)
	menu = [
		{'url': name, 'label': label, 'icon': icon, 'active': name == current}
		for name, label, icon, roles in MENU if r in roles
	]
	return {'role': r, 'menu': menu}
