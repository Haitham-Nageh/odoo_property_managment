from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EdaraOwnership(models.Model):
    _name = 'edara.ownership'
    _description = 'EDARA Property Ownership'
    _inherit = ['mail.thread']
    _order = 'property_id, date_from desc'

    property_id = fields.Many2one('edara.property', string='Property', required=True, index=True, tracking=True)
    branch_id = fields.Many2one(related='property_id.branch_id', string='Branch', store=True, index=True)
    company_id = fields.Many2one(related='property_id.company_id', string='Company', store=True, index=True)
    owner_id = fields.Many2one('res.partner', string='Owner', required=True, index=True, tracking=True)
    ownership_percentage = fields.Float(string='Ownership %', required=True, tracking=True)
    date_from = fields.Date(string='From', required=True, default=fields.Date.context_today, tracking=True)
    date_to = fields.Date(string='To', tracking=True,
                           help="Leave empty for an open-ended (current) ownership period.")
    active = fields.Boolean(default=True)

    @api.constrains('ownership_percentage')
    def _check_percentage_range(self):
        for record in self:
            if not (0 < record.ownership_percentage <= 100):
                raise ValidationError(self.env._("Ownership percentage must be between 0 and 100."))

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for record in self:
            if record.date_to and record.date_to < record.date_from:
                raise ValidationError(self.env._("The ownership end date cannot be before its start date."))

    @api.constrains('property_id', 'owner_id', 'ownership_percentage', 'date_from', 'date_to', 'active')
    def _check_total_ownership(self):
        for prop in self.mapped('property_id'):
            records = self.env['edara.ownership'].search([('property_id', '=', prop.id), ('active', '=', True)])
            if not records:
                continue
            # Sweep-line: the maximum concurrent total can only occur at a
            # record's own start or end boundary, so checking totals at those
            # points is sufficient to catch any overlap that exceeds 100%.
            boundaries = set(records.mapped('date_from'))
            boundaries.update(d for d in records.mapped('date_to') if d)
            for point in boundaries:
                total = sum(
                    r.ownership_percentage for r in records
                    if r.date_from <= point and (not r.date_to or r.date_to >= point)
                )
                if total > 100.0 + 1e-6:
                    raise ValidationError(self.env._(
                        "Total ownership of %(property)s would exceed 100%% on %(date)s.",
                        property=prop.display_name, date=point,
                    ))
