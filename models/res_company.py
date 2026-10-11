from math import isfinite

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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

    edara_sla_response_enabled = fields.Boolean(
        string='Response SLA Enabled',
        default=False, groups='base.group_user',
        help="Enable response SLA tracking for maintenance requests by default for this company. "
             "Disabled by default. Enabling response SLA does not enable resolution SLA. "
             "The 80% at-risk threshold is fixed in this release.")
    edara_sla_response_hours = fields.Float(
        string='Default Response Target (Hours)',
        default=24.0, groups='base.group_user',
        help="Default target time in hours from request creation until the first qualifying staff action. "
             "24 hours is a suggested value only. Applies when Response SLA is enabled.")
    edara_sla_resolution_enabled = fields.Boolean(
        string='Resolution SLA Enabled',
        default=False, groups='base.group_user',
        help="Enable resolution SLA tracking for maintenance requests by default for this company. "
             "Disabled by default. Enabling resolution SLA does not enable response SLA. "
             "The 80% at-risk threshold is fixed in this release.")
    edara_sla_resolution_hours = fields.Float(
        string='Default Resolution Target (Hours)',
        default=72.0, groups='base.group_user',
        help="Default target time in hours from request creation until final completion. "
             "72 hours is a suggested value only. Applies when Resolution SLA is enabled.")
    edara_sla_notifications_enabled = fields.Boolean(
        string='SLA Notifications Enabled',
        default=True, groups='base.group_user',
        help="Enable automated notifications when maintenance SLA targets approach or breach. "
             "Enabled by default and controlled independently from target activation.")

    @api.constrains('edara_sla_response_enabled', 'edara_sla_response_hours',
                    'edara_sla_resolution_enabled', 'edara_sla_resolution_hours')
    def _check_edara_sla_targets(self):
        for company in self:
            for dimension, label in (('response', _('Response')), ('resolution', _('Resolution'))):
                hours = company['edara_sla_%s_hours' % dimension]
                enabled = company['edara_sla_%s_enabled' % dimension]
                if not isfinite(hours) or hours < 0 or (enabled and hours == 0):
                    raise ValidationError(_(
                        "The %(dimension)s SLA target must be finite and non-negative, "
                        "and strictly positive when enabled.", dimension=label))
