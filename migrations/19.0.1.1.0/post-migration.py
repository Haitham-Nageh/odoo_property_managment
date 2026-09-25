"""Phase 10.1: lease `state` values follow the scheduled/active model (state values only - no
accounting, no schedule line, no date is touched).

* active with a future start_date  -> scheduled  (used to be "active but not started")
* renewed but still inside its own term (end_date >= today, the old "renewed at click time"
  behaviour) -> active; the daily job moves it to renewed at its boundary.
Idempotent: a second run finds nothing to change."""


def migrate(cr, version):
    cr.execute("UPDATE edara_lease_contract SET state = 'scheduled' "
               "WHERE state = 'active' AND start_date > CURRENT_DATE")
    cr.execute("UPDATE edara_lease_contract SET state = 'active' "
               "WHERE state = 'renewed' AND end_date >= CURRENT_DATE")
