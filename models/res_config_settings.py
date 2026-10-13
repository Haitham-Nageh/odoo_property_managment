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
    edara_maintenance_expense_account_id = fields.Many2one(
        related='company_id.edara_maintenance_expense_account_id', readonly=False,
        string='Maintenance Expense Account')
    edara_late_fee_amount = fields.Monetary(
        related='company_id.edara_late_fee_amount', readonly=False,
        string='Late Fee Amount', currency_field='currency_id')

    edara_sla_response_enabled = fields.Boolean(
        related='company_id.edara_sla_response_enabled', readonly=False,
        string='Response SLA Enabled',
        help="Enable response SLA tracking for maintenance requests by default for this company. "
             "Disabled by default. Enabling response SLA does not enable resolution SLA. "
             "The 80% at-risk threshold is fixed in this release.")
    edara_sla_response_hours = fields.Float(
        related='company_id.edara_sla_response_hours', readonly=False,
        string='Default Response Target (Hours)',
        help="Default target time in hours from request creation until the first qualifying staff action. "
             "24 hours is a suggested value only. Applies when Response SLA is enabled.")
    edara_sla_resolution_enabled = fields.Boolean(
        related='company_id.edara_sla_resolution_enabled', readonly=False,
        string='Resolution SLA Enabled',
        help="Enable resolution SLA tracking for maintenance requests by default for this company. "
             "Disabled by default. Enabling resolution SLA does not enable response SLA. "
             "The 80% at-risk threshold is fixed in this release.")
    edara_sla_resolution_hours = fields.Float(
        related='company_id.edara_sla_resolution_hours', readonly=False,
        string='Default Resolution Target (Hours)',
        help="Default target time in hours from request creation until final completion. "
             "72 hours is a suggested value only. Applies when Resolution SLA is enabled.")
    edara_sla_notifications_enabled = fields.Boolean(
        related='company_id.edara_sla_notifications_enabled', readonly=False,
        string='SLA Notifications Enabled',
        help="Enable automated notifications when maintenance SLA targets approach or breach. "
             "Enabled by default and controlled independently from target activation.")

    edara_portal_grace_days = fields.Integer(
        related='company_id.edara_portal_grace_days', readonly=False,
        string='Portal Grace Period (Days)',
        help="Number of days tenant retains portal access after contract ends or obligations are settled.")
