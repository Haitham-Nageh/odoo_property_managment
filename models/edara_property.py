from odoo import api, fields, models


class EdaraProperty(models.Model):
    _name = 'edara.property'
    _description = 'EDARA Property'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, tracking=True,
                        help="e.g. Al-Irsal Complex, Al-Masyoun Residence.")
    code = fields.Char(required=True, tracking=True)
    branch_id = fields.Many2one('edara.branch', string='Branch', required=True, index=True, tracking=True)
    company_id = fields.Many2one(related='branch_id.company_id', string='Company', store=True, index=True)
    active = fields.Boolean(default=True)

    street = fields.Char()
    city = fields.Char()

    building_ids = fields.One2many('edara.building', 'property_id', string='Buildings')
    building_count = fields.Integer(compute='_compute_building_count')
    unit_count = fields.Integer(compute='_compute_unit_count')

    ownership_ids = fields.One2many('edara.ownership', 'property_id', string='Ownership')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account',
                                           readonly=True, copy=False)

    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    total_revenue = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id')
    total_expenses = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id')
    net_operating_result = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id')
    total_outstanding = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id')
    maintenance_cost = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id', help=(
        "Posted Vendor Bills tagged edara_invoice_type='maintenance' for this property "
        "(Reporting & Management Intelligence, 2026-09-22) - already included in "
        "total_expenses, shown separately so a manager can see how much of a "
        "property's expenses are maintenance-driven."))
    has_accounting_access = fields.Boolean(compute='_compute_financial_summary', help=(
        "Whether the current user has native Odoo read access to account.move "
        "- drives whether the Financial Summary page is shown at all (same "
        "permission-aware pattern as edara.dashboard, MAT-FIND-014)."))

    _code_company_uniq = models.Constraint(
        'unique(company_id, code)',
        'Property code must be unique within a company.',
    )

    @api.depends('building_ids')
    def _compute_building_count(self):
        data = self.env['edara.building']._read_group(
            [('property_id', 'in', self.ids)], ['property_id'], ['__count'])
        counts = {prop.id: count for prop, count in data}
        for prop in self:
            prop.building_count = counts.get(prop.id, 0)

    @api.depends('building_ids.unit_ids')
    def _compute_unit_count(self):
        data = self.env['edara.unit']._read_group(
            [('property_id', 'in', self.ids)], ['property_id'], ['__count'])
        counts = {prop.id: count for prop, count in data}
        for prop in self:
            prop.unit_count = counts.get(prop.id, 0)

    def action_view_buildings(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_building')
        action['domain'] = [('property_id', '=', self.id)]
        action['context'] = {'default_property_id': self.id}
        return action

    def get_analytic_account(self):
        """Return this property's analytic account, creating it on first use.
        Lazy creation avoids cluttering the analytic account list with entries
        for properties that never get invoiced (e.g. still in setup).

        MAT-FIND-015: no EDARA role implies a native Accounting/Analytic
        group (by design - see EDARA_PROJECT_STATE.md), so an EDARA-only
        user cannot create the underlying account.analytic.account record
        without a narrow, scoped elevation. Authorization first: explicitly
        require normal EDARA write access to THIS property (ACL + record
        rules, e.g. branch scoping) before any elevation runs - a Viewer
        (read-only) must never reach the elevated create() just because
        get_analytic_account() happens to be called from a method they
        could otherwise invoke. The elevation itself is limited to this
        single create() call for this single property; the id is written
        back through the normal (non-elevated) environment so the caller
        never holds a broadly-privileged analytic-account recordset."""
        self.ensure_one()
        self.check_access('write')
        if not self.analytic_account_id:
            plan = self.env.ref('property_managment.analytic_plan_edara_property')
            new_account = self.env['account.analytic.account'].sudo().create({
                'name': self.display_name,
                'plan_id': plan.id,
                'company_id': self.company_id.id,
            })
            self.analytic_account_id = new_account.id
        return self.analytic_account_id

    def action_view_units(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_unit')
        action['domain'] = [('property_id', '=', self.id)]
        action['context'] = {'default_property_id': self.id}
        return action

    @api.depends()
    def _compute_financial_summary(self):
        """Not stored, not recomputed automatically - a report-style snapshot
        evaluated whenever the field is read (e.g. the form is opened). Uses
        account.move's own signed-amount conventions (see EDARA_PROJECT_STATE.md
        "Architecture Decisions") so credit notes/refunds net out correctly.

        MAT-FIND-014: a Property is a Viewer-readable record (see
        access_edara_property_viewer), so simply opening one must not raise a
        raw account.move AccessError for a user without native Accounting
        read access. Skip the account.move reads entirely when the user
        lacks that access and expose has_accounting_access so the view can
        hide the whole Financial Summary page rather than show misleading
        zeros - same pattern as edara.dashboard._compute_kpis()."""
        Move = self.env['account.move']
        has_accounting_access = Move.has_access('read')
        for prop in self:
            prop.has_accounting_access = has_accounting_access
            if not has_accounting_access:
                prop.total_revenue = 0.0
                prop.total_expenses = 0.0
                prop.net_operating_result = 0.0
                prop.total_outstanding = 0.0
                prop.maintenance_cost = 0.0
                continue
            revenue_row = Move._read_group(
                [('edara_property_id', '=', prop.id), ('state', '=', 'posted'),
                 ('move_type', 'in', ('out_invoice', 'out_refund'))],
                [], ['amount_untaxed_signed:sum', 'amount_residual_signed:sum'])
            revenue, outstanding = revenue_row[0] if revenue_row else (0.0, 0.0)
            expense_row = Move._read_group(
                [('edara_property_id', '=', prop.id), ('state', '=', 'posted'),
                 ('move_type', 'in', ('in_invoice', 'in_refund'))],
                [], ['amount_untaxed_signed:sum'])
            expenses = -(expense_row[0][0] if expense_row else 0.0)
            maintenance_row = Move._read_group(
                [('edara_property_id', '=', prop.id), ('state', '=', 'posted'),
                 ('move_type', 'in', ('in_invoice', 'in_refund')), ('edara_invoice_type', '=', 'maintenance')],
                [], ['amount_untaxed_signed:sum'])
            maintenance_cost = -(maintenance_row[0][0] if maintenance_row else 0.0)
            prop.total_revenue = revenue or 0.0
            prop.total_expenses = expenses or 0.0
            prop.net_operating_result = (revenue or 0.0) - (expenses or 0.0)
            prop.total_outstanding = outstanding or 0.0
            prop.maintenance_cost = maintenance_cost or 0.0

    def action_view_expenses(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_in_invoice_type')
        action['domain'] = [('edara_property_id', '=', self.id)]
        action['context'] = {'default_move_type': 'in_invoice', 'default_edara_property_id': self.id}
        return action

    def action_view_invoices(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_out_invoice_type')
        action['domain'] = [('edara_property_id', '=', self.id)]
        action['context'] = {'default_move_type': 'out_invoice', 'default_edara_property_id': self.id}
        return action
