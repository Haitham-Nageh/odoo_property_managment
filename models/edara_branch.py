from math import isfinite

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EdaraBranch(models.Model):
    _name = 'edara.branch'
    _description = 'EDARA Branch'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, tracking=True,
                        help="Short unique code for this branch within its company (e.g. RAM, NBL).")
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    manager_id = fields.Many2one('res.users', string='Branch Manager', tracking=True)
    user_ids = fields.Many2many(
        'res.users', 'edara_branch_users_rel', 'branch_id', 'user_id',
        string='Assigned Staff',
        help="Internal users who can access records scoped to this branch.")
    active = fields.Boolean(default=True)

    street = fields.Char()
    city = fields.Char()
    phone = fields.Char()
    email = fields.Char()

    property_ids = fields.One2many('edara.property', 'branch_id', string='Properties')
    property_count = fields.Integer(compute='_compute_property_count')

    # U2 Phase 2: input configuration is separate from the stored effective
    # values consumed by maintenance requests, dashboards and notification jobs.
    sla_response_mode = fields.Selection([
        ('inherit', 'Company default'), ('custom', 'Branch override'), ('disabled', 'Disabled'),
    ], string='Response SLA Mode', required=True, default='inherit', groups='base.group_user')
    sla_resolution_mode = fields.Selection([
        ('inherit', 'Company default'), ('custom', 'Branch override'), ('disabled', 'Disabled'),
    ], string='Resolution SLA Mode', required=True, default='inherit', groups='base.group_user')
    sla_response_override_hours = fields.Float(
        string='Response Override (Hours)', default=0.0, groups='base.group_user',
        help="Branch response target. Must be strictly positive in custom mode; otherwise zero is allowed.")
    sla_resolution_override_hours = fields.Float(
        string='Resolution Override (Hours)', default=0.0, groups='base.group_user',
        help="Branch resolution target. Must be strictly positive in custom mode; otherwise zero is allowed.")
    sla_response_enabled = fields.Boolean(
        string='Response SLA Enabled', compute='_compute_effective_sla', store=True, readonly=True,
        groups='base.group_user')
    sla_resolution_enabled = fields.Boolean(
        string='Resolution SLA Enabled', compute='_compute_effective_sla', store=True, readonly=True,
        groups='base.group_user')
    sla_response_hours = fields.Float(
        string='SLA Response Target (h)', compute='_compute_effective_sla', store=True, readonly=True,
        groups='base.group_user',
        help="Effective response target from this branch's mode and company. Zero means disabled.")
    sla_resolution_hours = fields.Float(
        string='SLA Resolution Target (h)', compute='_compute_effective_sla', store=True, readonly=True,
        groups='base.group_user',
        help="Effective resolution target from this branch's mode and company. Zero means disabled.")
    sla_notifications_enabled = fields.Boolean(
        string='SLA Notifications Enabled', compute='_compute_effective_sla', store=True, readonly=True,
        groups='base.group_user', help="Inherits the company notification setting independently of target activation.")
    # Selection labels translate on read; no language-dependent text is stored.
    sla_response_source = fields.Selection(
        related='sla_response_mode', string='Response Configuration Source', readonly=True, store=False,
        groups='base.group_user')
    sla_resolution_source = fields.Selection(
        related='sla_resolution_mode', string='Resolution Configuration Source', readonly=True, store=False,
        groups='base.group_user')

    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    total_revenue = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id')
    total_expenses = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id')
    net_operating_result = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id')
    total_outstanding = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id')
    maintenance_cost = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id', help=(
        "Posted Vendor Bills tagged edara_invoice_type='maintenance' for this branch "
        "(Reporting & Management Intelligence, 2026-09-22) - already included in "
        "total_expenses, shown separately for maintenance-cost visibility."))
    has_accounting_access = fields.Boolean(compute='_compute_financial_summary', help=(
        "Whether the current user has native Odoo read access to account.move "
        "- drives whether the Financial Summary page is shown at all (same "
        "permission-aware pattern as edara.dashboard, MAT-FIND-014)."))

    _code_company_uniq = models.Constraint(
        'unique(company_id, code)',
        'Branch code must be unique within a company.',
    )

    @api.constrains('code')
    def _check_code(self):
        for branch in self:
            if not branch.code or not branch.code.strip():
                raise ValidationError(self.env._("Branch code cannot be empty."))

    @api.depends(
        'company_id', 'sla_response_mode', 'sla_resolution_mode',
        'sla_response_override_hours', 'sla_resolution_override_hours',
        'company_id.edara_sla_response_enabled', 'company_id.edara_sla_response_hours',
        'company_id.edara_sla_resolution_enabled', 'company_id.edara_sla_resolution_hours',
        'company_id.edara_sla_notifications_enabled',
    )
    def _compute_effective_sla(self):
        for branch in self:
            company = branch.company_id
            for dimension in ('response', 'resolution'):
                mode = branch['sla_%s_mode' % dimension]
                if mode == 'inherit':
                    enabled = company['edara_sla_%s_enabled' % dimension]
                    hours = company['edara_sla_%s_hours' % dimension]
                elif mode == 'custom':
                    enabled = True
                    hours = branch['sla_%s_override_hours' % dimension]
                else:
                    enabled, hours = False, 0.0
                # An incomplete form or corrupted input must never activate a target.
                enabled = bool(enabled and isfinite(hours) and hours > 0)
                branch['sla_%s_enabled' % dimension] = enabled
                branch['sla_%s_hours' % dimension] = hours if enabled else 0.0
            branch.sla_notifications_enabled = company.edara_sla_notifications_enabled

    @api.constrains('sla_response_mode', 'sla_resolution_mode',
                    'sla_response_override_hours', 'sla_resolution_override_hours')
    def _check_sla_configuration(self):
        for branch in self:
            for dimension, label in (('response', _('Response')), ('resolution', _('Resolution'))):
                hours = branch['sla_%s_override_hours' % dimension]
                custom = branch['sla_%s_mode' % dimension] == 'custom'
                if not isfinite(hours) or hours < 0 or (custom and hours == 0):
                    raise ValidationError(_(
                        "The %(dimension)s SLA override must be finite and non-negative, "
                        "and strictly positive in custom mode.", dimension=label))

    @api.depends('property_ids')
    def _compute_property_count(self):
        data = self.env['edara.property']._read_group(
            [('branch_id', 'in', self.ids)], ['branch_id'], ['__count'])
        counts = {branch.id: count for branch, count in data}
        for branch in self:
            branch.property_count = counts.get(branch.id, 0)

    @api.depends()
    def _compute_financial_summary(self):
        """See edara.property._compute_financial_summary for the sign-convention
        notes and the MAT-FIND-014 permission-aware rationale (a Branch is
        Viewer-readable, so opening one must not raise a raw account.move
        AccessError for a user without native Accounting read access)."""
        Move = self.env['account.move']
        has_accounting_access = Move.has_access('read')
        for branch in self:
            branch.has_accounting_access = has_accounting_access
            if not has_accounting_access:
                branch.total_revenue = 0.0
                branch.total_expenses = 0.0
                branch.net_operating_result = 0.0
                branch.total_outstanding = 0.0
                branch.maintenance_cost = 0.0
                continue
            revenue_row = Move._read_group(
                [('edara_branch_id', '=', branch.id), ('state', '=', 'posted'),
                 ('move_type', 'in', ('out_invoice', 'out_refund'))],
                [], ['amount_untaxed_signed:sum', 'amount_residual_signed:sum'])
            revenue, outstanding = revenue_row[0] if revenue_row else (0.0, 0.0)
            expense_row = Move._read_group(
                [('edara_branch_id', '=', branch.id), ('state', '=', 'posted'),
                 ('move_type', 'in', ('in_invoice', 'in_refund'))],
                [], ['amount_untaxed_signed:sum'])
            expenses = -(expense_row[0][0] if expense_row else 0.0)
            maintenance_row = Move._read_group(
                [('edara_branch_id', '=', branch.id), ('state', '=', 'posted'),
                 ('move_type', 'in', ('in_invoice', 'in_refund')), ('edara_invoice_type', '=', 'maintenance')],
                [], ['amount_untaxed_signed:sum'])
            maintenance_cost = -(maintenance_row[0][0] if maintenance_row else 0.0)
            branch.total_revenue = revenue or 0.0
            branch.total_expenses = expenses or 0.0
            branch.net_operating_result = (revenue or 0.0) - (expenses or 0.0)
            branch.total_outstanding = outstanding or 0.0
            branch.maintenance_cost = maintenance_cost or 0.0

    def action_view_properties(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_property')
        action['domain'] = [('branch_id', '=', self.id)]
        action['context'] = {'default_branch_id': self.id}
        return action
