import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from decimal import Decimal
from io import BytesIO

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from inventory.models import Supplier
from product.models import Product, ProductPriceTier
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
        from product.models import ProductInvoiceNameAlias
        alias = ProductInvoiceNameAlias.objects.get(product=self.master)
        self.assertEqual(alias.name, 'Hylagan - (Fidia )')

    def test_merge_keeps_nested_invoice_name_aliases(self):
        from product.models import ProductInvoiceNameAlias
        from product.name_aliases import upsert_invoice_name_alias
        older = Product.objects.create(name='Older invoice name')
        upsert_invoice_name_alias(self.duplicate, 'PI line: Hyalgan inj')
        response = self.client.post(
            '/api/merge-products/',
            data=json.dumps({
                'primary_id': self.master.pk,
                'merge_ids': [self.duplicate.pk, older.pk],
            }),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        names = set(
            ProductInvoiceNameAlias.objects.filter(product=self.master).values_list('name', flat=True)
        )
        self.assertIn('Hylagan - (Fidia )', names)
        self.assertIn('Older invoice name', names)
        self.assertIn('PI line: Hyalgan inj', names)


class ProductExcelExportTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='exportstaff',
            password='testpass123',
            is_staff=True,
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.supplier = Supplier.objects.create(name='Export Test Supplier')
        self.product = Product.objects.create(
            name='Tiered Export Product',
            sku='EXP-TIER-1',
            selling_price=Decimal('100.00'),
            profit_margin=Decimal('20.00'),
            saved_base_cost=Decimal('80.00'),
            saved_base_cost_supplier=self.supplier,
        )
        ProductPriceTier.objects.create(
            product=self.product, min_quantity=10, price=Decimal('95.00')
        )
        ProductPriceTier.objects.create(
            product=self.product, min_quantity=20, price=Decimal('90.00')
        )
        self.plain = Product.objects.create(
            name='No Tiers Product',
            sku='EXP-PLAIN-1',
            selling_price=Decimal('50.00'),
            saved_base_cost=Decimal('40.00'),
            saved_base_cost_supplier=self.supplier,
        )

    def _workbook(self, products=None):
        from product.excel_export import build_products_xlsx

        qs = Product.objects.filter(
            pk__in=[p.pk for p in (products or [self.product, self.plain])]
        ).order_by('name')
        return load_workbook(BytesIO(build_products_xlsx(qs)))

    def test_export_includes_all_price_tiers(self):
        wb = self._workbook()
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        self.assertIn('tier_1_min_qty', headers)
        self.assertIn('tier_1_profit_margin', headers)
        self.assertIn('tier_1_selling_price', headers)
        self.assertIn('tier_2_min_qty', headers)
        self.assertIn('tier_2_selling_price', headers)

        rows = {
            ws.cell(row=r, column=headers.index('sku') + 1).value: r
            for r in range(2, ws.max_row + 1)
        }
        tiered_row = rows['EXP-TIER-1']
        self.assertEqual(
            ws.cell(row=tiered_row, column=headers.index('tier_1_min_qty') + 1).value, 10
        )
        self.assertEqual(
            ws.cell(row=tiered_row, column=headers.index('tier_2_min_qty') + 1).value, 20
        )

        plain_row = rows['EXP-PLAIN-1']
        self.assertIsNone(
            ws.cell(row=plain_row, column=headers.index('tier_1_min_qty') + 1).value
        )

    def test_export_uses_live_formulas_for_price_and_margin(self):
        wb = self._workbook([self.product])
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        row = 2
        base_col = headers.index('base_cost') + 1
        price_col = headers.index('selling_price') + 1
        margin_col = headers.index('profit_margin') + 1

        base_ref = f'{get_column_letter(base_col)}{row}'
        margin_ref = f'{get_column_letter(margin_col)}{row}'
        price_cell = ws.cell(row=row, column=price_col)
        self.assertIsInstance(price_cell.value, str)
        self.assertTrue(price_cell.value.startswith('='))
        self.assertIn(base_ref, price_cell.value)
        self.assertIn(margin_ref, price_cell.value)
        self.assertIn('/(1-', price_cell.value.replace(' ', ''))

        t1_price_col = headers.index('tier_1_selling_price') + 1
        t1_margin_col = headers.index('tier_1_profit_margin') + 1
        t1_price = ws.cell(row=row, column=t1_price_col)
        self.assertIsInstance(t1_price.value, str)
        self.assertTrue(t1_price.value.startswith('='))
        self.assertIn(base_ref, t1_price.value)
        self.assertIn(f'{get_column_letter(t1_margin_col)}{row}', t1_price.value)

        t2_price = ws.cell(row=row, column=headers.index('tier_2_selling_price') + 1)
        self.assertIsInstance(t2_price.value, str)
        self.assertTrue(t2_price.value.startswith('='))

    def test_export_selected_products_endpoint(self):
        response = self.client.get(f'/export-products/?ids={self.product.pk}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        wb = load_workbook(BytesIO(response.content))
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        sku_col = headers.index('sku') + 1
        skus = [ws.cell(row=r, column=sku_col).value for r in range(2, ws.max_row + 1)]
        self.assertEqual(skus, ['EXP-TIER-1'])
        self.assertIn('tier_1_min_qty', headers)
        price_col = headers.index('selling_price') + 1
        self.assertTrue(str(ws.cell(row=2, column=price_col).value).startswith('='))


class ProductImportFormulaTests(TestCase):
    def test_formula_cells_resolve_from_margin_and_cost(self):
        from product.resources import ProductResource

        resource = ProductResource()
        row = {
            'base_cost': '80',
            'profit_margin': '20',
            'selling_price': '=IF(OR(J2="",L2=""),"",IF(L2>=100,"",ROUND(J2/(1-L2/100),2)))',
            'tier_1_min_qty': 10,
            'tier_1_profit_margin': '15.79',
            'tier_1_selling_price': '=ROUND(J2/(1-N2/100),2)',
        }
        resource._resolve_pricing_formula_cells(row)
        self.assertEqual(row['selling_price'], Decimal('100.00'))
        self.assertEqual(row['tier_1_selling_price'], Decimal('95.00'))

    def test_blank_tier_columns_do_not_clear_existing_tiers(self):
        from product.resources import ProductResource

        resource = ProductResource()
        self.assertIsNone(resource._parse_price_tiers_from_row({
            'sku': 'X',
            'tier_1_min_qty': '',
            'tier_1_selling_price': '',
            'tier_1_profit_margin': '',
        }))
