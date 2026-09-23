from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEdaraHardening(TransactionCase):
    """Phase 13 hardening: company/branch consistency for account.move's
    freely-editable EDARA tag fields (see account_move.py's
    _check_edara_tags_consistent for why these aren't related fields)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch_a = cls.env['edara.branch'].create({'name': 'Branch A', 'code': 'HRDA'})
        cls.branch_b = cls.env['edara.branch'].create({'name': 'Branch B', 'code': 'HRDB'})
        cls.property_a = cls.env['edara.property'].create(
            {'name': 'Property A', 'code': 'HPA', 'branch_id': cls.branch_a.id})
        cls.property_b = cls.env['edara.property'].create(
            {'name': 'Property B', 'code': 'HPB', 'branch_id': cls.branch_b.id})
        cls.partner = cls.env['res.partner'].create({'name': 'Hardening Test Partner'})
        cls.income_account = cls.env['account.account'].create(
            {'name': 'Income (Hardening Test)', 'code': '402900', 'account_type': 'income'})

    def _make_move(self, **edara_fields):
        return self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Line', 'quantity': 1, 'price_unit': 100, 'account_id': self.income_account.id,
            })],
            **edara_fields,
        })

    def test_property_and_branch_from_different_branches_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_move(edara_property_id=self.property_a.id, edara_branch_id=self.branch_b.id)

    def test_property_and_branch_from_same_branch_accepted(self):
        move = self._make_move(edara_property_id=self.property_a.id, edara_branch_id=self.branch_a.id)
        self.assertTrue(move)

    def test_building_from_different_property_rejected(self):
        building_b = self.env['edara.building'].create(
            {'name': 'Building B', 'code': 'HB', 'property_id': self.property_b.id})
        with self.assertRaises(ValidationError):
            self._make_move(edara_property_id=self.property_a.id, edara_building_id=building_b.id)

    def test_unit_from_different_building_rejected(self):
        building_a = self.env['edara.building'].create(
            {'name': 'Building A', 'code': 'HA', 'property_id': self.property_a.id})
        building_a2 = self.env['edara.building'].create(
            {'name': 'Building A2', 'code': 'HA2', 'property_id': self.property_a.id})
        unit_a2 = self.env['edara.unit'].create(
            {'name': 'Unit A2-1', 'code': 'HA2U1', 'building_id': building_a2.id})
        with self.assertRaises(ValidationError):
            self._make_move(edara_building_id=building_a.id, edara_unit_id=unit_a2.id)

    def test_move_form_exposes_edara_tag_fields(self):
        """The tag fields had onchange/constraint logic since Phase 7 but were
        never actually shown on the invoice/bill form - fixed 2026-09-13
        (views/account_move_views.xml). Regression: confirm the fields are
        really reachable from the rendered form, not just present on the model."""
        arch = self.env['account.move'].get_view(view_id=self.env.ref('account.view_move_form').id)['arch']
        tree = etree.fromstring(arch)
        for field_name in ('edara_invoice_type', 'edara_contract_id', 'edara_branch_id',
                            'edara_property_id', 'edara_building_id', 'edara_unit_id'):
            self.assertTrue(tree.xpath("//field[@name='%s']" % field_name),
                             "%s should be present on the account.move form" % field_name)
