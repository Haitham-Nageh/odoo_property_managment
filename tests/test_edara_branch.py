from contextlib import contextmanager
import importlib.util
from pathlib import Path

from psycopg2.errors import UniqueViolation

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestEdaraBranch(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Phase 6.4: 'RAM' collides with a real, legitimate branch already in
        # this shared dev database (not test data - do not rename/delete it).
        cls.branch_a = cls.env['edara.branch'].create({'name': 'Test Ramallah Branch', 'code': 'TRAM'})
        cls.branch_b = cls.env['edara.branch'].create({'name': 'Nablus Branch', 'code': 'NBL'})

    def test_branch_code_unique_per_company(self):
        # Phase 7: creates its own original instead of assuming a pre-existing 'RAM'
        # branch (which only existed in the old Community dev DB, not a clean DB).
        self.env['edara.branch'].create({'name': 'Original', 'code': 'UNIQ1'})
        with mute_logger('odoo.sql_db'), self.assertRaises(UniqueViolation):
            with self.env.cr.savepoint():
                self.env['edara.branch'].create({'name': 'Duplicate', 'code': 'UNIQ1'})

    def test_viewer_sees_only_assigned_branch(self):
        user = new_test_user(self.env, login='edara_viewer_a', groups='property_managment.group_edara_viewer')
        self.branch_a.user_ids = [(4, user.id)]

        branches = self.env['edara.branch'].with_user(user).search([])
        self.assertEqual(branches, self.branch_a)

        with self.assertRaises(AccessError):
            self.branch_b.with_user(user).read(['name'])

    def test_company_manager_sees_all_branches(self):
        # Phase 6.4: assert against "every branch this company manager can
        # see" rather than an exact count, since this shared dev database may
        # already contain other real, legitimate branches beyond the two this
        # test creates - the (1,'=',1) rule's job is to include ALL of them,
        # not just these two.
        pre_existing = self.env['edara.branch'].search([])
        user = new_test_user(self.env, login='edara_cm', groups='property_managment.group_edara_company_manager')

        branches = self.env['edara.branch'].with_user(user).search([])
        self.assertEqual(branches, pre_existing | self.branch_a | self.branch_b)


@tagged('post_install', '-at_install')
class TestEdaraBranchSlaConfiguration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'U2 SLA Company'})
        cls.other_company = cls.env['res.company'].create({'name': 'U2 Other SLA Company'})
        cls.branch = cls.env['edara.branch'].create({
            'name': 'U2 SLA Branch', 'code': 'U2SLA', 'company_id': cls.company.id,
        })
        cls.viewer = new_test_user(
            cls.env, login='u2_sla_viewer', groups='property_managment.group_edara_viewer',
            company_id=cls.company.id, company_ids=[(6, 0, [cls.company.id])])
        cls.manager = new_test_user(
            cls.env, login='u2_sla_manager', groups='property_managment.group_edara_branch_manager',
            company_id=cls.company.id, company_ids=[(6, 0, [cls.company.id])])
        cls.company_manager = new_test_user(
            cls.env, login='u2_sla_company_manager',
            groups='property_managment.group_edara_company_manager',
            company_id=cls.company.id, company_ids=[(6, 0, [cls.company.id])])
        cls.portal = new_test_user(
            cls.env, login='u2_sla_portal', groups='property_managment.group_edara_portal_tenant',
            company_id=cls.company.id, company_ids=[(6, 0, [cls.company.id])])
        cls.branch.user_ids = cls.viewer | cls.manager

    def _assert_stored_targets(self, response, resolution):
        self.env.flush_all()
        self.env.cr.execute(
            'SELECT sla_response_hours, sla_resolution_hours FROM edara_branch WHERE id = %s',
            [self.branch.id])
        self.assertEqual(self.env.cr.fetchone(), (response, resolution))
        self.branch.invalidate_recordset()
        self.assertEqual(self.branch.sla_response_hours, response)
        self.assertEqual(self.branch.sla_resolution_hours, resolution)

    def test_new_branch_inherits_disabled_company_defaults(self):
        self.assertEqual(self.branch.sla_response_mode, 'inherit')
        self.assertEqual(self.branch.sla_resolution_mode, 'inherit')
        self.assertFalse(self.branch.sla_response_enabled)
        self.assertFalse(self.branch.sla_resolution_enabled)
        self.assertTrue(self.branch.sla_notifications_enabled)
        self.assertEqual(self.branch.sla_response_source, 'inherit')
        self.assertEqual(self.branch.sla_resolution_source, 'inherit')
        self._assert_stored_targets(0.0, 0.0)

    def test_inherited_targets_recompute_on_company_changes(self):
        self.company.write({
            'edara_sla_response_enabled': True, 'edara_sla_response_hours': 2.25,
            'edara_sla_resolution_enabled': True, 'edara_sla_resolution_hours': 8.5,
        })
        self._assert_stored_targets(2.25, 8.5)
        self.company.write({'edara_sla_response_hours': 4.75})
        self._assert_stored_targets(4.75, 8.5)
        self.company.write({'edara_sla_response_enabled': False})
        self.assertFalse(self.branch.sla_response_enabled)
        self.assertEqual(self.branch.sla_response_source, 'inherit')
        self._assert_stored_targets(0.0, 8.5)

    def test_custom_and_disabled_dimensions_are_independent(self):
        self.branch.write({
            'sla_response_mode': 'custom', 'sla_response_override_hours': 3.125,
            'sla_resolution_mode': 'disabled',
        })
        self.company.write({
            'edara_sla_response_enabled': True, 'edara_sla_response_hours': 20.0,
            'edara_sla_resolution_enabled': True, 'edara_sla_resolution_hours': 90.0,
        })
        self.assertTrue(self.branch.sla_response_enabled)
        self.assertFalse(self.branch.sla_resolution_enabled)
        self.assertEqual(self.branch.sla_response_override_hours, 3.125)
        self.assertEqual(self.branch.sla_response_source, 'custom')
        self.assertEqual(self.branch.sla_resolution_source, 'disabled')
        self._assert_stored_targets(3.125, 0.0)

    def test_notifications_follow_owning_company_independently(self):
        self.company.edara_sla_notifications_enabled = False
        self.assertFalse(self.branch.sla_notifications_enabled)
        self.company.edara_sla_notifications_enabled = True
        self.assertTrue(self.branch.sla_notifications_enabled)
        self.assertFalse(self.branch.sla_response_enabled)
        self.assertFalse(self.branch.sla_resolution_enabled)

    def test_effective_values_ignore_selected_environment_company(self):
        self.company.write({
            'edara_sla_response_enabled': True, 'edara_sla_response_hours': 6.25,
        })
        self.other_company.write({
            'edara_sla_response_enabled': True, 'edara_sla_response_hours': 99.0,
            'edara_sla_notifications_enabled': False,
        })
        branch = self.branch.with_company(self.other_company)
        self.assertEqual(branch.sla_response_hours, 6.25)
        self.assertTrue(branch.sla_notifications_enabled)
        self.branch.company_id = self.other_company
        self._assert_stored_targets(99.0, 0.0)
        self.assertFalse(self.branch.sla_notifications_enabled)

    def test_invalid_branch_overrides_are_rejected(self):
        for dimension in ('response', 'resolution'):
            for value in (0.0, -1.0, float('nan'), float('inf'), -float('inf')):
                with self.subTest(dimension=dimension, value=value):
                    with self.assertRaises(ValidationError), self.env.cr.savepoint():
                        self.branch.write({
                            'sla_%s_mode' % dimension: 'custom',
                            'sla_%s_override_hours' % dimension: value,
                        })
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                self.branch.write({'sla_%s_override_hours' % dimension: -1.0})

    def test_invalid_company_targets_are_rejected(self):
        for dimension in ('response', 'resolution'):
            for value in (0.0, -1.0, float('nan'), float('inf'), -float('inf')):
                with self.subTest(dimension=dimension, value=value):
                    with self.assertRaises(ValidationError), self.env.cr.savepoint():
                        self.company.write({
                            'edara_sla_%s_enabled' % dimension: True,
                            'edara_sla_%s_hours' % dimension: value,
                        })
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                self.company.write({'edara_sla_%s_hours' % dimension: -1.0})

    def test_inactive_zero_suggestions_do_not_enable_targets(self):
        self.company.write({'edara_sla_response_hours': 0.0})
        self.branch.write({'sla_response_override_hours': 0.0})
        self.assertFalse(self.branch.sla_response_enabled)
        self._assert_stored_targets(0.0, 0.0)

    def test_manager_can_configure_but_cannot_forge_effective_fields(self):
        branch = self.branch.with_user(self.manager)
        branch.write({'sla_response_mode': 'custom', 'sla_response_override_hours': 2.5})
        self.assertEqual(branch.sla_response_hours, 2.5)
        values = {
            'sla_response_hours': 999.0, 'sla_resolution_hours': 999.0,
            'sla_response_enabled': False, 'sla_resolution_enabled': True,
            'sla_notifications_enabled': False,
            'sla_response_source': 'disabled', 'sla_resolution_source': 'custom',
        }
        for name, value in values.items():
            with self.subTest(field=name), self.assertRaises(AccessError):
                branch.with_context(sudo=True).write({name: value})

    def test_company_manager_create_ignores_forged_effective_values(self):
        branch = self.env['edara.branch'].with_user(self.company_manager).create({
            'name': 'U2 Guarded Create', 'code': 'U2CREATE', 'company_id': self.company.id,
            'sla_response_hours': 999.0, 'sla_response_enabled': True,
            'sla_response_source': 'custom', 'sla_notifications_enabled': False,
        })
        self.assertEqual(branch.sla_response_hours, 0.0)
        self.assertFalse(branch.sla_response_enabled)
        self.assertEqual(branch.sla_response_source, 'inherit')
        self.assertTrue(branch.sla_notifications_enabled)

    def test_viewer_and_company_record_rules_remain_effective(self):
        self.branch.with_user(self.viewer).read(['sla_response_hours'])
        with self.assertRaises(AccessError):
            self.branch.with_user(self.viewer).write({'sla_response_mode': 'disabled'})
        other = self.env['edara.branch'].create({
            'name': 'U2 Other Company Branch', 'code': 'U2OTHER',
            'company_id': self.other_company.id,
        })
        for user in (self.viewer, self.manager, self.company_manager):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    other.with_user(user).read(['sla_response_hours'])
                with self.assertRaises(AccessError):
                    other.with_user(user).write({'sla_response_mode': 'disabled'})

    def test_portal_company_sla_reads_and_writes_are_denied(self):
        company = self.company.with_user(self.portal)
        for dimension in ('response', 'resolution'):
            for suffix, value in (('enabled', True), ('hours', 1.0)):
                name = 'edara_sla_%s_%s' % (dimension, suffix)
                with self.subTest(field=name):
                    with self.assertRaises(AccessError):
                        company.read([name])
                    with self.assertRaises(AccessError):
                        company.write({name: value})
        with self.assertRaises(AccessError):
            company.read(['edara_sla_notifications_enabled'])
        with self.assertRaises(AccessError):
            company.write({'edara_sla_notifications_enabled': False})

    def test_public_company_sla_fields_are_not_readable(self):
        company = self.env.company.with_user(self.env.ref('base.public_user'))
        for name in ('edara_sla_response_enabled', 'edara_sla_response_hours',
                     'edara_sla_resolution_enabled', 'edara_sla_resolution_hours',
                     'edara_sla_notifications_enabled'):
            with self.subTest(field=name), self.assertRaises(AccessError):
                company.read([name])

    def test_native_admin_can_read_and_write_company_configuration_without_sudo(self):
        admin = new_test_user(
            self.env, login='u2_sla_native_admin', groups='base.group_erp_manager',
            company_id=self.company.id, company_ids=[(6, 0, [self.company.id])])
        company = self.company.with_user(admin)
        self.assertFalse(company.env.su)
        company.write({'edara_sla_response_enabled': True, 'edara_sla_response_hours': 3.5})
        self.assertEqual(company.read(['edara_sla_response_hours'])[0]['edara_sla_response_hours'], 3.5)
        self._assert_stored_targets(3.5, 0.0)

    def test_fresh_install_cron_definition_is_hourly(self):
        # Installed rows may be user-configured/noupdate; inspect the fresh-install XML.
        from pathlib import Path
        from lxml import etree
        path = Path(__file__).parent.parent / 'data' / 'edara_cron.xml'
        tree = etree.parse(str(path))
        record = tree.xpath("//record[@id='ir_cron_edara_maintenance_sla_notifications']")[0]
        self.assertEqual(record.find("field[@name='interval_number']").text, '1')
        self.assertEqual(record.find("field[@name='interval_type']").text, 'hours')


def _u2_migration(stage):
    path = Path(__file__).parent.parent / 'migrations' / '19.0.1.5.0' / (stage + '-migration.py')
    spec = importlib.util.spec_from_file_location('u2_' + stage + '_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged('post_install', '-at_install')
class TestEdaraBranchSlaMigration(TransactionCase):
    """Database-backed migration checks; run only on an authorized disposable database."""

    @contextmanager
    def _legacy_table(self, rows, target_type='double precision', extra_column=None):
        # Temporary tables shadow the real branch table for SQL only. No branch ORM
        # calls are made until they are removed; the live model table is never renamed.
        self.env.flush_all()
        self.env.cr.execute(
            'CREATE TEMPORARY TABLE edara_branch ('
            'id integer PRIMARY KEY, active boolean, '
            'sla_response_hours %s, sla_resolution_hours %s) ON COMMIT DROP'
            % (target_type, target_type))
        try:
            for row in rows:
                self.env.cr.execute('INSERT INTO edara_branch VALUES (%s, %s, %s, %s)', row)
            if extra_column:
                self.env.cr.execute('ALTER TABLE edara_branch ADD COLUMN ' + extra_column)
            yield
        finally:
            self.env.cr.execute('DROP TABLE IF EXISTS pg_temp.edara_u2_sla_legacy')
            self.env.cr.execute('DROP TABLE pg_temp.edara_branch')

    def test_pre_migration_preserves_fractional_null_and_archived_values(self):
        rows = [(1, True, 2.25, 0.0), (2, False, None, 3.125), (3, True, 0.0, None)]
        with self._legacy_table(rows):
            _u2_migration('pre').migrate(self.env.cr, '19.0.1.4.0')
            self.env.cr.execute(
                'SELECT id, active, sla_response_override_hours, sla_resolution_override_hours, '
                'sla_response_mode, sla_resolution_mode FROM edara_branch ORDER BY id')
            self.assertEqual(self.env.cr.fetchall(), [
                (1, True, 2.25, 0.0, 'custom', 'disabled'),
                (2, False, None, 3.125, 'disabled', 'custom'),
                (3, True, 0.0, None, 'disabled', 'disabled'),
            ])
            # Keep the real pre-migration snapshot present for the post check.
            _u2_migration('post')._verify_legacy_preservation(self.env.cr)

    def test_post_preservation_check_rejects_changed_inputs_and_modes(self):
        mutations = [
            ('sla_response_override_hours = 2.5', 1),
            ('sla_resolution_override_hours = 3.0', 2),
            ('sla_response_override_hours = 0.0', 2),
            ("sla_response_mode = 'inherit'", 1),
            ("sla_resolution_mode = 'custom'", 1),
        ]
        rows = [(1, True, 2.25, 0.0), (2, False, None, 3.125)]
        for assignment, branch_id in mutations:
            with self.subTest(assignment=assignment):
                with self._legacy_table(rows):
                    _u2_migration('pre').migrate(self.env.cr, '19.0.1.4.0')
                    self.env.cr.execute(
                        'UPDATE edara_branch SET ' + assignment + ' WHERE id = %s',
                        [branch_id])
                    with self.assertRaisesRegex(ValueError, r'branches \[%s\]' % branch_id):
                        _u2_migration('post')._verify_legacy_preservation(self.env.cr)
        with self._legacy_table(rows):
            _u2_migration('pre').migrate(self.env.cr, '19.0.1.4.0')
            self.env.cr.execute('DELETE FROM edara_branch WHERE id = 2')
            with self.assertRaisesRegex(ValueError, r'branches \[2\]'):
                _u2_migration('post')._verify_legacy_preservation(self.env.cr)

    def test_pre_migration_rejects_all_invalid_rows_before_mutation(self):
        rows = [(1, True, -1.0, float('nan')), (2, False, float('inf'), -float('inf'))]
        with self._legacy_table(rows):
            with self.assertRaises(ValueError) as error:
                _u2_migration('pre').migrate(self.env.cr, '19.0.1.4.0')
            self.assertIn('1/response', str(error.exception))
            self.assertIn('1/resolution', str(error.exception))
            self.assertIn('2/response', str(error.exception))
            self.assertIn('2/resolution', str(error.exception))
            self.env.cr.execute("SELECT to_regclass('pg_temp.edara_u2_sla_legacy')")
            self.assertIsNone(self.env.cr.fetchone()[0])
            self.env.cr.execute('SELECT count(*) FROM edara_branch WHERE sla_response_hours < 0')
            self.assertEqual(self.env.cr.fetchone()[0], 1)

    def test_pre_migration_rejects_unexpected_column_types(self):
        with self._legacy_table([(1, True, '24', '72')], target_type='text'):
            with self.assertRaises(ValueError):
                _u2_migration('pre').migrate(self.env.cr, '19.0.1.4.0')

    def test_pre_migration_rejects_colliding_and_partial_schemas(self):
        for column in ('sla_response_override_hours double precision',
                       'sla_resolution_mode varchar', 'sla_notifications_enabled boolean'):
            with self.subTest(column=column):
                with self._legacy_table([(1, False, 24.0, 72.0)], extra_column=column):
                    with self.assertRaises(ValueError):
                        _u2_migration('pre').migrate(self.env.cr, '19.0.1.4.0')
                    self.env.cr.execute('SELECT sla_response_hours, sla_resolution_hours FROM edara_branch')
                    self.assertEqual(self.env.cr.fetchone(), (24.0, 72.0))

    def test_post_migration_is_repeatable_and_preserves_cron_settings(self):
        cron = self.env.ref('property_managment.ir_cron_edara_maintenance_sla_notifications')
        cron.write({'active': False, 'interval_number': 1, 'interval_type': 'days'})
        fields = ['active', 'code', 'state', 'model_id', 'user_id', 'priority', 'nextcall',
                  'lastcall', 'failure_count', 'first_failure_date']
        before = cron.read(fields)[0]
        branch = self.env['edara.branch'].create({
            'name': 'U2 Post Migration', 'code': 'U2POST', 'active': False,
            'sla_response_mode': 'custom', 'sla_response_override_hours': 2.25,
            'sla_resolution_mode': 'disabled',
        })
        migration = _u2_migration('post')
        migration.migrate(self.env.cr, '19.0.1.4.0')
        migration.migrate(self.env.cr, '19.0.1.4.0')
        self.assertEqual(cron.read(fields)[0], before)
        self.assertEqual(cron.interval_number, 1)
        self.assertEqual(cron.interval_type, 'hours')
        self.assertEqual(self.env.ref(
            'property_managment.ir_cron_edara_maintenance_sla_notifications').id, cron.id)
        self.assertEqual(branch.sla_response_mode, 'custom')
        self.assertEqual(branch.sla_response_override_hours, 2.25)
        self.assertEqual(branch.sla_response_hours, 2.25)
        self.assertEqual(branch.sla_resolution_hours, 0.0)
