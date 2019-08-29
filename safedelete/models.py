import logging

import warnings

from django.db import models, router, transaction
from django.utils import timezone

from .config import (HARD_DELETE, HARD_DELETE_NOCASCADE, NO_DELETE,
                     SOFT_DELETE, SOFT_DELETE_CASCADE, DEFAULT_DELETED)
from .managers import (SafeDeleteAllManager, SafeDeleteDeletedManager,
                       SafeDeleteManager)
from .signals import post_softdelete, post_undelete, pre_softdelete
from .utils import can_hard_delete, concatenate_delete_returns, get_objects_to_delete, is_deleted, is_safedelete_cls,\
    perform_updates


logger = logging.getLogger(__name__)


class SafeDeleteModel(models.Model):
    """Abstract safedelete-ready model.

    .. note::
        To create your safedelete-ready models, you have to make them inherit from this model.

    :attribute deleted:
        DateTimeField set to the moment the object was deleted. Is set to
        ``1970-01-01`` if the object has not been deleted.

    :attribute _safedelete_policy: define what happens when you delete an object.
        It can be one of ``HARD_DELETE``, ``SOFT_DELETE``, ``SOFT_DELETE_CASCADE``, ``NO_DELETE`` and
        ``HARD_DELETE_NOCASCADE``.
        Defaults to ``SOFT_DELETE``.

        >>> class MyModel(SafeDeleteModel):
        ...     _safedelete_policy = SOFT_DELETE
        ...     my_field = models.TextField()
        ...
        >>> # Now you have your model (with its ``deleted`` field, and custom manager and delete method)

    :attribute objects:
        The :class:`safedelete.managers.SafeDeleteManager` that returns the non-deleted models.

    :attribute all_objects:
        The :class:`safedelete.managers.SafeDeleteAllManager` that returns the all models
        (non-deleted and soft-deleted).

    :attribute deleted_objects:
        The :class:`safedelete.managers.SafeDeleteDeletedManager` that returns the soft-deleted models.
    """

    _safedelete_policy = SOFT_DELETE

    deleted = models.DateTimeField(editable=False, default=DEFAULT_DELETED, db_index=True)

    objects = SafeDeleteManager()
    all_objects = SafeDeleteAllManager()
    deleted_objects = SafeDeleteDeletedManager()

    class Meta:
        abstract = True

    def save(self, keep_deleted=False, **kwargs):
        """
        Save an object, un-deleting it if it was deleted.

        Args:
            keep_deleted: Do not undelete the model if soft-deleted. (default: {False})
            kwargs: Passed onto :func:`save`.

        .. note::
            Undeletes soft-deleted models by default.
        """
        # undelete signal has to happen here (and not in undelete)
        # in order to catch the case where a deleted model becomes
        # implicitly undeleted on-save.  If someone manually nulls out
        # deleted, it'll bypass this logic, which I think is fine, because
        # otherwise we'd have to shadow field changes to handle that case.
        was_undeleted = False
        if not keep_deleted:
            if is_deleted(self) and self.pk:
                was_undeleted = True
            self.deleted = DEFAULT_DELETED

        super(SafeDeleteModel, self).save(**kwargs)

        if was_undeleted:
            # send undelete signal
            using = kwargs.get('using') or router.db_for_write(self.__class__, instance=self)
            post_undelete.send(sender=self.__class__, instance=self, using=using)

    def undelete(self, force_policy=None, **kwargs):
        """Undelete a soft-deleted model.

        Args:
            force_policy: Force a specific undelete policy. (default: {None})
            kwargs: Passed onto :func:`save`.

        .. note::
            Will raise a :class:`AssertionError` if the model was not soft-deleted.
        """
        with transaction.atomic():
            current_policy = force_policy or self._safedelete_policy

            assert is_deleted(self)
            self.save(keep_deleted=False, **kwargs)

            if current_policy == SOFT_DELETE_CASCADE:
                # We get all the related objects (deleted or not) and we undelete the ones that are deleted
                fast_deletes, objects_to_delete = get_objects_to_delete([self], return_deleted=True)
                for related_objects_qs in fast_deletes:
                    model = related_objects_qs.model
                    if is_safedelete_cls(model):
                        # This could be done way more efficiently as we could not go through each object save
                        # but I don't really care about undelete
                        for related in related_objects_qs.exclude(deleted=DEFAULT_DELETED):
                            related.undelete()
                for model, related_objects in objects_to_delete.items():
                    if is_safedelete_cls(model):
                        for related in related_objects:
                            if is_deleted(related):
                                related.undelete()

    @classmethod
    def _get_safelete_policy(cls, force_policy=None):
        """
        Get the delete policy to apply.
        """
        return cls._safedelete_policy if (force_policy is None) else force_policy

    def delete(self, force_policy=None, **kwargs):
        """
        Overrides Django's delete behaviour based on the model's delete policy.

        Args:
            force_policy: Force a specific delete policy. (default: {None})
            kwargs: Passed onto :func:`save` if soft deleted.
        """
        # Wrap everything in a transaction to make sure that if something fails everything gets rolled back
        delete_returns = []
        with transaction.atomic():

            current_policy = self._get_safelete_policy(force_policy=force_policy)

            if current_policy == NO_DELETE:
                # Don't do anything.
                return (0, {})

            elif current_policy == HARD_DELETE:
                # Normally hard-delete the object.
                return super(SafeDeleteModel, self).delete()

            elif current_policy == HARD_DELETE_NOCASCADE:
                # Hard-delete the object only if nothing would be deleted with it
                if not can_hard_delete(self):
                    return self.delete(force_policy=SOFT_DELETE, **kwargs)
                else:
                    return self.delete(force_policy=HARD_DELETE, **kwargs)

            elif current_policy in [SOFT_DELETE_CASCADE, SOFT_DELETE]:
                # Soft-delete the object, marking it as deleted. Don't do anything for cascade so it might lead to
                # broken foreign key relationships for the ORM (pointing to objects that virtually don't exist any more)
                self.deleted = timezone.now()
                using = kwargs.get('using') or router.db_for_write(self.__class__, instance=self)
                # send pre_softdelete signal
                pre_softdelete.send(sender=self.__class__, instance=self, using=using)
                super(SafeDeleteModel, self).save(update_fields=["deleted"])
                delete_returns.append((1, {self._meta.label: 1}))
                # send softdelete signal
                post_softdelete.send(sender=self.__class__, instance=self, using=using)

            if current_policy == SOFT_DELETE_CASCADE:
                # Soft-delete on related objects
                logger.info("Delete {} {}".format(self.__class__.__name__, self.pk))
                fast_deletes, objects_to_delete = get_objects_to_delete([self])
                for related_objects_qs in fast_deletes:
                    model = related_objects_qs.model
                    if is_safedelete_cls(model):
                        # This could be done way more efficiently as we could not go through each object delete
                        # but in case they have some custom logic in the delete it's better to do it that way
                        for related in related_objects_qs:
                            delete_returns.append(related.delete(force_policy=SOFT_DELETE, **kwargs))
                for model, related_objects in objects_to_delete.items():
                    if is_safedelete_cls(model):
                        for related in related_objects:
                            delete_returns.append(related.delete(force_policy=SOFT_DELETE, **kwargs))

                # We don't do anything if it is not a safedelete model which means that we can leave some dangling
                # objects if they are not safe delete models...

                # Do the updates that the delete implies.
                # (for example in case of a relation `on_delete=models.SET_NULL`)
                perform_updates([self])
        return concatenate_delete_returns(*delete_returns)

    @classmethod
    def has_unique_fields(cls):
        """Checks if one of the fields of this model has a unique constraint set (unique=True)

        Args:
            model: Model instance to check
        """
        for field in cls._meta.fields:
            if field._unique:
                return True
        return False

    # ------------------------------------------------------------------------------------------------------------------
    # >>> TL: We don't want to override the check as we don't want to check unique constraint against deleted object
    # >>> Instead the user have to set delete to be part of the unique_together constraint (since it needs to be checked
    # >>> at db level too)

    # We need to overwrite this check to ensure uniqueness is also checked
    # against "deleted" (but still in db) objects.
    # FIXME: Better/cleaner way ?
    # def _perform_unique_checks(self, unique_checks):
    #     errors = {}

    #     for model_class, unique_check in unique_checks:
    #         lookup_kwargs = {}
    #         for field_name in unique_check:
    #             f = self._meta.get_field(field_name)
    #             lookup_value = getattr(self, f.attname)
    #             if lookup_value is None:
    #                 continue
    #             if f.primary_key and not self._state.adding:
    #                 continue
    #             lookup_kwargs[str(field_name)] = lookup_value
    #         if len(unique_check) != len(lookup_kwargs):
    #             continue

    #         # This is the changed line
    #         if hasattr(model_class, 'all_objects'):
    #             qs = model_class.all_objects.filter(**lookup_kwargs)
    #         else:
    #             qs = model_class._default_manager.filter(**lookup_kwargs)

    #         model_class_pk = self._get_pk_val(model_class._meta)
    #         if not self._state.adding and model_class_pk is not None:
    #             qs = qs.exclude(pk=model_class_pk)
    #         if qs.exists():
    #             if len(unique_check) == 1:
    #                 key = unique_check[0]
    #             else:
    #                 key = models.base.NON_FIELD_ERRORS
    #             errors.setdefault(key, []).append(
    #                 self.unique_error_message(model_class, unique_check)
    #             )
    #     return errors
    # ------------------------------------------------------------------------------------------------------------------


class SafeDeleteMixin(SafeDeleteModel):
    """``SafeDeleteModel`` was previously named ``SafeDeleteMixin``.

    .. deprecated:: 0.4.0
        Use :class:`SafeDeleteModel` instead.
    """

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        warnings.warn('The SafeDeleteMixin class was renamed SafeDeleteModel',
                      DeprecationWarning)
        SafeDeleteModel.__init__(self, *args, **kwargs)
