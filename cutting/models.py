from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from hours_tracker.models import DeductionRate


class CuttingStyle(models.TextChoices):
    """The two ways a fish is cut. 통포 is the bigger job, so it pays more."""
    TONGPO = 'tongpo', '통포'
    TONGHALBOK = 'tonghalbok', '통할복'


class PayslipLanguage(models.TextChoices):
    SCREEN = '', 'Same as the screen'
    EN = 'en', 'English'
    KO = 'ko', '한국어'


class Cutter(models.Model):
    """A member of the cutting crew.

    Cutters never log in: they exist only as records that the supervisor enters work against.
    """
    name = models.CharField(max_length=100)
    note = models.CharField(max_length=200, blank=True)
    # The language their payslip prints in, so a mixed crew each get one they can read.
    payslip_language = models.CharField(max_length=2, choices=PayslipLanguage.choices, blank=True, default='')
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


class CutterDeduction(DeductionRate):
    """Tax and health insurance taken off a cutter's monthly pay (see hours_tracker.deductions).

    Written only through cutting/services.py, which refuses a change that would alter a
    locked month's payslips and records every change in the change log.
    """
    cutter = models.ForeignKey(Cutter, on_delete=models.CASCADE, related_name='deductions')

    class Meta(DeductionRate.Meta):
        constraints = [
            models.UniqueConstraint(fields=['cutter', 'effective_from'], name='cutting_cutterdeduction_month_unique'),
        ]

    def __str__(self):
        return f'{self.cutter} from {self.effective_from:%Y-%m}'


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


class CutBatch(models.Model):
    """One save from the entry screen: the rows a supervisor entered together.

    `token` is minted when the entry form is shown, so a double tap or a browser
    resubmit can only ever create the batch once.
    """
    work_date = models.DateField()
    token = models.UUIDField(unique=True, editable=False)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    # Kept as text too, so deleting a supervisor's account can't erase who entered the work.
    entered_by_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['work_date', 'created_at']
        indexes = [models.Index(fields=['work_date'], name='cutting_batch_date_idx')]

    def __str__(self):
        return f'{self.work_date} #{self.pk}'


class CutRecord(models.Model):
    """One cutter's boxes in a batch.

    The style, size, unit price and total are copied when the record is saved, so later
    changes to the price list never alter pay that has already been recorded.
    """
    batch = models.ForeignKey(CutBatch, on_delete=models.CASCADE, related_name='records')
    cutter = models.ForeignKey(Cutter, on_delete=models.PROTECT, related_name='records')
    item = models.ForeignKey(PriceItem, on_delete=models.PROTECT, related_name='records')
    work_date = models.DateField()
    style = models.CharField(max_length=20, choices=CuttingStyle.choices)
    size = models.CharField(max_length=20)
    boxes = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=0)
    total = models.DecimalField(max_digits=14, decimal_places=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['work_date', 'batch_id', 'pk']
        indexes = [
            models.Index(fields=['work_date'], name='cutting_record_date_idx'),
            models.Index(fields=['cutter', 'work_date'], name='cutting_record_cutter_date_idx'),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(boxes__gt=0), name='cutting_record_boxes_positive'),
            models.CheckConstraint(condition=Q(unit_price__gt=0), name='cutting_record_price_positive'),
        ]

    def __str__(self):
        return f'{self.cutter} {self.work_date} {self.get_style_display()} {self.size} × {self.boxes}'

    @property
    def item_label(self):
        return f'{self.get_style_display()} {self.size}'


class MonthLock(models.Model):
    """A month that has been paid. While it is locked, its work can't be entered, corrected,
    deleted or re-priced. Unlocking removes the row; the change log keeps the history."""
    month = models.DateField(unique=True)  # always the first day of the month
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    locked_by_name = models.CharField(max_length=150, blank=True)
    locked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-month']

    def __str__(self):
        return f'{self.month:%Y-%m} locked'


class AuditAction(models.TextChoices):
    EDIT = 'edit', 'Corrected'
    DELETE_RECORD = 'delete_record', 'Deleted row'
    DELETE_BATCH = 'delete_batch', 'Deleted with its entry'
    REPRICE = 'reprice', 'Re-priced'
    LOCK = 'lock', 'Locked month'
    UNLOCK = 'unlock', 'Unlocked month'
    RATE_ADD = 'rate_add', 'New rate'
    RATE_EDIT = 'rate_edit', 'Rate changed'
    RATE_DELETE = 'rate_delete', 'Rate deleted'
    DEDUCTION_SET = 'deduction_set', 'Tax/insurance set'
    DEDUCTION_DELETE = 'deduction_delete', 'Tax/insurance deleted'
    PEEL_EDIT = 'peel_edit', 'Peeling entry corrected'
    PEEL_DELETE = 'peel_delete', 'Peeling entry deleted'
    PEEL_PRICE = 'peel_price', 'Peeling price changed'
    PEEL_PAID = 'peel_paid', 'Peeling statement paid'
    PEEL_UNPAID = 'peel_unpaid', 'Peeling statement reopened'


class AuditEntry(models.Model):
    """One change to recorded work, to a rate, or to a month's lock.

    Written by cutting/services.py and never changed or deleted. Names and figures are
    copied in, so an entry still reads correctly after the record, the cutter or the
    supervisor's account is gone.
    """
    action = models.CharField(max_length=20, choices=AuditAction.choices)
    month = models.DateField()  # first day of the month the change belongs to
    work_date = models.DateField(null=True, blank=True)  # the work's day, or a rate's start date
    cutter_name = models.CharField(max_length=100, blank=True)
    record_id = models.PositiveIntegerField(null=True, blank=True)  # plain ids: the rows may be gone
    batch_id = models.PositiveIntegerField(null=True, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    user_name = models.CharField(max_length=150, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-at', '-pk']
        indexes = [models.Index(fields=['month', 'at'], name='cutting_audit_month_idx')]

    def __str__(self):
        return f'{timezone.localtime(self.at):%Y-%m-%d %H:%M} {self.action} {self.cutter_name}'.strip()


# ─── Skin peeling by outside companies ────────────────────────
#
# After drying, fish go to outside companies that peel off the skin and bring back the flesh
# and the whole skin. They are paid per fish brought back, at their own agreed price.
# Every write goes through cutting/peeling.py.

class TaxMode(models.TextChoices):
    """How tax applies to what a peeling company is paid."""
    NONE = 'none', 'No tax'
    VAT = 'vat', '+10% VAT'
    WITHHOLD = 'withhold', '3.3% withheld'


class PeelCompany(models.Model):
    """An outside company that peels the skin off our dried fish."""
    name = models.CharField(max_length=100)
    note = models.CharField(max_length=200, blank=True)
    tax_mode = models.CharField(max_length=10, choices=TaxMode.choices, default=TaxMode.NONE)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(Lower('name'), name='cutting_peelcompany_name_unique_ci'),
        ]

    def __str__(self):
        return self.name

    def price_on(self, day):
        """The price in force on `day`: the latest one starting on or before it, or None.
        Filters in Python so a prefetched `prices` set is reused."""
        eligible = [price for price in self.prices.all() if price.effective_from <= day]
        return max(eligible, key=lambda price: price.effective_from, default=None)


class PeelPrice(models.Model):
    """What a company is paid per fish from `effective_from` until its next price starts.
    A batch brought back copies the price when it is saved, so changing a price never alters
    pay already recorded."""
    company = models.ForeignKey(PeelCompany, on_delete=models.CASCADE, related_name='prices')
    price_per_fish = models.DecimalField(max_digits=10, decimal_places=0)
    effective_from = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['company', '-effective_from']
        constraints = [
            models.UniqueConstraint(fields=['company', 'effective_from'], name='cutting_peelprice_company_date_unique'),
            models.CheckConstraint(condition=Q(price_per_fish__gt=0), name='cutting_peelprice_price_positive'),
        ]

    def __str__(self):
        return f'{self.company}: ₩{self.price_per_fish:,.0f}/fish from {self.effective_from}'


class PeelKind(models.TextChoices):
    OUT = 'out', 'Given to them'
    BACK = 'back', 'Brought back'
    LOST = 'lost', 'Lost or damaged'


class PeelMovement(models.Model):
    """Fish given to a peeling company, brought back peeled, or written off as lost or damaged.

    What a company still has = given − brought back − lost. Only fish brought back are paid:
    such a row copies the company's price for its day into unit_price and amount.
    `token` is minted when the form is shown, so a double tap can only save it once.
    """
    company = models.ForeignKey(PeelCompany, on_delete=models.PROTECT, related_name='movements')
    date = models.DateField()
    kind = models.CharField(max_length=4, choices=PeelKind.choices)
    fish = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=0, null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    note = models.CharField(max_length=200, blank=True)
    token = models.UUIDField(unique=True, editable=False)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    entered_by_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date', 'created_at', 'pk']
        indexes = [models.Index(fields=['company', 'date'], name='cutting_peelmove_company_date')]
        constraints = [
            models.CheckConstraint(condition=Q(fish__gt=0), name='cutting_peelmove_fish_positive'),
        ]

    def __str__(self):
        return f'{self.company} {self.date} {self.kind} {self.fish}'


class PeelPaid(models.Model):
    """A company's month that has been paid. Its entries can't change while it is marked paid,
    and the statement keeps the figures it was paid with, even if the price or tax setting
    changes later. Reopening removes the row; the change log keeps the history."""
    company = models.ForeignKey(PeelCompany, on_delete=models.CASCADE, related_name='paid_months')
    month = models.DateField()  # always the first day of the month
    fish = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=14, decimal_places=0)
    tax_mode = models.CharField(max_length=10, choices=TaxMode.choices)
    tax = models.DecimalField(max_digits=14, decimal_places=0)
    total = models.DecimalField(max_digits=14, decimal_places=0)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    paid_by_name = models.CharField(max_length=150, blank=True)
    paid_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-month']
        constraints = [
            models.UniqueConstraint(fields=['company', 'month'], name='cutting_peelpaid_company_month_unique'),
        ]

    def __str__(self):
        return f'{self.company} {self.month:%Y-%m} paid'
