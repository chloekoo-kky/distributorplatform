import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from inventory.models import Supplier
from product.models import Product
from sales.models import Invoice, InvoiceItem


class ProductMergeTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='mergetest',
            password='testpass123',
            is_staff=True,
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.supplier = Supplier.objects.create(name='MBA Pharmaceuticals Pvt Ltd')
        self.master = Product.objects.create(name='HYALGAN (Fidia)')
        self.duplicate = Product.objects.create(name='Hylagan - (Fidia )')
        self.invoice = Invoice.objects.create(
            invoice_id='PI/G-TEST001',
            supplier=self.supplier,
        )
        InvoiceItem.objects.create(
            invoice=self.invoice,
            product=self.duplicate,
            description=self.duplicate.name,
            quantity=200,
            unit_price='90.77',
        )

    def test_merge_reassigns_invoice_items_to_master(self):
        response = self.client.post(
            '/api/merge-products/',
            data=json.dumps({
                'primary_id': self.master.pk,
                'merge_ids': [self.duplicate.pk],
            }),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertFalse(Product.objects.filter(pk=self.duplicate.pk).exists())
        item = InvoiceItem.objects.get(pk=self.invoice.items.first().pk)
        self.assertEqual(item.product_id, self.master.pk)
