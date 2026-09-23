from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

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
    active_contracts_count = fields.Integer(compute='_compute_kpis')
    renewed_contracts_count = fields.Integer(compute='_compute_kpis')
    terminated_contracts_count = fields.Integer(compute='_compute_kpis')
    expired_contracts_count = fields.Integer(compute='_compute_kpis')
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
    schedule_due_today_count = fields.Integer(compute='_compute_kpis')
    schedule_due_this_month_count = fields.Integer(compute='_compute_kpis')
    schedule_paid_count = fields.Integer(compute='_compute_kpis')
    has_accounting_access = fields.Boolean(compute='_compute_kpis', help=(
        "Whether the current user has native Odoo read access to account.move "
        "and account.payment - drives whether the Accounting-dependent KPI "
        "tiles (Monthly Revenue, Outstanding Receivables, Payments This Month, "
        "and the whole Collections section) are shown at all (MAT-FIND-014)."))

    @api.depends()
    def _compute_kpis(self):
        """Live snapshot, recomputed on every read - same non-stored,
        on-demand pattern as edara.property._compute_financial_summary.

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
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        next_month_start = _next_month_start(month_start)

        total_units = Unit.search_count([])
        occupied_units = Unit.search_count([('occupancy_status', '=', 'rented')])
        # BD-001/MAT-FIND-010 (2026-09-21): canonical direct counts per
        # occupancy_status value - never derived by subtraction (that used to
        # silently miscount reserved/owner_occupied/sold as available).
        available_units = Unit.search_count([('occupancy_status', '=', 'available')])
        reserved_units = Unit.search_count([('occupancy_status', '=', 'reserved')])
        owner_occupied_units = Unit.search_count([('occupancy_status', '=', 'owner_occupied')])
        sold_units = Unit.search_count([('occupancy_status', '=', 'sold')])
        # operational_status is a separate, independent dimension from
        # occupancy_status (MAT/UI-032 §3/§16) - a unit's maintenance count is
        # never added to or subtracted from any occupancy count above.
        under_maintenance_units = Unit.search_count([('operational_status', '=', 'under_maintenance')])

        has_accounting_access = Move.has_access('read') and Payment.has_access('read')
        if has_accounting_access:
            revenue_row = Move._read_group(
                [('state', '=', 'posted'), ('move_type', 'in', ('out_invoice', 'out_refund')),
                 ('invoice_date', '>=', month_start)],
                [], ['amount_untaxed_signed:sum'])
            outstanding_row = Move._read_group(
                [('state', '=', 'posted'), ('move_type', 'in', ('out_invoice', 'out_refund'))],
                [], ['amount_residual_signed:sum'])
            monthly_revenue = revenue_row[0][0] if revenue_row else 0.0
            outstanding_receivables = outstanding_row[0][0] if outstanding_row else 0.0
            maintenance_row = Move._read_group(
                [('state', '=', 'posted'), ('move_type', 'in', ('in_invoice', 'in_refund')),
                 ('edara_invoice_type', '=', 'maintenance'), ('invoice_date', '>=', month_start)],
                [], ['amount_untaxed_signed:sum'])
            maintenance_cost_this_month = -(maintenance_row[0][0] if maintenance_row else 0.0)
            recent_payments_count = Payment.search_count([('date', '>=', month_start)])
            # Collections/Payment Schedule KPIs (MAT/UI-032 §7) - gated behind
            # the same has_accounting_access boolean as a deliberate product
            # choice (this section is "Where Accounting access is available"
            # per the ticket, not a technical ACL requirement of
            # edara.payment.schedule.line itself, which every EDARA role can
            # already read - see action_view_schedule_* below for the matching
            # server-side guard).
            schedule_overdue_count = Schedule.search_count([('state', '=', 'overdue')])
            schedule_due_today_count = Schedule.search_count([('due_date', '=', today)])
            schedule_due_this_month_count = Schedule.search_count(
                [('due_date', '>=', month_start), ('due_date', '<', next_month_start)])
            schedule_paid_count = Schedule.search_count([('state', '=', 'paid')])
        else:
            monthly_revenue = 0.0
            outstanding_receivables = 0.0
            maintenance_cost_this_month = 0.0
            recent_payments_count = 0
            schedule_overdue_count = 0
            schedule_due_today_count = 0
            schedule_due_this_month_count = 0
            schedule_paid_count = 0

        contract_counts = {
            state: Contract.search_count([('state', '=', state)])
            for state in ('draft', 'active', 'renewed', 'terminated', 'expired')
        }
        expiring_soon_count = Contract.search_count(_expiring_soon_domain(today))
        maintenance_counts = {
            state: Maintenance.search_count([('state', '=', state)])
            for state in ('new', 'assigned', 'in_progress', 'done', 'cancelled')
        }
        # Maintenance Phase 2 (2026-09-23): sla_state is non-stored (a live
        # snapshot, see its own help text), so it can't be searched for
        # directly - evaluated in Python over the bounded "open requests
        # with a configured SLA target" set only, same domain the SLA cron
        # itself uses, never a full historical scan.
        sla_candidates = Maintenance.search([
            ('state', 'in', ('new', 'assigned', 'in_progress')),
            ('branch_id.sla_resolution_hours', '>', 0),
        ])
        sla_at_risk_count = len(sla_candidates.filtered(lambda r: r.sla_state == 'at_risk'))
        sla_breached_count = len(sla_candidates.filtered(lambda r: r.sla_state == 'breached'))
        recurring_maintenance_due_count = self.env['edara.recurring.maintenance'].search_count(
            [('active', '=', True), ('next_date', '<=', today)])

        values = {
            'total_properties': self.env['edara.property'].search_count([]),
            'total_buildings': self.env['edara.building'].search_count([]),
            'total_units': total_units,
            'occupied_units': occupied_units,
            'available_units': available_units,
            'reserved_units': reserved_units,
            'owner_occupied_units': owner_occupied_units,
            'sold_units': sold_units,
            'under_maintenance_units': under_maintenance_units,
            'draft_contracts_count': contract_counts['draft'],
            'active_contracts_count': contract_counts['active'],
            'renewed_contracts_count': contract_counts['renewed'],
            'terminated_contracts_count': contract_counts['terminated'],
            'expired_contracts_count': contract_counts['expired'],
            'expiring_soon_contracts_count': expiring_soon_count,
            'maintenance_new_count': maintenance_counts['new'],
            'maintenance_assigned_count': maintenance_counts['assigned'],
            'maintenance_in_progress_count': maintenance_counts['in_progress'],
            'maintenance_done_count': maintenance_counts['done'],
            'maintenance_cancelled_count': maintenance_counts['cancelled'],
            'maintenance_sla_at_risk_count': sla_at_risk_count,
            'maintenance_sla_breached_count': sla_breached_count,
            'recurring_maintenance_due_count': recurring_maintenance_due_count,
            'currency_id': self.env.company.currency_id.id,
            'has_accounting_access': has_accounting_access,
            'monthly_revenue': monthly_revenue,
            'outstanding_receivables': outstanding_receivables,
            'maintenance_cost_this_month': maintenance_cost_this_month,
            'upcoming_renewals_count': self.env['edara.renewal.request'].search_count(
                [('state', '=', 'submitted')]),
            'open_maintenance_count': self.env['edara.maintenance.request'].search_count(
                [('state', 'not in', ('done', 'cancelled'))]),
            'recent_payments_count': recent_payments_count,
            'schedule_overdue_count': schedule_overdue_count,
            'schedule_due_today_count': schedule_due_today_count,
            'schedule_due_this_month_count': schedule_due_this_month_count,
            'schedule_paid_count': schedule_paid_count,
        }
        for dashboard in self:
            dashboard.update(values)

    def action_open(self):
        record = self.create({})
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
        action['domain'] = domain
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

    def action_view_contracts_active(self):
        return self._quick_action('action_edara_lease_contract', [('state', '=', 'active')])

    def action_view_contracts_renewed(self):
        return self._quick_action('action_edara_lease_contract', [('state', '=', 'renewed')])

    def action_view_contracts_terminated(self):
        return self._quick_action('action_edara_lease_contract', [('state', '=', 'terminated')])

    def action_view_contracts_expired(self):
        return self._quick_action('action_edara_lease_contract', [('state', '=', 'expired')])

    def action_view_contracts_expiring_soon(self):
        """BD-003 (2026-09-22): ACTIVE contracts ending within the next
        EXPIRING_SOON_WINDOW_DAYS (30) calendar days."""
        today = fields.Date.context_today(self)
        return self._quick_action('action_edara_lease_contract', _expiring_soon_domain(today))

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
        candidates = self.env['edara.maintenance.request'].search([
            ('state', 'in', ('new', 'assigned', 'in_progress')),
            ('branch_id.sla_resolution_hours', '>', 0),
        ])
        return candidates.filtered(lambda r: r.sla_state == sla_state).ids

    def action_view_maintenance_sla_at_risk(self):
        return self._quick_action('action_edara_maintenance_request', [('id', 'in', self._sla_request_ids('at_risk'))])

    def action_view_maintenance_sla_breached(self):
        return self._quick_action(
            'action_edara_maintenance_request', [('id', 'in', self._sla_request_ids('breached'))])

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
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        next_month_start = _next_month_start(month_start)
        return self._quick_action(
            'action_edara_payment_schedule_line',
            [('due_date', '>=', month_start), ('due_date', '<', next_month_start)])

    def action_view_schedule_paid(self):
        self._require_accounting_access()
        return self._quick_action('action_edara_payment_schedule_line', [('state', '=', 'paid')])

    def action_view_monthly_revenue(self):
        """Same domain as the Monthly Revenue KPI itself (_compute_kpis'
        revenue_row query) - opens the existing Revenue Report, not a new view."""
        self._require_accounting_access()
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        return self._quick_action('action_edara_revenue_report', [
            ('state', '=', 'posted'), ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('invoice_date', '>=', month_start),
        ])

    def action_view_outstanding_receivables(self):
        """Same domain as the Outstanding Receivables KPI (all-time, not month-bound)."""
        self._require_accounting_access()
        return self._quick_action('action_edara_receivables_report', [
            ('state', '=', 'posted'), ('move_type', 'in', ('out_invoice', 'out_refund')),
        ])

    def action_view_payments_this_month(self):
        self._require_accounting_access()
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        return self._quick_action('account.action_account_payments', [('date', '>=', month_start)])

    def action_view_maintenance_cost_this_month(self):
        """Same maintenance-bill relationship the KPI's maintenance_row query
        aggregates over, expressed as a domain on the existing Maintenance
        Cost Report action rather than a new view."""
        self._require_accounting_access()
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        next_month_start = _next_month_start(month_start)
        return self._quick_action('action_edara_maintenance_cost_report', [
            ('vendor_bill_id', '!=', False), ('vendor_bill_id.state', '=', 'posted'),
            ('vendor_bill_id.invoice_date', '>=', month_start),
            ('vendor_bill_id.invoice_date', '<', next_month_start),
        ])

    # ============ Business-level manual triggers (MAT-FIND-007, 2026-09-22) ============
    # Each wraps the SAME method the corresponding daily cron calls - see
    # edara.payment.schedule.line._process_due_invoices()/action_generate_due_invoices_now(),
    # edara.lease.contract._cron_expire_contracts(), and the four
    # _cron_send_*_reminders() methods - so manual and automated execution can
    # never diverge. None of them use sudo(): whoever clicks the button only
    # ever processes what their own record rules already let them see/write,
    # exactly like every other action in this module (MAT-FIND-015's
    # "authorization first" pattern - here, the authorization IS simply not
    # elevating at all).

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
