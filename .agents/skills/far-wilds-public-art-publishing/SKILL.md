---
name: far-wilds-public-art-publishing
description: Prepare and publish owner-selected Into the Far Wilds artwork to its independent public repository, with approved-source selection, derivatives, rights/privacy checks, galleries, and explicit release authorization. Excludes development edits, automatic synchronization, and new artwork generation.
---

# Far Wilds public artwork publishing

Use the owner-authorized public repository `AvinDeMar/IntoTheFarWilds-Public`. It is a separate viewing showcase, not a fork or development mirror. The repository's `docs/PUBLISHING.md` and `scripts/publish_art.py` maintain the procedure and deterministic implementation. Locate its checkout before running commands; do not assume the current directory is the publisher.

An installed discovery copy may have a private `references/local-profile.json` with checkout/source locators. Read it when available; never commit or publish that private profile. Otherwise resolve source/workspace locations from the current request. Keep all private selection, provenance, rights, masters, authorization and audit records outside the public repository.

## Select and prepare

- Establish the requested release scope and source revision. Development sources are read-only: do not change their branches, files, assets, Skills, tracker or migration work. Retrieve only selected images and manifest metadata through a focused Git/Git LFS read.
- Use active approved manifests and original queue ordering. Resolve canonical IDs, exact names, actual selected versions and hashes. A higher-numbered historical candidate is not automatically selected. Preserve source associations; never invent new entries from an old filename.
- Review each selected item's provenance and public-display rights. Record owner authorization and rights evidence privately. Stop an item with unresolved third-party rights; do not infer a license merely from visual approval or a supplied image. Exclude reference photographs, generation prompts/sources, internal documents and source history.
- Build an external selection JSON, then run `prepare`, `seal`, and `verify` from the publishing procedure. Icon derivatives use the exact live crop and 100×80/400×320 outputs; other artwork keeps its natural aspect ratio. Do not creatively modify approved artwork.
- Inspect relevant full previews and native thumbnails on light/dark backgrounds. Check all requested names, IDs/order, versions, links, transparency and derivative hashes. Repeat preparation to prove idempotency. A small update must leave unrelated images unchanged.

## Release authorization and publication

Show the proposed release summary, previews, exact changed files and privacy/rights result before future publication. Obtain explicit owner approval for that release, then bind an external approval receipt to the catalog, allowlist, active IDs and exact change summary. Do not create your own authorization. The initial 201-icon release was expressly preauthorized; that exception does not authorize future releases.

No artwork may be pushed to an unreviewed public branch while waiting for approval: public branches are public. There is no background importer, schedule or private-to-public automatic sync. Automatic Skill discovery does not authorize publication.

Use the publisher's authorized dry run before publishing. Inspect the staged allowlist; fail closed on unexpected files, missing approval, changed hashes or a destination mismatch. Publish only the approved changes to the independent public repository through ordinary Git; never change development-repository visibility or history. Resume a failed push only for the same validated authorized commit.

Deploy Pages manually only within the authorized release. Verify the actual repository, previews, gallery and website from an unauthenticated session. Report exact public commit/release, counts, changes, preservation, rights notice and working public links. Do not claim Pages is live from deployment intent or an authenticated-only view.

For additions or retirements, use explicit IDs and the same review/approval gate. Preserve stable URLs for updates. Explain that retired public artwork can remain in Git history and caches. Only newly requested artwork belongs in a release; empty future categories do not justify generating or publishing new content.
