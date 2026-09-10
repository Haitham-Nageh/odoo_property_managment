from odoo import _, fields, models
from odoo.exceptions import UserError

TRANSACTION_TYPES = [
    ('held', 'Held'),
    ('refund', 'Refund'),
    ('deduction', 'Deduction'),
]


class EdaraDepositTransaction(models.Model):
    _name = 'edara.deposit.transaction'
    _description = 'EDARA Deposit Transaction'
    _order = 'id desc'

    deposit_id = fields.Many2one('edara.deposit', string='Deposit', required=True,
                                  index=True, ondelete='restrict')
    contract_id = fields.Many2one(related='deposit_id.contract_id', store=True, index=True)
    branch_id = fields.Many2one(related='deposit_id.branch_id', store=True, index=True)
    company_id = fields.Many2one(related='deposit_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='deposit_id.currency_id', store=True)

    transaction_type = fields.Selection(TRANSACTION_TYPES, required=True)
    amount = fields.Monetary(required=True, currency_field='currency_id')
    date = fields.Date(default=fields.Date.context_today)
    description = fields.Char()

    # Index/audit layer only - each transaction must point to the actual account.payment
    # or account.move that carries the real accounting effect. This model is never a
    # parallel ledger (see EDARA_PROJECT_STATE.md "Architecture Decisions").
    payment_id = fields.Many2one('account.payment', string='Payment', readonly=True, copy=False)
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True, copy=False)

    def unlink(self):
        raise UserError(_("Deposit transactions are part of the financial audit trail and cannot be deleted."))
