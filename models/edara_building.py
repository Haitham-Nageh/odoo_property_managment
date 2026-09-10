from odoo import api, fields, models


class EdaraBuilding(models.Model):
    _name = 'edara.building'
    _description = 'EDARA Building'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, tracking=True)
    property_id = fields.Many2one('edara.property', string='Property', required=True, index=True, tracking=True)
    branch_id = fields.Many2one(related='property_id.branch_id', string='Branch', store=True, index=True)
    company_id = fields.Many2one(related='property_id.company_id', string='Company', store=True, index=True)
    active = fields.Boolean(default=True)

    street = fields.Char()
    floor_count = fields.Integer(string='Floors')

    unit_ids = fields.One2many('edara.unit', 'building_id', string='Units')
    unit_count = fields.Integer(compute='_compute_unit_count')

    service_charge_ids = fields.One2many('edara.service.charge', 'building_id', string='Service Charges')
    service_charge_count = fields.Integer(compute='_compute_service_charge_count')

    contract_count = fields.Integer(compute='_compute_contract_count')
    maintenance_request_count = fields.Integer(compute='_compute_maintenance_request_count')

    _code_property_uniq = models.Constraint(
        'unique(property_id, code)',
        'Building code must be unique within a property.',
    )

    @api.depends('unit_ids')
    def _compute_unit_count(self):
        data = self.env['edara.unit']._read_group(
            [('building_id', 'in', self.ids)], ['building_id'], ['__count'])
        counts = {building.id: count for building, count in data}
        for building in self:
            building.unit_count = counts.get(building.id, 0)

    def action_view_units(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_unit')
        action['domain'] = [('building_id', '=', self.id)]
        action['context'] = {'default_building_id': self.id, 'default_property_id': self.property_id.id}
        return action

    @api.depends('service_charge_ids')
    def _compute_service_charge_count(self):
        data = self.env['edara.service.charge']._read_group(
            [('building_id', 'in', self.ids)], ['building_id'], ['__count'])
        counts = {building.id: count for building, count in data}
        for building in self:
            building.service_charge_count = counts.get(building.id, 0)

    def action_view_service_charges(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_service_charge')
        action['domain'] = [('building_id', '=', self.id)]
        action['context'] = {'default_building_id': self.id}
        return action

    @api.depends('unit_ids.lease_contract_ids')
    def _compute_contract_count(self):
        data = self.env['edara.lease.contract']._read_group(
            [('building_id', 'in', self.ids)], ['building_id'], ['__count'])
        counts = {building.id: count for building, count in data}
        for building in self:
            building.contract_count = counts.get(building.id, 0)

    def action_view_contracts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_lease_contract')
        action['domain'] = [('building_id', '=', self.id)]
        return action

    @api.depends('unit_ids.maintenance_request_ids')
    def _compute_maintenance_request_count(self):
        data = self.env['edara.maintenance.request']._read_group(
            [('building_id', 'in', self.ids)], ['building_id'], ['__count'])
        counts = {building.id: count for building, count in data}
        for building in self:
            building.maintenance_request_count = counts.get(building.id, 0)

    def action_view_maintenance_requests(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_maintenance_request')
        action['domain'] = [('building_id', '=', self.id)]
        return action
