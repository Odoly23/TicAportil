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
		items = [  # name_tet, name_en, group, age_min, age_max, foreigner_only, plate, sort, price
			('Adultu', 'Adult', 'passenger', 12, None, False, False, 1, '4.00'),
			('Kiak', 'Child', 'passenger', 2, 11, False, False, 2, '2.00'),
			('Adultu Estranjeiru', 'Foreign adult', 'passenger', 12, None, True, False, 3, '10.00'),
			('Motór', 'Motorbike', 'vehicle', None, None, False, True, 1, '8.00'),
			('Kareta', 'Car', 'vehicle', None, None, False, True, 2, '40.00'),
			('Karau', 'Buffalo', 'goods', None, None, False, False, 1, '10.00'),
			('Fahi', 'Pig', 'goods', None, None, False, False, 2, '5.00'),
		]
		for n, e, g, amin, amax, fo, pl, so, price in items:
			it = FareItem.objects.get_or_create(name_tet=n, defaults=dict(
				name_en=e, quota_group=g, age_min=amin, age_max=amax, foreigner_only=fo, requires_plate=pl, sort_order=so))[0]
			for r in (r1, r2):
				Fare.objects.get_or_create(route=r, item=it, defaults={'price': Decimal(price)})
		base = timezone.now().replace(minute=0, second=0, microsecond=0)
		for i, (v, r) in enumerate([(vessels[0], r1), (vessels[1], r2)]):
			s, created = Sailing.objects.get_or_create(vessel=v, route=r, departure=base + timedelta(days=1, hours=i))
			if created:
				for g, cap in (('passenger', 200), ('vehicle', 5), ('goods', 50)):
					SailingQuota.objects.create(sailing=s, quota_group=g, capacity=cap)
		self.stdout.write(self.style.SUCCESS('Demo data loaded (placeholder prices!).'))
