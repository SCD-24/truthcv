"""The identity leaf: stdlib-only company and posting-URL identity helpers.

``truthcv.infra.identity.company`` holds company identity keys and name validation;
``truthcv.infra.identity.url`` holds posting URL validation, normalization and dedupe keys.
It is a leaf that imports nothing first-party (stdlib only), so every layer
can depend on it without creating an import cycle.
"""
