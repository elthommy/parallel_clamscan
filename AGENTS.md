# AGENTS.md

## Security model

`pclamscan` is a local CLI run by its operator, sometimes as root, to scan
directory trees. There is no network, no server and no authentication.

- **Trusted:** the operator and everything they control: argv (the folders
  list, `--clamscan`, the args after `--`, the `--json-report` path), the
  environment and `PATH`, the ClamAV install and its signature database.
- **Untrusted:** the scanned tree itself: file names, file contents and
  directory layout. They may belong to other local users or come from
  downloaded or uploaded content.
- **Intended:** running an executable chosen by the operator with args chosen
  by the operator.
- **Attackers that matter:**
  1. A local user who owns files inside the scanned tree and wants to hide
     malware from the scan, make the scan touch files outside the requested
     folders, or inject options or paths into clamscan.
  2. A local user on a shared host (e.g. `/tmp`) who goes after the per-batch
     file lists or the JSON report to read or tamper with them, especially
     when the scan runs as root.
- **Out of scope:** malicious ClamAV binaries or signatures, DoS and resource
  exhaustion, and a malicious operator.

A consequence for the code: every path in a batch must end up as exactly one
visible outcome (clean, infected or error). A file that is silently missing
from the results is a security bug, not a cosmetic one.
