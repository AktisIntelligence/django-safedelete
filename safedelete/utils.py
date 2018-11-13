import logging

import warnings

from collections import OrderedDict

from django.contrib.admin.utils import NestedObjects
from django.db import router

from .config import DEFAULT_DELETED

logger = logging.getLogger(__name__)


def is_safedelete_cls(cls):
    for base in cls.__bases__:
        # This used to check if it startswith 'safedelete', but that masks
        # the issue inside of a test. Other clients create models that are
        # outside of the safedelete package.
        if base.__module__.startswith('safedelete.models'):
            return True
        if is_safedelete_cls(base):
            return True
    return False


def is_safedelete(related):
    warnings.warn(
        'is_safedelete is deprecated in favor of is_safedelete_cls',
        DeprecationWarning)
    return is_safedelete_cls(related.__class__)


def is_deleted(obj):
    return obj.deleted != DEFAULT_DELETED


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
    collector.sort()
    return collector


def extract_objects_to_delete(obj):
    """
    Return a dictionary of objects that meed to be deleted if we want to delete the object provided as input.

    We exclude the input object from this dictionary.
    """
    collector = get_collector(obj)
    objects_to_delete = OrderedDict()
    for model, instances in collector.data.items():
        # we don't want to have the input object in the list of objects to delete by cascade as we will handle it
        # separately.
        if model is obj.__class__:
            instances.remove(obj)
        # If the model is a safedelete object we also want to exclude the already deleted objects.
        if is_safedelete_cls(model):
            instances = [instance for instance in instances if not is_deleted(instance)]
        if len(instances) != 0:
            objects_to_delete[model] = instances

    return objects_to_delete


def perform_updates(obj):
    """
    After the deletes have been done we need to perform the updates if there are any.
    Note that we don't need to do the updates for the already deleted objects.
    """
    collector = get_collector(obj)
    for model, updates in collector.field_updates.items():
        for (field, value), objects in updates.items():
            if is_safedelete_cls(model):
                objects = [o for o in objects if not is_deleted(o)]
            if len(objects) != 0:
                logger.info("  > cascade update {} {} ({}={})".format(len(objects), model.__name__, field.name, value))
                logger.debug("       {}".format([o.id for o in objects]))
            for o in objects:
                setattr(o, field.name, value)
                o.save()


def can_hard_delete(obj):
    """
    Check if it would delete other objects.
    """
    return bool(extract_objects_to_delete(obj))
