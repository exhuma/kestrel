# Vulture allowlist — names that frameworks reference in ways vulture's static
# analysis cannot see. Passed to vulture as an extra source file so these count
# as "used". This is ONLY for genuine framework false positives, NOT a
# grandfather list for real dead code: if code is actually unused, delete it
# instead of adding it here.
#
# Runs as: vulture app .vulture_allowlist.py --min-confidence 80

# pydantic-settings invokes Settings.settings_customise_sources(cls,
# settings_cls, ...); `settings_cls` is a required positional in that hook's
# signature even though the body does not use it.
settings_cls
