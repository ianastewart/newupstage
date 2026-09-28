from django.db import models, transaction
from django_enum import EnumField


class Upstage(models.Model):
    name = models.CharField(max_length=255)
    introduction = models.TextField(blank=True)
    logo = models.ImageField(upload_to="upstage/", blank=True)

    def __str__(self):
        return self.name


class Image(models.Model):
    class ImageType(models.TextChoices):
        BASE = "base", "Base"
        AUDITION = "audition", "Audition"
        PROMOTION = "promotion", "Promotion"
        GALLERY = "gallery", "Gallery"
        HEADSHOT = "headshot", "Headshot"
        LOGO = "logo", "Logo"
        OTHER = "other", "Other"

    image = models.ImageField(upload_to="images/")
    description = models.CharField(max_length=255, blank=True)
    image_type = EnumField(ImageType, default=ImageType.BASE)

    def __str__(self):
        return self.description or self.image.name


class Person(models.Model):
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    mobile = models.CharField(max_length=30, blank=True)
    biography = models.TextField(blank=True)
    gender = models.CharField(max_length=10, choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')], blank=True)
    dob = models.DateField(null=True, blank=True)
    image = models.ForeignKey(
        Image, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    roles = models.ManyToManyField("Role", blank=True, related_name="people")

    class Meta:
        verbose_name_plural = "people"
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class TicketSite(models.Model):
    # Not defined in documentation/model.md; minimal placeholder.
    name = models.CharField(max_length=255)
    url = models.URLField(blank=True)

    def __str__(self):
        return self.name


class Venue(models.Model):
    name = models.CharField(max_length=255)
    address = models.TextField(max_length=255, blank=True)
    logo = models.ForeignKey(
        Image, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        limit_choices_to={"image_type": Image.ImageType.LOGO},
    )

    def __str__(self):
        return self.name


class Event(models.Model):
    """ Wrapper for 1 or more stage productions """

    class EventType(models.TextChoices):
        AUDITION = "audition", "Audition"
        REHEARSAL = "rehearsal", "Rehearsal"
        PERFORMANCE = "performance", "Performance"
        OTHER = "other", "Other"

    title = models.CharField(max_length=255)
    event_type = models.CharField(
        max_length=20, choices=EventType.choices, default=EventType.PERFORMANCE
    )
    description = models.TextField(blank=True)
    venue = models.ForeignKey(Venue, null=True, blank=True, on_delete=models.SET_NULL)
    ticket_site = models.ForeignKey(
        TicketSite, null=True, blank=True, on_delete=models.SET_NULL
    )

    def __str__(self):
        return self.title


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


class Production(models.Model):
    class ProductionState(models.TextChoices):
        """Planned, Audition, Cast, Broadcast date, Live, Archived"""
        PLANNED = "planned", "Planned"
        AUDITION = "audition", "Audition"
        CAST = "cast", "Cast"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    class ProductionType(models.TextChoices):
        RADIO = "radio", "Radio play"
        STAGE = "stage", "Stage play"
        FILM = "film", "Film"
        OTHER = "other", "Other"

    title = models.CharField(max_length=255)
    strap_line = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    state = models.CharField(
        max_length=20, choices=ProductionState.choices, default=ProductionState.PLANNED
    )
    type = models.CharField(
        max_length=20, choices=ProductionType.choices, default=ProductionType.RADIO
    )
    # Auditions, rehearsals, performances...; an event (e.g. an evening of plays) can include several productions.
    events = models.ManyToManyField(Event, blank=True, related_name="productions")
    listen_url = models.URLField(null=True, blank=True)
    broadcast_datetime = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title

    @property
    def default_image(self):
        """The production's default ProductionImage, or None. Uses prefetched images if there are any."""
        images = list(self.images.all())
        return next((i for i in images if i.is_default), None) or min(images, key=lambda i: i.id, default=None)

    @property
    def writers(self):
        """People in the production team with the Writer role."""
        return [member.person for member in self.team.all() if member.role.name == "Writer"]


class Cast(models.Model):
    character_name = models.CharField(max_length=255)
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
        return f"{self.character_name} in {self.production}"


class Role(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


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

    def make_default(self):
        """Make this the production's default image (and no other)."""
        with transaction.atomic():
            self.production.images.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
            self.is_default = True
            self.save(update_fields=["is_default"])

    @classmethod
    def ensure_default(cls, production):
        """If the production has images but no default, make the earliest one the default."""
        images = production.images.order_by("id")
        if not images.filter(is_default=True).exists() and (first := images.first()):
            first.make_default()
