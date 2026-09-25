from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from backstage.views import ProductionView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("home.urls")),
    *ProductionView.get_urls(),
]

if settings.DEBUG:
    # Include django_browser_reload URLs only in DEBUG mode
    urlpatterns += [
        path("__reload__/", include("django_browser_reload.urls")),
    ]
