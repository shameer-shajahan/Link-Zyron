from django.templatetags.static import static
from itertools import zip_longest
import re
from django.db.models import Q
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import *
from django.db.models import Sum
from django.utils import timezone
from django.db import transaction
from datetime import date, timedelta
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils.timezone import now
from django.db.models import Sum, Count, Q
from datetime import timedelta
from .models import (
    Shop, Employee, Customer, Printer, PrinterCounts, 
    Finishing, FinishingRate, ItemCategory, StockItem, StockItemRate, StockQuantity, 
    StockAdjustment, CustomerPayment, ShopDailyEntry, 
    ShopDailyEntryItem, PurchaseItem
)





def get_shop_context(request):
    if hasattr(request.user, 'employee'):
        if not request.session.get('employee_shop_id'):
            return None, None, redirect('select_shop')
        final_shop_id = request.session['employee_shop_id']
        base_template = 'employee_base.html'
    else:
        final_shop_id = None
        base_template = 'admin_base.html'

    return final_shop_id, base_template, None


def _query_tokens(value):
    value = (value or '').strip()
    if not value:
        return []

    # Split mixed input like "Art300" or "Acme9876" into searchable chunks.
    tokens = re.findall(r'\d+|[^\W\d_]+', value, flags=re.UNICODE)
    return tokens or [value]


def _single_or_none(queryset):
    matches = list(queryset[:2])
    if len(matches) == 1:
        return matches[0]
    return None


def _find_customer_by_input(raw_value, customer_type=None):
    value = (raw_value or '').strip()
    if not value:
        return None

    exact_qs = Customer.objects.filter(
        Q(name__iexact=value) | Q(phone__iexact=value)
    )
    if customer_type:
        exact_qs = exact_qs.filter(customer_type=customer_type)
    customer = exact_qs.order_by('name').first()
    if customer:
        return customer

    tokens = _query_tokens(value)
    matches = Customer.objects.all()
    if customer_type:
        matches = matches.filter(customer_type=customer_type)
    for token in tokens:
        matches = matches.filter(Q(name__icontains=token) | Q(phone__icontains=token))

    return _single_or_none(matches.order_by('name'))


def _find_paper_by_input(raw_value):
    value = (raw_value or '').strip()
    if not value:
        return None

    formatted_match = re.match(r'^(?P<name>.+?)\s*-\s*(?P<gsm>\d+)\s*gsm$', value, flags=re.IGNORECASE)
    if formatted_match:
        exact_qs = StockItem.objects.filter(
            name__iexact=formatted_match.group('name').strip(),
            gsm=int(formatted_match.group('gsm')),
        )
        paper = exact_qs.order_by('name').first()
        if paper:
            return paper

    exact_qs = StockItem.objects.filter(name__iexact=value)
    if value.isdigit():
        exact_qs = exact_qs | StockItem.objects.filter(gsm=int(value))
    paper = _single_or_none(exact_qs.order_by('name', 'gsm'))
    if paper:
        return paper

    tokens = _query_tokens(value)
    matches = StockItem.objects.select_related('category').all()
    for token in tokens:
        token_filter = Q(name__icontains=token) | Q(category__name__icontains=token)
        if token.isdigit():
            token_filter |= Q(gsm=int(token))
        matches = matches.filter(token_filter)

    return _single_or_none(matches.order_by('name', 'gsm'))


def _find_finishing_by_input(raw_value):
    value = (raw_value or '').strip()
    if not value:
        return None

    exact_qs = Finishing.objects.filter(name__iexact=value)
    finishing = exact_qs.order_by('name').first()
    if finishing:
        return finishing

    tokens = _query_tokens(value)
    matches = Finishing.objects.all()
    for token in tokens:
        matches = matches.filter(name__icontains=token)

    return _single_or_none(matches.order_by('name'))


def build_pdf_bytes(html, base_url):
    from weasyprint import HTML

    return HTML(string=html, base_url=base_url).write_pdf()


def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        if not email or not password:
            messages.error(request, "Email and password are required")
            return render(request, 'login.html')

        user = authenticate(request, email=email, password=password)

        if user is not None:
            login(request, user)

            messages.success(
                request,
                f"Welcome back, {user.email}"
            )

            # Role-based redirect
            if user.role == 'admin':
                return redirect('admin_dashboard')
            else:
                return redirect('employee_dashboard')
        else:
            messages.error(request, "Invalid email or password")

    return render(request, 'login.html')

@login_required(login_url='login')
def logout_view(request):
    request.session.pop('employee_shop_id', None)
    logout(request)
    return redirect('login')

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils.timezone import now
from django.db.models import Sum, Count, Q, F, Value, IntegerField
from django.db.models.functions import Coalesce
from datetime import timedelta
from .models import (
    Shop, Employee, Customer, Printer, PrinterCounts, 
    Finishing, FinishingRate, ItemCategory, StockItem, StockItemRate, StockQuantity, 
    StockAdjustment, CustomerPayment, ShopDailyEntry, 
    ShopDailyEntryItem, PurchaseItem
)


@login_required(login_url='login')
def admin_dashboard(request):
    if request.user.role != 'admin':
        return redirect('login')

    today = now().date()

    # ================== SHOPS ==================
    total_shops = Shop.objects.count()
    recent_shops = Shop.objects.order_by('-id')[:5]

    # ================== EMPLOYEES ==================
    total_employees = Employee.objects.count()
    recent_employees = Employee.objects.select_related('user', 'shop').order_by('-id')[:5]

    # ================== CUSTOMERS ==================
    total_customers = Customer.objects.count()
    normal_customers = Customer.objects.filter(customer_type='normal').count()
    press_customers = Customer.objects.filter(customer_type='press').count()
    
    # Total credit balance across all customers
    total_credit_balance = Customer.objects.aggregate(
        total=Sum('balance')
    )['total'] or 0

    recent_customers = Customer.objects.order_by('-id')[:10]

    # ================== PRINTERS ==================
    total_printers = Printer.objects.count()
    recent_printer_counts = PrinterCounts.objects.select_related(
        'printer'
    ).order_by('-date')[:5]

    # Today's printer counts
    today_printer_counts = PrinterCounts.objects.filter(
        date=today
    ).aggregate(
        color=Sum('count', filter=Q(type='color')),
        bw=Sum('count', filter=Q(type='b/w'))
    )

    # ================== STOCK ==================
    # Get stock items with their quantities using annotation
    # This handles the OneToOneField relationship more efficiently
    stock_items_with_qty = []
    stock_items = StockItem.objects.select_related('category').all()
    
    for item in stock_items:
        try:
            qty = item.stockquantity.quantity
        except StockQuantity.DoesNotExist:
            qty = 0
        
        stock_items_with_qty.append({
            'item': item,
            'quantity': qty
        })

    # Low stock items (quantity < 100)
    low_stock_items = [item for item in stock_items_with_qty if item['quantity'] < 100]
    low_stock_count = len(low_stock_items)

    # ================== DAILY ENTRIES ==================
    # Today's sales
    today_sales = ShopDailyEntry.objects.filter(
        date=today
    ).aggregate(
        total=Sum('total_amount')
    )['total'] or 0

    # Total sales (all time)
    total_sales = ShopDailyEntry.objects.aggregate(
        total=Sum('total_amount')
    )['total'] or 0

    # Cash vs Credit today
    today_cash_sales = ShopDailyEntry.objects.filter(
        date=today,
        is_credit=False
    ).aggregate(total=Sum('total_amount'))['total'] or 0

    today_credit_sales = ShopDailyEntry.objects.filter(
        date=today,
        is_credit=True
    ).aggregate(total=Sum('total_amount'))['total'] or 0

    # Recent daily entries
    recent_entries = ShopDailyEntry.objects.select_related(
        'shop', 'customer'
    ).order_by('-date', '-id')[:10]

    # ================== CUSTOMER PAYMENTS ==================
    # Total payments received
    total_payments = CustomerPayment.objects.aggregate(
        total=Sum('amount')
    )['total'] or 0

    # Today's payments
    today_payments = CustomerPayment.objects.filter(
        date=today
    ).aggregate(
        total=Sum('amount')
    )['total'] or 0

    # Recent payments
    recent_payments = CustomerPayment.objects.select_related(
        'customer'
    ).order_by('-date')[:5]

    # ================== PURCHASES ==================
    total_purchases = PurchaseItem.objects.aggregate(
        total=Sum('amount')
    )['total'] or 0

    recent_purchases = PurchaseItem.objects.select_related(
        'category', 'stock_item'
    ).order_by('-id')[:5]

    context = {
        'today_date': today,
        
        # shops
        'total_shops': total_shops,
        'recent_shops': recent_shops,
        
        # employees
        'total_employees': total_employees,
        'recent_employees': recent_employees,
        
        # customers
        'total_customers': total_customers,
        'normal_customers': normal_customers,
        'press_customers': press_customers,
        'total_credit_balance': total_credit_balance,
        'recent_customers': recent_customers,
        
        # printers
        'total_printers': total_printers,
        'recent_printer_counts': recent_printer_counts,
        'today_printer_counts': today_printer_counts,
        
        # stock
        'low_stock_count': low_stock_count,
        'low_stock_items': low_stock_items[:10],  # Show top 10
        
        # sales
        'today_sales': today_sales,
        'total_sales': total_sales,
        'today_cash_sales': today_cash_sales,
        'today_credit_sales': today_credit_sales,
        'recent_entries': recent_entries,
        
        # payments
        'total_payments': total_payments,
        'today_payments': today_payments,
        'recent_payments': recent_payments,
        
        # purchases
        'total_purchases': total_purchases,
        'recent_purchases': recent_purchases,
    }

    return render(request, 'admin_dashboard.html', context)


@login_required(login_url='login')
def employee_dashboard(request):

    if request.user.role != 'employee':
        return redirect('login')

    
    today = now().date()

    # ================== SHOPS ==================
    total_shops = Shop.objects.count()
    recent_shops = Shop.objects.order_by('-id')[:5]

    # ================== EMPLOYEES ==================
    total_employees = Employee.objects.count()
    recent_employees = Employee.objects.select_related('user', 'shop').order_by('-id')[:5]

    # ================== CUSTOMERS ==================
    total_customers = Customer.objects.count()
    normal_customers = Customer.objects.filter(customer_type='normal').count()
    press_customers = Customer.objects.filter(customer_type='press').count()
    
    # Total credit balance across all customers
    total_credit_balance = Customer.objects.aggregate(
        total=Sum('balance')
    )['total'] or 0

    recent_customers = Customer.objects.order_by('-id')[:10]

    # ================== PRINTERS ==================
    total_printers = Printer.objects.count()
    recent_printer_counts = PrinterCounts.objects.select_related(
        'printer'
    ).order_by('-date')[:5]

    # Today's printer counts
    today_printer_counts = PrinterCounts.objects.filter(
        date=today
    ).aggregate(
        color=Sum('count', filter=Q(type='color')),
        bw=Sum('count', filter=Q(type='b/w'))
    )

    # ================== STOCK ==================
    # Get stock items with their quantities using annotation
    # This handles the OneToOneField relationship more efficiently
    stock_items_with_qty = []
    stock_items = StockItem.objects.select_related('category').all()
    
    for item in stock_items:
        try:
            qty = item.stockquantity.quantity
        except StockQuantity.DoesNotExist:
            qty = 0
        
        stock_items_with_qty.append({
            'item': item,
            'quantity': qty
        })

    # Low stock items (quantity < 100)
    low_stock_items = [item for item in stock_items_with_qty if item['quantity'] < 100]
    low_stock_count = len(low_stock_items)

    # ================== DAILY ENTRIES ==================
    # Today's sales
    today_sales = ShopDailyEntry.objects.filter(
        date=today
    ).aggregate(
        total=Sum('total_amount')
    )['total'] or 0

    # Total sales (all time)
    total_sales = ShopDailyEntry.objects.aggregate(
        total=Sum('total_amount')
    )['total'] or 0

    # Cash vs Credit today
    today_cash_sales = ShopDailyEntry.objects.filter(
        date=today,
        is_credit=False
    ).aggregate(total=Sum('total_amount'))['total'] or 0

    today_credit_sales = ShopDailyEntry.objects.filter(
        date=today,
        is_credit=True
    ).aggregate(total=Sum('total_amount'))['total'] or 0

    # Recent daily entries
    recent_entries = ShopDailyEntry.objects.select_related(
        'shop', 'customer'
    ).order_by('-date', '-id')[:10]

    # ================== CUSTOMER PAYMENTS ==================
    # Total payments received
    total_payments = CustomerPayment.objects.aggregate(
        total=Sum('amount')
    )['total'] or 0

    # Today's payments
    today_payments = CustomerPayment.objects.filter(
        date=today
    ).aggregate(
        total=Sum('amount')
    )['total'] or 0

    # Recent payments
    recent_payments = CustomerPayment.objects.select_related(
        'customer'
    ).order_by('-date')[:5]

    # ================== PURCHASES ==================
    total_purchases = PurchaseItem.objects.aggregate(
        total=Sum('amount')
    )['total'] or 0

    recent_purchases = PurchaseItem.objects.select_related(
        'category', 'stock_item'
    ).order_by('-id')[:5]

    context = {
        'today_date': today,
        
        # shops
        'total_shops': total_shops,
        'recent_shops': recent_shops,
        
        # employees
        'total_employees': total_employees,
        'recent_employees': recent_employees,
        
        # customers
        'total_customers': total_customers,
        'normal_customers': normal_customers,
        'press_customers': press_customers,
        'total_credit_balance': total_credit_balance,
        'recent_customers': recent_customers,
        
        # printers
        'total_printers': total_printers,
        'recent_printer_counts': recent_printer_counts,
        'today_printer_counts': today_printer_counts,
        
        # stock
        'low_stock_count': low_stock_count,
        'low_stock_items': low_stock_items[:10],  # Show top 10
        
        # sales
        'today_sales': today_sales,
        'total_sales': total_sales,
        'today_cash_sales': today_cash_sales,
        'today_credit_sales': today_credit_sales,
        'recent_entries': recent_entries,
        
        # payments
        'total_payments': total_payments,
        'today_payments': today_payments,
        'recent_payments': recent_payments,
        
        # purchases
        'total_purchases': total_purchases,
        'recent_purchases': recent_purchases,
    }


    return render(
        request,
        'employee_dashboard.html', context)
        
@login_required(login_url='login')
def master_dashboard(request):

    today = now().date()

    # ================== SHOPS ==================
    total_shops = Shop.objects.count()
    recent_shops = Shop.objects.order_by('-id')[:5]

    # ================== PRINTERS ==================
    total_printers = Printer.objects.count()
    recent_printers = Printer.objects.select_related('shop').order_by('-id')[:5]

    # ================== PRINTER COUNTS ==================
    # Today's printer counts
    today_printer_counts = PrinterCounts.objects.filter(
        date=today
    ).aggregate(
        color=Sum('count', filter=Q(type='color')),
        bw=Sum('count', filter=Q(type='b/w'))
    )

    # Total printer counts
    total_printer_counts = PrinterCounts.objects.aggregate(
        color=Sum('count', filter=Q(type='color')),
        bw=Sum('count', filter=Q(type='b/w'))
    )

    # Recent printer counts
    recent_printer_counts = PrinterCounts.objects.select_related(
        'printer', 'printer__shop'
    ).order_by('-date', '-id')[:10]

    # ================== CATEGORIES ==================
    total_categories = ItemCategory.objects.count()
    recent_categories = ItemCategory.objects.order_by('-id')[:5]

    # ================== STOCK ITEMS ==================
    total_stock_items = StockItem.objects.count()
    
    # Get stock items with their quantities
    stock_items_with_qty = []
    stock_items = StockItem.objects.select_related('category').all()
    
    for item in stock_items:
        try:
            qty = item.stockquantity.quantity
        except StockQuantity.DoesNotExist:
            qty = 0
        
        stock_items_with_qty.append({
            'item': item,
            'quantity': qty
        })

    # Low stock items (quantity < 100)
    low_stock_items = [item for item in stock_items_with_qty if item['quantity'] < 100]
    low_stock_count = len(low_stock_items)
    
    # Out of stock items
    out_of_stock_items = [item for item in stock_items_with_qty if item['quantity'] == 0]
    out_of_stock_count = len(out_of_stock_items)

    # ================== FINISHING ==================
    total_finishing = Finishing.objects.count()
    recent_finishing = Finishing.objects.order_by('-id')[:5]

    # ================== STOCK ADJUSTMENTS ==================
    total_adjustments = StockAdjustment.objects.count()
    
    # Today's adjustments
    today_adjustments = StockAdjustment.objects.filter(date=today).count()
    
    # Recent adjustments
    recent_adjustments = StockAdjustment.objects.select_related(
        'item', 'item__category'
    ).order_by('-date', '-id')[:10]

    # Total added and reduced
    total_added = StockAdjustment.objects.filter(
        adjustment_type='add'
    ).aggregate(total=Sum('quantity'))['total'] or 0
    
    total_reduced = StockAdjustment.objects.filter(
        adjustment_type='reduce'
    ).aggregate(total=Sum('quantity'))['total'] or 0

    context = {
        'today_date': today,
        
        # Shops
        'total_shops': total_shops,
        'recent_shops': recent_shops,
        
        # Printers
        'total_printers': total_printers,
        'recent_printers': recent_printers,
        
        # Printer Counts
        'today_printer_counts': today_printer_counts,
        'total_printer_counts': total_printer_counts,
        'recent_printer_counts': recent_printer_counts,
        
        # Categories
        'total_categories': total_categories,
        'recent_categories': recent_categories,
        
        # Stock Items
        'total_stock_items': total_stock_items,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'low_stock_items': low_stock_items[:10],
        
        # Finishing
        'total_finishing': total_finishing,
        'recent_finishing': recent_finishing,
        
        # Stock Adjustments
        'total_adjustments': total_adjustments,
        'today_adjustments': today_adjustments,
        'recent_adjustments': recent_adjustments,
        'total_added': total_added,
        'total_reduced': total_reduced,
    }

    return render(request, 'master_dashboard.html', context)

@login_required
def create_employee(request):
    if request.user.role != 'admin':
        return redirect('login')

    if request.method == 'POST':
        user = User.objects.create_user(
            email=request.POST['email'],
            password=request.POST['password'],
            name=request.POST['name'],
            role='employee'
        )

        Employee.objects.create(
            user=user,
            employee_id=request.POST['employee_id'],
            department=request.POST['department'],
            phone=request.POST['phone'],
            joining_date=request.POST['joining_date']
        )

        messages.success(request, 'Employee created successfully')

        return redirect('employee_list')

    return render(request, 'employee/create_employee.html')

@login_required
def edit_employee(request, employee_id):
    if request.user.role != 'admin':
        return redirect('login')

    employee = get_object_or_404(Employee, id=employee_id)
    user = employee.user

    if request.method == 'POST':
        # Update User model
        user.name = request.POST['name']
        user.email = request.POST['email']

        password = request.POST.get('password')
        if password:
            user.set_password(password)

        user.save()

        # Update Employee model
        employee.employee_id = request.POST['employee_id']
        employee.department = request.POST['department']
        employee.phone = request.POST['phone']
        employee.joining_date = request.POST['joining_date']
        employee.save()

        messages.success(request, 'Employee updated successfully')
        return redirect('employee_list')

    context = {
        'employee': employee,
        'user': user,
        'edit': True
    }
    return render(request, 'employee/create_employee.html', context)

@login_required
def employee_list(request):
    if request.user.role != 'admin':
        return redirect('login')

    employees = Employee.objects.all()
    return render(request, 'employee/employee_list.html', {'employees': employees})

@login_required
def employee_detail(request, employee_id):
    if request.user.role != 'admin':
        return redirect('login')

    employee = get_object_or_404(Employee, id=employee_id)
    return render(request, 'employee/employee_detail.html', {'employee': employee})

@login_required
def employee_delete(request, employee_id):
    if request.user.role != 'admin':
        return redirect('login')

    employee = get_object_or_404(Employee, id=employee_id)

    if request.method == 'POST':
        # Also delete the linked User
        employee.user.delete()
        employee.delete()
        return redirect('employee_list')

    return render(request, 'employee/employee_delete.html', {'employee': employee})




# =====================================================
# SHOP
# =====================================================
@login_required
def shop_create(request):
    if request.method == "POST":
        Shop.objects.create(
            name=request.POST['name'],
            location=request.POST['location']
        )
        return redirect('shop_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'shop/create.html', {'base_template': base_template})

@login_required
def shop_list(request):
    shops = Shop.objects.all()
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'shop/list.html', {'shops': shops, 'base_template': base_template})

@login_required
def shop_detail(request, pk):
    shop = get_object_or_404(Shop, pk=pk)
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'shop/detail.html', {'shop': shop, 'base_template': base_template})

@login_required
def shop_edit(request, pk):
    shop = get_object_or_404(Shop, pk=pk)
    if request.method == "POST":
        shop.name = request.POST['name']
        shop.location = request.POST['location']
        shop.save()
        return redirect('shop_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'shop/edit.html', {'shop': shop, 'base_template': base_template})

@login_required
def shop_delete(request, pk):
    shop = get_object_or_404(Shop, pk=pk)
    shop.delete()
    return redirect('shop_list')

# =====================================================
# PRINTER
# =====================================================
@login_required
def printer_create(request):
    shops = Shop.objects.all()
    if request.method == "POST":
        Printer.objects.create(
            shop_id=request.POST['shop'],
            name=request.POST['name'],
            model=request.POST['model']
        )
        return redirect('printer_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'printer/create.html', {'shops': shops, 'base_template': base_template})

@login_required
def printer_list(request):
    printers = Printer.objects.select_related('shop')
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'printer/list.html', {'printers': printers, 'base_template': base_template})

@login_required
def printer_detail(request, pk):
    printer = get_object_or_404(Printer, pk=pk)
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'printer/detail.html', {'printer': printer, 'base_template': base_template})

@login_required
def printer_edit(request, pk):
    printer = get_object_or_404(Printer, pk=pk)
    shops = Shop.objects.all()
    if request.method == "POST":
        printer.shop_id = request.POST['shop']
        printer.name = request.POST['name']
        printer.model = request.POST['model']
        printer.save()
        return redirect('printer_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'printer/create.html', {'printer': printer, 'shops': shops, 'base_template': base_template})

@login_required
def printer_delete(request, pk):
    printer = get_object_or_404(Printer, pk=pk)
    printer.delete()
    return redirect('printer_list')

# =====================================================
# PRINTER COUNTS
# =====================================================
@login_required
def printer_count_create(request):
    printers = Printer.objects.all()

    if request.method == "POST":
        PrinterCounts.objects.create(
            printer_id=request.POST['printer'],
            date=request.POST.get('date', timezone.now().date()),
            type=request.POST['type'],
            count=request.POST['count']
        )
        return redirect('printer_count_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'printer_counts/create.html', {'printers': printers, 'base_template': base_template})

@login_required
def printer_count_list(request):
    counts = PrinterCounts.objects.select_related('printer').order_by('-date')
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'printer_counts/list.html', {'counts': counts, 'base_template': base_template})

@login_required
def printer_count_detail(request, pk):
    count = get_object_or_404(PrinterCounts, pk=pk)
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'printer_counts/detail.html', {'count': count, 'base_template': base_template})

@login_required
def printer_count_edit(request, pk):
    count = get_object_or_404(PrinterCounts, pk=pk)
    printers = Printer.objects.all()

    if request.method == "POST":
        count.printer_id = request.POST['printer']
        date_value = request.POST.get('date')
        if date_value:
            count.date = date_value
        count.type = request.POST['type']
        count.count = request.POST['count']
        count.save()
        return redirect('printer_count_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'printer_counts/create.html', {'count': count, 'printers': printers, 'base_template': base_template})

@login_required
def printer_count_delete(request, pk):
    count = get_object_or_404(PrinterCounts, pk=pk)
    count.delete()
    return redirect('printer_count_list')


# =====================================================
# ITEM CATEGORY
# =====================================================
@login_required
def category_create(request):
    if request.method == "POST":
        ItemCategory.objects.create(name=request.POST['name'])
        return redirect('category_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'category/create.html', {'base_template': base_template})

@login_required
def category_list(request):
    categories = ItemCategory.objects.all()
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'category/list.html', {'categories': categories, 'base_template': base_template})

@login_required
def category_edit(request, pk):
    category = get_object_or_404(ItemCategory, pk=pk)
    if request.method == "POST":
        category.name = request.POST['name']
        category.save()
        return redirect('category_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'category/create.html', {'category': category, 'base_template': base_template})

@login_required
def category_delete(request, pk):
    category = get_object_or_404(ItemCategory, pk=pk)
    category.delete()
    return redirect('category_list')


# =====================================================
# STOCK ITEM
# =====================================================
def _blank_rate_row():
    return {
        'side': 'single',
        'min_count': '',
        'max_count': '',
        'normal_rate': '',
        'press_rate': '',
    }


def _build_rate_rows(post_data=None, slabs=None):
    rows = []

    if post_data is not None:
        sides = post_data.getlist('rate_side')
        min_counts = post_data.getlist('rate_min_count')
        max_counts = post_data.getlist('rate_max_count')
        normal_rates = post_data.getlist('normal_rate')
        press_rates = post_data.getlist('press_rate')

        for side, min_count, max_count, normal_rate, press_rate in zip_longest(
            sides, min_counts, max_counts, normal_rates, press_rates, fillvalue=''
        ):
            if not any([
                str(side).strip(),
                str(min_count).strip(),
                str(max_count).strip(),
                str(normal_rate).strip(),
                str(press_rate).strip(),
            ]):
                continue

            rows.append({
                'side': str(side).strip() or 'single',
                'min_count': str(min_count).strip(),
                'max_count': str(max_count).strip(),
                'normal_rate': str(normal_rate).strip(),
                'press_rate': str(press_rate).strip(),
            })

        return rows

    if slabs is not None:
        for slab in slabs:
            rows.append({
                'side': slab.side,
                'min_count': slab.min_count,
                'max_count': slab.max_count or '',
                'normal_rate': slab.normal_rate,
                'press_rate': slab.press_rate,
            })

    return rows


def _parse_rate_rows(post_data):
    raw_rows = _build_rate_rows(post_data=post_data)
    parsed_rows = []
    errors = []

    for index, row in enumerate(raw_rows, start=1):
        side = str(row.get('side', '')).strip() or 'single'
        min_count_raw = str(row.get('min_count', '')).strip()
        max_count_raw = str(row.get('max_count', '')).strip()
        normal_rate_raw = str(row.get('normal_rate', '')).strip()
        press_rate_raw = str(row.get('press_rate', '')).strip()

        if side not in {'single', 'double'}:
            errors.append(f"Rate row {index}: side must be single or double.")
            continue

        if not min_count_raw or not normal_rate_raw or not press_rate_raw:
            errors.append(
                f"Rate row {index}: min count, normal rate, and press rate are required."
            )
            continue

        try:
            min_count = int(min_count_raw)
        except ValueError:
            errors.append(f"Rate row {index}: min count must be a whole number.")
            continue

        max_count = None
        if max_count_raw:
            try:
                max_count = int(max_count_raw)
            except ValueError:
                errors.append(f"Rate row {index}: max count must be a whole number.")
                continue

        try:
            normal_rate = Decimal(normal_rate_raw)
            press_rate = Decimal(press_rate_raw)
        except InvalidOperation:
            errors.append(f"Rate row {index}: rates must be valid numbers.")
            continue

        if min_count <= 0:
            errors.append(f"Rate row {index}: min count must be greater than 0.")
            continue

        if max_count is not None and max_count < min_count:
            errors.append(
                f"Rate row {index}: max count must be greater than or equal to min count."
            )
            continue

        if normal_rate < 0 or press_rate < 0:
            errors.append(f"Rate row {index}: rates cannot be negative.")
            continue

        parsed_rows.append({
            'side': side,
            'min_count': min_count,
            'max_count': max_count,
            'normal_rate': normal_rate,
            'press_rate': press_rate,
        })

    return parsed_rows, errors


def _get_count_based_rate(item, quantity, customer_type, side=None):
    if not item or not quantity or not customer_type or not side:
        return None, None

    try:
        quantity_value = int(quantity)
    except (TypeError, ValueError):
        return None, None

    if quantity_value <= 0:
        return None, None

    slab = item.get_applicable_slab(quantity_value, side=side)
    if not slab:
        return None, None

    return slab.get_rate_for_customer(customer_type), slab


def _quantize_currency(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _rebalance_rates_for_amount(paper_quantity, finishing_quantity, paper_rate, finishing_rate, amount):
    paper_qty = Decimal(paper_quantity or 0)
    finishing_qty = Decimal(finishing_quantity or 0)
    target_amount = Decimal(amount or 0)
    current_paper_rate = Decimal(paper_rate or 0)
    current_finishing_rate = Decimal(finishing_rate or 0)

    if target_amount < 0:
        return _quantize_currency(current_paper_rate), _quantize_currency(current_finishing_rate)

    if paper_qty <= 0 and finishing_qty <= 0:
        return _quantize_currency(current_paper_rate), _quantize_currency(current_finishing_rate)

    current_paper_amount = paper_qty * current_paper_rate
    current_finishing_amount = finishing_qty * current_finishing_rate
    current_total = current_paper_amount + current_finishing_amount

    if paper_qty > 0:
        if current_total > 0:
            paper_share = current_paper_amount / current_total
        else:
            total_units = paper_qty + finishing_qty
            paper_share = (paper_qty / total_units) if total_units > 0 else Decimal('1')

        paper_target_amount = target_amount * paper_share
        adjusted_paper_rate = _quantize_currency(paper_target_amount / paper_qty)
    else:
        adjusted_paper_rate = Decimal('0.00')

    if finishing_qty > 0:
        residual_amount = target_amount - (paper_qty * adjusted_paper_rate)
        if residual_amount < 0 and paper_qty > 0:
            adjusted_paper_rate = _quantize_currency(target_amount / paper_qty)
            residual_amount = target_amount - (paper_qty * adjusted_paper_rate)
        adjusted_finishing_rate = _quantize_currency(
            (residual_amount / finishing_qty) if residual_amount > 0 else Decimal('0')
        )
    else:
        adjusted_finishing_rate = Decimal('0.00')
        if paper_qty > 0:
            adjusted_paper_rate = _quantize_currency(target_amount / paper_qty)

    return adjusted_paper_rate, adjusted_finishing_rate


@login_required
def stock_create(request):
    categories = ItemCategory.objects.all()
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        stock = StockItem(
            category_id=request.POST.get('category'),
            name=request.POST.get('name', '').strip(),
            gsm=request.POST.get('gsm') or 0,
        )
        rate_rows = _build_rate_rows(post_data=request.POST)
        parsed_rows, errors = _parse_rate_rows(request.POST)

        if not request.POST.get('category'):
            errors.append("Category is required.")
        if not stock.name:
            errors.append("Item name is required.")
        if not request.POST.get('gsm'):
            errors.append("GSM is required.")

        if errors:
            for error in errors:
                messages.error(request, error)

            return render(request, 'stock/create.html', {
                'stock': stock,
                'categories': categories,
                'rate_rows': rate_rows or [_blank_rate_row()],
                'base_template': base_template,
            })

        with transaction.atomic():
            stock = StockItem.objects.create(
                category_id=request.POST['category'],
                name=request.POST['name'],
                gsm=request.POST['gsm'],
            )
            StockItemRate.objects.bulk_create([
                StockItemRate(stock_item=stock, **row)
                for row in parsed_rows
            ])

        messages.success(request, "Stock item created successfully.")
        return redirect('stock_list')

    return render(request, 'stock/create.html', {
        'categories': categories,
        'rate_rows': [_blank_rate_row()],
        'base_template': base_template,
    })

@login_required
def stock_list(request):
    stocks_qs = StockItem.objects.select_related('category').prefetch_related('rate_slabs').order_by('name')
    paginator = Paginator(stocks_qs, 10)
    stocks = paginator.get_page(request.GET.get('page'))

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'stock/list.html', {'stocks': stocks, 'base_template': base_template})

@login_required
def stock_detail(request, pk):
    stock = get_object_or_404(StockItem, pk=pk)
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'stock/detail.html', {'stock': stock, 'base_template': base_template})

@login_required
def stock_edit(request, pk):
    stock = get_object_or_404(StockItem, pk=pk)
    categories = ItemCategory.objects.all()
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        stock.category_id = request.POST.get('category')
        stock.name = request.POST.get('name', '').strip()
        stock.gsm = request.POST.get('gsm') or 0
        rate_rows = _build_rate_rows(post_data=request.POST)
        parsed_rows, errors = _parse_rate_rows(request.POST)

        if not request.POST.get('category'):
            errors.append("Category is required.")
        if not stock.name:
            errors.append("Item name is required.")
        if not request.POST.get('gsm'):
            errors.append("GSM is required.")

        if errors:
            for error in errors:
                messages.error(request, error)

            return render(request, 'stock/create.html', {
                'stock': stock,
                'categories': categories,
                'rate_rows': rate_rows or [_blank_rate_row()],
                'base_template': base_template,
            })

        with transaction.atomic():
            stock.save()
            stock.rate_slabs.all().delete()
            StockItemRate.objects.bulk_create([
                StockItemRate(stock_item=stock, **row)
                for row in parsed_rows
            ])

        messages.success(request, "Stock item updated successfully.")
        return redirect('stock_list')

    return render(request, 'stock/create.html', {
        'stock': stock,
        'categories': categories,
        'rate_rows': _build_rate_rows(slabs=stock.rate_slabs.all()) or [_blank_rate_row()],
        'base_template': base_template,
    })

@login_required
def stock_delete(request, pk):
    stock = get_object_or_404(StockItem, pk=pk)
    stock.delete()
    return redirect('stock_list')


# =====================================================
# FINISHING
# =====================================================
def _blank_finishing_rate_row():
    return _blank_rate_row()


def _build_finishing_rate_rows(post_data=None, slabs=None):
    return _build_rate_rows(post_data=post_data, slabs=slabs)


def _parse_finishing_rate_rows(post_data):
    return _parse_rate_rows(post_data)


def _get_finishing_rate(finishing, quantity, customer_type, side=None):
    return _get_count_based_rate(finishing, quantity, customer_type, side=side)


@login_required
def finishing_create(request):
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        name = request.POST.get('name', '').strip()
        finishing = Finishing(name=name)
        rate_rows = _build_finishing_rate_rows(post_data=request.POST)
        parsed_rows, errors = _parse_finishing_rate_rows(request.POST)

        if not name:
            errors.append("Finishing name is required.")

        if errors:
            for error in errors:
                messages.error(request, error)

            return render(request, 'finishing/create.html', {
                'finishing': finishing,
                'rate_rows': rate_rows or [_blank_finishing_rate_row()],
                'base_template': base_template,
            })

        with transaction.atomic():
            finishing = Finishing.objects.create(name=name)
            FinishingRate.objects.bulk_create([
                FinishingRate(finishing=finishing, **row)
                for row in parsed_rows
            ])

        messages.success(request, "Finishing created successfully.")
        return redirect('finishing_list')

    return render(request, 'finishing/create.html', {
        'rate_rows': [_blank_finishing_rate_row()],
        'base_template': base_template,
    })

@login_required
def finishing_list(request):
    finishings_qs = Finishing.objects.prefetch_related('rate_slabs').order_by('name')
    paginator = Paginator(finishings_qs, 10)
    finishings = paginator.get_page(request.GET.get('page'))

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'finishing/list.html', {'finishings': finishings, 'base_template': base_template})

@login_required
def finishing_edit(request, pk):
    finishing = get_object_or_404(Finishing, pk=pk)
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        finishing.name = request.POST.get('name', '').strip()
        rate_rows = _build_finishing_rate_rows(post_data=request.POST)
        parsed_rows, errors = _parse_finishing_rate_rows(request.POST)

        if not finishing.name:
            errors.append("Finishing name is required.")

        if errors:
            for error in errors:
                messages.error(request, error)

            return render(request, 'finishing/create.html', {
                'finishing': finishing,
                'rate_rows': rate_rows or [_blank_finishing_rate_row()],
                'base_template': base_template,
            })

        with transaction.atomic():
            finishing.save()
            finishing.rate_slabs.all().delete()
            FinishingRate.objects.bulk_create([
                FinishingRate(finishing=finishing, **row)
                for row in parsed_rows
            ])

        messages.success(request, "Finishing updated successfully.")
        return redirect('finishing_list')

    return render(request, 'finishing/create.html', {
        'finishing': finishing,
        'rate_rows': _build_finishing_rate_rows(slabs=finishing.rate_slabs.all()) or [_blank_finishing_rate_row()],
        'base_template': base_template,
    })

@login_required
def finishing_delete(request, pk):
    finishing = get_object_or_404(Finishing, pk=pk)
    finishing.delete()
    return redirect('finishing_list')


# =====================================================
# STOCK ADJUSTMENT
# =====================================================
@login_required
def stock_adjustment_create(request):
    items = StockItem.objects.all()

    if request.method == "POST":
        paper_id = request.POST['item']
        adjustment_type = request.POST['adjustment_type']
        qty = int(request.POST['quantity'])
        reason = request.POST['reason']

        item = get_object_or_404(StockItem, id=paper_id)

        adjustment = StockAdjustment.objects.create(
            item=item,
            adjustment_type=adjustment_type,
            quantity=qty,
            reason=reason
        )

        stock_qty, created = StockQuantity.objects.get_or_create(item=item)

        if adjustment_type == 'add':
            stock_qty.quantity += qty
        else:
            stock_qty.quantity -= qty

        stock_qty.save()
        return redirect('stock_adjustment_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'stock_adjustment/create.html', {'items': items, 'base_template': base_template})

@login_required
def stock_adjustment_list(request):
    adjustments = StockAdjustment.objects.select_related('item').order_by('-date')
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'stock_adjustment/list.html', {'adjustments': adjustments, 'base_template': base_template})

@login_required
def stock_adjustment_detail(request, pk):
    adjustment = get_object_or_404(StockAdjustment, pk=pk)
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response
    return render(request, 'stock_adjustment/detail.html', {'adjustment': adjustment, 'base_template': base_template})

@login_required
def stock_adjustment_delete(request, pk):
    adjustment = get_object_or_404(StockAdjustment, pk=pk)
    stock_qty = get_object_or_404(StockQuantity, item=adjustment.item)

    if adjustment.adjustment_type == 'add':
        stock_qty.quantity -= adjustment.quantity
    else:
        stock_qty.quantity += adjustment.quantity

    stock_qty.save()
    adjustment.delete()

    return redirect('stock_adjustment_list')


# =====================================================
# shop daily entry
# =====================================================

@login_required
def select_shop(request):
    if request.session.get('employee_shop_id'):
        return redirect('shop_daily_entry_create')

    shops = Shop.objects.all()

    # choose base by role
    if hasattr(request.user, 'employee'):
        base_template = 'employee_base.html'
    else:
        base_template = 'admin_base.html'

    if request.method == "POST":
        request.session['employee_shop_id'] = request.POST['shop']
        return redirect('shop_daily_entry_create')

    return render(request, 'employee/select_shop.html', {
        'shops': shops,
        'base_template': base_template
    })

@login_required
def customer_autocomplete(request):
    q = (request.GET.get('q') or '').strip()
    if not q:
        return JsonResponse([], safe=False)

    tokens = _query_tokens(q)
    customers = Customer.objects.all()
    for token in tokens:
        customers = customers.filter(
            Q(name__icontains=token) | Q(phone__icontains=token)
        )

    customers = customers.order_by('name')[:10]
    return JsonResponse([
        {'id': c.id, 'name': c.name, 'type': c.customer_type, 'phone': c.phone or ''}
        for c in customers
    ], safe=False)

@login_required
def paper_autocomplete(request):
    q = (request.GET.get('q') or '').strip()
    if not q:
        return JsonResponse([], safe=False)

    tokens = _query_tokens(q)
    papers = StockItem.objects.select_related('category').all()
    for token in tokens:
        token_filter = Q(name__icontains=token) | Q(category__name__icontains=token)
        if token.isdigit():
            token_filter |= Q(gsm=int(token))
        papers = papers.filter(token_filter)

    papers = papers.order_by('name', 'gsm')[:10]
    return JsonResponse([
        {'id': p.id, 'name': p.name, 'gsm': p.gsm}
        for p in papers
    ], safe=False)

@login_required
def finishing_autocomplete(request):
    q = (request.GET.get('q') or '').strip()
    if not q:
        return JsonResponse([], safe=False)

    tokens = _query_tokens(q)
    finishings = Finishing.objects.all()
    for token in tokens:
        finishings = finishings.filter(name__icontains=token)

    finishings = finishings.order_by('name')[:10]
    return JsonResponse([
        {'id': f.id, 'name': f.name}
        for f in finishings
    ], safe=False)


@login_required
def item_name_autocomplete(request):
    q = (request.GET.get('q') or '').strip()
    if not q:
        return JsonResponse([], safe=False)

    tokens = _query_tokens(q)
    item_names = ShopDailyEntryItem.objects.exclude(item_name__isnull=True).exclude(item_name__exact='')
    for token in tokens:
        item_names = item_names.filter(item_name__icontains=token)

    item_names = item_names.values_list('item_name', flat=True).distinct().order_by('item_name')[:10]

    return JsonResponse([{'name': item_name} for item_name in item_names], safe=False)


def _serialize_entry_for_autofill(entry):
    return {
        'id': entry.id,
        'shop_id': entry.shop_id,
        'shop_name': entry.shop.name,
        'payment': entry.payment or '',
        'is_credit': entry.is_credit,
        'total_amount': str(entry.total_amount or Decimal('0.00')),
        'items': [
            {
                'item_name': item.item_name or '',
                'paper_id': item.paper_id,
                'paper_name': item.paper.name,
                'paper_gsm': item.paper.gsm,
                'finishing_id': item.finishing_id,
                'finishing_name': item.finishing.name if item.finishing else '',
                'side': item.side,
                'quantity': item.quantity,
                'paper_quantity': item.effective_paper_quantity,
                'finishing_quantity': item.effective_finishing_quantity,
                'paper_rate': str(item.paper_rate or Decimal('0.00')),
                'finishing_rate': str(item.finishing_rate or Decimal('0.00')),
                'rate': str(item.rate or Decimal('0.00')),
                'amount': str(item.amount or Decimal('0.00')),
            }
            for item in entry.items.all()
        ],
    }


@login_required
def customer_latest_entry_autofill(request, customer_id):
    current_shop_id = request.session.get('employee_shop_id')

    entries = (
        ShopDailyEntry.objects
        .filter(customer_id=customer_id)
        .select_related('shop')
        .prefetch_related('items__paper', 'items__finishing')
        .order_by('-date', '-id')
    )

    entry = None
    if current_shop_id:
        entry = entries.filter(shop_id=current_shop_id).first()

    if entry is None:
        entry = entries.first()

    if entry is None:
        return JsonResponse({'entry': None})

    return JsonResponse({
        'entry': _serialize_entry_for_autofill(entry),
        'same_shop': not current_shop_id or str(entry.shop_id) == str(current_shop_id),
    })

@login_required
def finishing_rate_lookup(request):
    finishing_id = request.GET.get('finishing_id')
    quantity = request.GET.get('quantity')
    customer_type = request.GET.get('customer_type')
    side = request.GET.get('side')

    if not finishing_id:
        return JsonResponse({'rate': None, 'message': 'Select a finishing first.'})

    finishing = Finishing.objects.filter(id=finishing_id).first()
    if not finishing:
        return JsonResponse({'rate': None, 'message': 'Selected finishing was not found.'})

    rate, slab = _get_finishing_rate(finishing, quantity, customer_type, side=side)
    if slab is None or rate is None:
        return JsonResponse({
            'rate': None,
            'message': 'No finishing slab.',
        })

    return JsonResponse({
        'rate': str(rate),
        'range_label': slab.count_label,
        'finishing_name': finishing.name,
    })


@login_required
def paper_rate_lookup(request):
    paper_id = request.GET.get('paper_id')
    quantity = request.GET.get('quantity')
    customer_type = request.GET.get('customer_type')
    side = request.GET.get('side')

    if not paper_id:
        return JsonResponse({'rate': None, 'message': 'Select a paper first.'})

    paper = StockItem.objects.filter(id=paper_id).first()
    if not paper:
        return JsonResponse({'rate': None, 'message': 'Selected paper was not found.'})

    rate, slab = _get_count_based_rate(paper, quantity, customer_type, side=side)
    if slab is None or rate is None:
        return JsonResponse({
            'rate': None,
            'message': 'No paper slab.',
        })

    return JsonResponse({
        'rate': str(rate),
        'range_label': slab.count_label,
        'paper_name': paper.name,
    })


def _resolve_daily_entry_customer(customer_id, customer_name, customer_type, customer_phone):
    customer_name = (customer_name or '').strip()
    customer_phone = (customer_phone or '').strip()

    if not customer_name or not customer_type:
        return None, "Customer name and type required"

    if customer_id:
        customer = Customer.objects.filter(id=customer_id).first()
        if not customer:
            return None, "Selected customer was not found."
    else:
        customer = _find_customer_by_input(customer_name, customer_type=customer_type)
        if not customer:
            customer = Customer.objects.create(
                name=customer_name,
                customer_type=customer_type,
                phone=customer_phone or None
            )

    if customer_phone and not customer.phone:
        customer.phone = customer_phone
        customer.save(update_fields=['phone'])

    return customer, None


def _build_daily_entry_items(post_data, customer_type_value):
    paper_ids = post_data.getlist('paper_id')
    paper_texts = post_data.getlist('paper_text')
    item_names = post_data.getlist('item_name')
    finishing_ids = post_data.getlist('finishing_id')
    finishing_texts = post_data.getlist('finishing_text')
    sides = post_data.getlist('side')
    legacy_quantities = post_data.getlist('quantity')
    paper_quantities = post_data.getlist('paper_quantity')
    finishing_quantities = post_data.getlist('finishing_quantity')
    if not paper_quantities:
        paper_quantities = legacy_quantities
    if not finishing_quantities:
        finishing_quantities = legacy_quantities
    paper_rates = post_data.getlist('paper_rate')
    finishing_rates = post_data.getlist('finishing_rate')
    rates = post_data.getlist('rate')
    amounts = post_data.getlist('amount')

    rows = zip_longest(
        paper_ids, paper_texts, item_names, finishing_ids, finishing_texts,
        sides, paper_quantities, finishing_quantities, paper_rates, finishing_rates, rates, amounts,
        fillvalue=''
    )

    total_amount = Decimal('0.00')
    items_to_create = []

    for row_number, row in enumerate(rows, start=1):
        (
            paper_id, paper_text, item_name, finishing_id, finishing_text,
            side, paper_qty, finishing_qty, paper_rate, finishing_rate, rate, amt
        ) = row

        paper_text = (paper_text or '').strip()
        item_name = (item_name or '').strip()
        finishing_text = (finishing_text or '').strip()
        side = (side or '').strip()
        paper_qty = (paper_qty or '').strip()
        finishing_qty = (finishing_qty or '').strip()
        paper_rate = (paper_rate or '').strip()
        finishing_rate = (finishing_rate or '').strip()
        amt = (amt or '').strip()

        row_has_data = any([
            paper_id,
            paper_text,
            item_name,
            finishing_id,
            finishing_text,
            side,
            paper_qty,
            finishing_qty,
            paper_rate,
            finishing_rate,
        ])
        if not row_has_data:
            continue

        if not paper_qty:
            return None, None, f"Paper qty is required for row {row_number}."

        paper = None
        if paper_id:
            paper = StockItem.objects.filter(id=paper_id).first()
        if paper is None and paper_text:
            paper = _find_paper_by_input(paper_text)
        if paper is None:
            return None, None, f"Select a valid paper for row {row_number}."

        finishing = None
        if finishing_id:
            finishing = Finishing.objects.filter(id=finishing_id).first()
        elif finishing_text:
            finishing = _find_finishing_by_input(finishing_text)
        if finishing_text and finishing is None:
            return None, None, f"Select a valid finishing for row {row_number}."

        if not side:
            return None, None, f"Side is required for row {row_number}."

        try:
            paper_qty_val = Decimal(paper_qty)
        except InvalidOperation:
            return None, None, f"Paper qty must be a valid number for row {row_number}."

        if paper_qty_val <= 0:
            return None, None, f"Paper qty must be greater than 0 for row {row_number}."

        finishing_qty_val = Decimal('0')
        if finishing:
            if not finishing_qty:
                return None, None, f"Finishing qty is required for row {row_number}."
            try:
                finishing_qty_val = Decimal(finishing_qty)
            except InvalidOperation:
                return None, None, f"Finishing qty must be a valid number for row {row_number}."

            if finishing_qty_val <= 0:
                return None, None, f"Finishing qty must be greater than 0 for row {row_number}."

        auto_paper_rate, _ = _get_count_based_rate(paper, paper_qty_val, customer_type_value, side=side)
        auto_finishing_rate = Decimal('0.00')
        if finishing:
            auto_finishing_rate, _ = _get_finishing_rate(finishing, finishing_qty_val, customer_type_value, side=side)

        try:
            paper_rate_val = Decimal(paper_rate) if paper_rate else auto_paper_rate
            finishing_rate_val = (
                Decimal(finishing_rate)
                if finishing_rate
                else (auto_finishing_rate if auto_finishing_rate is not None else Decimal('0.00'))
            )
        except InvalidOperation:
            return None, None, f"Rate must be a valid number for row {row_number}."

        item_label = item_name or paper.name

        if paper_rate_val is None:
            return None, None, (
                f"Add a paper rate for '{item_label}', or configure a paper slab for the selected count and side."
            )

        if finishing and auto_finishing_rate is None and not finishing_rate:
            return None, None, (
                f"Add a finishing rate for '{item_label}', or configure a finishing slab for the selected count and side."
            )

        rate_val = paper_rate_val + finishing_rate_val
        auto_amount_val = (paper_qty_val * paper_rate_val) + (finishing_qty_val * finishing_rate_val)

        if amt:
            try:
                amt_val = Decimal(amt)
            except InvalidOperation:
                return None, None, f"Amount must be a valid number for row {row_number}."

            if abs(amt_val - auto_amount_val) > Decimal('0.009'):
                paper_rate_val, finishing_rate_val = _rebalance_rates_for_amount(
                    paper_quantity=paper_qty_val,
                    finishing_quantity=finishing_qty_val,
                    paper_rate=paper_rate_val,
                    finishing_rate=finishing_rate_val,
                    amount=amt_val,
                )
                rate_val = paper_rate_val + finishing_rate_val
        else:
            amt_val = auto_amount_val

        if amt_val < 0:
            return None, None, f"Amount cannot be negative for row {row_number}."

        total_amount += amt_val
        items_to_create.append({
            'paper': paper,
            'item_name': item_name,
            'finishing': finishing,
            'side': side,
            'quantity': int(paper_qty_val),
            'paper_quantity': int(paper_qty_val),
            'finishing_quantity': int(finishing_qty_val),
            'paper_rate': paper_rate_val,
            'finishing_rate': finishing_rate_val,
            'rate': rate_val,
            'amount': amt_val,
        })

    if not items_to_create:
        return None, None, "At least one item row required"

    return items_to_create, total_amount, None

@login_required
def stock_item_autocomplete(request):
    q = request.GET.get('q', '')
    items = StockItem.objects.filter(name__icontains=q)[:10]
    return JsonResponse([
        {'id': i.id, 'name': i.name, 'gsm': i.gsm, 'category_id': i.category_id}
        for i in items
    ], safe=False)

@login_required
def category_autocomplete(request):
    q = request.GET.get('q', '')
    cats = ItemCategory.objects.filter(name__icontains=q)[:10]
    return JsonResponse([
        {'id': c.id, 'name': c.name}
        for c in cats
    ], safe=False)

@login_required
def shop_autocomplete(request):
    q = request.GET.get('q', '')
    shops = Shop.objects.filter(name__icontains=q)[:10]
    return JsonResponse([{'id': s.id, 'name': s.name} for s in shops], safe=False)

@login_required
def gsm_autocomplete(request):
    q = request.GET.get('q', '')
    gsms = (
        StockItem.objects
        .filter(gsm__icontains=q)
        .values_list('gsm', flat=True)
        .distinct()
        .order_by('gsm')[:10]
    )
    return JsonResponse([{'gsm': g} for g in gsms], safe=False)




@login_required
def shop_daily_entry_create(request):
    final_shop_id = request.session.get('employee_shop_id')
    if not final_shop_id:
        return redirect('select_shop')

    base_template = 'employee_base.html' if hasattr(request.user, 'employee') else 'admin_base.html'

    if request.method == "POST":
        customer_id = request.POST.get('customer_id')
        customer_name = request.POST.get('customer_name', '').strip()
        customer_type = request.POST.get('customer_type')
        customer_phone = request.POST.get('customer_phone', '').strip()
        customer, customer_error = _resolve_daily_entry_customer(
            customer_id=customer_id,
            customer_name=customer_name,
            customer_type=customer_type,
            customer_phone=customer_phone,
        )
        if customer_error:
            messages.error(request, customer_error)
            return redirect('shop_daily_entry_create')

        payment = request.POST.get('payment')
        is_credit = request.POST.get('is_credit') == 'on'

        if payment == 'credit' or is_credit:
            is_credit = True
            payment = None
        else:
            if not payment:
                messages.error(request, "Payment method required")
                return redirect('shop_daily_entry_create')

        customer_type_value = customer.customer_type
        items_to_create, total_amount, items_error = _build_daily_entry_items(
            post_data=request.POST,
            customer_type_value=customer_type_value,
        )
        if items_error:
            messages.error(request, items_error)
            return redirect('shop_daily_entry_create')

        with transaction.atomic():
            entry = ShopDailyEntry.objects.create(
                shop_id=final_shop_id,
                date=request.POST.get('date') or timezone.now().date(),
                customer=customer,
                payment=payment,
                is_credit=is_credit,
                total_amount=total_amount
            )

            for item in items_to_create:
                ShopDailyEntryItem.objects.create(
                    entry=entry,
                    paper=item['paper'],
                    item_name=item['item_name'],
                    finishing=item['finishing'],
                    side=item['side'],
                    quantity=item['quantity'],
                    paper_quantity=item['paper_quantity'],
                    finishing_quantity=item['finishing_quantity'],
                    paper_rate=item['paper_rate'],
                    finishing_rate=item['finishing_rate'],
                    rate=item['rate'],
                    amount=item['amount'],
                )

                stock_obj, _ = StockQuantity.objects.get_or_create(
                    item=item['paper'],
                    defaults={'quantity': 0}
                )
                stock_obj.quantity -= int(item['paper_quantity'])
                stock_obj.save()

            if is_credit:
                customer.balance = (customer.balance or Decimal('0.00')) + total_amount
                customer.save()

        messages.success(request, "Shop daily entry created successfully!")

        return redirect('shop_daily_entry_detail', pk=entry.id)

    last_entries = ShopDailyEntry.objects.filter(
        shop_id=final_shop_id
    ).order_by('-id')[:10]

    return render(request, 'shop_daily_entry/create.html', {
        'base_template': base_template,
        'last_entries': last_entries,
        'is_edit': False
    })

from django.core.paginator import Paginator
from django.db.models import Q

@login_required 
def shop_daily_entry_list(request): 
    # Get search query 
    search_query = request.GET.get('search', '').strip() 
    
    # Get filter parameters
    shop_filter = request.GET.get('shop', '')
    customer_filter = request.GET.get('customer', '')
    paper_filter = request.GET.get('paper', '')
    side_filter = request.GET.get('side', '')
    payment_filter = request.GET.get('payment', '')
    start_date = request.GET.get('start', '')
    end_date = request.GET.get('end', '')
    
    # Base queryset
    entries_list = ( 
        ShopDailyEntry.objects 
        .select_related('shop', 'customer') 
        .prefetch_related('items__paper', 'items__finishing')
    ) 
    
    # Apply filters
    if shop_filter:
        entries_list = entries_list.filter(shop_id=shop_filter)
    
    if customer_filter:
        entries_list = entries_list.filter(customer_id=customer_filter)
    
    if paper_filter:
        entries_list = entries_list.filter(items__paper_id=paper_filter).distinct()
    
    if side_filter:
        entries_list = entries_list.filter(items__side=side_filter).distinct()
    
    if payment_filter:
        if payment_filter == 'credit':
            entries_list = entries_list.filter(is_credit=True)
        else:
            entries_list = entries_list.filter(payment=payment_filter, is_credit=False)
    
    if start_date:
        entries_list = entries_list.filter(date__gte=start_date)
    
    if end_date:
        entries_list = entries_list.filter(date__lte=end_date)
    
    # Apply search filter
    if search_query: 
        entries_list = entries_list.filter( 
            Q(shop__name__icontains=search_query) | 
            Q(customer__name__icontains=search_query) | 
            Q(date__icontains=search_query) | 
            Q(payment__icontains=search_query) | 
            Q(total_amount__icontains=search_query)
        ) 
    
    # Order entries
    entries_list = entries_list.order_by('shop__name', '-date') 
    
    # Pagination 
    paginator = Paginator(entries_list, 10)  # Show 10 entries per page
    page_number = request.GET.get('page', 1) 
    entries = paginator.get_page(page_number) 
 
    final_shop_id, base_template, redirect_response = get_shop_context(request) 
    if redirect_response: 
        return redirect_response 
 
    # Get filter options for dropdowns
    shops = Shop.objects.all().order_by('name')
    customers = Customer.objects.all().order_by('name')
    papers = StockItem.objects.all().order_by('name')  # Changed from Paper to StockItem
    
    return render(request, 'shop_daily_entry/list.html', { 
        'entries': entries, 
        'base_template': base_template,
        'search_query': search_query,
        'shops': shops,
        'customers': customers,
        'papers': papers,
    })


    
@login_required
def shop_daily_entry_detail(request, pk):
    entry = (
        ShopDailyEntry.objects
        .select_related('shop', 'customer')
        .prefetch_related('items__paper', 'items__finishing')
        .get(pk=pk)
    )

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    return render(request, 'shop_daily_entry/detail.html', {
        'entry': entry,
        'items': entry.items.all(),
        'base_template': base_template,
    })


@login_required
def shop_daily_entry_detail_pdf(request, pk):
    entry = (
        ShopDailyEntry.objects
        .select_related('shop', 'customer')
        .prefetch_related('items__paper', 'items__finishing')
        .get(pk=pk)
    )

    header_url = request.build_absolute_uri(static('img/link_header2.png'))

    html = render_to_string('shop_daily_entry/detail_pdf.html', {
        'entry': entry,
        'items': entry.items.all(),
        'header_url': header_url
    })

    pdf = build_pdf_bytes(html, request.build_absolute_uri())
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="bill_{entry.id}.pdf"'
    return response

@login_required
def shop_daily_entry_edit(request, pk):
    entry = get_object_or_404(
        ShopDailyEntry.objects
        .select_related('customer', 'shop')
        .prefetch_related('items__paper', 'items__finishing'),
        pk=pk
    )

    if request.method == "POST":
        old_customer = entry.customer
        old_is_credit = entry.is_credit
        old_total = entry.total_amount or Decimal('0.00')

        # update shop if provided
        shop_id = request.POST.get('shop')
        if shop_id:
            entry.shop_id = shop_id

        date_value = request.POST.get('date')
        if date_value:
            entry.date = date_value

        # Customer
        customer_id = request.POST.get('customer_id')
        customer_name = request.POST.get('customer_name', '').strip()
        customer_type = request.POST.get('customer_type')
        customer_phone = request.POST.get('customer_phone', '').strip()
        customer, customer_error = _resolve_daily_entry_customer(
            customer_id=customer_id,
            customer_name=customer_name,
            customer_type=customer_type,
            customer_phone=customer_phone,
        )
        if customer_error:
            messages.error(request, customer_error)
            return redirect('shop_daily_entry_edit', pk=entry.id)

        entry.customer = customer

        # Payment
        payment = request.POST.get('payment')
        is_credit = request.POST.get('is_credit') == 'on'
        if payment == 'credit' or is_credit:
            is_credit = True
            payment = None
        else:
            if not payment:
                messages.error(request, "Payment method required")
                return redirect('shop_daily_entry_edit', pk=entry.id)

        customer_type_value = customer.customer_type
        items_to_create, total_amount, items_error = _build_daily_entry_items(
            post_data=request.POST,
            customer_type_value=customer_type_value,
        )
        if items_error:
            messages.error(request, items_error)
            return redirect('shop_daily_entry_edit', pk=entry.id)

        with transaction.atomic():
            # Restore stock from old items
            for old_item in entry.items.all():
                stock_old, _ = StockQuantity.objects.get_or_create(
                    item=old_item.paper,
                    defaults={'quantity': 0}
                )
                stock_old.quantity += int(old_item.effective_paper_quantity)
                stock_old.save()

            # Delete old items
            entry.items.all().delete()

            # Update entry
            entry.payment = payment
            entry.is_credit = is_credit
            entry.total_amount = total_amount
            entry.save()

            # Create new items and reduce stock
            for item in items_to_create:
                ShopDailyEntryItem.objects.create(
                    entry=entry,
                    paper=item['paper'],
                    item_name=item['item_name'],
                    finishing=item['finishing'],
                    side=item['side'],
                    quantity=item['quantity'],
                    paper_quantity=item['paper_quantity'],
                    finishing_quantity=item['finishing_quantity'],
                    paper_rate=item['paper_rate'],
                    finishing_rate=item['finishing_rate'],
                    rate=item['rate'],
                    amount=item['amount'],
                )

                stock_new, _ = StockQuantity.objects.get_or_create(
                    item=item['paper'],
                    defaults={'quantity': 0}
                )
                stock_new.quantity -= int(item['paper_quantity'])
                stock_new.save()

            # Update balance
            if old_is_credit:
                old_customer.balance = (old_customer.balance or Decimal('0.00')) - old_total
                old_customer.save(update_fields=['balance'])

            if is_credit:
                customer.balance = (customer.balance or Decimal('0.00')) + total_amount
                customer.save(update_fields=['balance'])

        messages.success(request, "Shop daily entry updated successfully!")


        return redirect('shop_daily_entry_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    return render(request, 'shop_daily_entry/create.html', {
        'entry': entry,
        'base_template': base_template,
        'is_edit': True
    })

@login_required
def shop_daily_entry_delete(request, pk):
    entry = get_object_or_404(ShopDailyEntry, pk=pk)
    entry.delete()
    messages.success(request, "Shop daily entry deleted successfully!")

    return redirect('shop_daily_entry_list')



@login_required
def press_customer_list(request):
    customers = Customer.objects.filter(customer_type='press')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    return render(request, 'customer/press_list.html', {
        'customers': customers,
        'base_template': base_template
    })

@login_required
def press_customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk, customer_type='press')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    qs = (
        ShopDailyEntry.objects
        .filter(customer=customer)
        .select_related('shop')
        .prefetch_related('items__paper', 'items__finishing')
    )

    filter_type = request.GET.get('filter', 'day')
    today = timezone.now().date()

    if filter_type == 'day':
        start = today; end = today
    elif filter_type == 'week':
        start = today - timedelta(days=today.weekday()); end = start + timedelta(days=6)
    elif filter_type == 'month':
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    elif filter_type == 'year':
        start = today.replace(month=1, day=1); end = today.replace(month=12, day=31)
    elif filter_type == 'custom':
        start = request.GET.get('start') or None
        end = request.GET.get('end') or None
    else:
        start = today; end = today

    if start and end:
        qs = qs.filter(date__range=[start, end])

    total_amount = qs.aggregate(total=Sum('items__amount'))['total'] or 0

    return render(request, 'customer/press_detail.html', {
        'customer': customer,
        'entries': qs.order_by('-date'),
        'total_amount': total_amount,
        'filter_type': filter_type,
        'start': start,
        'end': end,
        'base_template': base_template
    })


@login_required
def press_customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk, customer_type='press')

    if request.method == "POST":
        customer.name = request.POST.get('name')
        customer.phone = request.POST.get('phone')
        customer.save()

        messages.success(request, "Press customer updated successfully!")

        return redirect('press_customer_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    return render(request, 'customer/press_edit.html', {
        'customer': customer,
        'base_template': base_template
    })

@login_required
def press_customer_detail_pdf(request, pk):
    customer = get_object_or_404(Customer, pk=pk, customer_type='press')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    qs = (
        ShopDailyEntry.objects
        .filter(customer=customer)
        .select_related('shop')
        .prefetch_related('items__paper', 'items__finishing')
    )

    filter_type = request.GET.get('filter', 'day')
    today = timezone.now().date()

    if filter_type == 'day':
        start = today; end = today
    elif filter_type == 'week':
        start = today - timedelta(days=today.weekday()); end = start + timedelta(days=6)
    elif filter_type == 'month':
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    elif filter_type == 'year':
        start = today.replace(month=1, day=1); end = today.replace(month=12, day=31)
    elif filter_type == 'custom':
        start = request.GET.get('start') or None
        end = request.GET.get('end') or None
    else:
        start = today; end = today

    if start and end:
        qs = qs.filter(date__range=[start, end])

    total_amount = qs.aggregate(total=Sum('items__amount'))['total'] or 0

    header_url = request.build_absolute_uri(static('img/link_header.png'))

    html = render_to_string('customer/press_detail_pdf.html', {
        'customer': customer,
        'entries': qs.order_by('-date'),
        'total_amount': total_amount,
        'start': start,
        'end': end,
        'filter_type': filter_type,
        'header_url': header_url
    })

    pdf = build_pdf_bytes(html, request.build_absolute_uri())
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="press_customer_detail.pdf"'
    return response


@login_required
def press_customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk, customer_type='press')
    
    customer_name = customer.name  # optional (for better message)
    customer.delete()

    messages.success(request, f"Press customer '{customer_name}' deleted successfully!")

    return redirect('press_customer_list')





@login_required
def normal_customer_list(request):
    customers = (
        Customer.objects
        .filter(customer_type='normal')
        .annotate(total_purchase=Sum('shopdailyentry__total_amount'))
    )

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    return render(request, 'customer/normal_list.html', {
        'customers': customers,
        'base_template': base_template
    })

@login_required
def normal_customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk, customer_type='normal')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    qs = (
        ShopDailyEntry.objects
        .filter(customer=customer)
        .select_related('shop')
        .prefetch_related('items__paper', 'items__finishing')
    )

    filter_type = request.GET.get('filter', 'day')
    today = timezone.now().date()

    if filter_type == 'day':
        start = today; end = today
    elif filter_type == 'week':
        start = today - timedelta(days=today.weekday()); end = start + timedelta(days=6)
    elif filter_type == 'month':
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    elif filter_type == 'year':
        start = today.replace(month=1, day=1); end = today.replace(month=12, day=31)
    elif filter_type == 'custom':
        start = request.GET.get('start') or None
        end = request.GET.get('end') or None
    else:
        start = today; end = today

    if start and end:
        qs = qs.filter(date__range=[start, end])

    total_amount = qs.aggregate(total=Sum('items__amount'))['total'] or 0

    return render(request, 'customer/normal_detail.html', {
        'customer': customer,
        'entries': qs.order_by('-date'),
        'total_amount': total_amount,
        'filter_type': filter_type,
        'start': start,
        'end': end,
        'base_template': base_template
    })

@login_required
def normal_customer_detail_pdf(request, pk):
    customer = get_object_or_404(Customer, pk=pk, customer_type='normal')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    qs = (
        ShopDailyEntry.objects
        .filter(customer=customer)
        .select_related('shop')
        .prefetch_related('items__paper', 'items__finishing')
    )

    filter_type = request.GET.get('filter', 'day')
    today = timezone.now().date()

    if filter_type == 'day':
        start = today; end = today
    elif filter_type == 'week':
        start = today - timedelta(days=today.weekday()); end = start + timedelta(days=6)
    elif filter_type == 'month':
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    elif filter_type == 'year':
        start = today.replace(month=1, day=1); end = today.replace(month=12, day=31)
    elif filter_type == 'custom':
        start = request.GET.get('start') or None
        end = request.GET.get('end') or None
    else:
        start = today; end = today

    if start and end:
        qs = qs.filter(date__range=[start, end])

    total_amount = qs.aggregate(total=Sum('items__amount'))['total'] or 0

    header_url = request.build_absolute_uri(static('img/link_header.png'))

    html = render_to_string('customer/normal_detail_pdf.html', {
        'customer': customer,
        'entries': qs.order_by('-date'),
        'total_amount': total_amount,
        'start': start,
        'end': end,
        'filter_type': filter_type,
        'header_url': header_url
    })

    pdf = build_pdf_bytes(html, request.build_absolute_uri())
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="normal_customer_detail.pdf"'
    return response


@login_required
def normal_customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk, customer_type='normal')

    if request.method == "POST":
        customer.name = request.POST.get('name')
        customer.phone = request.POST.get('phone')
        customer.save()
        messages.success(request, "Customer updated successfully!")
        return redirect('normal_customer_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    return render(request, 'customer/normal_edit.html', {
        'customer': customer,
        'base_template': base_template
    })



@login_required
def normal_customer_delete(request, pk):
    if request.method != "POST":
        return redirect('normal_customer_list')

    customer = get_object_or_404(Customer, pk=pk, customer_type='normal')

    customer_name = customer.name
    customer.delete()

    messages.success(request, f"Customer '{customer_name}' deleted successfully!")

    return redirect('normal_customer_list')





@login_required
def customer_payment_create(request):
    customers = Customer.objects.filter(balance__gt=0).order_by('-customer_type', 'name')

    if request.method == "POST":
        customer_id = request.POST.get('customer')
        amount = request.POST.get('amount')

        if not customer_id or not amount:
            messages.error(request, "Customer and amount required")
            return redirect('customer_payment_create')

        customer = get_object_or_404(Customer, id=customer_id)
        amount_value = Decimal(amount)

        CustomerPayment.objects.create(
            customer=customer,
            amount=amount_value,
            date=request.POST.get('date') or timezone.now().date()
        )

        customer.balance = (customer.balance or Decimal('0.00')) - amount_value
        customer.save(update_fields=['balance'])

        messages.success(request, "Customer payment recorded successfully!")

        return redirect('customer_payment_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    return render(request, 'customer_payment/create.html', {
        'customers': customers,
        'base_template': base_template
    })

@login_required
def customer_payment_list(request):
    payments = CustomerPayment.objects.select_related('customer').order_by('-date')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    return render(request, 'customer_payment/list.html', {
        'payments': payments,
        'base_template': base_template
    })

@login_required
def customer_payment_delete(request, pk):
    payment = get_object_or_404(CustomerPayment, pk=pk)
    customer = payment.customer

    # rollback balance
    customer.balance = (customer.balance or Decimal('0')) + payment.amount
    customer.save(update_fields=['balance'])

    payment.delete()
    messages.success(request, "Customer payment deleted successfully!")

    return redirect('customer_payment_list')





@login_required
def purchase_item_create(request):
    if request.method == "POST":
        category_id = request.POST.get('category_id')
        stock_item_id = request.POST.get('stock_item_id')
        gsm = request.POST.get('gsm')
        quantity = request.POST.get('quantity')
        amount = request.POST.get('amount')

        category = ItemCategory.objects.get(id=category_id)
        stock_item = StockItem.objects.get(id=stock_item_id)

        item = PurchaseItem.objects.create(
            category=category,
            stock_item=stock_item,
            gsm=gsm,
            quantity=quantity,
            amount=amount
        )

        # ✅ add stock
        stock_qty, _ = StockQuantity.objects.get_or_create(item=stock_item, defaults={'quantity': 0})
        stock_qty.quantity += int(float(quantity))
        stock_qty.save()

        messages.success(request, "Purchase item added and stock updated successfully!")

        return redirect('purchase_item_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    return render(request, 'purchase_item/create.html', {'base_template': base_template})

@login_required
def purchase_item_list(request):
    items = PurchaseItem.objects.select_related('stock_item').order_by('-id')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    return render(request, 'purchase_item/list.html', {
        'items': items,
        'base_template': base_template
    })

@login_required
def purchase_item_detail(request, pk):
    item = get_object_or_404(PurchaseItem, pk=pk)

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    return render(request, 'purchase_item/detail.html', {
        'item': item,
        'base_template': base_template
    })

    stock_items = StockItem.objects.all()

    if request.method == "POST":
        PurchaseItem.objects.create(
            stock_item_id=request.POST.get('stock_item'),
            quantity=request.POST.get('quantity'),
            rate=request.POST.get('rate'),
            amount=request.POST.get('amount'),
        )
        return redirect('purchase_item_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    return render(request, 'purchase_item/create.html', {
        'stock_items': stock_items,
        'base_template': base_template
    })

@login_required
def purchase_item_edit(request, pk):
    item = get_object_or_404(PurchaseItem, pk=pk)

    if request.method == "POST":
        old_stock = item.stock_item
        old_qty = int(float(item.quantity))

        item.category_id = request.POST.get('category_id') or item.category_id
        item.stock_item_id = request.POST.get('stock_item_id') or item.stock_item_id
        item.gsm = request.POST.get('gsm') or item.gsm
        item.quantity = request.POST.get('quantity')
        item.amount = request.POST.get('amount')
        item.save()

        new_stock = item.stock_item
        new_qty = int(float(item.quantity))

        # rollback old
        old_sq, _ = StockQuantity.objects.get_or_create(item=old_stock, defaults={'quantity': 0})
        old_sq.quantity -= old_qty
        old_sq.save()

        # apply new
        new_sq, _ = StockQuantity.objects.get_or_create(item=new_stock, defaults={'quantity': 0})
        new_sq.quantity += new_qty
        new_sq.save()

        messages.success(request, "Purchase item updated successfully!")

        return redirect('purchase_item_list')

    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    return render(request, 'purchase_item/edit.html', {
        'item': item,
        'base_template': base_template
    })

@login_required
def purchase_item_delete(request, pk):
    item = get_object_or_404(PurchaseItem, pk=pk)
    qty = int(float(item.quantity))

    stock_qty, _ = StockQuantity.objects.get_or_create(item=item.stock_item, defaults={'quantity': 0})
    stock_qty.quantity -= qty
    stock_qty.save()

    item.delete()
    messages.success(request, "Purchase item deleted successfully!")
    return redirect('purchase_item_list')




@login_required
def shop_daily_entry_report(request):
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    qs = ShopDailyEntry.objects.select_related('shop', 'customer').prefetch_related('items__paper', 'items__finishing')

    def clean_id(val):
        if not val or val in ("None", "null", "undefined"):
            return None
        return val

    filter_type = request.GET.get('filter', 'day')

    shop_id = clean_id(request.GET.get('shop_id'))
    customer_id = clean_id(request.GET.get('customer_id'))
    paper_id = clean_id(request.GET.get('paper_id'))

    side = request.GET.get('side') or ''
    payment = request.GET.get('payment') or ''

    today = timezone.now().date()

    if filter_type == 'day':
        start = today; end = today
    elif filter_type == 'week':
        start = today - timedelta(days=today.weekday()); end = start + timedelta(days=6)
    elif filter_type == 'month':
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    elif filter_type == 'year':
        start = today.replace(month=1, day=1); end = today.replace(month=12, day=31)
    elif filter_type == 'custom':
        start = request.GET.get('start') or None
        end = request.GET.get('end') or None
    else:
        start = today; end = today

    if shop_id:
        qs = qs.filter(shop_id=shop_id)
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    if paper_id:
        qs = qs.filter(items__paper_id=paper_id)
    if side:
        qs = qs.filter(items__side=side)
    if payment:
        if payment == 'credit':
            qs = qs.filter(is_credit=True)
        else:
            qs = qs.filter(payment=payment)

    if start and end:
        qs = qs.filter(date__range=[start, end])

    qs = qs.distinct()

    total_amount = (
        qs.aggregate(total=Sum('items__amount'))['total'] or 0
    )

    return render(request, 'reports/daily_entry_report.html', {
        'entries': qs.order_by('-date'),
        'filter_type': filter_type,
        'start': start,
        'end': end,
        'selected_shop': shop_id,
        'selected_customer': customer_id,
        'selected_paper': paper_id,
        'selected_side': side,
        'selected_payment': payment,
        'total_amount': total_amount,
        'base_template': base_template
    })

@login_required
def shop_daily_entry_report_pdf(request):
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    qs = ShopDailyEntry.objects.select_related('shop', 'customer').prefetch_related('items__paper', 'items__finishing')

    def clean_id(val):
        if not val or val in ("None", "null", "undefined"):
            return None
        return val

    filter_type = request.GET.get('filter', 'day')

    shop_id = clean_id(request.GET.get('shop_id'))
    customer_id = clean_id(request.GET.get('customer_id'))
    paper_id = clean_id(request.GET.get('paper_id'))

    side = request.GET.get('side') or ''
    payment = request.GET.get('payment') or ''

    today = timezone.now().date()

    if filter_type == 'day':
        start = today; end = today
    elif filter_type == 'week':
        start = today - timedelta(days=today.weekday()); end = start + timedelta(days=6)
    elif filter_type == 'month':
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    elif filter_type == 'year':
        start = today.replace(month=1, day=1); end = today.replace(month=12, day=31)
    elif filter_type == 'custom':
        start = request.GET.get('start') or None
        end = request.GET.get('end') or None
    else:
        start = today; end = today

    if shop_id: qs = qs.filter(shop_id=shop_id)
    if customer_id: qs = qs.filter(customer_id=customer_id)
    if paper_id: qs = qs.filter(items__paper_id=paper_id)
    if side: qs = qs.filter(items__side=side)
    if payment:
        if payment == 'credit':
            qs = qs.filter(is_credit=True)
        else:
            qs = qs.filter(payment=payment)

    if start and end:
        qs = qs.filter(date__range=[start, end])

    qs = qs.distinct()

    total_amount = qs.aggregate(total=Sum('items__amount'))['total'] or 0

    header_url = request.build_absolute_uri(static('img/link_header.png'))

    html = render_to_string('reports/daily_entry_report_pdf.html', {
        'entries': qs.order_by('-date'),
        'total_amount': total_amount,
        'start': start,
        'end': end,
        'filter_type': filter_type,
        'header_url': header_url
    })

    pdf = build_pdf_bytes(html, request.build_absolute_uri())
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="daily_entry_report.pdf"'
    return response




@login_required
def stock_report(request):
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    qs = StockQuantity.objects.select_related('item', 'item__category')

    def clean(val):
        if not val or val in ("None", "null", "undefined"):
            return None
        return val

    item_name = (request.GET.get('item_name') or '').strip()
    category_id = clean(request.GET.get('category_id'))
    gsm = clean(request.GET.get('gsm'))
    low = request.GET.get('low') or ''

    if item_name:
        qs = qs.filter(item__name__icontains=item_name)

    if category_id:
        qs = qs.filter(item__category_id=category_id)

    if gsm:
        qs = qs.filter(item__gsm=gsm)

    if low == '1':
        qs = qs.filter(quantity__lte=0)

    return render(request, 'reports/stock_report.html', {
        'stocks': qs.order_by('item__name'),
        'base_template': base_template
    })

@login_required
def stock_report_pdf(request):
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    qs = StockQuantity.objects.select_related('item', 'item__category')

    item_id = request.GET.get('item_id')
    category_id = request.GET.get('category_id')
    gsm = request.GET.get('gsm')
    low = request.GET.get('low')

    if item_id and item_id not in ("None","null","undefined"):
        qs = qs.filter(item_id=item_id)
    if category_id and category_id not in ("None","null","undefined"):
        qs = qs.filter(item__category_id=category_id)
    if gsm and gsm not in ("None","null","undefined"):
        qs = qs.filter(item__gsm=gsm)
    if low == '1':
        qs = qs.filter(quantity__lte=0)

    header_url = request.build_absolute_uri(static('img/link_header.png'))

    html = render_to_string('reports/stock_report_pdf.html', {
        'stocks': qs.order_by('item__name'),
        'header_url': header_url,   # ✅ pass header
    })
    pdf = build_pdf_bytes(html, request.build_absolute_uri())
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="stock_report.pdf"'
    return response



@login_required
def payment_statement_report(request):
    final_shop_id, base_template, redirect_response = get_shop_context(request)
    if redirect_response:
        return redirect_response

    def clean_id(val):
        if not val or val in ("None","null","undefined"):
            return None
        return val

    customer_id = clean_id(request.GET.get('customer_id'))
    filter_type = request.GET.get('filter', 'day')

    today = timezone.now().date()
    if filter_type == 'day':
        start = today; end = today
    elif filter_type == 'week':
        start = today - timedelta(days=today.weekday()); end = start + timedelta(days=6)
    elif filter_type == 'month':
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    elif filter_type == 'year':
        start = today.replace(month=1, day=1); end = today.replace(month=12, day=31)
    elif filter_type == 'custom':
        start = request.GET.get('start') or None
        end = request.GET.get('end') or None
    else:
        start = today; end = today

    if not customer_id:
        return render(request, 'reports/payment_statement.html', {
            'customers_list': Customer.objects.all(),
            'base_template': base_template
        })

    customer = Customer.objects.get(id=customer_id)

    credit_before = ShopDailyEntry.objects.filter(
        customer_id=customer_id, is_credit=True, date__lt=start
    ).aggregate(total=Sum('items__amount'))['total'] or 0

    payment_before = CustomerPayment.objects.filter(
        customer_id=customer_id, date__lt=start
    ).aggregate(total=Sum('amount'))['total'] or 0

    opening_balance = Decimal(credit_before) - Decimal(payment_before)

    credits = ShopDailyEntry.objects.filter(
        customer_id=customer_id, is_credit=True, date__range=[start, end]
    ).values('date').annotate(amount=Sum('items__amount'))

    payments = CustomerPayment.objects.filter(
        customer_id=customer_id, date__range=[start, end]
    ).values('date', 'amount')

    transactions = []
    for c in credits:
        transactions.append({
            'date': c['date'],
            'type': 'Credit',
            'debit': Decimal(c['amount'] or 0),
            'credit': Decimal('0')
        })
    for p in payments:
        transactions.append({
            'date': p['date'],
            'type': 'Payment',
            'debit': Decimal('0'),
            'credit': Decimal(p['amount'])
        })

    transactions.sort(key=lambda x: x['date'])

    balance = opening_balance
    for t in transactions:
        balance += t['debit']
        balance -= t['credit']
        t['balance'] = balance

    return render(request, 'reports/payment_statement.html', {
        'customer': customer,
        'transactions': transactions,
        'opening_balance': opening_balance,
        'customers_list': Customer.objects.all(),
        'filter_type': filter_type,
        'start': start,
        'end': end,
        'base_template': base_template
    })

@login_required
def payment_statement_report_pdf(request):
    def clean_id(val):
        if not val or val in ("None","null","undefined"):
            return None
        return val

    customer_id = clean_id(request.GET.get('customer_id'))
    filter_type = request.GET.get('filter', 'day')

    today = timezone.now().date()
    if filter_type == 'day':
        start = today; end = today
    elif filter_type == 'week':
        start = today - timedelta(days=today.weekday()); end = start + timedelta(days=6)
    elif filter_type == 'month':
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    elif filter_type == 'year':
        start = today.replace(month=1, day=1); end = today.replace(month=12, day=31)
    elif filter_type == 'custom':
        start = request.GET.get('start') or None
        end = request.GET.get('end') or None
    else:
        start = today; end = today

    if not customer_id:
        return HttpResponse("Customer required", status=400)

    customer = Customer.objects.get(id=customer_id)

    credit_before = ShopDailyEntry.objects.filter(
        customer_id=customer_id, is_credit=True, date__lt=start
    ).aggregate(total=Sum('items__amount'))['total'] or 0

    payment_before = CustomerPayment.objects.filter(
        customer_id=customer_id, date__lt=start
    ).aggregate(total=Sum('amount'))['total'] or 0

    opening_balance = Decimal(credit_before) - Decimal(payment_before)

    credits = ShopDailyEntry.objects.filter(
        customer_id=customer_id, is_credit=True, date__range=[start, end]
    ).values('date').annotate(amount=Sum('items__amount'))

    payments = CustomerPayment.objects.filter(
        customer_id=customer_id, date__range=[start, end]
    ).values('date', 'amount')

    transactions = []
    for c in credits:
        transactions.append({'date': c['date'], 'type': 'Credit', 'debit': Decimal(c['amount'] or 0), 'credit': Decimal('0')})
    for p in payments:
        transactions.append({'date': p['date'], 'type': 'Payment', 'debit': Decimal('0'), 'credit': Decimal(p['amount'])})

    transactions.sort(key=lambda x: x['date'])

    balance = opening_balance
    for t in transactions:
        balance += t['debit']
        balance -= t['credit']
        t['balance'] = balance

    header_url = request.build_absolute_uri(static('img/link_header.png'))

    html = render_to_string('reports/payment_statement_pdf.html', {
        'customer': customer,
        'transactions': transactions,
        'opening_balance': opening_balance,
        'start': start,
        'end': end,
        'filter_type': filter_type,
        'header_url': header_url
    })

    pdf = build_pdf_bytes(html, request.build_absolute_uri())
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="payment_statement.pdf"'
    return response




# ACTIVITY LOG


from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.http import HttpResponseForbidden
from .models import ActivityLog

@login_required
def activity_log_list(request):
    if request.user.role != 'admin':
        return redirect('login')

    logs_list = ActivityLog.objects.select_related('user').order_by('-created_at')

    # Pagination
    paginator = Paginator(logs_list, 10)
    page_number = request.GET.get('page', 1)
    logs = paginator.get_page(page_number)

    return render(request, 'activity_log_list.html', {'logs': logs})


@login_required
@require_POST
def activity_log_bulk_delete(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden('Permission denied')

    log_ids_str = request.POST.get('log_ids', '')

    if not log_ids_str:
        return redirect('activity_log_list')

    try:
        log_ids = [int(i) for i in log_ids_str.split(',') if i.strip()]
        ActivityLog.objects.filter(id__in=log_ids).delete()
    except Exception:
        pass

    return redirect('activity_log_list')


@login_required
@require_POST
def activity_log_delete(request, log_id):
    if request.user.role != 'admin':
        return HttpResponseForbidden('Permission denied')

    try:
        ActivityLog.objects.filter(id=log_id).delete()
    except Exception:
        pass

    return redirect('activity_log_list')
