from django.db import models
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


class Event(models.Model):
    """ Wrapper for 1 or more stage productions """

    title = models.CharField(max_length=255)
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
    writer = models.ForeignKey(
        Person,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="writers",
    )
    state = models.CharField(
        max_length=20, choices=ProductionState.choices, default=ProductionState.PLANNED
    )
    type = models.CharField(
        max_length=20, choices=ProductionType.choices, default=ProductionType.RADIO
    )
    event = models.ForeignKey(
        Event, null=True, blank=True, on_delete=models.SET_NULL
    )

    def __str__(self):
        return self.title


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

    def __str__(self):
        return f"{self.production} - {self.image}"
