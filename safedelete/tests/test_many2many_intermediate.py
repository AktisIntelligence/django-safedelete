"""These test uses models for django"s example for extra fields on many to many
relationships
"""
from django.db import models

from .testcase import SafeDeleteTestCase
from ..config import SOFT_DELETE_CASCADE
from ..fields import SafeDeleteManyToManyField
from ..models import SafeDeleteModel


class Artist(models.Model):
    name = models.CharField(max_length=128)


class Group(models.Model):
    name = models.CharField(max_length=128)
    members = SafeDeleteManyToManyField(Artist, through="Membership")


# Note: this model is safe deletable
class Membership(SafeDeleteModel):
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    invite_reason = models.CharField(max_length=64)


class ManyToManyIntermediateTestCase(SafeDeleteTestCase):

    def test_many_to_many_with_intermediate(self):
        """
        Test that when deleting a through field the related queryset do not contain the deleted relationship.
        """
        artist = Artist.objects.create(name="Great singer")
        group = Group.objects.create(name="Cool band")

        # can't use group.members.add() with intermediate model
        membership = Membership.objects.create(
            artist=artist,
            group=group,
            invite_reason="Need a new drummer"
        )

        # group members visible now
        self.assertEqual(group.members.count(), 1)

        # soft-delete intermediate instance
        # so link should be invisible
        membership.delete()
        self.assertEqual(Membership.objects.deleted_only().count(), 1)

        self.assertEqual(group.members.count(), 0)
        self.assertEqual(artist.group_set.count(), 0)

    def test_many_to_many_prefetch_related(self):
        """
        Test whether prefetch_related works as expected.
        """
        artist = Artist.objects.create(name="Great singer")
        group = Group.objects.create(name="Cool band")

        membership = Membership.objects.create(
            artist=artist,
            group=group,
            invite_reason="Need a new drummer"
        )

        membership.delete()

        query = Group.objects.filter(id=group.id).prefetch_related("members")
        self.assertEqual(
            query[0].members.count(),
            0
        )


class Person(SafeDeleteModel):
    _safedelete_policy = SOFT_DELETE_CASCADE
    children = SafeDeleteManyToManyField(
        "Person",
        through="Parentship",
        through_fields=("parent", "child"),
        symmetrical=False,
    )


class Parentship(SafeDeleteModel):
    _safedelete_policy = SOFT_DELETE_CASCADE
    parent = models.ForeignKey("Person", on_delete=models.CASCADE, related_name="child")
    child = models.ForeignKey("Person", on_delete=models.CASCADE, related_name="parent")


class ManyToManyWithThroughModelTestCase(SafeDeleteTestCase):

    def test_through_model_cascade_delete(self):
        """
        Test that when deleting one of the objects which the through model links, the relationship object is deleted too
        """
        dad = Person.objects.create()
        son = Person.objects.create()
        Parentship.objects.create(parent=dad, child=son)
        self.assertEqual(Person.objects.count(), 2)
        self.assertEqual(Parentship.objects.count(), 1)
        self.assertEqual(dad.children.count(), 1)
        self.assertEqual(dad.child.count(), 1)
        self.assertEqual(dad.parent.count(), 0)
        self.assertEqual(son.children.count(), 0)
        self.assertEqual(son.child.count(), 0)
        self.assertEqual(son.parent.count(), 1)
        son.delete()
        self.assertEqual(Person.objects.count(), 1)
        self.assertEqual(Parentship.objects.count(), 0)
        self.assertEqual(dad.children.count(), 0)
        self.assertEqual(dad.child.count(), 0)
        self.assertEqual(dad.parent.count(), 0)

    def test_through_model_delete(self):
        """
        Test that when deleting the through model, the linked objects don't get deleted
        """
        dad = Person.objects.create()
        son = Person.objects.create()
        family = Parentship.objects.create(parent=dad, child=son)
        self.assertEqual(Person.objects.count(), 2)
        self.assertEqual(Parentship.objects.count(), 1)
        self.assertEqual(dad.children.count(), 1)
        self.assertEqual(dad.child.count(), 1)
        self.assertEqual(dad.parent.count(), 0)
        self.assertEqual(son.children.count(), 0)
        self.assertEqual(son.child.count(), 0)
        self.assertEqual(son.parent.count(), 1)
        family.delete()
        self.assertEqual(Person.objects.count(), 2)
        self.assertEqual(Parentship.objects.count(), 0)
        self.assertEqual(dad.children.count(), 0)
        self.assertEqual(dad.child.count(), 0)
        self.assertEqual(dad.parent.count(), 0)
        self.assertEqual(son.children.count(), 0)
        self.assertEqual(son.child.count(), 0)
        self.assertEqual(son.parent.count(), 0)

    def test_through_model_cascade_delete_qs(self):
        """
        Test that when deleting one of the objects which the through model links, the relationship object is deleted too
        """
        dad = Person.objects.create()
        son = Person.objects.create()
        Parentship.objects.create(parent=dad, child=son)
        self.assertEqual(Person.objects.count(), 2)
        self.assertEqual(Parentship.objects.count(), 1)
        self.assertEqual(dad.children.count(), 1)
        self.assertEqual(dad.child.count(), 1)
        self.assertEqual(dad.parent.count(), 0)
        self.assertEqual(son.children.count(), 0)
        self.assertEqual(son.child.count(), 0)
        self.assertEqual(son.parent.count(), 1)
        Person.objects.filter(pk=son.pk).delete()
        self.assertEqual(Person.objects.count(), 1)
        self.assertEqual(Parentship.objects.count(), 0)
        self.assertEqual(dad.children.count(), 0)
        self.assertEqual(dad.child.count(), 0)
        self.assertEqual(dad.parent.count(), 0)

    def test_through_model_delete_qs(self):
        """
        Test that when deleting the through model, the linked objects don't get deleted
        but this time using a queryset delete.
        """
        dad = Person.objects.create()
        son = Person.objects.create()
        family = Parentship.objects.create(parent=dad, child=son)
        self.assertEqual(Person.objects.count(), 2)
        self.assertEqual(Parentship.objects.count(), 1)
        self.assertEqual(dad.children.count(), 1)
        self.assertEqual(dad.child.count(), 1)
        self.assertEqual(dad.parent.count(), 0)
        self.assertEqual(son.children.count(), 0)
        self.assertEqual(son.child.count(), 0)
        self.assertEqual(son.parent.count(), 1)
        Parentship.objects.filter(pk=family.pk).delete()
        self.assertEqual(Person.objects.count(), 2)
        self.assertEqual(Parentship.objects.count(), 0)
        self.assertEqual(dad.children.count(), 0)
        self.assertEqual(dad.child.count(), 0)
        self.assertEqual(dad.parent.count(), 0)
        self.assertEqual(son.children.count(), 0)
        self.assertEqual(son.child.count(), 0)
        self.assertEqual(son.parent.count(), 0)

    def test_through_model_delete_qs_numqueries(self):
        """
        Test that when deleting the through model, the linked objects don't get deleted
        but this time using a queryset delete.
        """
        dad = Person.objects.create()
        mom = Person.objects.create()
        adoptive_dad = Person.objects.create()
        adoptive_mom = Person.objects.create()
        son = Person.objects.create()
        daughter = Person.objects.create()
        baby = Person.objects.create()
        Parentship.objects.create(parent=dad, child=son)
        Parentship.objects.create(parent=dad, child=daughter)
        Parentship.objects.create(parent=mom, child=son)
        Parentship.objects.create(parent=mom, child=daughter)
        Parentship.objects.create(parent=adoptive_dad, child=son)
        Parentship.objects.create(parent=adoptive_dad, child=daughter)
        Parentship.objects.create(parent=adoptive_mom, child=son)
        Parentship.objects.create(parent=adoptive_mom, child=daughter)
        Parentship.objects.create(parent=adoptive_dad, child=baby)
        Parentship.objects.create(parent=adoptive_mom, child=baby)
        Person.objects.filter(pk__in=[adoptive_mom.pk, adoptive_dad.pk]).delete()
