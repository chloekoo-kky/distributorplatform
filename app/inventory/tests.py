from decimal import Decimal
from io import BytesIO

from django.test import SimpleTestCase, TestCase
from tablib import Dataset

from inventory.invoice_import import (
    confirm_payable_invoice_import,
    parse_payable_invoice_detail_file,
    suggest_supplier_code,
)
from inventory.models import Supplier
from product.models import Product
from sales.models import Invoice, InvoiceItem
from inventory.supplier_pricing import (
    _clean_pdf_table,
    _find_matrix_header_row,
    _load_pdf_as_dataset,
    _parse_dataset_rows,
    _parse_pdf_table_segments,
    parse_supplier_price_matrix_file,
)


class SupplierPriceMatrixParserTests(SimpleTestCase):
    def _csv_file(self, content: str, name='prices.csv'):
        return BytesIO(content.encode('utf-8')), name

    def test_parse_csv_with_tier_columns(self):
        csv_content = (
            'Medication,Strength,Size,1-999,1000-1999\n'
            'Tirzepatide,10mg,2mL,80.00,75.00\n'
        )
        file_obj, name = self._csv_file(csv_content)
        file_obj.name = name
        rows, error = parse_supplier_price_matrix_file(file_obj)
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['medication'], 'Tirzepatide')
        self.assertEqual(len(rows[0]['tiers']), 2)
        self.assertEqual(rows[0]['tiers'][0]['unit_price'], Decimal('80.00'))

    def test_find_matrix_header_row(self):
        table = [
            ['Supplier price list', '', ''],
            ['Medication', 'Strength', '1-999', '2000+'],
            ['Product A', '5mg', '10.00', '9.00'],
        ]
        self.assertEqual(_find_matrix_header_row(table), 1)

    def test_parse_dataset_single_price_column(self):
        dataset = Dataset()
        dataset.headers = ['Product', 'Quoted Price (Unit)']
        dataset.append(['Semaglutide 5mg', '120.50'])
        rows, error = _parse_dataset_rows(dataset)
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['tiers'][0]['unit_price'], Decimal('120.50'))

    def test_pdf_multi_table_parsing(self):
        glp1 = [
            ['GLP-1 INJECTABLES'],
            ['Medication', 'Strength', 'Form', 'Size', '1–999 Scripts', '1,000–1,999', '2,000+ Scripts', 'Notes'],
            ['Semaglutide / Pyridoxine (Vit B6)*', '2.5 mg / 10 mg/mL', 'INJ', '1 mL', '$79.00', '$75.00', '$69.00', 'Kits included'],
        ]
        hormone = [
            ['MALE HORMONE THERAPY — INJECTABLES'],
            ['Medication', 'Strength', 'Form', 'Size', 'Price', 'Notes'],
            ['Testosterone Cypionate MFG', '200 mg/mL', 'INJ', '10 mL', '$60.00', ''],
        ]
        rows = []
        for table in (glp1, hormone):
            parsed = _parse_pdf_table_segments(_clean_pdf_table(table))
            self.assertTrue(parsed)
            rows.extend(parsed)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]['tiers']), 3)
        self.assertEqual(rows[1]['tiers'][0]['unit_price'], Decimal('60.00'))

    def test_pdf_merged_table_with_multiple_sections(self):
        merged = [
            ['GLP-1 INJECTABLES'],
            ['Medication', 'Strength', 'Form', 'Size', '1–999 Scripts', '1,000–1,999', '2,000+ Scripts', 'Notes'],
            ['Semaglutide / Pyridoxine (Vit B6)*', '2.5 mg / 10 mg/mL', 'INJ', '1 mL', '$79.00', '$75.00', '$69.00', ''],
            ['MALE HORMONE THERAPY — INJECTABLES'],
            ['Medication', 'Strength', 'Form', 'Size', 'Price', 'Notes'],
            ['Testosterone Cypionate MFG', '200 mg/mL', 'INJ', '10 mL', '$60.00', ''],
        ]
        rows = _parse_pdf_table_segments(_clean_pdf_table(merged))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['medication'], 'Testosterone Cypionate MFG')

    def test_pdf_two_column_product_name_with_continuations(self):
        table = [
            ["MEN'S HEALTH"],
            ['Product Name', 'Strength', 'Size', 'Price', 'Product Name', 'Strength', 'Size', 'Price'],
            [
                '7-Keto DHEA Capsule', '12.5 mg, 25 mg', 'Each', '$1.68',
                'Liothyronine Sodium (Cytomel®) Tablet †', '5 mcg', 'Each', '$2.33',
            ],
            ['', '50 mg', 'Each', '$1.70', '', '25 mcg', 'Each', '$3.06'],
        ]
        rows = _parse_pdf_table_segments(_clean_pdf_table(table))
        self.assertGreaterEqual(len(rows), 4)
        by_key = {(r['medication'], r['strength']): r for r in rows}
        self.assertIn(('7-Keto DHEA Capsule', '12.5 mg, 25 mg'), by_key)
        self.assertIn(('7-Keto DHEA Capsule', '50 mg'), by_key)
        self.assertIn(('Liothyronine Sodium (Cytomel®) Tablet †', '5 mcg'), by_key)
        self.assertEqual(by_key[('7-Keto DHEA Capsule', '50 mg')]['tiers'][0]['unit_price'], Decimal('1.70'))

    def test_pdf_product_name_continuation_rows(self):
        table = [
            ['Product Name', 'Strength', 'Size', 'Price'],
            ['Anastrozole Capsule | Tablet', '0.1 mg, 0.25 mg', 'Each', '$0.95'],
            ['', '1 mg', 'Each', '$1.28'],
        ]
        rows = _parse_pdf_table_segments(_clean_pdf_table(table))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['medication'], 'Anastrozole Capsule | Tablet')
        self.assertEqual(rows[1]['strength'], '1 mg')
        self.assertEqual(rows[1]['tiers'][0]['unit_price'], Decimal('1.28'))

    def test_pdf_testosterone_split_cells_strength_and_size(self):
        """PDF tables may split 200 mg/mL and 2.5 mL across extra cells."""
        table = [
            ['Product Name', 'Medication Strength', 'Size', '1–10', '11–25', '26–100', '101+'],
            [
                'Testosterone Cypionate Injection (',
                'Grapeseed Oil)',
                '200',
                'mg/mL',
                '2.5',
                'mL',
                '$21.81',
                '$21.37',
                '$20.80',
                '$17.43',
            ],
            ['', '200', 'mg/mL', '5', 'mL', '$21.17', '$20.11', '$19.11', '$18.15'],
        ]
        rows = _parse_pdf_table_segments(_clean_pdf_table(table))
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(
            rows[0]['medication'],
            'Testosterone Cypionate Injection (Grapeseed Oil)',
        )
        self.assertEqual(rows[0]['strength'], '200 mg/mL')
        self.assertEqual(rows[0]['size'], '2.5 mL')
        self.assertEqual(rows[1]['strength'], '200 mg/mL')
        self.assertEqual(rows[1]['size'], '5 mL')

    def test_pdf_testosterone_continuation_without_form_column(self):
        table = [
            ['Product Name', 'Medication Strength', 'Size', '1–10', '11–25'],
            [
                'Testosterone Cypionate Injection (Grapeseed Oil)',
                '20 mg/mL',
                '5 mL',
                '$21.17',
                '$20.11',
            ],
            ['', '50 mg/mL', '5 mL', '$21.17', '$20.11'],
            ['', '200 mg/mL', '2.5 mL', '$21.81', '$21.37'],
        ]
        rows = _parse_pdf_table_segments(_clean_pdf_table(table))
        self.assertEqual(len(rows), 3)
        by_strength = {r['strength']: r for r in rows}
        self.assertEqual(by_strength['200 mg/mL']['size'], '2.5 mL')
        self.assertEqual(by_strength['200 mg/mL']['tiers'][0]['unit_price'], Decimal('21.81'))

    def test_split_merged_strength_size_helper(self):
        from inventory.supplier_pricing import _repair_strength_size_pair
        strength, size = _repair_strength_size_pair('200 mg/mL 2.5', 'mL')
        self.assertEqual(strength, '200 mg/mL')
        self.assertEqual(size, '2.5 mL')

    def test_repair_strength_size_trailing_digits(self):
        from inventory.supplier_pricing import _repair_strength_size_pair

        strength, size = _repair_strength_size_pair('200 mg/ml 1', '0 ml')
        self.assertEqual(strength, '200 mg/ml')
        self.assertEqual(size, '10 ml')

        strength, size = _repair_strength_size_pair('2 5 mg/ml 30', 'ml')
        self.assertEqual(strength, '25 mg/ml')
        self.assertEqual(size, '30 ml')

    def test_pdf_size_split_from_strength_column(self):
        table = [
            ['Product Name', 'Medication Strength', 'Size', '1–10', '11–39'],
            [
                'Testosterone Cypionate Injection (Grapeseed Oil)',
                '200 mg/ml 1',
                '0 ml',
                '$25.31',
                '$24.87',
            ],
            [
                'Alpha Lipoic Acid Injection',
                '2 5 mg/ml 30',
                'ml',
                '$74.84',
                '$69.20',
            ],
        ]
        rows = _parse_pdf_table_segments(_clean_pdf_table(table))
        by_med = {r['medication']: r for r in rows}
        self.assertEqual(by_med['Testosterone Cypionate Injection (Grapeseed Oil)']['strength'], '200 mg/ml')
        self.assertEqual(by_med['Testosterone Cypionate Injection (Grapeseed Oil)']['size'], '10 ml')
        self.assertEqual(by_med['Alpha Lipoic Acid Injection']['strength'], '25 mg/ml')
        self.assertEqual(by_med['Alpha Lipoic Acid Injection']['size'], '30 ml')

    def test_pdf_testosterone_merged_strength_size_in_columns(self):
        """Repair trailing size number absorbed into the strength column."""
        table = [
            ['Product Name', 'Medication Strength', 'Size', '1–10', '11–25'],
            [
                'Testosterone Cypionate Injection (Grapeseed Oil)',
                '200 mg/mL 2.5',
                'mL',
                '$21.81',
                '$21.37',
            ],
        ]
        rows = _parse_pdf_table_segments(_clean_pdf_table(table))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['strength'], '200 mg/mL')
        self.assertEqual(rows[0]['size'].lower(), '2.5 ml')

    def test_repair_split_medication_words(self):
        from inventory.supplier_pricing import _repair_split_medication_words

        self.assertEqual(_repair_split_medication_words('?-Keto DHEA Capsu le'), '7-Keto DHEA Capsule')
        self.assertEqual(_repair_split_medication_words('Anastrozole Tab let'), 'Anastrozole Tablet')
        self.assertEqual(_repair_split_medication_words('Testosterone Injec tion'), 'Testosterone Injection')

    def test_pdf_compound_strength_biotin_finasteride_minoxidil(self):
        """Compound strengths like 5/1.25/0.5 mg split across PDF columns."""
        table = [
            ['Product Name', 'Medication Strength', 'Size', '1-+'],
            [
                'Biotin / Finasteride / Minoxidil Capsule 5/1.25/',
                '0.5 mg',
                'Each',
                '$1.69',
            ],
            ['', '5/1.25/5 mg', 'Each', '$1.70'],
            ['', '5/2.5/0.25 mg', 'Each', '$1.32'],
            ['', '5/2.5/2.5 mg', 'Each', '$1.32'],
        ]
        rows = _parse_pdf_table_segments(_clean_pdf_table(table))
        self.assertEqual(len(rows), 4)
        by_strength = {r['strength']: r for r in rows}
        self.assertEqual(
            by_strength['5/1.25/0.5 mg']['medication'],
            'Biotin / Finasteride / Minoxidil Capsule',
        )
        self.assertIn('5/1.25/5 mg', by_strength)
        self.assertIn('5/2.5/0.25 mg', by_strength)
        self.assertIn('5/2.5/2.5 mg', by_strength)

    def test_pdf_compound_strength_corrupt_pdf_split(self):
        """Repair compound strengths split mid-value on continuation rows."""
        table = [
            ['Product Name', 'Medication Strength', 'Size', '1-+'],
            [
                'Biotin/ Finasteride / Minoxidil Capsule 5/1.25/',
                '0.5 mg',
                'Each',
                '$1.69',
            ],
            ['', '.25/5 mg', 'Each', '$1.70'],
            ['', '5/2.5/', '0.25 mg', 'Each', '$1.32'],
            ['', '5/2.5', '2.5 mg', 'Each', '$1.32'],
        ]
        rows = _parse_pdf_table_segments(_clean_pdf_table(table))
        self.assertEqual(len(rows), 4)
        strengths = {r['strength'] for r in rows}
        self.assertIn('5/1.25/0.5 mg', strengths)
        self.assertIn('5/1.25/5 mg', strengths)
        self.assertIn('5/2.5/0.25 mg', strengths)
        self.assertIn('5/2.5/2.5 mg', strengths)
        self.assertEqual(
            rows[0]['medication'],
            'Biotin / Finasteride / Minoxidil Capsule',
        )

    def test_pdf_split_capsule_word_in_medication(self):
        table = [
            ['Product Name', 'Medication Strength', 'Size', '1–10'],
            ['?-Keto DHEA Capsu le', '25 mg', 'Each', '$1.00'],
        ]
        rows = _parse_pdf_table_segments(_clean_pdf_table(table))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['medication'], '7-Keto DHEA Capsule')

    def test_pdf_kinami_grapeseed_oil_strength_split(self):
        """Kinami PDFs split product at '(' and glue 'Grapeseed Oil) 2' into strength."""
        table = [
            ['Product Name', 'Medication Strength', 'Size', '1–10', '11–39', '40–99', '100+'],
            [
                'Estradiol Cypionate Injecti~',
                'Grapeseed Oil) 1',
                '0 mg/ml',
                '5 ml',
                '$59.12',
                '$50.25',
                '$47.74',
                '$45.35',
            ],
            [
                'Nandrolone Decanoate Injection (Grapeseed Oil) 20',
                '0 mg/ml',
                '5 ml',
                '$55.23',
                '$46.95',
                '$44.60',
                '$42.37',
            ],
            [
                'Testosterone Cypionate Injection ( ',
                'Grapeseed Oil) 2',
                '0 mg/ml',
                '5 ml',
                '$21.17',
                '$20.11',
                '$19.11',
                '$18.15',
            ],
            ['', '5 0 mg/ml', '5 ml', '$21.17', '$20.11', '$19.11', '$18.15'],
            ['', '10 0 mg/ml', '5 ml', '$21.17', '$20.11', '$19.11', '$18.15'],
        ]
        rows = _parse_pdf_table_segments(_clean_pdf_table(table))
        by_strength = {r['strength']: r for r in rows}
        self.assertEqual(
            by_strength['20 mg/ml']['medication'],
            'Testosterone Cypionate Injection (Grapeseed Oil)',
        )
        self.assertEqual(by_strength['20 mg/ml']['size'], '5 ml')
        self.assertEqual(by_strength['10 mg/ml']['medication'], 'Estradiol Cypionate Injecti~ Grapeseed Oil)')
        self.assertEqual(by_strength['200 mg/ml']['medication'], 'Nandrolone Decanoate Injection (Grapeseed Oil)')
        self.assertEqual(by_strength['50 mg/ml']['medication'], 'Testosterone Cypionate Injection (Grapeseed Oil)')
        self.assertEqual(by_strength['100 mg/ml']['medication'], 'Testosterone Cypionate Injection (Grapeseed Oil)')

    def test_pdf_loader_requires_pdfplumber(self):
        try:
            import pdfplumber  # noqa: F401
        except ImportError:
            dataset, error = _load_pdf_as_dataset(b'%PDF-1.4')
            self.assertIsNone(dataset)
            self.assertIn('pdfplumber', error or '')
            return
        self.assertTrue(True)


class PayableInvoiceImportParserTests(SimpleTestCase):
    def _xlsx_bytes(self, rows):
        from io import BytesIO
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        for row in rows:
            ws.append(row)
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = 'payable-invoices.xlsx'
        return buf

    def test_skips_metadata_and_parses_supplier_groups(self):
        rows = [
            ['Payable Invoice Detail'],
            ['Pharma Depot Sdn. Bhd.'],
            ['For the period 1 June 2022 to 30 June 2026'],
            ['Branch is PO: Unassigned.'],
            ['Account contains Inventory'],
            ['Status contains Paid'],
            [],
            [
                'Invoice Date', 'Source', 'Reference', 'Item Code', 'Description', 'Quantity',
                'Original Currency', 'Unit Price (ex) (Source)', 'Gross (Source)',
                'Unit Price (ex) (MYR)', 'Gross (MYR)', 'Invoice Total (MYR)',
            ],
            ['Alb Medikal A.S.'],
            [
                '22 Aug 2023', 'Payable Invoice', 'ALB20230027', '', 'NEXPLANON Implant 68mg', 50,
                'USD', 79.9, 3995, 79.9, 3995, 5000,
            ],
            [
                '22 Aug 2023', 'Payable Invoice', 'ALB20230027', '', 'BOTOX 100iu', 10,
                'USD', 100, 1000, 100, 1000, 5000,
            ],
        ]
        file_obj = self._xlsx_bytes(rows)
        parsed, error = parse_payable_invoice_detail_file(file_obj)
        self.assertIsNone(error)
        self.assertEqual(parsed['summary']['supplier_count'], 1)
        self.assertEqual(parsed['summary']['invoice_count'], 1)
        self.assertEqual(parsed['summary']['line_count'], 2)
        sup = parsed['suppliers'][0]
        self.assertEqual(sup['file_supplier_name'], 'Alb Medikal A.S.')
        self.assertEqual(sup['invoices'][0]['reference'], 'ALB20230027')
        self.assertEqual(len(sup['invoices'][0]['lines']), 2)
        lines = sup['invoices'][0]['lines']
        self.assertEqual(lines[0]['description'], 'NEXPLANON Implant 68mg')
        self.assertEqual(lines[0]['quantity'], 50)
        self.assertEqual(lines[1]['quantity'], 10)
        self.assertEqual(lines[0]['unit_price_source'], 79.9)
        self.assertEqual(lines[0]['original_currency'], 'USD')

    def test_infers_quantity_when_quantity_cell_empty(self):
        rows = [
            ['Payable Invoice Detail'],
            [],
            [
                'Invoice Date', 'Source', 'Reference', 'Item Code', 'Description', 'Quantity',
                'Original Currency', 'Unit Price (ex) (Source)', 'Gross (Source)',
                'Unit Price (ex) (MYR)', 'Gross (MYR)', 'Invoice Total (MYR)',
            ],
            ['Test Supplier'],
            ['22 Aug 2023', 'Payable Invoice', 'INV001', '', 'Product A', None,
             'USD', 10, 100, 42, 420, 420],
        ]
        file_obj = self._xlsx_bytes(rows)
        parsed, error = parse_payable_invoice_detail_file(file_obj)
        self.assertIsNone(error)
        line = parsed['suppliers'][0]['invoices'][0]['lines'][0]
        self.assertEqual(line['quantity'], 10)

    def test_finds_quantity_between_description_and_currency(self):
        """Quantity column mis-mapped to empty cell; value sits before currency."""
        rows = [
            ['Payable Invoice Detail'],
            [],
            [
                'Invoice Date', 'Source', 'Reference', 'Item Code', 'Description', 'Qty',
                'Original Currency', 'Unit Price (ex) (Source)', 'Gross (Source)',
                'Unit Price (ex) (MYR)', 'Gross (MYR)', 'Invoice Total (MYR)',
            ],
            ['Test Supplier'],
            ['22 Aug 2023', 'Payable Invoice', 'INV001', '', 'Product A', 60.0, 'USD', 21.34, 7510.80, 95, 5700, 5700],
        ]
        file_obj = self._xlsx_bytes(rows)
        parsed, error = parse_payable_invoice_detail_file(file_obj)
        self.assertIsNone(error)
        self.assertEqual(parsed['suppliers'][0]['invoices'][0]['lines'][0]['quantity'], 60)

    def test_rejects_non_xlsx(self):
        from io import BytesIO
        f = BytesIO(b'a,b\n1,2')
        f.name = 'data.csv'
        parsed, error = parse_payable_invoice_detail_file(f)
        self.assertIsNone(parsed)
        self.assertIn('Excel', error)

    def test_merges_repeated_supplier_group_headers(self):
        rows = [
            ['Payable Invoice Detail'],
            [],
            [
                'Invoice Date', 'Source', 'Reference', 'Item Code', 'Description', 'Quantity',
                'Original Currency', 'Unit Price (ex) (Source)', 'Gross (Source)',
                'Unit Price (ex) (MYR)', 'Gross (MYR)', 'Invoice Total (MYR)',
            ],
            ['Alb Medikal A.S.'],
            ['22 Aug 2023', 'Payable Invoice', 'ALB001', '', 'Product A', 1, 'USD', 10, 10, 10, 10, 10],
            ['Alb Medikal A.S.'],
            ['23 Aug 2023', 'Payable Invoice', 'ALB002', '', 'Product B', 2, 'USD', 20, 40, 20, 40, 40],
        ]
        file_obj = self._xlsx_bytes(rows)
        parsed, error = parse_payable_invoice_detail_file(file_obj)
        self.assertIsNone(error)
        self.assertEqual(parsed['summary']['supplier_count'], 1)
        self.assertEqual(parsed['summary']['invoice_count'], 2)

    def test_suggest_supplier_code_from_name(self):
        self.assertEqual(suggest_supplier_code('Alb Medikal A.S.'), 'ALBM')
        self.assertEqual(suggest_supplier_code('Corena Ecza Deposu'), 'CORE')

    def test_suggest_supplier_code_short_name(self):
        self.assertEqual(suggest_supplier_code('AB'), 'AB')


class InvoiceImportConfirmTests(TestCase):
    def test_two_create_groups_same_code_one_supplier(self):
        payload = {
            'source_filename': 'test.xlsx',
            'suppliers': [
                {
                    'action': 'create',
                    'file_supplier_name': 'Alb Medikal A.S.',
                    'new_supplier_name': 'Alb Medikal A.S.',
                    'new_supplier_code': 'ALB',
                    'invoices': [{
                        'reference': 'ALB001',
                        'invoice_date': '2023-08-22',
                        'lines': [{
                            'description': 'Product A',
                            'quantity': 1,
                            'unit_price_myr': 10.0,
                            'gross_myr': 10.0,
                        }],
                    }],
                },
                {
                    'action': 'create',
                    'file_supplier_name': 'Alb Medikal A.S.5',
                    'new_supplier_name': 'Alb Medikal A.S.5',
                    'new_supplier_code': 'ALB',
                    'invoices': [{
                        'reference': 'ALB002',
                        'invoice_date': '2023-08-23',
                        'lines': [{
                            'description': 'Product B',
                            'quantity': 2,
                            'unit_price_myr': 20.0,
                            'gross_myr': 40.0,
                        }],
                    }],
                },
            ],
        }
        stats = confirm_payable_invoice_import(
            payload,
            product_model=Product,
            supplier_model=Supplier,
            invoice_model=Invoice,
            invoice_item_model=InvoiceItem,
        )
        self.assertEqual(Supplier.objects.count(), 1)
        self.assertEqual(Invoice.objects.count(), 2)
        self.assertEqual(stats['invoices_created'], 2)
        supplier = Supplier.objects.get()
        self.assertEqual(supplier.code, 'ALB')
        self.assertEqual(set(Invoice.objects.values_list('supplier_id', flat=True)), {supplier.pk})

    def test_import_updates_supplier_price_matrix(self):
        payload = {
            'source_filename': 'test.xlsx',
            'suppliers': [{
                'action': 'create',
                'file_supplier_name': 'Matrix Supplier',
                'new_supplier_name': 'Matrix Supplier',
                'new_supplier_code': 'MATX',
                'invoices': [{
                    'reference': 'MAT001',
                    'invoice_date': '2023-08-22',
                    'lines': [{
                        'description': 'Matrix Product',
                        'quantity': 5,
                        'unit_price_myr': 42.0,
                        'gross_myr': 210.0,
                        'unit_price_source': 10.0,
                        'gross_source': 50.0,
                        'original_currency': 'USD',
                    }],
                }],
            }],
        }
        from inventory.models import SupplierPriceMatrixEntry
        stats = confirm_payable_invoice_import(
            payload,
            product_model=Product,
            supplier_model=Supplier,
            invoice_model=Invoice,
            invoice_item_model=InvoiceItem,
        )
        self.assertEqual(stats['matrix_rows_updated'], 1)
        from inventory.models import SupplierPriceMatrixEntry, SupplierPriceMatrixUploadRecord
        entry = SupplierPriceMatrixEntry.objects.get(line_medication='Matrix Product')
        self.assertEqual(entry.price_currency, 'USD')
        self.assertEqual(entry.tiers.count(), 1)
        self.assertEqual(float(entry.tiers.first().unit_price), 42.0)
        self.assertEqual(entry.upload_records.count(), 1)
        record = SupplierPriceMatrixUploadRecord.objects.get(entry=entry)
        self.assertEqual(record.effective_date.isoformat(), '2023-08-22')
        self.assertEqual(record.tiers[0].get('unit_price_source'), '10.0000')
        item = InvoiceItem.objects.get(description='Matrix Product')
        self.assertEqual(item.quantity, 5)
        self.assertEqual(item.original_currency, 'USD')

