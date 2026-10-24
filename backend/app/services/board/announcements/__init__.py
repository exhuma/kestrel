"""What kestrel says on the ticket (feature 046, User Story 2).

``gates.py`` and ``status.py`` build each announcement as a
:class:`~app.documents.Document` from constructs, never from a platform's
syntax; ``common.py`` holds the parts they share; ``service.py`` decides
when to say what, and posts it through the projection ledger.
"""
