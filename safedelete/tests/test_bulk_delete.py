from django.db import models
from django.test import TestCase

from ..config import SOFT_DELETE_CASCADE
from ..models import SafeDeleteModel


class Reference(SafeDeleteModel):
    _safedelete_policy = SOFT_DELETE_CASCADE


class Document1(SafeDeleteModel):
    _safedelete_policy = SOFT_DELETE_CASCADE
    reference = models.ForeignKey("Reference", blank=True, null=True, on_delete=models.SET_NULL)


class Document2(SafeDeleteModel):
    _safedelete_policy = SOFT_DELETE_CASCADE
    reference = models.ForeignKey("Reference", blank=True, null=True, on_delete=models.SET_NULL)


class BulkDeleteTestCase(TestCase):

    def setUp(self):
        """
        Create the dataset used by each test
        """
        self.refs = [
            Reference.objects.create(),
            Reference.objects.create(),
            Reference.objects.create(),
        ]
        self.docs = [
            Document1.objects.create(reference=self.refs[0]),
            Document1.objects.create(),
            Document2.objects.create(reference=self.refs[1]),
            Document2.objects.create(),
            Document2.objects.create(reference=self.refs[2]),
        ]

    def test_delete_one(self):
        """
        Delete a model with SET_NULL relationships and check the number of queries each time.
        """
        self.assertEqual(Reference.objects.count(), 3)
        self.assertEqual(Document1.objects.count(), 2)
        self.assertEqual(Document2.objects.count(), 3)
        self.assertEqual(Document1.objects.filter(reference__isnull=False).count(), 1)
        self.assertEqual(Document2.objects.filter(reference__isnull=False).count(), 2)
        self.assertEqual(Reference.deleted_objects.count(), 0)
        self.assertEqual(Document1.deleted_objects.count(), 0)
        self.assertEqual(Document2.deleted_objects.count(), 0)

        with self.assertNumQueries(3):
            # Delete the first document, should not delete any references
            # The 3 queries are:
            #   - 2 for the transaction (savepoint and release savepoint)
            #   - 1 for the actual delete
            self.docs[0].delete()

        self.assertEqual(Reference.objects.count(), 3)
        self.assertEqual(Document1.objects.count(), 1)
        self.assertEqual(Document2.objects.count(), 3)
        self.assertEqual(Document1.objects.filter(reference__isnull=False).count(), 0)
        self.assertEqual(Document2.objects.filter(reference__isnull=False).count(), 2)

        self.assertEqual(Reference.deleted_objects.count(), 0)
        self.assertEqual(Document1.deleted_objects.count(), 1)
        self.assertEqual(Document2.deleted_objects.count(), 0)

        with self.assertNumQueries(8):
            # Delete the second reference, should not delete any document but should set the reference in the
            # corresponding document to None.
            # The 8 queries are:
            #   - 2 for the transaction (savepoint and release savepoint)
            #   - 1 for the actual delete
            #   - 2 for the select on documents to check which ones need to be cascade deleted
            #   - 2 for the select on documents to check which ones need to be updated (for the SET_NULL)
            #   - 1 for the update of the reference to None
            # The 2 times request to get the objects to cascade delete and then update should be merged to be honest
            # but they are left like that for now for sake of simplicity
            self.refs[1].delete()

        self.assertIsNone(Document2.objects.get(id=self.docs[2].id).reference)
        self.assertEqual(Reference.objects.count(), 2)
        self.assertEqual(Document1.objects.count(), 1)
        self.assertEqual(Document2.objects.count(), 3)
        self.assertEqual(Document1.objects.filter(reference__isnull=False).count(), 0)
        self.assertEqual(Document2.objects.filter(reference__isnull=False).count(), 1)

        self.assertEqual(Reference.deleted_objects.count(), 1)
        self.assertEqual(Document1.deleted_objects.count(), 1)
        self.assertEqual(Document2.deleted_objects.count(), 0)

        with self.assertNumQueries(11):
            # Delete the second reference, should not delete any document but should set the reference in the
            # corresponding document to None.
            # The 11 queries are:
            #   - 8 for the reference delete
            #   - 3 for the document delete
            self.refs[2].delete()
            self.docs[4].delete()

        self.assertEqual(Reference.objects.count(), 1)
        self.assertEqual(Document1.objects.count(), 1)
        self.assertEqual(Document2.objects.count(), 2)
        self.assertEqual(Document1.objects.filter(reference__isnull=False).count(), 0)
        self.assertEqual(Document2.objects.filter(reference__isnull=False).count(), 0)

        self.assertEqual(Reference.deleted_objects.count(), 2)
        self.assertEqual(Document1.deleted_objects.count(), 1)
        self.assertEqual(Document2.deleted_objects.count(), 1)

    def test_delete_bulk_all_references(self):
        """
        Test the bulk delete (aka query set delete). It should significantly reduce the number of queries compare to an
        iterative delete.
        """
        self.assertEqual(Reference.objects.count(), 3)
        self.assertEqual(Document1.objects.count(), 2)
        self.assertEqual(Document2.objects.count(), 3)
        self.assertEqual(Document1.objects.filter(reference__isnull=False).count(), 1)
        self.assertEqual(Document2.objects.filter(reference__isnull=False).count(), 2)
        self.assertEqual(Reference.deleted_objects.count(), 0)
        self.assertEqual(Document1.deleted_objects.count(), 0)
        self.assertEqual(Document2.deleted_objects.count(), 0)

        with self.assertNumQueries(13):
            # Delete all the references should not delete any document but should set the reference in the
            # corresponding documents to None.
            # The 13 queries are:
            #   - 4 for the transaction (savepoint and release savepoint)s
            #   - 1 for select all the references that are not deleted
            #   - 1 for delete them (update the deleted field on those references)
            #   - 1 to get the count of reference we deleted for the return value of the delete method
            #   - 2 for the select on documents to check which ones need to be cascade deleted
            #   - 2 for the select on documents to check which ones need to be updated (for the SET_NULL)
            #   - 1 for the update of the reference to None
            # The 2 times request to get the objects to cascade delete and then update should be merged to be honest
            # but they are left like that for now for sake of simplicity
            Reference.objects.all().delete()

        self.assertEqual(Reference.objects.count(), 0)
        self.assertEqual(Document1.objects.count(), 2)
        self.assertEqual(Document2.objects.count(), 3)
        self.assertEqual(Document1.objects.filter(reference__isnull=False).count(), 0)
        self.assertEqual(Document2.objects.filter(reference__isnull=False).count(), 0)
        self.assertEqual(Reference.deleted_objects.count(), 3)
        self.assertEqual(Document1.deleted_objects.count(), 0)
        self.assertEqual(Document2.deleted_objects.count(), 0)

    def test_delete_bulk_all_documents_2(self):
        """
        Test the bulk delete (aka query set delete). It should significantly reduce the number of queries compare to an
        iterative delete.
        """
        self.assertEqual(Reference.objects.count(), 3)
        self.assertEqual(Document1.objects.count(), 2)
        self.assertEqual(Document2.objects.count(), 3)
        self.assertEqual(Document1.objects.filter(reference__isnull=False).count(), 1)
        self.assertEqual(Document2.objects.filter(reference__isnull=False).count(), 2)
        self.assertEqual(Reference.deleted_objects.count(), 0)
        self.assertEqual(Document1.deleted_objects.count(), 0)
        self.assertEqual(Document2.deleted_objects.count(), 0)

        with self.assertNumQueries(7):
            # Delete all the references should not delete any document but should set the reference in the
            # corresponding documents to None.
            # The 7 queries are:
            #   - 4 for the transaction (savepoint and release savepoint)s
            #   - 1 for select all the references that are not deleted
            #   - 1 for delete them (update the deleted field on those references)
            #   - 1 to get the count of reference we deleted for the return value of the delete method
            # The 2 times request to get the objects to cascade delete and then update should be merged to be honest
            # but they are left like that for now for sake of simplicity
            Document2.objects.all().delete()

        self.assertEqual(Reference.objects.count(), 3)
        self.assertEqual(Document1.objects.count(), 2)
        self.assertEqual(Document2.objects.count(), 0)
        self.assertEqual(Document1.objects.filter(reference__isnull=False).count(), 1)
        self.assertEqual(Document2.objects.filter(reference__isnull=False).count(), 0)
        self.assertEqual(Reference.deleted_objects.count(), 0)
        self.assertEqual(Document1.deleted_objects.count(), 0)
        self.assertEqual(Document2.deleted_objects.count(), 3)

    def test_delete_bulk_some_documents_2(self):
        """
        Test the bulk delete (aka query set delete). It should significantly reduce the number of queries compare to an
        iterative delete.
        """
        self.assertEqual(Reference.objects.count(), 3)
        self.assertEqual(Document1.objects.count(), 2)
        self.assertEqual(Document2.objects.count(), 3)
        self.assertEqual(Document1.objects.filter(reference__isnull=False).count(), 1)
        self.assertEqual(Document2.objects.filter(reference__isnull=False).count(), 2)
        self.assertEqual(Reference.deleted_objects.count(), 0)
        self.assertEqual(Document1.deleted_objects.count(), 0)
        self.assertEqual(Document2.deleted_objects.count(), 0)

        with self.assertNumQueries(7):
            # Delete all the references should not delete any document but should set the reference in the
            # corresponding documents to None.
            # The 7 queries are:
            #   - 4 for the transaction (savepoint and release savepoint)s
            #   - 1 for select all the references that are not deleted
            #   - 1 for delete them (update the deleted field on those references)
            #   - 1 to get the count of reference we deleted for the return value of the delete method
            # The 2 times request to get the objects to cascade delete and then update should be merged to be honest
            # but they are left like that for now for sake of simplicity
            Document2.objects.filter(id__in=[self.docs[2].id, self.docs[3].id]).delete()

        self.assertEqual(Reference.objects.count(), 3)
        self.assertEqual(Document1.objects.count(), 2)
        self.assertEqual(Document2.objects.count(), 1)
        self.assertEqual(Document1.objects.filter(reference__isnull=False).count(), 1)
        self.assertEqual(Document2.objects.filter(reference__isnull=False).count(), 1)
        self.assertEqual(Reference.deleted_objects.count(), 0)
        self.assertEqual(Document1.deleted_objects.count(), 0)
        self.assertEqual(Document2.deleted_objects.count(), 2)
