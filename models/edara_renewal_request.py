from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

STATES = [
    ('submitted', 'Submitted'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
]


class EdaraRenewalRequest(models.Model):
    _name = 'edara.renewal.request'
    _description = 'EDARA Lease Renewal Request'
    _inherit = ['mail.thread']
    _order = 'id desc'

    contract_id = fields.Many2one('edara.lease.contract', string='Contract', required=True,
                                   index=True, ondelete='restrict')
    tenant_id = fields.Many2one(related='contract_id.tenant_id', store=True, index=True)
    unit_id = fields.Many2one(related='contract_id.unit_id', store=True)
    branch_id = fields.Many2one(related='contract_id.branch_id', store=True, index=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)

    requested_start_date = fields.Date(required=True)
    requested_end_date = fields.Date(required=True)
    requested_rent_amount = fields.Monetary(required=True, currency_field='currency_id')
    note = fields.Text(string='Tenant Message')

    state = fields.Selection(STATES, required=True, default='submitted', tracking=True, copy=False)
    decision_note = fields.Text(string='Decision Note', copy=False)
    new_contract_id = fields.Many2one('edara.lease.contract', string='New Contract', readonly=True, copy=False)

    @api.constrains('contract_id', 'state')
    def _check_contract_active_when_submitted(self):
        for request in self:
            if request.state == 'submitted' and request.contract_id.state != 'active':
                raise ValidationError(_("A renewal can only be requested for an active contract."))

    @api.constrains('contract_id', 'state')
    def _check_single_open_request(self):
        for request in self:
            if request.state != 'submitted':
                continue
            other_open = self.search_count([
                ('id', '!=', request.id),
                ('contract_id', '=', request.contract_id.id),
                ('state', '=', 'submitted'),
            ])
            if other_open:
                raise ValidationError(_(
                    "%(contract)s already has an open renewal request.", contract=request.contract_id.display_name))

    @api.constrains('requested_start_date', 'requested_end_date')
    def _check_dates(self):
        for request in self:
            if request.requested_end_date <= request.requested_start_date:
                raise ValidationError(_("The requested end date must be after the requested start date."))

    def action_approve(self):
        for request in self:
            if request.state != 'submitted':
                raise UserError(_("Only a submitted request can be approved."))
            new_contract = request.contract_id.action_renew(
                request.requested_start_date, request.requested_end_date, request.requested_rent_amount)
            request.write({'state': 'approved', 'new_contract_id': new_contract.id})

    def action_reject(self, reason=None):
        for request in self:
            if request.state != 'submitted':
                raise UserError(_("Only a submitted request can be rejected."))
            request.write({'state': 'rejected', 'decision_note': reason})
