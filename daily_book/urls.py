from django import views
from django.contrib import admin
from django.urls import path
from .views import *

urlpatterns = [
    path('', login_view, name='login'),
    path('logout/', logout_view, name='logout'),

    path('dashboard/admin/', admin_dashboard, name='admin_dashboard'),
    path('dashboard/employee/', employee_dashboard, name='employee_dashboard'),
    path('dashboard/master/', master_dashboard, name='master_dashboard'),

    path('employee/create/', create_employee, name='create_employee'),
    path('employee/edit/<int:employee_id>/',edit_employee,name='edit_employee'),
    path('employee/list/', employee_list, name='employee_list'),
    path('employee/detail/<int:employee_id>/', employee_detail, name='employee_detail'),
    path('employee/delete/<int:employee_id>/', employee_delete, name='employee_delete'),


    # ================= SHOP =================
    path('shops/', shop_list, name='shop_list'),
    path('shops/add/', shop_create, name='shop_create'),
    path('shops/<int:pk>/', shop_detail, name='shop_detail'),
    path('shops/<int:pk>/edit/', shop_edit, name='shop_edit'),
    path('shops/<int:pk>/delete/', shop_delete, name='shop_delete'),

    # ================= PRINTER =================
    path('printers/', printer_list, name='printer_list'),
    path('printers/add/', printer_create, name='printer_create'),
    path('printers/<int:pk>/', printer_detail, name='printer_detail'),
    path('printers/<int:pk>/edit/', printer_edit, name='printer_edit'),
    path('printers/<int:pk>/delete/', printer_delete, name='printer_delete'),

    # ================= PRINTER COUNTS =================
    path('printer-counts/', printer_count_list, name='printer_count_list'),
    path('printer-counts/add/', printer_count_create, name='printer_count_create'),
    path('printer-counts/<int:pk>/', printer_count_detail, name='printer_count_detail'),
    path('printer-counts/<int:pk>/edit/', printer_count_edit, name='printer_count_edit'),
    path('printer-counts/<int:pk>/delete/', printer_count_delete, name='printer_count_delete'),

    # ================= ITEM CATEGORY =================
    path('categories/', category_list, name='category_list'),
    path('categories/add/', category_create, name='category_create'),
    path('categories/<int:pk>/edit/', category_edit, name='category_edit'),
    path('categories/<int:pk>/delete/', category_delete, name='category_delete'),

    # ================= STOCK ITEM =================
    path('stocks/', stock_list, name='stock_list'),
    path('stocks/add/', stock_create, name='stock_create'),
    path('stocks/<int:pk>/', stock_detail, name='stock_detail'),
    path('stocks/<int:pk>/edit/', stock_edit, name='stock_edit'),
    path('stocks/<int:pk>/delete/', stock_delete, name='stock_delete'),

    # ================= FINISHING =================
    path('finishing/', finishing_list, name='finishing_list'),
    path('finishing/add/', finishing_create, name='finishing_create'),
    path('finishing/<int:pk>/edit/', finishing_edit, name='finishing_edit'),
    path('finishing/<int:pk>/delete/', finishing_delete, name='finishing_delete'),

    # ================= STOCK ADJUSTMENT =================
    path('stock-adjustment/', stock_adjustment_list, name='stock_adjustment_list'),
    path('stock-adjustment/add/', stock_adjustment_create, name='stock_adjustment_create'),
    path('stock-adjustment/<int:pk>/', stock_adjustment_detail, name='stock_adjustment_detail'),
    path('stock-adjustment/<int:pk>/delete/', stock_adjustment_delete, name='stock_adjustment_delete'),


    # ================= SHOP DAILY ENTRY =================
   
    path('select-shop/', select_shop, name='select_shop'),

    path('shop-daily-entry/',shop_daily_entry_list,name='shop_daily_entry_list'),
    path('shop-daily-entry/add/',shop_daily_entry_create,name='shop_daily_entry_create'),
    path('shop-daily-entry/<int:pk>/',shop_daily_entry_detail,name='shop_daily_entry_detail'),
    path('shop-daily-entry/<int:pk>/pdf/', shop_daily_entry_detail_pdf, name='shop_daily_entry_detail_pdf'),
    path('shop-daily-entry/<int:pk>/edit/',shop_daily_entry_edit,name='shop_daily_entry_edit'),
    path('shop-daily-entry/<int:pk>/delete/',shop_daily_entry_delete,name='shop_daily_entry_delete'),

    path('customers/autocomplete/', customer_autocomplete, name='customer_autocomplete'),
    path('customers/<int:customer_id>/latest-entry/', customer_latest_entry_autofill, name='customer_latest_entry_autofill'),
    path('item-names/autocomplete/', item_name_autocomplete, name='item_name_autocomplete'),
    path('papers/autocomplete/', paper_autocomplete, name='paper_autocomplete'),
    path('papers/rate/', paper_rate_lookup, name='paper_rate_lookup'),
    path('finishings/autocomplete/', finishing_autocomplete, name='finishing_autocomplete'),
    path('finishings/rate/', finishing_rate_lookup, name='finishing_rate_lookup'),
    path('stock-items/autocomplete/', stock_item_autocomplete, name='stock_item_autocomplete'),
    path('categories/autocomplete/', category_autocomplete, name='category_autocomplete'),
    path('shops/autocomplete/', shop_autocomplete, name='shop_autocomplete'),
    path('gsm/autocomplete/', gsm_autocomplete, name='gsm_autocomplete'),

    path('customers/press/', press_customer_list, name='press_customer_list'),
    path('customers/press/<int:pk>/', press_customer_detail, name='press_customer_detail'),
    path('customers/press/<int:pk>/pdf/', press_customer_detail_pdf, name='press_customer_detail_pdf'),
    path('customers/press/<int:pk>/edit/', press_customer_edit, name='press_customer_edit'),
    path('customers/press/<int:pk>/delete/', press_customer_delete, name='press_customer_delete'),

    path('customers/normal/', normal_customer_list, name='normal_customer_list'),
    path('customers/normal/<int:pk>/', normal_customer_detail, name='normal_customer_detail'),
    path('customers/normal/<int:pk>/pdf/', normal_customer_detail_pdf, name='normal_customer_detail_pdf'),
    path('customers/normal/<int:pk>/edit/', normal_customer_edit, name='normal_customer_edit'),
    path('customers/normal/<int:pk>/delete/', normal_customer_delete, name='normal_customer_delete'),

    path('customer-payments/', customer_payment_list, name='customer_payment_list'),
    path('customer-payments/add/', customer_payment_create, name='customer_payment_create'),
    path('customer-payments/<int:pk>/delete/', customer_payment_delete, name='customer_payment_delete'),

    path('purchase-items/add/', purchase_item_create, name='purchase_item_create'),
    path('purchase-items/', purchase_item_list, name='purchase_item_list'),
    path('purchase-items/<int:pk>/', purchase_item_detail, name='purchase_item_detail'),
    path('purchase-items/<int:pk>/edit/', purchase_item_edit, name='purchase_item_edit'),
    path('purchase-items/<int:pk>/delete/', purchase_item_delete, name='purchase_item_delete'),

    path('reports/daily-entry/', shop_daily_entry_report, name='shop_daily_entry_report'),
    path('reports/daily-entry/pdf/', shop_daily_entry_report_pdf, name='shop_daily_entry_report_pdf'),

    path('reports/stock/', stock_report, name='stock_report'),
    path('reports/stock/pdf/', stock_report_pdf, name='stock_report_pdf'),

    path('reports/payment-statement/', payment_statement_report, name='payment_statement_report'),
    path('reports/payment-statement/pdf/', payment_statement_report_pdf, name='payment_statement_report_pdf'),

    path('activity-logs/', activity_log_list, name='activity_log_list'),
    path('activity-logs/bulk-delete/', activity_log_bulk_delete, name='activity_log_bulk_delete'),
    path('activity-logs/<int:log_id>/delete/', activity_log_delete, name='activity_log_delete'),





]
