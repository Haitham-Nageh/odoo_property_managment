from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    edara_rental_income_account_id = fields.Many2one(
        related='company_id.edara_rental_income_account_id', readonly=False,
        string='Rental Income Account')
    edara_late_fee_income_account_id = fields.Many2one(
        related='company_id.edara_late_fee_income_account_id', readonly=False,
        string='Late Fee Income Account')
    edara_service_charge_income_account_id = fields.Many2one(
        related='company_id.edara_service_charge_income_account_id', readonly=False,
        string='Service Charge Income Account')
    edara_deposit_liability_account_id = fields.Many2one(
        related='company_id.edara_deposit_liability_account_id', readonly=False,
        string='Security Deposit Liability Account')
    edara_deposit_deduction_income_account_id = fields.Many2one(
        related='company_id.edara_deposit_deduction_income_account_id', readonly=False,
        string='Deposit Deduction Income Account')
    edara_late_fee_amount = fields.Monetary(
        related='company_id.edara_late_fee_amount', readonly=False,
        string='Late Fee Amount', currency_field='currency_id')
