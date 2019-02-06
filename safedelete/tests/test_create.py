try:
    from unittest import mock
except ImportError:
    import mock

from django.db import models, IntegrityError
from django.test import override_settings, TransactionTestCase

from ..config import SOFT_DELETE_CASCADE
from ..models import SafeDeleteModel
from ..queryset import SafeDeleteIntegrityError


class Endangered(SafeDeleteModel):
    _safedelete_policy = SOFT_DELETE_CASCADE

    key = models.CharField(max_length=2, db_index=True, primary_key=True)
    value = models.CharField(max_length=24)


class Genus(SafeDeleteModel):
    _safedelete_policy = SOFT_DELETE_CASCADE

    name = models.TextField()


class Species(SafeDeleteModel):
    _safedelete_policy = SOFT_DELETE_CASCADE

    name = models.TextField()
    genus = models.ForeignKey(Genus, on_delete=models.CASCADE)
    endangered = models.ForeignKey(Endangered, on_delete=models.CASCADE, null=True)


class CreateTestCase(TransactionTestCase):
    """
    Need to use TransactionTestCase so FK constraints are checked and not deferred.
    """

    def setUp(self):
        Endangered.objects.create(key="VU", value="Vunerable")
        Endangered.objects.create(key="LC", value="Least Concern")

        self.panthera = Genus.objects.create(name="Panthera")
        self.lynx = Genus.objects.create(name="Lynx")
        self.lynx.delete()

    @override_settings(SAFE_DELETE_ALLOW_FK_TO_SOFT_DELETED_OBJECTS=False)
    def test_can_create_with_fk(self):
        """
        Should be able to create a record that fks to an existing record.
        """
        genus_id = self.panthera.id

        lion = Species.objects.create(name="Lion", genus_id=genus_id, endangered_id="VU")
        self.assertTrue(isinstance(lion, Species))

    @override_settings(SAFE_DELETE_ALLOW_FK_TO_SOFT_DELETED_OBJECTS=False)
    def test_cannot_create_with_nonexistant_fk(self):
        """
        Make sure we haven't broken the existing functionality: should NOT be able to fk to a non-existent record.
        """
        nonexistent_genus_id = Genus.objects.latest("id").id + 10000

        with self.assertRaises(IntegrityError):
            Species.objects.create(name="Dog", genus_id=nonexistent_genus_id)
        self.assertFalse(Species.objects.filter(name="Dog").exists())

    @override_settings(SAFE_DELETE_ALLOW_FK_TO_SOFT_DELETED_OBJECTS=True)
    def test_can_create_with_deleted_fk(self):
        """
        If the setting SAFE_DELETE_ALLOW_FK_TO_SOFT_DELETED_OBJECTS is True then we can fk to a soft-deleted record.
        """
        genus_id = self.lynx.id

        eurasian_lynx = Species.objects.create(name="Eurasian Lynx", genus_id=genus_id)
        self.assertTrue(isinstance(eurasian_lynx, Species))

    @override_settings(SAFE_DELETE_ALLOW_FK_TO_SOFT_DELETED_OBJECTS=False)
    def test_cannot_create_with_deleted_fk(self):
        """
        If the setting SAFE_DELETE_ALLOW_FK_TO_SOFT_DELETED_OBJECTS is False then we cannot fk to a soft-deleted record.
        """
        genus_id = self.lynx.id

        with self.assertRaises(SafeDeleteIntegrityError) as context:
            Species.objects.create(name="Bobcat", genus_id=genus_id, endangered_id="LC")
        self.assertEqual(
            "The related <class 'safedelete.tests.test_create.Genus'> object with pk {} has been soft-deleted"
            .format(genus_id), str(context.exception)
        )
        self.assertFalse(Species.objects.filter(name="Bobcat").exists())
