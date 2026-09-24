from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PRIORITIES = [
    ('low', 'Low'),
    ('normal', 'Normal'),
    ('high', 'High'),
    ('urgent', 'Urgent'),
]

STATES = [
    ('new', 'New'),
    ('assigned', 'Assigned'),
    ('in_progress', 'In Progress'),
    ('done', 'Done'),
    ('cancelled', 'Cancelled'),
]

# Maintenance Phase 2 (2026-09-23): the spec names no maintenance category
# list at all (§41's suggested fields are silent on it) - this generic,
# industry-standard set is a reasonable engineering default, defined once
# here and reused everywhere (never hard-coded inline per the ticket's own
# §27 instruction), not a business-mandated taxonomy. Optional, not required
# - a request/recurring definition can leave it unset.
MAINTENANCE_CATEGORIES = [
    ('plumbing', 'Plumbing'),
    ('electrical', 'Electrical'),
    ('hvac', 'HVAC'),
    ('general', 'General'),
    ('cleaning', 'Cleaning'),
    ('structural', 'Structural'),
    ('other', 'Other'),
]

# Notifications & Reminders Automation (2026-09-22): no explicit deadline
# field exists on this model (spec doesn't define one), so staleness is
# anchored on the only date field that does - requested_date - per the
# ticket's own "do not invent fields just to support a notification" rule.
MAINTENANCE_STALE_DAYS = 3

# Maintenance Phase 2 (2026-09-23), BD-MNT-004: an open request is "at risk"
# once it has used up this fraction of its resolution target without being
# resolved yet - a reasonable, documented engineering default (the spec
# defines no SLA mechanics at all), not a tunable business parameter, since
# no requirement calls for one.
SLA_AT_RISK_THRESHOLD = 0.8


class EdaraMaintenanceRequest(models.Model):
    _name = 'edara.maintenance.request'
    _description = 'EDARA Maintenance Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'requested_date desc, id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True,
                        default=lambda self: _('New'))
    title = fields.Char(required=True, tracking=True)
    description = fields.Text()

    tenant_id = fields.Many2one('res.partner', string='Reported By', index=True, tracking=True)
    unit_id = fields.Many2one('edara.unit', string='Unit', required=True, index=True, tracking=True)
    building_id = fields.Many2one(related='unit_id.building_id', store=True, index=True)
    property_id = fields.Many2one(related='unit_id.property_id', store=True, index=True)
    branch_id = fields.Many2one(related='unit_id.branch_id', store=True, index=True)
    company_id = fields.Many2one(related='unit_id.company_id', store=True, index=True)

    assigned_user_id = fields.Many2one('res.users', string='Assigned To', tracking=True)
    priority = fields.Selection(PRIORITIES, required=True, default='normal', tracking=True)
    state = fields.Selection(STATES, required=True, default='new', tracking=True, copy=False, index=True)
    category = fields.Selection(MAINTENANCE_CATEGORIES, tracking=True)

    requested_date = fields.Date(required=True, default=fields.Date.context_today)
    completed_date = fields.Date(readonly=True, copy=False)

    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    cost = fields.Monetary(currency_field='currency_id')
    vendor_id = fields.Many2one('res.partner', string='Vendor')

    # Maintenance Phase 2 (2026-09-23), SLA / Response Tracking (ticket §10-14):
    # both timestamps are set exactly once (in action_assign()/action_complete()
    # below) and never overwritten by a later edit - readonly=True enforces
    # that from the UI side, and the write-once logic lives in those two
    # methods rather than a generic onchange. completed_date (Date, day
    # granularity) is preserved unchanged; resolved_at is a genuinely
    # different, more precise concept (Datetime) needed for hour-level SLA
    # math, not a duplicate of it.
    first_response_at = fields.Datetime(readonly=True, copy=False, help=(
        "Set exactly once, the first time this request is assigned - never "
        "overwritten by a later re-assignment."))
    resolved_at = fields.Datetime(readonly=True, copy=False, help=(
        "Set exactly once, when this request is completed - the Datetime "
        "counterpart to completed_date (Date), needed for hour-level SLA math."))
    response_hours = fields.Float(compute='_compute_sla_durations', store=True, help=(
        "Hours between creation and first_response_at. Blank until the "
        "request has actually been assigned."))
    resolution_hours = fields.Float(compute='_compute_sla_durations', store=True, help=(
        "Hours between creation and resolved_at. Blank until the request "
        "has actually been completed."))
    sla_response_target_hours = fields.Float(
        related='branch_id.sla_response_hours', string='SLA Response Target (h)')
    sla_resolution_target_hours = fields.Float(
        related='branch_id.sla_resolution_hours', string='SLA Resolution Target (h)')
    sla_state = fields.Selection(
        [('within', 'Within SLA'), ('at_risk', 'At Risk'), ('breached', 'Breached')],
        string='SLA Status', compute='_compute_sla_state', help=(
            "Always derived from timestamps and the branch's configured SLA "
            "targets - never manually settable (ticket §12). Not stored: a "
            "live, on-demand snapshot (same pattern as "
            "edara.dashboard/edara.property._compute_financial_summary) so an "
            "open request's status stays accurate as time passes without a "
            "cron having to rewrite every open record just to keep a stored "
            "value current."))

    # Maintenance Phase 2 (2026-09-23), Recurring Maintenance (ticket §18-23):
    # only ever set on a request generated by edara.recurring.maintenance's
    # cron - blank on every ordinary, manually/tenant-created request. The
    # unique constraint below is the actual idempotency guarantee (ticket
    # §22 explicitly prefers a DB constraint over a Python-only check) -
    # running the generation cron twice can never create two requests for
    # the same recurring definition/occurrence.
    edara_recurring_id = fields.Many2one(
        'edara.recurring.maintenance', string='Recurring Maintenance', readonly=True, copy=False, index=True)
    occurrence_date = fields.Date(readonly=True, copy=False)

    vendor_bill_id = fields.Many2one('account.move', string='Vendor Bill', readonly=True, copy=False, index=True)
    has_accounting_access = fields.Boolean(compute='_compute_has_accounting_access', help=(
        "Whether the current user has native Odoo read access to account.move "
        "- drives whether the Vendor Bill smart button is shown at all (same "
        "permission-aware pattern as edara.dashboard/edara.property, MAT-FIND-014)."))
    vendor_bill_amount_total = fields.Monetary(
        compute='_compute_has_accounting_access', currency_field='currency_id', help=(
            "The Vendor Bill's actual posted total (native Accounting, authoritative) "
            "for the Maintenance Cost report - deliberately separate from `cost`, which "
            "is the estimated/requested amount entered before a bill exists and may "
            "differ from what was actually billed. Degrades to 0 (never AccessError) "
            "for a user without native Accounting read access, same gating as "
            "has_accounting_access above."))

    _vendor_bill_id_uniq = models.Constraint(
        'unique(vendor_bill_id)',
        'A vendor bill cannot be linked to more than one maintenance request.',
    )
    _recurring_occurrence_uniq = models.Constraint(
        'unique(edara_recurring_id, occurrence_date)',
        'A recurring maintenance definition cannot generate more than one request for the same occurrence date.',
    )

    @api.depends('vendor_bill_id.amount_total')
    def _compute_has_accounting_access(self):
        has_access = self.env['account.move'].has_access('read')
        for request in self:
            request.has_accounting_access = has_access
            request.vendor_bill_amount_total = (
                request.vendor_bill_id.amount_total if has_access and request.vendor_bill_id else 0.0)

    @api.depends('first_response_at', 'resolved_at', 'create_date')
    def _compute_sla_durations(self):
        for request in self:
            request.response_hours = (
                (request.first_response_at - request.create_date).total_seconds() / 3600.0
                if request.first_response_at and request.create_date else 0.0)
            request.resolution_hours = (
                (request.resolved_at - request.create_date).total_seconds() / 3600.0
                if request.resolved_at and request.create_date else 0.0)

    @api.depends()
    def _compute_sla_state(self):
        """Live snapshot, recomputed on every read (see sla_state's help
        text) - never stored, so no cron needs to touch every open request
        just to keep this accurate as wall-clock time passes."""
        now = fields.Datetime.now()
        for request in self:
            target = request.sla_resolution_target_hours
            if request.state in ('done', 'cancelled'):
                if not target or not request.resolved_at:
                    request.sla_state = 'within'
                else:
                    request.sla_state = 'within' if request.resolution_hours <= target else 'breached'
                continue
            if not target or not request.create_date:
                request.sla_state = 'within'
                continue
            elapsed_hours = (now - request.create_date).total_seconds() / 3600.0
            if elapsed_hours > target:
                request.sla_state = 'breached'
            elif elapsed_hours > target * SLA_AT_RISK_THRESHOLD:
                request.sla_state = 'at_risk'
            else:
                request.sla_state = 'within'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('edara.maintenance.request') or _('New')
        requests = super().create(vals_list)
        requests._schedule_triage_activity()
        return requests

    def _schedule_triage_activity(self):
        """Notifications & Reminders Automation (2026-09-22): "newly created
        maintenance request" (ticket §7). Reused, not duplicated, by
        _cron_send_maintenance_reminders() below - both call sites idempotently
        check for an already-open activity of the same type before scheduling
        another one, so a request already triaged (or already reminded about)
        is never double-notified."""
        activity_type = self.env.ref('property_managment.mail_activity_type_edara_maintenance')
        for request in self:
            if request.activity_ids.filtered(lambda a: a.activity_type_id == activity_type):
                continue
            user = request.assigned_user_id or request.branch_id.manager_id or self.env.ref('base.user_admin')
            request.activity_schedule(
                activity_type_id=activity_type.id,
                summary=_("New maintenance request"),
                note=_(
                    "%(title)s reported for %(unit)s needs triage.",
                    title=request.title, unit=request.unit_id.display_name,
                ),
                user_id=user.id,
                date_deadline=fields.Date.context_today(self),
            )

    @api.constrains('cost')
    def _check_cost(self):
        for request in self:
            if request.cost < 0:
                raise ValidationError(_("Cost cannot be negative."))

    def unlink(self):
        if any(request.state != 'new' for request in self):
            raise UserError(_(
                "Only a request still in the New state can be deleted - cancel it instead "
                "to preserve the history once it has been assigned or worked on."))
        return super().unlink()

    def action_assign(self, user_id=None):
        """user_id is optional so this can be wired to a plain header button (which
        calls with no arguments) - in that case it uses whatever assigned_user_id
        is already set on the form. Still callable the original way (explicit
        user_id) from Python/other code paths."""
        for request in self:
            if request.state not in ('new', 'assigned'):
                raise UserError(_("Only a new or already-assigned request can be reassigned."))
            if user_id is not None:
                request.assigned_user_id = user_id
            if not request.assigned_user_id:
                raise UserError(_("Select who this request is assigned to before assigning it."))
            request.state = 'assigned'
            if not request.first_response_at:
                # SLA Response Time (ticket §10/§13): set exactly once, on
                # the FIRST assignment - a later re-assignment (state was
                # already 'assigned') must never move it.
                request.first_response_at = fields.Datetime.now()

    def action_start(self):
        for request in self:
            if request.state not in ('new', 'assigned'):
                raise UserError(_("Only a new or assigned request can be started."))
            request.state = 'in_progress'

    def action_complete(self):
        for request in self:
            if request.state not in ('assigned', 'in_progress'):
                raise UserError(_("Only an assigned or in-progress request can be completed."))
            request.write({
                'state': 'done', 'completed_date': fields.Date.context_today(request),
                'resolved_at': fields.Datetime.now(),
            })
            if request.tenant_id:
                request.message_post(
                    body=_(
                        "Your maintenance request %(title)s has been completed.", title=request.title,
                    ),
                    partner_ids=request.tenant_id.ids,
                )

    def action_cancel(self):
        for request in self:
            if request.state in ('done', 'cancelled'):
                raise UserError(_("A completed or already-cancelled request cannot be cancelled."))
            request.state = 'cancelled'

    def action_create_vendor_bill(self):
        """BD-MNT-001 (2026-09-22): Vendor Bills are created manually only,
        never auto-created on completion - maintenance completion and
        accounting settlement are separate business events (a request may be
        operationally done before the vendor's invoice is even available).
        BD-MNT-002: this method, not action_complete(), is where cost/vendor
        are required - completion itself stays unblocked either way.

        MAT-FIND-015 pattern: no EDARA role implies a native Accounting
        group (by design - see EDARA_PROJECT_STATE.md), so creating the
        native vendor bill needs a narrow, scoped elevation. Authorization
        first: normal EDARA write access to THIS request (ACL + record
        rules, e.g. branch scoping) IS the full accounting-access
        verification under this architecture - there is no separate native
        Accounting group to check for, by design. A Viewer's read-only
        access must never be enough to reach the elevated create() below.

        Idempotent: a request already linked to a bill just returns it
        (mirrors every other invoice-creating action in this module) rather
        than creating a second one - this product's scope is one Vendor
        Bill per Maintenance Request (see _vendor_bill_id_uniq)."""
        self.ensure_one()
        self.check_access('write')
        if self.vendor_bill_id:
            return self.vendor_bill_id
        if not self.vendor_id:
            raise UserError(_("Select a Vendor before creating a Vendor Bill."))
        if self.cost <= 0:
            raise UserError(_("A Vendor Bill requires a positive Cost."))
        company = self.company_id
        expense_account = company.edara_maintenance_expense_account_id
        if not expense_account:
            raise UserError(_(
                "Please configure the Maintenance Expense Account for %(company)s "
                "(Settings > EDARA Property Management) before creating a vendor bill.",
                company=company.display_name,
            ))
        analytic_account = self.property_id.get_analytic_account()
        bill = self.env['account.move'].sudo().create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor_id.id,
            'invoice_date': fields.Date.context_today(self),
            'company_id': company.id,
            # Phase 7: cost is denominated in the request's own currency_id, so the
            # bill must be too (it previously fell back to the company currency).
            'currency_id': self.currency_id.id,
            'edara_invoice_type': 'maintenance',
            'edara_unit_id': self.unit_id.id,
            'edara_building_id': self.building_id.id,
            'edara_property_id': self.property_id.id,
            'edara_branch_id': self.branch_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': _("Maintenance - %(request)s", request=self.display_name),
                'quantity': 1,
                'price_unit': self.cost,
                'account_id': expense_account.id,
                # Phase 7: same property analytic account rent/late-fee/service-charge
                # invoices already use, so maintenance cost reaches the property's
                # analytic reporting.
                'analytic_distribution': {str(analytic_account.id): 100.0},
            })],
        })
        self.vendor_bill_id = bill.id
        return self.vendor_bill_id

    def action_view_vendor_bill(self):
        """Smart-button target - separate from action_create_vendor_bill()
        (which never navigates, matching action_charge_late_fee()'s
        established pattern of staying on the originating form). Gated in
        the view by has_accounting_access (MAT-FIND-014 pattern: most EDARA
        roles have no native account.move read access by design), and
        re-checked here server-side since view invisible="" never
        substitutes for a real authorization check (MAT-FIND-014's
        _require_accounting_access() precedent, edara_dashboard.py)."""
        self.ensure_one()
        if not self.env['account.move'].has_access('read'):
            raise UserError(_(
                "Viewing the Vendor Bill requires native Odoo Accounting read "
                "access. Contact your administrator if you believe you should "
                "have this."))
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_in_invoice_type')
        action['res_id'] = self.vendor_bill_id.id
        action['views'] = [(False, 'form')]
        return action

    @api.model
    def _cron_send_maintenance_reminders(self):
        """Notifications & Reminders Automation (2026-09-22): "maintenance
        request requiring attention" / "overdue" (ticket §7), folded into one
        unified "stale open request" reminder rather than two separately-
        thresholded workflows, since no priority-based SLA exists in the spec
        to justify splitting them. Idempotent the same way
        _schedule_triage_activity() is: skips a request that already has an
        open activity of this type, and (correctly) re-reminds one whose
        earlier activity was already marked done but is still open past the
        threshold."""
        today = fields.Date.context_today(self)
        stale_before = today - timedelta(days=MAINTENANCE_STALE_DAYS)
        activity_type = self.env.ref('property_managment.mail_activity_type_edara_maintenance')
        requests = self.search([
            ('state', 'in', ('new', 'assigned', 'in_progress')),
            ('requested_date', '<=', stale_before),
        ])
        sent = 0
        for request in requests:
            if request.activity_ids.filtered(lambda a: a.activity_type_id == activity_type):
                continue
            user = request.assigned_user_id or request.branch_id.manager_id or self.env.ref('base.user_admin')
            request.activity_schedule(
                activity_type_id=activity_type.id,
                summary=_("Maintenance request needs follow-up"),
                note=_(
                    "%(title)s for %(unit)s has been open since %(date)s.",
                    title=request.title, unit=request.unit_id.display_name, date=request.requested_date,
                ),
                user_id=user.id,
                date_deadline=today,
            )
            sent += 1
        return sent

    @api.model
    def _cron_send_sla_notifications(self):
        """Maintenance Phase 2 (2026-09-23), SLA Escalation (ticket §16-17):
        distinct from _cron_send_maintenance_reminders() above (a generic
        "nobody has looked at this in N days" staleness reminder that stays
        unchanged) - this is specifically about the branch's configured SLA
        target being at risk or breached. Bounded domain (open requests whose
        branch has a configured resolution target > 0) rather than a full-
        table scan; sla_state itself is a non-stored live computation (see
        its own help text) so it's evaluated in Python per candidate, not
        searched for directly. Idempotent via the same "does an open
        activity of this type already exist" check every other reminder in
        this module uses - a request already flagged is never re-notified
        until that activity is cleared."""
        activity_type = self.env.ref('property_managment.mail_activity_type_edara_maintenance_sla')
        requests = self.search([
            ('state', 'in', ('new', 'assigned', 'in_progress')),
            ('branch_id.sla_resolution_hours', '>', 0),
        ])
        sent = 0
        for request in requests:
            if request.sla_state not in ('at_risk', 'breached'):
                continue
            if request.activity_ids.filtered(lambda a: a.activity_type_id == activity_type):
                continue
            user = request.assigned_user_id or request.branch_id.manager_id or self.env.ref('base.user_admin')
            summary = (
                _("Maintenance request has breached its SLA") if request.sla_state == 'breached'
                else _("Maintenance request is at risk of breaching its SLA"))
            request.activity_schedule(
                activity_type_id=activity_type.id,
                summary=summary,
                note=_(
                    "%(title)s for %(unit)s: resolution target is %(target).1fh, "
                    "currently open %(elapsed).1fh.",
                    title=request.title, unit=request.unit_id.display_name,
                    target=request.sla_resolution_target_hours,
                    elapsed=(fields.Datetime.now() - request.create_date).total_seconds() / 3600.0,
                ),
                user_id=user.id,
                date_deadline=fields.Date.context_today(self),
            )
            sent += 1
        return sent
