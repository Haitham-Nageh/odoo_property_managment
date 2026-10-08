from odoo import fields, models


class EdaraUnitType(models.Model):
    _name = 'edara.unit.type'
    _description = 'EDARA Unit Type'
    _order = 'sequence, name'

    name = fields.Char(
        required=True,
        translate=True,
    )
    has_bedrooms_bathrooms = fields.Boolean(
        string='Has Bedrooms/Bathrooms',
        default=False,
    )
    active = fields.Boolean(
        default=True,
    )
    sequence = fields.Integer(
        default=10,
    )
