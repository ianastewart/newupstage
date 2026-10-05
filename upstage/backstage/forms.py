from urllib.parse import urlparse

from django import forms
from django.db.models import Q
from django.db.models.functions import Lower

from backstage import models
from backstage.fields import CENTRE, NEUTRAL_TONE, clamp, clamp_tone
from rmeditor.widgets import RichTextWidget

class PersonForm(forms.ModelForm):
    class Meta:
        model = models.Person
        fields = ["first_name", "last_name", "email", "mobile", "biography", "gender", "dob", "image", "roles"]
        labels = {"dob": "Date of birth", "image": "Photo"}
        widgets = {
            # Not a list to choose from: the photo comes from the Upload photo button, which returns here with it chosen.
            "image": forms.HiddenInput(),
            "biography": RichTextWidget(attrs={"rows": 8, "data-tools": "bold underline italic link"}),
            # Date pickers need ISO dates regardless of the site's locale.
            "dob": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "roles": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only headshots can be chosen as a photo, plus the current photo so editing keeps it.
        photos = Q(image_type=models.Image.ImageType.HEADSHOT)
        if self.instance.image_id:
            photos |= Q(pk=self.instance.image_id)
        self.fields["image"].queryset = models.Image.objects.filter(photos).order_by("description")


class PersonDetailsForm(forms.ModelForm):
    """Step 1 of the new actor wizard: who they are (names, contact details, biography)."""

    class Meta:
        model = models.Person
        fields = ["first_name", "last_name", "email", "mobile", "gender", "dob", "biography"]
        labels = {"dob": "Date of birth"}
        widgets = {
            "biography": RichTextWidget(attrs={"rows": 8, "data-tools": "bold underline italic link"}),
            "dob": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }


class PersonRolesForm(forms.ModelForm):
    """Step 3 of the new actor wizard: their roles."""

    class Meta:
        model = models.Person
        fields = ["roles"]
        widgets = {"roles": forms.CheckboxSelectMultiple}


class CastForm(forms.ModelForm):
    class Meta:
        model = models.Cast
        fields = ["character_name", "characteristics", "actor"]
        widgets = {"characteristics": forms.Textarea(attrs={"rows": 3})}


class ProductionTeamForm(forms.ModelForm):
    class Meta:
        model = models.ProductionTeam
        fields = ["person", "role"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Alphabetical by first name (as the names are shown), leaving out people who are only actors:
        # they are cast, not team. Whoever is already on the team stays, so editing still works.
        actor_only = models.Person.objects.filter(roles__name="Actor").exclude(
            roles__in=models.Role.objects.exclude(name="Actor")
        )
        allowed = ~Q(pk__in=actor_only.values("pk"))
        if self.instance.person_id:
            allowed |= Q(pk=self.instance.person_id)
        self.fields["person"].queryset = models.Person.objects.filter(allowed).order_by(
            Lower("first_name"), Lower("last_name")
        )
        self.fields["person"].help_text = "People with only an Actor role are omitted from the list"


class EventDetailsForm(forms.ModelForm):
    """
    An event's type, whether it is published, venue, where to buy tickets and description. The tickets are a web address that is typed in,
    not picked from a list: it is kept as a TicketSite (found by its address, or made, named after the website).
    """

    ticket_url = forms.URLField(
        required=False, label="Ticket website", assume_scheme="https",
        widget=forms.URLInput(attrs={"placeholder": "https://..."}),
        help_text="Where to buy tickets. Leave blank if there is no ticket website.",
    )
    field_order = ["event_type", "publish", "venue", "ticket_url", "description"]

    class Meta:
        model = models.Event
        fields = ["event_type", "publish", "venue", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.ticket_site_id:
            self.fields["ticket_url"].initial = self.instance.ticket_site.url

    def save(self, commit=True):
        url = self.cleaned_data.get("ticket_url")
        if url:
            site = models.TicketSite.objects.filter(url=url).first() or models.TicketSite.objects.create(
                name=urlparse(url).netloc.removeprefix("www.") or url, url=url
            )
        else:
            site = None
        self.instance.ticket_site = site
        return super().save(commit)


class EventForm(EventDetailsForm):
    """A new event from a production's Events tab, optionally with its first date and time."""

    first_datetime = forms.DateTimeField(
        required=False, label="First date & time",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        help_text="More dates can be added on the Events tab.",
    )
    field_order = ["event_type", "publish", "venue", "ticket_url", "first_datetime", "description"]

    def save(self, commit=True):
        event = super().save(commit)
        if commit and self.cleaned_data.get("first_datetime"):
            event.datetimes.create(datetime=self.cleaned_data["first_datetime"])
        return event


class ImageForm(forms.ModelForm):
    """
    The image library's upload form. For a headshot, the photo is cropped around a focus point (`focal_x` and
    `focal_y`, 0 to 1 from the left and from the top) and given a brightness and contrast (`brightness` and `contrast`,
    -100 to 100): the page sets them. They are not kept: they only steer what is done when the file is saved.
    Anything unusable means the middle, and no change to the tone.
    """

    focal_x = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"id": "id_focal_x"}), initial="0.5")
    focal_y = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"id": "id_focal_y"}), initial="0.5")
    # Brightness and contrast, -100 to 100 (0: as the photo is): set by the sliders on the page, and not kept either.
    brightness = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"id": "id_brightness"}), initial="0")
    contrast = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"id": "id_contrast"}), initial="0")

    class Meta:
        model = models.Image
        fields = ["image", "description", "image_type"]
        widgets = {"image": forms.ClearableFileInput(attrs={"accept": "image/*"})}

    def clean_focal_x(self):
        return clamp(self.cleaned_data.get("focal_x"))

    def clean_focal_y(self):
        return clamp(self.cleaned_data.get("focal_y"))

    def clean_brightness(self):
        return clamp_tone(self.cleaned_data.get("brightness"))

    def clean_contrast(self):
        return clamp_tone(self.cleaned_data.get("contrast"))

    def save(self, commit=True):
        self.instance.focal_point = (
            self.cleaned_data.get("focal_x", CENTRE[0]), self.cleaned_data.get("focal_y", CENTRE[1])
        )
        self.instance.tone = (
            self.cleaned_data.get("brightness", NEUTRAL_TONE[0]), self.cleaned_data.get("contrast", NEUTRAL_TONE[1])
        )
        return super().save(commit)
