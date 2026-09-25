from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("home.urls")),
    path("backstage/", include("backstage.urls")),
]

if settings.DEBUG:
    # Include django_browser_reload URLs only in DEBUG mode
    urlpatterns += [
        path("__reload__/", include("django_browser_reload.urls")),
    ]
    # Serve uploaded images in development
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
