from django.forms.renderers import TemplatesSetting


class DaisyFormRenderer(TemplatesSetting):
    """Render every form with the project's daisyUI layout templates."""

    form_template_name = "forms/div.html"
    field_template_name = "forms/field.html"
