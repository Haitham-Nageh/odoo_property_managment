"""Preserve legacy branch targets before introducing computed effective columns.

All schema/data validation precedes mutation. A transaction-local snapshot lets
post-migration verify the original values, including physical NULLs and archived
branches. No ORM access is needed before the Phase 1 company columns exist.
"""
import logging
from math import isfinite

_logger = logging.getLogger(__name__)

_NEW_COLUMNS = {
    'sla_response_mode', 'sla_resolution_mode',
    'sla_response_override_hours', 'sla_resolution_override_hours',
    'sla_response_enabled', 'sla_resolution_enabled', 'sla_notifications_enabled',
    'sla_response_source', 'sla_resolution_source',
}


def _validate_legacy_targets(rows):
    invalid = []
    for branch_id, response, resolution in rows:
        for dimension, value in (('response', response), ('resolution', resolution)):
            if value is None:
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or value < 0):
                invalid.append('%s/%s=%r' % (branch_id, dimension, value))
    if invalid:
        raise ValueError('U2 SLA migration: invalid legacy branch/dimension values: '
                         + ', '.join(invalid))


def migrate(cr, version):
    cr.execute("SELECT relkind FROM pg_class WHERE oid = to_regclass('edara_branch')")
    table = cr.fetchone()
    if not table or table[0] != 'r':
        raise ValueError('U2 SLA migration: expected the existing edara_branch table.')
    # Fail on concurrent use rather than validating a dataset that can change
    # between its SELECT and the column rename. A lock does not mutate data.
    cr.execute('LOCK TABLE edara_branch IN ACCESS EXCLUSIVE MODE NOWAIT')
    cr.execute("""
        SELECT attname, format_type(atttypid, atttypmod)
          FROM pg_attribute
         WHERE attrelid = to_regclass('edara_branch')
           AND attnum > 0 AND NOT attisdropped
    """)
    columns = dict(cr.fetchall())
    collisions = sorted(_NEW_COLUMNS.intersection(columns))
    if collisions:
        raise ValueError('U2 SLA migration: colliding or partially migrated columns: '
                         + ', '.join(collisions))
    for name in ('sla_response_hours', 'sla_resolution_hours'):
        if columns.get(name) != 'double precision':
            raise ValueError('U2 SLA migration: expected legacy double precision column %s; got %r.'
                             % (name, columns.get(name)))
    if columns.get('id') != 'integer':
        raise ValueError('U2 SLA migration: expected the branch integer id column.')
    cr.execute("SELECT to_regclass('pg_temp.edara_u2_sla_legacy')")
    if cr.fetchone()[0] is not None:
        raise ValueError('U2 SLA migration: unexpected existing migration snapshot.')
    # No active filter: validate the COMPLETE dataset before any CREATE/ALTER/UPDATE.
    cr.execute('SELECT id, sla_response_hours, sla_resolution_hours FROM edara_branch ORDER BY id')
    rows = cr.fetchall()
    _validate_legacy_targets(rows)

    cr.execute("""
        CREATE TEMPORARY TABLE edara_u2_sla_legacy ON COMMIT DROP AS
        SELECT id, sla_response_hours, sla_resolution_hours FROM edara_branch
    """)
    cr.execute('ALTER TABLE edara_branch RENAME COLUMN sla_response_hours TO sla_response_override_hours')
    cr.execute('ALTER TABLE edara_branch RENAME COLUMN sla_resolution_hours TO sla_resolution_override_hours')
    cr.execute('ALTER TABLE edara_branch ADD COLUMN sla_response_mode varchar')
    cr.execute('ALTER TABLE edara_branch ADD COLUMN sla_resolution_mode varchar')
    cr.execute("""
        UPDATE edara_branch
           SET sla_response_mode = CASE WHEN sla_response_override_hours > 0
                                       THEN 'custom' ELSE 'disabled' END,
               sla_resolution_mode = CASE WHEN sla_resolution_override_hours > 0
                                         THEN 'custom' ELSE 'disabled' END
    """)
    _logger.info('U2 SLA migration: preserved targets and seeded modes for %s branches.', len(rows))
