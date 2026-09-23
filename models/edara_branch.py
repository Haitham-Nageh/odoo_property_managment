from odoo import api, fields, models
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

    # Maintenance Phase 2 (2026-09-23), BD-MNT-003: SLA targets are
    # branch-level, not company- or per-request-level - the spec defines no
    # SLA mechanics at all, so branch-level is the reasonable, minimal choice
    # consistent with every other operational parameter in this module
    # already being branch-scoped (matches §11's "do not introduce
    # unnecessary per-request configuration unless required"). 0 disables
    # SLA tracking/notifications for that branch entirely (see
    # edara.maintenance.request.sla_state/_cron_send_sla_notifications).
    sla_response_hours = fields.Float(
        string='SLA Response Target (h)', default=24.0,
        help="Target hours from a maintenance request's creation to its first assignment. 0 disables SLA tracking.")
    sla_resolution_hours = fields.Float(
        string='SLA Resolution Target (h)', default=72.0,
        help="Target hours from a maintenance request's creation to its completion. 0 disables SLA tracking.")

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
