from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

STATES = [
    ('draft', 'Not Collected'),
    ('held', 'Held'),
    ('closed', 'Closed'),
]


class EdaraDeposit(models.Model):
    _name = 'edara.deposit'
    _description = 'EDARA Security Deposit'
    _inherit = ['mail.thread']
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
    state = fields.Selection(STATES, compute='_compute_amounts', store=True, tracking=True)

    _contract_uniq = models.Constraint(
        'unique(contract_id)',
        'A contract can only have one security deposit record.',
    )

    @api.constrains('amount', 'contract_id')
    def _check_amount(self):
        for deposit in self:
            if deposit.amount < 0:
                raise ValidationError(_("Deposit amount cannot be negative."))
            if deposit.contract_id.deposit_required and deposit.amount <= 0:
                raise ValidationError(_(
                    "This contract requires a security deposit; the deposit amount must be positive."))

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

    def _default_transaction_amount(self, transaction_type):
        """Suggested amount for a given transaction type, reused by the wizard's
        default and by action_collect()/action_refund()'s own amount=None
        fallback: Collect -> remaining uncollected amount, Refund/Deduct ->
        current balance. Never negative (clamped to 0)."""
        self.ensure_one()
        if transaction_type == 'held':
            return max(self.amount - self.amount_held, 0.0)
        return max(self.balance, 0.0)

    def action_collect(self, journal_id, amount=None):
        """MAT-FIND-015: authorization first. `edara.deposit.transaction` is
        created BEFORE the native payment (not after, as a plain audit
        record would suggest) specifically so that its own ACL/record-rule
        check - which a Viewer fails, an Accountant/Branch Manager+ passes -
        gates entry to this method's native Accounting elevation. Creating
        the native payment first and the transaction record second would let
        an unauthorized caller trigger a real account.payment before EDARA's
        own authorization ever ran. See _create_deposit_payment() for the
        elevation itself."""
        self.ensure_one()
        self.check_access('write')
        amount = self._default_transaction_amount('held') if amount is None else amount
        if amount <= 0:
            raise UserError(_("There is nothing left to collect for this deposit."))
        transaction = self.env['edara.deposit.transaction'].create({
            'deposit_id': self.id,
            'transaction_type': 'held',
            'amount': amount,
        })
        payment = self._create_deposit_payment('inbound', journal_id, amount)
        transaction.payment_id = payment.id
        return payment

    def action_refund(self, journal_id, amount=None):
        """MAT-FIND-015: same authorization-first ordering as action_collect()
        above - see its docstring."""
        self.ensure_one()
        self.check_access('write')
        amount = self._default_transaction_amount('refund') if amount is None else amount
        if amount <= 0:
            raise UserError(_("There is no deposit balance left to refund."))
        if amount > self.balance:
            raise UserError(_("Cannot refund more than the remaining deposit balance."))
        transaction = self.env['edara.deposit.transaction'].create({
            'deposit_id': self.id,
            'transaction_type': 'refund',
            'amount': amount,
        })
        payment = self._create_deposit_payment('outbound', journal_id, amount)
        transaction.payment_id = payment.id
        return payment

    def action_deduct(self, amount, description):
        """MAT-FIND-015: authorization first, same principle as
        action_collect()/action_refund() above - the edara.deposit.transaction
        record (gated by its own ACL/record rules) is created BEFORE the
        native journal entry, not after, so an unauthorized caller can never
        trigger the elevated account.move.create() below. Amount/accounts/
        partner are already fully resolved server-side above."""
        self.ensure_one()
        self.check_access('write')
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
        transaction = self.env['edara.deposit.transaction'].create({
            'deposit_id': self.id,
            'transaction_type': 'deduction',
            'amount': amount,
            'description': description,
        })
        # Phase 8 (currency correctness): `amount` is denominated in the deposit's own
        # currency (same as the collect/refund payments, which carry currency_id and
        # let native accounting convert). A non-invoice entry line must carry BOTH
        # currency_id/amount_currency (the transaction amount) AND an explicit
        # company-currency balance - Odoo does not derive balance from amount_currency
        # for plain entries - converted at the entry date with the native rate table.
        entry_date = fields.Date.context_today(self)
        currency = self.currency_id
        company_currency = company.currency_id
        balance = company_currency.round(currency._convert(amount, company_currency, company, entry_date))
        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'date': entry_date,
            'company_id': company.id,
            'partner_id': self.tenant_id.id,
            'line_ids': [
                (0, 0, {
                    'account_id': liability_account.id, 'partner_id': self.tenant_id.id,
                    'currency_id': currency.id, 'amount_currency': amount,
                    'debit': balance, 'credit': 0.0, 'name': description,
                }),
                (0, 0, {
                    'account_id': income_account.id, 'partner_id': self.tenant_id.id,
                    'currency_id': currency.id, 'amount_currency': -amount,
                    'debit': 0.0, 'credit': balance, 'name': description,
                }),
            ],
        })
        move.action_post()
        transaction.move_id = move.id
        return self.env['account.move'].browse(move.id)

    def _create_deposit_payment(self, payment_type, journal_id, amount):
        """MAT-FIND-015: narrow, scoped elevation for the native payment
        create+post - see action_collect()/action_refund() above for the
        authorization-first ordering that gates entry to this method.
        `journal_id` is expected to already be a real, company-appropriate
        journal id - resolved by the wizard's own narrowly-scoped
        _resolve_deposit_journal() lookup, or supplied directly by
        already-privileged callers (tests, future business-workflow code)."""
        self.ensure_one()
        if not self.company_id.edara_deposit_liability_account_id:
            raise UserError(_("Configure a Security Deposit account before recording deposits."))
        payment = self.env['account.payment'].sudo().create({
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
        return self.env['account.payment'].browse(payment.id)
