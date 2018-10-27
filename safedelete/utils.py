from collections import OrderedDict

from django.contrib.admin.utils import NestedObjects
from django.db import router


def get_collector(obj):
    """
    Create a collector for a given object.
    The collector contains all the objects related to the object given as input that would need to be modified if we
    deleted the input object:
    - if they need to be deleted by cascade they are in `collector.data` (ordered dictionary) and `collector.nested()`
    (as a nested list)
    - if they need to be updated (case of on_delete=models.SET_NULL for example) they are in `collector.field_updates`

    When calling `collector.delete()`, it goes through both types and delete/update the related objects.
    Note that by doing that it does not call the model delete/save methods.

    Note that `collector.data` also contains the object itself.
    """
    collector = NestedObjects(using=router.db_for_write(obj))
    collector.collect([obj])
    return collector


def extract_objects_to_delete(obj):
    """
    Return a dictionary of objects that meed to be deleted if we want to delete the object provided as input.

    We exclude the input object from this dictionary.
    """
    collector = get_collector(obj)
    collector.sort()
    objects_to_delete = OrderedDict()
    for model, instances in collector.data.items():
        # we don't want to have the input object in the list of objects to delete by cascade as we will handle it
        # separately.
        if model is obj.__class__:
            instances.remove(obj)
        if len(instances) != 0:
            objects_to_delete[model] = instances

    return objects_to_delete


def perform_updates(obj):
    """
    Remove everything to delete in the collector and call the `delete()` method to do the updates.
    """
    collector = get_collector(obj)
    # Replace the data to delete by an empty dict
    collector.data = OrderedDict()
    collector.delete()


def can_hard_delete(obj):
    """
    Check if it would delete other objects.
    """
    collector = get_collector(obj)
    return bool(extract_objects_to_delete(obj, collector))
