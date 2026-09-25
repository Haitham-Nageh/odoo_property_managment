from odoo import _
from odoo.exceptions import AccessError, UserError
from odoo.http import request, route

from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.portal import pager as portal_pager


class EdaraPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id
        if 'lease_count' in counters:
            values['lease_count'] = request.env['edara.lease.contract'].search_count(
                [('tenant_id', '=', partner.id)])
        if 'maintenance_count' in counters:
            values['maintenance_count'] = request.env['edara.maintenance.request'].search_count(
                [('tenant_id', '=', partner.id)])
        return values

    def _edara_tenant_active_units(self):
        partner = request.env.user.partner_id
        contracts = request.env['edara.lease.contract'].search([
            ('tenant_id', '=', partner.id), ('state', '=', 'active'),
        ])
        return contracts.mapped('unit_id')

    def _edara_get_tenant_partner(self):
        """Tenant Portal Expansion (2026-09-22), spec §6 Tenant Resolution:
        the single safe tenant-resolution helper reused by every Phase 3
        route below. The partner always comes from the authenticated
        session (request.env.user.partner_id) - never from a URL/POST/query
        parameter - and must already be a real EDARA tenant
        (res.partner.is_edara_tenant, an existing stored computed field, not
        reinvented here). Fails closed: no tenant relationship means no
        data, never a silent fallback to broader access."""
        partner = request.env.user.partner_id
        if not partner.is_edara_tenant:
            raise AccessError(_("This portal area is only available to EDARA tenants."))
        return partner

    _EDARA_NOTIFICATION_MODELS = [
        'edara.lease.contract', 'edara.maintenance.request',
        'edara.renewal.request', 'edara.payment.schedule.line',
    ]

    def _edara_tenant_notifications(self, partner, limit=None):
        """Notifications (spec §18): exposes only tenant-facing chatter
        messages, never Phase 1's internal mail.activity automation (staff
        assignments/reminders - never queried here at all). A message only
        ever matches if it was explicitly addressed to THIS server-resolved
        tenant partner via partner_ids (message_post(partner_ids=...), the
        same call sites Phase 1/3 use) - client input plays no part in the
        filter, so this can never leak another tenant's notifications.
        sudo() is required (portal has no ACL on mail.message at all), but
        the partner_ids domain IS the authorization, evaluated before
        elevation conceptually the same way MAT-FIND-015's scoped-sudo
        pattern works elsewhere in this module."""
        domain = [('model', 'in', self._EDARA_NOTIFICATION_MODELS), ('partner_ids', 'in', partner.id)]
        return request.env['mail.message'].sudo().search(domain, order='date desc', limit=limit)

    # ------------------------------------------------------------
    # My Lease
    # ------------------------------------------------------------

    @route(['/my/leases', '/my/leases/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_leases(self, page=1, **kw):
        Contract = request.env['edara.lease.contract']
        domain = [('tenant_id', '=', request.env.user.partner_id.id)]
        pager = portal_pager(
            url='/my/leases', total=Contract.search_count(domain), page=page, step=self._items_per_page)
        contracts = Contract.search(
            domain, order='start_date desc', limit=self._items_per_page, offset=pager['offset'])
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'lease', 'contracts': contracts, 'pager': pager})
        return request.render('property_managment.portal_my_leases', values)

    @route(['/my/leases/<int:contract_id>'], type='http', auth='user', website=True)
    def portal_lease_detail(self, contract_id, **kw):
        contract_sudo = self._document_check_access('edara.lease.contract', contract_id)
        open_renewal = contract_sudo.renewal_request_ids.filtered(lambda r: r.state == 'submitted')
        # Renewal Requests (spec §40 item): decided requests, most recent
        # first (model default order is already 'id desc') - the tenant's
        # own renewal history, reusing renewal_request_ids rather than a new
        # route/model.
        renewal_history = contract_sudo.renewal_request_ids.filtered(lambda r: r.state != 'submitted')
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'lease',
            'contract': contract_sudo,
            'open_renewal': open_renewal[:1],
            'renewal_history': renewal_history,
        })
        return request.render('property_managment.portal_lease_detail', values)

    @route(['/my/leases/<int:contract_id>/renew'], type='http', auth='user', website=True, methods=['POST'])
    def portal_lease_request_renewal(self, contract_id, **post):
        contract_sudo = self._document_check_access('edara.lease.contract', contract_id)
        if contract_sudo.tenant_id.id != request.env.user.partner_id.id:
            raise AccessError(_("You are not allowed to request a renewal for this lease."))
        try:
            rent_amount = float(post.get('requested_rent_amount') or contract_sudo.rent_amount)
        except ValueError:
            rent_amount = contract_sudo.rent_amount
        request.env['edara.renewal.request'].create({
            'contract_id': contract_sudo.id,
            'requested_start_date': post.get('requested_start_date') or contract_sudo._term_boundary(),
            'requested_end_date': post.get('requested_end_date'),
            'requested_rent_amount': rent_amount,
            'note': post.get('note'),
        })
        return request.redirect('/my/leases/%d' % contract_id)

    # ------------------------------------------------------------
    # My Maintenance Requests
    # ------------------------------------------------------------

    @route(['/my/maintenance', '/my/maintenance/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_maintenance(self, page=1, **kw):
        MaintenanceRequest = request.env['edara.maintenance.request']
        domain = [('tenant_id', '=', request.env.user.partner_id.id)]
        pager = portal_pager(
            url='/my/maintenance', total=MaintenanceRequest.search_count(domain),
            page=page, step=self._items_per_page)
        maintenance_requests = MaintenanceRequest.search(
            domain, order='requested_date desc', limit=self._items_per_page, offset=pager['offset'])
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'maintenance', 'maintenance_requests': maintenance_requests, 'pager': pager,
        })
        return request.render('property_managment.portal_my_maintenance', values)

    @route(['/my/maintenance/new'], type='http', auth='user', website=True, methods=['GET'])
    def portal_maintenance_new_form(self, **kw):
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'maintenance', 'units': self._edara_tenant_active_units()})
        return request.render('property_managment.portal_maintenance_new', values)

    @route(['/my/maintenance/new'], type='http', auth='user', website=True, methods=['POST'])
    def portal_maintenance_new_submit(self, **post):
        units = self._edara_tenant_active_units()
        try:
            unit_id = int(post.get('unit_id') or 0)
        except ValueError:
            unit_id = 0
        if unit_id not in units.ids:
            raise UserError(_("You can only file a maintenance request for a unit you currently lease."))
        # sudo: ownership already verified above (unit_id restricted to the tenant's own
        # active leases); a portal user has no ir.sequence read access, needed for the
        # request's naming sequence, so the actual create must run with elevated rights.
        maintenance_request = request.env['edara.maintenance.request'].sudo().create({
            'title': post.get('title'),
            'description': post.get('description'),
            'unit_id': unit_id,
            'tenant_id': request.env.user.partner_id.id,
            'priority': post.get('priority') or 'normal',
        })
        return request.redirect('/my/maintenance/%d' % maintenance_request.id)

    @route(['/my/maintenance/<int:request_id>'], type='http', auth='user', website=True)
    def portal_maintenance_detail(self, request_id, **kw):
        maintenance_request_sudo = self._document_check_access('edara.maintenance.request', request_id)
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'maintenance', 'maintenance_request': maintenance_request_sudo})
        return request.render('property_managment.portal_maintenance_detail', values)

    # ------------------------------------------------------------
    # Tenant Dashboard
    # ------------------------------------------------------------

    @route(['/my/dashboard'], type='http', auth='user', website=True)
    def portal_dashboard(self, **kw):
        """Tenant Dashboard (spec §8/§40): a read-only summary built entirely
        from existing fields/models - no duplicated financial fields are
        created solely for display here. Internal management data (owner
        settlement, staff notes, activities, other tenants) is never
        queried, so there is nothing of that kind to leak."""
        partner = self._edara_get_tenant_partner()
        contract = request.env['edara.lease.contract'].sudo().search(
            [('tenant_id', '=', partner.id), ('state', '=', 'active')], order='start_date desc', limit=1)
        next_line = request.env['edara.payment.schedule.line'].sudo().search([
            ('tenant_id', '=', partner.id),
            ('state', 'in', ('draft', 'invoiced', 'overdue', 'partial')),
        ], order='due_date', limit=1)
        moves = request.env['account.move'].sudo().search([
            ('partner_id', '=', partner.id), ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
        ])
        # Phase 8: amount_residual is in each invoice's own currency (a tenant can hold ILS and
        # USD invoices); the signed company-currency residual is summable and nets credit notes.
        outstanding = sum(moves.mapped('amount_residual_signed'))
        open_renewal = request.env['edara.renewal.request'].sudo().search(
            [('tenant_id', '=', partner.id), ('state', '=', 'submitted')], limit=1)
        maintenance_count = request.env['edara.maintenance.request'].sudo().search_count([
            ('tenant_id', '=', partner.id), ('state', 'in', ('new', 'assigned', 'in_progress')),
        ])
        notifications = self._edara_tenant_notifications(partner, limit=5)
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'dashboard',
            'contract': contract,
            'next_line': next_line,
            'outstanding': outstanding,
            'currency': request.env.company.currency_id,
            'open_renewal': open_renewal,
            'maintenance_count': maintenance_count,
            'notifications': notifications,
        })
        return request.render('property_managment.portal_dashboard', values)

    # ------------------------------------------------------------
    # My Unit
    # ------------------------------------------------------------

    @route(['/my/units', '/my/units/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_units(self, page=1, **kw):
        self._edara_get_tenant_partner()
        Unit = request.env['edara.unit']
        domain = [('lease_contract_ids.tenant_id', '=', request.env.user.partner_id.id)]
        pager = portal_pager(
            url='/my/units', total=Unit.search_count(domain), page=page, step=self._items_per_page)
        # The domain above (non-sudo) is the real authorization - it already
        # restricts to this tenant's own unit(s). sudo() here is only to
        # read display fields on related edara.property/edara.building,
        # which the portal tenant group has no ACL on at all (unlike
        # edara.unit itself) - same authorize-first-then-sudo shape as
        # _document_check_access() uses for every detail route.
        units = Unit.search(domain, limit=self._items_per_page, offset=pager['offset']).sudo()
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'unit', 'units': units, 'pager': pager})
        return request.render('property_managment.portal_my_units', values)

    @route(['/my/units/<int:unit_id>'], type='http', auth='user', website=True)
    def portal_unit_detail(self, unit_id, **kw):
        unit_sudo = self._document_check_access('edara.unit', unit_id)
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'unit', 'unit': unit_sudo})
        return request.render('property_managment.portal_unit_detail', values)

    # ------------------------------------------------------------
    # Billing: Invoices / Payments / Outstanding Balance / Payment History
    # ------------------------------------------------------------

    @route(['/my/billing'], type='http', auth='user', website=True)
    def portal_billing(self, **kw):
        """Invoices/Payments/Outstanding Balance/Payment History (spec §40,
        §11-13): an EDARA-branded, business-language read of native
        account.move - the sole accounting source of truth, no parallel
        ledger. Full accounting detail (PDF, tax breakdown, payment
        allocations) intentionally stays on the native /my/invoices/<id>
        page (already installed via the account+portal dependency and
        already tenant/company-isolated by its own native record rules) -
        this page links out to it rather than rebuilding it."""
        partner = self._edara_get_tenant_partner()
        moves = request.env['account.move'].sudo().search([
            ('partner_id', '=', partner.id), ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
        ], order='invoice_date desc')
        # Phase 8: amount_residual is in each invoice's own currency (a tenant can hold ILS and
        # USD invoices); the signed company-currency residual is summable and nets credit notes.
        outstanding = sum(moves.mapped('amount_residual_signed'))
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'billing',
            'moves': moves,
            'outstanding': outstanding,
            'currency': request.env.company.currency_id,
        })
        return request.render('property_managment.portal_billing', values)

    # ------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------

    _EDARA_DOCUMENT_MODELS = ['edara.lease.contract', 'edara.maintenance.request', 'edara.renewal.request']

    @route(['/my/documents'], type='http', auth='user', website=True)
    def portal_documents(self, **kw):
        """Documents (spec §17/§42): reuses native ir.attachment - no
        redundant file-storage system. For each business record type, the
        candidate record set is first restricted to this server-resolved
        tenant's own records (tenant_id = partner.id, never a client id),
        and only THEN are attachments looked up for exactly those ids.
        ir.attachment's own native access check (gated on read access to the
        linked res_model/res_id) independently protects the actual
        /web/content/<id> download link, so cross-tenant/cross-company
        access is denied even if an id were guessed directly."""
        partner = self._edara_get_tenant_partner()
        documents = []
        for model_name in self._EDARA_DOCUMENT_MODELS:
            records = request.env[model_name].sudo().search([('tenant_id', '=', partner.id)])
            if not records:
                continue
            records_by_id = {record.id: record for record in records}
            attachments = request.env['ir.attachment'].sudo().search([
                ('res_model', '=', model_name), ('res_id', 'in', records.ids),
            ], order='create_date desc')
            for attachment in attachments:
                documents.append({'attachment': attachment, 'record': records_by_id.get(attachment.res_id)})
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'documents', 'documents': documents})
        return request.render('property_managment.portal_documents', values)

    # ------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------

    @route(['/my/notifications'], type='http', auth='user', website=True)
    def portal_notifications(self, **kw):
        partner = self._edara_get_tenant_partner()
        notifications = self._edara_tenant_notifications(partner)
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'notifications', 'notifications': notifications})
        return request.render('property_managment.portal_notifications', values)
