from django.db import models
from django.contrib.auth.models import (AbstractBaseUser,PermissionsMixin,BaseUserManager)
from django.utils import timezone
from django.contrib.auth.models import User
from django.db.models import Q

SIDE_CHOICES = (
    ('single', 'Single Side'),
    ('double', 'Double Side'),
)




class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):

    ROLE_CHOICES = (
        ('admin', 'Admin'),
        ('employee', 'Employee'),
    )

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name', 'role']

    def __str__(self):
        return f"{self.email} - {self.name}"


class Shop (models.Model):
    name = models.CharField(max_length=100, unique=True)
    location = models.CharField(max_length=200)

    def __str__(self):
        return self.name

class Employee(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    shop = models.ForeignKey(Shop, on_delete=models.SET_NULL, null=True, blank=True)
    employee_id = models.CharField(max_length=50, unique=True)
    department = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    joining_date = models.DateField()

    def __str__(self):
        return self.user.name

class Customer(models.Model):
    CUSTOMER_TYPE = (
        ('normal', 'Normal'),
        ('press', 'Press'),
    )

    name = models.CharField(max_length=150, unique=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    customer_type = models.CharField(max_length=10, choices=CUSTOMER_TYPE)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # credit balance

    def __str__(self):
        return self.name


class Printer(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, unique=True)
    model = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class PrinterCounts(models.Model):

    TYPE_CHOICES = (
        ('color', 'Color'),
        ('b/w', 'B/W'),
    )
    printer = models.ForeignKey(Printer, on_delete=models.CASCADE)
    date = models.DateField(default=timezone.now)

    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    count = models.PositiveIntegerField()

    def __str__(self):
        return f"Counts on {self.date}"

class Finishing(models.Model):
    name = models.CharField(max_length=100)

    def get_applicable_slab(self, count, side=None):
        if not count:
            return None

        slabs = (
            self.rate_slabs
            .filter(min_count__lte=count)
            .filter(Q(max_count__isnull=True) | Q(max_count__gte=count))
        )

        if side:
            slabs = slabs.filter(side=side)

        return slabs.order_by('min_count', 'max_count', 'id').first()

    def get_rate_for_customer(self, count, customer_type, side=None):
        slab = self.get_applicable_slab(count, side=side)
        if not slab:
            return None
        return slab.get_rate_for_customer(customer_type)

    def __str__(self):
        return self.name


class FinishingRate(models.Model):
    finishing = models.ForeignKey(Finishing, on_delete=models.CASCADE, related_name='rate_slabs')
    side = models.CharField(max_length=10, choices=SIDE_CHOICES, default='single')
    min_count = models.PositiveIntegerField()
    max_count = models.PositiveIntegerField(blank=True, null=True)
    normal_rate = models.DecimalField(max_digits=10, decimal_places=2)
    press_rate = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ('min_count', 'max_count', 'id')

    @property
    def count_label(self):
        side_label = self.get_side_display()
        if self.max_count:
            return f"{side_label} | {self.min_count} - {self.max_count}"
        return f"{side_label} | {self.min_count}+"

    def get_rate_for_customer(self, customer_type):
        if customer_type == 'press':
            return self.press_rate
        return self.normal_rate

    def __str__(self):
        return f"{self.finishing.name} ({self.count_label})"


class ItemCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class StockItem(models.Model):
    category = models.ForeignKey(ItemCategory, on_delete=models.CASCADE)
    name = models.CharField(max_length=150)
    gsm = models.PositiveIntegerField()

    def get_applicable_slab(self, count, side=None):
        if not count:
            return None

        slabs = (
            self.rate_slabs
            .filter(min_count__lte=count)
            .filter(Q(max_count__isnull=True) | Q(max_count__gte=count))
        )

        if side:
            slabs = slabs.filter(side=side)

        return slabs.order_by('min_count', 'max_count', 'id').first()

    def get_rate_for_customer(self, count, customer_type, side=None):
        slab = self.get_applicable_slab(count, side=side)
        if not slab:
            return None
        return slab.get_rate_for_customer(customer_type)

    def __str__(self):
        return f"{self.name} - {self.gsm} GSM"


class StockItemRate(models.Model):
    stock_item = models.ForeignKey(StockItem, on_delete=models.CASCADE, related_name='rate_slabs')
    side = models.CharField(max_length=10, choices=SIDE_CHOICES, default='single')
    min_count = models.PositiveIntegerField()
    max_count = models.PositiveIntegerField(blank=True, null=True)
    normal_rate = models.DecimalField(max_digits=10, decimal_places=2)
    press_rate = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ('min_count', 'max_count', 'id')

    @property
    def count_label(self):
        side_label = self.get_side_display()
        if self.max_count:
            return f"{side_label} | {self.min_count} - {self.max_count}"
        return f"{side_label} | {self.min_count}+"

    def get_rate_for_customer(self, customer_type):
        if customer_type == 'press':
            return self.press_rate
        return self.normal_rate

    def __str__(self):
        return f"{self.stock_item.name} ({self.count_label})"


class StockQuantity(models.Model):
    item = models.OneToOneField('StockItem', on_delete=models.CASCADE)
    quantity = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.item.name} - {self.quantity}"

class StockAdjustment(models.Model):
    ADJUSTMENT_TYPE = (
        ('add', 'Add Stock'),
        ('reduce', 'Reduce Stock'),
    )

    item = models.ForeignKey('StockItem', on_delete=models.CASCADE)
    adjustment_type = models.CharField(max_length=10, choices=ADJUSTMENT_TYPE)
    quantity = models.PositiveIntegerField()
    reason = models.CharField(max_length=200)
    date = models.DateField(default=timezone.now)

    def __str__(self):
        return f"{self.item.name} - {self.adjustment_type} - {self.quantity}"


class CustomerPayment(models.Model):
    date = models.DateField(default=timezone.now)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    def __str__(self):
        return f"{self.customer.name} - {self.amount}"
    

    
class ShopDailyEntry(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE)
    date = models.DateField(default=timezone.now)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    payment = models.CharField(max_length=10, blank=True, null=True, choices=[('cash', 'Cash'), ('UPI', 'UPI')])
    is_credit = models.BooleanField(default=False)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.customer.name} - {self.total_amount}"

class ShopDailyEntryItem(models.Model):
    entry = models.ForeignKey(ShopDailyEntry, on_delete=models.CASCADE, related_name='items')
    paper = models.ForeignKey(StockItem, on_delete=models.CASCADE)
    item_name = models.CharField(max_length=150, blank=True, null=True)
    finishing = models.ForeignKey(Finishing, on_delete=models.CASCADE, blank=True, null=True)

    side = models.CharField(max_length=10, choices=SIDE_CHOICES)

    quantity = models.PositiveIntegerField()
    paper_quantity = models.PositiveIntegerField(default=0)
    finishing_quantity = models.PositiveIntegerField(default=0)
    paper_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    finishing_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def effective_paper_quantity(self):
        return self.paper_quantity or self.quantity

    @property
    def effective_finishing_quantity(self):
        if self.finishing_id:
            return self.finishing_quantity or self.quantity
        return self.finishing_quantity or 0

    @property
    def quantity_breakdown(self):
        if self.finishing_id:
            return f"P:{self.effective_paper_quantity} | F:{self.effective_finishing_quantity}"
        return f"P:{self.effective_paper_quantity}"

    def __str__(self):
        return f"{self.entry.customer.name} - {self.amount}"



class PurchaseItem(models.Model):
    category = models.ForeignKey(ItemCategory, on_delete=models.CASCADE)
    stock_item = models.ForeignKey(StockItem, on_delete=models.CASCADE)
    gsm = models.PositiveIntegerField()
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)


from django.conf import settings
from django.db import models

class ActivityLog(models.Model):
    LEVEL_CHOICES = (
        ('success', 'Success'),
        ('error', 'Error'),
        ('info', 'Info'),
        ('warning', 'Warning'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    level = models.CharField(max_length=10, choices=LEVEL_CHOICES)
    message = models.TextField()

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.level} - {self.message[:40]}"















