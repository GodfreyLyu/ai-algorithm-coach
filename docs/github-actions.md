<!-- File purpose: Explain CI checks, owner review, and enforced main branch rules. -->

# GitHub Actions and pull requests

The current release uses Python 3.12 and the standard library.
CI checks the local Skill loop. The planned React and FastAPI UI has no build yet.

## Triggers and names

The [PR workflow](../.github/workflows/pr-checks.yml) is named `Pull request checks`.
It runs for every PR that targets `main`, including fork and draft PRs.
Opening, updating, reopening, editing, or marking a PR ready starts the checks.
It also runs after a push to `main` and supports a manual run.
There are no path filters. A documentation-only PR still runs every job.
A newer run cancels an older run for the same PR or branch.

| Required check name | What it checks |
| --- | --- |
| `Python syntax` | Compile all Python source, tools, Skill scripts, and tests. Parse package, example, and ruleset TOML. |
| `Workflow syntax` | Use actionlint to check workflow structure, expressions, and shell commands. |
| `Logic tests` | Run all unit tests, including transaction, migration, CLI, and standalone bundle tests. |
| `Documentation content` | Check file purposes, function contracts, local links, anchors, fences, and executable public examples. |

Keep these names unique and stable. The main branch rules use the exact job names.
Update the rules and this guide together when a check is renamed.
Every step also has a name that describes its purpose.

## Local checks

Run from the repository root:

```sh
python3.12 -m compileall -q src scripts skills tests
python3.12 -m unittest discover -s tests -v
python3.12 scripts/check_comments.py
python3.12 scripts/check_docs.py
```

Run `actionlint` from the repository root when changing a workflow.
CI downloads actionlint 1.7.12 and verifies its pinned SHA-256 checksum.
GitHub actions use full commit hashes with version comments.
The Python runtime and tests need no third-party Python packages.

Documentation tests run the actual README quick start and both public TOML examples.
They use synthetic records in temporary directories outside the checkout.
The Markdown checker covers root documents, `docs`, `skills`, and `.github`.
It checks inline local links and ATX heading anchors outside code examples.
It checks fenced code blocks. It does not fetch external links or judge every claim.
Changes to prose still need human review.

## Owner approval and merge

[CODEOWNERS](../.github/CODEOWNERS) assigns every file to `@GodfreyLyu`.
This includes the workflow, ruleset definitions, and CODEOWNERS itself.
GitHub reads CODEOWNERS from the PR's base branch.
The file must be present on `main` before code owner review can be enforced.

Two branch rulesets target only `refs/heads/main`:

| Ruleset | Enforced behavior |
| --- | --- |
| `Main quality and owner approval` | Require a PR, one approval, code owner approval, resolved review threads, all four checks, and an up-to-date branch. Block deletion and force pushes. |
| `Main owner merge only` | Restrict branch updates. Only the owner may bypass this update restriction, through a PR. |

The quality ruleset has no bypass actors. Its checks also apply to the owner.
Required status checks must come from the GitHub Actions app, integration ID `15368`.
The merge ruleset uses the owner's user ID `39753221`, not a general admin role.
Its bypass applies only to the update restriction. It cannot bypass quality checks.
Direct pushes to `main` are blocked, including owner pushes.
New reviewable commits dismiss old approvals.

Only the owner's approval satisfies the code owner requirement.
GitHub may still let other users submit reviews. Those reviews do not replace it.
To limit approval buttons in this public repository, enable Settings > Moderation
options > Code review limits > Limit to users explicitly granted read or higher access.
Keep the owner as the only account with explicit repository access for that limit.
Adding collaborators can allow them to submit reviews. They still cannot satisfy
the owner approval requirement or update `main` under these rulesets.

GitHub does not let PR authors approve their own PRs.
Under this strict policy, an owner-authored PR cannot meet the approval requirement.
It stays blocked. There is no automatic owner exemption or approval bot.
Changing that policy requires a separate owner decision.

## Apply and inspect repository rules

The definitions are [quality and approval](../.github/rulesets/main-quality.toml)
and [owner merge](../.github/rulesets/main-owner-merge.toml).
TOML keeps purpose comments and uses only the Python standard library.
Committing these files does not apply GitHub settings.
An authenticated owner must apply them through the repository rules API.
Do not run settings changes from an untrusted PR workflow.

First inspect the live rulesets:

```sh
gh api repos/GodfreyLyu/ai-algorithm-coach/rulesets
```

For a repository with no matching rulesets, create them once:

```sh
python3.12 -c 'import json, pathlib, tomllib; print(json.dumps(tomllib.loads(pathlib.Path(".github/rulesets/main-quality.toml").read_text())))' \
  | gh api --method POST -H 'X-GitHub-Api-Version: 2026-03-10' \
      repos/GodfreyLyu/ai-algorithm-coach/rulesets --input -
python3.12 -c 'import json, pathlib, tomllib; print(json.dumps(tomllib.loads(pathlib.Path(".github/rulesets/main-owner-merge.toml").read_text())))' \
  | gh api --method POST -H 'X-GitHub-Api-Version: 2026-03-10' \
      repos/GodfreyLyu/ai-algorithm-coach/rulesets --input -
```

For an existing ruleset, use `--method PUT` with its observed
`repos/GodfreyLyu/ai-algorithm-coach/rulesets/RULESET_ID` endpoint instead.
Do not create duplicate rulesets or remove unrelated protections.
Read each ruleset back and compare its checks, actors, and enforcement with the file.
Check the effective rules with:

```sh
gh api repos/GodfreyLyu/ai-algorithm-coach/rules/branches/main
```

The live rulesets are [quality and approval](https://github.com/GodfreyLyu/ai-algorithm-coach/rules/27294405)
and [owner merge](https://github.com/GodfreyLyu/ai-algorithm-coach/rules/27294407).
Inspect their current enforcement before relying on a local copy.

Keep the current access model when the repository is renamed or transferred.
Resolve the new owner and app IDs before applying copied settings.

## First rollout and permissions

The workflow starts after its files are pushed to a PR branch.
The first rollout needs CODEOWNERS on `main` to complete owner review enforcement.
Required checks stay pending if the workflow is absent, Actions is disabled,
or a fork workflow is waiting for GitHub approval to run.
There is no deployment, publication, or automatic PR merge in this workflow.

CI grants only `contents: read` to its token and does not persist Git credentials.
It uses `pull_request`, not `pull_request_target`, to test proposed code.
Do not expose repository secrets or private practice data to PR checks.

See GitHub's [workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[code owner rules](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners),
[branch rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets),
[ruleset API](https://docs.github.com/en/rest/repos/rules), and
[review limits](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/managing-pull-request-reviews-in-your-repository).
