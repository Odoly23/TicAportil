from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

# Group name -> permission codenames. Admins can still grant/revoke individual permissions per user.
ROLES = {
	"admin": "__all__",
	"resepsionista": ["issue_ticket", "view_sailing", "view_ticket", "view_fare", "view_fareitem"],
	"inspector": ["scan_ticket", "view_sailing", "view_ticket"],
	"operator": ["manage_schedule", "view_sailing", "view_reports", "view_vessel"],
}


class Command(BaseCommand):
	help = "Create the default role groups (idempotent)."

	def handle(self, *args, **opts):
		for name, codes in ROLES.items():
			group, _ = Group.objects.get_or_create(name=name)
			perms = Permission.objects.all() if codes == "__all__" else Permission.objects.filter(codename__in=codes)
			group.permissions.set(perms)
			if opts["verbosity"] > 0:
				self.stdout.write(f"{name}: {group.permissions.count()} permissions")
