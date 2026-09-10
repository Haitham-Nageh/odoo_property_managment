from odoo import _, fields, models
from odoo.exceptions import UserError


class EdaraDepositTransactionWizard(models.TransientModel):
    _name = 'edara.deposit.transaction.wizard'
    _description = 'Record Deposit Transaction'

    deposit_id = fields.Many2one('edara.deposit', required=True,
                                  default=lambda self: self.env.context.get('active_id'))
    company_id = fields.Many2one(related='deposit_id.company_id')
    currency_id = fields.Many2one(related='deposit_id.currency_id')
    transaction_type = fields.Selection([
        ('held', 'Collect Deposit'),
        ('refund', 'Refund Deposit'),
        ('deduction', 'Deduct from Deposit'),
    ], required=True, default=lambda self: self.env.context.get('default_transaction_type', 'held'))
    amount = fields.Monetary(required=True, currency_field='currency_id')
    journal_id = fields.Many2one('account.journal', string='Payment Journal',
                                  domain="[('type', 'in', ('cash', 'bank')), ('company_id', '=', company_id)]")
    description = fields.Char(string='Reason')

    def action_confirm(self):
        self.ensure_one()
        if self.transaction_type == 'held':
            if not self.journal_id:
                raise UserError(_("Please select the journal receiving this deposit."))
            self.deposit_id.action_collect(self.journal_id.id, self.amount)
        elif self.transaction_type == 'refund':
            if not self.journal_id:
                raise UserError(_("Please select the journal paying out this refund."))
            self.deposit_id.action_refund(self.journal_id.id, self.amount)
        else:
            if not self.description:
                raise UserError(_("Please describe the reason for this deduction."))
            self.deposit_id.action_deduct(self.amount, self.description)
        return {'type': 'ir.actions.act_window_close'}
