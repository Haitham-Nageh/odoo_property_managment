from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    edara_rental_income_account_id = fields.Many2one('account.account', string='Rental Income Account')
    edara_late_fee_income_account_id = fields.Many2one('account.account', string='Late Fee Income Account')
    edara_service_charge_income_account_id = fields.Many2one('account.account', string='Service Charge Income Account')
    edara_deposit_liability_account_id = fields.Many2one('account.account', string='Security Deposit Liability Account')
    edara_deposit_deduction_income_account_id = fields.Many2one(
        'account.account', string='Deposit Deduction Income Account')
    edara_maintenance_expense_account_id = fields.Many2one(
        'account.account', string='Maintenance Expense Account')
    edara_late_fee_amount = fields.Monetary(
        string='Late Fee Amount', currency_field='currency_id',
        help="Flat amount charged when a Property Manager manually charges a "
             "late fee on an overdue payment schedule line. Never applied automatically.")
