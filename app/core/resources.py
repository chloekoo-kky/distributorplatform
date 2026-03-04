from import_export import resources
from import_export.results import Result, RowResult
from tablib import Dataset
import math

from .models import SiteSetting


class SiteSettingResource(resources.ModelResource):
    """
    Import/export resource for SiteSetting.
    Exports a vertical sheet: one row per field -> [field, value].
    Imports the same shape and updates the singleton instance.
    """

    class Meta:
        model = SiteSetting
        # We control import/export shape manually; id is inferred from the singleton.
        import_id_fields = ['id']

        # Keep a list of all model fields for export, but skip 'id' in the vertical sheet.
        field_names = ['id'] + [f.name for f in SiteSetting._meta.fields if f.name != 'id']
        fields = tuple(field_names)
        export_order = fields

        skip_unchanged = True
        report_skipped = True
        # Avoid admin log generation for each imported row since we are
        # doing custom RowResult handling and only updating a singleton.
        skip_admin_log = True

    def export(self, queryset=None, *args, **kwargs):
        """
        Export as:
            field | value
        one row per setting field (excluding id).
        """
        dataset = Dataset()
        dataset.headers = ['field', 'value']

        instance = SiteSetting.objects.first()
        if not instance:
            return dataset

        for name in self._meta.field_names:
            if name == 'id':
                continue
            dataset.append([name, getattr(instance, name)])

        return dataset

    def import_data(self, dataset, dry_run=False, raise_errors=False, use_transactions=None, **kwargs):
        """
        Import from a vertical sheet:
            field | value
        and apply changes to the singleton SiteSetting instance.
        """
        result = Result()

        instance = SiteSetting.objects.first() or SiteSetting()
        changed_fields = set()

        # Expect headers 'field' and 'value'; dataset.dict yields list of dicts.
        for row_number, row in enumerate(dataset.dict, start=1):
            raw_field = row.get('field') or row.get('Field') or ''
            field_name = str(raw_field).strip()
            if not field_name:
                continue

            if not hasattr(instance, field_name):
                # Skip unknown fields but record a skipped row.
                rr = RowResult()
                rr.import_type = RowResult.IMPORT_TYPE_SKIP
                rr.row = row
                result.rows.append(rr)
                continue

            value = row.get('value') if 'value' in row else row.get('Value')

            # If the cell is empty / NaN, skip updating this field so we don't
            # accidentally overwrite non-nullable fields with NULL.
            if value is None:
                continue
            if isinstance(value, float) and math.isnan(value):
                continue
            if isinstance(value, str):
                stripped = value.strip()
                if stripped == '':
                    continue
                value = stripped

            setattr(instance, field_name, value)
            changed_fields.add(field_name)

            rr = RowResult()
            rr.import_type = RowResult.IMPORT_TYPE_UPDATE
            rr.row = row
            rr.instance = instance
            result.rows.append(rr)

        if not dry_run and changed_fields:
            # Save only the fields that changed.
            instance.save(update_fields=list(changed_fields))

        return result

