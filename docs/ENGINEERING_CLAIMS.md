# Engineering claims and accountable review

Owner: repository maintainer (Nipun / Cyphire2025). Review deadline: 2026-12-25.

`engineering-claims.json` is the machine-checked register. CI rejects missing owners, expired reviews, unsupported status labels, missing evidence and changed evidence fingerprints. Refreshing a date or hash requires a substantive review of the underlying result and scope; it is not a substitute for rerunning a changed control.

| Claim | Evidence status and boundary |
| --- | --- |
| Reproducible backend developer tooling | Locally verified clean Windows and Linux installs of the hashed runtime/developer tool lock. CPython 3.11 is the supported line. Native-app toolchains and arbitrary OS distributions are outside this claim. |
| Database process capacity guard | Locally verified deployment arithmetic, replica/surge rejection and 64 simultaneous PostgreSQL sessions for an approved configuration. This does not establish throughput, availability or the VPS workload capacity. |
| Time-bounded dependency exception | Scoped review of the actual Apple verifier import closure and exact installed dependency sources. The vulnerable transitive dependency remains present; arbitrary dynamic Python reachability is not formally proved. |
| Signed immutable production promotion | Implemented and tested for refusal/identity/checksum handling. Actual GitHub issuance, protected-environment approval, registry retention and a production promotion are not yet verified. Production activation fails without the required signatures. |
| Enterprise-grade availability or compliance | Not claimed. A single VPS does not establish high availability, and source controls do not establish organizational/compliance processes. |
| Production alert delivery and off-host disaster recovery | Explicitly deferred by the user. Synthetic fault and restore receipts do not establish actual recipients, off-host backup placement, successful VPS restore or PITR. |

Documented architecture is a design description, not a guarantee of perfect dependency inversion. ORM use does not establish absence of injection in all entry points. Environment variables do not establish complete secrets management. Test coverage percentages apply only to their recorded files, revision and measurement method. Public-facing assurances must name the evidence scope and the limitations above.
