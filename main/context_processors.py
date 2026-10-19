from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.translation import gettext_lazy as _

# Menu entries. A leaf is (url name, label, FontAwesome 4 icon, permission or None). A group is
# (None, label, icon, None, [leaves]): it renders as a dropdown on desktop and is flattened in the mobile sidebar.
# A group with a single visible child collapses into that child. Add new modules here.
MENU = [
	('home', _("Painel"), 'fa-home', None),
	(None, _("Bilhete"), 'fa-ticket', None, [
		('sell-sailings', _("Sosa Bilhete"), 'fa-ticket', 'ticketing.issue_ticket'),
		('ticket-list', _("Lista Bilhete"), 'fa-list', 'ticketing.issue_ticket'),
	]),
	('scan', _("Scan QR"), 'fa-qrcode', 'ticketing.scan_ticket'),
	(None, _("Jadwal"), 'fa-calendar', None, [
		('sailing-list', _("Jadwal"), 'fa-calendar', 'ticketing.manage_schedule'),
		('announcement-list', _("Anúnsiu"), 'fa-bullhorn', 'ticketing.manage_schedule'),
	]),
	('notifications', _("Notifikasaun"), 'fa-bell', 'ticketing.manage_schedule'),
	(None, _("Relatóriu"), 'fa-bar-chart', None, [
		('report-dash', _("Dashboard"), 'fa-bar-chart', 'ticketing.view_reports'),
		('report-sales', _("Relatóriu Vendas"), 'fa-table', 'ticketing.view_reports'),
		('report-cashier', _("Relatóriu Kaixa"), 'fa-money', 'ticketing.issue_ticket'),
		('report-boarding', _("Relatóriu Embarke"), 'fa-ship', 'ticketing.view_reports'),
	]),
	(None, _("Jestaun"), 'fa-cog', None, [
		('fare-matrix', _("Presu"), 'fa-usd', 'custom.change_fare'),
		('fareitem-list', _("Kategoria"), 'fa-tags', 'custom.change_fareitem'),
		('route-list', _("Rota"), 'fa-road', 'custom.change_route'),
		('port-list', _("Porta"), 'fa-anchor', 'custom.change_port'),
		('operator-list', _("Operadór"), 'fa-building', 'custom.change_operator'),
		('vessel-list', _("Ró"), 'fa-ship', 'custom.change_vessel'),
		('bonus-policy', _("Batas Bonus"), 'fa-gift', 'ticketing.change_bonuspolicy'),
		('user-list', _("Uza-na'in"), 'fa-users', 'users.change_user'),
		('audit-list', _("Audit Log"), 'fa-history', 'users.view_auditlog'),
		('admin:index', _("Django admin"), 'fa-wrench', '__staff__'),
	]),
]


def role(request):
	"""Expose the user's role, the nested menu (desktop) and the flat menu (sidebar), filtered by permissions."""
	user = request.user
	if not user.is_authenticated:
		return {'role': None, 'menu': [], 'menu_flat': []}
	if user.is_superuser:
		r = 'admin'
	else:
		g = user.groups.first()
		r = g.name if g else None
	current = getattr(getattr(request, 'resolver_match', None), 'url_name', None)
	unread = user.notifications.filter(read_at__isnull=True).count() if user.has_perm('ticketing.manage_schedule') else 0

	def leaf(e):
		name, label, icon, perm = e
		if perm == '__staff__':
			if not user.is_staff:
				return None
		elif perm is not None and not user.has_perm(perm):
			return None
		return {'url': name, 'label': label, 'icon': icon, 'active': name == current, 'badge': unread if name == 'notifications' else 0, 'children': None}

	menu, flat = [], []
	for e in MENU:
		if e[0] is not None:
			item = leaf(e)
		else:
			kids = [k for k in (leaf(c) for c in e[4]) if k]
			item = None if not kids else kids[0] if len(kids) == 1 else {
				'url': None, 'label': e[1], 'icon': e[2], 'children': kids, 'badge': 0, 'active': any(k['active'] for k in kids)}
		if item:
			menu.append(item)
			flat.extend(item['children'] or [item])
	return {'role': r, 'menu': menu, 'menu_flat': flat}


def logo(request):
	"""Use main/static/main/images/logo.png when present, else fall back to the text/icon brand."""
	return {'logo_url': static('main/images/logo.png') if finders.find('main/images/logo.png') else None}
