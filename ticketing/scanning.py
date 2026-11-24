"""Boarding validation shared by the online endpoint and the offline sync."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import ScanEvent, Sailing, Ticket

R = ScanEvent.Result
BOARDABLE = (Ticket.Status.ISSUED,)


def parse_token(token):
	"""Return (serial, manual). A scanned QR is `<serial>.<hmac>`; a bare serial means typed by hand."""
	token = (token or '').strip()
	if '.' in token:
		return Ticket.verify_payload(token), False
	return (token.upper() or None), True


def stats(sailing):
	qs = Ticket.objects.filter(sailing=sailing, status__in=[Ticket.Status.ISSUED, Ticket.Status.BOARDED])
	return {'boarded': qs.filter(status=Ticket.Status.BOARDED).count(), 'total': qs.count()}


def _payload(result, ticket=None, sailing=None, extra=None):
	d = {'result': result}
	if ticket is not None:
		d.update(serial=ticket.serial, name=ticket.full_name, item=ticket.item.display_name(), qty=ticket.quantity,
			route=str(ticket.sailing.route), sailing_id=ticket.sailing_id,
			departure=timezone.localtime(ticket.sailing.departure).strftime('%d/%m %H:%M'))
		if ticket.boarded_at:
			d['boarded_at'] = timezone.localtime(ticket.boarded_at).strftime('%d/%m %H:%M')
			d['boarded_by'] = str(ticket.boarded_by) if ticket.boarded_by_id else ''
	if extra:
		d.update(extra)
	if sailing is not None:
		d['stats'] = stats(sailing)
	return d


def process_scan(user, sailing, token, scanned_at=None, offline=False):
	"""Validate one token against `sailing`, board the ticket if allowed, and log the attempt."""
	now = timezone.now()
	scanned_at = min(scanned_at or now, now)  # a phone clock in the future cannot back-date into tomorrow
	serial, manual = parse_token(token)
	ticket, result = None, R.INVALID
	if serial:
		ticket = Ticket.objects.select_related('sailing__route', 'item', 'boarded_by').filter(serial=serial).first()
		result = R.NOT_FOUND if ticket is None else None
	if ticket is not None:
		result = _decide(ticket, sailing, user, scanned_at)
		ticket.refresh_from_db()
	ScanEvent.objects.create(user=user, sailing=sailing, ticket=ticket, serial=(serial or '')[:40], result=result,
		manual=manual, offline=offline, scanned_at=scanned_at)
	return _payload(result, ticket, sailing)


def _decide(ticket, sailing, user, scanned_at):
	if ticket.status in (Ticket.Status.CANCELLED, Ticket.Status.REFUNDED):
		return R.CANCELLED
	if ticket.sailing_id != sailing.pk:
		return R.WRONG_SAILING
	if sailing.status == Sailing.Status.CANCELLED:
		return R.SAILING_CANCELLED
	with transaction.atomic():
		# Conditional update: of two simultaneous scans only one can flip ISSUED -> BOARDED.
		n = Ticket.objects.filter(pk=ticket.pk, status__in=BOARDABLE).update(
			status=Ticket.Status.BOARDED, boarded_at=scanned_at, boarded_by=user)
	return R.OK if n else R.DUPLICATE
