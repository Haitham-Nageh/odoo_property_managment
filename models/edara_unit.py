from odoo import api, fields, models
from odoo.exceptions import ValidationError

UNIT_TYPES = [
    ('apartment', 'Apartment'),
    ('office', 'Office'),
    ('shop', 'Shop'),
    ('warehouse', 'Warehouse'),
    ('villa', 'Villa'),
    ('parking', 'Parking'),
    ('commercial', 'Commercial Space'),
    ('other', 'Other'),
]

OCCUPANCY_STATUSES = [
    ('available', 'Available'),
    ('reserved', 'Reserved'),
    ('rented', 'Rented'),
    ('owner_occupied', 'Owner Occupied'),
    ('sold', 'Sold'),
]

OPERATIONAL_STATUSES = [
    ('normal', 'Normal'),
    ('under_maintenance', 'Under Maintenance'),
]


class EdaraUnit(models.Model):
    _name = 'edara.unit'
    _description = 'EDARA Unit'
    _inherit = ['mail.thread']
    _order = 'building_id, floor, name'

    name = fields.Char(required=True, tracking=True, help="e.g. A-101, Shop-01.")
    code = fields.Char(required=True, tracking=True)
    building_id = fields.Many2one('edara.building', string='Building', required=True, index=True, tracking=True)
    property_id = fields.Many2one(related='building_id.property_id', string='Property', store=True, index=True)
    branch_id = fields.Many2one(related='building_id.branch_id', string='Branch', store=True, index=True)
    company_id = fields.Many2one(related='building_id.company_id', string='Company', store=True, index=True)
    active = fields.Boolean(default=True)

    floor = fields.Char()
    unit_number = fields.Char()
    unit_type = fields.Selection(UNIT_TYPES, string='Type', required=True, default='apartment', tracking=True)
    area = fields.Float(string='Area (sqm)')
    bedrooms = fields.Integer()
    bathrooms = fields.Integer()

    rent_amount_default = fields.Monetary(string='Default Rent', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: self.env.company.currency_id)

    occupancy_status = fields.Selection(OCCUPANCY_STATUSES, string='Occupancy', required=True,
                                         default='available', tracking=True,
                                         help="'Rented' can only be set through an active lease contract "
                                              "(see the Contracts smart button) - it is not freely editable.")
    operational_status = fields.Selection(OPERATIONAL_STATUSES, string='Operational State', required=True,
                                           default='normal', tracking=True)

    lease_contract_ids = fields.One2many('edara.lease.contract', 'unit_id', string='Lease Contracts')
    contract_count = fields.Integer(compute='_compute_contract_count')

    maintenance_request_ids = fields.One2many('edara.maintenance.request', 'unit_id', string='Maintenance Requests')
    maintenance_request_count = fields.Integer(compute='_compute_maintenance_request_count')

    _code_building_uniq = models.Constraint(
        'unique(building_id, code)',
        'Unit code must be unique within a building.',
    )

    @api.constrains('occupancy_status', 'operational_status')
    def _check_status_consistency(self):
        for unit in self:
            if unit.operational_status == 'under_maintenance' and unit.occupancy_status == 'available':
                raise ValidationError(self.env._(
                    "%(unit)s cannot be Available while it is Under Maintenance.",
                    unit=unit.display_name,
                ))

    @api.constrains('occupancy_status')
    def _check_occupancy_status_derivation(self):
        for unit in self:
            if unit.occupancy_status == 'rented' and not self.env['edara.lease.contract'].search_count([
                ('unit_id', '=', unit.id), ('state', '=', 'active'),
            ]):
                raise ValidationError(self.env._(
                    "%(unit)s can only be marked Rented through an active lease contract.",
                    unit=unit.display_name,
                ))

    @api.depends('lease_contract_ids')
    def _compute_contract_count(self):
        data = self.env['edara.lease.contract']._read_group(
            [('unit_id', 'in', self.ids)], ['unit_id'], ['__count'])
        counts = {unit.id: count for unit, count in data}
        for unit in self:
            unit.contract_count = counts.get(unit.id, 0)

    def action_view_contracts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_lease_contract')
        action['domain'] = [('unit_id', '=', self.id)]
        action['context'] = {'default_unit_id': self.id}
        return action

    @api.depends('maintenance_request_ids')
    def _compute_maintenance_request_count(self):
        data = self.env['edara.maintenance.request']._read_group(
            [('unit_id', 'in', self.ids)], ['unit_id'], ['__count'])
        counts = {unit.id: count for unit, count in data}
        for unit in self:
            unit.maintenance_request_count = counts.get(unit.id, 0)

    def action_view_maintenance_requests(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_maintenance_request')
        action['domain'] = [('unit_id', '=', self.id)]
        action['context'] = {'default_unit_id': self.id}
        return action
