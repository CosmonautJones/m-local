# Temporary test host proposal

Status: proposal only. No machine, purchase or account change is authorized by
this document. An existing qualified, isolated host can be used instead.

The actual GitHub package job stopped at qualification: four available CPUs,
16,766,414,848 raw memory bytes, below the frozen 17,179,869,184-byte floor.
No package checkout, artifact retrieval, provisioning or native build ran.
This personal public repository has no registered self-hosted runners.

One candidate is a DigitalOcean CPU-Optimized Droplet with Ubuntu 24.04 x64,
32 GiB RAM, 16 dedicated vCPUs and 200 GiB SSD. Its published rate checked on
October 6, 2026 is $0.50/hour: six hours of compute is $3.00 before tax.
See [official pricing](https://www.digitalocean.com/pricing/droplets).
The extra disk leaves room for the required fresh 64 GiB image and 20 GiB
reserve. Actual memory, CPU, free space and host controls still need checking.

Proposed authorization would cover one disposable test host with a $5 total
spending cap and no automatic extension. It would use the reviewed public
inputs and private loopback fixtures, print sanitized evidence, then destroy
the host and confirm its removal. It would add no backups, snapshots or
separate storage. Provider availability, price and billing terms must be
rechecked before creating it; the published calculation is an estimate.

Provisioning is not ready merely because hardware meets the specification.
The host must supply the required trusted system utilities, Git and GitHub
CLI. No unpinned or apt installation is permitted by the frozen build plan.
Any missing tool requires an independently reviewed, hash-bound preparation
plan before the machine is rented or the runtime is executed.

The current package workflow uses GitHub's standard Ubuntu runner. A chosen
qualified host needs a reviewed execution connection before the native run.
No cloud credentials, runner token or private cache belongs in this repository.
