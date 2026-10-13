from django.db import models


class ReportLog(models.Model):
    """One row per periodic report e-mail, so a re-run (cron retry) never sends the same report twice."""

    DAILY, MONTHLY, YEARLY = "daily", "monthly", "yearly"
    PERIODS = [(DAILY, "daily"), (MONTHLY, "monthly"), (YEARLY, "yearly")]

    period = models.CharField(max_length=10, choices=PERIODS)
    key = models.CharField(max_length=10)  # 2026-10-13 | 2026-10 | 2026
    recipients = models.TextField(blank=True)
    ok = models.BooleanField(default=False)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["period", "key", "ok"])]

    def __str__(self):
        return f"{self.period} {self.key} {'ok' if self.ok else 'FAILED'}"
