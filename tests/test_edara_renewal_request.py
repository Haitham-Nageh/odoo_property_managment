from datetime import date

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEdaraRenewalRequest(TransactionCase):
    """BD-002 (2026-09-22): Reject requires a reason; Terminate's reason
    stays optional (see also tests/test_edara_lease_contract.py for
    Terminate coverage)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Renewal Branch', 'code': 'RNW'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Renewal Property', 'code': 'RNWP', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Renewal Building', 'code': 'RNWB', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create(
            {'name': 'R-101', 'code': 'R101', 'building_id': cls.building.id})
        cls.tenant = cls.env['res.partner'].create({'name': 'Renewal Tenant'})

    def _make_submitted_request(self):
        contract = self.env['edara.lease.contract'].create({
            'unit_id': self.unit.id, 'tenant_id': self.tenant.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31),
            'rent_amount': 1000, 'deposit_required': False,
        })
        contract.action_activate()
        return self.env['edara.renewal.request'].create({
            'contract_id': contract.id,
            'requested_start_date': date(2027, 1, 1),
            'requested_end_date': date(2027, 12, 31),
            'requested_rent_amount': 1050,
        })

    def test_reject_without_reason_blocked(self):
        request = self._make_submitted_request()
        with self.assertRaises(UserError):
            request.action_reject()
        self.assertEqual(request.state, 'submitted')

    def test_reject_with_whitespace_only_reason_blocked(self):
        request = self._make_submitted_request()
        with self.assertRaises(UserError):
            request.action_reject(reason='   ')
        self.assertEqual(request.state, 'submitted')

    def test_reject_with_decision_note_prefilled_on_form_blocked_when_blank(self):
        """Mirrors the UI flow: decision_note is now editable while
        submitted (see renewal_request_views.xml) - Reject falls back to it
        when no explicit reason= is passed."""
        request = self._make_submitted_request()
        request.decision_note = ''
        with self.assertRaises(UserError):
            request.action_reject()

    def test_reject_with_valid_reason_succeeds(self):
        request = self._make_submitted_request()
        request.action_reject(reason='Owner intends to sell the unit')
        self.assertEqual(request.state, 'rejected')
        self.assertEqual(request.decision_note, 'Owner intends to sell the unit')

    def test_reject_uses_prefilled_decision_note_when_no_reason_argument(self):
        request = self._make_submitted_request()
        request.decision_note = 'Rent increase not acceptable to owner'
        request.action_reject()
        self.assertEqual(request.state, 'rejected')
        self.assertEqual(request.decision_note, 'Rent increase not acceptable to owner')

    def test_reject_reason_persists_and_no_successor_contract_created(self):
        request = self._make_submitted_request()
        request.action_reject(reason='Declined')
        self.assertFalse(request.new_contract_id)
        self.assertEqual(request.contract_id.state, 'active')  # original contract untouched

    def test_approve_still_works_unaffected_by_reject_reason_requirement(self):
        request = self._make_submitted_request()
        request.action_approve()
        self.assertEqual(request.state, 'approved')
        self.assertTrue(request.new_contract_id)


@tagged('post_install', '-at_install')
class TestEdaraRenewalRequestNoteField(TransactionCase):
    """MAT-FIND-008 (2026-09-22): the 'Tenant Message' (note) field was
    unconditionally readonly="1" in the backend form - unlike every sibling
    field - blocking staff from entering it when creating a request on a
    tenant's behalf. Fixed to mirror the same readonly="state != 'submitted'"
    pattern. The portal flow (controllers/portal.py) sets note at create()
    time and never writes it afterwards, so it is unaffected either way -
    and a portal tenant has no write access to this model at all (see
    ir.model.access.csv: perm_write=0 for group_edara_portal_tenant), so
    they can never modify note (or any owner-only decision field) post-
    creation regardless of the view-level readonly state."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Note Branch', 'code': 'NOTE'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Note Property', 'code': 'NOTEP', 'branch_id': cls.branch.id})
        cls.building = cls.env['edara.building'].create(
            {'name': 'Note Building', 'code': 'NOTEB', 'property_id': cls.property.id})
        cls.unit = cls.env['edara.unit'].create(
            {'name': 'N-101', 'code': 'N101', 'building_id': cls.building.id})
        cls.tenant_partner = cls.env['res.partner'].create({'name': 'Note Tenant'})

        cls.branch_manager_group = cls.env.ref('property_managment.group_edara_branch_manager')
        cls.branch_manager = cls.env['res.users'].create({
            'name': 'Note Branch Manager', 'login': 'edara_note_bm', 'password': 'edara_note_bm',
            'group_ids': [(6, 0, [cls.branch_manager_group.id])],
        })
        cls.branch.manager_id = cls.branch_manager

        cls.portal_group = cls.env.ref('property_managment.group_edara_portal_tenant')
        cls.tenant_user = cls.env['res.users'].create({
            'name': 'Note Tenant User', 'login': 'edara_note_tenant', 'password': 'edara_note_tenant',
            'partner_id': cls.tenant_partner.id, 'group_ids': [(6, 0, [cls.portal_group.id])],
        })

        cls.contract = cls.env['edara.lease.contract'].create({
            'unit_id': cls.unit.id, 'tenant_id': cls.tenant_partner.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31),
            'rent_amount': 1000, 'deposit_required': False,
        })
        cls.contract.action_activate()

    def test_staff_can_write_note_while_submitted(self):
        request = self.env['edara.renewal.request'].with_user(self.branch_manager).create({
            'contract_id': self.contract.id,
            'requested_start_date': date(2027, 1, 1), 'requested_end_date': date(2027, 12, 31),
            'requested_rent_amount': 1050,
        })
        request.with_user(self.branch_manager).write({'note': 'Tenant called in to request a renewal'})
        self.assertEqual(request.note, 'Tenant called in to request a renewal')

    def test_portal_tenant_cannot_write_note_after_creation(self):
        request = self.env['edara.renewal.request'].with_user(self.tenant_user).create({
            'contract_id': self.contract.id,
            'requested_start_date': date(2027, 1, 1), 'requested_end_date': date(2027, 12, 31),
            'requested_rent_amount': 1050, 'note': 'Please renew my lease',
        })
        self.assertEqual(request.note, 'Please renew my lease')
        with self.assertRaises(AccessError):
            request.with_user(self.tenant_user).write({'note': 'Trying to edit after submission'})

    def test_portal_tenant_cannot_write_owner_only_decision_fields(self):
        request = self.env['edara.renewal.request'].with_user(self.tenant_user).create({
            'contract_id': self.contract.id,
            'requested_start_date': date(2027, 1, 1), 'requested_end_date': date(2027, 12, 31),
            'requested_rent_amount': 1050,
        })
        with self.assertRaises(AccessError):
            request.with_user(self.tenant_user).write({'decision_note': 'Self-approved'})
        with self.assertRaises(AccessError):
            request.with_user(self.tenant_user).write({'state': 'approved'})
