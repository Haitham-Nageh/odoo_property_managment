from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    edara_ownership_ids = fields.One2many('edara.ownership', 'owner_id', string='EDARA Ownerships')
    is_edara_owner = fields.Boolean(string='EDARA Owner', compute='_compute_is_edara_owner', store=True)

    edara_lease_contract_ids = fields.One2many('edara.lease.contract', 'tenant_id', string='EDARA Lease Contracts')
    is_edara_tenant = fields.Boolean(string='EDARA Tenant', compute='_compute_is_edara_tenant', store=True)
    edara_national_id = fields.Char(string='National ID / Registration No.')

    # Maintenance Phase 2 (2026-09-23), Vendor Management (ticket §5-9):
    # res.partner IS the vendor source of truth - no separate EdaraVendor
    # model, same is_edara_owner/is_edara_tenant computed-stored pattern.
    edara_maintenance_request_ids = fields.One2many(
        'edara.maintenance.request', 'vendor_id', string='EDARA Maintenance Requests (as Vendor)')
    is_edara_vendor = fields.Boolean(string='EDARA Vendor', compute='_compute_is_edara_vendor', store=True)
    edara_vendor_request_count = fields.Integer(compute='_compute_vendor_stats')
    edara_vendor_open_request_count = fields.Integer(compute='_compute_vendor_stats')
    edara_vendor_last_service_date = fields.Date(compute='_compute_vendor_stats')
    edara_vendor_avg_response_hours = fields.Float(compute='_compute_vendor_stats')
    edara_vendor_avg_resolution_hours = fields.Float(compute='_compute_vendor_stats')
    edara_vendor_maintenance_cost_total = fields.Monetary(
        compute='_compute_vendor_stats', currency_field='currency_id', help=(
            "Sum of posted Vendor Bill totals for this vendor's maintenance "
            "requests - native Accounting, authoritative. Deliberately kept "
            "separate from any request's estimated `cost` (ticket §9: "
            "'these remain separate concepts'). Degrades to 0 (never "
            "AccessError) for a user without native Accounting read access."))
    edara_vendor_has_accounting_access = fields.Boolean(compute='_compute_vendor_stats')

    @api.depends('edara_ownership_ids.active')
    def _compute_is_edara_owner(self):
        for partner in self:
            partner.is_edara_owner = bool(partner.edara_ownership_ids.filtered('active'))

    @api.depends('edara_lease_contract_ids')
    def _compute_is_edara_tenant(self):
        for partner in self:
            partner.is_edara_tenant = bool(partner.edara_lease_contract_ids)

    @api.depends('edara_maintenance_request_ids')
    def _compute_is_edara_vendor(self):
        for partner in self:
            partner.is_edara_vendor = bool(partner.edara_maintenance_request_ids)

    @api.depends()
    def _compute_vendor_stats(self):
        """Live snapshot, recomputed on every read - same non-stored pattern
        as edara.dashboard/edara.property._compute_financial_summary, for
        the same reason (these aggregate across a mutable set of requests
        and a mutable set of posted bills, so a stored value would need
        constant recomputation to stay correct)."""
        Request = self.env['edara.maintenance.request']
        Move = self.env['account.move']
        has_accounting_access = Move.has_access('read')
        for partner in self:
            requests = Request.search([('vendor_id', '=', partner.id)])
            partner.edara_vendor_request_count = len(requests)
            partner.edara_vendor_open_request_count = len(
                requests.filtered(lambda r: r.state not in ('done', 'cancelled')))
            completed = requests.filtered('completed_date')
            partner.edara_vendor_last_service_date = max(completed.mapped('completed_date'), default=False)
            response_samples = requests.filtered('response_hours').mapped('response_hours')
            resolution_samples = requests.filtered('resolution_hours').mapped('resolution_hours')
            partner.edara_vendor_avg_response_hours = (
                sum(response_samples) / len(response_samples) if response_samples else 0.0)
            partner.edara_vendor_avg_resolution_hours = (
                sum(resolution_samples) / len(resolution_samples) if resolution_samples else 0.0)
            partner.edara_vendor_has_accounting_access = has_accounting_access
            if not has_accounting_access:
                partner.edara_vendor_maintenance_cost_total = 0.0
                continue
            cost_row = Move._read_group(
                [('id', 'in', requests.mapped('vendor_bill_id').ids), ('state', '=', 'posted')],
                [], ['amount_total:sum'])
            partner.edara_vendor_maintenance_cost_total = cost_row[0][0] if cost_row else 0.0
