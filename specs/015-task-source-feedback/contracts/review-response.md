# Contract: External Review Response

Every Kestrel review request contains an active opaque token and one sentence
explaining that a marked reply, or marked task comment containing that token,
can approve, reject, or request changes.

Kestrel classifies a claimed response as `approve`, `reject`,
`request_changes`, or `unclear`. Only a response matching the active token may
resolve the gate. An unclear response receives one concise clarification reply.

After requested changes, Kestrel replies with only added, removed, and changed
items plus a reference to the canonical artifact. It does not repeat the full
artifact in that reply.
