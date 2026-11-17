# Model output bounds

Ordinary requests specify these output-token ceilings:

| Role | Tokens |
| --- | ---: |
| Anthropic writer | 1,024 |
| Optional Google writer | 1,024 |
| Safety | 2,048 |
| Factual checker | 8,192 |
| Critic | 8,192 |
| Grounded news discovery or claim verification | 8,192 |

Runtime model selection, prompts, reasoning settings, sample counts and retry
budgets are unchanged. The separate experimental shared-check lane keeps its
explicit 4,096-token limit. Finite trials retain their existing limits, prices,
request-size allowance and maximum eight calls; the ordinary check settings
produce the same bounded trial requests as before.

The affected ordinary Google paths retain response usage before requiring one
unblocked, completed textual candidate. A token-limit finish, missing completion
metadata, function call, blocked response or unusable text holds the operation.
Valid-looking JSON does not override that hold. It does not buy a JSON retry or
create a reusable verdict that the underlying weather evidence is bad. A finite
trial becomes terminal and keeps its spent reservations and any earlier stop cause.
Unexpected SDK response-projection errors also hold the trial. Interrupts propagate
after that terminal hold is recorded; they cannot permit a replacement purchase.

Token limits contain individual requests. They do not establish actual billing,
limit grounding-tool charges or enforce an all-provider monthly budget. Existing
news discovery limits remain one grounded request, six verification requests and
three page fetches per operation, including failed attempts. Missing usage and
unknown prices remain unknown.
