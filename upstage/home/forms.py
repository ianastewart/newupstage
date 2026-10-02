from django import forms
from rmeditor.widgets import RichTextWidget

from backstage.models import Image, Production

from .models import Block, WebPage


class WebPageForm(forms.ModelForm):
    class Meta:
        model = WebPage
        fields = ["title", "slug", "background_colour"]
        widgets = {"background_colour": forms.TextInput(attrs={"placeholder": "#rrggbb", "data-swatches": ""})}
        help_texts = {"slug": "Used in the page's address: /page/<slug>/. Letters, numbers and hyphens."}


class BlockForm(forms.ModelForm):
    class Meta:
        model = Block
        fields = [
            "name", "block_type", "title", "subtitle", "text", "production", "image", "url", "image_size", "layout",
            "background_colour", "text_colour",
        ]
        widgets = {
            "text": RichTextWidget(attrs={"rows": 10}),
            # Plain text rather than a colour picker, which can't be left blank (blank = theme colour); swatches fill it in.
            "background_colour": forms.TextInput(attrs={"placeholder": "#rrggbb", "data-swatches": ""}),
            "url": forms.TextInput(attrs={"placeholder": "https://... or /page/about/"}),
            "text_colour": forms.TextInput(attrs={"placeholder": "#rrggbb", "data-swatches": ""}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].queryset = Image.objects.order_by("description")
        self.fields["production"].queryset = Production.objects.order_by("title")
