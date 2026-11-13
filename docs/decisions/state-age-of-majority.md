# State-based age of majority (11 Nov)

Reverses docs/PLAN.md question 22's 4 Nov decision ("18 everywhere").

## Sources

- Client 1.1, Age Check: sign-up compares the date of birth "with the age of majority for the
  selected state": 18 in most states and Washington, D.C., 19 in Alabama and Nebraska, 21 in
  Mississippi.
- Client 3.1 and 11.1: each state's age of majority decides the age rules (teen or adult).
- The BA's routing document ("Revised Intake Routing", "Answers and Fixes"): the user's state's
  age of majority, "not a flat 18"; the same three exceptions. In Mississippi the teen rules
  run from 13 to 20.

## Design

- `settings.age_of_majority` (18) stays the default; `settings.age_of_majority_by_state`
  (`{"AL": 19, "NE": 19, "MS": 21}`, USPS codes) holds the exceptions. 1.1 says "the
  age-of-majority table can be updated without an app release": it's an environment setting
  (`AGE_OF_MAJORITY_BY_STATE`, JSON), so it changes without a mobile or web release. Not in
  `.env.example` (the old `age_of_majority` wasn't either, and that file is being edited for
  Stripe now).
- `app/core/ages.py`: `age_of_majority(state)`, `is_adult(dob, state)`, `age_group(dob,
  state)` and `adult_on(dob, state)`. `state` is a required argument so no caller can forget
  it. Still counted on Hawaii's date.
- `Profile.majority_state` (a property, no column): the state that counts for a profile, read
  from its account through the session's identity map. Used where only the profile is at hand
  (visits, guidance, wellness, health routing, the safety check, the intake's Teen Profile
  Choice). Where the account is already loaded, callers pass `account.state` directly.
- `accounts.service.age_of_majority_in` and `adult_in` now use the table, so 11.1's teen-rules
  message shows the real age ("In Mississippi, the age of majority is 21. …"). 1.1's under-age
  message is unchanged.
- Admin audit log's role filter (client or teen) is SQL: a `CASE` on `users.state` gives each
  state's cut-off date of birth.
- The daily 1.6 age check's rough SQL filter uses the youngest age in the table (18), so no
  teen is missed; each teen is then checked against their own state, and the two-week reminder
  is two weeks before their own state's age.

## Whose state counts

- The client's own profile: `users.state`.
- A teen with their own account (1.5, 1.6): the teen's own `users.state`. At invite acceptance
  and at Create My Account, the state the teen types decides, as before.
- A family member: the account holder's `users.state`. **Assumption** (the stories don't say;
  a managed family member has no state of their own). This also decides whether the parent
  sees the Teen Profile Choice; at acceptance the teen's own state is checked again.
- An unknown or missing state: 18 (the default).

## Messages not in the stories

- Intake, Teen Profile Choice for someone not in the teen band (existing message, now with the
  real age): "This question is only for family members aged 13 to [age − 1]."

## Open questions for the BA (also in PLAN question 22)

1. A family member has no state: is the account holder's state right?
2. The routing document says the state comes "from billing address"; we use the state from
   sign-up, edited in 11.1. Should billing's address override it?
3. A state change in 11.1 can also move managed family members across the line (they follow
   the holder's state); 11.1's confirmation only speaks of the client. Is that intended?

No schema change and no migration needed.
