import json
from datetime import date, datetime, time, timedelta
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html_escape
from odoo.tools.misc import format_date

# BD-003 (2026-09-22): ACTIVE contracts whose end_date falls within the next
# 30 calendar days (today through today+30, inclusive of both boundaries).
EXPIRING_SOON_WINDOW_DAYS = 30


def _next_month_start(month_start):
    return (month_start.replace(month=month_start.month + 1) if month_start.month < 12
            else month_start.replace(year=month_start.year + 1, month=1))


def _expiring_soon_domain(today):
    return [
        ('state', '=', 'active'),
        ('end_date', '>=', today),
        ('end_date', '<=', today + timedelta(days=EXPIRING_SOON_WINDOW_DAYS)),
    ]


class EdaraDashboard(models.TransientModel):
    _name = 'edara.dashboard'
    _description = 'EDARA Management Command Center'

    # Phase 6.1 (2026-09-23): with no name/_rec_name field, Odoo's default
    # display_name falls back to "edara.dashboard,<id>" (orm/models.py
    # _compute_display_name) - that raw technical string was showing up in
    # the form's breadcrumb. A fixed, non-stored name closes it without
    # inventing a real business field.
    name = fields.Char(default='EDARA Dashboard')

    # Phase A: Global Context Bar
    branch_id = fields.Many2one(
        'edara.branch',
        string='Branch',
        help="Filter dashboard metrics to a specific branch. When empty, aggregates across all accessible branches.",
    )
    has_multiple_branches = fields.Boolean(
        compute='_compute_branch_info',
        help="Indicates whether the current user has access to multiple branches, to toggle selector vs display label.",
    )
    period_preset = fields.Selection([
        ('this_month', 'This Month'),
        ('this_year', 'This Year'),
        ('custom', 'Custom'),
    ], string='Reporting Period', default='this_month', required=True)
    date_from = fields.Date(string='Date From')
    date_to = fields.Date(string='Date To')

    total_properties = fields.Integer(compute='_compute_kpis')
    total_buildings = fields.Integer(compute='_compute_kpis')
    total_units = fields.Integer(compute='_compute_kpis')
    occupied_units = fields.Integer(compute='_compute_kpis')
    available_units = fields.Integer(compute='_compute_kpis')
    reserved_units = fields.Integer(compute='_compute_kpis')
    owner_occupied_units = fields.Integer(compute='_compute_kpis')
    sold_units = fields.Integer(compute='_compute_kpis')
    under_maintenance_units = fields.Integer(compute='_compute_kpis')

    draft_contracts_count = fields.Integer(compute='_compute_kpis')
    scheduled_contracts_count = fields.Integer(compute='_compute_kpis')
    active_contracts_count = fields.Integer(compute='_compute_kpis')
    renewed_contracts_count = fields.Integer(compute='_compute_kpis')
    terminated_contracts_count = fields.Integer(compute='_compute_kpis')
    expired_contracts_count = fields.Integer(compute='_compute_kpis')
    cancelled_contracts_count = fields.Integer(compute='_compute_kpis')
    expiring_soon_contracts_count = fields.Integer(compute='_compute_kpis')

    maintenance_new_count = fields.Integer(compute='_compute_kpis')
    maintenance_assigned_count = fields.Integer(compute='_compute_kpis')
    maintenance_in_progress_count = fields.Integer(compute='_compute_kpis')
    maintenance_done_count = fields.Integer(compute='_compute_kpis')
    maintenance_cancelled_count = fields.Integer(compute='_compute_kpis')
    maintenance_sla_at_risk_count = fields.Integer(compute='_compute_kpis', help=(
        "Maintenance Phase 2 (2026-09-23): open requests currently 'At Risk' "
        "per their branch's configured SLA resolution target."))
    maintenance_sla_breached_count = fields.Integer(compute='_compute_kpis', help=(
        "Open requests currently 'Breached' per their branch's configured "
        "SLA resolution target."))
    recurring_maintenance_due_count = fields.Integer(compute='_compute_kpis', help=(
        "Active recurring maintenance definitions whose next occurrence is "
        "due today or overdue."))
    maintenance_urgent_count = fields.Integer(compute='_compute_kpis', help=(
        "Open requests currently marked with Urgent priority."))

    expiring_leases_html = fields.Html(compute='_compute_kpis', sanitize=False)
    overdue_payments_html = fields.Html(compute='_compute_kpis', sanitize=False)
    maintenance_attention_html = fields.Html(compute='_compute_kpis', sanitize=False)
    pending_renewals_html = fields.Html(compute='_compute_kpis', sanitize=False)
    recent_activity_html = fields.Html(compute='_compute_kpis', sanitize=False)
    occupancy_chart_data = fields.Text(compute='_compute_kpis')
    revenue_trend_data = fields.Text(compute='_compute_kpis')

    currency_id = fields.Many2one('res.currency', compute='_compute_kpis')
    monthly_revenue = fields.Monetary(compute='_compute_kpis', currency_field='currency_id')
    outstanding_receivables = fields.Monetary(compute='_compute_kpis', currency_field='currency_id')
    maintenance_cost_this_month = fields.Monetary(compute='_compute_kpis', currency_field='currency_id', help=(
        "Posted Vendor Bills tagged edara_invoice_type='maintenance', dated this "
        "month (Reporting & Management Intelligence, 2026-09-22) - the Portfolio "
        "Summary's maintenance-cost figure, per the roadmap's §14."))
    upcoming_renewals_count = fields.Integer(compute='_compute_kpis')
    open_maintenance_count = fields.Integer(compute='_compute_kpis')
    recent_payments_count = fields.Integer(compute='_compute_kpis')
    schedule_overdue_count = fields.Integer(compute='_compute_kpis')
    schedule_overdue_amount = fields.Monetary(compute='_compute_kpis', currency_field='currency_id', help=(
        "Total unpaid residual/amount on currently overdue payment schedule lines."))
    schedule_due_today_count = fields.Integer(compute='_compute_kpis')
    schedule_due_this_month_count = fields.Integer(compute='_compute_kpis')
    schedule_paid_count = fields.Integer(compute='_compute_kpis')
    has_accounting_access = fields.Boolean(compute='_compute_kpis', help=(
        "Whether the current user has native Odoo read access to account.move "
        "and account.payment - drives whether the Accounting-dependent KPI "
        "tiles (Monthly Revenue, Outstanding Receivables, Payments This Month, "
        "and the whole Collections section) are shown at all (MAT-FIND-014)."))

    @api.depends()
    def _compute_branch_info(self):
        """Inspects accessible branches strictly respecting record rules (no sudo)."""
        accessible_count = self.env['edara.branch'].search_count([])
        for dash in self:
            dash.has_multiple_branches = accessible_count > 1

    @api.onchange('period_preset')
    def _onchange_period_preset(self):
        today = fields.Date.context_today(self)
        if self.period_preset == 'this_month':
            month_start = today.replace(day=1)
            self.date_from = month_start
            self.date_to = _next_month_start(month_start) - timedelta(days=1)
        elif self.period_preset == 'this_year':
            self.date_from = date(today.year, 1, 1)
            self.date_to = date(today.year, 12, 31)

    @api.onchange('date_from', 'date_to')
    def _onchange_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationError(_(
                "Date From (%(start)s) cannot be later than Date To (%(end)s).",
                start=self.date_from, end=self.date_to,
            ))

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for dash in self:
            if dash.date_from and dash.date_to and dash.date_from > dash.date_to:
                raise ValidationError(_(
                    "Date From (%(start)s) cannot be later than Date To (%(end)s).",
                    start=dash.date_from, end=dash.date_to,
                ))

    def _get_reporting_period_dates(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        d_from = self.date_from
        d_to = self.date_to
        if not d_from or not d_to:
            if self.period_preset == 'this_year':
                d_from = d_from or date(today.year, 1, 1)
                d_to = d_to or date(today.year, 12, 31)
            else:
                m_start = today.replace(day=1)
                d_from = d_from or m_start
                d_to = d_to or (_next_month_start(m_start) - timedelta(days=1))
        return d_from, d_to

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        if 'period_preset' in fields_list and 'period_preset' not in res:
            res['period_preset'] = 'this_month'
        if 'date_from' in fields_list and 'date_from' not in res:
            res['date_from'] = month_start
        if 'date_to' in fields_list and 'date_to' not in res:
            res['date_to'] = _next_month_start(month_start) - timedelta(days=1)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        for vals in vals_list:
            preset = vals.get('period_preset', 'this_month')
            if preset == 'this_year':
                if 'date_from' not in vals:
                    vals['date_from'] = date(today.year, 1, 1)
                if 'date_to' not in vals:
                    vals['date_to'] = date(today.year, 12, 31)
            elif preset == 'this_month':
                if 'date_from' not in vals:
                    vals['date_from'] = month_start
                if 'date_to' not in vals:
                    vals['date_to'] = _next_month_start(month_start) - timedelta(days=1)
        return super().create(vals_list)

    @api.depends('branch_id', 'period_preset', 'date_from', 'date_to')
    def _compute_kpis(self):
        """Live snapshot, recomputed on every read - same non-stored,
        on-demand pattern as edara.property._compute_financial_summary.

        Phase A: Respects branch filtering (without sudo) and reporting-period
        semantics (reporting metrics use date_from/date_to; current-state
        metrics remain unconstrained by financial date range).

        MAT-FIND-014: a user without native Accounting read access (e.g. an
        EDARA Viewer, or any EDARA role that hasn't separately been granted a
        native Accounting group - EDARA's own groups never imply one, see
        EDARA_PROJECT_STATE.md) must never hit a raw account.move/account.payment
        AccessError just from opening this dashboard. Accounting-dependent KPIs
        are computed only when the user actually has read access to both
        models; otherwise they default to 0 and has_accounting_access is False,
        which the view uses to hide those tiles entirely rather than show a
        misleading $0. This is a permission check, not a privilege escalation -
        nothing here reads accounting data the user isn't already allowed to
        read, and no sudo() is used."""
        Unit = self.env['edara.unit']
        Contract = self.env['edara.lease.contract']
        Maintenance = self.env['edara.maintenance.request']
        Schedule = self.env['edara.payment.schedule.line']
        Move = self.env['account.move']
        Payment = self.env['account.payment']
        Property = self.env['edara.property']
        Building = self.env['edara.building']
        Renewal = self.env['edara.renewal.request']
        Recurring = self.env['edara.recurring.maintenance']
        today = fields.Date.context_today(self)
        comp = self.env.company

        has_accounting_access = Move.has_access('read') and Payment.has_access('read')

        for dashboard in self:
            branch = dashboard.branch_id
            branch_domain = [('branch_id', '=', branch.id)] if branch else []
            move_branch_domain = [('edara_branch_id', '=', branch.id)] if branch else []

            d_from, d_to = dashboard._get_reporting_period_dates()

            total_properties = Property.search_count(branch_domain)
            total_buildings = Building.search_count(branch_domain)
            total_units = Unit.search_count(branch_domain)
            occupied_units = Unit.search_count(branch_domain + [('occupancy_status', '=', 'rented')])
            # BD-001/MAT-FIND-010 (2026-09-21): canonical direct counts per
            # occupancy_status value - never derived by subtraction.
            available_units = Unit.search_count(branch_domain + [('occupancy_status', '=', 'available')])
            reserved_units = Unit.search_count(branch_domain + [('occupancy_status', '=', 'reserved')])
            owner_occupied_units = Unit.search_count(branch_domain + [('occupancy_status', '=', 'owner_occupied')])
            sold_units = Unit.search_count(branch_domain + [('occupancy_status', '=', 'sold')])
            # operational_status is a separate, independent dimension from
            # occupancy_status (MAT/UI-032 §3/§16).
            under_maintenance_units = Unit.search_count(branch_domain + [('operational_status', '=', 'under_maintenance')])

            if has_accounting_access:
                # Reporting-period metrics (Revenue, Maintenance Bills, Payments)
                revenue_domain = [
                    ('state', '=', 'posted'), ('move_type', 'in', ('out_invoice', 'out_refund')),
                    ('invoice_date', '>=', d_from), ('invoice_date', '<=', d_to),
                ] + move_branch_domain
                revenue_row = Move._read_group(revenue_domain, [], ['amount_untaxed_signed:sum'])
                monthly_revenue = revenue_row[0][0] if revenue_row else 0.0

                maint_cost_domain = [
                    ('state', '=', 'posted'), ('move_type', 'in', ('in_invoice', 'in_refund')),
                    ('edara_invoice_type', '=', 'maintenance'),
                    ('invoice_date', '>=', d_from), ('invoice_date', '<=', d_to),
                ] + move_branch_domain
                maintenance_row = Move._read_group(maint_cost_domain, [], ['amount_untaxed_signed:sum'])
                maintenance_cost_this_month = -(maintenance_row[0][0] if maintenance_row else 0.0)

                payment_domain = [('date', '>=', d_from), ('date', '<=', d_to)]
                if branch:
                    branch_invoices = Move.search([('edara_branch_id', '=', branch.id)])
                    payment_domain.append(('reconciled_invoice_ids', 'in', branch_invoices.ids))
                recent_payments_count = Payment.search_count(payment_domain)

                # Current-state financial metrics:
                # Outstanding receivables is cumulative all-time (not filtered by date range)
                outstanding_domain = [
                    ('state', '=', 'posted'), ('move_type', 'in', ('out_invoice', 'out_refund')),
                ] + move_branch_domain
                outstanding_row = Move._read_group(outstanding_domain, [], ['amount_residual_signed:sum'])
                outstanding_receivables = outstanding_row[0][0] if outstanding_row else 0.0

                # Current overdue payments (current state - NOT filtered by reporting period)
                overdue_domain = [('state', '=', 'overdue')] + branch_domain
                schedule_overdue_count = Schedule.search_count(overdue_domain)
                # Overdue amount with multi-currency conversion to company currency
                overdue_lines = Schedule.search(overdue_domain)
                schedule_overdue_amount = 0.0
                comp = self.env.company
                for line in overdue_lines:
                    line_amt = line.invoice_id.amount_residual if line.invoice_id else line.amount
                    if line.currency_id and line.currency_id != comp.currency_id:
                        line_amt = line.currency_id._convert(line_amt, comp.currency_id, comp, today)
                    schedule_overdue_amount += line_amt

                # Due Today (current-state)
                schedule_due_today_count = Schedule.search_count(branch_domain + [('due_date', '=', today)])
                # Due in reporting period (reporting-period metric)
                schedule_due_this_month_count = Schedule.search_count(
                    branch_domain + [('due_date', '>=', d_from), ('due_date', '<=', d_to)])
                # Paid schedule lines
                schedule_paid_count = Schedule.search_count(branch_domain + [('state', '=', 'paid')])
            else:
                monthly_revenue = 0.0
                outstanding_receivables = 0.0
                maintenance_cost_this_month = 0.0
                recent_payments_count = 0
                schedule_overdue_count = 0
                schedule_overdue_amount = 0.0
                schedule_due_today_count = 0
                schedule_due_this_month_count = 0
                schedule_paid_count = 0

            contract_counts = {
                state: Contract.search_count(branch_domain + [('state', '=', state)])
                for state in ('draft', 'scheduled', 'active', 'renewed', 'terminated', 'expired', 'cancelled')
            }
            # Independent lookahead window (today through today + 30 days)
            expiring_soon_domain = branch_domain + _expiring_soon_domain(today)
            expiring_soon_count = Contract.search_count(expiring_soon_domain)
            expiring_soon_records = Contract.search(expiring_soon_domain, order='end_date asc, id asc', limit=5)
            expiring_leases_html = dashboard._render_expiring_leases_html(expiring_soon_records, today)

            if has_accounting_access:
                overdue_payments_html = dashboard._render_overdue_payments_html(overdue_lines[:5], today, comp)
            else:
                overdue_payments_html = False

            maintenance_counts = {
                state: Maintenance.search_count(branch_domain + [('state', '=', state)])
                for state in ('new', 'assigned', 'in_progress', 'done', 'cancelled')
            }
            maint_urgent_candidates = Maintenance.search(branch_domain + [
                ('priority', '=', 'urgent'),
                ('state', 'not in', ('done', 'cancelled')),
            ])
            maintenance_urgent_count = len(maint_urgent_candidates)

            sla_candidates_domain = [
                ('state', 'in', ('new', 'assigned', 'in_progress')),
                ('branch_id.sla_resolution_hours', '>', 0),
            ]
            if branch:
                sla_candidates_domain.append(('branch_id', '=', branch.id))
            sla_candidates = Maintenance.search(sla_candidates_domain)
            sla_at_risk_recs = sla_candidates.filtered(lambda r: r.sla_state == 'at_risk')
            sla_breached_recs = sla_candidates.filtered(lambda r: r.sla_state == 'breached')
            sla_at_risk_count = len(sla_at_risk_recs)
            sla_breached_count = len(sla_breached_recs)

            def _maint_urgency_rank(r):
                if r.sla_state == 'breached':
                    return (0, r.requested_date or date.min, r.id)
                elif r.priority == 'urgent':
                    return (1, r.requested_date or date.min, r.id)
                elif r.sla_state == 'at_risk':
                    return (2, r.requested_date or date.min, r.id)
                return (3, r.requested_date or date.min, r.id)

            attention_maint = sorted(
                maint_urgent_candidates | sla_breached_recs | sla_at_risk_recs,
                key=_maint_urgency_rank
            )[:5]
            maintenance_attention_html = dashboard._render_maintenance_attention_html(attention_maint)

            rec_domain = [('active', '=', True), ('next_date', '<=', today)]
            if branch:
                rec_domain.append(('branch_id', '=', branch.id))
            recurring_maintenance_due_count = Recurring.search_count(rec_domain)

            renewal_domain = branch_domain + [('state', '=', 'submitted')]
            pending_renewals = Renewal.search(renewal_domain, order='id desc', limit=5)
            upcoming_renewals_count = Renewal.search_count(renewal_domain)
            pending_renewals_html = dashboard._render_pending_renewals_html(pending_renewals, comp)

            recent_activity_html = dashboard._render_recent_activity_html(
                branch_domain, branch, comp, has_accounting_access,
            )

            total_occupancy = available_units + reserved_units + occupied_units + owner_occupied_units + sold_units
            occupancy_data = {
                'total': total_occupancy,
                'slices': [
                    {
                        'status': 'available',
                        'label': _('Available'),
                        'count': available_units,
                        'action_method': 'action_view_units_available',
                        'color': '#10B981',
                    },
                    {
                        'status': 'reserved',
                        'label': _('Reserved'),
                        'count': reserved_units,
                        'action_method': 'action_view_units_reserved',
                        'color': '#F59E0B',
                    },
                    {
                        'status': 'rented',
                        'label': _('Rented'),
                        'count': occupied_units,
                        'action_method': 'action_view_units_rented',
                        'color': '#3B82F6',
                    },
                    {
                        'status': 'owner_occupied',
                        'label': _('Owner Occupied'),
                        'count': owner_occupied_units,
                        'action_method': 'action_view_units_owner_occupied',
                        'color': '#8B5CF6',
                    },
                    {
                        'status': 'sold',
                        'label': _('Sold'),
                        'count': sold_units,
                        'action_method': 'action_view_units_sold',
                        'color': '#64748B',
                    },
                ],
                'under_maintenance': {
                    'count': under_maintenance_units,
                    'action_method': 'action_view_units_under_maintenance',
                },
            }
            occupancy_chart_data = json.dumps(occupancy_data)

            # Phase C3: Trailing 6 calendar months Revenue Trend
            cur_month_start = today.replace(day=1)
            window_start = cur_month_start - relativedelta(months=5)
            window_end = (cur_month_start + relativedelta(months=1)) - timedelta(days=1)

            if has_accounting_access:
                trend_domain = [
                    ('state', '=', 'posted'),
                    ('move_type', 'in', ('out_invoice', 'out_refund')),
                    ('invoice_date', '>=', window_start),
                    ('invoice_date', '<=', window_end),
                ] + move_branch_domain
                trend_groups = Move._read_group(
                    trend_domain, ['invoice_date:month'], ['amount_untaxed_signed:sum']
                )
                trend_totals = {
                    (d.year, d.month): round(val or 0.0, 2)
                    for d, val in trend_groups
                    if d
                }
            else:
                trend_totals = {}

            trend_months = []
            total_trend_revenue = 0.0
            for idx in range(6):
                months_ago = 5 - idx
                m_start = cur_month_start - relativedelta(months=months_ago)
                val = trend_totals.get((m_start.year, m_start.month), 0.0) if has_accounting_access else 0.0
                total_trend_revenue += val
                trend_months.append({
                    'index': idx,
                    'label': format_date(self.env, m_start, date_format='MMM yyyy'),
                    'year': m_start.year,
                    'month': m_start.month,
                    'value': val,
                })

            revenue_trend_data = json.dumps({
                'currency': comp.currency_id.name or '',
                'currency_symbol': comp.currency_id.symbol or '',
                'total_revenue': round(total_trend_revenue, 2),
                'months': trend_months,
            })

            dashboard.update({
                'total_properties': total_properties,
                'total_buildings': total_buildings,
                'total_units': total_units,
                'occupied_units': occupied_units,
                'available_units': available_units,
                'reserved_units': reserved_units,
                'owner_occupied_units': owner_occupied_units,
                'sold_units': sold_units,
                'under_maintenance_units': under_maintenance_units,
                'occupancy_chart_data': occupancy_chart_data,
                'revenue_trend_data': revenue_trend_data,
                'draft_contracts_count': contract_counts['draft'],
                'scheduled_contracts_count': contract_counts['scheduled'],
                'active_contracts_count': contract_counts['active'],
                'renewed_contracts_count': contract_counts['renewed'],
                'terminated_contracts_count': contract_counts['terminated'],
                'expired_contracts_count': contract_counts['expired'],
                'cancelled_contracts_count': contract_counts['cancelled'],
                'expiring_soon_contracts_count': expiring_soon_count,
                'expiring_leases_html': expiring_leases_html,
                'maintenance_new_count': maintenance_counts['new'],
                'maintenance_assigned_count': maintenance_counts['assigned'],
                'maintenance_in_progress_count': maintenance_counts['in_progress'],
                'maintenance_done_count': maintenance_counts['done'],
                'maintenance_cancelled_count': maintenance_counts['cancelled'],
                'maintenance_urgent_count': maintenance_urgent_count,
                'maintenance_sla_at_risk_count': sla_at_risk_count,
                'maintenance_sla_breached_count': sla_breached_count,
                'maintenance_attention_html': maintenance_attention_html,
                'recurring_maintenance_due_count': recurring_maintenance_due_count,
                'currency_id': self.env.company.currency_id.id,
                'has_accounting_access': has_accounting_access,
                'monthly_revenue': monthly_revenue,
                'outstanding_receivables': outstanding_receivables,
                'maintenance_cost_this_month': maintenance_cost_this_month,
                'upcoming_renewals_count': upcoming_renewals_count,
                'pending_renewals_html': pending_renewals_html,
                'recent_activity_html': recent_activity_html,
                'open_maintenance_count': Maintenance.search_count(branch_domain + [('state', 'not in', ('done', 'cancelled'))]),
                'recent_payments_count': recent_payments_count,
                'schedule_overdue_count': schedule_overdue_count,
                'schedule_overdue_amount': schedule_overdue_amount,
                'overdue_payments_html': overdue_payments_html,
                'schedule_due_today_count': schedule_due_today_count,
                'schedule_due_this_month_count': schedule_due_this_month_count,
                'schedule_paid_count': schedule_paid_count,
            })

    def _render_expiring_leases_html(self, contracts, today):
        if not contracts:
            return (
                '<div class="o_edara_empty_state text-center text-muted py-3">'
                '<i class="fa fa-check-circle text-success fs-5 mb-1 d-block"/>'
                '<span>No leases expiring soon</span>'
                '</div>'
            )
        items = []
        for c in contracts:
            days_left = (c.end_date - today).days if c.end_date else 0
            if days_left <= 0:
                badge = '<span class="badge bg-danger text-white">Expires today</span>' if days_left == 0 else f'<span class="badge bg-danger text-white">Expired {-days_left}d ago</span>'
            elif days_left == 1:
                badge = '<span class="badge bg-danger text-white">1 day remaining</span>'
            elif days_left <= 7:
                badge = f'<span class="badge bg-danger text-white">{days_left} days remaining</span>'
            else:
                badge = f'<span class="badge bg-warning text-dark">{days_left} days remaining</span>'

            tenant_name = html_escape(c.tenant_id.name or _('Unknown Tenant'))
            contract_ref = html_escape(c.name or '')
            unit_info = html_escape(c.unit_id.name or '')
            if c.property_id:
                unit_info += f' • {html_escape(c.property_id.name)}'
            expiry_str = c.end_date.strftime('%Y-%m-%d') if c.end_date else ''

            items.append(
                f'<a href="/odoo/action-property_managment.action_edara_lease_contract/{c.id}" '
                f'class="o_attention_item text-reset">'
                f'<div class="me-2 text-truncate">'
                f'<div class="fw-bold text-dark text-truncate">{tenant_name} '
                f'<span class="text-muted fw-normal small">({contract_ref})</span></div>'
                f'<div class="text-muted small text-truncate"><i class="fa fa-building-o me-1"/>{unit_info}</div>'
                f'<div class="text-muted small"><i class="fa fa-calendar me-1"/>Expires: {expiry_str}</div>'
                f'</div>'
                f'<div class="text-end flex-shrink-0">'
                f'{badge}'
                f'</div>'
                f'</a>'
            )
        return f'<div class="o_attention_list">{"".join(items)}</div>'

    def _render_overdue_payments_html(self, lines, today, comp):
        if not lines:
            return (
                '<div class="o_edara_empty_state text-center text-muted py-3">'
                '<i class="fa fa-check-circle text-success fs-5 mb-1 d-block"/>'
                '<span>No overdue payments</span>'
                '</div>'
            )
        items = []
        for l in lines:
            days_overdue = (today - l.due_date).days if l.due_date else 0
            line_amt = l.invoice_id.amount_residual if l.invoice_id else l.amount
            curr = l.currency_id or comp.currency_id
            curr_str = curr.symbol or curr.name or ''
            amt_str = f"{line_amt:,.2f} {html_escape(curr_str)}"

            tenant_name = html_escape(l.tenant_id.name or _('Unknown Tenant'))
            contract_ref = html_escape(l.contract_id.name or '')
            unit_str = f" • {html_escape(l.unit_id.name)}" if l.unit_id else ""
            due_str = l.due_date.strftime('%Y-%m-%d') if l.due_date else ''

            items.append(
                f'<a href="/odoo/action-property_managment.action_edara_payment_schedule_line/{l.id}" '
                f'class="o_attention_item text-reset">'
                f'<div class="me-2 text-truncate">'
                f'<div class="fw-bold text-dark text-truncate">{tenant_name} '
                f'<span class="text-muted fw-normal small">({contract_ref}{unit_str})</span></div>'
                f'<div class="text-muted small"><i class="fa fa-calendar me-1"/>Due: {due_str}</div>'
                f'</div>'
                f'<div class="text-end flex-shrink-0">'
                f'<div class="fw-bold text-danger">{amt_str}</div>'
                f'<span class="badge bg-danger text-white">{days_overdue}d overdue</span>'
                f'</div>'
                f'</a>'
            )
        return f'<div class="o_attention_list">{"".join(items)}</div>'

    def _render_maintenance_attention_html(self, requests):
        if not requests:
            return (
                '<div class="o_edara_empty_state text-center text-muted py-3">'
                '<i class="fa fa-check-circle text-success fs-5 mb-1 d-block"/>'
                '<span>No maintenance requiring attention</span>'
                '</div>'
            )
        items = []
        for req in requests:
            title = html_escape(req.title or req.name or '')
            ref = html_escape(req.name or '')
            unit_info = html_escape(req.unit_id.name or '')
            if req.property_id:
                unit_info += f' • {html_escape(req.property_id.name)}'

            badges = []
            if req.priority == 'urgent':
                badges.append('<span class="badge bg-danger text-white">Urgent</span>')
            elif req.priority == 'high':
                badges.append('<span class="badge bg-warning text-dark">High</span>')

            if req.sla_state == 'breached':
                badges.append('<span class="badge bg-danger text-white">SLA Breached</span>')
            elif req.sla_state == 'at_risk':
                badges.append('<span class="badge bg-warning text-dark">SLA At Risk</span>')

            badges_html = ' '.join(badges)

            items.append(
                f'<a href="/odoo/action-property_managment.action_edara_maintenance_request/{req.id}" '
                f'class="o_attention_item text-reset">'
                f'<div class="me-2 text-truncate">'
                f'<div class="fw-bold text-dark text-truncate">{title} '
                f'<span class="text-muted fw-normal small">({ref})</span></div>'
                f'<div class="text-muted small text-truncate"><i class="fa fa-wrench me-1"/>{unit_info}</div>'
                f'</div>'
                f'<div class="text-end flex-shrink-0 d-flex flex-column gap-1 align-items-end">'
                f'{badges_html}'
                f'</div>'
                f'</a>'
            )
        return f'<div class="o_attention_list">{"".join(items)}</div>'

    def _render_pending_renewals_html(self, renewals, comp):
        if not renewals:
            return (
                '<div class="o_edara_empty_state text-center text-muted py-3">'
                '<i class="fa fa-check-circle text-success fs-5 mb-1 d-block"/>'
                '<span>No pending renewal decisions</span>'
                '</div>'
            )
        items = []
        for ren in renewals:
            tenant_name = html_escape(ren.tenant_id.name or _('Unknown Tenant'))
            contract_ref = html_escape(ren.contract_id.name or '')
            unit_str = f" • {html_escape(ren.unit_id.name)}" if ren.unit_id else ""
            end_date_str = ren.requested_end_date.strftime('%Y-%m-%d') if ren.requested_end_date else ''
            rent_amt = ren.requested_rent_amount or 0.0
            curr = ren.currency_id or comp.currency_id
            curr_str = curr.symbol or curr.name or ''
            rent_str = f"{rent_amt:,.2f} {html_escape(curr_str)}"

            items.append(
                f'<a href="/odoo/action-property_managment.action_edara_renewal_request/{ren.id}" '
                f'class="o_attention_item text-reset">'
                f'<div class="me-2 text-truncate">'
                f'<div class="fw-bold text-dark text-truncate">{tenant_name} '
                f'<span class="text-muted fw-normal small">({contract_ref}{unit_str})</span></div>'
                f'<div class="text-muted small"><i class="fa fa-calendar me-1"/>Requested until: {end_date_str}</div>'
                f'</div>'
                f'<div class="text-end flex-shrink-0">'
                f'<div class="fw-bold text-primary">{rent_str}</div>'
                f'<span class="badge bg-info text-dark">Submitted</span>'
                f'</div>'
                f'</a>'
            )
        return f'<div class="o_attention_list">{"".join(items)}</div>'

    def _render_recent_activity_html(self, branch_domain, branch, comp, has_accounting_access):
        """Phase C1: Render a unified, interleaved operational timeline of recent activity.
        Sources:
        - Lease Terminated: edara.lease.contract (state='terminated', termination_date!=False)
        - Maintenance Completed: edara.maintenance.request (state='done', resolved_at or completed_date)
        - Renewal Decision: edara.renewal.request (state in ('approved', 'rejected'), write_date)
        - Payment Received: account.payment (gated by has_accounting_access, inbound, customer, paid)
        Independent candidate queries, merged, sorted descending by timestamp, capped at 8.
        """
        CANDIDATE_LIMIT = 10
        FINAL_CAP = 8
        activities = []

        Contract = self.env['edara.lease.contract']
        Maintenance = self.env['edara.maintenance.request']
        Renewal = self.env['edara.renewal.request']

        # 1. Lease Terminated
        term_domain = branch_domain + [
            ('state', '=', 'terminated'),
            ('termination_date', '!=', False),
        ]
        term_contracts = Contract.search(term_domain, order='termination_date desc, id desc', limit=CANDIDATE_LIMIT)
        for c in term_contracts:
            t_date = c.termination_date
            timestamp = datetime.combine(t_date, time.min)
            unit_str = f" ({c.unit_id.name})" if c.unit_id else ""
            tenant_name = c.tenant_id.name or _('Unknown Tenant')
            activities.append({
                'id': c.id,
                'action_xml_id': 'property_managment.action_edara_lease_contract',
                'timestamp': timestamp,
                'raw_date': t_date,
                'title': f"Lease Terminated: {c.name}",
                'subtitle': f"{tenant_name}{unit_str}",
                'badge_label': 'Terminated',
                'badge_class': 'bg-danger-subtle text-danger border border-danger-subtle',
                'icon_class': 'fa fa-ban text-danger',
                'icon_bg': 'bg-danger-subtle',
            })

        # 2. Maintenance Completed
        # Exclude records where both resolved_at and completed_date are missing.
        maint_domain = branch_domain + [
            ('state', '=', 'done'),
            '|', ('resolved_at', '!=', False), ('completed_date', '!=', False),
        ]
        maint_candidates = Maintenance.search(
            maint_domain,
            order='resolved_at desc nulls last, completed_date desc nulls last, id desc',
            limit=CANDIDATE_LIMIT * 2,
        )
        for m in maint_candidates:
            raw_dt = m.resolved_at or m.completed_date
            if not raw_dt:
                continue
            if isinstance(raw_dt, datetime):
                timestamp = raw_dt
            elif isinstance(raw_dt, date):
                timestamp = datetime.combine(raw_dt, time.min)
            else:
                continue

            unit_str = f" ({m.unit_id.name})" if m.unit_id else ""
            m_title = f": {m.title}" if m.title else ""
            activities.append({
                'id': m.id,
                'action_xml_id': 'property_managment.action_edara_maintenance_request',
                'timestamp': timestamp,
                'raw_date': raw_dt,
                'title': f"Maintenance Completed: {m.name}{m_title}",
                'subtitle': unit_str.strip(),
                'badge_label': 'Completed',
                'badge_class': 'bg-success-subtle text-success border border-success-subtle',
                'icon_class': 'fa fa-wrench text-success',
                'icon_bg': 'bg-success-subtle',
            })

        # 3. Renewal Decision
        renewal_domain = branch_domain + [
            ('state', 'in', ('approved', 'rejected')),
        ]
        renewal_candidates = Renewal.search(renewal_domain, order='write_date desc, id desc', limit=CANDIDATE_LIMIT)
        for ren in renewal_candidates:
            timestamp = ren.write_date or datetime.min
            is_approved = (ren.state == 'approved')
            status_label = 'Approved' if is_approved else 'Rejected'
            badge_class = (
                'bg-success-subtle text-success border border-success-subtle'
                if is_approved
                else 'bg-danger-subtle text-danger border border-danger-subtle'
            )
            icon_class = 'fa fa-check-circle text-success' if is_approved else 'fa fa-times-circle text-danger'
            icon_bg = 'bg-success-subtle' if is_approved else 'bg-danger-subtle'

            contract_str = ren.contract_id.name or _('Contract')
            tenant_str = ren.tenant_id.name or ""
            activities.append({
                'id': ren.id,
                'action_xml_id': 'property_managment.action_edara_renewal_request',
                'timestamp': timestamp,
                'raw_date': timestamp,
                'title': f"Renewal {status_label}: Lease {contract_str}",
                'subtitle': tenant_str,
                'badge_label': status_label,
                'badge_class': badge_class,
                'icon_class': icon_class,
                'icon_bg': icon_bg,
            })

        # 4. Payment Received (accounting-gated)
        if has_accounting_access:
            Payment = self.env['account.payment']
            payment_domain = [
                ('payment_type', '=', 'inbound'),
                ('partner_type', '=', 'customer'),
                ('state', '=', 'paid'),
            ]
            if branch:
                branch_invoices = self.env['account.move'].search([('edara_branch_id', '=', branch.id)])
                payment_domain.append(('reconciled_invoice_ids', 'in', branch_invoices.ids))

            payments = Payment.search(payment_domain, order='date desc, id desc', limit=CANDIDATE_LIMIT)
            for p in payments:
                p_date = p.date or date.min
                timestamp = datetime.combine(p_date, time.min) if isinstance(p_date, date) else p_date

                reconciled_contracts = p.reconciled_invoice_ids.mapped('edara_contract_id').filtered(lambda c: c)
                curr = p.currency_id or comp.currency_id
                curr_str = curr.symbol or curr.name or ''
                amt_str = f"{p.amount:,.2f} {curr_str}".strip()
                partner_name = p.partner_id.name or _('Customer')

                if len(reconciled_contracts) == 1:
                    contract_name = reconciled_contracts[0].name
                    title = f"Payment Received: {amt_str} for Lease {contract_name}"
                    subtitle = partner_name
                else:
                    title = f"Payment Received: {amt_str} from {partner_name}"
                    subtitle = ""

                activities.append({
                    'id': p.id,
                    'action_xml_id': 'account.action_account_payments',
                    'timestamp': timestamp,
                    'raw_date': p_date,
                    'title': title,
                    'subtitle': subtitle,
                    'badge_label': 'Paid',
                    'badge_class': 'bg-primary-subtle text-primary border border-primary-subtle',
                    'icon_class': 'fa fa-money text-primary',
                    'icon_bg': 'bg-primary-subtle',
                })

        if not activities:
            return (
                '<div class="o_edara_empty_state text-center text-muted py-3">'
                '<i class="fa fa-history text-muted fs-5 mb-1 d-block"/>'
                '<span>No recent activity</span>'
                '</div>'
            )

        # Sort descending by timestamp, tie-break by id descending
        activities.sort(key=lambda a: (a['timestamp'], a['id']), reverse=True)
        activities = activities[:FINAL_CAP]

        items = []
        for act in activities:
            url = f"/odoo/action-{act['action_xml_id']}/{act['id']}"
            title = html_escape(act['title'])
            subtitle_val = act['subtitle'].strip() if act['subtitle'] else ""
            subtitle_html = f'<span class="text-muted small ms-1">• {html_escape(subtitle_val)}</span>' if subtitle_val else ""
            badge_label = html_escape(act['badge_label'])
            badge_class = act['badge_class']
            icon_class = act['icon_class']
            icon_bg = act['icon_bg']

            raw_dt = act['raw_date']
            if isinstance(raw_dt, (datetime, date)):
                date_str = raw_dt.strftime('%Y-%m-%d')
            else:
                date_str = html_escape(str(raw_dt or ''))

            items.append(
                f'<a href="{url}" class="o_activity_item text-reset">'
                f'<div class="o_activity_icon {icon_bg}">'
                f'<i class="{icon_class}"/>'
                f'</div>'
                f'<div class="o_activity_content me-2 text-truncate">'
                f'<span class="fw-semibold text-dark">{title}</span>'
                f'{subtitle_html}'
                f'</div>'
                f'<div class="o_activity_meta ms-auto text-end flex-shrink-0">'
                f'<span class="badge {badge_class} me-2">{badge_label}</span>'
                f'<span class="o_activity_date text-muted small">{date_str}</span>'
                f'</div>'
                f'</a>'
            )

        return f'<div class="o_activity_timeline">{"".join(items)}</div>'

    def action_open_attention_record(self):
        """Native action to open the form view of an individual record from the Attention Center.
        Receives target_model and target_id from context. Enforces access rights and record rules without sudo."""
        self.ensure_one()
        res_model = self.env.context.get('target_model')
        res_id = self.env.context.get('target_id')
        ALLOWED_MODELS = {
            'edara.lease.contract': 'property_managment.action_edara_lease_contract',
            'edara.payment.schedule.line': 'property_managment.action_edara_payment_schedule_line',
            'edara.maintenance.request': 'property_managment.action_edara_maintenance_request',
            'edara.renewal.request': 'property_managment.action_edara_renewal_request',
            'account.payment': 'account.action_account_payments',
        }
        if not res_model or res_model not in ALLOWED_MODELS or not res_id:
            raise UserError(_("Invalid or unspecified target record for Attention Center navigation."))

        if res_model in ('edara.payment.schedule.line', 'account.payment'):
            self._require_accounting_access()

        record = self.env[res_model].browse(int(res_id))
        record.check_access('read')
        if not record.exists():
            raise UserError(_("The requested record was not found or is inaccessible."))

        xml_id = ALLOWED_MODELS[res_model]
        action = self.env['ir.actions.act_window']._for_xml_id(xml_id)
        views = action.get('views', [])
        form_view_entry = next((v for v in views if v[1] == 'form'), None)
        action['views'] = [form_view_entry] if form_view_entry else [(False, 'form')]
        action['view_mode'] = 'form'
        action['res_id'] = record.id
        action['target'] = 'current'
        return action

    def action_open(self):
        accessible_branches = self.env['edara.branch'].search([])
        default_vals = {}
        if len(accessible_branches) == 1:
            default_vals['branch_id'] = accessible_branches.id
        record = self.create(default_vals)
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_dashboard')
        action['res_id'] = record.id
        return action

    # ===================== Native quick actions (MAT/UI-032) =====================
    # Every quick action below is a thin wrapper that opens the SAME native
    # act_window action the corresponding top-level EDARA menu already uses,
    # with a domain applied - never a custom filtering mechanism, per the
    # ticket's "Critical Architecture Rule". The resulting domain is visible
    # and editable in Odoo's normal Search Bar exactly like any other native
    # filtered action, and Filters/Group By/Favorites/view-switching all keep
    # working unmodified.

    def _quick_action(self, xml_id, domain):
        self.ensure_one()
        full_xml_id = xml_id if '.' in xml_id else 'property_managment.%s' % xml_id
        action = self.env['ir.actions.act_window']._for_xml_id(full_xml_id)
        combined_domain = list(domain)
        if self.branch_id:
            model = action.get('res_model')
            if model == 'account.move':
                combined_domain.append(('edara_branch_id', '=', self.branch_id.id))
            elif model == 'account.payment':
                branch_invoices = self.env['account.move'].search([('edara_branch_id', '=', self.branch_id.id)])
                combined_domain.append(('reconciled_invoice_ids', 'in', branch_invoices.ids))
            elif model in ('edara.property', 'edara.building', 'edara.unit',
                           'edara.lease.contract', 'edara.maintenance.request',
                           'edara.renewal.request', 'edara.recurring.maintenance',
                           'edara.payment.schedule.line'):
                combined_domain.append(('branch_id', '=', self.branch_id.id))
        action['domain'] = combined_domain
        return action

    def _require_accounting_access(self):
        """Server-side mirror of the view's has_accounting_access-gated
        visibility for the Collections quick actions - never lets a raw
        account.move/account.payment AccessError leak (MAT-FIND-014's
        established pattern), even if a hidden button were invoked directly."""
        if not (self.env['account.move'].has_access('read') and self.env['account.payment'].has_access('read')):
            raise UserError(_(
                "Collections quick actions require native Odoo Accounting read "
                "access. Contact your administrator if you believe you should "
                "have this."))

    def action_view_properties(self):
        return self._quick_action('action_edara_property', [])

    def action_view_buildings(self):
        return self._quick_action('action_edara_building', [])

    def action_view_renewals_pending(self):
        return self._quick_action('action_edara_renewal_request', [('state', '=', 'submitted')])

    def action_view_maintenance_open(self):
        return self._quick_action('action_edara_maintenance_request', [('state', 'not in', ('done', 'cancelled'))])

    def action_view_units_total(self):
        return self._quick_action('action_edara_unit', [])

    def action_view_units_available(self):
        return self._quick_action('action_edara_unit', [('occupancy_status', '=', 'available')])

    def action_view_units_reserved(self):
        return self._quick_action('action_edara_unit', [('occupancy_status', '=', 'reserved')])

    def action_view_units_rented(self):
        return self._quick_action('action_edara_unit', [('occupancy_status', '=', 'rented')])

    def action_view_units_owner_occupied(self):
        return self._quick_action('action_edara_unit', [('occupancy_status', '=', 'owner_occupied')])

    def action_view_units_sold(self):
        return self._quick_action('action_edara_unit', [('occupancy_status', '=', 'sold')])

    def action_view_units_under_maintenance(self):
        return self._quick_action('action_edara_unit', [('operational_status', '=', 'under_maintenance')])

    def action_view_contracts_draft(self):
        return self._quick_action('action_edara_lease_contract', [('state', '=', 'draft')])

    def action_view_contracts_scheduled(self):
        return self._quick_action(
            'action_edara_lease_contract',
            [('state', '=', 'scheduled')],
        )

    def action_view_contracts_active(self):
        return self._quick_action('action_edara_lease_contract', [('state', '=', 'active')])

    def action_view_contracts_renewed(self):
        return self._quick_action('action_edara_lease_contract', [('state', '=', 'renewed')])

    def action_view_contracts_terminated(self):
        return self._quick_action('action_edara_lease_contract', [('state', '=', 'terminated')])

    def action_view_contracts_expired(self):
        return self._quick_action('action_edara_lease_contract', [('state', '=', 'expired')])

    def action_view_contracts_cancelled(self):
        return self._quick_action(
            'action_edara_lease_contract',
            [('state', '=', 'cancelled')],
        )

    def action_view_contracts_expiring_soon(self):
        """BD-003 (2026-09-22): ACTIVE contracts ending within the next
        EXPIRING_SOON_WINDOW_DAYS (30) calendar days."""
        today = fields.Date.context_today(self)
        return self._quick_action('action_edara_lease_contract', _expiring_soon_domain(today))

    def action_view_lease_timeline(self):
        """Phase 11.1: Native Gantt timeline quick action from Dashboard tile."""
        action = self._quick_action('action_edara_lease_contract', [])
        views = action.get('views', [])
        gantt_entry = next((v for v in views if v[1] == 'gantt'), None)
        if gantt_entry:
            action['views'] = [gantt_entry] + [v for v in views if v[1] != 'gantt']
        return action

    def action_view_maintenance_new(self):
        return self._quick_action('action_edara_maintenance_request', [('state', '=', 'new')])

    def action_view_maintenance_assigned(self):
        return self._quick_action('action_edara_maintenance_request', [('state', '=', 'assigned')])

    def action_view_maintenance_in_progress(self):
        return self._quick_action('action_edara_maintenance_request', [('state', '=', 'in_progress')])

    def action_view_maintenance_done(self):
        return self._quick_action('action_edara_maintenance_request', [('state', '=', 'done')])

    def action_view_maintenance_cancelled(self):
        return self._quick_action('action_edara_maintenance_request', [('state', '=', 'cancelled')])

    def _sla_request_ids(self, sla_state):
        """Same bounded 'open + branch has a configured SLA target' set the
        SLA cron/KPI computation itself already uses (never a full historical
        scan) - sla_state is a non-stored live snapshot (Phase 4's own
        documented limitation: it can't be used as a search domain), so the
        click-through filters by an explicit, already-computed id list
        instead of a field domain. Still a normal, editable native list
        filter once opened - just expressed as ('id', 'in', [...])."""
        domain = [
            ('state', 'in', ('new', 'assigned', 'in_progress')),
            ('branch_id.sla_resolution_hours', '>', 0),
        ]
        if self.branch_id:
            domain.append(('branch_id', '=', self.branch_id.id))
        candidates = self.env['edara.maintenance.request'].search(domain)
        return candidates.filtered(lambda r: r.sla_state == sla_state).ids

    def action_view_maintenance_sla_at_risk(self):
        return self._quick_action('action_edara_maintenance_request', [('id', 'in', self._sla_request_ids('at_risk'))])

    def action_view_maintenance_sla_breached(self):
        return self._quick_action(
            'action_edara_maintenance_request', [('id', 'in', self._sla_request_ids('breached'))])

    def action_view_maintenance_urgent(self):
        return self._quick_action(
            'action_edara_maintenance_request',
            [('priority', '=', 'urgent'), ('state', 'not in', ('done', 'cancelled'))]
        )

    def action_view_recurring_maintenance_due(self):
        today = fields.Date.context_today(self)
        return self._quick_action(
            'action_edara_recurring_maintenance', [('active', '=', True), ('next_date', '<=', today)])

    def action_view_schedule_overdue(self):
        self._require_accounting_access()
        return self._quick_action('action_edara_payment_schedule_line', [('state', '=', 'overdue')])

    def action_view_schedule_due_today(self):
        self._require_accounting_access()
        today = fields.Date.context_today(self)
        return self._quick_action('action_edara_payment_schedule_line', [('due_date', '=', today)])

    def action_view_schedule_due_this_month(self):
        self._require_accounting_access()
        d_from, d_to = self._get_reporting_period_dates()
        return self._quick_action(
            'action_edara_payment_schedule_line',
            [('due_date', '>=', d_from), ('due_date', '<=', d_to)])

    def action_view_schedule_paid(self):
        self._require_accounting_access()
        return self._quick_action('action_edara_payment_schedule_line', [('state', '=', 'paid')])

    def action_view_monthly_revenue(self):
        """Same domain as the Monthly Revenue KPI itself (_compute_kpis'
        revenue_row query) - opens the existing Revenue Report, not a new view."""
        self._require_accounting_access()
        d_from, d_to = self._get_reporting_period_dates()
        return self._quick_action('action_edara_revenue_report', [
            ('state', '=', 'posted'), ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('invoice_date', '>=', d_from), ('invoice_date', '<=', d_to),
        ])

    def action_view_revenue_trend_month(self, month_index=None):
        """Phase C3: Opens native Revenue Report filtered to the exact calendar
        month bucket corresponding to month_index (0..5, where 0 is 5 months ago
        and 5 is current month). Fully server-validated and branch-aware."""
        self.ensure_one()
        self._require_accounting_access()
        if month_index is None:
            month_index = self.env.context.get('month_index')
        try:
            month_index = int(month_index)
        except (TypeError, ValueError):
            raise UserError(_("Invalid month index."))
        if month_index < 0 or month_index > 5:
            raise UserError(_("Month index must be between 0 and 5."))

        today = fields.Date.context_today(self)
        cur_month_start = today.replace(day=1)
        months_ago = 5 - month_index
        m_start = cur_month_start - relativedelta(months=months_ago)
        m_end = (m_start + relativedelta(months=1)) - timedelta(days=1)

        domain = [
            ('state', '=', 'posted'),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('invoice_date', '>=', m_start),
            ('invoice_date', '<=', m_end),
        ]
        return self._quick_action('action_edara_revenue_report', domain)

    def action_view_outstanding_receivables(self):
        """Same domain as the Outstanding Receivables KPI (all-time, not month-bound)."""
        self._require_accounting_access()
        return self._quick_action('action_edara_receivables_report', [
            ('state', '=', 'posted'), ('move_type', 'in', ('out_invoice', 'out_refund')),
        ])

    def action_view_payments_this_month(self):
        self._require_accounting_access()
        d_from, d_to = self._get_reporting_period_dates()
        return self._quick_action('account.action_account_payments', [
            ('date', '>=', d_from), ('date', '<=', d_to),
        ])

    def action_view_maintenance_cost_this_month(self):
        """Same maintenance-bill relationship the KPI's maintenance_row query
        aggregates over, expressed as a domain on the existing Maintenance
        Cost Report action rather than a new view."""
        self._require_accounting_access()
        d_from, d_to = self._get_reporting_period_dates()
        return self._quick_action('action_edara_maintenance_cost_report', [
            ('vendor_bill_id', '!=', False), ('vendor_bill_id.state', '=', 'posted'),
            ('vendor_bill_id.invoice_date', '>=', d_from),
            ('vendor_bill_id.invoice_date', '<=', d_to),
        ])

    # ============ Business-level manual triggers (MAT-FIND-007, 2026-09-22) ============
    # Each wraps the SAME method the corresponding daily cron calls - see
    # edara.payment.schedule.line._process_due_invoices()/action_generate_due_invoices_now(),
    # edara.lease.contract._cron_expire_contracts(), and the four
    # _cron_send_*_reminders() methods - so manual and automated execution can
    # never diverge. None of them use sudo(): whoever clicks the button only
    # ever processes what their own record rules already let them see/write,
    # exactly like every other action in this module (MAT-FIND-015's
    # ============ Phase C4: Contextual Record Creation Shortcuts ============

    def action_new_lease_contract(self):
        """Phase C4: Opens a blank create form for edara.lease.contract.
        If a branch is selected on the dashboard, passes restrict_unit_branch_id
        in context so unit_id selection on the form is filtered to that branch."""
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_lease_contract')
        views = action.get('views', [])
        form_view_entry = next((v for v in views if v[1] == 'form'), None)
        action['views'] = [form_view_entry] if form_view_entry else [(False, 'form')]
        action['view_mode'] = 'form'
        action['target'] = 'current'
        context = dict(self.env.context)
        if self.branch_id:
            context['restrict_unit_branch_id'] = self.branch_id.id
        action['context'] = context
        return action

    def action_new_maintenance_request(self):
        """Phase C4: Opens a blank create form for edara.maintenance.request.
        If a branch is selected on the dashboard, passes restrict_unit_branch_id
        in context so unit_id selection on the form is filtered to that branch."""
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_maintenance_request')
        views = action.get('views', [])
        form_view_entry = next((v for v in views if v[1] == 'form'), None)
        action['views'] = [form_view_entry] if form_view_entry else [(False, 'form')]
        action['view_mode'] = 'form'
        action['target'] = 'current'
        context = dict(self.env.context)
        if self.branch_id:
            context['restrict_unit_branch_id'] = self.branch_id.id
        action['context'] = context
        return action

    def action_new_tenant(self):
        """Phase C4: Opens a blank create form for res.partner with default_is_company=False
        to create an individual tenant record."""
        self.ensure_one()
        xml_id = 'contacts.action_contacts' if self.env.ref('contacts.action_contacts', raise_if_not_found=False) else 'base.action_partner_form'
        action = self.env['ir.actions.act_window']._for_xml_id(xml_id)
        views = action.get('views', [])
        form_view_entry = next((v for v in views if v[1] == 'form'), None)
        action['views'] = [form_view_entry] if form_view_entry else [(False, 'form')]
        action['view_mode'] = 'form'
        action['target'] = 'current'
        context = dict(self.env.context)
        context['default_is_company'] = False
        action['context'] = context
        return action

    def _automation_result_notification(self, title, message):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': title, 'message': message, 'type': 'success', 'sticky': False},
        }

    def action_manual_generate_due_invoices(self):
        self.ensure_one()
        created, skipped, errors = self.env['edara.payment.schedule.line'].action_generate_due_invoices_now()
        return self._automation_result_notification(
            _("Generate Due Invoices"),
            _("%(created)d invoice(s) created, %(skipped)d skipped, %(errors)d error(s).",
              created=created, skipped=skipped, errors=errors))

    def action_manual_process_lease_expiry(self):
        self.ensure_one()
        count = self.env['edara.lease.contract']._cron_expire_contracts()
        return self._automation_result_notification(
            _("Process Lease Expiry"), _("%(count)d contract(s) expired.", count=count))

    def action_manual_process_reminders(self):
        self.ensure_one()
        lease = self.env['edara.lease.contract']._cron_send_expiry_reminders()
        renewal = self.env['edara.renewal.request']._cron_send_renewal_reminders()
        overdue = self.env['edara.payment.schedule.line']._cron_send_overdue_reminders()
        maintenance = self.env['edara.maintenance.request']._cron_send_maintenance_reminders()
        sla = self.env['edara.maintenance.request']._cron_send_sla_notifications()
        return self._automation_result_notification(
            _("Process Reminders"),
            _("Lease expiry: %(lease)d, Renewal: %(renewal)d, Overdue payment: %(overdue)d, "
              "Maintenance: %(maintenance)d, SLA alert: %(sla)d reminder(s) sent.",
              lease=lease, renewal=renewal, overdue=overdue, maintenance=maintenance, sla=sla))

    def action_manual_generate_recurring_maintenance(self):
        """Maintenance Phase 2 (2026-09-23), ticket §40: reuses the exact
        cron method, never a second implementation."""
        self.ensure_one()
        count = self.env['edara.recurring.maintenance']._cron_generate_recurring_maintenance()
        return self._automation_result_notification(
            _("Generate Recurring Maintenance"), _("%(count)d maintenance request(s) generated.", count=count))
