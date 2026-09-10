import logging

from odoo import _, api, fields, models, modules
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

STATES = [
    ('draft', 'Draft'),
    ('invoiced', 'Invoiced'),
    ('partial', 'Partially Paid'),
    ('paid', 'Paid'),
    ('overdue', 'Overdue'),
    ('cancelled', 'Cancelled'),
]

INVOICE_PAYMENT_STATE_TO_LINE_STATE = {
    'not_paid': 'invoiced',
    'in_payment': 'paid',
    'paid': 'paid',
    'partial': 'partial',
    'reversed': 'cancelled',
    'blocked': 'invoiced',
    'invoicing_legacy': 'invoiced',
}


class EdaraPaymentScheduleLine(models.Model):
    _name = 'edara.payment.schedule.line'
    _description = 'EDARA Payment Schedule Line'
    _order = 'due_date, id'

    contract_id = fields.Many2one('edara.lease.contract', string='Contract', required=True,
                                   index=True, ondelete='cascade')
    tenant_id = fields.Many2one(related='contract_id.tenant_id', string='Tenant', store=True, index=True)
    unit_id = fields.Many2one(related='contract_id.unit_id', string='Unit', store=True, index=True)
    property_id = fields.Many2one(related='contract_id.property_id', string='Property', store=True, index=True)
    building_id = fields.Many2one(related='contract_id.building_id', string='Building', store=True, index=True)
    branch_id = fields.Many2one(related='contract_id.branch_id', string='Branch', store=True, index=True)
    company_id = fields.Many2one(related='contract_id.company_id', string='Company', store=True, index=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', string='Currency', store=True)

    sequence = fields.Integer(default=10)
    due_date = fields.Date(required=True, index=True)
    amount = fields.Monetary(required=True, currency_field='currency_id')
    description = fields.Char()

    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False, index=True)
    state = fields.Selection(STATES, compute='_compute_state', store=True)

    _invoice_id_uniq = models.Constraint(
        'unique(invoice_id)',
        'An invoice cannot be linked to more than one payment schedule line.',
    )

    def unlink(self):
        """The invoice itself is already protected by native Odoo (a posted
        account.move cannot be unlinked without first resetting to draft, a
        separate accounting permission) - this only stops deleting OUR OWN
        record of which schedule slot produced it, which would silently break
        the audit trail linking a contract's rent periods to their invoices
        even though the invoice/payment history remains untouched. Uninvoiced
        (draft) lines are unaffected - action_terminate() still unlinks them."""
        if any(line.invoice_id for line in self):
            raise UserError(_(
                "An invoiced payment schedule line cannot be deleted, to preserve the "
                "link between the lease contract and its invoice history."))
        return super().unlink()

    @api.depends('invoice_id.payment_state', 'invoice_id.state', 'due_date')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for line in self:
            if not line.invoice_id:
                line.state = 'overdue' if line.due_date < today else 'draft'
            elif line.invoice_id.state == 'cancel':
                line.state = 'cancelled'
            else:
                mapped = INVOICE_PAYMENT_STATE_TO_LINE_STATE.get(line.invoice_id.payment_state, 'invoiced')
                if mapped == 'invoiced' and line.due_date < today:
                    mapped = 'overdue'
                line.state = mapped

    def _create_invoice(self):
        self.ensure_one()
        if self.invoice_id:
            return self.invoice_id
        company = self.company_id
        income_account = company.edara_rental_income_account_id
        if not income_account:
            raise UserError(_(
                "Please configure the Rental Income Account for %(company)s "
                "(Settings > EDARA Property Management) before generating invoices.",
                company=company.display_name,
            ))
        analytic_account = self.property_id.get_analytic_account()
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.tenant_id.id,
            'invoice_date': self.due_date,
            'currency_id': self.currency_id.id,
            'company_id': company.id,
            'edara_invoice_type': 'rent',
            'edara_contract_id': self.contract_id.id,
            'edara_unit_id': self.unit_id.id,
            'edara_building_id': self.building_id.id,
            'edara_property_id': self.property_id.id,
            'edara_branch_id': self.branch_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': self.description or self.contract_id.display_name,
                'quantity': 1,
                'price_unit': self.amount,
                'account_id': income_account.id,
                'analytic_distribution': {str(analytic_account.id): 100.0},
            })],
        })
        invoice.action_post()
        self.invoice_id = invoice.id
        return invoice

    def action_charge_late_fee(self):
        """Manual only, per spec §21 "do not automatically charge arbitrary
        late fees without a business rule" - there is no cron and no
        auto-trigger anywhere for this. A Property Manager/Accountant reviews
        an overdue line and deliberately charges the company-configured flat
        amount as a separate invoice, tagged edara_invoice_type='late_fee' so
        it appears distinctly in the Reports and is netted the same way as
        any other posted revenue."""
        self.ensure_one()
        if self.state != 'overdue':
            raise UserError(_("A late fee can only be charged on an overdue payment schedule line."))
        company = self.company_id
        income_account = company.edara_late_fee_income_account_id
        if not income_account:
            raise UserError(_(
                "Please configure the Late Fee Income Account for %(company)s "
                "(Settings > EDARA Property Management) before charging late fees.",
                company=company.display_name,
            ))
        if not company.edara_late_fee_amount:
            raise UserError(_(
                "Please configure the Late Fee Amount for %(company)s "
                "(Settings > EDARA Property Management) before charging late fees.",
                company=company.display_name,
            ))
        analytic_account = self.property_id.get_analytic_account()
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.tenant_id.id,
            'invoice_date': fields.Date.context_today(self),
            'currency_id': self.currency_id.id,
            'company_id': company.id,
            'edara_invoice_type': 'late_fee',
            'edara_contract_id': self.contract_id.id,
            'edara_unit_id': self.unit_id.id,
            'edara_building_id': self.building_id.id,
            'edara_property_id': self.property_id.id,
            'edara_branch_id': self.branch_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': _("Late fee - %(contract)s due %(due_date)s",
                          contract=self.contract_id.display_name, due_date=self.due_date),
                'quantity': 1,
                'price_unit': company.edara_late_fee_amount,
                'account_id': income_account.id,
                'analytic_distribution': {str(analytic_account.id): 100.0},
            })],
        })
        invoice.action_post()
        return invoice

    @api.model
    def _cron_generate_due_invoices(self):
        """Idempotent, batch-safe: only picks lines with no invoice yet, and
        FOR UPDATE SKIP LOCKED lets concurrent runs (or a slow prior run still
        in flight) partition the work instead of double-invoicing the same line.
        Re-checks contract.state == 'active' as a second defense layer against
        a contract terminated after its schedule lines were generated (the
        first layer is action_terminate() unlinking uninvoiced future lines).
        """
        today = fields.Date.context_today(self)
        self.env.cr.execute("""
            SELECT id FROM edara_payment_schedule_line
            WHERE invoice_id IS NULL AND due_date <= %s
            FOR UPDATE SKIP LOCKED
        """, (today,))
        line_ids = [row[0] for row in self.env.cr.fetchall()]
        auto_commit = not modules.module.current_test
        for line in self.browse(line_ids):
            try:
                if line.contract_id.state != 'active':
                    continue
                line._create_invoice()
                if auto_commit:
                    self.env.cr.commit()
            except Exception:
                _logger.exception("EDARA: failed to generate invoice for payment schedule line %s", line.id)
                if auto_commit:
                    self.env.cr.rollback()
