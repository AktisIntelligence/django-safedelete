import logging

import warnings

from collections import OrderedDict

from .collector import get_collector
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


def get_objects_to_delete(objs, return_deleted=False):
    """
    Return a dictionary of objects that meed to be deleted if we want to delete the objects provided as input.

    We exclude the input objects from this dictionary (we make the assumption that all objects provided as input are
    of the same type).

    If return_deleted is set to False it will exclude the already deleted objects.
    """
    collector = get_collector(objs)
    fast_deletes = OrderedDict()
    for fast_delete_qs in collector.fast_deletes:
        model = fast_delete_qs.model
        if model is objs[0].__class__:
            fast_delete_qs = fast_delete_qs.exclude(pk__in=[o.pk for o in objs])
        if is_safedelete_cls(model) and not return_deleted:
            fast_delete_qs = fast_delete_qs.filter(deleted=DEFAULT_DELETED)
        fast_deletes[model] = fast_delete_qs
    objects_to_delete = OrderedDict()
    for model in collector.data:
        instances = collector.data[model]
        # we don't want to have the input object in the list of objects to delete by cascade as we will handle it
        # separately.
        if model is objs[0].__class__:
            instances = [instance for instance in instances if instance not in objs]
        # If the model is a safedelete object we also want to exclude the already deleted objects.
        if is_safedelete_cls(model) and not return_deleted:
            instances = [instance for instance in instances if not is_deleted(instance)]
        if len(instances) != 0:
            objects_to_delete[model] = instances
    return fast_deletes, objects_to_delete


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
    fast_deletes, objects_to_delete = get_objects_to_delete([obj])
    nb_objects_deleted = sum([fast_delete_qs.count() for fast_delete_qs in fast_deletes.values()])
    nb_objects_deleted += sum([len(instances) for instances in objects_to_delete.values()])
    return nb_objects_deleted == 0


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
