from django.contrib import admin
from django.urls import include, path

handler403 = "main.views.error_403"
handler404 = "main.views.error_404"
handler500 = "main.views.error_500"

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),
    path("", include("users.urls")),
    path("custom/", include("custom.urls")),
    path("ticketing/", include("ticketing.urls")),
    path("report/", include("report.urls")),
    path("api/report/", include("report.api.urls")),
    path("", include("main.urls")),
]
