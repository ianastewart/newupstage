"""The sitemap (/sitemap.xml): every public page, so search engines find them all."""

from django.contrib.sitemaps import Sitemap
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from backstage.models import Event, Production

from .auditions import upcoming_auditions
from .models import WebPage
from .views import public_actors, public_team_members


def is_upcoming(last_date):
    """Whether something whose last date is `last_date` still has a date to come."""
    return bool(last_date) and last_date >= timezone.now()


class StaticSitemap(Sitemap):
    """The pages that are always there."""

    priority = 0.8

    def items(self):
        return [
            "home", "stage-shows", "musicals", "films", "auditions", "radio-archive", "public-actors", "public-writers",
            "public-crew",
        ]

    def location(self, name):
        return reverse(name)


class WebPageSitemap(Sitemap):
    """The pages built in the page editor. The home page is the site's root, and a copy still being worked on is left out."""

    def items(self):
        return WebPage.objects.exclude(slug="home").filter(copied_from__isnull=True, production__isnull=True).order_by("slug")


class ProductionSitemap(Sitemap):
    """Every production has its page."""

    def items(self):
        return list(Production.objects.annotate(last_date=Max("events__datetimes__datetime")).order_by("pk"))

    def location(self, production):
        return reverse("public-production", args=[production.pk])

    def lastmod(self, production):
        """The last date of its events (there is no record of when a production was edited)."""
        return production.last_date

    # Something still to come matters more, and changes more, than a production that is over (or has no dates).
    def priority(self, production):
        return 0.7 if is_upcoming(production.last_date) else 0.5

    def changefreq(self, production):
        return "weekly" if is_upcoming(production.last_date) else "yearly"


class EventSitemap(Sitemap):
    """Published events only, as on the site."""

    def items(self):
        return Event.objects.published().annotate(last_date=Max("datetimes__datetime")).order_by("pk")

    def location(self, event):
        return reverse("public-event", args=[event.pk])

    def lastmod(self, event):
        return event.last_date

    # Past events stay (a broadcast can still be listened to) but matter least.
    def priority(self, event):
        return 0.6 if is_upcoming(event.last_date) else 0.3

    def changefreq(self, event):
        return "weekly" if is_upcoming(event.last_date) else "yearly"


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
