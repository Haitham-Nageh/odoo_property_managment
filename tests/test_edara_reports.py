from datetime import date

from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install')
class TestEdaraReports(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch = cls.env['edara.branch'].create({'name': 'Ramallah Branch', 'code': 'RAM10'})
        cls.property = cls.env['edara.property'].create(
            {'name': 'Al-Tireh Complex', 'code': 'ATC', 'branch_id': cls.branch.id})
        cls.partner = cls.env['res.partner'].create({'name': 'Report Test Partner'})
        cls.income_account = cls.env['account.account'].create(
            {'name': 'Income (Report Test)', 'code': '401900', 'account_type': 'income'})
        cls.expense_account = cls.env['account.account'].create(
            {'name': 'Expense (Report Test)', 'code': '601900', 'account_type': 'expense'})

    def _make_move(self, move_type, amount, account, posted=True):
        move = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.partner.id,
            'invoice_date': date(2026, 1, 1),
            'edara_property_id': self.property.id,
            'edara_branch_id': self.branch.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Test line', 'quantity': 1, 'price_unit': amount, 'account_id': account.id,
            })],
        })
        if posted:
            move.action_post()
        return move

    def test_financial_summary_computes_revenue_expenses_and_nor(self):
        self._make_move('out_invoice', 1000, self.income_account)
        self._make_move('in_invoice', 400, self.expense_account)
        self.assertAlmostEqual(self.property.total_revenue, 1000)
        self.assertAlmostEqual(self.property.total_expenses, 400)
        self.assertAlmostEqual(self.property.net_operating_result, 600)
        self.assertAlmostEqual(self.property.total_outstanding, 1000)
        self.assertAlmostEqual(self.branch.total_revenue, 1000)
        self.assertAlmostEqual(self.branch.total_expenses, 400)
        self.assertAlmostEqual(self.branch.net_operating_result, 600)

    def test_credit_note_nets_against_revenue(self):
        self._make_move('out_invoice', 1000, self.income_account)
        self._make_move('out_refund', 300, self.income_account)
        self.assertAlmostEqual(self.property.total_revenue, 700)

    def test_draft_move_excluded_from_summary(self):
        self._make_move('out_invoice', 1000, self.income_account, posted=False)
        self.assertAlmostEqual(self.property.total_revenue, 0.0)
        self.assertAlmostEqual(self.property.total_outstanding, 0.0)

    def test_report_pivot_views_load(self):
        for xmlid, model in (
            ('action_edara_revenue_report', 'account.move'),
            ('action_edara_expense_report', 'account.move'),
            ('action_edara_receivables_report', 'account.move'),
            ('action_edara_occupancy_report', 'edara.unit'),
        ):
            action = self.env.ref('property_managment.%s' % xmlid)
            self.assertEqual(action.res_model, model)
            view = self.env[model].get_view(view_id=action.view_id.id, view_type='pivot')
            self.assertTrue(view.get('arch'))

    def test_tenant_ledger_lists_only_tenant_invoices(self):
        action = self.env.ref('property_managment.action_edara_tenant_ledger_report')
        view = self.env['account.move'].get_view(view_id=action.view_id.id, view_type='list')
        self.assertTrue(view.get('arch'))

        tenant = self.env['res.partner'].create({'name': 'Ledger Tenant'})
        unit = self.env['edara.unit'].create(
            {'name': 'A-901', 'code': '901', 'building_id': self.env['edara.building'].create(
                {'name': 'Ledger Bldg', 'code': 'LB', 'property_id': self.property.id}).id})
        contract = self.env['edara.lease.contract'].create({
            'unit_id': unit.id, 'tenant_id': tenant.id,
            'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'rent_amount': 800,
        })
        contract.action_activate()
        move = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': tenant.id, 'invoice_date': date(2026, 1, 1),
            'edara_property_id': self.property.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Rent', 'quantity': 1, 'price_unit': 800, 'account_id': self.income_account.id,
            })],
        })
        move.action_post()
        self._make_move('out_invoice', 1000, self.income_account)  # non-tenant partner, must be excluded

        ledger_moves = self.env['account.move'].search(safe_eval(action.domain))
        self.assertIn(move, ledger_moves)
        self.assertNotIn(self.env['account.move'].search(
            [('partner_id', '=', self.partner.id)], limit=1), ledger_moves)
