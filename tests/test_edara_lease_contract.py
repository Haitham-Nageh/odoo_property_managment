from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEdaraLeaseContract(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Ramallah Branch', 'code': 'RAM'})
        cls.property = cls.env['edara.property'].create({'name': 'Al-Irsal Complex', 'code': 'IRS', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create({'name': 'Building A', 'code': 'A', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create({'name': 'A-101', 'code': '101', 'building_id': cls.building.id})
        cls.tenant = cls.env['res.partner'].create({'name': 'Ahmad Ali'})

    def _make_contract(self, **overrides):
        vals = {
            'unit_id': self.unit.id,
            'tenant_id': self.tenant.id,
            'start_date': date(2026, 1, 1),
            'end_date': date(2026, 12, 31),
            'rent_amount': 1500,
        }
        vals.update(overrides)
        return self.env['edara.lease.contract'].create(vals)

    def test_end_date_must_be_after_start_date(self):
        with self.assertRaises(ValidationError):
            self._make_contract(start_date=date(2026, 6, 1), end_date=date(2026, 1, 1))

    def test_rent_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self._make_contract(rent_amount=0)

    def test_activate_sets_unit_rented_and_tenant_flag(self):
        contract = self._make_contract()
        self.assertEqual(contract.name[:2], 'LC')
        contract.action_activate()
        self.assertEqual(contract.state, 'active')
        self.assertEqual(self.unit.occupancy_status, 'rented')
        self.assertTrue(self.tenant.is_edara_tenant)

    def test_cannot_activate_over_sold_unit(self):
        self.unit.occupancy_status = 'sold'
        contract = self._make_contract()
        with self.assertRaises(UserError):
            contract.action_activate()

    def test_cannot_manually_mark_unit_rented_without_active_contract(self):
        with self.assertRaises(ValidationError):
            self.unit.occupancy_status = 'rented'

    def test_overlap_prevented_between_two_active_contracts(self):
        contract_1 = self._make_contract()
        contract_1.action_activate()
        contract_2 = self._make_contract(tenant_id=self.tenant.id, start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        with self.assertRaises(ValidationError):
            contract_2.action_activate()

    def test_terminate_frees_the_unit(self):
        contract = self._make_contract()
        contract.action_activate()
        contract.action_terminate(reason='Tenant moved out')
        self.assertEqual(contract.state, 'terminated')
        self.assertEqual(self.unit.occupancy_status, 'available')
        self.assertEqual(contract.termination_reason, 'Tenant moved out')

    def test_renew_creates_active_successor_and_marks_predecessor_renewed(self):
        contract = self._make_contract()
        contract.action_activate()
        new_contract = contract.action_renew(date(2027, 1, 1), date(2027, 12, 31), 1650)
        self.assertEqual(contract.state, 'renewed')
        self.assertEqual(contract.successor_contract_id, new_contract)
        self.assertEqual(new_contract.state, 'active')
        self.assertEqual(new_contract.predecessor_contract_id, contract)
        self.assertEqual(new_contract.rent_amount, 1650)
        self.assertEqual(self.unit.occupancy_status, 'rented')

    def test_cannot_delete_activated_contract(self):
        contract = self._make_contract()
        contract.action_activate()
        with self.assertRaises(UserError):
            contract.unlink()

    def test_cron_expires_active_contract_past_end_date(self):
        contract = self._make_contract(start_date=date(2020, 1, 1), end_date=date(2020, 12, 31))
        contract.action_activate()
        uninvoiced_line_count = len(contract.schedule_line_ids)
        self.assertTrue(uninvoiced_line_count)

        self.env['edara.lease.contract']._cron_expire_contracts()

        self.assertEqual(contract.state, 'expired')
        self.assertEqual(self.unit.occupancy_status, 'available')
        self.assertFalse(contract.schedule_line_ids)

        # Idempotent: running it again does nothing further (no error, still expired).
        self.env['edara.lease.contract']._cron_expire_contracts()
        self.assertEqual(contract.state, 'expired')

    def test_cron_does_not_expire_contract_still_within_term(self):
        contract = self._make_contract()  # ends 2026-12-31, still in the future
        contract.action_activate()
        self.env['edara.lease.contract']._cron_expire_contracts()
        self.assertEqual(contract.state, 'active')
