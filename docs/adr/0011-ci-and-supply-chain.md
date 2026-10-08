# ADR-0011: CI and supply-chain strategy

- Status: accepted
- Date: 2026-10

## Context

The repository is maintained by one person, is public, and runs its own CI, so a compromised
dependency or action executes with the workflow's token. Its output is evidence (numbers and
figures), so a silently wrong result is the failure that matters most. The strategy below is
what is in place on `main`; it is deliberately modest and says what it leaves out.

## Decision

**Keep the workflow's authority small.**
- Workflows run with `contents: read`. Only CodeQL (`security-events: write`) and the Pages
  deployment (`pages: write`, `id-token: write`) are granted more.
- Every third-party action is pinned to a full commit SHA with its release in a comment.
  Dependabot proposes updates for actions, pip dependencies and the Docker base image.

**Make the build prove the claims.**
- Lint (ruff, ruff format, mypy), the test suite on Python 3.11, 3.12 and 3.13 on Linux, and
  on macOS and Windows at 3.13.
- A coverage ratchet with a floor per module, measured by the project's own tracer script
  (constraint S1 keeps `pytest-cov` out). There is no coverage badge, because no live source
  of the number exists.
- Reproducibility jobs: the benchmark and the sweeps run twice and must agree.
- A golden snapshot of the seeded benchmark, with tolerances justified in ADR-0009.
- A build job that installs the wheel in a clean environment and runs the CLI from another
  directory, and a container job that builds the image.

**Release with provenance.** `.github/workflows/release.yml` runs on a version tag
(`vMAJOR.MINOR.PATCH`) and, as a dry run, by hand.
- It checks that the tag, `pyproject.toml`, `navkit.__version__`, `docs/releases/<version>.md`
  (without its DRAFT banner) and a `CHANGELOG.md` section agree (`scripts/check_release.py`). On a
  tag any disagreement fails the run; on a manual run it is only printed.
- It builds the sdist and wheel, installs the wheel in a clean environment and runs the CLI from
  another directory, generates a CycloneDX SBOM, and records SHA-256 checksums.
- On a tag only, a second job, the only one with write permissions, attests the build provenance of
  the sdist and the wheel (`actions/attest-build-provenance`, signed through Sigstore with the
  workflow's identity) and creates a **draft** release with the artifacts, the SBOM, the checksums
  and the versioned notes. Nothing is public until the maintainer publishes it.
- A manual run builds and checks and publishes and attests nothing: an attestation is a public
  record, and a dry run should not leave one for an artifact that is never released.
- The Dockerfile base image is pinned by digest. Dependabot proposes the next digest and the
  container job rebuilds the image to check it.
- `tests/test_supply_chain.py` checks all of the above that is a property of the files: every action
  is pinned to a SHA, the base image to a digest, the release workflow is read-only by default,
  and only the tag-only job can write or attest.

**Look for what the tests cannot see.**
- CodeQL on push, pull request and weekly.
- A security workflow: a secret scan of the tracked files and the whole history (one finding is
  known, rotated and listed with its reason), dependency review on pull requests, `pip-audit`
  of the installed dependencies, and a CycloneDX SBOM of the runtime dependencies.
- A relative-link and anchor check on every pull request, and an external-link check weekly.

**Leave the gates to the repository settings.** The recommended branch-protection settings and
the exact required check names are in CONTRIBUTING; the owner applies them. The checks that
are automated review services, not gates, are not required.

## Consequences

- A pull request that moves a published number fails the golden test, the documentation-table
  check or a reproducibility job, whichever it hits first.
- The macOS and Windows legs found a real platform dependence in the fixture (ADR-0009), which a
  Linux-only build would not have.
- Runners are not identical machines. One series needed a wider tolerance after the same commit
  passed and failed on different runs; the policy for that is in ADR-0009.

## Not done

- **No package is published to PyPI**, and the release is not signed with a maintainer key. The
  provenance attestation says which workflow built the artifact from which commit; it does not say
  a person reviewed it. Verify one with `gh attestation verify <file> --repo Telschow/contested-nav`.
- **The build backend floats.** `pyproject.toml` asks for `hatchling>=1.21`, so two builds of the
  same commit at different times can use different backend versions. The attestation records the
  build, not a reproducible one.
- **The release workflow has not run for a tag.** It has been exercised only as a dry run, which
  cannot test the attest and release steps.
- **No OpenSSF Scorecard or similar external rating.**
- **`uv.lock` is not used by CI.** It is stale and either needs to be adopted or deleted.
- **No branch protection is configured by the repository's own files.** It is a setting.
