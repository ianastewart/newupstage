from django import forms
from django.db.models import Q

from backstage import models
from rmeditor.widgets import RichTextWidget

class PersonForm(forms.ModelForm):
    class Meta:
        model = models.Person
        fields = ["first_name", "last_name", "email", "mobile", "biography", "gender", "dob", "image", "roles"]
        labels = {"dob": "Date of birth", "image": "Photo"}
        widgets = {
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


class CastForm(forms.ModelForm):
    class Meta:
        model = models.Cast
        fields = ["character_name", "characteristics", "actor"]
        widgets = {"characteristics": forms.Textarea(attrs={"rows": 3})}


class ProductionTeamForm(forms.ModelForm):
    class Meta:
        model = models.ProductionTeam
        fields = ["person", "role"]


class EventForm(forms.ModelForm):
    """A new event from a production's Events tab, optionally with its first date and time."""

    first_datetime = forms.DateTimeField(
        required=False, label="First date & time",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        help_text="More dates can be added on the Events tab.",
    )

    class Meta:
        model = models.Event
        fields = ["title", "event_type", "venue", "ticket_site", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def save(self, commit=True):
        event = super().save(commit)
        if commit and self.cleaned_data.get("first_datetime"):
            event.datetimes.create(datetime=self.cleaned_data["first_datetime"])
        return event
