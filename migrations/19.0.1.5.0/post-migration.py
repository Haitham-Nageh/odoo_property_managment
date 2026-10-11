"""Verify preserved inputs, recompute effective SLA fields and update the existing cron."""
from odoo import SUPERUSER_ID, api

_EFFECTIVE_FIELDS = (
    'sla_response_enabled', 'sla_resolution_enabled',
    'sla_response_hours', 'sla_resolution_hours', 'sla_notifications_enabled',
)


def _verify_legacy_preservation(cr):
    cr.execute("SELECT to_regclass('pg_temp.edara_u2_sla_legacy')")
    if cr.fetchone()[0] is None:
        # On a repeat after the upgrade transaction, inputs may have been
        # deliberately edited. Never overwrite them or reconstruct old modes.
        return
    cr.execute("""
        SELECT s.id FROM pg_temp.edara_u2_sla_legacy s
        LEFT JOIN edara_branch b ON b.id = s.id
        WHERE b.id IS NULL
           OR b.sla_response_override_hours IS DISTINCT FROM s.sla_response_hours
           OR b.sla_resolution_override_hours IS DISTINCT FROM s.sla_resolution_hours
           OR b.sla_response_mode IS DISTINCT FROM
              CASE WHEN s.sla_response_hours > 0 THEN 'custom' ELSE 'disabled' END
           OR b.sla_resolution_mode IS DISTINCT FROM
              CASE WHEN s.sla_resolution_hours > 0 THEN 'custom' ELSE 'disabled' END
    """)
    changed = [row[0] for row in cr.fetchall()]
    if changed:
        raise ValueError('U2 SLA migration: legacy targets/modes changed for branches %s.' % changed)


def _verify_effective_values(cr):
    cr.execute("""
        SELECT b.id FROM edara_branch b LEFT JOIN res_company c ON c.id = b.company_id
        WHERE c.id IS NULL
           OR b.sla_response_enabled IS DISTINCT FROM
              CASE b.sla_response_mode WHEN 'custom' THEN true
                   WHEN 'inherit' THEN COALESCE(c.edara_sla_response_enabled, false) ELSE false END
           OR b.sla_resolution_enabled IS DISTINCT FROM
              CASE b.sla_resolution_mode WHEN 'custom' THEN true
                   WHEN 'inherit' THEN COALESCE(c.edara_sla_resolution_enabled, false) ELSE false END
           OR b.sla_response_hours IS DISTINCT FROM
              CASE WHEN b.sla_response_mode = 'custom' THEN b.sla_response_override_hours
                   WHEN b.sla_response_mode = 'inherit' AND c.edara_sla_response_enabled
                   THEN c.edara_sla_response_hours ELSE 0.0 END
           OR b.sla_resolution_hours IS DISTINCT FROM
              CASE WHEN b.sla_resolution_mode = 'custom' THEN b.sla_resolution_override_hours
                   WHEN b.sla_resolution_mode = 'inherit' AND c.edara_sla_resolution_enabled
                   THEN c.edara_sla_resolution_hours ELSE 0.0 END
           OR b.sla_notifications_enabled IS DISTINCT FROM
              COALESCE(c.edara_sla_notifications_enabled, false)
    """)
    inconsistent = [row[0] for row in cr.fetchall()]
    if inconsistent:
        raise ValueError('U2 SLA migration: inconsistent effective values for branches %s.' % inconsistent)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    companies = env['res.company'].with_context(active_test=False).search([])
    companies._check_edara_sla_targets()
    branches = env['edara.branch'].with_context(active_test=False).search([])
    branches._check_sla_configuration()
    _verify_legacy_preservation(cr)
    for name in _EFFECTIVE_FIELDS:
        env.add_to_compute(branches._fields[name], branches)
    branches._recompute_recordset(_EFFECTIVE_FIELDS)
    branches.flush_model(_EFFECTIVE_FIELDS)
    _verify_effective_values(cr)

    cron = env.ref('property_managment.ir_cron_edara_maintenance_sla_notifications',
                   raise_if_not_found=False)
    if (not cron or cron._name != 'ir.cron' or not cron.exists()
            or cron.model_id.model != 'edara.maintenance.request' or cron.state != 'code'
            or (cron.code or '').strip() != 'model._cron_send_sla_notifications()'):
        raise ValueError('U2 SLA migration: missing or unexpected existing SLA notification cron.')
    if cron.interval_number != 1 or cron.interval_type != 'hours':
        # noupdate only governs XML imports. ORM retains native cron locking
        # and changes neither active/nextcall nor the existing execution action.
        cron.write({'interval_number': 1, 'interval_type': 'hours'})
