from django.db import router
from django.db.models.deletion import Collector


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
    collector = Collector(using=router.db_for_write(objs[0]))
    collector.collect(objs)
    collector.sort()
    return collector
