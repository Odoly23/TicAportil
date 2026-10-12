from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from ticketing.models import Ticket


class Command(BaseCommand):
    help = "Delete passenger document photos older than DOCUMENT_RETENTION_DAYS (run daily via cron)."

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=settings.DOCUMENT_RETENTION_DAYS)
        n = 0
        for t in Ticket.objects.filter(created_at__lt=cutoff, document_deleted_at__isnull=True).exclude(document_photo=""):
            t.document_photo.delete(save=False)
            t.document_photo = ""
            t.document_deleted_at = timezone.now()
            t.save(update_fields=["document_photo", "document_deleted_at"])
            n += 1
        self.stdout.write(f"Purged {n} document photos")
