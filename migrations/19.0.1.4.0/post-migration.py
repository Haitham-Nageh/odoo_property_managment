"""Ticket E (19.0.1.4.0): Migrate hardcoded Selection fields to master data models.

1. edara.unit: unit_type -> unit_type_id
2. edara.maintenance.request: category (varchar) -> category_id (Many2one)
3. edara.recurring.maintenance: category (varchar) -> category_id (Many2one)
"""
from odoo import SUPERUSER_ID, api

UNIT_TYPE_MAPPING = {
    'apartment': 'property_managment.edara_unit_type_apartment',
    'office': 'property_managment.edara_unit_type_office',
    'shop': 'property_managment.edara_unit_type_shop',
    'warehouse': 'property_managment.edara_unit_type_warehouse',
    'villa': 'property_managment.edara_unit_type_villa',
    'parking': 'property_managment.edara_unit_type_parking',
    'commercial': 'property_managment.edara_unit_type_commercial',
    'other': 'property_managment.edara_unit_type_other',
}

MAINTENANCE_CATEGORY_MAPPING = {
    'plumbing': 'property_managment.edara_maintenance_category_plumbing',
    'electrical': 'property_managment.edara_maintenance_category_electrical',
    'hvac': 'property_managment.edara_maintenance_category_hvac',
    'general': 'property_managment.edara_maintenance_category_general',
    'cleaning': 'property_managment.edara_maintenance_category_cleaning',
    'structural': 'property_managment.edara_maintenance_category_structural',
    'other': 'property_managment.edara_maintenance_category_other',
}


def migrate_unit_types(env):
    cr = env.cr
    # Check if legacy unit_type column exists
    cr.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'edara_unit' AND column_name = 'unit_type'
    """)
    if not cr.fetchone():
        return

    cr.execute("SELECT id, unit_type FROM edara_unit")
    rows = cr.fetchall()
    if not rows:
        return

    apartment_rec = env.ref('property_managment.edara_unit_type_apartment')
    type_records = {
        key: env.ref(xml_id)
        for key, xml_id in UNIT_TYPE_MAPPING.items()
    }

    for unit_id, legacy_val in rows:
        if not legacy_val:
            target_record = apartment_rec
        elif legacy_val in type_records:
            target_record = type_records[legacy_val]
        else:
            raise ValueError(
                f"Unexpected legacy Selection value in model 'edara.unit', "
                f"record ID {unit_id}: '{legacy_val}'"
            )
        unit = env['edara.unit'].browse(unit_id)
        if unit.unit_type_id != target_record:
            unit.write({'unit_type_id': target_record.id})


def migrate_maintenance_categories(env):
    cr = env.cr
    category_records = {
        key: env.ref(xml_id)
        for key, xml_id in MAINTENANCE_CATEGORY_MAPPING.items()
    }

    for table, model_name in [
        ('edara_maintenance_request', 'edara.maintenance.request'),
        ('edara_recurring_maintenance', 'edara.recurring.maintenance'),
    ]:
        cr.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'category'
        """)
        row = cr.fetchone()
        if not row:
            continue
        col_type = row[1]
        if col_type not in ('character varying', 'text', 'varchar'):
            continue

        cr.execute(f"SELECT id, category FROM {table} WHERE category IS NOT NULL")
        rows = cr.fetchall()
        for record_id, legacy_val in rows:
            if not legacy_val:
                continue
            if legacy_val in category_records:
                target_record = category_records[legacy_val]
                env[model_name].browse(record_id).write({'category_id': target_record.id})
            else:
                raise ValueError(
                    f"Unexpected legacy Selection value in model '{model_name}', "
                    f"record ID {record_id}: '{legacy_val}'"
                )


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    migrate_unit_types(env)
    migrate_maintenance_categories(env)
