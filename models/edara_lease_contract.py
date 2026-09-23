from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

BILLING_FREQUENCIES = [
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly'),
    ('yearly', 'Yearly'),
]

PERIOD_MONTHS = {'monthly': 1, 'quarterly': 3, 'yearly': 12}

STATES = [
    ('draft', 'Draft'),
    ('active', 'Active'),
    ('renewed', 'Renewed'),
    ('terminated', 'Terminated'),
    ('expired', 'Expired'),
]

# Notifications & Reminders Automation (2026-09-22): escalating lease-expiry
# reminder windows, checked most-urgent-first. 30 matches BD-003's existing
# "Expiring Soon" definition (dashboard's edara_dashboard.EXPIRING_SOON_WINDOW_DAYS) -
# not duplicated as an independent number. 7 is one additional, more urgent
# escalation, per the ticket's own suggested example; no third window is added
# without a business need for one.
EXPIRY_REMINDER_WINDOWS_DAYS = (30, 7)


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

    start_date = fields.Date(required=True, tracking=True)
    end_date = fields.Date(required=True, tracking=True)
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

    def _generate_schedule_lines(self):
        """Generate schedule lines covering [start_date, end_date) - end_date
        is the exclusive boundary of the lease term, never itself a billable
        period (MAT-FIND-005).

        Each schedule line represents exactly ONE billing period at the
        configured billing_frequency granularity (1/3/12 months for
        Monthly/Quarterly/Yearly) - a full quarterly or yearly period is
        always ONE line at the full configured rent_amount, never
        decomposed into monthly-equivalent lines (MAT-FIND-013). Once a
        full billing-frequency period no longer fits before end_date, the
        entire remainder becomes ONE prorated line (monthly-equivalent
        rate x occupied days / a standardized 30-day reference month) -
        it is not further split at monthly granularity either. This
        guarantees at least one line is always produced, even for a
        contract shorter than its own billing frequency (MAT-FIND-011):
        the loop's first period_start is always start_date itself, which
        is always < end_date.

        Only touches uninvoiced lines - already-invoiced history is never
        regenerated."""
        self.ensure_one()
        self.schedule_line_ids.filtered(lambda l: not l.invoice_id).unlink()
        frequency_months = PERIOD_MONTHS[self.billing_frequency]
        # Reuses the stored monthly_equivalent_rent field (Reporting & Management
        # Intelligence, 2026-09-22) rather than recomputing the same formula here -
        # one calculation, exposed both as a report column and used internally.
        monthly_equivalent = self.monthly_equivalent_rent

        vals_list = []
        sequence = 10
        months_elapsed = 0
        while True:
            period_start = self._period_boundary(months_elapsed)
            if period_start >= self.end_date:
                break
            next_boundary = self._period_boundary(months_elapsed + frequency_months)
            period_end = min(next_boundary, self.end_date)
            is_prorated = period_end != next_boundary
            amount = (monthly_equivalent * (period_end - period_start).days / 30
                      if is_prorated else self.rent_amount)
            months_elapsed += frequency_months
            vals_list.append((0, 0, {
                'due_date': period_start,
                'period_start': period_start,
                'period_end': period_end,
                'occupied_days': (period_end - period_start).days,
                'is_prorated': is_prorated,
                'amount': self.currency_id.round(amount),
                'sequence': sequence,
                'description': _("Rent %(start)s - %(end)s", start=period_start, end=period_end),
            }))
            sequence += 10
        self.schedule_line_ids = vals_list

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
            if contract.end_date <= contract.start_date:
                raise ValidationError(_("The end date must be after the start date."))

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
        """MAT-FIND-012 (2026-09-22): end_date is EXCLUSIVE for overlap
        purposes, consistent with _generate_schedule_lines()'s already-
        exclusive billing boundary (MAT-FIND-005) - a lease ending on a date
        no longer occupies that date, so a new lease may start exactly on
        the prior lease's end_date (adjacent leases are allowed). Two ranges
        [s1, e1) and [s2, e2) overlap iff s1 < e2 AND s2 < e1."""
        for contract in self:
            if contract.state != 'active':
                continue
            overlapping = self.search([
                ('id', '!=', contract.id),
                ('unit_id', '=', contract.unit_id.id),
                ('state', '=', 'active'),
                ('start_date', '<', contract.end_date),
                ('end_date', '>', contract.start_date),
            ])
            if overlapping:
                raise ValidationError(_(
                    "%(unit)s already has an active lease (%(other)s) overlapping these dates.",
                    unit=contract.unit_id.display_name, other=overlapping[0].name,
                ))

    def action_activate(self):
        for contract in self:
            if contract.state != 'draft':
                raise UserError(_("Only draft contracts can be activated."))
            if contract.unit_id.occupancy_status == 'sold':
                raise UserError(_("%(unit)s has been sold and cannot be leased.", unit=contract.unit_id.display_name))
            if contract.unit_id.operational_status == 'under_maintenance':
                raise UserError(_(
                    "%(unit)s is under maintenance and cannot be leased right now.",
                    unit=contract.unit_id.display_name,
                ))
            if contract.deposit_required and contract.deposit_amount <= 0:
                raise UserError(_(
                    "Configure a positive Deposit Amount before activating this contract."))
            contract.state = 'active'
            # Date-aware occupancy per BD-001 (2026-09-21, resolves MAT-FIND-010):
            # unconditionally forces the unit's occupancy to whatever its active
            # contracts now imply - 'reserved' for a future start_date, 'rented'
            # once start_date has arrived. Unlike unit._sync_occupancy_from_contracts()
            # (used by termination/expiry/the reserved-to-rented cron), this always
            # overwrites regardless of the unit's prior state, matching activation's
            # existing "always force it" semantics (only sold/under_maintenance are
            # blocked earlier, as preconditions above).
            contract.unit_id.occupancy_status = contract.unit_id._lease_occupancy_state()
            contract._generate_schedule_lines()

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
        for contract in self:
            if contract.state != 'active':
                raise UserError(_("Only active contracts can be terminated."))
            contract.write({
                'state': 'terminated',
                'termination_date': fields.Date.context_today(contract),
                'termination_reason': reason or contract.termination_reason,
            })
            # Only frees the unit if no OTHER currently-active contract remains on it
            # (e.g. terminating a future-dated contract must not clobber a still-active
            # current lease on the same unit - see EDARA_PROJECT_STATE.md, MAT-020).
            contract.unit_id._sync_occupancy_from_contracts()
            # Defense-in-depth #1: drop not-yet-due, uninvoiced future obligations now.
            # Defense #2 is the invoicing cron re-checking state == 'active'.
            contract._unlink_future_uninvoiced_schedule_lines()

    def action_renew(self, new_start_date, new_end_date, new_rent_amount):
        """Owner-initiated renewal: create the successor contract and activate it.
        Tenant-requested renewals go through edara.renewal.request (added once the
        tenant portal exists, Phase 9) which calls into this same method after
        owner approval - it never bypasses these checks.
        """
        self.ensure_one()
        if self.state != 'active':
            raise UserError(_("Only an active contract can be renewed."))
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
        self.write({'state': 'renewed', 'successor_contract_id': new_contract.id})
        new_contract.action_activate()
        return new_contract

    @api.model
    def _cron_expire_contracts(self):
        """Daily. A contract that was never renewed (action_renew already
        flips it to 'renewed' the moment renewal happens, so an active
        contract past its own end_date is by definition un-renewed) or
        terminated moves to EXPIRED - reachable state per spec §14, otherwise
        unreachable. Naturally idempotent: the state='active' filter excludes
        anything this method already expired on a prior run. No per-record
        commit/lock dance needed (unlike the invoicing cron) since this only
        flips plain fields in one transaction, with no partial-failure risk
        across records and no external financial posting."""
        today = fields.Date.context_today(self)
        contracts = self.search([('state', '=', 'active'), ('end_date', '<', today)])
        for contract in contracts:
            contract.state = 'expired'
            # Same sibling-aware recompute as action_terminate() - a future-dated
            # active contract on the same unit must keep it Rented (MAT-020).
            contract.unit_id._sync_occupancy_from_contracts()
            contract._unlink_future_uninvoiced_schedule_lines()
        return len(contracts)

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
