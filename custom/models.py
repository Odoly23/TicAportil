from django.db import models
from django.utils.translation import gettext_lazy as _


class Port(models.Model):
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(_("Naran"), max_length=100)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Route(models.Model):
    origin = models.ForeignKey(Port, on_delete=models.PROTECT, related_name="departures")
    destination = models.ForeignKey(Port, on_delete=models.PROTECT, related_name="arrivals")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["origin__name", "destination__name"]
        constraints = [models.UniqueConstraint(fields=["origin", "destination"], name="uniq_route")]

    def __str__(self):
        return f"{self.origin} ➔ {self.destination}"


class Operator(models.Model):
    name = models.CharField(_("Naran"), max_length=150, unique=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Vessel(models.Model):
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT, related_name="vessels")
    name = models.CharField(_("Naran"), max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["operator", "name"], name="uniq_vessel_per_operator")]

    def __str__(self):
        return self.name


class QuotaGroup(models.TextChoices):
    PASSENGER = "passenger", _("Pasajeiru")
    VEHICLE = "vehicle", _("Veíkulu")
    GOODS = "goods", _("Sasán / Animál")
    CHARTER = "charter", _("Aluga ró (charter)")


class FareItem(models.Model):
    """Something that can be sold: a passenger category, a vehicle type, a cargo item or an animal.

    The catalog is managed by APORTIL admins. An item without a Fare on a route is not sold there.
    """

    name_tet = models.CharField("Tetun", max_length=100)
    name_pt = models.CharField("Português", max_length=100, blank=True)
    name_en = models.CharField("English", max_length=100, blank=True)
    name_id = models.CharField("Indonesia", max_length=100, blank=True)
    quota_group = models.CharField(max_length=10, choices=QuotaGroup.choices)
    age_min = models.PositiveSmallIntegerField(null=True, blank=True, help_text=_("Pasajeiru: idade minimu"))
    age_max = models.PositiveSmallIntegerField(null=True, blank=True, help_text=_("Pasajeiru: idade maximu"))
    foreigner_only = models.BooleanField(default=False)
    requires_plate = models.BooleanField(default=False)
    is_block = models.BooleanField(default=False, help_text=_("Aluga parte: blok kursi / veíkulu / sasán ba ema ida"))
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["quota_group", "sort_order", "name_tet"]

    def __str__(self):
        return self.name_tet

    def display_name(self, lang=None):
        from django.utils import translation

        lang = (lang or translation.get_language() or "tet").split("-")[0]
        return getattr(self, f"name_{lang}", "") or self.name_tet


class Fare(models.Model):
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="fares")
    item = models.ForeignKey(FareItem, on_delete=models.CASCADE, related_name="fares")
    price = models.DecimalField(max_digits=8, decimal_places=2)  # USD

    class Meta:
        constraints = [models.UniqueConstraint(fields=["route", "item"], name="uniq_fare")]

    def __str__(self):
        return f"{self.route} / {self.item}: ${self.price}"




def order_items(qs):
    """Passenger categories first, then vehicles, then goods/animals; each by sort_order then name."""
    from django.db.models import Case, IntegerField, Value, When

    rank = Case(When(quota_group=QuotaGroup.PASSENGER, then=Value(0)), When(quota_group=QuotaGroup.VEHICLE, then=Value(1)),
        When(quota_group=QuotaGroup.CHARTER, then=Value(3)), default=Value(2), output_field=IntegerField())
    return qs.order_by(rank, "sort_order", "name_tet")
