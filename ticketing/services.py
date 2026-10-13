"""Schedule logic: scoping, moving tickets between sailings, and notifying people."""
from django.core import mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from users.models import AuditLog, User

from .messages import render_all
from .models import Announcement, Notification, Sailing, SailingQuota, Ticket

VALID = (Ticket.Status.ISSUED,)


def is_global(user):
	"""Admins see every operator; operator users are limited to their own operator."""
	return user.is_superuser or user.groups.filter(name='admin').exists()


def scoped_sailings(user, qs=None):
	qs = Sailing.objects.all() if qs is None else qs
	if is_global(user):
		return qs
	if user.operator_id:
		return qs.filter(vessel__operator_id=user.operator_id)
	return qs.none()


def iso(dt):
	return dt.isoformat() if dt else None


def sailing_data(s, **extra):
	data = {'route': str(s.route), 'vessel': str(s.vessel), 'old': iso(s.departure), 'note': s.note}
	data.update(extra)
	return data


def move_tickets(src, dst, user=None, request=None):
	"""Move all valid tickets of `src` to `dst` (same route). All-or-nothing; returns the moved count."""
	if src.route_id != dst.route_id:
		raise ValueError('route')
	with transaction.atomic():
		tickets = list(Ticket.objects.select_for_update().filter(sailing=src, status__in=VALID).select_related('item'))
		need = {}
		for t in tickets:
			need[t.item.quota_group] = need.get(t.item.quota_group, 0) + t.quantity
		short = {}
		for group, qty in need.items():
			q = SailingQuota.objects.select_for_update().filter(sailing=dst, quota_group=group).first()
			remaining = q.remaining if q else 0
			if remaining < qty:
				short[group] = qty - remaining
		if short:
			raise ShortQuota(short)
		Ticket.objects.filter(pk__in=[t.pk for t in tickets]).update(sailing=dst)
		src.replaced_by = dst
		src.save(update_fields=['replaced_by'])
		AuditLog.record('tickets_moved', user=user, request=request, detail=f'{src.pk}->{dst.pk} n={len(tickets)}')
	return tickets


class ShortQuota(Exception):
	def __init__(self, short):
		self.short = short
		super().__init__(short)


def staff_to_notify(sailing, exclude=None):
	q = Q(is_superuser=True) | Q(groups__name='admin') | Q(operator_id=sailing.vessel.operator_id, groups__name='operator')
	users = User.objects.filter(is_active=True).filter(q).distinct()
	return users.exclude(pk=exclude.pk) if exclude else users


def notify_change(sailing, kind, data, actor=None, tickets=None, announce=True, email=True):
	"""System (announcement + staff notifications) and email. WhatsApp will plug in here later."""
	if announce:
		Announcement.objects.create(kind=kind, data=data, sailing=sailing, is_public=True, created_by=actor)
	Notification.objects.bulk_create([
		Notification(user=u, kind=kind, data=data, sailing=sailing) for u in staff_to_notify(sailing, exclude=actor)])
	if email:
		return send_emails(sailing, kind, data, tickets)
	return 0


def send_emails(sailing, kind, data, tickets=None):
	tickets = list(tickets) if tickets is not None else list(Ticket.objects.filter(sailing=sailing, status__in=VALID))
	addrs = {t.contact_email.strip().lower() for t in tickets if t.contact_email}
	op_email = sailing.vessel.operator.email
	if op_email:
		addrs.add(op_email.strip().lower())
	if not addrs:
		return 0
	subject, body = render_all(kind, data)
	try:
		conn = mail.get_connection()
		msgs = [mail.EmailMessage(subject, body, to=[a], connection=conn) for a in sorted(addrs)]
		return conn.send_messages(msgs)
	except Exception as e:  # never block a schedule change because SMTP is down
		AuditLog.record('email_failed', detail=f'sailing={sailing.pk} {type(e).__name__}: {e}'[:500])
		return 0
