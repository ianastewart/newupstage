from django import forms

from backstage import models


class PersonForm(forms.ModelForm):
    class Meta:
        model = models.Person
        fields = ["first_name", "last_name", "email", "mobile", "biography", "gender", "dob", "image", "roles"]
        labels = {"dob": "Date of birth", "image": "Photo"}
        widgets = {
            "biography": forms.Textarea(attrs={"rows": 4}),
            # Date pickers need ISO dates regardless of the site's locale.
            "dob": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "roles": forms.CheckboxSelectMultiple,
        }


class CastForm(forms.ModelForm):
    class Meta:
        model = models.Cast
        fields = ["character_name", "characteristics", "actor"]
        widgets = {"characteristics": forms.Textarea(attrs={"rows": 3})}


class ProductionTeamForm(forms.ModelForm):
    class Meta:
        model = models.ProductionTeam
        fields = ["person", "role"]
