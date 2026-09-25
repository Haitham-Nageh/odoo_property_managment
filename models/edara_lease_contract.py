from dateutil.relativedelta import relativedelta
from fractions import Fraction

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from . import edara_proration as proration

BILLING_FREQUENCIES = [
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly'),
    ('yearly', 'Yearly'),
]

PERIOD_MONTHS = {'monthly': 1, 'quarterly': 3, 'yearly': 12}

# Phase 10.1: 'scheduled' = confirmed, start_date still in the future (protects the unit from
# double-leasing, never invoiced); 'cancelled' = a scheduled lease withdrawn before it started.
STATES = [
    ('draft', 'Draft'),
    ('scheduled', 'Scheduled'),
    ('active', 'Active'),
    ('renewed', 'Renewed'),
    ('terminated', 'Terminated'),
    ('expired', 'Expired'),
    ('cancelled', 'Cancelled'),
]

# Notifications & Reminders Automation (2026-09-22): escalating lease-expiry
# reminder windows, checked most-urgent-first. 30 matches BD-003's existing
# "Expiring Soon" definition (dashboard's edara_dashboard.EXPIRING_SOON_WINDOW_DAYS) -
# not duplicated as an independent number. 7 is one additional, more urgent
# escalation, per the ticket's own suggested example; no third window is added
# without a business need for one.
EXPIRY_REMINDER_WINDOWS_DAYS = (30, 7)

# States in which a lease holds its unit (overlap protection); only 'active' occupies it today.
LIVE_STATES = ['scheduled', 'active']


class EdaraLeaseContract(models.Model):
    _name = 'edara.lease.contract'
    _description = 'EDARA Lease Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, id desc'

    name = fields.Char(required=True, copy=False, readonly=True, default=lambda self: _('New'))
    company_id = fields.Many2one(related='unit_id.company_id', string='Company', store=True, index=True)
    branch_id = fields.Many2one(related='unit_id.branch_id', string='Branch', store=True, index=True)
    property_id = fields.Many2one(related='unit_id.property_id', string='Property', store=True, index=True)
    building_id = fields.Many2one(related='unit_id.building_id', string='Building', store=True, index=True)
    unit_id = fields.Many2one('edara.unit', string='Unit', required=True, index=True, tracking=True)
    tenant_id = fields.Many2one('res.partner', string='Tenant', required=True, index=True, tracking=True)

    start_date = fields.Date(required=True, tracking=True, help="First occupied day.")
    end_date = fields.Date(required=True, tracking=True, help=(
        "LAST occupied day (inclusive): 01/01 - 31/12 means the tenant is in the unit through "
        "31/12. Interval logic uses the exclusive boundary end_date + 1 day, see _term_boundary()."))
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                   default=lambda self: self.env.company.currency_id)
    rent_amount = fields.Monetary(string='Rent', required=True, currency_field='currency_id', tracking=True)
    billing_frequency = fields.Selection(BILLING_FREQUENCIES, required=True, default='monthly', tracking=True)
    payment_day = fields.Integer(string='Payment Day', compute='_compute_payment_day', store=True, readonly=True,
                                  help="The billing anchor day, always derived from the Start Date's day of "
                                       "month - not independently editable. It stays fixed even when a "
                                       "particular month is too short to contain it (e.g. day 31 in "
                                       "February): that month's boundary is clamped to its last day, but "
                                       "the anchor itself is restored the moment a later month is long "
                                       "enough again (see _period_boundary()).")
    monthly_equivalent_rent = fields.Monetary(
        compute='_compute_monthly_equivalent_rent', store=True, currency_field='currency_id',
        help="rent_amount normalized to a monthly rate - the exact same "
             "rent_amount/PERIOD_MONTHS formula _generate_schedule_lines() already "
             "uses internally, now exposed as a field for the Rent Roll report "
             "(Reporting & Management Intelligence, 2026-09-22) rather than a second "
             "calculation. Stored since it's a cheap, rarely-changing derivation used "
             "as a report column.")
    unit_occupancy_status = fields.Selection(
        related='unit_id.occupancy_status', string='Unit Occupancy', store=False,
        help="Display-only passthrough of the unit's own occupancy_status, for the "
             "Rent Roll report - never independently derived (BD-001's unit-level "
             "logic remains the single source of truth).")

    @api.depends('start_date')
    def _compute_payment_day(self):
        for contract in self:
            contract.payment_day = contract.start_date.day if contract.start_date else False

    @api.depends('rent_amount', 'billing_frequency')
    def _compute_monthly_equivalent_rent(self):
        for contract in self:
            contract.monthly_equivalent_rent = (
                contract.rent_amount / PERIOD_MONTHS[contract.billing_frequency] if contract.billing_frequency
                else 0.0)

    deposit_required = fields.Boolean(default=True)
    deposit_amount = fields.Monetary(currency_field='currency_id')

    state = fields.Selection(STATES, required=True, default='draft', tracking=True, copy=False, index=True)
    termination_date = fields.Date(copy=False, tracking=True)
    termination_reason = fields.Text(copy=False)

    predecessor_contract_id = fields.Many2one('edara.lease.contract', string='Renewed From',
                                               readonly=True, copy=False)
    successor_contract_id = fields.Many2one('edara.lease.contract', string='Renewed Into',
                                             readonly=True, copy=False)

    last_expiry_reminder_days = fields.Integer(
        copy=False, default=0, help=(
            "Which escalation window (see EXPIRY_REMINDER_WINDOWS_DAYS) the most recent "
            "lease-expiry reminder was sent for - 0 means none sent yet. Lets "
            "_cron_send_expiry_reminders() stay idempotent per window without depending on "
            "mail.activity state, which a user may legitimately mark done before the next, "
            "more urgent window is reached."))

    notes = fields.Text()

    schedule_line_ids = fields.One2many('edara.payment.schedule.line', 'contract_id',
                                         string='Payment Schedule')
    schedule_line_count = fields.Integer(compute='_compute_schedule_line_count')

    renewal_request_ids = fields.One2many('edara.renewal.request', 'contract_id', string='Renewal Requests')
    renewal_request_count = fields.Integer(compute='_compute_renewal_request_count')

    @api.depends('schedule_line_ids')
    def _compute_schedule_line_count(self):
        data = self.env['edara.payment.schedule.line']._read_group(
            [('contract_id', 'in', self.ids)], ['contract_id'], ['__count'])
        counts = {contract.id: count for contract, count in data}
        for contract in self:
            contract.schedule_line_count = counts.get(contract.id, 0)

    def action_view_schedule_lines(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'property_managment.action_edara_payment_schedule_line')
        action['domain'] = [('contract_id', '=', self.id)]
        action['context'] = {'default_contract_id': self.id}
        return action

    @api.depends('renewal_request_ids')
    def _compute_renewal_request_count(self):
        data = self.env['edara.renewal.request']._read_group(
            [('contract_id', 'in', self.ids)], ['contract_id'], ['__count'])
        counts = {contract.id: count for contract, count in data}
        for contract in self:
            contract.renewal_request_count = counts.get(contract.id, 0)

    def action_view_renewal_requests(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_renewal_request')
        action['domain'] = [('contract_id', '=', self.id)]
        action['context'] = {'default_contract_id': self.id}
        return action

    def action_view_deposit(self):
        self.ensure_one()
        deposit = self.env['edara.deposit'].search([('contract_id', '=', self.id)], limit=1)
        if not deposit:
            deposit = self.env['edara.deposit'].create({
                'contract_id': self.id,
                'amount': self.deposit_amount,
            })
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_deposit')
        action['res_id'] = deposit.id
        action['view_mode'] = 'form'
        action['views'] = [(False, 'form')]
        return action

    def _period_boundary(self, months_elapsed):
        """The billing anchor (payment_day = start_date.day) is immutable:
        every period boundary must be calculated fresh from the original
        start_date, never by chaining from a previously computed boundary.
        Chaining is structurally unsafe - relativedelta's own day-of-month
        clamping (e.g. 31/01 -> 28/02) would otherwise compound across
        iterations and permanently lose the anchor day (28/02 + 1mo =
        28/03, not the correct 31/03). Computing fresh from start_date each
        time makes the anchor self-heal the moment a later month is long
        enough to contain it again."""
        self.ensure_one()
        return self.start_date + relativedelta(months=months_elapsed)

    def _term_boundary(self):
        """The exclusive end of the term: end_date is the last occupied day, so the half-open
        interval every subsystem uses is [start_date, _term_boundary()). The only place the
        +1 day lives (Phase 10.1, RULE-02)."""
        self.ensure_one()
        return proration.term_boundary(self.end_date)

    def _generate_schedule_lines(self):
        """Create the schedule lines for the part of [start_date, _term_boundary()) that no
        line covers yet - generate by coverage, never by regeneration (RULE-11/13).

        Kept as they are: every invoiced line, and every uninvoiced line that covers a whole
        billing period. Dropped and recomputed: uninvoiced prorated lines (an unbilled partial
        tail is re-cut inside the new range on extension). Generation starts at the end of the
        last kept line, so a period that is already invoiced can never be created again, and an
        invoiced partial tail is completed by a stub line up to the next anchor boundary.

        One line per billing period at the contract's frequency (1/3/12 months): a whole period
        bills exactly rent_amount; a part of a period bills round(F(b)) - round(F(a)) - see
        edara_proration (Period-Relative Actual/Actual, cumulative rounding). Only the exact
        rent_amount / months is used; the stored, rounded monthly_equivalent_rent never is."""
        self.ensure_one()
        self.schedule_line_ids.filtered(lambda l: not l.invoice_id and l.is_prorated).unlink()
        covered_to = max([d for d in self.schedule_line_ids.mapped('period_end') if d] or [self.start_date])
        rent = Fraction(str(self.rent_amount))
        rounding = Fraction(str(self.currency_id.rounding))
        sequence = max(self.schedule_line_ids.mapped('sequence') or [0]) + 10
        vals_list = []
        for period_start, period_end, is_prorated, amount in proration.piece_lines(
                self.start_date, PERIOD_MONTHS[self.billing_frequency], rent, rounding,
                covered_to, self._term_boundary()):
            occupied_days = (period_end - period_start).days
            vals_list.append((0, 0, {
                'due_date': period_start,
                'period_start': period_start,
                'period_end': period_end,
                'occupied_days': occupied_days,
                'is_prorated': is_prorated,
                'amount': self.currency_id.round(amount),
                'sequence': sequence,
                'description': self._schedule_line_description(period_start, period_end, is_prorated),
            }))
            sequence += 10
        self.schedule_line_ids = vals_list

    def _schedule_line_description(self, period_start, period_end, is_prorated):
        """Invoice-line text: business-facing (last occupied day, not the exclusive boundary)."""
        last_day = period_end - relativedelta(days=1)
        text = _("Rent %(start)s - %(end)s", start=period_start, end=last_day)
        if is_prorated:
            text += _(" (prorated, %(days)s days)", days=(period_end - period_start).days)
        return text

    def unlink(self):
        if any(contract.state != 'draft' for contract in self):
            raise UserError(_("Only draft contracts can be deleted. Terminate an active contract instead."))
        return super().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('edara.lease.contract') or _('New')
        return super().create(vals_list)

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for contract in self:
            if contract.end_date < contract.start_date:
                raise ValidationError(_("The end date cannot be before the start date."))

    @api.constrains('rent_amount')
    def _check_rent_amount(self):
        for contract in self:
            if contract.rent_amount <= 0:
                raise ValidationError(_("Rent must be a positive amount."))

    @api.constrains('deposit_required', 'deposit_amount')
    def _check_deposit_amount(self):
        for contract in self:
            if contract.deposit_required and contract.deposit_amount <= 0:
                raise ValidationError(_(
                    "A positive Deposit Amount is required when Deposit Required is set."))

    @api.constrains('unit_id', 'start_date', 'end_date', 'state')
    def _check_no_overlap(self):
        """end_date is the last occupied day (inclusive), so two leases on one unit overlap iff
        s1 <= e2 AND s2 <= e1; a successor may start on the day after the predecessor's end_date.
        Scheduled leases count: a signed, not-yet-started lease protects the unit from
        double-leasing."""
        for contract in self:
            if contract.state not in LIVE_STATES:
                continue
            overlapping = self.search([
                ('id', '!=', contract.id),
                ('unit_id', '=', contract.unit_id.id),
                ('state', 'in', LIVE_STATES),
                ('start_date', '<=', contract.end_date),
                ('end_date', '>=', contract.start_date),
            ])
            if overlapping:
                raise ValidationError(_(
                    "%(unit)s already has an active lease (%(other)s) overlapping these dates.",
                    unit=contract.unit_id.display_name, other=overlapping[0].name,
                ))

    def write(self, vals):
        """The end date of a confirmed lease only ever moves LATER (an extension); shortening is
        Terminate. A later end date creates the missing schedule lines and nothing else."""
        if 'end_date' not in vals:
            return super().write(vals)
        new_end = fields.Date.to_date(vals['end_date'])
        live = self.filtered(lambda c: c.state in LIVE_STATES)
        if any(new_end < c.end_date for c in live):
            raise UserError(_("A confirmed lease's end date can only be moved later. To end it "
                              "earlier, terminate the contract."))
        res = super().write(vals)
        for contract in live:
            contract._generate_schedule_lines()
        return res

    def action_activate(self):
        """Confirm a draft lease: preconditions, lifecycle state and the payment schedule.
        A lease starting in the future becomes 'scheduled' (unit reserved, no invoice can be
        raised); one that has started is 'active'. The schedule is created here, independent
        of activation (see _activate_scheduled()) and of invoicing."""
        # Phase 7: `state` is a system-managed field (edara.system.field.guard) - it is
        # only ever changed here, after the caller's own write access is verified,
        # through a scoped sudo() write (a client cannot forge env.su via RPC).
        self.check_access('write')
        today = fields.Date.context_today(self)
        for contract in self:
            if contract.state != 'draft':
                raise UserError(_("Only draft contracts can be activated."))
            contract._check_can_start()
            contract.sudo().state = 'scheduled' if contract.start_date > today else 'active'
            # Date-aware occupancy per BD-001: the unit follows what its live leases imply -
            # 'rented' once a lease covers today, 'reserved' while only a scheduled one exists.
            contract.unit_id.occupancy_status = contract.unit_id._lease_occupancy_state()
            contract._generate_schedule_lines()

    def _check_can_start(self):
        self.ensure_one()
        if self.unit_id.occupancy_status == 'sold':
            raise UserError(_("%(unit)s has been sold and cannot be leased.", unit=self.unit_id.display_name))
        if self.unit_id.operational_status == 'under_maintenance':
            raise UserError(_(
                "%(unit)s is under maintenance and cannot be leased right now.",
                unit=self.unit_id.display_name,
            ))
        if self.deposit_required and self.deposit_amount <= 0:
            raise UserError(_("Configure a positive Deposit Amount before activating this contract."))

    def _activate_scheduled(self):
        """scheduled -> active on/after start_date. Lifecycle only: the schedule already exists
        and is left untouched. A lease that cannot start (unit sold / under maintenance, or an
        overlap with another live lease) stays scheduled and gets one to-do for the branch
        manager instead of failing the whole daily job."""
        started = self.browse()
        for contract in self:
            try:
                with self.env.cr.savepoint():
                    contract._check_can_start()
                    contract.sudo().state = 'active'
            except UserError as error:
                contract.invalidate_recordset(['state'])
                summary = _("Scheduled lease could not start")
                if not contract.activity_ids.filtered(lambda a: a.summary == summary):
                    contract.activity_schedule(
                        summary=summary, note=str(error),
                        user_id=contract._get_reminder_responsible_user().id,
                        date_deadline=fields.Date.context_today(contract))
                continue
            started |= contract
        return started

    def _unlink_future_uninvoiced_schedule_lines(self):
        """Drop not-yet-due, uninvoiced schedule lines only - called by both
        action_terminate() and _cron_expire_contracts() so the two paths can
        never diverge (see MAT-FIND-007's precedent for this requirement).
        Uninvoiced lines already due (computed state 'overdue', per
        edara.payment.schedule.line._compute_state()) are deliberately left
        alone - they represent real unpaid rent obligations, not cancelled
        future periods, and must survive contract termination/expiry to
        preserve financial/audit history (MAT-FIND-006). Already-invoiced
        lines are never touched by this filter regardless of due date."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        self.schedule_line_ids.filtered(
            lambda l: not l.invoice_id and l.due_date >= today
        ).unlink()

    def action_terminate(self, reason=None):
        self.check_access('write')
        for contract in self:
            if contract.state != 'active':
                raise UserError(_("Only active contracts can be terminated."))
            contract.sudo().write({
                'state': 'terminated',
                'termination_date': fields.Date.context_today(contract),
                'termination_reason': reason or contract.termination_reason,
            })
            # A scheduled renewal for a tenant who has left must not start (OD-B9).
            successor = contract.successor_contract_id
            if successor.state == 'scheduled':
                successor.action_cancel()
                contract.message_post(body=_("Scheduled renewal %(name)s was cancelled.", name=successor.name))
            # Only frees the unit if no OTHER live contract remains on it (MAT-020).
            contract.unit_id._sync_occupancy_from_contracts()
            # Defense-in-depth #1: drop not-yet-due, uninvoiced future obligations now.
            # Defense #2 is the invoicing cron re-checking state == 'active'.
            contract._unlink_future_uninvoiced_schedule_lines()

    def action_cancel(self):
        """Withdraw a scheduled lease before it starts: no invoice can exist yet, so the schedule
        is removed and the reservation released. Nothing posted is touched."""
        self.check_access('write')
        for contract in self:
            if contract.state != 'scheduled':
                raise UserError(_("Only a scheduled contract can be cancelled."))
            contract.schedule_line_ids.filtered(lambda l: not l.invoice_id).unlink()
            contract.sudo().state = 'cancelled'
            predecessor = contract.predecessor_contract_id
            if predecessor.successor_contract_id == contract:
                predecessor.sudo().successor_contract_id = False
            contract.unit_id._sync_occupancy_from_contracts()

    def action_renew(self, new_start_date, new_end_date, new_rent_amount):
        """Owner-initiated renewal: create the successor and confirm it (scheduled while its
        start is in the future). The current contract is untouched - it keeps occupying the unit,
        stays active and keeps billing until its own term ends; only the daily job then moves it
        to 'renewed' (_cron_expire_contracts). Tenant-requested renewals go through
        edara.renewal.request, which calls this same method after owner approval."""
        self.ensure_one()
        self.check_access('write')
        if self.state != 'active':
            raise UserError(_("Only an active contract can be renewed."))
        if self.successor_contract_id.state in LIVE_STATES:
            raise UserError(_("%(name)s already has a renewal (%(succ)s).",
                              name=self.name, succ=self.successor_contract_id.name))
        if new_start_date < self._term_boundary():
            raise UserError(_(
                "A renewal starts when the current term ends (%(date)s at the earliest); to change "
                "terms mid-term, end the current contract first.", date=self._term_boundary()))
        new_contract = self.create({
            'unit_id': self.unit_id.id,
            'tenant_id': self.tenant_id.id,
            'start_date': new_start_date,
            'end_date': new_end_date,
            'currency_id': self.currency_id.id,
            'rent_amount': new_rent_amount,
            'billing_frequency': self.billing_frequency,
            'deposit_required': self.deposit_required,
            'deposit_amount': self.deposit_amount,
            'predecessor_contract_id': self.id,
        })
        self.sudo().successor_contract_id = new_contract.id
        new_contract.action_activate()
        return new_contract

    @api.model
    def _cron_expire_contracts(self):
        """Daily lifecycle job, one run, in this order:
        1. scheduled leases whose start_date has arrived become active;
        2. active leases whose term is over (end_date < today: end_date is the last occupied
           day) become 'renewed' if a live successor exists, else 'expired';
        3. occupancy of every touched unit is recomputed.
        The successor starts at the predecessor's boundary, so both are briefly 'active' with
        disjoint dates (never an overlap). Idempotent: it only picks contracts still in the
        source state. Returns the number of contracts closed in step 2."""
        today = fields.Date.context_today(self)
        scheduled = self.search([('state', '=', 'scheduled'), ('start_date', '<=', today)])
        started = scheduled._activate_scheduled()
        finished = self.search([('state', '=', 'active'), ('end_date', '<', today)])
        for contract in finished:
            renewed = contract.successor_contract_id.state in ('scheduled', 'active')
            contract.sudo().state = 'renewed' if renewed else 'expired'
            contract._unlink_future_uninvoiced_schedule_lines()
        (started | finished).unit_id._sync_occupancy_from_contracts()
        return len(finished)

    def _get_reminder_responsible_user(self):
        """Deterministic responsible user for an operational reminder: the
        assigned Branch Manager, or - only when none is configured - the same
        default-Administrator fallback this module already grants
        base.user_admin on install (see group_edara_administrator's user_ids
        in security/edara_security.xml). Not a new role, just reusing that
        existing precedent instead of inventing one."""
        self.ensure_one()
        return self.branch_id.manager_id or self.env.ref('base.user_admin')

    @api.model
    def _cron_send_expiry_reminders(self):
        """Notifications & Reminders Automation (2026-09-22). Escalating,
        idempotent per EXPIRY_REMINDER_WINDOWS_DAYS window - see
        last_expiry_reminder_days. Internal reminder is a mail.activity
        assigned to the Branch Manager; the tenant is separately informed via
        a chatter message addressed to them (native mail notification, no new
        template infrastructure). Safe to run repeatedly the same day, safe to
        run after a manual trigger already handled the same window."""
        today = fields.Date.context_today(self)
        widest_window = max(EXPIRY_REMINDER_WINDOWS_DAYS)
        activity_type = self.env.ref('property_managment.mail_activity_type_edara_lease_expiry')
        contracts = self.search([
            ('state', '=', 'active'),
            ('end_date', '>=', today),
            ('end_date', '<=', today + relativedelta(days=widest_window)),
        ])
        sent = 0
        for contract in contracts:
            days_left = (contract.end_date - today).days
            window = min((w for w in EXPIRY_REMINDER_WINDOWS_DAYS if days_left <= w), default=None)
            if window is None:
                continue
            if contract.last_expiry_reminder_days and contract.last_expiry_reminder_days <= window:
                continue
            user = contract._get_reminder_responsible_user()
            contract.activity_schedule(
                activity_type_id=activity_type.id,
                summary=_("Lease expiring in %(days)d day(s)", days=days_left),
                note=_(
                    "%(contract)s for %(tenant)s at %(unit)s expires on %(date)s. Review renewal "
                    "or termination.",
                    contract=contract.name, tenant=contract.tenant_id.display_name,
                    unit=contract.unit_id.display_name, date=contract.end_date,
                ),
                user_id=user.id,
                date_deadline=today,
            )
            contract.last_expiry_reminder_days = window
            if contract.tenant_id:
                contract.message_post(
                    body=_(
                        "Your lease %(contract)s expires on %(date)s.",
                        contract=contract.name, date=contract.end_date,
                    ),
                    partner_ids=contract.tenant_id.ids,
                )
            sent += 1
        return sent
