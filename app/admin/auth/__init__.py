"""Admin invitations and account setup (Super Admin 7.2, Admin 1.1).

Admins sign in through the shared `/auth/signin` and `/auth/verify`; the admins' own rules
(a code at every sign-in, 15 idle minutes) are in `app/auth/service.py` and
`app/auth/dependencies.py`.
"""
