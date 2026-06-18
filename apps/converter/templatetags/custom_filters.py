from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary with a dynamic key (supports hyphenated keys)."""
    if dictionary is None:
        return None
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    # Handle objects with attributes
    return getattr(dictionary, key, None)
