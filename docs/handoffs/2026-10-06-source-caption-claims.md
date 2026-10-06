# Source caption claim coverage

A checker can inventory every fact and source in a draft while omitting the
structural label in a trailing `Data:` caption. The previous capitalized-entity
heuristic rejects that label as an uncovered fact. The new exception is limited
to an exact primary source name and an exact `named_entity` claim at the caption's
start. It removes only the label from the temporary entity scan, preserving offsets.

Recognized captions follow a period or semicolon with horizontal whitespace,
contain a colon and whitespace, and have no following sentence or newline. Only
one caption label is allowed. Quotes (including possessive apostrophes), a label
inside the place/source name, absent context and unknown source identity retain
the stricter behavior. Exact source identity, or its name before literal ` via `
and a nonempty provider, must come from a primary source field. Historical,
related, description and URL fields cannot supply that identity.

The source itself, all detectable numbers/dates/entities and all exact claim
spans remain checked. The actual model verdict remains necessary. A structural
pass is not scientific qualification or posting approval. Both synchronous and
retained-check interpretation receive the evidence they already checked/bound;
no provider request, retry, text transformation or evidence repair is added.
Existing policy identity invalidation applies to the changed source files.

Offline fixtures cover recognized syntax, source/context/claim omissions, wrong
identity, quotes, entity boundaries, invalid dates, explicit checker rejection,
unchanged inputs and the real synchronous/retained parsers. These are invented
parser controls, not model evaluation or proof of source truth, shorter copy,
user preference, lower bills or global coverage. The generated dashboard policy
requires manual deployment after the reviewed commit passes required CI.
