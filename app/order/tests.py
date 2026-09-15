from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from order.models import Order, OrderItem
from product.models import Product


class OrdersBreakdownProfitMarginTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.superuser = user_model.objects.create_superuser(
            username='breakadmin',
            email='breakadmin@example.com',
            password='testpass123',
        )
        self.staff = user_model.objects.create_user(
            username='breakstaff',
            email='breakstaff@example.com',
            password='testpass123',
            is_staff=True,
        )
        self.agent = user_model.objects.create_user(
            username='breakagent',
            email='breakagent@example.com',
            password='testpass123',
        )
        self.product = Product.objects.create(name='Breakdown Widget', sku='BD-W-1')
        now = timezone.now()
        self.order = Order.objects.create(
            agent=self.agent,
            status=Order.OrderStatus.COMPLETED,
            transaction_date=now.date(),
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            selling_price=Decimal('100.00'),
            landed_cost=Decimal('80.00'),
        )
        self.url = '/order/api/orders-breakdown/'
        self.params = {
            'month': now.month,
            'year': now.year,
        }

    def test_superuser_sees_profit_margin(self):
        client = Client()
        client.force_login(self.superuser)
        response = client.get(self.url, self.params)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total_revenue'], 200.0)
        self.assertEqual(data['total_profit'], 40.0)
        self.assertEqual(data['total_profit_margin'], 20.0)
        self.assertEqual(len(data['breakdown']), 1)
        row = data['breakdown'][0]
        self.assertEqual(row['profit'], 40.0)
        self.assertEqual(row['profit_margin'], 20.0)

    def test_staff_does_not_receive_profit_fields(self):
        client = Client()
        client.force_login(self.staff)
        response = client.get(self.url, self.params)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn('total_profit', data)
        self.assertNotIn('total_profit_margin', data)
        self.assertNotIn('profit', data['breakdown'][0])
        self.assertNotIn('profit_margin', data['breakdown'][0])
