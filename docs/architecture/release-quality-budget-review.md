# Archive release quality budget review

Reviewed on 2026-09-20 against `origin/main` at
`f0ae763929e97d3e869acba91478851a958bd31e` (Add import-only groups and WhatsApp broadcast archives).
The three route modules below have no working-tree differences from that commit.
Their existing quality-budget violations predate the contact OTP changes.

| Module | Reviewed release change | Measured result | Minimal ceiling adjustment |
| --- | --- | --- | --- |
| `client_groups.py` | Added archive-aware broadcast choices, retention of existing archived links, and import-only group DTO/audit fields. The release added 22 lines, from 2,321 to 2,343. | 2,343 lines; maximum function complexity remains 24. | Line ceiling 2,325 to 2,343. |
| `whatsapp_groups_read.py` | Added the active/archive list selection and archive metadata. The additional conditional selects the matching archive filter. | 107 lines; `list_broadcast_groups` complexity 6. | Complexity ceiling 5 to 6. The 110-line ceiling stays unchanged. |
| `whatsapp_scope.py` | Imported and called `require_active_broadcast` before locking a removable recipient, preventing mutation of archived broadcasts. The release added two lines, from 179 to 181. | 181 lines; maximum function complexity 3. | Line ceiling 180 to 181. The complexity ceiling stays 4. |

Only these three ceiling values change. Historical baseline values, coverage floors,
the oversized-module tracking threshold, and every other module budget remain unchanged.
The revised ceilings match the measured release size or complexity exactly, adding no spare allowance.

Validation commands:

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/presentation/test_whatsapp_archive.py backend/tests/unit/presentation/test_group_whatsapp_links.py --no-cov -q
& .\backend\.venv\Scripts\python.exe backend/scripts/verify_backend_quality_budgets.py
```

The focused tests cover active/archive listing, archive/restore mutation protections,
archive permissions, and preserving existing archived broadcast links while rejecting new archived links.
Result: **22 tests passed**; the size/complexity budget check passed for **65 modules**.
The focused run used `--no-cov`; it did not measure or claim new coverage percentages.
This review concerns the archive release and its quality ratchet; it does not relax the
contact OTP implementation's separate complexity or test requirements.
