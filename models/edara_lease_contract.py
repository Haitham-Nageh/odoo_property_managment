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
    payment_day = fields.Integer(string='Payment Day of Month', default=1,
                                  help="Day of the month rent is due (1-28, to stay valid in every month).")

    deposit_required = fields.Boolean(default=True)
    deposit_amount = fields.Monetary(currency_field='currency_id')

    state = fields.Selection(STATES, required=True, default='draft', tracking=True, copy=False)
    termination_date = fields.Date(copy=False, tracking=True)
    termination_reason = fields.Text(copy=False)

    predecessor_contract_id = fields.Many2one('edara.lease.contract', string='Renewed From',
                                               readonly=True, copy=False)
    successor_contract_id = fields.Many2one('edara.lease.contract', string='Renewed Into',
                                             readonly=True, copy=False)

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

    def _generate_schedule_lines(self):
        """Generate one schedule line per billing period from start_date to
        end_date, due on payment_day of each period's month. Only touches
        uninvoiced lines - already-invoiced history is never regenerated."""
        self.ensure_one()
        self.schedule_line_ids.filtered(lambda l: not l.invoice_id).unlink()
        months = PERIOD_MONTHS[self.billing_frequency]
        # Not named "cursor": odoo.tools.translate._get_cr() treats any local
        # variable literally named "cursor" as a DB cursor for _()'s frame
        # inspection, which would misfire here since this is a plain date.
        due_date = self.start_date.replace(day=self.payment_day)
        if due_date < self.start_date:
            due_date += relativedelta(months=months)
        vals_list = []
        sequence = 10
        while due_date <= self.end_date:
            vals_list.append((0, 0, {
                'due_date': due_date,
                'amount': self.rent_amount,
                'sequence': sequence,
                'description': _("Rent due %(date)s", date=due_date),
            }))
            sequence += 10
            due_date += relativedelta(months=months)
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

    @api.constrains('payment_day')
    def _check_payment_day(self):
        for contract in self:
            if not (1 <= contract.payment_day <= 28):
                raise ValidationError(_("Payment day must be between 1 and 28."))

    @api.constrains('unit_id', 'start_date', 'end_date', 'state')
    def _check_no_overlap(self):
        for contract in self:
            if contract.state != 'active':
                continue
            overlapping = self.search([
                ('id', '!=', contract.id),
                ('unit_id', '=', contract.unit_id.id),
                ('state', '=', 'active'),
                ('start_date', '<=', contract.end_date),
                ('end_date', '>=', contract.start_date),
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
            contract.state = 'active'
            contract.unit_id.occupancy_status = 'rented'
            contract._generate_schedule_lines()

    def action_terminate(self, reason=None):
        for contract in self:
            if contract.state != 'active':
                raise UserError(_("Only active contracts can be terminated."))
            contract.write({
                'state': 'terminated',
                'termination_date': fields.Date.context_today(contract),
                'termination_reason': reason or contract.termination_reason,
            })
            contract.unit_id.occupancy_status = 'available'
            # Defense-in-depth #1: drop not-yet-invoiced future obligations now.
            # Defense #2 is the invoicing cron re-checking state == 'active'.
            contract.schedule_line_ids.filtered(
                lambda l: not l.invoice_id and l.due_date > contract.termination_date
            ).unlink()

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
            'payment_day': self.payment_day,
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
            contract.unit_id.occupancy_status = 'available'
            contract.schedule_line_ids.filtered(lambda l: not l.invoice_id).unlink()
