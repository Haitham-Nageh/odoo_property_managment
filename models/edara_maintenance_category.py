from odoo import fields, models


class EdaraMaintenanceCategory(models.Model):
    _name = 'edara.maintenance.category'
    _description = 'EDARA Maintenance Category'
    _order = 'sequence, name'

    name = fields.Char(
        required=True,
        translate=True,
    )
    active = fields.Boolean(
        default=True,
    )
    sequence = fields.Integer(
        default=10,
    )
