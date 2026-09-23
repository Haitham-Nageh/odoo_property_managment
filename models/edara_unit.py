from odoo import api, fields, models
from odoo.exceptions import ValidationError

UNIT_TYPES = [
    ('apartment', 'Apartment'),
    ('office', 'Office'),
    ('shop', 'Shop'),
    ('warehouse', 'Warehouse'),
    ('villa', 'Villa'),
    ('parking', 'Parking'),
    ('commercial', 'Commercial Space'),
    ('other', 'Other'),
]

OCCUPANCY_STATUSES = [
    ('available', 'Available'),
    ('reserved', 'Reserved'),
    ('rented', 'Rented'),
    ('owner_occupied', 'Owner Occupied'),
    ('sold', 'Sold'),
]

OPERATIONAL_STATUSES = [
    ('normal', 'Normal'),
    ('under_maintenance', 'Under Maintenance'),
]


class EdaraUnit(models.Model):
    _name = 'edara.unit'
    _description = 'EDARA Unit'
    _inherit = ['mail.thread']
    _order = 'building_id, floor, name'

    name = fields.Char(required=True, tracking=True, help="e.g. A-101, Shop-01.")
    code = fields.Char(required=True, tracking=True)
    building_id = fields.Many2one('edara.building', string='Building', required=True, index=True, tracking=True)
    property_id = fields.Many2one(related='building_id.property_id', string='Property', store=True, index=True)
    branch_id = fields.Many2one(related='building_id.branch_id', string='Branch', store=True, index=True)
    company_id = fields.Many2one(related='building_id.company_id', string='Company', store=True, index=True)
    active = fields.Boolean(default=True)

    floor = fields.Char()
    unit_number = fields.Char()
    unit_type = fields.Selection(UNIT_TYPES, string='Type', required=True, default='apartment', tracking=True)
    area = fields.Float(string='Area (sqm)')
    bedrooms = fields.Integer()
    bathrooms = fields.Integer()

    rent_amount_default = fields.Monetary(string='Default Rent', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: self.env.company.currency_id)

    occupancy_status = fields.Selection(OCCUPANCY_STATUSES, string='Occupancy', required=True,
                                         default='available', tracking=True, index=True,
                                         help="'Rented' can only be set through an active lease contract "
                                              "(see the Contracts smart button) - it is not freely editable.")
    operational_status = fields.Selection(OPERATIONAL_STATUSES, string='Operational State', required=True,
                                           default='normal', tracking=True)

    lease_contract_ids = fields.One2many('edara.lease.contract', 'unit_id', string='Lease Contracts')
    contract_count = fields.Integer(compute='_compute_contract_count')
    active_tenant_name = fields.Char(compute='_compute_active_lease_display', help=(
        "Dashboard UX Hardening 6.1 (2026-09-23): a read-only projection of "
        "this unit's own active lease_contract_ids - not a new business "
        "field, no data beyond what the Contracts smart button already "
        "shows. Used only by the Unit Kanban card."))
    active_contract_name = fields.Char(compute='_compute_active_lease_display')

    maintenance_request_ids = fields.One2many('edara.maintenance.request', 'unit_id', string='Maintenance Requests')
    maintenance_request_count = fields.Integer(compute='_compute_maintenance_request_count')

    total_revenue = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id')
    total_expenses = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id')
    total_outstanding = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id')
    maintenance_cost = fields.Monetary(compute='_compute_financial_summary', currency_field='currency_id')
    has_accounting_access = fields.Boolean(compute='_compute_financial_summary', help=(
        "Whether the current user has native Odoo read access to account.move "
        "- drives whether this unit's Financial Summary page is shown at all "
        "(Reporting & Management Intelligence, 2026-09-22; same MAT-FIND-014 "
        "permission-aware pattern already used on edara.property/edara.branch/edara.dashboard)."))

    _code_building_uniq = models.Constraint(
        'unique(building_id, code)',
        'Unit code must be unique within a building.',
    )

    def copy(self, default=None):
        """MAT-FIND-003 (2026-09-22): native Duplicate must not fail against
        the (correct, unchanged) unit-code uniqueness constraint. `code` is
        a plain internal unique identifier, not the business-facing unit
        number - that role belongs to the separate, unconstrained
        `unit_number` field (confirmed: `code` is referenced nowhere else in
        the module besides this model's own uniqueness constraint) - so it
        is safe to auto-regenerate rather than requiring the user to type a
        new one in before saving. Appends a `-COPY`/`-COPY2`/... suffix to
        the original code, scoped to the same building (the constraint's own
        scope), guaranteed unique before the copy is even created - never
        touches the original unit's code, never bypasses the constraint."""
        default = dict(default or {})
        if 'code' not in default:
            candidate = '%s-COPY' % self.code
            suffix = 2
            while self.search_count([('building_id', '=', self.building_id.id), ('code', '=', candidate)]):
                candidate = '%s-COPY%d' % (self.code, suffix)
                suffix += 1
            default['code'] = candidate
        if 'occupancy_status' not in default and self.occupancy_status in ('rented', 'reserved'):
            # lease_contract_ids (a One2many) is never copied by native
            # duplication, so a 'rented'/'reserved' copy would otherwise
            # violate _check_occupancy_status_derivation() with zero backing
            # contracts. 'owner_occupied'/'sold' are administrative,
            # contract-independent states and are safely preserved as-is.
            default['occupancy_status'] = 'available'
        return super().copy(default)

    @api.constrains('occupancy_status', 'operational_status')
    def _check_status_consistency(self):
        for unit in self:
            if unit.operational_status == 'under_maintenance' and unit.occupancy_status == 'available':
                raise ValidationError(self.env._(
                    "%(unit)s cannot be Available while it is Under Maintenance.",
                    unit=unit.display_name,
                ))

    @api.constrains('occupancy_status')
    def _check_occupancy_status_derivation(self):
        for unit in self:
            if unit.occupancy_status == 'rented' and not unit._has_current_active_contract():
                raise ValidationError(self.env._(
                    "%(unit)s can only be marked Rented through an active lease contract "
                    "that is currently in force (its start date must have arrived).",
                    unit=unit.display_name,
                ))
            if unit.occupancy_status == 'available' and unit._has_current_active_contract():
                raise ValidationError(self.env._(
                    "%(unit)s cannot be marked Available while it still has a currently active "
                    "lease contract covering today.",
                    unit=unit.display_name,
                ))
            if unit.occupancy_status == 'available' and unit._has_future_active_contract():
                raise ValidationError(self.env._(
                    "%(unit)s cannot be marked Available while it has an active lease contract "
                    "reserved for a future start date - use Reserved instead.",
                    unit=unit.display_name,
                ))

    def _has_current_active_contract(self):
        """Whether this unit has an active-state lease contract whose date range
        covers today. An 'active' contract with a future start_date does not
        count - state=active does not by itself mean occupying the unit today
        (see EDARA_PROJECT_STATE.md, MAT-020)."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        return bool(self.env['edara.lease.contract'].search_count([
            ('unit_id', '=', self.id),
            ('state', '=', 'active'),
            ('start_date', '<=', today),
            ('end_date', '>=', today),
        ]))

    def _has_future_active_contract(self):
        """Whether this unit has an active-state lease contract that has not
        started yet (start_date > today) - the "contractually committed for
        future occupancy, but not currently occupied" case (BD-001,
        2026-09-21, resolves MAT-FIND-010): such a unit is RESERVED, not
        AVAILABLE, until that contract's start date arrives."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        return bool(self.env['edara.lease.contract'].search_count([
            ('unit_id', '=', self.id),
            ('state', '=', 'active'),
            ('start_date', '>', today),
        ]))

    def _lease_occupancy_state(self):
        """Pure derivation (BD-001, 2026-09-21) of what occupancy_status this
        unit's active lease contracts alone imply, independent of the unit's
        current stored value: 'rented' if an active contract currently covers
        today, else 'reserved' if an active contract exists but hasn't
        started yet, else 'available'. A unit can have both a current and a
        future active contract at once (sequential, non-overlapping leases,
        MAT-020) - 'rented' always wins in that case, since the unit IS
        occupied today regardless of what's queued up next."""
        self.ensure_one()
        if self._has_current_active_contract():
            return 'rented'
        if self._has_future_active_contract():
            return 'reserved'
        return 'available'

    def _sync_occupancy_from_contracts(self):
        """Reusable occupancy recomputation for lease-lifecycle events
        (terminate, cron expiry, the reserved-to-rented start-date cron -
        _cron_sync_reserved_occupancy) that can change which contract governs
        a unit. Derives the correct value via _lease_occupancy_state() for
        any unit currently in one of the three lease-managed states
        (available/reserved/rented). Never touches a unit manually set to
        owner_occupied/sold - those are administrative states outside the
        lease lifecycle. Intentionally NOT the code path action_activate()
        uses - activation unconditionally forces the derived state on every
        unit regardless of its prior value (see action_activate())."""
        for unit in self:
            if unit.occupancy_status not in ('available', 'reserved', 'rented'):
                continue
            unit.occupancy_status = unit._lease_occupancy_state()

    @api.model
    def _cron_sync_reserved_occupancy(self):
        """Daily (BD-001/MAT-FIND-010, 2026-09-21). The reliable start-date-
        arrival mechanism BD-001 requires: re-evaluates every unit currently
        RESERVED and flips it to RENTED once its governing lease contract's
        start_date has arrived. Naturally idempotent - only ever touches
        units currently 'reserved'; a unit already flipped to 'rented' on a
        prior run no longer matches this domain on the next run, so
        re-running finds nothing further to do. Pure occupancy_status
        recompute via the existing _sync_occupancy_from_contracts() - no
        accounting side effects, no schedule-line changes, no company filter
        needed (matches the existing _cron_expire_contracts()/
        _cron_generate_due_invoices() convention of running unscoped)."""
        self.search([('occupancy_status', '=', 'reserved')])._sync_occupancy_from_contracts()

    @api.depends('lease_contract_ids')
    def _compute_contract_count(self):
        data = self.env['edara.lease.contract']._read_group(
            [('unit_id', 'in', self.ids)], ['unit_id'], ['__count'])
        counts = {unit.id: count for unit, count in data}
        for unit in self:
            unit.contract_count = counts.get(unit.id, 0)

    @api.depends('lease_contract_ids.state', 'lease_contract_ids.tenant_id', 'lease_contract_ids.name')
    def _compute_active_lease_display(self):
        active_contracts = self.env['edara.lease.contract'].search(
            [('unit_id', 'in', self.ids), ('state', '=', 'active')])
        by_unit = {contract.unit_id.id: contract for contract in active_contracts}
        for unit in self:
            contract = by_unit.get(unit.id)
            unit.active_tenant_name = contract.tenant_id.name if contract else False
            unit.active_contract_name = contract.name if contract else False

    def action_view_contracts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_lease_contract')
        action['domain'] = [('unit_id', '=', self.id)]
        action['context'] = {'default_unit_id': self.id}
        return action

    @api.depends('maintenance_request_ids')
    def _compute_maintenance_request_count(self):
        data = self.env['edara.maintenance.request']._read_group(
            [('unit_id', 'in', self.ids)], ['unit_id'], ['__count'])
        counts = {unit.id: count for unit, count in data}
        for unit in self:
            unit.maintenance_request_count = counts.get(unit.id, 0)

    def action_view_maintenance_requests(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('property_managment.action_edara_maintenance_request')
        action['domain'] = [('unit_id', '=', self.id)]
        action['context'] = {'default_unit_id': self.id}
        return action

    @api.depends()
    def _compute_financial_summary(self):
        """Unit/Property Performance (Reporting & Management Intelligence,
        2026-09-22) - same non-stored, on-demand, MAT-FIND-014-gated pattern
        already used on edara.property/edara.branch, scoped to edara_unit_id
        instead. Deliberately not added to any list/kanban view - only the
        single-record form - so browsing the Units list never triggers one
        account.move query per row."""
        Move = self.env['account.move']
        has_accounting_access = Move.has_access('read')
        for unit in self:
            unit.has_accounting_access = has_accounting_access
            if not has_accounting_access:
                unit.total_revenue = 0.0
                unit.total_expenses = 0.0
                unit.total_outstanding = 0.0
                unit.maintenance_cost = 0.0
                continue
            revenue_row = Move._read_group(
                [('edara_unit_id', '=', unit.id), ('state', '=', 'posted'),
                 ('move_type', 'in', ('out_invoice', 'out_refund'))],
                [], ['amount_untaxed_signed:sum', 'amount_residual_signed:sum'])
            revenue, outstanding = revenue_row[0] if revenue_row else (0.0, 0.0)
            expense_row = Move._read_group(
                [('edara_unit_id', '=', unit.id), ('state', '=', 'posted'),
                 ('move_type', 'in', ('in_invoice', 'in_refund'))],
                [], ['amount_untaxed_signed:sum'])
            expenses = -(expense_row[0][0] if expense_row else 0.0)
            maintenance_row = Move._read_group(
                [('edara_unit_id', '=', unit.id), ('state', '=', 'posted'),
                 ('move_type', 'in', ('in_invoice', 'in_refund')), ('edara_invoice_type', '=', 'maintenance')],
                [], ['amount_untaxed_signed:sum'])
            maintenance_cost = -(maintenance_row[0][0] if maintenance_row else 0.0)
            unit.total_revenue = revenue or 0.0
            unit.total_expenses = expenses or 0.0
            unit.total_outstanding = outstanding or 0.0
            unit.maintenance_cost = maintenance_cost or 0.0
