"""API-backed job feeds: boards TruthCV pulls postings from instead of searching.

A feed differs from every other job board in the catalog in that TruthCV, not
the agent, does the discovery: the operator saves an API key, the app calls the
board's API with each enabled profile's criteria, and the agent receives the
resulting postings as concrete URLs in its run prompt. There is no browser
sign-in and no Google dork for these boards.

This package is a leaf on the data path: it imports agentconfig.store for the
profile shape and secretstore for the key, and nothing imports it but api/.
"""
