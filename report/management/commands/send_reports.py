from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from report import emails


class Command(BaseCommand):
	help = ("E-mail the sales report to REPORT_RECIPIENTS. Defaults: daily = today, monthly = previous month, "
		"yearly = previous year. Safe to re-run: an already sent report is skipped unless --force.")

	def add_arguments(self, parser):
		parser.add_argument('--period', choices=['daily', 'monthly', 'yearly'], required=True)
		parser.add_argument('--date', help='Any date inside the wanted period (YYYY-MM-DD)')
		parser.add_argument('--force', action='store_true', help='Send even if this period was already sent')

	def handle(self, *args, **o):
		today = timezone.localdate()
		if o['date']:
			try:
				d = date.fromisoformat(o['date'])
			except ValueError:
				raise CommandError('--date must be YYYY-MM-DD')
		elif o['period'] == 'daily':
			d = today
		elif o['period'] == 'monthly':
			d = today.replace(day=1) - timedelta(days=1)
		else:
			d = today.replace(month=1, day=1) - timedelta(days=1)
		log = emails.send(o['period'], d, force=o['force'])
		if log is None:
			self.stdout.write('Already sent, skipped.')
		elif log.ok:
			self.stdout.write(self.style.SUCCESS(f'Sent {log.period} {log.key} to {log.recipients}'))
		else:
			raise CommandError(f'Report {log.period} {log.key} NOT sent: {log.error}')
