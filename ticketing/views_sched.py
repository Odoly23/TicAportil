from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from config.decorators import perm_required
from custom.models import QuotaGroup
from users.models import AuditLog

from .forms_sched import AnnouncementForm, CancelForm, DelayForm, MoveForm, SailingForm, TicketCancelForm
from .models import Announcement, Notification, Sailing, Ticket
from .services import ShortQuota, is_global, iso, move_tickets, notify_change, scoped_sailings

MANAGE = 'ticketing.manage_schedule'
OPEN = (Sailing.Status.SCHEDULED, Sailing.Status.DELAYED)


def _group(request):
	return request.user.groups.all()[0].name if request.user.groups.exists() else 'admin'


def _sailing(request, pk):
	return get_object_or_404(scoped_sailings(request.user).select_related('vessel__operator', 'route__origin', 'route__destination'), pk=pk)


def _short_msg(short):
	labels = dict(QuotaGroup.choices)
	return ', '.join(f'{labels[g]}: -{n}' for g, n in short.items())


@login_required
@perm_required(MANAGE)
def SailingList(request):
	qs = scoped_sailings(request.user).select_related('vessel__operator', 'route__origin', 'route__destination').prefetch_related('quotas')
	show_all = request.GET.get('all') == '1'
	if not show_all:
		qs = qs.filter(departure__gte=timezone.now() - timedelta(days=1))
	rows = []
	for s in qs:
		qs_ = {q.quota_group: q for q in s.quotas.all()}
		rows.append({'obj': s, 'q': [(label, qs_.get(code)) for code, label in QuotaGroup.choices]})
	context = {'group': _group(request), 'rows': rows, 'show_all': show_all, 'title': 'Jadwal', 'legend': 'Jadwal Viajen'}
	return render(request, 'ticketing/sailing_list.html', context)


def _form_page(request, form, title, legend, back=None, submit=None, extra=None):
	ctx = {'group': _group(request), 'form': form, 'title': title, 'legend': legend, 'back': back, 'submit': submit}
	ctx.update(extra or {})
	return render(request, 'ticketing/action_form.html', ctx)


@login_required
@perm_required(MANAGE)
def SailingAdd(request):
	form = SailingForm(request.POST or None, user=request.user)
	if request.method == 'POST' and form.is_valid():
		s = form.save(commit=False)
		s.created_by = request.user
		with transaction.atomic():
			s.save()
			form.save_quotas(s)
		AuditLog.record('sailing_created', user=request.user, request=request, detail=str(s))
		messages.success(request, _("Viajen rai ona."))
		return redirect('sailing-detail', s.pk)
	return _form_page(request, form, 'Jadwal', 'Aumenta Viajen', back='sailing-list')


@login_required
@perm_required(MANAGE)
def SailingEdit(request, pk):
	s = _sailing(request, pk)
	if s.status not in OPEN:
		messages.warning(request, _("Viajen ne'e la bele edita ona."))
		return redirect('sailing-detail', s.pk)
	form = SailingForm(request.POST or None, instance=s, user=request.user)
	if request.method == 'POST' and form.is_valid():
		form.save()
		AuditLog.record('sailing_edited', user=request.user, request=request, detail=str(s))
		messages.success(request, _("Viajen atualiza ona."))
		return redirect('sailing-detail', s.pk)
	return _form_page(request, form, 'Jadwal', f'Edita Viajen · {s}', back='sailing-detail', extra={'back_pk': s.pk})


@login_required
@perm_required(MANAGE)
def SailingDetail(request, pk):
	s = _sailing(request, pk)
	quotas = {q.quota_group: q for q in s.quotas.all()}
	by_status = {r['status']: r['n'] for r in s.tickets.values('status').annotate(n=Count('id'))}
	revenue = sum(t.total for t in s.tickets.filter(status__in=[Ticket.Status.ISSUED, Ticket.Status.BOARDED]))
	valid_left = s.tickets.filter(status=Ticket.Status.ISSUED).count()
	context = {
		'group': _group(request), 'obj': s, 'title': 'Jadwal', 'legend': f'{s.route} · {s.vessel}',
		'quotas': [(label, quotas.get(code)) for code, label in QuotaGroup.choices],
		'by_status': by_status, 'revenue': revenue, 'valid_left': valid_left,
		'is_open': s.status in OPEN, 'can_move': s.status == Sailing.Status.CANCELLED and valid_left > 0,
		'announcements': s.announcements.all()[:5],
	}
	return render(request, 'ticketing/sailing_detail.html', context)


@login_required
@perm_required(MANAGE)
def SailingDelay(request, pk):
	s = _sailing(request, pk)
	if s.status not in OPEN:
		return redirect('sailing-detail', s.pk)
	form = DelayForm(request.POST or None, sailing=s)
	if request.method == 'POST' and form.is_valid():
		with transaction.atomic():
			old = s.departure
			s.original_departure = s.original_departure or old
			s.departure = form.cleaned_data['new_departure']
			s.status = Sailing.Status.DELAYED
			s.note = form.cleaned_data['reason']
			s.save()
			AuditLog.record('sailing_delayed', user=request.user, request=request, detail=f'{s.pk} {old:%d/%m %H:%M}->{s.departure:%d/%m %H:%M}')
		data = {'route': str(s.route), 'vessel': str(s.vessel), 'old': iso(old), 'new': iso(s.departure), 'note': s.note}
		n = notify_change(s, 'delayed', data, actor=request.user)
		messages.success(request, _("Viajen atrazadu ona. Email haruka: %(n)d.") % {'n': n})
		return redirect('sailing-detail', s.pk)
	return _form_page(request, form, 'Jadwal', f'Atrazu Viajen · {s}', back='sailing-detail', extra={'back_pk': s.pk},
		submit=_("Atrazu no haruka notifikasaun"))


@login_required
@perm_required(MANAGE)
def SailingCancel(request, pk):
	s = _sailing(request, pk)
	if s.status not in OPEN:
		return redirect('sailing-detail', s.pk)
	form = CancelForm(request.POST or None, sailing=s, user=request.user)
	if request.method == 'POST' and form.is_valid():
		dst = form.cleaned_data['move_to']
		tickets = list(Ticket.objects.filter(sailing=s, status=Ticket.Status.ISSUED))
		try:
			with transaction.atomic():
				s.status = Sailing.Status.CANCELLED
				s.note = form.cleaned_data['reason']
				s.save()
				if dst:
					move_tickets(s, dst, user=request.user, request=request)
				AuditLog.record('sailing_cancelled', user=request.user, request=request, detail=f'{s.pk} moved_to={dst.pk if dst else None}')
		except ShortQuota as e:
			form.add_error('move_to', _("Kuota la to'o iha viajen foun: %(s)s") % {'s': _short_msg(e.short)})
		else:
			data = {'route': str(s.route), 'vessel': str(s.vessel), 'old': iso(s.departure), 'note': s.note}
			if dst:
				data['new'] = iso(dst.departure)
			n = notify_change(s, 'cancelled_moved' if dst else 'cancelled', data, actor=request.user, tickets=tickets)
			messages.success(request, _("Viajen kansela ona. Email haruka: %(n)d.") % {'n': n})
			return redirect('sailing-detail', s.pk)
	return _form_page(request, form, 'Jadwal', f'Kansela Viajen · {s}', back='sailing-detail', extra={'back_pk': s.pk},
		submit=_("Kansela viajen"))


@login_required
@perm_required(MANAGE)
def SailingMove(request, pk):
	s = _sailing(request, pk)
	if s.status != Sailing.Status.CANCELLED:
		return redirect('sailing-detail', s.pk)
	form = MoveForm(request.POST or None, sailing=s, user=request.user)
	if request.method == 'POST' and form.is_valid():
		dst = form.cleaned_data['move_to']
		try:
			tickets = move_tickets(s, dst, user=request.user, request=request)
		except ShortQuota as e:
			form.add_error('move_to', _("Kuota la to'o iha viajen foun: %(s)s") % {'s': _short_msg(e.short)})
		else:
			data = {'route': str(s.route), 'vessel': str(s.vessel), 'old': iso(s.departure), 'new': iso(dst.departure)}
			n = notify_change(s, 'tickets_moved', data, actor=request.user, tickets=tickets, announce=False)
			messages.success(request, _("Bilhete %(t)d muda ona. Email haruka: %(n)d.") % {'t': len(tickets), 'n': n})
			return redirect('sailing-detail', s.pk)
	return _form_page(request, form, 'Jadwal', f'Muda Bilhete · {s}', back='sailing-detail', extra={'back_pk': s.pk}, submit=_("Muda bilhete"))


@login_required
@perm_required(MANAGE)
def SailingStatus(request, pk, action):
	s = _sailing(request, pk)
	if request.method != 'POST':
		return redirect('sailing-detail', s.pk)
	if action == 'depart' and s.status in OPEN:
		s.status = Sailing.Status.DEPARTED
	elif action == 'complete' and s.status == Sailing.Status.DEPARTED:
		s.status = Sailing.Status.COMPLETED
	else:
		messages.warning(request, _("Asaun la bele."))
		return redirect('sailing-detail', s.pk)
	s.save(update_fields=['status'])
	AuditLog.record(f'sailing_{action}', user=request.user, request=request, detail=str(s.pk))
	return redirect('sailing-detail', s.pk)


# ----------------------------------------------------------------------------------- announcements
@login_required
@perm_required(MANAGE)
def AnnouncementList(request):
	qs = Announcement.objects.select_related('sailing__vessel', 'sailing__route')
	if not is_global(request.user):
		qs = qs.filter(sailing__in=scoped_sailings(request.user))
	context = {'group': _group(request), 'objects': qs[:200], 'title': 'Anúnsiu', 'legend': 'Anúnsiu'}
	return render(request, 'ticketing/announcement_list.html', context)


@login_required
@perm_required(MANAGE)
def AnnouncementAdd(request):
	form = AnnouncementForm(request.POST or None, user=request.user)
	if request.method == 'POST' and form.is_valid():
		a = form.save(commit=False)
		a.created_by = request.user
		a.save()
		n = 0
		if form.cleaned_data['send_email'] and a.sailing:
			from django.core import mail
			subject, body = a.title, a.body
			tickets = Ticket.objects.filter(sailing=a.sailing, status=Ticket.Status.ISSUED).exclude(contact_email='')
			addrs = sorted({t.contact_email.lower() for t in tickets})
			try:
				conn = mail.get_connection()
				n = conn.send_messages([mail.EmailMessage(subject, body, to=[x], connection=conn) for x in addrs])
			except Exception as e:
				AuditLog.record('email_failed', user=request.user, request=request, detail=f'announcement {a.pk}: {e}'[:500])
		AuditLog.record('announcement_created', user=request.user, request=request, detail=a.title)
		messages.success(request, _("Anúnsiu rai ona. Email haruka: %(n)d.") % {'n': n})
		return redirect('announcement-list')
	return _form_page(request, form, 'Anúnsiu', 'Aumenta Anúnsiu', back='announcement-list')


@login_required
@perm_required(MANAGE)
def AnnouncementDelete(request, pk):
	a = get_object_or_404(Announcement, pk=pk)
	if not is_global(request.user) and (not a.sailing_id or not scoped_sailings(request.user).filter(pk=a.sailing_id).exists()):
		return render(request, 'home/403.html', status=403)
	if request.method == 'POST':
		AuditLog.record('announcement_deleted', user=request.user, request=request, detail=a.title or a.kind)
		a.delete()
	return redirect('announcement-list')


# ---------------------------------------------------------------------------------- notifications
@login_required
@perm_required(MANAGE)
def NotificationList(request):
	items = list(Notification.objects.filter(user=request.user).select_related('sailing')[:100])
	context = {'group': _group(request), 'objects': items, 'title': 'Notifikasaun', 'legend': 'Notifikasaun'}
	response = render(request, 'ticketing/notifications.html', context)
	Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
	return response


# ------------------------------------------------------------------------------------ ticket cancel
@login_required
def TicketCancel(request, pk):
	if not (request.user.has_perm('ticketing.cancel_ticket') or request.user.has_perm('ticketing.refund_ticket')):
		return render(request, 'home/403.html', status=403)
	t = get_object_or_404(Ticket.objects.select_related('sailing__route', 'item'), pk=pk)
	can_refund = request.user.has_perm('ticketing.refund_ticket')
	eligible = t.status == Ticket.Status.ISSUED and t.sailing.status in OPEN
	if not eligible:
		messages.warning(request, _("Bilhete ne'e la bele kansela ona."))
		return redirect('ticket-detail', t.pk)
	form = TicketCancelForm(request.POST or None, user=request.user, ticket=t)
	if request.method == 'POST' and form.is_valid():
		refund = form.cleaned_data['kind'] == 'refund' and can_refund
		t.status = Ticket.Status.REFUNDED if refund else Ticket.Status.CANCELLED
		t.cancelled_at = timezone.now()
		t.cancel_reason = form.cleaned_data['reason']
		t.cancelled_by = request.user
		t.save(update_fields=['status', 'cancelled_at', 'cancel_reason', 'cancelled_by'])
		AuditLog.record('ticket_refund' if refund else 'ticket_void', user=request.user, request=request,
			detail=f'{t.serial} ${t.total} {t.cancel_reason}')
		messages.success(request, _("Bilhete kansela ona.") + (_(" Fila fali osan: $%(a)s.") % {'a': t.total} if refund else ''))
		return redirect('ticket-detail', t.pk)
	return _form_page(request, form, 'Bilhete', f'Kansela Bilhete {t.serial}', back='ticket-detail', extra={'back_pk': t.pk, 'ticket': t},
		submit=_("Konfirma kansela"))
