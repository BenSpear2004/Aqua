"""Natural-language-to-SQL pipeline: generate SQL with a model, prove it is
a single read-only SELECT, and run it against Sakila.

Kept separate from main.py so the pipeline can be tested without starting
the web server, and so the API layer stays a thin wrapper around it.
"""
