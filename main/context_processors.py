from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.translation import gettext_lazy as _

# (url name, label, FontAwesome 4 icon, required permission or None). Add new modules here; the desktop
# navbar and the mobile sidebar both render from this single list, filtered by the user's permissions.
MENU = [
	('home', _("Painel"), 'fa-home', None),
	('sell-sailings', _("Sosa Bilhete"), 'fa-ticket', 'ticketing.issue_ticket'),
	('ticket-list', _("Lista Bilhete"), 'fa-list', 'ticketing.issue_ticket'),
	('sailing-list', _("Jadwal"), 'fa-calendar', 'ticketing.manage_schedule'),
	('announcement-list', _("Anúnsiu"), 'fa-bullhorn', 'ticketing.manage_schedule'),
	('notifications', _("Notifikasaun"), 'fa-bell', 'ticketing.manage_schedule'),
	('report-dash', _("Relatóriu"), 'fa-bar-chart', 'ticketing.view_reports'),
]


def role(request):
	"""Expose the user's role ('admin', 'resepsionista', ...) and the menu they may see."""
	user = request.user
	if not user.is_authenticated:
		return {'role': None, 'menu': []}
	if user.is_superuser:
		r = 'admin'
	else:
		g = user.groups.first()
		r = g.name if g else None
	current = getattr(getattr(request, 'resolver_match', None), 'url_name', None)
	unread = 0
	if user.has_perm('ticketing.manage_schedule'):
		unread = user.notifications.filter(read_at__isnull=True).count()
	menu = [
		{'url': name, 'label': label, 'icon': icon, 'active': name == current, 'badge': unread if name == 'notifications' else 0}
		for name, label, icon, perm in MENU if perm is None or user.has_perm(perm)
	]
	return {'role': r, 'menu': menu}


def logo(request):
	"""Use main/static/main/images/logo.png when present, else fall back to the text/icon brand."""
	return {'logo_url': static('main/images/logo.png') if finders.find('main/images/logo.png') else None}
