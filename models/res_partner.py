from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

PORTAL_RETENTION_DAYS = 30


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

    def _provision_edara_portal_tenant(self):
        """Phase 12.6 — Provision or reactivate EDARA portal access for tenant partners.
        When a partner has a live EDARA lease (scheduled or active):
        - Reactivates existing archived portal users.
        - Grants base.group_portal and property_managment.group_edara_portal_tenant.
        - Creates a new portal user if no res.users record exists.
        - Idempotent and safe to execute repeatedly.
        """
        portal_group = self.env.ref('base.group_portal', raise_if_not_found=False)
        edara_portal_group = self.env.ref('property_managment.group_edara_portal_tenant', raise_if_not_found=False)
        if not portal_group or not edara_portal_group:
            return

        for partner in self:
            users = self.env['res.users'].sudo().search([
                ('partner_id', '=', partner.id),
                ('active', 'in', [True, False]),
            ])

            portal_users = users.filtered(
                lambda u: portal_group in u.group_ids or edara_portal_group in u.group_ids
            )
            if not portal_users and users:
                portal_users = users

            if portal_users:
                for user in portal_users:
                    vals = {}
                    if not user.active:
                        vals['active'] = True
                    groups_to_add = []
                    if portal_group not in user.group_ids:
                        groups_to_add.append(portal_group.id)
                    if edara_portal_group not in user.group_ids:
                        groups_to_add.append(edara_portal_group.id)
                    if groups_to_add:
                        vals['group_ids'] = [(4, gid) for gid in groups_to_add]
                    if vals:
                        user.sudo().write(vals)
            else:
                company = partner.company_id or self.env.company
                login = partner.email or partner.phone or f"tenant_{partner.id}@edara.local"
                existing = self.env['res.users'].sudo().search([
                    ('login', '=', login),
                    ('active', 'in', [True, False]),
                ], limit=1)
                if existing:
                    login = f"tenant_{partner.id}_{partner.id}@edara.local"

                user_vals = {
                    'name': partner.name,
                    'login': login,
                    'email': partner.email or partner.phone or '',
                    'partner_id': partner.id,
                    'company_id': company.id,
                    'company_ids': [(4, company.id)],
                    'group_ids': [(6, 0, [portal_group.id, edara_portal_group.id])],
                    'active': True,
                }
                self.env['res.users'].sudo().with_context(
                    no_reset_password=True, signup_valid=False
                ).create(user_vals)

    @api.model
    def _cron_cleanup_expired_portal_tenants(self):
        """Phase 12.6 — Daily cleanup job for EDARA tenant portal users.
        - Evaluates res.users records with group_edara_portal_tenant.
        - Keeps users active if they have any live lease (scheduled or active).
        - If no live lease exists, computes the latest end_date among non-draft, non-cancelled leases.
        - If today > latest_end_date + PORTAL_RETENTION_DAYS (30 days), archives the user (active=False).
        - Does NOT delete res.users records; does NOT remove group_edara_portal_tenant.
        - Idempotent and safe to execute repeatedly.
        """
        today = fields.Date.context_today(self)
        edara_portal_group = self.env.ref('property_managment.group_edara_portal_tenant', raise_if_not_found=False)
        if not edara_portal_group:
            return 0

        portal_tenant_users = self.env['res.users'].sudo().search([
            ('group_ids', 'in', [edara_portal_group.id]),
            ('active', '=', True),
        ])

        archived_count = 0
        for user in portal_tenant_users:
            partner = user.partner_id
            if not partner:
                continue

            contracts = partner.edara_lease_contract_ids
            has_live_lease = any(c.state in ['scheduled', 'active'] for c in contracts)
            if has_live_lease:
                continue

            valid_contracts = contracts.filtered(lambda c: c.state not in ('draft', 'cancelled') and c.end_date)
            if not valid_contracts:
                user.sudo().write({'active': False})
                archived_count += 1
                continue

            latest_end_date = max(valid_contracts.mapped('end_date'))
            retention_threshold = latest_end_date + relativedelta(days=PORTAL_RETENTION_DAYS)
            if today > retention_threshold:
                user.sudo().write({'active': False})
                archived_count += 1

        return archived_count
