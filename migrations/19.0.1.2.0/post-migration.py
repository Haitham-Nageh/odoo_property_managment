"""Phase 10.1.1: leave stored unit occupancy consistent with the migrated lease states.

19.0.1.1.0 moved lease states (active-with-future-start -> scheduled, in-term renewed -> active) but
did not recompute the units, so a unit whose lease is now active and covers today could still read
'reserved'. This recomputes each lease-managed unit from its leases through the same reusable,
guarded helper the runtime uses (edara.unit._sync_occupancy_from_contracts, Phase 10.1.2 hardened it
to skip a unit under maintenance with no current lease rather than attempt the invalid
'available' + 'under_maintenance' write) and writes only where the stored value differs. Idempotent;
touches no lease, date, schedule line or accounting record; owner_occupied / sold units are never
changed."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    units = env['edara.unit'].search([('occupancy_status', 'in', ('available', 'reserved', 'rented'))])
    units._sync_occupancy_from_contracts()
