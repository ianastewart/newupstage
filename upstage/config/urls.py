from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.contrib.sitemaps.views import sitemap
from django.templatetags.static import static as static_url
from django.urls import URLPattern, include, path, re_path
from django.utils.cache import patch_cache_control
from django.views.generic import RedirectView
from django.views.static import serve
from django.conf import settings
from django.conf.urls.static import static

from home.sitemaps import SITEMAPS
from home.views import robots_txt

def media_file(request, path):
    """An uploaded file, told how long it may be kept (the file's own date lets a browser ask "has it changed?")."""
    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    if response.status_code in (200, 304):
        if settings.SITE_MODE == "sandbox":
            patch_cache_control(response, private=True, max_age=min(settings.MEDIA_CACHE_SECONDS, 3600))
        else:
            patch_cache_control(response, public=True, max_age=settings.MEDIA_CACHE_SECONDS)
    return response


urlpatterns = [
    path("admin/", admin.site.urls),
    path("sitemap.xml", login_not_required(sitemap), {"sitemaps": SITEMAPS}, name="sitemap"),
    path("robots.txt", robots_txt, name="robots"),
    # Browsers ask for /favicon.ico whatever the page says; send them to the real file.
    path("favicon.ico", login_not_required(RedirectView.as_view(url=static_url("favicon/favicon.ico"))), name="favicon"),
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
else:
    # No web server in front serving the uploads: the app does (they appear on public pages, so no login).
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$", login_not_required(media_file), name="media"
        )
    ]


def _public(patterns):
    """Exempt development-only URL patterns from the login requirement (images appear on public pages)."""
    for pattern in patterns:
        if isinstance(pattern, URLPattern):
            pattern.callback = login_not_required(pattern.callback)
        else:
            _public(pattern.url_patterns)


if settings.DEBUG:
    _public(urlpatterns[-2:])
