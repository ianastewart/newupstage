from django import forms
from rmeditor.widgets import RichTextWidget

from backstage.models import Image, Production

from .models import Block, BlockColumn, WebPage


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
            "name", "block_type", "title", "subtitle", "text", "production", "image", "url", "image_size", "layout", "separate_columns", "equal_height", "flush_images", "match_image_heights", "fade_in_seconds",
            "background_colour", "text_colour",
        ]
        widgets = {
            "text": RichTextWidget(attrs={"rows": 10}),
            # Plain text rather than a colour picker, which can't be left blank (blank = theme colour); swatches fill it in.
            "background_colour": forms.TextInput(attrs={"placeholder": "#rrggbb", "data-swatches": ""}),
            "url": forms.TextInput(attrs={"placeholder": "https://... or /page/about/"}),
            "fade_in_seconds": forms.NumberInput(attrs={"min": 0, "max": 30, "step": "0.5"}),
            "text_colour": forms.TextInput(attrs={"placeholder": "#rrggbb", "data-swatches": ""}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].queryset = Image.objects.order_by("description")
        self.fields["production"].queryset = Production.objects.order_by("title")
        self.fields["fade_in_seconds"].required = False  # left blank, it is the usual 5 seconds

    def clean_fade_in_seconds(self):
        seconds = self.cleaned_data.get("fade_in_seconds")
        return Block._meta.get_field("fade_in_seconds").get_default() if seconds is None else seconds


class BlockColumnForm(forms.ModelForm):
    """One column of a columns block: an image, some text and an optional link on the image."""

    class Meta:
        model = BlockColumn
        fields = ["title", "image", "text", "url"]
        widgets = {
            "text": RichTextWidget(attrs={"rows": 6}),
            "url": forms.TextInput(attrs={"placeholder": "https://... or /page/about/"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].queryset = Image.objects.order_by("description")

    def is_blank(self):
        data = self.cleaned_data
        return not (
            data.get("image") or (data.get("title") or "").strip() or (data.get("text") or "").strip() or data.get("url")
        )


class BaseBlockColumnFormSet(forms.BaseInlineFormSet):
    """
    The columns of a block. There is room for the most any block has; a block shows only as many as its type
    has. `required_columns` (set before validating) is how many of the first columns must have something in them.
    """

    required_columns = 0

    def add_fields(self, form, index):
        super().add_fields(form, index)
        # Where the column is in the row, left to right. The page's Move left and Move right buttons change it.
        form.fields["order"] = forms.IntegerField(
            required=False, min_value=0, widget=forms.HiddenInput(attrs={"data-column-order": ""}), initial=index
        )

    def in_order(self):
        """The forms in the order the columns are to be in: by their order field, then as they came."""
        def key(item):
            index, form = item
            order = getattr(form, "cleaned_data", {}).get("order")
            return (index if order is None else order, index)

        return [form for _, form in sorted(enumerate(self.forms), key=key)]

    def clean(self):
        super().clean()
        for form in self.in_order()[: self.required_columns]:
            if hasattr(form, "cleaned_data") and form.is_blank():
                form.add_error(None, "This column needs an image, a title or some text.")

    def save_columns(self, block):
        """Save the columns in order. A column that has been emptied is removed, and an empty new one skipped."""
        position = 0
        for form in self.in_order():
            if not hasattr(form, "cleaned_data"):
                continue
            if form.is_blank():
                if form.instance.pk:
                    form.instance.delete()
                continue
            column = form.save(commit=False)
            column.block, column.position = block, position
            column.save()
            position += 1


BlockColumnFormSet = forms.inlineformset_factory(
    Block, BlockColumn, form=BlockColumnForm, formset=BaseBlockColumnFormSet,
    extra=Block.MAX_COLUMNS, max_num=Block.MAX_COLUMNS, can_delete=False,
)
