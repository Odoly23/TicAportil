from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from report import emails


class Command(BaseCommand):
	help = ("One daily job for hosts that only offer a daily scheduler (e.g. PythonAnywhere). Run it just after midnight, Dili time: "
		"it sends yesterday's daily report, on the 1st also last month's report, on 1 January also last year's. "
		"Already-sent reports are skipped, so running it twice is harmless.")

	def handle(self, *args, **o):
		today = timezone.localdate()
		yesterday = today - timedelta(days=1)
		due = [('daily', yesterday)]
		if today.day == 1:
			due.append(('monthly', yesterday))        # yesterday belongs to the month that just ended
			if today.month == 1:
				due.append(('yearly', yesterday))     # ...and to the year that just ended
		failed = []
		for period, day in due:
			log = emails.send(period, day)
			if log is None:
				self.stdout.write(f'{period} {day}: already sent')
			elif log.ok:
				self.stdout.write(self.style.SUCCESS(f'{period} {log.key}: sent to {log.recipients}'))
			else:
				failed.append(f'{period} {log.key}: {log.error}')
				self.stderr.write(f'{period} {log.key}: NOT sent ({log.error})')
		if failed:
			raise SystemExit(1)  # non-zero exit so the host's task log shows the failure
