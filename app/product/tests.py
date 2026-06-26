import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from inventory.models import Supplier
from product.models import Product
from product.views import _build_merge_candidate_groups, _products_are_merge_candidates
from sales.models import Invoice, InvoiceItem


class ProductMergeSuggestionTests(TestCase):
    def setUp(self):
        self.mounjaro_10 = Product.objects.create(
            name='MOUNJARO® KwikPen®, 1 Stk (English Alternative) 10mg'
        )
        self.mounjaro_15 = Product.objects.create(
            name='MOUNJARO® KwikPen®, 1 Stk (English Alternative) 15mg'
        )
        self.master = Product.objects.create(name='HYALGAN (Fidia)')
        self.duplicate = Product.objects.create(name='Hylagan - (Fidia )')

    def test_different_doses_are_not_merge_candidates(self):
        self.assertFalse(
            _products_are_merge_candidates(self.mounjaro_10.name, self.mounjaro_15.name)
        )
        groups = _build_merge_candidate_groups(
            [self.mounjaro_10, self.mounjaro_15],
        )
        self.assertEqual(groups, [])

    def test_spelling_variants_are_merge_candidates(self):
        self.assertTrue(
            _products_are_merge_candidates(self.master.name, self.duplicate.name)
        )
        groups = _build_merge_candidate_groups([self.master, self.duplicate])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)


class ProductMergeApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='mergeapi',
            password='testpass123',
            is_staff=True,
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.master = Product.objects.create(name='HYALGAN (Fidia)')
        self.duplicate = Product.objects.create(name='Hylagan - (Fidia )')
        self.mounjaro_10 = Product.objects.create(
            name='MOUNJARO® KwikPen®, 1 Stk (English Alternative) 10mg'
        )
        self.mounjaro_15 = Product.objects.create(
            name='MOUNJARO® KwikPen®, 1 Stk (English Alternative) 15mg'
        )

    def test_merge_suggestions_exclude_dose_variants(self):
        response = self.client.get(
            '/api/product-merge-suggestions/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        groups = response.json()['groups']
        mounjaro_group = next(
            (group for group in groups if len(group['products']) >= 2
             and any('MOUNJARO' in product['name'] for product in group['products'])),
            None,
        )
        self.assertIsNone(mounjaro_group)

    def test_merge_suggestions_find_spelling_duplicates(self):
        response = self.client.get(
            '/api/product-merge-suggestions/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        hyalgan_groups = [
            group for group in response.json()['groups']
            if {product['id'] for product in group['products']} == {self.master.pk, self.duplicate.pk}
        ]
        self.assertEqual(len(hyalgan_groups), 1)

    def test_merge_suggestions_selection_mode_returns_manual_group(self):
        unrelated_a = Product.objects.create(name='Alpha Widget')
        unrelated_b = Product.objects.create(name='Beta Gadget')
        response = self.client.get(
            f'/api/product-merge-suggestions/?product_ids={unrelated_a.pk},{unrelated_b.pk}',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['mode'], 'selection')
        self.assertEqual(len(data['groups']), 1)
        self.assertEqual(len(data['groups'][0]['products']), 2)


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
