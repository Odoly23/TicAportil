from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from custom.models import Fare, FareItem, Operator, Port, Route, Vessel
from ticketing.models import Sailing, SailingQuota


class Command(BaseCommand):
	help = "Load DEMO master data and sailings for development. Prices are placeholders, NOT real tariffs."

	def add_arguments(self, parser):
		parser.add_argument('--force', action='store_true', help='Allow running when DEBUG is off')

	def handle(self, *args, **opts):
		if not settings.DEBUG and not opts['force']:
			raise CommandError('Refusing to load demo data with DEBUG off (use --force).')
		dili, beloi, mahata = (Port.objects.get_or_create(code=c, defaults={'name': n})[0]
			for c, n in (('DIL', 'Dili'), ('BEL', 'Beloi (Ataúro)'), ('MAH', 'Mahata (Oecusse)')))
		r1 = Route.objects.get_or_create(origin=dili, destination=beloi)[0]
		r2 = Route.objects.get_or_create(origin=dili, destination=mahata)[0]
		op = Operator.objects.get_or_create(name='DEMO Operator')[0]
		vessels = [Vessel.objects.get_or_create(operator=op, name=n)[0] for n in ('Berlin Nakroma', 'Berlin Ramelau')]
		# name_tet, (pt, en, id), group, age_min, age_max, foreigner_only, plate, sort, PLACEHOLDER price
		items = [
			('Labarik', ('Criança', 'Child', 'Anak-anak'), 'passenger', 0, 11, False, False, 1, '2.00'),
			('Adultu', ('Adulto', 'Adult', 'Dewasa'), 'passenger', 12, 59, False, False, 2, '4.00'),
			('Idozu', ('Idoso', 'Senior', 'Lansia'), 'passenger', 60, None, False, False, 3, '2.00'),
			('Motór', ('Mota', 'Motorbike', 'Sepeda motor'), 'vehicle', None, None, False, True, 1, '8.00'),
			('Kareta', ('Carro', 'Car', 'Mobil'), 'vehicle', None, None, False, True, 2, '40.00'),
			('Karau', ('Búfalo', 'Buffalo', 'Kerbau'), 'goods', None, None, False, False, 1, '10.00'),
			('Fahi', ('Porco', 'Pig', 'Babi'), 'goods', None, None, False, False, 2, '5.00'),
			('Aluga ró', ('Aluguer do barco', 'Vessel charter', 'Sewa kapal'), 'charter', None, None, False, False, 1, '500.00'),
		]
		for n, (pt, e, idn), g, amin, amax, fo, pl, so, price in items:
			it = FareItem.objects.get_or_create(name_tet=n, defaults=dict(
				name_pt=pt, name_en=e, name_id=idn, quota_group=g, age_min=amin, age_max=amax, foreigner_only=fo, requires_plate=pl, sort_order=so))[0]
			for r in (r1, r2):
				Fare.objects.get_or_create(route=r, item=it, defaults={'price': Decimal(price)})
		base = timezone.now().replace(minute=0, second=0, microsecond=0)
		for i, (v, r) in enumerate([(vessels[0], r1), (vessels[1], r2)]):
			s, created = Sailing.objects.get_or_create(vessel=v, route=r, departure=base + timedelta(days=1, hours=i))
			if created:
				for g, cap in (('passenger', 200), ('vehicle', 5), ('goods', 50), ('charter', 1)):
					SailingQuota.objects.create(sailing=s, quota_group=g, capacity=cap)
		self.stdout.write(self.style.SUCCESS('Demo data loaded (placeholder prices!).'))
