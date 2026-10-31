"""The sitemap (/sitemap.xml): every public page, so search engines find them all."""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from backstage.models import Event, Production

from .auditions import upcoming_auditions
from .models import WebPage
from .views import public_actors, public_team_members


class StaticSitemap(Sitemap):
    """The pages that are always there."""

    priority = 0.8

    def items(self):
        return ["home", "auditions", "radio-archive", "public-actors"]

    def location(self, name):
        return reverse(name)


class WebPageSitemap(Sitemap):
    """The pages built in the page editor. The home page is the site's root, and a copy still being worked on is left out."""

    def items(self):
        return WebPage.objects.exclude(slug="home").filter(copied_from__isnull=True).order_by("slug")


class ProductionSitemap(Sitemap):
    """Stage plays, films and the rest have their page; radio plays have theirs in the radio archive."""

    def items(self):
        return list(Production.objects.order_by("pk"))

    def location(self, production):
        if production.type == Production.ProductionType.RADIO:
            return reverse("radio-play", args=[production.pk])
        return reverse("public-production", args=[production.pk])


class EventSitemap(Sitemap):
    """Published events only, as on the site."""

    def items(self):
        return Event.objects.published().order_by("pk")

    def location(self, event):
        return reverse("public-event", args=[event.pk])


class PerformerSitemap(Sitemap):
    """The actors, and the team members, who have a public page."""

    def items(self):
        return [("public-actor", p.pk) for p in public_actors().order_by("pk")] + [
            ("public-team-member", p.pk) for p in public_team_members().order_by("pk")
        ]

    def location(self, item):
        return reverse(item[0], args=[item[1]])


class AuditionSitemap(Sitemap):
    """Productions with an audition still to come."""

    def items(self):
        return list(upcoming_auditions())

    def location(self, production):
        return reverse("audition-detail", args=[production.pk])


SITEMAPS = {
    "pages": StaticSitemap,
    "webpages": WebPageSitemap,
    "productions": ProductionSitemap,
    "events": EventSitemap,
    "people": PerformerSitemap,
    "auditions": AuditionSitemap,
}
