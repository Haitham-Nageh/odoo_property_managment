from datetime import date, timedelta

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPhase1013OccupancySelfHealing(TransactionCase):
    """Phase 10.1.3 - Occupancy Self-Healing execution tests.
    Verifies that clearing operational_status away from under_maintenance
    resynchronizes occupancy_status from current contract state."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        E = cls.env
        cls.branch = E['edara.branch'].create({'name': 'P1013 Branch', 'code': 'P1013B'})
        cls.property = E['edara.property'].create({'name': 'P1013 Property', 'code': 'P1013P', 'branch_id': cls.branch.id})
        cls.building = E['edara.building'].create({'name': 'P1013 Building', 'code': 'P1013BL', 'property_id': cls.property.id})
        cls.tenant = E['res.partner'].create({'name': 'P1013 Tenant'})
        cls.today = date.today()
        cls._n = 0

    def _unit(self, **kw):
        type(self)._n += 1
        vals = {
            'name': 'P1013-%d' % self._n,
            'code': 'P1013U%d' % self._n,
            'building_id': self.building.id,
        }
        vals.update(kw)
        return self.env['edara.unit'].create(vals)

    def _contract(self, start, end, unit=None, rent=1000, **kw):
        vals = {
            'unit_id': (unit or self._unit()).id,
            'tenant_id': self.tenant.id,
            'start_date': start,
            'end_date': end,
            'rent_amount': rent,
            'billing_frequency': 'monthly',
            'deposit_required': False,
        }
        vals.update(kw)
        return self.env['edara.lease.contract'].create(vals)

    def test_a_self_healing_after_maintenance(self):
        """Test A — Self-healing after maintenance:
        1. Create a unit.
        2. Give it an active/current lease so occupancy is 'rented'.
        3. Set the unit to 'under_maintenance'.
        4. End/terminate the lease while unit is still under maintenance.
        5. Confirm Phase 10.1.2 behavior leaves stored occupancy stale ('rented').
        6. Clear maintenance by changing operational_status = 'normal'.
        7. Assert occupancy_status == 'available'."""
        unit = self._unit()
        contract = self._contract(self.today - timedelta(days=10), self.today + timedelta(days=20), unit=unit)
        contract.action_activate()
        self.assertEqual(unit.occupancy_status, 'rented')

        unit.operational_status = 'under_maintenance'
        self.assertEqual(unit.operational_status, 'under_maintenance')
        self.assertEqual(unit.occupancy_status, 'rented')

        contract.action_terminate(reason='maintenance test')
        self.assertEqual(contract.state, 'terminated')
        self.assertEqual(unit.operational_status, 'under_maintenance')
        self.assertEqual(unit.occupancy_status, 'rented')
        self.assertEqual(unit._lease_occupancy_state(), 'available')

        unit.operational_status = 'normal'
        self.assertEqual(unit.operational_status, 'normal')
        self.assertEqual(unit.occupancy_status, 'available')

    def test_b_no_unnecessary_behavior(self):
        """Test B — No unnecessary behavior:
        Verify that clearing maintenance when stored occupancy already equals
        derived occupancy does not introduce incorrect behavior or unnecessary state changes."""
        unit = self._unit()
        contract = self._contract(self.today - timedelta(days=10), self.today + timedelta(days=20), unit=unit)
        contract.action_activate()
        unit.operational_status = 'under_maintenance'
        self.assertEqual(unit.occupancy_status, 'rented')

        unit.operational_status = 'normal'
        self.assertEqual(unit.operational_status, 'normal')
        self.assertEqual(unit.occupancy_status, 'rented')

        unit_admin = self._unit(occupancy_status='owner_occupied', operational_status='under_maintenance')
        unit_admin.operational_status = 'normal'
        self.assertEqual(unit_admin.occupancy_status, 'owner_occupied')

    def test_c_unrelated_writes(self):
        """Test C — Unrelated writes:
        Verify that ordinary writes which do NOT change operational_status do not
        trigger an unnecessary occupancy synchronization."""
        contract = self._contract(self.today - timedelta(days=10), self.today + timedelta(days=20))
        contract.action_activate()
        unit = contract.unit_id
        unit.operational_status = 'under_maintenance'
        contract.action_terminate(reason='test')
        self.assertEqual(unit.occupancy_status, 'rented')

        unit.write({'name': 'Renamed Unit P1013'})
        self.assertEqual(unit.name, 'Renamed Unit P1013')
        self.assertEqual(unit.occupancy_status, 'rented')

        unit.write({'area': 85.5})
        self.assertEqual(unit.area, 85.5)
        self.assertEqual(unit.occupancy_status, 'rented')

    def test_d_multi_record_write(self):
        """Test D — Multi-record write:
        Verify that a multi-record write clearing maintenance behaves correctly for
        multiple units and does not incorrectly synchronize unrelated records."""
        unit1 = self._unit()
        contract1 = self._contract(self.today - timedelta(days=10), self.today + timedelta(days=20), unit=unit1)
        contract1.action_activate()
        unit1.operational_status = 'under_maintenance'
        contract1.action_terminate(reason='test multi')
        self.assertEqual(unit1.occupancy_status, 'rented')

        unit2 = self._unit()
        contract2 = self._contract(self.today - timedelta(days=10), self.today + timedelta(days=20), unit=unit2)
        contract2.action_activate()
        unit2.operational_status = 'under_maintenance'
        self.assertEqual(unit2.occupancy_status, 'rented')

        unit3 = self._unit()
        self.assertEqual(unit3.occupancy_status, 'available')
        self.assertEqual(unit3.operational_status, 'normal')

        units = unit1 | unit2 | unit3
        units.write({'operational_status': 'normal'})

        self.assertEqual(unit1.operational_status, 'normal')
        self.assertEqual(unit1.occupancy_status, 'available')

        self.assertEqual(unit2.operational_status, 'normal')
        self.assertEqual(unit2.occupancy_status, 'rented')

        self.assertEqual(unit3.operational_status, 'normal')
        self.assertEqual(unit3.occupancy_status, 'available')
