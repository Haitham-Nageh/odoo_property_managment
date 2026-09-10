from odoo import _, api, fields, models
from odoo.exceptions import UserError

ALLOCATION_METHODS = [
    ('equal', 'Equal'),
    ('proportional', 'Proportional by Area'),
    ('per_sqm', 'Per Square Meter'),
    ('fixed_per_unit', 'Fixed Amount per Unit'),
]

STATES = [
    ('draft', 'Draft'),
    ('allocated', 'Allocated'),
    ('invoiced', 'Invoiced'),
]


class EdaraServiceCharge(models.Model):
    _name = 'edara.service.charge'
    _description = 'EDARA Service Charge'
    _order = 'date desc, id desc'

    name = fields.Char(required=True, copy=False, default=lambda self: _('New'))
    building_id = fields.Many2one('edara.building', string='Building', required=True, index=True)
    property_id = fields.Many2one(related='building_id.property_id', store=True, index=True)
    branch_id = fields.Many2one(related='building_id.branch_id', store=True, index=True)
    company_id = fields.Many2one(related='building_id.company_id', store=True, index=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    date = fields.Date(required=True, default=fields.Date.context_today)
    description = fields.Char()

    allocation_method = fields.Selection(ALLOCATION_METHODS, required=True, default='equal')
    total_amount = fields.Monetary(
        string='Total Amount', currency_field='currency_id',
        help="Grand total to allocate. Used by the Equal and Proportional by Area methods.")
    rate_per_sqm = fields.Monetary(
        string='Rate per m²', currency_field='currency_id',
        help="Amount charged per square meter of unit area. Used by the Per Square Meter method.")
    fixed_amount_per_unit = fields.Monetary(
        string='Fixed Amount per Unit', currency_field='currency_id',
        help="Flat amount charged to every occupied unit. Used by the Fixed Amount per Unit method.")

    line_ids = fields.One2many('edara.service.charge.line', 'charge_id', string='Allocation')
    state = fields.Selection(STATES, compute='_compute_state', store=True)

    @api.depends('line_ids.invoice_id')
    def _compute_state(self):
        for charge in self:
            if not charge.line_ids:
                charge.state = 'draft'
            elif all(line.invoice_id for line in charge.line_ids):
                charge.state = 'invoiced'
            else:
                charge.state = 'allocated'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('edara.service.charge') or _('New')
        return super().create(vals_list)

    def action_generate_allocation(self):
        self.ensure_one()
        self.line_ids.filtered(lambda l: not l.invoice_id).unlink()
        units = self.building_id.unit_ids.filtered('active')
        if not units:
            raise UserError(_("This building has no units to allocate a service charge to."))
        amounts = self._compute_allocation(units)
        vals_list = []
        for unit, amount in amounts.items():
            tenant = unit.lease_contract_ids.filtered(lambda c: c.state == 'active')[:1].tenant_id
            if not tenant:
                continue
            vals_list.append((0, 0, {'unit_id': unit.id, 'tenant_id': tenant.id, 'amount': amount}))
        if not vals_list:
            raise UserError(_("None of this building's units currently have an active tenant to charge."))
        self.line_ids = vals_list

    def _compute_allocation(self, units):
        self.ensure_one()
        if self.allocation_method == 'equal':
            if self.total_amount <= 0:
                raise UserError(_("Please set the total amount to allocate."))
            share = self.total_amount / len(units)
            return {unit: share for unit in units}
        if self.allocation_method == 'proportional':
            if self.total_amount <= 0:
                raise UserError(_("Please set the total amount to allocate."))
            total_area = sum(units.mapped('area'))
            if total_area <= 0:
                raise UserError(_(
                    "Set an area (sqm) on this building's units before using proportional allocation."))
            return {unit: self.total_amount * (unit.area / total_area) for unit in units}
        if self.allocation_method == 'per_sqm':
            if self.rate_per_sqm <= 0:
                raise UserError(_("Please set the rate per square meter."))
            return {unit: self.rate_per_sqm * unit.area for unit in units}
        # fixed_per_unit
        if self.fixed_amount_per_unit <= 0:
            raise UserError(_("Please set the fixed amount per unit."))
        return {unit: self.fixed_amount_per_unit for unit in units}

    def action_invoice_lines(self):
        for charge in self:
            for line in charge.line_ids.filtered(lambda l: not l.invoice_id):
                line._create_invoice()
