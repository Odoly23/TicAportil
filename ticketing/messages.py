"""Schedule-change messages, rendered per language (tet/pt/en/id) from stored (kind, data)."""
from django.utils import timezone, translation
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _

LANGS = ('tet', 'pt', 'en', 'id')


def _fmt(iso):
	if not iso:
		return ''
	return timezone.localtime(parse_datetime(iso)).strftime('%d/%m/%Y %H:%M')


def render(kind, data, lang=None):
	"""Return (title, body) for the given language (default: the active one)."""
	with translation.override(lang or translation.get_language() or 'tet'):
		v = {'route': data.get('route', ''), 'vessel': data.get('vessel', ''), 'old': _fmt(data.get('old')),
			'new': _fmt(data.get('new')), 'note': data.get('note', '')}
		if kind == 'delayed':
			title = _("Viajen %(route)s atrazadu") % v
			body = _("Viajen %(route)s (%(vessel)s) muda husi %(old)s ba %(new)s. Razaun: %(note)s. Bilhete mak iha validu nafatin.") % v
		elif kind == 'cancelled_moved':
			title = _("Viajen %(route)s kansela") % v
			body = _("Viajen %(route)s (%(vessel)s) iha %(old)s kansela. Razaun: %(note)s. Bilhete hasai ona ba viajen foun iha %(new)s.") % v
		elif kind == 'cancelled':
			title = _("Viajen %(route)s kansela") % v
			body = _("Viajen %(route)s (%(vessel)s) iha %(old)s kansela. Razaun: %(note)s. Favór kontaktu loket APORTIL.") % v
		elif kind == 'tickets_moved':
			title = _("Bilhete muda viajen")
			body = _("Bilhete husi viajen %(route)s (%(old)s) muda ona ba viajen %(new)s.") % v
		else:
			return ('', '')
		return title, body


def render_all(kind, data):
	"""Four-language text (for email): returns (subject, body)."""
	parts = [(lang, *render(kind, data, lang)) for lang in LANGS]
	subject = ' / '.join(dict.fromkeys(p[1] for p in parts if p[0] in ('tet', 'en')))
	body = '\n\n'.join(f"[{lang.upper()}] {t}\n{b}" for lang, t, b in parts)
	return subject, body
