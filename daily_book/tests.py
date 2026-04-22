from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Customer,
    Finishing,
    FinishingRate,
    ItemCategory,
    Shop,
    ShopDailyEntry,
    ShopDailyEntryItem,
    StockItem,
    StockItemRate,
)


class ShopDailyEntryAutocompleteTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            email='admin@example.com',
            password='testpass123',
            name='Admin User',
            role='admin',
        )
        self.client.force_login(self.user)

        self.shop = Shop.objects.create(name='Main Shop', location='Town')
        self.other_shop = Shop.objects.create(name='Second Shop', location='City')
        self.customer = Customer.objects.create(
            name='Acme Prints',
            phone='9876543210',
            customer_type='press',
        )

        category = ItemCategory.objects.create(name='Paper')
        self.paper = StockItem.objects.create(category=category, name='Art Card', gsm=300)
        self.finishing = Finishing.objects.create(name='Lamination')
        StockItemRate.objects.create(
            stock_item=self.paper,
            side='single',
            min_count=1,
            max_count=100,
            normal_rate='2.50',
            press_rate='1.50',
        )
        StockItemRate.objects.create(
            stock_item=self.paper,
            side='double',
            min_count=1,
            max_count=100,
            normal_rate='3.00',
            press_rate='2.00',
        )
        FinishingRate.objects.create(
            finishing=self.finishing,
            side='single',
            min_count=1,
            max_count=100,
            normal_rate='0.75',
            press_rate='0.25',
        )
        FinishingRate.objects.create(
            finishing=self.finishing,
            side='double',
            min_count=1,
            max_count=100,
            normal_rate='1.00',
            press_rate='0.50',
        )

        same_shop_entry = ShopDailyEntry.objects.create(
            shop=self.shop,
            date=timezone.now().date() - timedelta(days=2),
            customer=self.customer,
            payment='upi',
            is_credit=False,
            total_amount='120.00',
        )
        ShopDailyEntryItem.objects.create(
            entry=same_shop_entry,
            paper=self.paper,
            item_name='Business Card',
            finishing=self.finishing,
            side='double',
            quantity=100,
            paper_quantity=100,
            finishing_quantity=100,
            paper_rate='1.00',
            finishing_rate='0.20',
            rate='1.20',
            amount='120.00',
        )

        newer_other_shop_entry = ShopDailyEntry.objects.create(
            shop=self.other_shop,
            date=timezone.now().date(),
            customer=self.customer,
            payment='cash',
            is_credit=False,
            total_amount='60.00',
        )
        ShopDailyEntryItem.objects.create(
            entry=newer_other_shop_entry,
            paper=self.paper,
            item_name='Business Card',
            finishing=None,
            side='single',
            quantity=50,
            paper_quantity=50,
            finishing_quantity=0,
            paper_rate='1.20',
            finishing_rate='0.00',
            rate='1.20',
            amount='60.00',
        )

        session = self.client.session
        session['employee_shop_id'] = self.shop.id
        session.save()

    def test_customer_autocomplete_matches_phone_number(self):
        response = self.client.get(reverse('customer_autocomplete'), {'q': '987654'})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['id'], self.customer.id)
        self.assertEqual(data[0]['name'], self.customer.name)

    def test_customer_autocomplete_matches_name_and_phone_tokens(self):
        response = self.client.get(reverse('customer_autocomplete'), {'q': 'Acme 3210'})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['id'], self.customer.id)

    def test_item_name_autocomplete_returns_distinct_history(self):
        response = self.client.get(reverse('item_name_autocomplete'), {'q': 'Business'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{'name': 'Business Card'}])

    def test_paper_autocomplete_matches_letter_and_number_tokens(self):
        response = self.client.get(reverse('paper_autocomplete'), {'q': 'Art 300'})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['id'], self.paper.id)
        self.assertEqual(data[0]['gsm'], 300)

    def test_paper_autocomplete_matches_compact_letter_number_value(self):
        response = self.client.get(reverse('paper_autocomplete'), {'q': 'Art300'})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['id'], self.paper.id)

    def test_shop_daily_entry_create_page_includes_side_select_hook(self):
        response = self.client.get(reverse('shop_daily_entry_create'))

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'name="side" class="form-control side-select"',
            response.content.decode(),
        )

    def test_paper_rate_lookup_uses_stock_item_rate_model(self):
        response = self.client.get(
            reverse('paper_rate_lookup'),
            {
                'paper_id': self.paper.id,
                'quantity': 10,
                'customer_type': 'press',
                'side': 'single',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'rate': '1.50',
                'range_label': 'Single Side | 1 - 100',
                'paper_name': self.paper.name,
            },
        )

    def test_finishing_rate_lookup_uses_finishing_rate_model(self):
        response = self.client.get(
            reverse('finishing_rate_lookup'),
            {
                'finishing_id': self.finishing.id,
                'quantity': 10,
                'customer_type': 'press',
                'side': 'single',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'rate': '0.25',
                'range_label': 'Single Side | 1 - 100',
                'finishing_name': self.finishing.name,
            },
        )

    def test_shop_daily_entry_create_autocalculates_rates_from_models(self):
        response = self.client.post(
            reverse('shop_daily_entry_create'),
            {
                'customer_name': '9876543210',
                'customer_id': '',
                'customer_type': 'press',
                'customer_phone': '',
                'payment': 'cash',
                'is_credit': 'off',
                'item_name': ['Poster'],
                'paper_text': ['Art300'],
                'paper_id': [''],
                'side': ['single'],
                'finishing_text': ['Lamination'],
                'finishing_id': [''],
                'paper_quantity': ['10'],
                'finishing_quantity': ['10'],
                'paper_rate': [''],
                'finishing_rate': [''],
                'rate': [''],
                'amount': [''],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        entry = ShopDailyEntry.objects.order_by('-id').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.total_amount, Decimal('17.50'))
        created_item = entry.items.first()
        self.assertEqual(created_item.paper_quantity, 10)
        self.assertEqual(created_item.finishing_quantity, 10)
        self.assertEqual(created_item.paper_rate, Decimal('1.50'))
        self.assertEqual(created_item.finishing_rate, Decimal('0.25'))
        self.assertEqual(created_item.rate, Decimal('1.75'))
        self.assertEqual(created_item.amount, Decimal('17.50'))

    def test_shop_daily_entry_create_supports_manual_amount_with_separate_quantities(self):
        response = self.client.post(
            reverse('shop_daily_entry_create'),
            {
                'customer_name': '9876543210',
                'customer_id': '',
                'customer_type': 'press',
                'customer_phone': '',
                'payment': 'cash',
                'is_credit': 'off',
                'item_name': ['Poster'],
                'paper_text': ['Art300'],
                'paper_id': [''],
                'side': ['single'],
                'finishing_text': ['Lamination'],
                'finishing_id': [''],
                'paper_quantity': ['10'],
                'finishing_quantity': ['4'],
                'paper_rate': [''],
                'finishing_rate': [''],
                'rate': [''],
                'amount': ['20.00'],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        entry = ShopDailyEntry.objects.order_by('-id').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.total_amount, Decimal('20.00'))
        created_item = entry.items.first()
        self.assertEqual(created_item.quantity, 10)
        self.assertEqual(created_item.paper_quantity, 10)
        self.assertEqual(created_item.finishing_quantity, 4)
        self.assertEqual(created_item.paper_rate, Decimal('1.88'))
        self.assertEqual(created_item.finishing_rate, Decimal('0.30'))
        self.assertEqual(created_item.rate, Decimal('2.18'))
        self.assertEqual(created_item.amount, Decimal('20.00'))

    def test_shop_daily_entry_create_resolves_typed_values_without_hidden_ids(self):
        response = self.client.post(
            reverse('shop_daily_entry_create'),
            {
                'customer_name': '9876543210',
                'customer_id': '',
                'customer_type': 'press',
                'customer_phone': '',
                'payment': 'cash',
                'is_credit': 'off',
                'item_name': ['Poster'],
                'paper_text': ['Art300'],
                'paper_id': [''],
                'side': ['single'],
                'finishing_text': ['Lamination'],
                'finishing_id': [''],
                'paper_quantity': ['10'],
                'finishing_quantity': ['10'],
                'paper_rate': ['2.00'],
                'finishing_rate': ['0.50'],
                'rate': [''],
                'amount': [''],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        entry = ShopDailyEntry.objects.order_by('-id').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.customer_id, self.customer.id)
        self.assertEqual(entry.payment, 'cash')
        self.assertEqual(entry.items.count(), 1)
        created_item = entry.items.first()
        self.assertEqual(created_item.paper_id, self.paper.id)
        self.assertEqual(created_item.finishing_id, self.finishing.id)
        self.assertEqual(created_item.item_name, 'Poster')

    def test_customer_latest_entry_autofill_prefers_selected_shop(self):
        response = self.client.get(
            reverse('customer_latest_entry_autofill', args=[self.customer.id])
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data['same_shop'])
        self.assertEqual(data['entry']['shop_id'], self.shop.id)
        self.assertEqual(data['entry']['payment'], 'upi')
        self.assertEqual(len(data['entry']['items']), 1)
        self.assertEqual(data['entry']['items'][0]['item_name'], 'Business Card')
        self.assertEqual(data['entry']['items'][0]['paper_name'], self.paper.name)
        self.assertEqual(data['entry']['items'][0]['paper_quantity'], 100)
        self.assertEqual(data['entry']['items'][0]['finishing_quantity'], 100)

    def test_customer_latest_entry_autofill_falls_back_to_other_shop(self):
        session = self.client.session
        session['employee_shop_id'] = 999999
        session.save()

        response = self.client.get(
            reverse('customer_latest_entry_autofill', args=[self.customer.id])
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertFalse(data['same_shop'])
        self.assertEqual(data['entry']['shop_id'], self.other_shop.id)
        self.assertEqual(data['entry']['payment'], 'cash')
