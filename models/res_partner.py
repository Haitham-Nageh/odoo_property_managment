import logging
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

PORTAL_RETENTION_DAYS = 30


class ResPartner(models.Model):
    _inherit = 'res.partner'

    edara_ownership_ids = fields.One2many('edara.ownership', 'owner_id', string='EDARA Ownerships')
    is_edara_owner = fields.Boolean(string='EDARA Owner', compute='_compute_is_edara_owner', store=True)

    edara_lease_contract_ids = fields.One2many('edara.lease.contract', 'tenant_id', string='EDARA Lease Contracts')
    edara_lease_contract_count = fields.Integer(
        compute='_compute_edara_lease_contract_count',
        store=True,
    )
    is_edara_tenant = fields.Boolean(string='EDARA Tenant', compute='_compute_is_edara_tenant', store=True)
    edara_national_id = fields.Char(string='National ID / Registration No.')
    edara_portal_settled_date = fields.Date(
        string='Portal Settled Date',
        readonly=True,
        copy=False,
        help="Date when tenant obligations were cleanly settled with no active contract.",
    )

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

    @api.depends('edara_lease_contract_ids')
    def _compute_edara_lease_contract_count(self):
        for partner in self:
            partner.edara_lease_contract_count = len(partner.edara_lease_contract_ids)

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

    def _get_edara_activity_user(self):
        self.ensure_one()
        contracts = self.sudo().edara_lease_contract_ids.sorted(
            key=lambda c: c.end_date or fields.Date.today(), reverse=True
        )
        for contract in contracts:
            if contract.branch_id.manager_id:
                return contract.branch_id.manager_id
        return self.env.ref('base.user_admin')

    def _is_usable_email(self, email):
        if not email or not isinstance(email, str):
            return False
        email = email.strip()
        if '@' not in email:
            return False
        parts = email.split('@')
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return False
        domain_parts = parts[1].split('.')
        if len(domain_parts) < 2 or not all(domain_parts):
            return False
        return True

    def _schedule_edara_portal_activity(self, summary, note):
        self.ensure_one()
        existing = self.sudo().activity_ids.filtered(lambda a: a.summary == summary)
        if not existing:
            user = self._get_edara_activity_user()
            self.sudo().activity_schedule(
                summary=summary,
                note=note,
                user_id=user.id,
                date_deadline=fields.Date.context_today(self),
            )

    def _provision_edara_portal_tenant(self):
        """Provision or reactivate EDARA portal access for tenant partners.
        When a partner has an active EDARA lease:
        - Reactivates lifecycle-archived portal users (never manually archived users).
        - Grants base.group_portal and property_managment.group_edara_portal_tenant.
        - Creates a new portal user if no res.users record exists, given a usable email.
        - Schedules deduplicated staff follow-up activities if email is missing/invalid or login conflicts.
        - Never modifies internal users.
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

            # Never touch partners linked to internal users
            if any(u.has_group('base.group_user') for u in users):
                continue

            portal_users = users.filtered(lambda u: not u.has_group('base.group_user'))
            if portal_users:
                for user in portal_users:
                    vals = {}
                    if not user.active:
                        if user.edara_portal_lifecycle_archived:
                            vals['active'] = True
                            vals['edara_portal_lifecycle_archived'] = False
                        else:
                            # Deliberately manually archived: never automatically reactivate
                            continue
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
                email = (partner.email or '').strip()
                if not email:
                    partner._schedule_edara_portal_activity(
                        _("Portal Provisioning: Missing Email"),
                        _(
                            "Tenant %s has an active contract but no email address configured. "
                            "Add an email to provision portal access.",
                            partner.display_name,
                        ),
                    )
                    continue

                if not partner._is_usable_email(email):
                    partner._schedule_edara_portal_activity(
                        _("Portal Provisioning: Invalid Email"),
                        _(
                            "Tenant %(name)s has an invalid email '%(email)s'. "
                            "Correct the email to provision portal access.",
                            name=partner.display_name,
                            email=email,
                        ),
                    )
                    continue

                login = email.lower()
                existing_login = self.env['res.users'].sudo().search([
                    ('login', '=', login),
                    ('partner_id', '!=', partner.id),
                    ('active', 'in', [True, False]),
                ], limit=1)
                if existing_login:
                    partner._schedule_edara_portal_activity(
                        _("Portal Provisioning: Login Conflict"),
                        _(
                            "Login '%(login)s' for tenant %(name)s is already in use by another user account. "
                            "Resolve the conflict to provision portal access.",
                            login=email,
                            name=partner.display_name,
                        ),
                    )
                    continue

                company = partner.company_id or self.env.company
                user_vals = {
                    'name': partner.name,
                    'login': login,
                    'email': email,
                    'partner_id': partner.id,
                    'company_id': company.id,
                    'company_ids': [(4, company.id)],
                    'group_ids': [(6, 0, [portal_group.id, edara_portal_group.id])],
                    'active': True,
                    'edara_portal_lifecycle_archived': False,
                }
                self.env['res.users'].sudo().with_context(
                    no_reset_password=True, signup_valid=False
                ).create(user_vals)

    def _evaluate_single_portal_tenant(self, partner):
        """Evaluate portal lifecycle for a single tenant partner.
        Returns the number of portal users archived (if any)."""
        today = fields.Date.context_today(self)
        edara_portal_group = self.env.ref('property_managment.group_edara_portal_tenant', raise_if_not_found=False)
        portal_group = self.env.ref('base.group_portal', raise_if_not_found=False)
        if not edara_portal_group or not portal_group:
            return 0

        # Never touch internal users
        users = self.env['res.users'].sudo().search([
            ('partner_id', '=', partner.id),
            ('active', 'in', [True, False]),
        ])
        if any(u.has_group('base.group_user') for u in users):
            return 0

        portal_users = users.filtered(
            lambda u: not u.has_group('base.group_user') and (
                portal_group in u.group_ids or edara_portal_group in u.group_ids
            )
        )

        contracts = partner.edara_lease_contract_ids
        has_active_contract = any(c.state == 'active' for c in contracts)

        # 1. Active contract rule:
        # A tenant with an active contract is entitled to portal access.
        # An active contract always takes precedence over end-date and grace-period evaluation.
        # Clear settled date when active qualifying contract exists.
        if has_active_contract:
            if partner.edara_portal_settled_date:
                partner.sudo().write({'edara_portal_settled_date': False})

            # Retry provisioning if no portal user exists, or reactivate if lifecycle-archived
            if not portal_users:
                partner._provision_edara_portal_tenant()
            else:
                for user in portal_users:
                    vals = {}
                    if not user.active and user.edara_portal_lifecycle_archived:
                        vals['active'] = True
                        vals['edara_portal_lifecycle_archived'] = False
                    groups_to_add = []
                    if portal_group not in user.group_ids:
                        groups_to_add.append(portal_group.id)
                    if edara_portal_group not in user.group_ids:
                        groups_to_add.append(edara_portal_group.id)
                    if groups_to_add:
                        vals['group_ids'] = [(4, gid) for gid in groups_to_add]
                    if vals:
                        user.sudo().write(vals)
            return 0

        # 2. No active contract:
        # Evaluate obligations (blockers)
        unsettled_invoices = self.env['account.move'].sudo().search([
            ('move_type', '=', 'out_invoice'),
            ('partner_id', '=', partner.id),
            ('edara_invoice_type', 'in', ['rent', 'late_fee', 'service_charge', 'ad_hoc']),
            ('state', '!=', 'cancel'),
        ])
        blocking_invoices = unsettled_invoices.filtered(
            lambda inv: not (inv.state == 'posted' and inv.payment_state in ('paid', 'reversed'))
        )

        blocking_schedule_lines = self.env['edara.payment.schedule.line'].sudo().search([
            ('contract_id.tenant_id', '=', partner.id),
            ('invoice_id', '=', False),
            ('due_date', '<=', today),
            ('contract_id.state', 'in', ['terminated', 'expired', 'renewed']),
        ])

        blocking_service_charge_lines = self.env['edara.service.charge.line'].sudo().search([
            ('tenant_id', '=', partner.id),
            ('invoice_id', '=', False),
        ])

        has_blockers = bool(blocking_invoices or blocking_schedule_lines or blocking_service_charge_lines)

        if has_blockers:
            # When a new blocker appears, clear the settled date
            if partner.edara_portal_settled_date:
                partner.sudo().write({'edara_portal_settled_date': False})

            # Reactivate lifecycle-archived users if a qualifying blocker appears
            for user in portal_users:
                if not user.active and user.edara_portal_lifecycle_archived:
                    vals = {'active': True, 'edara_portal_lifecycle_archived': False}
                    groups_to_add = []
                    if portal_group not in user.group_ids:
                        groups_to_add.append(portal_group.id)
                    if edara_portal_group not in user.group_ids:
                        groups_to_add.append(edara_portal_group.id)
                    if groups_to_add:
                        vals['group_ids'] = [(4, gid) for gid in groups_to_add]
                    user.sudo().write(vals)

            # Deduplicate staff follow-up activities
            for line in blocking_service_charge_lines:
                summary = _("Pending Service Charge: %s", line.charge_id.name or _("Line"))
                note = _(
                    "Service charge '%(charge)s' for unit %(unit)s is uninvoiced for tenant %(tenant)s.",
                    charge=line.charge_id.display_name,
                    unit=line.unit_id.display_name,
                    tenant=partner.display_name,
                )
                partner._schedule_edara_portal_activity(summary, note)

            for inv in blocking_invoices.filtered(lambda i: i.edara_invoice_type == 'ad_hoc'):
                summary = _("Unsettled Ad-hoc Invoice: %s", inv.name or _("Draft"))
                unit_name = inv.edara_unit_id.display_name if inv.edara_unit_id else _("Unassigned")
                note = _(
                    "Ad-hoc invoice %(invoice)s (Amount: %(amount)s %(currency)s, Unit: %(unit)s) "
                    "for tenant %(tenant)s is unsettled.",
                    invoice=inv.display_name,
                    amount=inv.amount_total,
                    currency=inv.currency_id.name or '',
                    unit=unit_name,
                    tenant=partner.display_name,
                )
                partner._schedule_edara_portal_activity(summary, note)

            return 0

        # 3. No active contract AND No blockers:
        has_qualifying_invoice_history = bool(self.env['account.move'].sudo().search([
            ('move_type', '=', 'out_invoice'),
            ('partner_id', '=', partner.id),
            ('edara_invoice_type', 'in', ['rent', 'late_fee', 'service_charge', 'ad_hoc']),
            ('state', '=', 'posted'),
        ], limit=1))

        if not partner.edara_portal_settled_date and has_qualifying_invoice_history:
            partner.sudo().write({'edara_portal_settled_date': today})

        ended_contracts = contracts.filtered(lambda c: c.state in ('terminated', 'expired', 'renewed'))
        effective_ends = []
        for c in ended_contracts:
            if c.state == 'terminated':
                dates = [d for d in [c.termination_date, c.end_date] if d]
                if dates:
                    effective_ends.append(min(dates))
            else:
                if c.end_date:
                    effective_ends.append(c.end_date)

        latest_effective_end = max(effective_ends) if effective_ends else False

        anchors = [d for d in [latest_effective_end, partner.edara_portal_settled_date] if d]
        if not anchors:
            archived_count = 0
            for user in portal_users.filtered(lambda u: u.active):
                user.sudo().write({'active': False, 'edara_portal_lifecycle_archived': True})
                archived_count += 1
            return archived_count

        grace_anchor = max(anchors)
        company = partner.company_id or self.env.company
        grace_days = company.edara_portal_grace_days if company.edara_portal_grace_days is not False else 30
        grace_end = grace_anchor + relativedelta(days=grace_days)

        if today > grace_end:
            archived_count = 0
            for user in portal_users.filtered(lambda u: u.active):
                user.sudo().write({'active': False, 'edara_portal_lifecycle_archived': True})
                archived_count += 1
            return archived_count

        return 0

    @api.model
    def _cron_cleanup_expired_portal_tenants(self):
        """Portal User Lifecycle — Daily cleanup job for EDARA tenant portal users.
        - Evaluates tenants that have active or archived portal users.
        - Also processes tenants with active contracts but no portal user to retry provisioning.
        - Safely isolates per-tenant processing using savepoints.
        """
        edara_portal_group = self.env.ref('property_managment.group_edara_portal_tenant', raise_if_not_found=False)
        portal_group = self.env.ref('base.group_portal', raise_if_not_found=False)
        if not edara_portal_group or not portal_group:
            return 0

        portal_users = self.env['res.users'].sudo().search([
            ('group_ids', 'in', [edara_portal_group.id]),
            ('active', 'in', [True, False]),
        ])
        portal_partners = portal_users.mapped('partner_id')

        active_contracts = self.env['edara.lease.contract'].sudo().search([
            ('state', '=', 'active'),
        ])
        active_partners = active_contracts.mapped('tenant_id')

        candidate_partners = (portal_partners | active_partners).filtered('id')

        archived_count = 0
        for partner in candidate_partners:
            try:
                with self.env.cr.savepoint():
                    archived = self._evaluate_single_portal_tenant(partner)
                    if archived:
                        archived_count += archived
            except Exception as e:
                _logger.exception(
                    "Failed to evaluate portal lifecycle for partner %s (ID %s): %s",
                    partner.name, partner.id, e,
                )
                continue

        return archived_count

    def _has_single_overdue_currency(self):
        """Phase 12.10: Return True if this partner has at most one distinct
        currency among their overdue invoices, allowing native batch payment.
        If overdue invoices span multiple currencies, return False so that
        the batch 'Pay All Overdue' action is hidden in portal views."""
        if not self:
            return True
        partner = self[:1]
        moves = self.env['account.move'].sudo().search([
            ('state', 'not in', ('cancel', 'draft')),
            ('move_type', 'in', ('out_invoice', 'out_receipt')),
            ('payment_state', 'not in', ('in_payment', 'paid', 'reversed', 'blocked', 'invoicing_legacy')),
            ('invoice_date_due', '<', fields.Date.today()),
            ('partner_id', '=', partner.id),
        ])
        return len(moves.currency_id) <= 1

    def action_view_edara_lease_contracts(self):
        self.ensure_one()

        action = self.env['ir.actions.act_window']._for_xml_id(
            'property_managment.action_edara_lease_contract'
        )

        action['domain'] = [('tenant_id', '=', self.id)]
        action['context'] = {'default_tenant_id': self.id}

        return action
