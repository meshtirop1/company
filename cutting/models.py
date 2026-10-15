from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class CuttingStyle(models.TextChoices):
    """The two ways a fish is cut. 통포 is the bigger job, so it pays more."""
    TONGPO = 'tongpo', '통포'
    TONGHALBOK = 'tonghalbok', '통할복'


class Cutter(models.Model):
    """A member of the cutting crew.

    Cutters never log in: they exist only as records that the supervisor enters work against.
    """
    name = models.CharField(max_length=100)
    note = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(Lower('name'), name='cutting_cutter_name_unique_ci'),
        ]

    def __str__(self):
        return self.name


class PriceItem(models.Model):
    """One line of the price list: a cutting style at a fish size, e.g. 통포 10~11."""
    style = models.CharField(max_length=20, choices=CuttingStyle.choices)
    size = models.CharField(max_length=20)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['style', 'sort_order', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['style', 'size'], name='cutting_priceitem_style_size_unique'),
        ]

    def __str__(self):
        return f'{self.get_style_display()} {self.size}'

    def rate_on(self, day):
        """The rate in force on `day`: the latest one starting on or before it, or None.

        Filters in Python so a prefetched `rates` set is reused instead of re-queried.
        """
        eligible = [rate for rate in self.rates.all() if rate.effective_from <= day]
        return max(eligible, key=lambda rate: rate.effective_from, default=None)


class PriceRate(models.Model):
    """The per-box price of a PriceItem from `effective_from` until the next rate starts.

    Work records copy the price at the moment they are saved, so adding or changing a
    rate never alters pay that has already been recorded.
    """
    item = models.ForeignKey(PriceItem, on_delete=models.CASCADE, related_name='rates')
    unit_price = models.DecimalField(max_digits=10, decimal_places=0)
    effective_from = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['item', '-effective_from']
        constraints = [
            models.UniqueConstraint(fields=['item', 'effective_from'], name='cutting_pricerate_item_date_unique'),
            models.CheckConstraint(condition=Q(unit_price__gt=0), name='cutting_pricerate_price_positive'),
        ]

    def __str__(self):
        return f'{self.item}: ₩{self.unit_price:,.0f} from {self.effective_from}'
