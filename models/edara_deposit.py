from odoo import _, api, fields, models
from odoo.exceptions import UserError

STATES = [
    ('draft', 'Not Collected'),
    ('held', 'Held'),
    ('closed', 'Closed'),
]


class EdaraDeposit(models.Model):
    _name = 'edara.deposit'
    _description = 'EDARA Security Deposit'
    _order = 'id desc'

    contract_id = fields.Many2one('edara.lease.contract', string='Contract', required=True,
                                   index=True, ondelete='restrict')
    tenant_id = fields.Many2one(related='contract_id.tenant_id', string='Tenant', store=True)
    unit_id = fields.Many2one(related='contract_id.unit_id', string='Unit', store=True)
    property_id = fields.Many2one(related='contract_id.property_id', string='Property', store=True)
    building_id = fields.Many2one(related='contract_id.building_id', string='Building', store=True)
    branch_id = fields.Many2one(related='contract_id.branch_id', string='Branch', store=True, index=True)
    company_id = fields.Many2one(related='contract_id.company_id', string='Company', store=True, index=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', string='Currency', store=True)

    amount = fields.Monetary(string='Deposit Amount', required=True, currency_field='currency_id')
    transaction_ids = fields.One2many('edara.deposit.transaction', 'deposit_id', string='Transactions')

    amount_held = fields.Monetary(compute='_compute_amounts', store=True, currency_field='currency_id')
    amount_refunded = fields.Monetary(compute='_compute_amounts', store=True, currency_field='currency_id')
    amount_deducted = fields.Monetary(compute='_compute_amounts', store=True, currency_field='currency_id')
    balance = fields.Monetary(compute='_compute_amounts', store=True, currency_field='currency_id')
    state = fields.Selection(STATES, compute='_compute_amounts', store=True)

    _contract_uniq = models.Constraint(
        'unique(contract_id)',
        'A contract can only have one security deposit record.',
    )

    @api.depends('transaction_ids.transaction_type', 'transaction_ids.amount')
    def _compute_amounts(self):
        for deposit in self:
            held = sum(deposit.transaction_ids.filtered(lambda t: t.transaction_type == 'held').mapped('amount'))
            refunded = sum(deposit.transaction_ids.filtered(lambda t: t.transaction_type == 'refund').mapped('amount'))
            deducted = sum(deposit.transaction_ids.filtered(lambda t: t.transaction_type == 'deduction').mapped('amount'))
            deposit.amount_held = held
            deposit.amount_refunded = refunded
            deposit.amount_deducted = deducted
            deposit.balance = held - refunded - deducted
            if held <= 0:
                deposit.state = 'draft'
            elif deposit.balance <= 0:
                deposit.state = 'closed'
            else:
                deposit.state = 'held'

    def action_collect(self, journal_id, amount=None):
        self.ensure_one()
        amount = self.amount - self.amount_held if amount is None else amount
        if amount <= 0:
            raise UserError(_("There is nothing left to collect for this deposit."))
        payment = self._create_deposit_payment('inbound', journal_id, amount)
        self.env['edara.deposit.transaction'].create({
            'deposit_id': self.id,
            'transaction_type': 'held',
            'amount': amount,
            'payment_id': payment.id,
        })
        return payment

    def action_refund(self, journal_id, amount=None):
        self.ensure_one()
        amount = self.balance if amount is None else amount
        if amount <= 0:
            raise UserError(_("There is no deposit balance left to refund."))
        if amount > self.balance:
            raise UserError(_("Cannot refund more than the remaining deposit balance."))
        payment = self._create_deposit_payment('outbound', journal_id, amount)
        self.env['edara.deposit.transaction'].create({
            'deposit_id': self.id,
            'transaction_type': 'refund',
            'amount': amount,
            'payment_id': payment.id,
        })
        return payment

    def action_deduct(self, amount, description):
        self.ensure_one()
        if amount <= 0:
            raise UserError(_("Deduction amount must be positive."))
        if amount > self.balance:
            raise UserError(_("Cannot deduct more than the remaining deposit balance."))
        company = self.company_id
        liability_account = company.edara_deposit_liability_account_id
        income_account = company.edara_deposit_deduction_income_account_id
        if not liability_account:
            raise UserError(_("Configure a Security Deposit account before recording deposits."))
        if not income_account:
            raise UserError(_(
                "Please configure the Deposit Deduction Income Account for %(company)s "
                "(Settings > EDARA Property Management) before recording a deduction.",
                company=company.display_name,
            ))
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self),
            'company_id': company.id,
            'partner_id': self.tenant_id.id,
            'line_ids': [
                (0, 0, {
                    'account_id': liability_account.id, 'partner_id': self.tenant_id.id,
                    'debit': amount, 'credit': 0.0, 'name': description,
                }),
                (0, 0, {
                    'account_id': income_account.id, 'partner_id': self.tenant_id.id,
                    'debit': 0.0, 'credit': amount, 'name': description,
                }),
            ],
        })
        move.action_post()
        self.env['edara.deposit.transaction'].create({
            'deposit_id': self.id,
            'transaction_type': 'deduction',
            'amount': amount,
            'move_id': move.id,
            'description': description,
        })
        return move

    def _create_deposit_payment(self, payment_type, journal_id, amount):
        self.ensure_one()
        if not self.company_id.edara_deposit_liability_account_id:
            raise UserError(_("Configure a Security Deposit account before recording deposits."))
        payment = self.env['account.payment'].create({
            'payment_type': payment_type,
            'partner_type': 'customer',
            'partner_id': self.tenant_id.id,
            'amount': amount,
            'currency_id': self.currency_id.id,
            'journal_id': journal_id,
            'company_id': self.company_id.id,
            'edara_is_security_deposit': True,
            'memo': _("Security deposit - %(contract)s", contract=self.contract_id.display_name),
        })
        payment.action_post()
        return payment
