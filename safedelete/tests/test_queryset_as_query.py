from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import F, Q, Avg, Max, Subquery

from ..managers import SafeDeleteManager, SafeDeleteQueryset
from ..models import SafeDeleteModel, SOFT_DELETE_CASCADE
from .testcase import SafeDeleteTestCase

import random


class BaseModel(SafeDeleteModel):
    _safedelete_policy = SOFT_DELETE_CASCADE

    class Meta:
        abstract = True


class Region(BaseModel):
    CONTINENTS = (
        ("EUROPE", "Europe"),
        ("NORTH AMERICA", "North America"),
        ("SOUTH AMERICA", "South America"),
        ("AFRICA", "Africa"),
        ("ASIA", "Asia"),
        ("AUSTRALIA", "Australia"),
        ("ANTARCTICA", "Antarctica")
    )
    name = models.CharField(
        max_length=150,
        choices=CONTINENTS
    )

    def __str__(self):
        return "{}".format(self.name)


class Country(BaseModel):
    name = models.CharField(
        max_length=150
    )
    region = models.ForeignKey(
        Region,
        on_delete=models.CASCADE,
        null=False
    )

    def __str__(self):
        return "{}, {}".format(self.name, self.region.name)


class Flavour(BaseModel):
    name = models.CharField(
        max_length=100
    )

    def __str__(self):
        return "{}, id: {}".format(self.name, self.pk)


class Coffee(BaseModel):
    flavours = models.ManyToManyField(
        Flavour
    )
    in_stock = models.BooleanField(
        default=False,
        null=False
    )
    country = models.ForeignKey(
        Country,
        on_delete=models.DO_NOTHING
    )
    quantity = models.IntegerField(
        default=0,
        null=False
    )
    suppliers = models.IntegerField(
        default=0,
        null=False
    )
    customers = models.IntegerField(
        default=0,
        null=False
    )

    def __str__(self):
        return "{}, id: {}".format(self.country.name, self.pk)


class CustomQuerySetTestCase(SafeDeleteTestCase):
    """
    Tests to check that methods to exclude deleted entries from being included
    when a QuerySet is passed as a query, work as expected and don't have any
    unexpected behaviour
    """

    def create_entries(self):
        """
        Create entries for all models
        """
        self.SA = [
            "Brazil",
            "Colombia",
            "Guatemala",
            "Honduras",
            "Peru",
            "Costa Rica"
        ]

        self.AF = [
            "Ethiopia",
            "Uganda",
            "Tanzania",
            "Cameroon",
            "Kenya",
            "Ivory Coast"
        ]

        self.EU = ["Spain"]

        self.AS = [
            "Thailand",
            "Vietnam",
            "Indonesia",
            "India",
            "Laos"
        ]

        self.AU = ["Papua New Guinea"]

        self.NA = [
            "Cuba",
            "Mexico",
            "Honduras"
        ]

        flavours = [
            "berries",
            "biscuit",
            "caramel",
            "fruity",
            "nutty",
            "chocolatey",
            "spicy",
            "citrus",
            "smooth",
            "velvety",
            "acidic",
            "bitter"
        ]

        self.country_by_region = {
            "EUROPE": self.EU,
            "NORTH AMERICA": self.NA,
            "SOUTH AMERICA": self.SA,
            "AFRICA": self.AF,
            "ASIA": self.AS,
            "AUSTRALIA": self.AU
        }

        for region in Region.CONTINENTS:
            Region.objects.create(
                name=region[0]
            )
        # Check all regions were created
        self.assertEqual(Region.objects.count(), 7)

        for flavour in flavours:
            Flavour.objects.create(
                name=flavour
            )

        for region, countries in self.country_by_region.items():
            region = Region.objects.get(name=region)
            for country in countries:
                country = Country.objects.create(
                    region=region,
                    name=country
                )
                # Create coffees with random descriptions for the flavour & random quantities
                coffee = Coffee.objects.create(
                    country=country,
                    in_stock=True if random.randint(0, 1) == 1 else False,
                    quantity=random.randrange(0, 5000, 100),
                    suppliers=random.randint(1, 10),
                    customers=random.randint(1, 10)
                )
                length = random.randint(2, 5)
                for pk in range(1, length):
                    coffee.flavours.add(Flavour.objects.get(pk=pk))

        # Check we have the expected number of Coffees and Countries
        self.expected_total = sum(list(map(lambda x: len(x), self.country_by_region.values())))
        self.assertEqual(Country.objects.count(), self.expected_total)
        self.assertEqual(Coffee.objects.count(), self.expected_total)

    def test_simple_filter_with_subquery(self):
        # Create all entries
        self.create_entries()

        # Check filter on subquery composed of subquery to get all coffees by region & check the
        # count is as expected
        with self.assertNumQueries(1):
            sa_coffees = Coffee.objects.filter(
                country__in=Country.objects.filter(
                    region=Region.objects.get(name="SOUTH AMERICA")
                )
            )
        self.assertEqual(sa_coffees.count(), len(self.SA))

        # Check before deleting country Brazil, that we have 1 coffee associated
        with self.assertNumQueries(1):
            brazillian_coffees = Coffee.objects.filter(country__in=Country.objects.filter(name="Brazil"))
            self.assertEqual(brazillian_coffees.count(), 1)

        # Delete a country so that we can now query to see if any coffees are related to that country
        # when using a queryset as a query param
        Country.objects.get(name="Brazil").delete()

        # Check filtering for coffees from Brazil, total should not change for total coffees but countries
        # should decrease by one and the filter by country="Brazil", should now return 0 as count
        with self.assertNumQueries(3):
            brazillian_coffees = Coffee.objects.filter(country__in=Country.objects.filter(name="Brazil"))
            self.assertEqual(brazillian_coffees.count(), 0)
            self.assertEqual(Coffee.objects.count(), self.expected_total)
            self.assertEqual(Country.objects.count(), self.expected_total - 1)

        # Check filter on subquery composed of QuerySet to get all coffees by region & check the
        # count has decreased by one
        with self.assertNumQueries(1):
            sa_coffees = Coffee.objects.filter(
                country__in=Country.objects.filter(
                    region__name="SOUTH AMERICA"
                )
            )
            self.assertEqual(sa_coffees.count(), len(self.SA) - 1)

        # Check that forcing visibility to show deleted entries that we now find the coffee associated
        # with the deleted country
        with self.assertNumQueries(3):
            brazillian_coffees = Coffee.objects.filter(
                country__in=Country.objects.all_with_deleted().filter(name="Brazil")
            )
            self.assertEqual(brazillian_coffees.count(), 1)
            self.assertEqual(Country.objects.all_with_deleted().count(), self.expected_total)
            sa_coffees = Coffee.objects.filter(
                country__in=Country.objects.all_with_deleted().filter(
                    region__name="SOUTH AMERICA"
                )
            )
            self.assertEqual(sa_coffees.count(), len(self.SA))

    def test_simple_exclude_with_subquery(self):
        # Create all entries
        self.create_entries()

        # Check exclude on subquery composed of subquery to get all coffees by region & check the
        # count is as expected
        with self.assertNumQueries(1):
            other_coffees = Coffee.objects.exclude(
                country__in=Country.objects.filter(
                    region__name="ASIA"
                )
            )
            self.assertEqual(other_coffees.count(), self.expected_total - len(self.AS))

        # Check delete the region ASIA & this should delete all countries in this region
        Region.objects.get(name="ASIA").delete()
        with self.assertNumQueries(1):
            self.assertEqual(Country.objects.count(), self.expected_total - len(self.AS))

        # Check using excluding the coffees from South America doesn't include the coffees
        # from the deleted Asis region
        with self.assertNumQueries(1):
            non_SA_coffees = Coffee.objects.filter(
                country__in=Country.objects.exclude(
                    region__name="SOUTH AMERICA"
                )
            ).count()
        self.assertEqual(non_SA_coffees, self.expected_total - len(self.AS) - len(self.SA))

        # Check that forcing visibility to show deleted entries that we now find the coffee associated
        # with the region
        with self.assertNumQueries(1):
            non_SA_coffees = Coffee.objects.filter(
                country__in=Country.objects.all_with_deleted().exclude(
                    region__name="SOUTH AMERICA"
                )
            )
            self.assertEqual(non_SA_coffees.count(), self.expected_total - len(self.SA))

    def test_simple_query_using_F(self):
        # Create all entries
        self.create_entries()

        coffee_performances = Coffee.objects.annotate(
            performance=F("customers") - F("suppliers")
        )
        with self.assertNumQueries(2):
            best_coffee = Coffee.objects.filter(country__in=Country.objects.filter(region__name="AFRICA")).first()
            best_coffee.customers = 20
            best_coffee.save()

        best_coffee_score = best_coffee.customers - best_coffee.suppliers

        with self.assertNumQueries(1):
            african_country_ids = list(Country.objects.filter(region__name="AFRICA").values_list("pk", flat=True))

        with self.assertNumQueries(1):
            good_sellers_before = coffee_performances.filter(
                country__in=african_country_ids,
                performance__gt=0
            ).count()

        with self.assertNumQueries(1):
            max_score = coffee_performances.all().aggregate(Max("performance"))["performance__max"]
        self.assertEqual(max_score, best_coffee_score)

        # Delete the best coffee
        with self.assertNumQueries(len(self.AF)):
            coffee_performances.filter(
                country__in=african_country_ids,
                performance=max_score
            ).delete()

        coffee_performances = Coffee.objects.annotate(
            performance=F("customers") - F("suppliers")
        )
        with self.assertNumQueries(1):
            good_sellers_after = coffee_performances.filter(
                country__in=african_country_ids,
                performance__gt=0
            ).count()

        # Check the number has decreased by one
        self.assertEqual(good_sellers_after, good_sellers_before - 1)

        coffee_performances = Coffee.objects.all_with_deleted().annotate(
            performance=F("customers") - F("suppliers")
        )

        good_sellers_after_inc_deleted = coffee_performances.filter(
            country__in=african_country_ids,
            performance__gt=0
        )
        # Check the it's now visible when calling filter on the all_with_deleted queryset
        self.assertEqual(good_sellers_after_inc_deleted.count(), good_sellers_before)

    def test_using_subquery(self):
        # Create all entries
        self.create_entries()
        regions = Region.objects.all()[:3]

        countries = Country.objects.filter(region__in=Subquery(regions.values("pk")))

        country_count = 0
        for region in regions:
            country_count += len(self.country_by_region[region.name])
        self.assertEqual(countries.count(), country_count)

        Region.objects.get(name="NORTH AMERICA").delete()
        with self.assertNumQueries(2):
            regions = Region.objects.all()
            self.assertEqual(regions.count(), 6)
            self.assertNotIn("NORTH AMERICA", regions.values_list("name", flat=True))

        with self.assertNumQueries(1):
            countries = Country.objects.filter(region__in=Subquery(regions.values("pk")))
            self.assertEqual(countries.count(), self.expected_total - len(self.NA))

        with self.assertNumQueries(1):
            regions = Region.objects.all_with_deleted()
            countries_inc_deleted = Country.objects.all_with_deleted().filter(region__in=Subquery(regions.values("pk")))
            self.assertEqual(countries_inc_deleted.count(), self.expected_total)

    def test_using_Q(self):
        # Create all entries
        self.create_entries()

        n_or_c_coffees = Coffee.objects.filter(
            Q(flavours__name__in="nutty") | Q(flavours__name__in="chocolatey")
        )

        with self.assertNumQueries(1):
            no_n_or_c_coffees_from_SA = n_or_c_coffees.filter(
                country__in=Country.objects.filter(region__name="SOUTH AMERICA")
            ).count()

        with self.assertNumQueries(1):
            no_n_or_c_coffees = n_or_c_coffees.count()
        # delete all countries in region SOUTH AMERICA
        Country.objects.filter(region__name="SOUTH AMERICA").delete()

        with self.assertNumQueries(1):
            no_n_or_c_coffees_excluding_sa = Coffee.objects.filter(
                Q(flavours__name__in="nutty") | Q(flavours__name__in="chocolatey")
            ).count()

        self.assertEqual(no_n_or_c_coffees_excluding_sa, no_n_or_c_coffees - no_n_or_c_coffees_from_SA)

        with self.assertNumQueries(1):
            no_sa_coffees = Coffee.objects.filter(
                country__in=(Country.objects.filter(region__name="SOUTH AMERICA"))
            ).count()

        self.assertEqual(no_sa_coffees, 0)
