from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    edara_ownership_ids = fields.One2many('edara.ownership', 'owner_id', string='EDARA Ownerships')
    is_edara_owner = fields.Boolean(string='EDARA Owner', compute='_compute_is_edara_owner', store=True)

    edara_lease_contract_ids = fields.One2many('edara.lease.contract', 'tenant_id', string='EDARA Lease Contracts')
    is_edara_tenant = fields.Boolean(string='EDARA Tenant', compute='_compute_is_edara_tenant', store=True)
    edara_national_id = fields.Char(string='National ID / Registration No.')

    @api.depends('edara_ownership_ids.active')
    def _compute_is_edara_owner(self):
        for partner in self:
            partner.is_edara_owner = bool(partner.edara_ownership_ids.filtered('active'))

    @api.depends('edara_lease_contract_ids')
    def _compute_is_edara_tenant(self):
        for partner in self:
            partner.is_edara_tenant = bool(partner.edara_lease_contract_ids)
