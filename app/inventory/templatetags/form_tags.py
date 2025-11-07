# distributorplatform/app/inventory/templatetags/form_tags.py
from django import template

register = template.Library()

@register.filter(name='add_class')
def add_class(field, css_classes):
    """
    Adds CSS classes to a Django form field widget.
    Usage: {{ form.my_field|add_class:"your-tailwind-classes here" }}
    """
    # Get the existing classes (if any)
    existing_classes = field.field.widget.attrs.get('class', '')

    # Combine old and new classes, split into a list
    all_classes = existing_classes.split() + css_classes.split()

    # Remove duplicates and join back into a space-separated string
    final_classes = ' '.join(sorted(list(set(all_classes))))

    # Add the final class string back to the widget attributes
    return field.as_widget(attrs={'class': final_classes})
