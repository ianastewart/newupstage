import os
import re
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, RegexValidator, URLValidator
from django.db import models, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone
from django.db.models import Case, Exists, F, Min, OuterRef, Q, Value, When
from django_enum import EnumField

from backstage.fields import HeadshotImageField


class Upstage(models.Model):
    name = models.CharField(max_length=255)
    introduction = models.TextField(blank=True)
    logo = models.ImageField(upload_to="upstage/", blank=True)

    def __str__(self):
        return self.name


class SiteSettings(models.Model):
    """Settings for the whole site: there is one row, which `SiteSettings.load()` finds or makes."""

    public_theme = models.CharField(
        max_length=40, blank=True,
        help_text="The theme every visitor sees on the public pages. Blank: Upstage, or Upstage dark if the visitor's device prefers dark.",
    )

    class Meta:
        verbose_name_plural = "site settings"

    def __str__(self):
        return "Site settings"

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]


class Image(models.Model):
    class ImageType(models.TextChoices):
        PRODUCTION = "production", "Production"
        AUDITION = "audition", "Audition"
        PROMOTION = "promotion", "Promotion"
        GALLERY = "gallery", "Gallery"
        HEADSHOT = "headshot", "Headshot"
        LOGO = "logo", "Logo"
        OTHER = "other", "Other"

    # Headshots are made black and white and resized to 400 x 500 when they are uploaded (see backstage/fields.py); other images are kept as they are.
    image = HeadshotImageField(upload_to="images/")
    description = models.CharField(max_length=255, blank=True)
    image_type = EnumField(ImageType, default=ImageType.PRODUCTION)

    def __str__(self):
        return self.description or self.image.name

    @property
    def file_exists(self):
        """Whether the image's file is there (it can go missing, e.g. when the media folder is out of step)."""
        return bool(self.image) and self.image.storage.exists(self.image.name)

    @property
    def dimensions(self):
        """(width, height) in pixels, or None if the file is missing or can't be read."""
        if not self.file_exists:
            return None
        try:
            return self.image.width, self.image.height
        except (OSError, ValueError):
            return None


class Person(models.Model):
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    mobile = models.CharField(max_length=30, blank=True)
    biography = models.TextField(blank=True)
    image = models.ForeignKey(
        Image, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    roles = models.ManyToManyField("Role", blank=True, related_name="people")
    email_consent = models.BooleanField(default=False)
    publish_consent = models.BooleanField(default=False)
    consent_date = models.DateField(null=True, blank=True)
    backstage_interest = models.BooleanField(default=False)
    acting_interest = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "people"
        ordering = ["last_name", "first_name"]

    CONSENT_FLAGS = ("email_consent", "publish_consent")

    @classmethod
    def from_db(cls, db, field_names, values):
        person = super().from_db(db, field_names, values)
        person.remember_consent()
        return person

    def remember_consent(self):
        """Note the consent as it is stored, to see later whether it has been changed."""
        self._stored_consent = (self.email_consent, self.publish_consent, self.consent_date)

    def save(self, *args, **kwargs):
        """
        Saving a change to the email or publish consent dates the consent today (so does a new person who has given
        either). A date set by hand in the same save is kept.
        """
        update_fields = kwargs.get("update_fields")
        stored = getattr(self, "_stored_consent", None)
        flags = (self.email_consent, self.publish_consent)
        if update_fields is not None and not set(self.CONSENT_FLAGS) & set(update_fields):
            changed = False
        elif stored is None:
            changed = any(flags)
        else:
            changed = flags != stored[:2]
        if changed and self.consent_date == (stored[2] if stored else None):
            self.consent_date = timezone.localdate()
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "consent_date"}
        super().save(*args, **kwargs)
        self.remember_consent()

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class TicketSite(models.Model):
    # Not defined in documentation/model.md; minimal placeholder.
    name = models.CharField(max_length=255)
    url = models.URLField(blank=True)

    def __str__(self):
        return self.name


def validate_listen_url(value):
    """A listen address: a web address (http or https), or a place on this site, which starts with / (/media/sounds/a.mp3)."""
    if value.startswith("/"):
        if value.startswith("//") or any(c.isspace() for c in value):
            raise ValidationError("A local address starts with a single / and has no spaces.")
        return
    URLValidator(schemes=["http", "https"])(value)


class Venue(models.Model):
    name = models.CharField(max_length=255)
    address = models.TextField(max_length=255, blank=True)
    logo = models.ForeignKey(
        Image, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        limit_choices_to={"image_type": Image.ImageType.LOGO},
    )

    def __str__(self):
        return self.name


class EventQuerySet(models.QuerySet):
    def published(self):
        """The events the public site shows: Published or Promoted ones."""
        return self.filter(publish__in=Event.SHOWN)


class Event(models.Model):
    """ Wrapper for 1 or more stage productions """

    class EventType(models.TextChoices):
        AUDITION = "audition", "Audition"
        REHEARSAL = "rehearsal", "Rehearsal"
        PERFORMANCE = "performance", "Performance"
        BROADCAST = "broadcast", "Broadcast"
        OTHER = "other", "Other"

    class Publish(models.TextChoices):
        NOT_PUBLISHED = "not_published", "Not published"
        PUBLISHED = "published", "Published"
        PROMOTED = "promoted", "Promoted"

    # The Publish values the public site shows (Promoted only adds a badge in backstage).
    SHOWN = [Publish.PUBLISHED, Publish.PROMOTED]

    objects = EventQuerySet.as_manager()

    event_type = models.CharField(
        max_length=20, choices=EventType.choices, default=EventType.PERFORMANCE
    )
    publish = models.CharField(max_length=20, choices=Publish.choices, default=Publish.NOT_PUBLISHED)
    description = models.TextField(blank=True)
    venue = models.ForeignKey(Venue, null=True, blank=True, on_delete=models.SET_NULL)
    ticket_site = models.ForeignKey(
        TicketSite, null=True, blank=True, on_delete=models.SET_NULL
    )
    # Where to listen to a Broadcast event (tickets are for performances).
    # A web address, or a local one starting with / (a sound file on this site, say /media/sounds/play.mp3).
    listen_url = models.CharField(max_length=200, blank=True, validators=[validate_listen_url])

    def __str__(self):
        return self.get_event_type_display()

    @property
    def published(self):
        """Whether the public site shows this event (it is Published or Promoted)."""
        return self.publish in self.SHOWN


class EventDateTime(models.Model):
    """ Date & times for an event"""
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="datetimes"
    )
    datetime = models.DateTimeField()

    class Meta:
        ordering = ["datetime"]

    def __str__(self):
        return f"{self.event} - {self.datetime}"


def broadcast_date(prefix=""):
    """
    An expression for a production's broadcast date: the first date of its Broadcast events (nothing if it has none).
    `prefix` is the way from the model being queried to the production, e.g. "production__" for a Cast.
    """
    return Min(
        f"{prefix}events__datetimes__datetime", filter=Q(**{f"{prefix}events__event_type": Event.EventType.BROADCAST})
    )


class ProductionQuerySet(models.QuerySet):
    def with_broadcast_date(self):
        """Each production has `broadcast_at`: its broadcast date, or None (see Production.broadcast_datetime)."""
        return self.annotate(broadcast_at=broadcast_date())

    def with_event_date(self):
        """
        Each production has `event_at`: the first date of its performances and broadcasts, or None; and `upcoming`:
        whether any of those dates is still to come.
        """
        kinds = [Event.EventType.PERFORMANCE, Event.EventType.BROADCAST]
        return self.annotate(
            event_at=Min("events__datetimes__datetime", filter=Q(events__event_type__in=kinds)),
            upcoming=Exists(
                EventDateTime.objects.filter(
                    event__productions=OuterRef("pk"), event__event_type__in=kinds, datetime__gte=timezone.now()
                )
            ),
        )

    def published(self):
        """The productions with a published event (see Production.published)."""
        return self.filter(Exists(Event.objects.published().filter(productions=OuterRef("pk"))))

    def unpublished(self):
        """The productions with no published event."""
        return self.filter(~Exists(Event.objects.published().filter(productions=OuterRef("pk"))))


class Production(models.Model):
    class ProductionType(models.TextChoices):
        RADIO = "radio", "Radio play"
        STAGE = "stage", "Stage play"
        FILM = "film", "Film"
        MUSICAL = "musical", "Musical"
        OTHER = "other", "Other"

    # What the backstage menu and the list of productions call each type, in the plural.
    TYPE_TITLES = {
        "radio": "Radio plays", "stage": "Stage plays", "film": "Films", "musical": "Musicals",
        "other": "Other productions",
    }

    title = models.CharField(max_length=255)
    strap_line = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    type = models.CharField(
        max_length=20, choices=ProductionType.choices, default=ProductionType.RADIO
    )
    # Auditions, rehearsals, performances...; an event (e.g. an evening of plays) can include several productions.
    events = models.ManyToManyField(Event, blank=True, related_name="productions")
    # The parent production this one is part of (see ParentProduction), if any.
    parent = models.ForeignKey(
        "ParentProduction", null=True, blank=True, on_delete=models.SET_NULL, related_name="children",
        help_text="The parent production this is part of: it must be the same type of production",
    )

    # The image the public page shows (chosen on the backstage Public view tab); the default image if none is chosen.
    public_image = models.ForeignKey("Image", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # The background colour of the box round the public page (#rrggbb); blank means DEFAULT_PUBLIC_COLOUR.
    public_colour = models.CharField(
        max_length=7, blank=True, validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", "Enter a colour as #rrggbb.")],
    )
    DEFAULT_PUBLIC_COLOUR = "#2e1065"  # deep purple
    # The parts of the public page that are switched off (see home.views.PUBLIC_VIEW_PARTS); none: all are shown.
    public_hidden_parts = models.JSONField(default=list, blank=True)

    objects = ProductionQuerySet.as_manager()

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if not self.parent_id:
            return
        if self.pk and ParentProduction.objects.filter(pk=self.pk).exists():
            raise ValidationError({"parent": "A parent production cannot itself be part of another."})
        if self.parent.type != self.type:
            raise ValidationError({"parent": f"The parent is a {self.parent.get_type_display().lower()}, so this must be one too."})

    @property
    def published(self):
        """Whether the production is published: it has at least one Published or Promoted event. For queries use
        `Production.objects.published()` / `.unpublished()`."""
        return self.events.published().exists()

    @property
    def is_parent(self):
        """Whether this is a ParentProduction (one that wraps other productions)."""
        return ParentProduction.objects.filter(pk=self.pk).exists()

    @property
    def broadcast_datetime(self):
        """When it is (or was) broadcast: the first date of its Broadcast events, or None. Uses `broadcast_at` if the
        production came from `with_broadcast_date()`."""
        if "broadcast_at" in self.__dict__:
            return self.broadcast_at
        return (
            EventDateTime.objects.filter(event__productions=self, event__event_type=Event.EventType.BROADCAST)
            .order_by("datetime").values_list("datetime", flat=True).first()
        )

    def set_broadcast(self, when):
        """Make `when` the production's broadcast date: its first Broadcast date is changed, or a Broadcast event is made."""
        date = (
            EventDateTime.objects.filter(event__productions=self, event__event_type=Event.EventType.BROADCAST)
            .order_by("datetime", "pk").first()
        )
        if date:
            date.datetime = when
            date.save(update_fields=["datetime"])
            return
        event = Event.objects.create(event_type=Event.EventType.BROADCAST, publish=Event.Publish.PUBLISHED)
        EventDateTime.objects.create(event=event, datetime=when)
        self.events.add(event)

    def event_type_counts(self):
        """[(type label, number of events)] for each type of event the production has, in the order of the types."""
        counts = {}
        for event_type in self.events.values_list("event_type", flat=True):
            counts[event_type] = counts.get(event_type, 0) + 1
        return [(label, counts[value]) for value, label in Event.EventType.choices if value in counts]

    def broadcast_event(self):
        """The production's first Broadcast event (earliest date first, undated last), made (undated) if it has none."""
        event = (
            self.events.filter(event_type=Event.EventType.BROADCAST)
            .annotate(first_date=Min("datetimes__datetime"))
            .order_by(F("first_date").asc(nulls_last=True), "pk")
            .first()
        )
        if event is None:
            event = Event.objects.create(event_type=Event.EventType.BROADCAST, publish=Event.Publish.PUBLISHED)
            self.events.add(event)
        return event

    def _listen_url(self, published_only):
        events = self.events.filter(event_type=Event.EventType.BROADCAST).exclude(listen_url="")
        if published_only:
            events = events.published()
        event = events.annotate(first_date=Min("datetimes__datetime")).order_by(F("first_date").asc(nulls_last=True), "pk").first()
        return event.listen_url if event else ""

    # Seconds before a cached Brooklands Radio lookup that found nothing, or failed, is tried again.
    LOOKUP_RETRY = 60 * 60

    def find_listen_url(self, cached=False):
        """
        For a published radio play with no listen URL, look it up on Brooklands Radio and save it on the
        production's Broadcast event. Returns the URL found, or "" (also if the lookup fails).
        """
        if self.type != self.ProductionType.RADIO or not self.published or self.listen_url:
            return ""
        key = f"brooklands-miss-{self.pk}"
        if cached and cache.get(key):
            return ""
        from scraper.scrape import find_brooklands_play
        try:
            found = find_brooklands_play(self.title)
        except Exception:  # the site being down must not break the page; try again soon
            if cached:
                cache.set(key, True, self.LOOKUP_RETRY)
            return ""
        if not found:
            if cached:
                cache.set(key, True, self.LOOKUP_RETRY)
            return ""
        event = self.broadcast_event()
        event.listen_url = found[1]
        event.save(update_fields=["listen_url"])
        return event.listen_url

    @property
    def listen_url(self):
        """Where to listen: the address of the production's first Broadcast event that has one, or ""."""
        return self._listen_url(published_only=False)

    @property
    def awaiting_archive(self):
        """Whether it is a radio play that has been broadcast but has no public listen URL yet."""
        broadcast = self.broadcast_datetime
        return (
            self.type == self.ProductionType.RADIO and broadcast is not None and broadcast <= timezone.now()
            and not self.public_listen_url
        )

    @property
    def public_listen_url(self):
        """As listen_url, but only from a published (or promoted) event: what the public pages offer."""
        return self._listen_url(published_only=True)

    @property
    def default_image(self):
        """The production's default ProductionImage, or None. Uses prefetched images if there are any."""
        images = list(self.images.all())
        return next((i for i in images if i.is_default), None) or min(images, key=ProductionImage.preference, default=None)

    @property
    def public_view_image(self):
        """The Image the public page shows: the one chosen for it, if it is still one of the production's images,
        else the default image, else None."""
        images = list(self.images.all())
        chosen = next((i.image for i in images if i.image_id == self.public_image_id), None)
        if chosen:
            return chosen
        default = self.default_image
        return default.image if default else None

    @property
    def public_background(self):
        """The background colour of the box round the public page: the chosen one, else deep purple."""
        return self.public_colour or self.DEFAULT_PUBLIC_COLOUR

    @property
    def public_text_colour(self):
        """White or near-black, whichever reads better on the box's background colour."""
        red, green, blue = (int(self.public_background[i:i + 2], 16) for i in (1, 3, 5))
        return "#ffffff" if (0.299 * red + 0.587 * green + 0.114 * blue) < 150 else "#1f1720"

    @property
    def writers(self):
        """People in the production team with the Writer role."""
        return [member.person for member in self.team.all() if member.role.name == "Writer"]


class ParentProduction(Production):
    """
    A production that wraps several others of the same type (its `children`, e.g. the plays of an evening of short plays).
    It has everything a production has; a child production shows the parent it is linked to (Production.parent).
    """

    class Meta:
        verbose_name = "parent production"


class Cast(models.Model):
    character_name = models.CharField(max_length=255, blank=True)
    characteristics = models.TextField(blank=True)
    production = models.ForeignKey(
        Production, on_delete=models.CASCADE, related_name="cast"
    )
    actor = models.ForeignKey(
        Person,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cast_roles",
    )

    def __str__(self):
        return f"{self.character_name} in {self.production}" if self.character_name else f"{self.actor} in {self.production}"


class Role(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# Team members are always listed in this order of role; any other roles follow, alphabetically.
TEAM_ROLE_ORDER = ["Writer", "Director", "Producer", "Editor"]


def team_role_rank(role_name):
    """Where a role comes in a team listing: its place in TEAM_ROLE_ORDER, or after all of those."""
    return TEAM_ROLE_ORDER.index(role_name) if role_name in TEAM_ROLE_ORDER else len(TEAM_ROLE_ORDER)


def team_order_by(prefix=""):
    """order_by terms for a query of team members (ProductionTeam, or `prefix` away from one): see TEAM_ROLE_ORDER."""
    rank = Case(
        *[When(**{f"{prefix}role__name": name}, then=Value(i)) for i, name in enumerate(TEAM_ROLE_ORDER)],
        default=Value(len(TEAM_ROLE_ORDER)),
        output_field=models.IntegerField(),
    )
    return [rank, f"{prefix}role__name", f"{prefix}person__last_name", f"{prefix}person__first_name"]


def team_sort_key(member):
    """The same order for team members already in a list."""
    return (team_role_rank(member.role.name), member.role.name, member.person.last_name, member.person.first_name)


class ProductionTeam(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.PROTECT)
    production = models.ForeignKey(
        Production, on_delete=models.CASCADE, related_name="team"
    )

    def __str__(self):
        return f"{self.person} ({self.role}) - {self.production}"


class ProductionImage(models.Model):
    production = models.ForeignKey(
        Production, on_delete=models.CASCADE, related_name="images"
    )
    image = models.ForeignKey(Image, on_delete=models.CASCADE)
    # The production's main image (e.g. its cover in lists). A production with images has exactly one.
    is_default = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["production"],
                condition=models.Q(is_default=True),
                name="one_default_image_per_production",
            )
        ]

    def __str__(self):
        return f"{self.production} - {self.image}"

    # Which kind of image is best as the default: a production image, else a promotion image, else a gallery image, else anything.
    TYPE_PREFERENCE = [Image.ImageType.PRODUCTION, Image.ImageType.PROMOTION, Image.ImageType.GALLERY]

    @classmethod
    def preference(cls, production_image):
        """A sort key: the best default image comes first (by kind of image, then the earliest)."""
        kind = production_image.image.image_type
        rank = cls.TYPE_PREFERENCE.index(kind) if kind in cls.TYPE_PREFERENCE else len(cls.TYPE_PREFERENCE)
        return rank, production_image.id

    def make_default(self):
        """Make this the production's default image (and no other)."""
        with transaction.atomic():
            self.production.images.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
            self.is_default = True
            self.save(update_fields=["is_default"])

    @classmethod
    def ensure_default(cls, production):
        """If the production has images but no default, make the best one the default (see `preference`)."""
        images = production.images.select_related("image")
        if not images.filter(is_default=True).exists() and (best := min(images, key=cls.preference, default=None)):
            best.make_default()


class Sound(models.Model):
    """A sound file of a production (uploaded on its Media tab), kept in MEDIA_ROOT/sounds/. It always belongs to one."""

    production = models.ForeignKey(Production, on_delete=models.CASCADE, related_name="sounds")
    file = models.FileField(upload_to="sounds/")
    uploaded = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded", "id"]

    @property
    def name(self):
        return os.path.basename(self.file.name)

    def __str__(self):
        return f"{self.name} ({self.production})"


@receiver(post_delete, sender=Sound)
def delete_sound_file(sender, instance, **kwargs):
    """The file goes with its sound (also when the production is deleted)."""
    if instance.file:
        instance.file.storage.delete(instance.file.name)


@receiver(post_save, sender=Image)
def make_gallery_copy(sender, instance, **kwargs):
    """A gallery image gets its resized copy for the public gallery as soon as it is saved (it is also made on demand)."""
    if instance.image and instance.image_type == Image.ImageType.GALLERY:
        from backstage.renditions import gallery_items

        gallery_items([instance])  # never raises: a fault here must not stop an upload


@receiver(post_delete, sender=Image)
def delete_gallery_copy(sender, instance, **kwargs):
    """The resized copy goes with its image."""
    if instance.image:
        from backstage.renditions import existing_rendition

        found = existing_rendition(instance)
        if found:
            instance.image.storage.delete(found[0])


class Palette(models.Model):
    """A named set of up to 8 colours (e.g. the swatches offered for a public page's background)."""

    SIZE = 8

    name = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def as_pairs(self):
        """[(colour name, #rrggbb)] in order, the form of themes.PUBLIC_PALETTE."""
        return [(colour.name, colour.colour) for colour in self.colours.all()]

    @property
    def is_complete(self):
        """Whether all 8 colours are set."""
        return self.colours.count() == self.SIZE

    def slots(self):
        """The 8 places in order: a (name, #rrggbb), or None where nothing is saved."""
        by_position = {c.position: (c.name, c.colour) for c in self.colours.all()}
        return [by_position.get(i) for i in range(self.SIZE)]

    def set_colour(self, position, colour, name=""):
        """Save `colour` (#rrggbb) in place `position` (0 to 7), replacing what was there. ValueError if either is bad."""
        colour = (colour or "").strip().lower()
        if not re.fullmatch(r"#[0-9a-f]{6}", colour):
            raise ValueError("That is not a colour (#rrggbb).")
        if not isinstance(position, int) or not 0 <= position < self.SIZE:
            raise ValueError("Choose one of the saved boxes.")
        saved, _ = self.colours.update_or_create(position=position, defaults={"name": name, "colour": colour})
        return saved


class PaletteColour(models.Model):
    palette = models.ForeignKey(Palette, on_delete=models.CASCADE, related_name="colours")
    # Where the colour comes in the palette: 0 to 7 (so a palette cannot have more than 8 colours).
    position = models.PositiveSmallIntegerField(validators=[MaxValueValidator(Palette.SIZE - 1)])
    name = models.CharField(max_length=255, blank=True)
    colour = models.CharField(max_length=7, validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", "Enter a colour as #rrggbb.")])

    class Meta:
        ordering = ["palette", "position"]
        constraints = [
            models.UniqueConstraint(fields=["palette", "position"], name="one_colour_per_palette_position"),
            models.CheckConstraint(condition=models.Q(position__lt=8), name="palette_position_below_8"),
        ]

    def __str__(self):
        return f"{self.palette} {self.position + 1}: {self.name or self.colour}"

    def save(self, *args, **kwargs):
        self.colour = self.colour.lower()
        super().save(*args, **kwargs)

