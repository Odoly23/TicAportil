"""Sales and boarding figures. Every page, chart, export and e-mail goes through here so numbers always agree.

Money rules (USD):
  gross   = tickets created in the period that were not voided (status cancelled = issued by mistake)
  refunds = tickets refunded (health reasons) whose refund happened in the period
  net     = gross - refunds
Days are Asia/Dili calendar days, not UTC.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import Coalesce
from django.db.models.functions import TruncDate
from django.utils import timezone

from custom.models import FareItem, Operator, Route, Vessel
from ticketing.models import ScanEvent, Sailing, Ticket
from ticketing.services import scoped_sailings
from users.models import User

ZERO = Decimal('0.00')
T = Ticket.Status
AMOUNT = ExpressionWrapper(F('unit_price') * F('quantity'), output_field=DecimalField(max_digits=12, decimal_places=2))
LIST_AMOUNT = ExpressionWrapper(Coalesce(F('list_price'), F('unit_price')) * F('quantity'), output_field=DecimalField(max_digits=12, decimal_places=2))
PAX = Sum('quantity', filter=Q(item__quota_group='passenger'))


def aware(d, end=False):
	"""Start of local day `d`, or start of the following day when end=True (an exclusive upper bound)."""
	return timezone.make_aware(datetime.combine(d + timedelta(days=1) if end else d, time.min))


def period_bounds(period, key_date):
	"""(first_day, last_day) of the day / month / year containing key_date."""
	if period == 'daily':
		return key_date, key_date
	if period == 'monthly':
		first = key_date.replace(day=1)
		nxt = (first + timedelta(days=32)).replace(day=1)
		return first, nxt - timedelta(days=1)
	return key_date.replace(month=1, day=1), key_date.replace(month=12, day=31)


class Filters:
	"""Date range plus optional route / vessel / operator, applied on top of the user's own scope."""

	def __init__(self, user, start, end, route=None, vessel=None, operator=None):
		self.user, self.start, self.end = user, start, end
		self.route, self.vessel, self.operator = route, vessel, operator

	def _scope(self, qs):
		qs = qs.filter(sailing__in=scoped_sailings(self.user)) if self.user is not None else qs
		if self.route:
			qs = qs.filter(sailing__route_id=self.route)
		if self.vessel:
			qs = qs.filter(sailing__vessel_id=self.vessel)
		if self.operator:
			qs = qs.filter(sailing__vessel__operator_id=self.operator)
		return qs

	@property
	def sold(self):
		"""Tickets created in the range, voids excluded."""
		return self._scope(Ticket.objects.filter(created_at__gte=aware(self.start), created_at__lt=aware(self.end, True))
			.exclude(status=T.CANCELLED))

	@property
	def voided(self):
		return self._scope(Ticket.objects.filter(created_at__gte=aware(self.start), created_at__lt=aware(self.end, True),
			status=T.CANCELLED))

	@property
	def refunds(self):
		return self._scope(Ticket.objects.filter(status=T.REFUNDED, cancelled_at__gte=aware(self.start),
			cancelled_at__lt=aware(self.end, True)))


def _sum(qs):
	r = qs.aggregate(amt=Sum(AMOUNT), n=Count('id'), pax=PAX)
	return {'amount': r['amt'] or ZERO, 'tickets': r['n'], 'pax': r['pax'] or 0}


def summary(f):
	g, r, v = _sum(f.sold), _sum(f.refunds), _sum(f.voided)
	b = f.sold.filter(payment_method=Ticket.Payment.COMPLIMENTARY).aggregate(n=Count('id'), pax=PAX, value=Sum(LIST_AMOUNT))
	return {'bonus_tickets': b['n'], 'bonus_pax': b['pax'] or 0, 'bonus_value': b['value'] or ZERO, 'gross': g['amount'], 'tickets': g['tickets'], 'pax': g['pax'], 'refunds': r['amount'], 'refund_tickets': r['tickets'],
		'voided': v['amount'], 'void_tickets': v['tickets'], 'net': g['amount'] - r['amount']}


def breakdown(f, field, labels, annotate=None, order=None):
	"""Rows per `field` value: tickets, passengers, gross, refunds, net. `labels` maps key -> display text."""
	sold, ref = f.sold, f.refunds
	if annotate:
		sold, ref = annotate(sold, 'created_at'), annotate(ref, 'cancelled_at')
	s = {r[field]: r for r in sold.values(field).annotate(amt=Sum(AMOUNT), n=Count('id'), pax=PAX)}
	rf = {r[field]: r for r in ref.values(field).annotate(amt=Sum(AMOUNT), n=Count('id'))}
	rows = []
	for key in set(s) | set(rf):
		g = (s.get(key) or {}).get('amt') or ZERO
		r = (rf.get(key) or {}).get('amt') or ZERO
		rows.append({'key': key, 'label': labels(key), 'tickets': (s.get(key) or {}).get('n', 0),
			'pax': (s.get(key) or {}).get('pax') or 0, 'gross': g, 'refunds': r, 'net': g - r})
	return sorted(rows, key=order or (lambda x: -x['net']))


def by_route(f):
	names = {r.pk: str(r) for r in Route.objects.select_related('origin', 'destination')}
	return breakdown(f, 'sailing__route', lambda k: names.get(k, '?'))


def by_vessel(f):
	names = {v.pk: f'{v.name} ({v.operator.name})' for v in Vessel.objects.select_related('operator')}
	return breakdown(f, 'sailing__vessel', lambda k: names.get(k, '?'))


def by_operator(f):
	names = dict(Operator.objects.values_list('pk', 'name'))
	return breakdown(f, 'sailing__vessel__operator', lambda k: names.get(k, '?'))


def by_item(f):
	items = {i.pk: i for i in FareItem.objects.all()}
	return breakdown(f, 'item', lambda k: items[k].display_name() if k in items else '?')


def by_payment(f):
	names = dict(Ticket.Payment.choices)
	return breakdown(f, 'payment_method', lambda k: str(names.get(k, k)))


def by_cashier(f):
	names = {u.pk: u.get_full_name() or u.username for u in User.objects.all()}
	return breakdown(f, 'sold_by', lambda k: names.get(k, '—'))


def by_day(f):
	ann = lambda qs, col: qs.annotate(day=TruncDate(col))
	rows = breakdown(f, 'day', lambda k: k, annotate=ann, order=lambda x: x['key'])
	return rows


def daily_series(f):
	"""Every day of the range (zeros included) so charts have no gaps."""
	have = {r['key']: r for r in by_day(f)}
	out, d = [], f.start
	while d <= f.end:
		r = have.get(d)
		out.append({'day': d, 'net': r['net'] if r else ZERO, 'tickets': r['tickets'] if r else 0})
		d += timedelta(days=1)
	return out


# ----------------------------------------------------------------------------------- cashier shift
def cashier_day(user, day, cashier=None):
	"""Cash drawer view for one calendar day. `cashier` limits it to one user (a clerk sees only themself)."""
	f = Filters(user=None, start=day, end=day)
	sold, ref = f.sold, f.refunds
	if cashier is not None:
		sold, ref = sold.filter(sold_by=cashier), ref.filter(sold_by=cashier)
	rows = []
	for uid in sorted(set(sold.values_list('sold_by', flat=True)) | set(ref.values_list('sold_by', flat=True)), key=lambda x: x or 0):
		s, r = sold.filter(sold_by=uid), ref.filter(sold_by=uid)
		cash = _sum(s.filter(payment_method=Ticket.Payment.CASH))['amount']
		transfer = _sum(s.filter(payment_method=Ticket.Payment.TRANSFER))['amount']
		cash_ref = _sum(r.filter(payment_method=Ticket.Payment.CASH))['amount']
		rows.append({'user': User.objects.filter(pk=uid).first(), 'tickets': s.count(), 'cash': cash, 'transfer': transfer,
			'refunds': _sum(r)['amount'], 'drawer': cash - cash_ref, 'lines': list(s.select_related('item', 'sailing__route').order_by('created_at'))})
	return rows


# ------------------------------------------------------------------------------------- boarding
def boarding(user, start, end):
	"""Per sailing departing in the range: sold vs boarded, no-shows (only once the sailing has left), scan problems."""
	sailings = scoped_sailings(user, Sailing.objects.filter(departure__gte=aware(start), departure__lt=aware(end, True))
		.select_related('vessel__operator', 'route__origin', 'route__destination')).order_by('departure')
	rows = []
	for s in sailings:
		valid = s.tickets.filter(status__in=[T.ISSUED, T.BOARDED])
		boarded = valid.filter(status=T.BOARDED).count()
		total = valid.count()
		left = s.status in (Sailing.Status.DEPARTED, Sailing.Status.COMPLETED)
		ev = {r['result']: r['n'] for r in s.scans.values('result').annotate(n=Count('id'))}
		rows.append({'sailing': s, 'tickets': total, 'boarded': boarded, 'no_show': (total - boarded) if left else None,
			'duplicates': ev.get('duplicate', 0), 'invalid': ev.get('invalid', 0) + ev.get('not_found', 0), 'wrong': ev.get('wrong_sailing', 0)})
	return rows
