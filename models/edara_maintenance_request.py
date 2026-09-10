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
    state = fields.Selection(STATES, required=True, default='new', tracking=True, copy=False)

    requested_date = fields.Date(required=True, default=fields.Date.context_today)
    completed_date = fields.Date(readonly=True, copy=False)

    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    cost = fields.Monetary(currency_field='currency_id')
    vendor_id = fields.Many2one('res.partner', string='Vendor')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('edara.maintenance.request') or _('New')
        return super().create(vals_list)

    @api.constrains('cost')
    def _check_cost(self):
        for request in self:
            if request.cost < 0:
                raise ValidationError(_("Cost cannot be negative."))

    def action_assign(self, user_id):
        for request in self:
            if request.state not in ('new', 'assigned'):
                raise UserError(_("Only a new or already-assigned request can be reassigned."))
            request.write({'assigned_user_id': user_id, 'state': 'assigned'})

    def action_start(self):
        for request in self:
            if request.state not in ('new', 'assigned'):
                raise UserError(_("Only a new or assigned request can be started."))
            request.state = 'in_progress'

    def action_complete(self):
        for request in self:
            if request.state not in ('assigned', 'in_progress'):
                raise UserError(_("Only an assigned or in-progress request can be completed."))
            request.write({'state': 'done', 'completed_date': fields.Date.context_today(request)})

    def action_cancel(self):
        for request in self:
            if request.state in ('done', 'cancelled'):
                raise UserError(_("A completed or already-cancelled request cannot be cancelled."))
            request.state = 'cancelled'
