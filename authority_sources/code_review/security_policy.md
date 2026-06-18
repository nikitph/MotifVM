# Code Review Security Policy

Version: manual-profile-0.2.5

The review profile flags high-confidence security risks in added diff lines:

- Unconditional authorization allow such as `return True` in auth-sensitive functions.
- Obvious secret literals in added lines.
- `subprocess` calls using `shell=True`.
- `eval` or `exec`.
- Disabled TLS verification.
- SQL queries built with string interpolation.
- Unsafe deserialization APIs such as `pickle.loads` or `yaml.load`.
