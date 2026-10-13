# Delivery process

Use one integrated task tracker and short-lived branches from main. Every
review includes acceptance criteria, tests, manual evidence, risk and gaps.
One peer approval and green required checks are the merge standard; local
verification does not configure GitHub branch protection or grant merge approval.

Local completion means the scoped behavior, authorization, failure handling,
tests, review evidence and documentation are present. Release completion also
requires the maintainer's review, green remote CI and authorized merge or release.
Report these states separately.

Small implementation choices belong in the review description. Cross-cutting
API, schema, dependency or operational changes need an architecture decision.
Remote environment changes require explicit authorization.
