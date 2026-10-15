from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator


class CustomUser(AbstractUser):
    is_employee = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)
    hourly_wage = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=20, blank=True)
    is_contracted = models.BooleanField(default=False)
    visa_type = models.CharField(max_length=50, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.email


class WorkHours(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    date = models.DateField()
    hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[
            MinValueValidator(0.00, message="Hours cannot be negative."),
            MaxValueValidator(24.00, message="Hours cannot exceed 24 per day.")
        ]
    )
    is_absence = models.BooleanField(default=False)

    # Enhanced tracking timestamps (using only auto_now/auto_now_add)
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this record was first created"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When this record was last modified"
    )

    class Meta:
        unique_together = ('user', 'date')

        # Database indexes for better performance
        indexes = [
            models.Index(fields=['date'], name='workhours_date_idx'),
            models.Index(fields=['user', 'date'], name='workhours_user_date_idx'),
            models.Index(fields=['created_at'], name='workhours_created_idx'),
            models.Index(fields=['is_absence'], name='workhours_absence_idx'),
        ]

        # Ordering for consistent results
        ordering = ['-date', 'user']

        # Verbose names for admin interface
        verbose_name = "Work Hours"
        verbose_name_plural = "Work Hours"

    def __str__(self):
        if self.is_absence:
            return f"{self.user.email} - {self.date} (Absent)"
        return f"{self.user.email} - {self.date} ({self.hours}h)"

    def clean(self):
        """Additional validation logic"""
        from django.core.exceptions import ValidationError

        # If marked as absence, hours should be 0
        if self.is_absence and self.hours > 0:
            raise ValidationError("Hours must be 0 when marked as absence.")

        # If not absence, hours should be greater than 0
        if not self.is_absence and self.hours <= 0:
            raise ValidationError("Hours must be greater than 0 when not marked as absence.")

    def save(self, *args, **kwargs):
        """Override save to run validation"""
        self.clean()
        super().save(*args, **kwargs)


class Holiday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=100)

    # Enhanced tracking (using only auto_now/auto_now_add)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date']
        indexes = [
            models.Index(fields=['date'], name='holiday_date_idx'),
        ]

    def __str__(self):
        return f"{self.name} - {self.date}"


class Settings(models.Model):
    minimum_wage = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        validators=[
            MinValueValidator(0.00, message="Minimum wage cannot be negative.")
        ]
    )

    # Enhanced tracking (using only auto_now/auto_now_add)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Settings"
        verbose_name_plural = "Settings"

    def __str__(self):
        return f"Minimum Wage: ₩{self.minimum_wage}"

class CardExpense(models.Model):
    user = models.ForeignKey('CustomUser', on_delete=models.CASCADE, related_name='card_expenses')
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    date = models.DateField()
    description = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.user} - {self.date} - ₩{self.amount}"


class InsuranceMode(models.TextChoices):
    NONE = '', 'None'
    PERCENT = 'percent', '% of gross pay'
    AMOUNT = 'amount', 'Fixed amount (₩)'


class DeductionRate(models.Model):
    """Tax and health insurance taken off one person's pay, from `effective_from` (always the
    first day of a month) until their next rate starts.

    Payslips look up the rate for their own month, so adding a rate for a later month never
    changes an earlier payslip. hours_tracker.deductions does the arithmetic; employees and
    fish cutters each have a concrete subclass.
    """
    effective_from = models.DateField()
    tax_percent = models.DecimalField(
        max_digits=6, decimal_places=3, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    insurance_mode = models.CharField(max_length=10, choices=InsuranceMode.choices, blank=True, default='')
    # A percentage (e.g. 3.545) or whole won (e.g. 150000), depending on insurance_mode.
    insurance_value = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-effective_from']


class EmployeeDeduction(DeductionRate):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='deductions')

    class Meta(DeductionRate.Meta):
        constraints = [
            models.UniqueConstraint(fields=['user', 'effective_from'], name='hours_employeededuction_user_month_unique'),
        ]

    def __str__(self):
        return f'{self.user} from {self.effective_from:%Y-%m}'
