from distutils.version import LooseVersion

import django
from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import query
from django.db.models.fields.related import ForeignKey
from django.db.models.query_utils import Q
from django.utils import timezone

from .config import (DEFAULT_DELETED, DELETED_INVISIBLE, DELETED_ONLY_VISIBLE, DELETED_VISIBLE,
                     DELETED_VISIBLE_BY_FIELD, HARD_DELETE, HARD_DELETE_NOCASCADE, NO_DELETE, SOFT_DELETE_CASCADE,
                     SOFT_DELETE)
from .utils import concatenate_delete_returns, get_objects_to_delete, is_safedelete_cls, perform_updates


class SafeDeleteIntegrityError(DatabaseError):
    pass


class SafeDeleteQueryset(query.QuerySet):
    """Default queryset for the SafeDeleteManager.

    Takes care of "lazily evaluating" safedelete QuerySets. QuerySets passed
    within the ``SafeDeleteQueryset`` will have all of the models available.
    The deleted policy is evaluated at the very end of the chain when the
    QuerySet itself is evaluated.
    """
    _safedelete_filter_applied = False

    def delete(self, force_policy=None):
        """Overrides bulk delete behaviour.
        Note that like Django implementation we don't call the custom delete of each models so if they have any magic
        in them it won't be applied.

        .. seealso::
            :py:func:`safedelete.models.SafeDeleteModel.delete`
        """
        assert self.query.can_filter(), "Cannot use 'limit' or 'offset' with delete."
        with transaction.atomic():
            current_policy = self.model._get_safelete_policy(force_policy=force_policy)
            delete_returns = []
            if current_policy == NO_DELETE:
                # Don't do anything.
                return (0, {})
            elif current_policy == HARD_DELETE:
                # Normally hard-delete the objects (bulk delete from Django)
                return super(SafeDeleteQueryset, self).delete()
            elif current_policy == HARD_DELETE_NOCASCADE:
                # This is not optimised but we don't use it for now anyway
                for obj in self.all():
                    delete_returns.append(obj.delete(force_policy=force_policy))
                self._result_cache = None
            elif current_policy == SOFT_DELETE:
                nb_objects = self.count()
                self.update(deleted=timezone.now())
                delete_returns.append((nb_objects, {self.model._meta.label: nb_objects}))
            elif current_policy == SOFT_DELETE_CASCADE:
                queryset_objects = list(self.all())
                if len(queryset_objects) == 0:
                    # If it is an empty query set nothing to do
                    return (0, {})
                delete_returns.append(self.delete(force_policy=SOFT_DELETE))
                # Soft-delete on related objects
                for model, related_objects in get_objects_to_delete(queryset_objects).items():
                    if is_safedelete_cls(model):
                        nb_objects = len(related_objects)
                        related_objects_qs = model.objects.filter(pk__in=[o.pk for o in related_objects])
                        delete_returns.append(related_objects_qs.delete(force_policy=SOFT_DELETE))
                # Do the updates that the delete implies.
                # (for example in case of a relation `on_delete=models.SET_NULL`)
                perform_updates(queryset_objects)
        return concatenate_delete_returns(*delete_returns)
    delete.alters_data = True

    def undelete(self, force_policy=None):
        """Undelete all soft deleted models.

        .. note::
            The current implementation loses performance on bulk undeletes in
            order to call the pre/post-save signals.

        .. seealso::
            :py:func:`safedelete.models.SafeDeleteModel.undelete`
        """
        assert self.query.can_filter(), "Cannot use 'limit' or 'offset' with undelete."
        # TODO: Replace this by bulk update if we can (need to call pre/post-save signal)
        for obj in self.all():
            obj.undelete(force_policy=force_policy)
        self._result_cache = None
    undelete.alters_data = True

    def all(self, force_visibility=None):
        """Override so related managers can also see the deleted models.

        A model's m2m field does not easily have access to `all_objects` and
        so setting `force_visibility` to True is a way of getting all of the
        models. It is not recommended to use `force_visibility` outside of related
        models because it will create a new queryset.

        Args:
            force_visibility: Force a deletion visibility. (default: {None})
        """
        if force_visibility is not None:
            self._safedelete_force_visibility = force_visibility
        return super(SafeDeleteQueryset, self).all()

    def create(self, **kwargs):
        """
        When we create a new object we need to check the FK fields to make sure we are not linking to a soft-deleted
        record.  We only need to worry about the case where it is a FK id passed in (not an FK model instance) because
        selecting soft-deleted model instances should have already been taken care of.
        """
        if not getattr(settings, 'SAFE_DELETE_ALLOW_FK_TO_SOFT_DELETED_OBJECTS', True):
            fk_fields = [
                field for field in self.model._meta.fields
                if isinstance(field, ForeignKey) and self.get_field_name_as_id(field) in kwargs
            ]

            for field in fk_fields:
                kwarg_key = self.get_field_name_as_id(field)
                if field.related_model.deleted_objects.filter(pk=kwargs[kwarg_key]).exists():
                    raise SafeDeleteIntegrityError("The related {} object with pk {} has been soft-deleted".format(
                        str(field.related_model), kwargs[kwarg_key]
                    ))

        return super(SafeDeleteQueryset, self).create(**kwargs)

    @staticmethod
    def get_field_name_as_id(field):
        return "_".join([field.name, "id"])

    def _check_field_filter(self, **kwargs):
        """Check if the visibility for DELETED_VISIBLE_BY_FIELD needs t be put into effect.

        DELETED_VISIBLE_BY_FIELD is a temporary visibility flag that changes
        to DELETED_VISIBLE once asked for the named parameter defined in
        `_safedelete_force_visibility`. When evaluating the queryset, it will
        then filter on all models.
        """
        if self._safedelete_visibility == DELETED_VISIBLE_BY_FIELD \
                and self._safedelete_visibility_field in kwargs:
            self._safedelete_force_visibility = DELETED_VISIBLE

    def filter(self, *args, **kwargs):
        self._check_field_filter(**kwargs)
        return super(SafeDeleteQueryset, self).filter(*args, **kwargs)

    def get(self, *args, **kwargs):
        self._check_field_filter(**kwargs)
        return super(SafeDeleteQueryset, self).get(*args, **kwargs)

    def _filter_visibility(self):
        """Add deleted filters to the current QuerySet.

        Unlike QuerySet.filter, this does not return a clone.
        This is because QuerySet._fetch_all cannot work with a clone.
        """
        force_visibility = getattr(self, '_safedelete_force_visibility', None)
        visibility = force_visibility \
            if force_visibility is not None \
            else self._safedelete_visibility
        if not self._safedelete_filter_applied and \
           visibility in (DELETED_INVISIBLE, DELETED_VISIBLE_BY_FIELD, DELETED_ONLY_VISIBLE):
            assert self.query.can_filter(), \
                "Cannot filter a query once a slice has been taken."

            # Add a query manually, QuerySet.filter returns a clone.
            # QuerySet._fetch_all cannot work with clones.
            if visibility in [DELETED_INVISIBLE, DELETED_VISIBLE_BY_FIELD]:
                self.query.add_q(Q(deleted=DEFAULT_DELETED))
            else:
                self.query.add_q(~Q(deleted=DEFAULT_DELETED))

            self._safedelete_filter_applied = True

    @staticmethod
    def filter_visibility_sub_queryset(sub_queryset):
        """Add deleted filters to the subquery QuerySet.

        Unlike QuerySet.filter, this does not return a clone.
        This is because QuerySet._fetch_all cannot work with a clone.
        """
        force_visibility = getattr(sub_queryset, '_safedelete_force_visibility', None)
        visibility = force_visibility \
            if force_visibility is not None \
            else sub_queryset._safedelete_visibility
        if not sub_queryset._safedelete_filter_applied and \
           visibility in (DELETED_INVISIBLE, DELETED_VISIBLE_BY_FIELD, DELETED_ONLY_VISIBLE):
            assert sub_queryset.query.can_filter(), \
                "Cannot filter a query once a slice has been taken."
            if visibility in (DELETED_INVISIBLE, DELETED_VISIBLE_BY_FIELD):
                sub_queryset.query.add_q(Q(deleted=DEFAULT_DELETED))
            else:
                sub_queryset.query.add_q(~Q(deleted=DEFAULT_DELETED))

            sub_queryset._safedelete_filter_applied = True

    def _filter_or_exclude(self, negate, *args, **kwargs):
        """
        Here we have to catch any queries passed which are a QuerySet and add a WHERE `model`.`deleted`
        in the sql to filter out any objects that have been soft deleted. These get passed in as kwargs
        so we have to loop through all and check to see if they are a QuerySet class instance
        """
        for _, value in kwargs.items():
            if isinstance(value, SafeDeleteQueryset):
                self.__class__.filter_visibility_sub_queryset(value)
        clone = super(SafeDeleteQueryset, self)._filter_or_exclude(negate, *args, **kwargs)
        return clone

    def __getitem__(self, key):
        """
        Override __getitem__ just before it hits the original queryset
        to apply the filter visibility method.
        """
        self._filter_visibility()
        return super(SafeDeleteQueryset, self).__getitem__(key)

    def __getattribute__(self, name):
        """Methods that do not return a QuerySet should call ``_filter_visibility`` first."""
        attr = object.__getattribute__(self, name)
        # These methods evaluate the queryset and therefore need to filter the
        # visiblity set.
        evaluation_methods = (
            '_fetch_all', 'count', 'exists', 'aggregate', 'update', '_update',
            'delete', 'undelete', 'iterator', 'first', 'last', 'latest', 'earliest'
        )
        if hasattr(attr, '__call__') and name in evaluation_methods:
            def decorator(*args, **kwargs):
                self._filter_visibility()
                return attr(*args, **kwargs)
            return decorator
        return attr

    def _clone(self, klass=None, **kwargs):
        """Called by django when cloning a QuerySet."""
        if LooseVersion(django.get_version()) < LooseVersion('1.9'):
            clone = super(SafeDeleteQueryset, self)._clone(klass, **kwargs)
        else:
            clone = super(SafeDeleteQueryset, self)._clone(**kwargs)
        clone._safedelete_visibility = self._safedelete_visibility
        clone._safedelete_visibility_field = self._safedelete_visibility_field
        clone._safedelete_filter_applied = self._safedelete_filter_applied
        if hasattr(self, '_safedelete_force_visibility'):
            clone._safedelete_force_visibility = self._safedelete_force_visibility
        return clone
