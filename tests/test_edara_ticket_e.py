from psycopg2.errors import ForeignKeyViolation
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestEdaraUnitTypeMasterData(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Ticket E Branch', 'code': 'TEB'})
        cls.property = cls.env['edara.property'].create({'name': 'Ticket E Property', 'code': 'TEP', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create({'name': 'Ticket E Building', 'code': 'TEBLD', 'property_id': cls.property.id})

    def test_seeded_unit_types_exist_and_flags(self):
        """Covers requirements 1-6: All 8 seeded unit types exist with correct flags."""
        expected_types = {
            'property_managment.edara_unit_type_apartment': ('Apartment', True),
            'property_managment.edara_unit_type_office': ('Office', False),
            'property_managment.edara_unit_type_shop': ('Shop', False),
            'property_managment.edara_unit_type_warehouse': ('Warehouse', False),
            'property_managment.edara_unit_type_villa': ('Villa', True),
            'property_managment.edara_unit_type_parking': ('Parking', False),
            'property_managment.edara_unit_type_commercial': ('Commercial Space', False),
            'property_managment.edara_unit_type_other': ('Other', False),
        }
        for xml_id, (name, has_bb) in expected_types.items():
            record = self.env.ref(xml_id, raise_if_not_found=False)
            self.assertTrue(record, f"Seeded unit type '{xml_id}' does not exist.")
            self.assertEqual(record.name, name)
            self.assertEqual(record.has_bedrooms_bathrooms, has_bb)
            self.assertTrue(record.active)

    def test_custom_unit_type_creation_and_flags(self):
        """Covers requirements 7-9: Custom types with True and False can be created."""
        hotel_room = self.env['edara.unit.type'].create({
            'name': 'Hotel Room',
            'has_bedrooms_bathrooms': True,
            'sequence': 25,
        })
        self.assertTrue(hotel_room.id)
        self.assertTrue(hotel_room.has_bedrooms_bathrooms)

        storage = self.env['edara.unit.type'].create({
            'name': 'Storage Locker',
            'has_bedrooms_bathrooms': False,
            'sequence': 85,
        })
        self.assertTrue(storage.id)
        self.assertFalse(storage.has_bedrooms_bathrooms)

    def test_unit_default_is_apartment(self):
        """Covers requirement 10: Unit default remains Apartment."""
        unit = self.env['edara.unit'].create({
            'name': 'Default Type Unit',
            'code': 'DEF-1',
            'building_id': self.building.id,
        })
        apartment_type = self.env.ref('property_managment.edara_unit_type_apartment')
        self.assertEqual(unit.unit_type_id, apartment_type)
        self.assertTrue(unit.has_bedrooms_bathrooms)

    def test_used_unit_type_deletion_blocked(self):
        """Covers requirement 11: Used Unit Type cannot be deleted (ondelete='restrict')."""
        unit = self.env['edara.unit'].create({
            'name': 'Restrict Unit',
            'code': 'RES-1',
            'building_id': self.building.id,
        })
        apartment_type = self.env.ref('property_managment.edara_unit_type_apartment')
        with mute_logger('odoo.sql_db'), self.assertRaises(ForeignKeyViolation):
            with self.env.cr.savepoint():
                apartment_type.unlink()

    def test_unit_type_archive_and_retention(self):
        """Covers requirements 12-14: Archiving allowed, unit keeps archived type, excluded from normal choices."""
        custom_type = self.env['edara.unit.type'].create({
            'name': 'Chalet',
            'has_bedrooms_bathrooms': True,
        })
        unit = self.env['edara.unit'].create({
            'name': 'Chalet Unit',
            'code': 'CHAL-1',
            'building_id': self.building.id,
            'unit_type_id': custom_type.id,
        })
        self.assertEqual(unit.unit_type_id, custom_type)

        # Archive custom type
        custom_type.active = False
        self.assertFalse(custom_type.active)

        # Unit still retains the archived type
        unit.invalidate_recordset()
        self.assertEqual(unit.unit_type_id, custom_type)

        # Archived type is excluded from default search
        active_types = self.env['edara.unit.type'].search([])
        self.assertNotIn(custom_type, active_types)


@tagged('post_install', '-at_install')
class TestEdaraUnitVisibility(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Visibility Branch', 'code': 'VISB'})
        cls.property = cls.env['edara.property'].create({'name': 'Visibility Property', 'code': 'VISP', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create({'name': 'Visibility Building', 'code': 'VISBLD', 'property_id': cls.property.id})

    def test_visibility_flag_per_type(self):
        """Covers requirement 4 & 19: Prove has_bedrooms_bathrooms business rule."""
        apartment = self.env.ref('property_managment.edara_unit_type_apartment')
        villa = self.env.ref('property_managment.edara_unit_type_villa')
        office = self.env.ref('property_managment.edara_unit_type_office')
        custom_true = self.env['edara.unit.type'].create({'name': 'Studio', 'has_bedrooms_bathrooms': True})
        custom_false = self.env['edara.unit.type'].create({'name': 'Kiosk', 'has_bedrooms_bathrooms': False})

        unit = self.env['edara.unit'].create({
            'name': 'Vis Unit',
            'code': 'VU-1',
            'building_id': self.building.id,
            'unit_type_id': apartment.id,
        })
        self.assertTrue(unit.has_bedrooms_bathrooms)

        unit.unit_type_id = villa
        self.assertTrue(unit.has_bedrooms_bathrooms)

        unit.unit_type_id = office
        self.assertFalse(unit.has_bedrooms_bathrooms)

        unit.unit_type_id = custom_true
        self.assertTrue(unit.has_bedrooms_bathrooms)

        unit.unit_type_id = custom_false
        self.assertFalse(unit.has_bedrooms_bathrooms)

    def test_form_view_architecture_has_no_hardcoded_unit_type(self):
        """Verifies that the form view uses not has_bedrooms_bathrooms and no literal ('apartment', 'villa') condition."""
        arch = self.env['edara.unit'].get_view(view_type='form')['arch']
        self.assertNotIn("('apartment', 'villa')", arch)
        self.assertNotIn("('apartment','villa')", arch)
        self.assertIn("has_bedrooms_bathrooms", arch)


@tagged('post_install', '-at_install')
class TestEdaraMaintenanceCategoryMasterData(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Cat Branch', 'code': 'CATB'})
        cls.property = cls.env['edara.property'].create({'name': 'Cat Property', 'code': 'CATP', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create({'name': 'Cat Building', 'code': 'CATBLD', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create({'name': 'Cat Unit', 'code': 'CU-1', 'building_id': cls.building.id})

    def test_seeded_maintenance_categories_exist(self):
        """Covers requirement 1: All 7 seeded categories exist."""
        expected_cats = {
            'property_managment.edara_maintenance_category_plumbing': 'Plumbing',
            'property_managment.edara_maintenance_category_electrical': 'Electrical',
            'property_managment.edara_maintenance_category_hvac': 'HVAC',
            'property_managment.edara_maintenance_category_general': 'General',
            'property_managment.edara_maintenance_category_cleaning': 'Cleaning',
            'property_managment.edara_maintenance_category_structural': 'Structural',
            'property_managment.edara_maintenance_category_other': 'Other',
        }
        for xml_id, name in expected_cats.items():
            record = self.env.ref(xml_id, raise_if_not_found=False)
            self.assertTrue(record, f"Seeded category '{xml_id}' does not exist.")
            self.assertEqual(record.name, name)
            self.assertTrue(record.active)

    def test_custom_category_creation_and_archive(self):
        """Covers requirements 2, 3, 5: Custom category creation, archiving, and retention."""
        cat = self.env['edara.maintenance.category'].create({'name': 'Pest Control'})
        self.assertTrue(cat.id)

        req = self.env['edara.maintenance.request'].create({
            'title': 'Termites treatment',
            'unit_id': self.unit.id,
            'category_id': cat.id,
        })
        self.assertEqual(req.category_id, cat)

        # Archive category
        cat.active = False
        self.assertFalse(cat.active)

        # Existing request retains archived category
        req.invalidate_recordset()
        self.assertEqual(req.category_id, cat)

        # Archived category excluded from normal active search
        active_cats = self.env['edara.maintenance.category'].search([])
        self.assertNotIn(cat, active_cats)

    def test_used_category_deletion_blocked(self):
        """Covers requirement 4: Used category cannot be deleted."""
        plumbing = self.env.ref('property_managment.edara_maintenance_category_plumbing')
        self.env['edara.maintenance.request'].create({
            'title': 'Leaking sink',
            'unit_id': self.unit.id,
            'category_id': plumbing.id,
        })
        with mute_logger('odoo.sql_db'), self.assertRaises(ForeignKeyViolation):
            with self.env.cr.savepoint():
                plumbing.unlink()

    def test_recurring_maintenance_copies_category(self):
        """Covers requirement 6: Recurring maintenance category copies correctly to generated request."""
        elec_cat = self.env.ref('property_managment.edara_maintenance_category_electrical')
        definition = self.env['edara.recurring.maintenance'].create({
            'name': 'Generator Inspection',
            'unit_id': self.unit.id,
            'category_id': elec_cat.id,
            'frequency': 'monthly',
        })
        created_count = self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        self.assertEqual(created_count, 1)
        generated_req = definition.generated_request_ids
        self.assertEqual(generated_req.category_id, elec_cat)

    def test_category_optional_remains_false(self):
        """Covers requirement 7: Optional category can remain False."""
        req = self.env['edara.maintenance.request'].create({
            'title': 'Generic issue',
            'unit_id': self.unit.id,
        })
        self.assertFalse(req.category_id)

        rec = self.env['edara.recurring.maintenance'].create({
            'name': 'Generic recurring',
            'unit_id': self.unit.id,
        })
        self.assertFalse(rec.category_id)


@tagged('post_install', '-at_install')
class TestEdaraTicketESecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.viewer_user = new_test_user(
            cls.env,
            login='ticket_e_viewer',
            groups='property_managment.group_edara_viewer',
        )
        cls.manager_user = new_test_user(
            cls.env,
            login='ticket_e_branch_mgr',
            groups='property_managment.group_edara_branch_manager',
        )

    def test_viewer_access(self):
        """Viewer can read but cannot create/write/unlink."""
        apartment = self.env.ref('property_managment.edara_unit_type_apartment').with_user(self.viewer_user)
        self.assertEqual(apartment.name, 'Apartment')

        plumbing = self.env.ref('property_managment.edara_maintenance_category_plumbing').with_user(self.viewer_user)
        self.assertEqual(plumbing.name, 'Plumbing')

        # Cannot create
        with self.assertRaises(AccessError):
            self.env['edara.unit.type'].with_user(self.viewer_user).create({'name': 'Forbidden Type'})
        with self.assertRaises(AccessError):
            self.env['edara.maintenance.category'].with_user(self.viewer_user).create({'name': 'Forbidden Cat'})

        # Cannot write
        with self.assertRaises(AccessError):
            apartment.write({'sequence': 999})
        with self.assertRaises(AccessError):
            plumbing.write({'sequence': 999})

    def test_branch_manager_access(self):
        """Branch Manager and above has full CRUD."""
        # Create
        new_type = self.env['edara.unit.type'].with_user(self.manager_user).create({
            'name': 'Manager Custom Type',
            'has_bedrooms_bathrooms': True,
        })
        self.assertTrue(new_type.id)

        new_cat = self.env['edara.maintenance.category'].with_user(self.manager_user).create({
            'name': 'Manager Custom Cat',
        })
        self.assertTrue(new_cat.id)

        # Write
        new_type.write({'name': 'Manager Custom Type Updated'})
        self.assertEqual(new_type.name, 'Manager Custom Type Updated')

        new_cat.write({'name': 'Manager Custom Cat Updated'})
        self.assertEqual(new_cat.name, 'Manager Custom Cat Updated')

        # Unlink
        new_type.unlink()
        new_cat.unlink()


@tagged('post_install', '-at_install')
class TestEdaraTicketEMigration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import importlib.util
        from pathlib import Path
        mig_path = Path(__file__).parent.parent / 'migrations' / '19.0.1.4.0' / 'post-migration.py'
        spec = importlib.util.spec_from_file_location('post_migration_19_0_1_4_0', mig_path)
        cls.mig_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mig_module)

        cls.branch = cls.env['edara.branch'].create({'name': 'Mig Branch', 'code': 'MIGB'})
        cls.property = cls.env['edara.property'].create({'name': 'Mig Property', 'code': 'MIGP', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create({'name': 'Mig Building', 'code': 'MIGBLD', 'property_id': cls.property.id})

        # Ensure unit_type column exists for migration test
        cls.env.cr.execute("ALTER TABLE edara_unit ADD COLUMN IF NOT EXISTS unit_type varchar")

        # Ensure category varchar column exists for legacy simulation
        cls.env.cr.execute("""
            SELECT data_type FROM information_schema.columns 
            WHERE table_name = 'edara_maintenance_request' AND column_name = 'category'
        """)
        row = cls.env.cr.fetchone()
        if not row:
            cls.env.cr.execute("ALTER TABLE edara_maintenance_request ADD COLUMN category varchar")
        elif row[0] not in ('character varying', 'text', 'varchar'):
            cls.env.cr.execute("ALTER TABLE edara_maintenance_request ALTER COLUMN category TYPE varchar USING category::varchar")

        cls.env.cr.execute("""
            SELECT data_type FROM information_schema.columns 
            WHERE table_name = 'edara_recurring_maintenance' AND column_name = 'category'
        """)
        row = cls.env.cr.fetchone()
        if not row:
            cls.env.cr.execute("ALTER TABLE edara_recurring_maintenance ADD COLUMN category varchar")
        elif row[0] not in ('character varying', 'text', 'varchar'):
            cls.env.cr.execute("ALTER TABLE edara_recurring_maintenance ALTER COLUMN category TYPE varchar USING category::varchar")

    @classmethod
    def tearDownClass(cls):
        cls.env.cr.execute("ALTER TABLE edara_unit DROP COLUMN IF EXISTS unit_type")
        super().tearDownClass()

    def test_unit_type_mapping_all_8_values(self):
        """Tests deterministic mapping of all 8 legacy unit type values."""
        mapping = self.mig_module.UNIT_TYPE_MAPPING
        self.assertEqual(len(mapping), 8)
        for legacy_key, xml_id in mapping.items():
            unit = self.env['edara.unit'].create({
                'name': f'Mig Unit {legacy_key}',
                'code': f'MIG-{legacy_key}',
                'building_id': self.building.id,
            })
            self.env.cr.execute(
                "UPDATE edara_unit SET unit_type = %s WHERE id = %s",
                (legacy_key, unit.id)
            )
            unit.invalidate_recordset()

            self.mig_module.migrate_unit_types(self.env)
            unit.invalidate_recordset()
            expected_rec = self.env.ref(xml_id)
            self.assertEqual(unit.unit_type_id, expected_rec, f"Failed mapping for legacy type '{legacy_key}'")

    def test_unit_legacy_false_falls_back_to_apartment(self):
        """Tests fallback to Apartment when legacy unit_type is False/NULL."""
        villa = self.env.ref('property_managment.edara_unit_type_villa')
        unit = self.env['edara.unit'].create({
            'name': 'Mig Unit Null Type',
            'code': 'MIG-NULL',
            'building_id': self.building.id,
            'unit_type_id': villa.id,
        })
        self.assertEqual(unit.unit_type_id, villa)

        self.env.cr.execute(
            "UPDATE edara_unit SET unit_type = NULL WHERE id = %s",
            (unit.id,)
        )
        unit.invalidate_recordset()

        self.mig_module.migrate_unit_types(self.env)
        unit.invalidate_recordset()
        apartment = self.env.ref('property_managment.edara_unit_type_apartment')
        self.assertEqual(unit.unit_type_id, apartment)

    def test_unexpected_legacy_unit_type_fails_loudly(self):
        """Tests that an unexpected legacy unit type raises an explicit exception with details."""
        unit = self.env['edara.unit'].create({
            'name': 'Mig Unit Invalid Type',
            'code': 'MIG-INV',
            'building_id': self.building.id,
        })
        self.env.cr.execute(
            "UPDATE edara_unit SET unit_type = 'spaceship' WHERE id = %s",
            (unit.id,)
        )
        unit.invalidate_recordset()

        with self.assertRaises(ValueError) as cm:
            self.mig_module.migrate_unit_types(self.env)
        err_msg = str(cm.exception)
        self.assertIn("edara.unit", err_msg)
        self.assertIn(str(unit.id), err_msg)
        self.assertIn("spaceship", err_msg)

    def test_maintenance_category_mapping_all_7_values(self):
        """Tests deterministic mapping of all 7 legacy maintenance category values (requirements 1-7)."""
        unit = self.env['edara.unit'].create({
            'name': 'Mig Mnt Unit',
            'code': 'MIG-MNT',
            'building_id': self.building.id,
        })
        mapping = self.mig_module.MAINTENANCE_CATEGORY_MAPPING
        self.assertEqual(len(mapping), 7)
        cr = self.env.cr

        for legacy_key, xml_id in mapping.items():
            req = self.env['edara.maintenance.request'].create({
                'title': f'Mig Req {legacy_key}',
                'unit_id': unit.id,
            })
            cr.execute(
                "UPDATE edara_maintenance_request SET category = %s, category_id = NULL WHERE id = %s",
                (legacy_key, req.id)
            )
            req.invalidate_recordset()

            self.mig_module.migrate_maintenance_categories(self.env)
            req.invalidate_recordset()
            expected_rec = self.env.ref(xml_id)
            self.assertEqual(
                req.category_id, expected_rec,
                f"Failed mapping for legacy category '{legacy_key}'"
            )

    def test_maintenance_category_legacy_null_remains_unset(self):
        """Tests requirement 8: Legacy NULL/False remains unset (False) on category_id."""
        unit = self.env['edara.unit'].create({
            'name': 'Mig Mnt Null Unit',
            'code': 'MIG-MNT-NULL',
            'building_id': self.building.id,
        })
        plumbing = self.env.ref('property_managment.edara_maintenance_category_plumbing')
        req = self.env['edara.maintenance.request'].create({
            'title': 'Mig Req Null Cat',
            'unit_id': unit.id,
            'category_id': plumbing.id,
        })
        self.assertEqual(req.category_id, plumbing)

        self.env.cr.execute(
            "UPDATE edara_maintenance_request SET category = NULL, category_id = NULL WHERE id = %s",
            (req.id,)
        )
        req.invalidate_recordset()

        self.mig_module.migrate_maintenance_categories(self.env)
        req.invalidate_recordset()
        self.assertFalse(req.category_id, "NULL legacy category must leave category_id unset (False).")

    def test_unexpected_legacy_maintenance_category_fails_loudly(self):
        """Tests requirement 9: Unexpected legacy category raises explicit error with model, id, and value."""
        unit = self.env['edara.unit'].create({
            'name': 'Mig Mnt Invalid Unit',
            'code': 'MIG-MNT-INV',
            'building_id': self.building.id,
        })
        req_invalid = self.env['edara.maintenance.request'].create({
            'title': 'Mig Req Invalid',
            'unit_id': unit.id,
        })
        self.env.cr.execute(
            "UPDATE edara_maintenance_request SET category = 'blacksmithing', category_id = NULL WHERE id = %s",
            (req_invalid.id,)
        )
        req_invalid.invalidate_recordset()

        with self.assertRaises(ValueError) as cm:
            self.mig_module.migrate_maintenance_categories(self.env)
        err_msg = str(cm.exception)
        self.assertIn("edara.maintenance.request", err_msg)
        self.assertIn(str(req_invalid.id), err_msg)
        self.assertIn("blacksmithing", err_msg)

        # Reset category to avoid leaving unexpected value
        self.env.cr.execute("UPDATE edara_maintenance_request SET category = NULL WHERE id = %s", (req_invalid.id,))

    def test_recurring_maintenance_legacy_category_migration(self):
        """Tests legacy category migration on edara.recurring.maintenance model."""
        unit = self.env['edara.unit'].create({
            'name': 'Mig Rec Mnt Unit',
            'code': 'MIG-REC-MNT',
            'building_id': self.building.id,
        })
        rec = self.env['edara.recurring.maintenance'].create({
            'name': 'Mig Rec Electrical',
            'unit_id': unit.id,
        })
        self.env.cr.execute(
            "UPDATE edara_recurring_maintenance SET category = 'electrical', category_id = NULL WHERE id = %s",
            (rec.id,)
        )
        rec.invalidate_recordset()

        self.mig_module.migrate_maintenance_categories(self.env)
        rec.invalidate_recordset()
        expected_rec = self.env.ref('property_managment.edara_maintenance_category_electrical')
        self.assertEqual(rec.category_id, expected_rec)
