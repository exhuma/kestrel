"""Platform formats for documents: the only place they are parsed or
rendered (constitution Principle VI).

One module per format. Only adapters at a system boundary import this
package — task sources, code hosts, agent backends, persistence and the
HTTP API — which an import-linter contract enforces.
"""
