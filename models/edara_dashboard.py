from odoo import api, fields, models


class EdaraDashboard(models.TransientModel):
    _name = 'edara.dashboard'
    _description = 'EDARA Management Dashboard'

    total_properties = fields.Integer(compute='_compute_kpis')
    total_buildings = fields.Integer(compute='_compute_kpis')
    total_units = fields.Integer(compute='_compute_kpis')
    occupied_units = fields.Integer(compute='_compute_kpis')
    available_units = fields.Integer(compute='_compute_kpis')
    under_maintenance_units = fields.Integer(compute='_compute_kpis')
    currency_id = fields.Many2one('res.currency', compute='_compute_kpis')
    monthly_revenue = fields.Monetary(compute='_compute_kpis', currency_field='currency_id')
    outstanding_receivables = fields.Monetary(compute='_compute_kpis', currency_field='currency_id')
    upcoming_renewals_count = fields.Integer(compute='_compute_kpis')
    open_maintenance_count = fields.Integer(compute='_compute_kpis')
    recent_payments_count = fields.Integer(compute='_compute_kpis')

    @api.depends()
    def _compute_kpis(self):
        """Live snapshot, recomputed on every read - same non-stored,
        on-demand pattern as edara.property._compute_financial_summary."""
        Unit = self.env['edara.unit']
        Move = self.env['account.move']
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)

        total_units = Unit.search_count([])
        occupied_units = Unit.search_count([('occupancy_status', '=', 'rented')])
        under_maintenance_units = Unit.search_count([('operational_status', '=', 'under_maintenance')])

        revenue_row = Move._read_group(
            [('state', '=', 'posted'), ('move_type', 'in', ('out_invoice', 'out_refund')),
             ('invoice_date', '>=', month_start)],
            [], ['amount_untaxed_signed:sum'])
        outstanding_row = Move._read_group(
            [('state', '=', 'posted'), ('move_type', 'in', ('out_invoice', 'out_refund'))],
            [], ['amount_residual_signed:sum'])

        values = {
            'total_properties': self.env['edara.property'].search_count([]),
            'total_buildings': self.env['edara.building'].search_count([]),
            'total_units': total_units,
            'occupied_units': occupied_units,
            'available_units': total_units - occupied_units - under_maintenance_units,
            'under_maintenance_units': under_maintenance_units,
            'currency_id': self.env.company.currency_id.id,
            'monthly_revenue': revenue_row[0][0] if revenue_row else 0.0,
            'outstanding_receivables': outstanding_row[0][0] if outstanding_row else 0.0,
            'upcoming_renewals_count': self.env['edara.renewal.request'].search_count(
                [('state', '=', 'submitted')]),
            'open_maintenance_count': self.env['edara.maintenance.request'].search_count(
                [('state', 'not in', ('done', 'cancelled'))]),
            'recent_payments_count': self.env['account.payment'].search_count(
                [('date', '>=', month_start)]),
        }
        for dashboard in self:
            dashboard.update(values)

    def action_open(self):
        record = self.create({})
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_dashboard')
        action['res_id'] = record.id
        return action
