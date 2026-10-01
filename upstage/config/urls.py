from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.urls import URLPattern, include, path
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
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


def _public(patterns):
    """Exempt development-only URL patterns from the login requirement (images appear on public pages)."""
    for pattern in patterns:
        if isinstance(pattern, URLPattern):
            pattern.callback = login_not_required(pattern.callback)
        else:
            _public(pattern.url_patterns)


if settings.DEBUG:
    _public(urlpatterns[-2:])
