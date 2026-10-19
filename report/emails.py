"""Periodic sales report e-mails (formal reports are written in Portuguese, the State's official language)."""
from datetime import date

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import translation
from django.utils.translation import gettext as _

from . import exports, services as S
from .models import ReportLog

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def period_key(period, first):
	return {'daily': f'{first:%Y-%m-%d}', 'monthly': f'{first:%Y-%m}', 'yearly': f'{first:%Y}'}[period]


def build(period, key_date):
	"""Return (key, subject, body, [(filename, bytes, mimetype)]) for the period containing key_date."""
	first, last = S.period_bounds(period, key_date)
	f = S.Filters(None, first, last)  # the system manager gets every operator
	key = period_key(period, first)
	with translation.override('pt'):
		s = S.summary(f)
		name = {'daily': _("diário"), 'monthly': _("mensal"), 'yearly': _("anual")}[period]
		subject = f"[APORTIL] {_('Relatório de vendas')} {name} — {key}"
		lines = [f"{_('Relatório de vendas')} {name}: {first:%d/%m/%Y}" + ('' if first == last else f" – {last:%d/%m/%Y}"), '',
			f"{_('Bilhetes vendidos')}: {s['tickets']}", f"{_('Passageiros')}: {s['pax']}",
			f"{_('Bruto (USD)')}: {s['gross']:,.2f}", f"{_('Reembolsos (USD)')}: {s['refunds']:,.2f} ({s['refund_tickets']})",
			f"{_('Líquido (USD)')}: {s['net']:,.2f}", f"{_('Bilhetes anulados (erro, não contam)')}: {s['void_tickets']}",
			f"{_('Bilhetes bónus (gratuitos)')}: {s['bonus_tickets']} ({_('valor normal')} USD {s['bonus_value']:,.2f})", '']
		top = S.by_route(f)[:5]
		if top:
			lines.append(_("Por rota") + ':')
			lines += [f"  {r['label']}: ${r['net']:,.2f} ({r['tickets']})" for r in top]
		lines += ['', _("Em anexo: relatório detalhado em PDF e Excel.")]
		files = [(f'aportil-vendas-{key}.pdf', exports.to_pdf(f), 'application/pdf'), (f'aportil-vendas-{key}.xlsx', exports.to_xlsx(f), XLSX)]
	return key, subject, '\n'.join(lines), files


def send(period, key_date, force=False, recipients=None):
	"""Send one report. Returns the ReportLog, or None if it was already sent and force is off."""
	recipients = list(recipients if recipients is not None else settings.REPORT_RECIPIENTS)
	key, subject, body, files = build(period, key_date)
	if not force and ReportLog.objects.filter(period=period, key=key, ok=True).exists():
		return None
	log = ReportLog(period=period, key=key, recipients=', '.join(recipients))
	if not recipients:
		log.error = 'no recipients (REPORT_RECIPIENTS is empty)'
		log.save()
		return log
	try:
		msg = EmailMessage(subject, body, to=recipients)
		for name, data, mime in files:
			msg.attach(name, data, mime)
		msg.send(fail_silently=False)
		log.ok = True
	except Exception as e:  # logged, and the cron run can be retried: failed attempts do not block a re-send
		log.error = f'{type(e).__name__}: {e}'[:300]
	log.save()
	return log
