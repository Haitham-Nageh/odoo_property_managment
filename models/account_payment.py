from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    edara_is_security_deposit = fields.Boolean(string='Security Deposit', copy=False)

    @api.depends('journal_id', 'partner_id', 'partner_type', 'edara_is_security_deposit')
    def _compute_destination_account_id(self):
        super()._compute_destination_account_id()
        for pay in self:
            if not pay.edara_is_security_deposit:
                continue
            liability_account = pay.company_id.edara_deposit_liability_account_id
            if not liability_account:
                raise UserError(_("Configure a Security Deposit account before recording deposits."))
            pay.destination_account_id = liability_account
