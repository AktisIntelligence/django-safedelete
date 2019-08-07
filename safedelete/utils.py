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


def get_collector(objs):
    """
    Create a collector for the given objects.
    The collector contains all the objects related to the objects given as input that would need to be modified if we
    deleted the input objects:
    - if they need to be deleted by cascade they are in `collector.data` (ordered dictionary) and `collector.nested()`
    (as a nested list)
    - if they need to be updated (case of on_delete=models.SET_NULL for example) they are in `collector.field_updates`

    When calling `collector.delete()`, it goes through both types and delete/update the related objects.
    Note that by doing that it does not call the model delete/save methods.

    Note that `collector.data` also contains the object itself.
    """
    # Assume we have at least one object (which is fine since we control where this method is called)
    collector = NestedObjects(using=router.db_for_write(objs[0]))
    collector.collect(objs)
    collector.sort()
    return collector


def get_objects_to_delete(objs, return_deleted=False):
    """
    Return a dictionary of objects that meed to be deleted if we want to delete the objects provided as input.

    We exclude the input objects from this dictionary (we make the assumption that all objects provided as input are
    of the same type).

    If return_deleted is set to False it will exclude the already deleted objects.
    """
    collector = get_collector(objs)
    objects_to_delete = OrderedDict()
    for model, instances in collector.data.items():
        # we don't want to have the input object in the list of objects to delete by cascade as we will handle it
        # separately.
        if model is objs[0].__class__:
            instances = [instance for instance in instances if instance not in objs]
        # If the model is a safedelete object we also want to exclude the already deleted objects.
        if is_safedelete_cls(model):
            instances = [instance for instance in instances if not is_deleted(instance) or return_deleted]
        if len(instances) != 0:
            objects_to_delete[model] = instances
    return objects_to_delete


def perform_updates(objs):
    """
    After the deletes have been done we need to perform the updates if there are any.
    Note that we don't need to do the updates for the already deleted objects.
    """
    collector = get_collector(objs)
    for model, updates in collector.field_updates.items():
        for (field, value), objects in updates.items():
            if is_safedelete_cls(model):
                pks = [o.pk for o in objects if not is_deleted(o)]
            else:
                pks = [o.pk for o in objects]
            if len(pks) != 0:
                logger.info("  > cascade update {} {} ({}={})".format(len(objects), model.__name__, field.name, value))
                logger.debug("       {}".format([o.pk for o in objects]))
            # bulk update the field (this means that we dont)
            model.objects.filter(pk__in=[o.pk for o in objects]).update(**{field.name: value})


def can_hard_delete(obj):
    """
    Check if it would delete other objects.
    """
    return not bool(get_objects_to_delete([obj]))


def concatenate_delete_returns(*args):
    """
    This method allow to concatenate the return values of multiple deletes.
    This is useful when we override a delete method so it automatically deletes other objects we can then return
    an accurate result of the number of entities deleted.
    """
    # the return of a delete is a tuple with:
    #  - total number of objects deleted
    #  - a dict with the number of objects deleted per models
    concatenated = [0, {}]
    for return_value in args:
        concatenated[0] += return_value[0]
        for model, count in return_value[1].items():
            concatenated[1].setdefault(model, 0)
            concatenated[1][model] += count
    return tuple(concatenated)
