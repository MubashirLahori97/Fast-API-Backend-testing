# Admin user stories

Admin section of *Genesis Health/The Oracle - User Stories* (BA: Atiya Abid), synced from https://docs.google.com/document/d/1u94uQ0yDgEwk5TF1tu9VB97aF9NtCG7pdAm-MYp9NVs/edit by `scripts/sync_user_stories.py`. Do not edit by hand: changes are overwritten on the next sync. Out of scope for the backend for now (see `docs/PLAN.md`).

## 1. Epic: Login Module
### 1.1 - Accept Invitation & Set Password - (24-hour Invite Expiry)
## Requirement Statement:
As an Admin, I want to accept my invitation and set my password, so that I can securely access the admin panel.
### Specifications:
Story Details:
- Receiving the Invitation
  - The Super Admin invites the Admin from Admin Management (see Super Admin story 7.2).
  - The Admin receives an email with a Set up your account link.
- Invite Link
  - The link is valid for 24 hours, and can be used once.
  - It stops working once it’s used, when the Super Admin sends a new invite, or when the invite is cancelled (see Super Admin story 7.1).
- Account Setup Screen
  - The link opens a setup screen, which shall include:
    - first name and last name (filled in from the invite, can’t be changed)
    - email address (filled in from the invite, can’t be changed)
    - Password field, masked, with a Show / Hide icon (Mandatory)
    - Confirm Password field, masked, with a Show / Hide icon (Mandatory)
    - Set up account button
  - The password must follow the password rules:
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
    - At least 1 special character
- Email Verification
  - After setting the password, the Admin verifies their email with a 6-digit code:
    - valid for 10 minutes, and can be used once
    - stops working after 5 wrong attempts
    - can be resent after 60 seconds
- Once Set Up
  - The Admin’s status changes to Active, and the Super Admin is notified (see Super Admin story 11.1).
  - The Admin is taken to the Sign In screen, and signs in with their email, password and a verification code (see story 1.2).
- Logging
  - The invite being accepted, and the account being set up, are recorded in the audit logs.
Acceptance Criteria:
- Invite email: Given the Super Admin sends an invite, when it’s sent, then the Admin receives an email with the Set up your account link.
- Valid link: Given the Admin opens the link within 24 hours, when it loads, then the setup screen opens, with their name and email filled in and locked.
- Expired or used link: Given more than 24 hours have passed, or the link has been used or cancelled, when the Admin opens it, then it no longer works.
- Password rules: Given the password doesn’t follow the rules, or the passwords don’t match, when the Admin selects Set up account, then an error is shown, and the account isn’t set up.
- Verification: Given a valid password, when the Admin enters the correct code within 10 minutes, then their email is verified.
- Active: Given the code is verified, when setup completes, then the Admin is Active, the Super Admin is notified, and the Admin is taken to Sign In.
- Logging: Given the account is set up, when it completes, then it’s recorded in the audit logs.
Alternate Scenario:
- Invite link expired
  - The Admin sees a message, and asks the Super Admin to send a new one.
- Invite cancelled
  - The link stops working.
- Passwords don’t match, or don’t follow the rules
  - An error is shown, and the Admin stays on the setup screen.
- Code incorrect or expired
  - The Admin can request a new code after 60 seconds.
- Admin closes the page before finishing
  - They can use the same link again, if it’s still within 24 hours and hasn’t been used.
Non-functional Requirements:
- Invite links are unique, single use, and expire after 24 hours.
- Passwords are securely encrypted, and never stored in plain text.
- Verification codes should arrive by email within 2 minutes.
- Every action is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- Invite link expired or invalid: “This invite has expired. Please ask the Super Admin to send a new one.”
- Password empty: “Please create a password.”
- Password doesn’t meet the rules: “Your password needs at least 8 characters, including an uppercase letter, a lowercase letter, a number and a special character.”
- Passwords don’t match: “The passwords don’t match.”
- Wrong code: “That code doesn’t match. Please check your email and try again.”
- Code expired, or too many attempts: “This code has expired. Please request a new one.”
- Account set up: “Your account is ready. Please sign in.”
### 1.2 - Sign In with 2FA
## Requirement Statement:
As an Admin, I want to securely sign in using my email, password and a verification code, so that I can access the admin panel.
### Specifications:
Story Details:
- Admin Accounts
  - Admin accounts are created by invitation from the Super Admin (see Super Admin story 7.2).
  - The Admin must set up their account from the invite link before they can sign in (see story 1.1).
- Sign In Screen
  - The Sign In screen shall include:
    - Email field (Mandatory)
    - Password field, masked (Mandatory), with a Show / Hide icon
    - Sign In button
    - Forget Password link (see story 1.3)
- Sign In Validation
  - The platform shall:
    - Validate the email format (example@domain.com)
    - Check the email and password together, and show one general error if either is wrong, without saying which one
    - Lock the account temporarily after 3 failed attempts in a row
    - Check the account has been set up, and isn’t deactivated
- Two-Step Verification (Every Sign-In)
  - After the email and password are checked, the platform shall send a 6-digit code to the Admin’s email, at every sign-in, because Admins can see Clients’ account information.
  - The code:
    - is valid for 10 minutes, and can be used once
    - stops working after 5 wrong attempts
    - can be resent after 60 seconds
  - The Verification screen shall include:
    - Verification Code field (Mandatory)
    - Verify button
    - Resend code link
- After Signing In
  - The Admin is taken to the Dashboard (see story 2.1).
  - The Super Admin-only areas aren’t shown:
    - Admin Management
    - Subscription & Billing
    - subscription and free trial metrics, and Content to review, on the Dashboard
- Session Management
  - The Admin is signed out after 15 minutes of inactivity.
  - Signing in again always needs a new verification code.
  - If the Super Admin deactivates the Admin while they’re signed in, they’re signed out straight away (see Super Admin story 7.1).
- Logging
  - Every sign-in attempt, successful or failed, is recorded in the audit logs.
Acceptance Criteria:
- Successful sign-in: Given an active Admin enters a valid email and password, when they enter the emailed code, then they’re taken to the Dashboard.
- 2FA every time: Given any sign-in, when the email and password are valid, then a verification code is always required, on every device.
- Invalid credentials: Given the email or password is wrong, when the Admin selects Sign In, then one general error is shown, without saying which field is wrong.
- Required fields: Given the email or password is empty, when the Admin selects Sign In, then a required-field error appears against that field.
- Show password: Given the Admin selects the eye icon, when it’s toggled, then the password switches between masked and visible.
- Code rules: Given a code is sent, when it’s used after 10 minutes, used twice, or entered wrongly 5 times, then it no longer works.
- Account lock: Given 3 failed attempts in a row, when the Admin tries again, then the account is temporarily locked, and they’re directed to Forget Password.
- Account not set up: Given an Admin hasn’t set up their account yet, when they try to sign in, then they’re asked to use the link in their invite email first.
- Deactivated Admin: Given an Admin has been deactivated, when they try to sign in, then they can’t, and see the deactivated message.
- Admin view: Given an Admin signs in, when the admin panel opens, then the Super Admin-only areas aren’t shown.
- Inactivity: Given the Admin is inactive for 15 minutes, when the time passes, then they’re signed out.
- Logging: Given any sign-in attempt, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- Incorrect email or password
  - A general error is shown, and the attempt counts towards the lock.
- Code incorrect or expired
  - The Admin stays on the Verification screen, and can request a new code after 60 seconds.
- 3 failed attempts
  - The account is temporarily locked, and the Admin is directed to Forget Password (see story 1.3).
- Account not set up
  - The Admin is asked to use their invite link. If it has expired, they ask the Super Admin to send a new one.
- Admin was deactivated while signed in
  - They’re signed out straight away, and can’t sign in again.
- Admin reactivated
  - They sign in with their existing password and a new verification code.
- Signed out after inactivity
  - The Admin signs in again, with a new code.
Non-functional Requirements:
- Passwords must be securely encrypted, and never stored in plain text.
- Authentication responses should complete within 3 seconds.
- Verification codes should arrive by email within 2 minutes.
- Admin permissions are checked at every sign-in, and enforced by the system, not only hidden on screen.
- Authentication logs must be retained for at least six years.
- The sign-in flow must follow OWASP authentication best practices.
Validation Rules/Errors:
- Email empty: “Email is required.”
- Invalid email format: “Please enter a valid email address.”
- Password empty: “Password is required.”
- Email or password incorrect: “Incorrect email or password. Please try again.”
- Code empty: “Please enter the verification code sent to your email.”
- Code incorrect: “That code doesn’t match. Please check your email and try again.”
- Code expired, or too many attempts: “This code has expired. Please request a new one.”
- Account locked: “Your account has been temporarily locked after too many attempts. Please reset your password to continue.”
- Account not set up: “Please set up your account using the link in your invite email.”
- Deactivated: “Your account has been deactivated. Please contact the Super Admin.”
- Signed out after inactivity: “You’ve been signed out after 15 minutes of inactivity. Please sign in again.”
### 1.3 - Forget Password
## Requirement Statement:
As an Admin, I want to reset my password if I forget it, so that I can securely regain access to my account.
### Specifications:
Story Details:
- Forget Password Screen
  - The Admin opens it from the Forget Password link on the Sign In screen (see story 1.2).
  - The screen shall include:
    - Email field (Mandatory)
    - Send Reset Link button
    - Back to Sign In link
- Sending the Reset Link
  - The Admin enters their email and selects Send Reset Link.
  - The platform shall:
    - Validate the email format (example@domain.com)
    - Send a reset link only if the email belongs to an active Admin account that has been set up
    - Show the same message whatever the result, so nobody can find out which emails have an account
  - No link is sent if the account:
    - hasn’t been set up from the invite yet (see story 1.1)
    - has been deactivated (see Super Admin story 7.1)
- Reset Link
  - The link is valid for 60 minutes, and can be used once.
  - It stops working once it’s used, once the password is changed, or when a newer link is requested.
- Reset Password Screen
  - The link opens a screen that shall include:
    - New Password field, masked, with a Show / Hide icon (Mandatory)
    - Confirm New Password field, masked, with a Show / Hide icon (Mandatory)
    - Password strength indicator
    - Reset Password button
  - The new password must follow the password rules:
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
    - At least 1 special character
  - The new password can’t be the same as the current password.
- After the Password Is Reset
  - The Admin is signed out of any open sessions.
  - A temporary lock from failed sign-in attempts is removed.
  - The Admin receives an email confirming the password was changed.
  - They’re taken to the Sign In screen, and sign in with the new password and a verification code (see story 1.2).
- Logging
  - Every reset request and password change is recorded in the audit logs.
Acceptance Criteria:
- Reset requested: Given the Admin enters a valid email, when they select Send Reset Link, then the same confirmation message is shown, whether or not a link is sent.
- Reset email: Given the email belongs to an active Admin account that has been set up, when the reset is requested, then a reset link is sent to it.
- No link for inactive accounts: Given the account hasn’t been set up, or has been deactivated, when the reset is requested, then no link is sent.
- Link expiry: Given more than 60 minutes have passed, or the link has been used, when the Admin opens it, then the link no longer works.
- Newer link: Given the Admin requests a new link, when it’s sent, then any earlier link stops working.
- Password rules: Given the new password doesn’t follow the rules, or matches the current password, when the Admin selects Reset Password, then an error is shown.
- Matching: Given the new password and confirmation don’t match, when the Admin selects Reset Password, then an error is shown.
- Successful reset: Given a valid new password, when the Admin selects Reset Password, then the password is changed, open sessions end, any lock is removed, a confirmation email is sent, and they’re taken to Sign In.
- Next sign-in: Given the password has been reset, when the Admin signs in, then a verification code is required.
- Logging: Given a reset is requested or completed, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- Email not registered
  - The same confirmation message is shown, and no email is sent.
- Account not set up yet
  - No link is sent. The Admin uses their invite link instead (see story 1.1).
- Account deactivated
  - No link is sent. The Admin contacts the Super Admin.
- Link expired or already used
  - The Admin sees a message, and requests a new link.
- Passwords don’t match
  - The Admin stays on the Reset Password screen, and sees an error.
- Same as the current password
  - The Admin is asked to choose a different password.
- Account was locked
  - The Admin resets their password, and the lock is removed.
Non-functional Requirements:
- Reset links must be unique, single use and time-limited.
- Reset emails should arrive within 2 minutes.
- Passwords must be securely encrypted, and never stored in plain text.
- All reset events must be recorded in the audit logs, and retained for at least six years.
- The reset flow must follow OWASP authentication best practices.
Validation Rules/Errors:
- Email empty: “Email is required.”
- Invalid email format: “Please enter a valid email address.”
- Reset requested: “If an account exists for this email, we’ve sent a link to reset your password.”
- Link expired or already used: “This link has expired. Please request a new one.”
- New password empty: “Please enter a new password.”
- Password doesn’t meet the rules: “Your password needs at least 8 characters, including an uppercase letter, a lowercase letter, a number and a special character.”
- Passwords don’t match: “The passwords don’t match.”
- Same as the current password: “Please choose a password you haven’t used before.”
- Password reset: “Your password has been reset. Please sign in.”
## 2. Epic: Dashboard Module
### 2.1 - Dashboard & Analytics
## Requirement Statement:
As an Admin, I want to view items needing attention along with platform-wide KPIs and analytics, so that I can act quickly on open cases and keep track of how the platform is used.
### Specifications:
Story Details:
- Dashboard Entry
  - The Dashboard is the first screen the Admin sees after signing in (see story 1.2).
- Global Date Range Filter
  - A calendar date picker that applies to all KPI cards and graphs.
  - Supports a custom date range, as well as weekly, monthly and yearly views.
  - The Needs Attention strip always shows what’s open now, whatever the date range.
- Needs Attention Strip (at the top, real-time counts)
  - Escalations: escalations not yet reviewed, by level (Emergency, Crisis, Urgent). Links to Escalation Management (see story 4.1).
    - The team doesn’t follow up with Clients about escalations, so there’s no overdue count (Session 9).
  - Support Requests: open requests, by type: Talk to Support Team, Consultation Request, Knowledge Gap and Email Change Request. Links to Support Request Management (see story 5.1).
  - Deletion Requests: requests past their grace period and waiting for review, with the number close to their 45-day deadline. Links to Deletion Requests (see story 5.2).
  - Knowledge Gaps: new knowledge gaps, which Admins can answer for the Super Admin’s approval. Links to Knowledge Gaps (see story 6.3).
  - Content waiting for the Super Admin’s approval isn’t shown, because only the Super Admin can approve it.
- KPI Cards (real-time numbers, for the selected date range)
  - Total Registered Clients: all Clients with their own account on the platform.
  - Active Clients: Clients who used the platform within the date range.
  - Total Conversations: conversations held with the Oracle.
  - Escalations: escalations within the date range, and how many are not yet reviewed.
  - Teen Accounts: teens with their own account, split into:
    - Joined: the teen has set up their account
    - Invite sent: waiting for the teen to sign up
    - Access paused: the parent’s Family plan or consent isn’t active
- Graphs
  - Client Growth Over Time (Session 4): line graph of registered Clients over the date range.
  - Conversations Over Time (Session 4): bar graph of Oracle conversations, by week or month.
  - Top Health Topics (Session 4): horizontal bar graph of the health topics Clients ask about most, highest first.
  - Escalation Status Breakdown (Session 4): donut chart of escalations by status (Not yet reviewed, Reviewed), and by level (Emergency, Crisis, Urgent).
  - Teen Accounts Over Time: line graph of teens with their own account (Joined) over the date range.
- Not Shown to Admins
  - the Active Subscribers and Free Trial KPI cards
  - the Subscribers Over Time graph
  - content waiting for approval
- Privacy
  - The Dashboard shows only totals and trends. No Client’s or teen’s name, conversation or health information appears on it.
Acceptance Criteria:
- Dashboard shown: Given the Admin signs in, when the Dashboard opens, then it shows the Needs Attention strip, the KPI cards and the graphs available to Admins.
- Session 4 items: Given the Dashboard, when it loads, then it includes Total Registered Clients, Active Clients, Total Conversations and Escalations, and the Client Growth, Conversations Over Time, Top Health Topics and Escalation Status Breakdown graphs.
- Needs Attention: Given open items exist, when the Dashboard loads, then it shows escalations not yet reviewed (by level), open support requests (by type), pending deletion requests (with those close to the deadline) and new knowledge gaps.
- Links: Given the Admin selects an item in Needs Attention, when it’s clicked, then the matching management screen opens.
- No overdue count: Given escalations are shown, when the strip loads, then there’s no overdue count.
- Teen accounts: Given teens with their own account exist, when the Dashboard loads, then the Teen Accounts card shows how many have joined, how many invites are pending, and how many are paused, and the graph shows joined teen accounts over time.
- Super Admin-only items hidden: Given an Admin opens the Dashboard, when it loads, then the subscription and free trial metrics, and content waiting for approval, aren’t shown.
- Date range: Given the Admin changes the date range, when it’s applied, then every KPI card and graph updates. The Needs Attention strip stays on what’s open now.
- Accuracy: Given any KPI or graph, when it’s shown, then it matches the platform data for the date range.
- Real time: Given new activity happens, when the Dashboard is open, then the counts, numbers and graphs update without signing out and back in.
- Topics: Given the Top Health Topics graph, when it’s shown, then topics appear highest first.
- Privacy: Given the Dashboard, when it’s shown, then no Client’s or teen’s personal or health information appears on it.
Alternate Scenario:
- No data for the date range
  - KPI cards show zero, and graphs show an empty state.
- New platform with little activity
  - KPI cards and graphs show zero or empty states until data is available.
- No teen accounts yet
  - The Teen Accounts card shows zero.
- Nothing needs attention
  - The Needs Attention strip shows all clear.
- Date range changed
  - All KPI cards and graphs update to the new range.
- Data can’t load
  - An error is shown, and the Admin can try again.
Non-functional Requirements:
- The Dashboard should load within 3 seconds.
- Counts, KPIs and graphs update in real time.
- Analytics use totals only, and never expose an individual Client’s or teen’s information.
- Subscription and free trial metrics are never sent to an Admin’s screen, not only hidden.
- The layout works on desktop browsers used for the admin panel.
Validation Rules/Errors:
- No data for the date range: “There’s no data for this date range.”
- Nothing needs attention: “You’re all caught up.”
- Data couldn’t load: “We couldn’t load the dashboard. Please try again.”
## 3. Epic: Client Management
### 3.1 - View Client (Listings & Details)
## Requirement Statement:
As an Admin, I want to view and manage Client accounts, so that I can support Clients and keep their account details accurate.
### Specifications:
Story Details:
- Client Listing
  - The Admin opens Client Management from the main navigation.
  - The listing shall show each account with:
    - first name and email address (no last name or phone number is collected, Session 9)
    - state
    - account type: Adult or Teen (own account, linked to the parent)
    - status: Trial, Active, Payment issue, Cancelled, Consent revoked, Deactivated, Scheduled for deletion (during the 10-day grace period) and Being deleted (after the grace period, until the deletion is complete)
    - number of family members (adults only)
    - sign-up date and last active date
  - The newest accounts are shown first.
- Search and Filter
  - Search: by first name or email address.
  - Filter: by account type, status, state and sign-up date.
- Client Details
  - Selecting an account opens the Client Details screen, which shall show:
    - Account: first name, email address,state, ZIP code account type and sign-up date
    - Consent: the versions of the Terms of Service, Privacy Policy and Health Consent accepted, and when; or “Consent revoked”
    - Family members:
      - managed family members, with first name, relationship and age
      - invited teens, with their status (Invite sent, Joined, Turned off or Access paused)
    - Teen account: the parent’s account it’s linked to, and whether access is active or paused
    - Activity: last active date, number of conversations, and any open support, deletion or escalation requests, with links to them
    - Health Information: includes health information only which would get updated as the user converse with the Oracle.
    - Actions: Change email address, and Deactivate or Reactivate (see story 3.2)
  - Not shown to Admins: the Client’s plan and subscription details.
  - Privacy: Client Details doesn’t show conversations, guidance summaries, provider notes or health profile answers.
- Changing a Client’s Email Address
  - Used when a Client has sent an Email Change Request (see story 5.1).
  - The Admin selects Change email address, enters the new address the Client asked for, and confirms.
  - Once changed:
    - the Client is notified at both their old and new addresses
    - they’re signed out on all devices, and their trusted devices are cleared
    - they complete two-step verification at their next sign-in (see Client story 11.1)
  - The related Email Change Request is marked resolved.
- Logging
  - Every view of Client Details, and every email change, is recorded in the audit logs, with who did it and when.
Acceptance Criteria:
- Listing: Given the Admin opens Client Management, when it loads, then each account shows its first name, email, state, account type, status, family member count, sign-up date and last active date, newest first.
- Search: Given the Admin searches by first name or email, when results load, then only matching accounts are shown.
- Filter: Given the Admin applies filters, when they’re applied, then only accounts matching every filter are shown.
- Details: Given the Admin selects an account, when Client Details opens, then it shows the account, consent, family members, teen link, activity and actions.
- No subscription details: Given an Admin opens Client Management, when it loads, then no plan or subscription details are shown.
- Health profile: Given the Admin opens Client Details, when it loads, then the health profile is shown read-only, including for teens with their own account.
- Teen link: Given a teen account, when its details are shown, then the linked parent account and the teen’s access status are shown.
- Change email: Given an Email Change Request, when the Admin changes the email, then the Client is notified at both addresses, signed out on all devices, their trusted devices are cleared, and the request is marked resolved.
- Logging: Given a Client Details view or an email change, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- No accounts match the search or filters
  - An empty state is shown.
- New email already in use
  - An error is shown, and the email isn’t changed.
- Account scheduled for deletion, or being deleted
  - It shows its status, with a link to the request (see story 5.2).
- Account is deactivated
  - It shows “Deactivated”, with the Reactivate option (see story 3.2).
- Action fails
  - The Admin can try again.
Non-functional Requirements:
- The listing should load within 3 seconds, and search results within 1 second.
- Subscription details are never sent to an Admin’s screen, not only hidden.
- Client Details shows only what’s needed to support the account, including the health information.
- Every view and email change is recorded in the audit logs, and retained for six years.
- All Client data is stored in the HIPAA-compliant cloud (Azure).
Validation Rules/Errors:
- No results: “No clients match your search.”
- New email invalid: “Please enter a valid email address.”
- New email already in use: “An account with this email address already exists.”
- Change email confirmation: “Change [First name]’s email address to [new email]? They’ll be signed out and asked to verify their new address.”
- Email changed: “[First name]’s email address has been changed.”
- Action failed: “We couldn’t do that just now. Please try again.”
### 3.2 - Deactivate / Reactivate Client
## Requirement Statement:
As an Admin, I want to deactivate or reactivate a Client’s account, so that I can control who can access the platform while keeping their information.
### Specifications:
Story Details:
- Where to Deactivate or Reactivate
  - From the Client Details screen (see story 3.1).
- Deactivating an Account
  - The Admin selects Deactivate, and a confirmation opens, with:
    - a Reason field (Mandatory)
    - Deactivate and Cancel buttons
  - Once confirmed:
    - the Client is signed out on all devices, and can’t sign in
    - when they try, they see: “Your account has been deactivated. Please contact the support team for help.” (see Client story 1.2)
    - their information is kept. Nothing is deleted.
    - their notifications stop
    - the account status shows Deactivated in the listing
- Parents With Invited Teens
  - Deactivating a parent also pauses their invited teens’ access. The teens see: “Your access is paused. Please ask your parent or guardian.”
  - The confirmation shows how many teen accounts will be affected.
- Deactivating a Teen Account
  - The teen can’t sign in. The parent’s account isn’t affected, and the parent isn’t told what happened.
- Reactivating an Account
  - The Admin selects Reactivate, and confirms.
  - The Client can sign in again, with all their information intact. Their notifications restart.
  - For a parent: their invited teens’ access is restored, if their Family plan and consent are still active.
- Subscription
  - Deactivating doesn’t cancel the Client’s subscription. Billing is managed separately (see Client story 11.3).
- Logging
  - Every deactivation and reactivation is recorded in the audit logs, with who did it, when, and the reason.
Acceptance Criteria:
- Deactivate: Given the Admin selects Deactivate and enters a reason, when they confirm, then the Client is signed out on all devices, can’t sign in, and their information is kept.
- Reason required: Given the reason is empty, when the Admin tries to confirm, then they can’t.
- Message to the Client: Given a deactivated Client tries to sign in, when they do, then they see the deactivated message.
- Parent with teens: Given the Admin deactivates a parent with invited teens, when they confirm, then the teens’ access is paused, and the confirmation showed how many were affected.
- Teen account: Given the Admin deactivates a teen account, when they confirm, then the teen can’t sign in, and the parent’s account isn’t affected.
- Reactivate: Given a deactivated account, when the Admin reactivates it, then the Client can sign in again, with all information intact. A parent’s invited teens get their access back.
- Status: Given an account is deactivated or reactivated, when the listing loads, then its status shows correctly.
- Logging: Given any deactivation or reactivation, when it happens, then it’s recorded in the audit logs with the reason.
Alternate Scenario:
- Admin cancels
  - Nothing changes.
- Client is signed in when deactivated
  - They’re signed out straight away.
- Parent reactivated, but the Family plan has ended
  - The parent’s access returns, but their invited teens stay paused until the Family plan is active again.
- Account has a pending deletion request
  - It can still be deactivated, and the deletion continues as normal (see story 5.2).
- Action fails
  - The Admin can try again.
Non-functional Requirements:
- Deactivation takes effect straight away, on every device.
- Deactivating never deletes any information.
- Every action is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- Deactivate confirmation: “Deactivate [First name]’s account? They won’t be able to sign in until it’s reactivated. Their information will be kept.”
- Parent with invited teens: “This will also pause access for [number] teen account(s) linked to this account.”
- Reason left empty: “Please add a reason for deactivating this account.”
- Reactivate confirmation: “Reactivate [First name]’s account? They’ll be able to sign in again.”
- Deactivated: “[First name]’s account has been deactivated.”
- Reactivated: “[First name]’s account has been reactivated.”
- Action failed: “We couldn’t do that just now. Please try again.”
## 4. Epic: Escalations Management
### 4.1 - Manage Escalations
## Requirement Statement:
As an Admin, I want to review the escalations the Oracle has recorded, so that I can check how emergencies, crises and urgent concerns were handled, and spot false alarms.
### Specifications:
Story Details:
- How Escalations Work
  - The support team doesn’t contact or follow up with Clients about escalations: “nobody’s making sure you went” (see Client story 3.2).
  - Escalations are recorded for review only. There’s no overdue flag, 24-hour check-in, or option to contact the Client.
- Escalation Listing
  - The Admin opens Escalation Management from the main navigation, or the Needs Attention strip on the Dashboard (see story 2.1).
  - The listing shall show each escalation with:
    - level: Emergency, Crisis or Urgent
    - status: Not yet reviewed, or Reviewed
    - profile: the Client, a family member (with the advocate’s name), or a teen with their own account
    - a one-line reason
    - date and time
  - Not yet reviewed comes first, newest first.
- Search and Filter
  - Search: by the Client’s first name or email.
  - Filter: by level, status, profile type (Client, family member, teen) and date range.
- Escalation Details
  - Selecting an escalation opens its details, which shall show:
    - level, date and time
    - the account and profile involved, with a link to Client Details (see story 3.1)
    - why it escalated: the Oracle’s summary, and the message that triggered it
    - what the Oracle showed: for example, the 911 or 988 instructions
    - what the Client chose: I’ve called for help, I’ve reached out for help, I’m safe now, or no response
    - teen accounts only: whether the parent was told, and when (see Client story 3.2)
    - review notes: a text field for the reviewer’s notes
  - The rest of the conversation isn’t shown.
- Marking as Reviewed
  - The Admin adds any notes, and selects Mark as reviewed.
  - The status changes to Reviewed, with who reviewed it and when.
  - The Admin can mark it Not yet reviewed again if needed.
- Logging
  - Every view, review and status change is recorded in the audit logs.
Acceptance Criteria:
- Listing: Given the Admin opens Escalation Management, when it loads, then each escalation shows its level, status, profile, reason, date and time, with Not yet reviewed first.
- No follow-up: Given any escalation, when it’s shown, then there’s no overdue flag, check-in or option to contact the Client.
- Search and filter: Given the Admin searches or filters, when results load, then only matching escalations are shown.
- Details: Given the Admin selects an escalation, when details open, then they show the level, profile, the Oracle’s summary, the triggering message, what the Oracle showed, and what the Client chose.
- Limited conversation: Given escalation details, when they’re shown, then only the triggering message appears, not the rest of the conversation.
- Teen escalations: Given an escalation for a teen with their own account, when details open, then they show whether and when the parent was told.
- Reviewed: Given the Admin selects Mark as reviewed, when it’s saved, then the status changes, with the reviewer and time recorded.
- Undo: Given a reviewed escalation, when the Admin marks it Not yet reviewed, then it moves back to the top of the list.
- Dashboard: Given escalations aren’t yet reviewed, when the Dashboard loads, then they’re counted in Needs Attention.
- Logging: Given any view, review or status change, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- No escalations
  - An empty state is shown.
- Client chose no option
  - Details show “No response”.
- Escalation about a family member
  - Details show the family member and the advocate.
- Teen in crisis
  - Details show that the parent was told, with the time.
- Possible false alarm
  - The Admin adds a note in the review notes.
- Action fails
  - The Admin can try again.
Non-functional Requirements:
- New escalations appear in the listing within 1 minute.
- Escalation details show only what’s needed to review the escalation
- Escalation records are stored in the HIPAA-compliant cloud (Azure), and retained for at least six years.
Validation Rules/Errors:
- No escalations: “There are no escalations to review.”
- Marked as reviewed: “This escalation has been marked as reviewed.”
- Action failed: “We couldn’t do that just now. Please try again.”
## 5. Epic: Support Request Management
### 5.1 - Manage Support Requests
## Requirement Statement:
As an Admin, I want to view and manage the requests Clients send to the support team, so that every Client gets an answer and nothing is missed.
### Specifications:
Story Details:
- Where Requests Come From
  - Talk to Support Team: the Client writes to the team from Profile & Account, or asks for a person in a conversation (see Client story 10.1).
  - Consultation Request: the Client taps Consult with support team (see Client story 10.1).
  - Knowledge Gap: the Oracle couldn’t answer a question, and the Client agreed to send it to the team (see Client story 3.1).
  - Email Change Request: the Client asks to change their email address (see Client story 11.1).
  - Deletion requests are managed separately (see story 5.2).
- Request Listing
  - The Admin opens Support Requests from the main navigation, or the Needs Attention strip on the Dashboard (see story 2.1).
  - The listing shall show each request with:
    - type: Talk to Support Team, Consultation Request, Knowledge Gap or Email Change Request
    - status: Open or Resolved
    - the Client’s first name and email
    - profile it’s about, for example “Sent by Sarah about Azka”
    - the first line of the message
    - date and time received
  - Open requests come first, oldest first.
- Search and Filter
  - Search: by the Client’s first name or email.
  - Filter: by type, status, account type (Adult or Teen) and date range.
- Request Details
  - Selecting a request opens its details, which shall show:
    - type, status, and date and time received
    - the Client’s first name, email and account type, with a link to Client Details (see story 3.1)
    - the profile it’s about
    - the full message
    - by type:
      - Knowledge Gap: the question the Oracle couldn’t answer. It’s also sent to Knowledge Base Management (see story 6.3).
      - Email Change Request: the new email address requested, with a Change email address button (see story 3.1)
      - Consultation Request: what the Client would like help with
    - internal notes: a text field for the team’s notes, for example “Emailed on 2 Nov”
    - who resolved it, and when
- Replying to the Client
  - The team replies by email, outside the app (Session 9).
  - There’s no phone contact, because no phone number is collected.
- Consultation Requests (Session 9)
  - The support team (Gaby) contacts the Client by email, and decides whether a consultation is right for them.
  - Any consultation is booked and paid outside the app. The app doesn’t record bookings or payments.
  - The team adds a note, and marks the request resolved once they’ve been in touch.
- Resolving a Request
  - The Admin adds any notes, and selects Mark as resolved.
  - Email Change Requests are resolved automatically once the email is changed (see story 3.1).
  - The Admin can Reopen a resolved request.
- Teen Requests
  - Requests from teens with their own account are shown to the team as normal.
  - The parent never sees them.
- Logging
  - Every view, note, status change and email change is recorded in the audit logs (see story 10.1).
Acceptance Criteria:
- Listing: Given the Admin opens Support Requests, when it loads, then each request shows its type, status, Client, profile, first line and date, with Open requests first, oldest first.
- Search and filter: Given the Admin searches or filters, when results load, then only matching requests are shown.
- Details: Given the Admin selects a request, when details open, then they show the type, status, Client, profile, full message and notes.
- Knowledge Gap: Given a Knowledge Gap request, when it’s received, then it also appears in Knowledge Base Management.
- Email change: Given an Email Change Request, when the Admin changes the email from it, then the request is resolved automatically.
- Consultation Request: Given a Consultation Request, when it’s shown, then there’s no booking, price or payment in the app.
- No in-app reply: Given any request, when the team replies, then it’s by email outside the app.
- Resolve and reopen: Given an Open request, when the Admin marks it resolved, then it’s recorded with who and when, and it can be reopened.
- Teens: Given a request from a teen with their own account, when it’s shown, then it’s handled as normal, and the parent can’t see it.
- Dashboard: Given open requests exist, when the Dashboard loads, then they’re counted in Needs Attention, by type.
- Logging: Given any view, note, status change or email change, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- No requests
  - An empty state is shown.
- Request about a family member
  - The details show the family member and the advocate.
- Client doesn’t reply to the team’s email
  - The team adds a note, and decides whether to resolve the request.
- Consultation isn’t right for the Client
  - The team tells them by email, adds a note, and resolves the request.
- Email Change Request for an address already in use
  - The email isn’t changed, and the team contacts the Client.
- Resolved request needs more work
  - The Admin reopens it.
- Action fails
  - The Admin can try again.
Non-functional Requirements:
- New requests appear in the listing, and reach the support email, within 1 minute.
- Requests show only what the Client wrote and the account details needed to answer them (BAA, minimum necessary).
- Requests are stored in the HIPAA-compliant cloud (Azure).
- Every action is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- No requests: “There are no support requests right now.”
- Marked as resolved: “This request has been marked as resolved.”
- Reopened: “This request has been reopened.”
- Note saved: “Your note has been saved.”
- Action failed: “We couldn’t do that just now. Please try again.”
### 5.2 - Manage Data Deletion Requests
## Requirement Statement:
As an Admin, I want to manage Clients’ deletion requests, so that each one is completed correctly and safely.
### Specifications:
Story Details:
- Where Requests Come From
  - Account Deletion: a Client deletes their account, which deletes their data, all managed family members’ data, and their invited teens’ accounts and data (see Client story 11.4).
  - Family Member Deletion: a Client removes a managed family member (see Client story 8.2).
  - Invited Teen Removal: a parent removes an invited teen from their family (see Client story 8.2).
  - Teen Deletion:
    - a teen with their own account asks to delete all their information in the app, including when they’ve lost access (see Client story 11.4)
    - or, if the teen can’t sign in at all, they email the support team, and the Admin creates the request (see “Creating a Request for a Teen Who Can’t Sign In” below)
  - Exports are done by the Client in the app, and don’t come to the team (see Client story 11.4).
- The Deletion Timeline
  - Request made: the user is acknowledged straight away, by email.
  - 10-day grace period:
    - the user keeps full use of the app, with nothing locked
    - the request shows in the listing as Grace period, and can’t be completed yet
  - After the grace period:
    - the account is locked automatically
    - the status changes to Pending review
    - the team is notified (see story 7.1)
  - Deadline: the deletion must be completed within 45 calendar days of the request (CCPA/CPRA).
- Request Listing
  - The Admin opens Deletion Requests from the main navigation, or the Needs Attention strip on the Dashboard (see story 2.1).
  - The listing shall show each request with:
    - type: Account Deletion, Family Member Deletion, Invited Teen Removal or Teen Deletion
    - source: In app, or By email (created by the support team)
    - status: Grace period, Pending review, In progress, On legal hold, or Completed
    - the Client’s first name and email, and the profile it’s about
    - date received
    - grace period ends: 10 days after the request
    - deletion due: 45 calendar days after the request, with days remaining. Requests due within 5 days are highlighted.
  - The closest deadlines come first.
  - A + Create deletion request button.
- Search and Filter
  - Search: by the Client’s first name or email.
  - Filter: by type, source, status and date received.
- Creating a Request for a Teen Who Can’t Sign In
  - When it’s used: only when a teen can’t sign in at all, for example because their own account was deactivated (see story 3.2). They email the support team to ask for their data to be deleted.
  - The Admin selects + Create deletion request, and a form opens, with:
    - Teen’s account: search by first name or email, and select the teen’s account (Mandatory)
    - Date the email was received (Mandatory). The 45-day deadline starts from this date.
    - Note (Optional), for example where the email came from
    - Create and Cancel buttons
  - Identity check:
    - The request can only be created if the email came from the email address registered to the teen’s account.
    - If it didn’t, the team replies, asking the teen to write from the email address they used to set up their account. No request is created until they do.
    - Requests from anyone else (for example, the parent) aren’t accepted.
  - The teen is acknowledged by email. Because they can’t sign in, there’s no grace period, and the request goes straight to Pending review.
- Request Details
  - Selecting a request opens its details, which shall show:
    - type, source, status, date received, grace period end and deletion due date
    - the Client’s first name, email and account type, with a link to Client Details (see story 3.1)
    - what will be deleted: the profiles and data affected, including any invited teens
    - review checklist:
      - identity confirmed: for in-app requests, the request came from the signed-in account holder; for email requests, the email came from the registered address
      - legal hold checked
    - internal notes
    - who created it (for email requests), who completed it, and when
- Completing a Deletion
  - Available once the grace period has ended (status Pending review).
  - The Admin completes the review checklist, selects Complete deletion, and confirms.
  - What’s deleted, by type:
    - Account Deletion: the Client’s account, all managed family members’ data, and invited teens’ accounts and data
    - Family Member Deletion: that family member’s data only. Their place is freed.
    - Invited Teen Removal: the teen’s account and data
    - Teen Deletion: the teen’s account and data. If they’re still in a parent’s family, they’re removed, and the place is freed. The parent isn’t told why.
  - Data is deleted permanently, including from backups.
  - The Client, and any teen affected, is emailed once the deletion is complete.
- Legal Hold
  - If a legal hold applies, the Admin selects Place on legal hold, and adds a note.
  - The status shows On legal hold, and the deletion waits. The Client is told by email.
  - Once the hold is lifted, the deletion continues.
- Logging
  - Every request, acknowledgement, grace period, review, deletion and legal hold is recorded in the audit logs. The audit logs themselves are kept for six years, even after the data is deleted.
Acceptance Criteria:
- Listing: Given the Admin opens Deletion Requests, when it loads, then each request shows its type, source, status, Client, profile, date received, grace period end and deletion due date, with the closest deadlines first.
- Grace period: Given a request is in its grace period, when it’s shown, then its status is Grace period, and Complete deletion isn’t available.
- Pending review: Given 10 days have passed, when the grace period ends, then the status changes to Pending review, the account is locked, and the team is notified.
- Deadline: Given a request is within 5 days of its 45-day deadline, when the listing loads, then it’s highlighted, and counted on the Dashboard.
- Create a request: Given a teen who can’t sign in emails the support team, when the Admin creates a request, then it appears as a Teen Deletion, with the source By email, and goes straight to Pending review.
- Registered email only: Given the email didn’t come from the teen’s registered address, when the Admin tries to create the request, then they can’t confirm the identity check.
- Deadline from email: Given a request is created from an email, when it’s saved, then the deadline is 45 calendar days from the date the email was received.
- Details: Given the Admin selects a request, when details open, then they show what will be deleted, the review checklist and notes.
- Checklist required: Given the review checklist isn’t complete, when the Admin tries to complete the deletion, then they can’t.
- Deletion by type: Given a deletion is completed, when it’s processed, then only the data covered by its type is deleted, including from backups.
- Invited teens: Given an Account Deletion or Invited Teen Removal, when it’s completed, then the teen’s account and data are deleted.
- Legal hold: Given a legal hold applies, when the Admin places it, then the deletion waits, and the Client is told.
- Notified: Given a deletion is completed, when it’s done, then the Client, and any teen affected, is emailed.
- Within 45 days: Given a request, when it’s completed, then it’s within 45 calendar days of the request, unless a legal hold applies.
- No exports: Given a Client exports their data, when they do, then no request comes to the team.
- Logging: Given any action, when it happens, then it’s recorded in the audit logs, which are kept for six years.
Alternate Scenario:
- No requests
  - An empty state is shown.
- Request still in its grace period
  - The Admin can view it, but can’t complete it yet.
- Teen emails from a different address
  - The team replies, asking them to write from their registered email address. No request is created until they do.
- Parent emails to delete a teen’s data
  - The request isn’t accepted. Only the teen can ask.
- Teen’s account can’t be found
  - The team replies, asking for the email address they used to sign up.
- Legal hold applies
  - The deletion waits until the hold is lifted.
- Deadline close
  - The request is highlighted, and shown on the Dashboard.
- Action fails
  - The Admin can try again.
Non-functional Requirements:
- The grace period ends automatically after 10 days, and the status changes without anyone acting.
- Deletions are completed within 45 calendar days of the request, including from backups, unless a legal hold applies (CCPA/CPRA).
- Deletion requests are stored in the HIPAA-compliant cloud (Azure).
- Every action is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- No requests: “There are no deletion requests right now.”
- Grace period not ended: “This request can be completed after the grace period ends on [date].”
- Teen’s account not selected: “Please select the teen’s account.”
- Date received empty: “Please add the date the email was received.”
- Request created: “The deletion request has been created. It’s due by [date].”
- Checklist not complete: “Please complete the review checklist first.”
- Complete deletion confirmation: “Permanently delete this data? This can’t be undone.”
- Deletion completed: “The deletion is complete, and [First name] has been emailed.”
- Placed on legal hold: “This request is on legal hold. The Client has been told.”
- Action failed: “We couldn’t do that just now. Please try again.”
-

## 6. Epic: Knowledge Base Management
### 6.1 - View Knowledge Base Content
## Requirement Statement:
As an Admin, I want to view and edit the content the Oracle learns from, so that I can help keep it accurate and up to date, with the Super Admin approving what’s published.
### Specifications:
Story Details:
- What the Knowledge Base Is
  - Deborah’s content that the Oracle uses to answer Clients: books, protocols, blog posts, Q&A answers, symptom charts, diagnostic trees, case studies and knowledge gap answers (Session 5).
  - It includes the Wellness Protocols shown to Clients in their Wellness Plan.
  - All content, including blog posts and live document content, is added through Add New Content (see story 6.2).
  - The content is public, so it doesn’t need to be HIPAA compliant (Session 10). It’s kept in the app’s own library in Azure, not in Dropbox.
  - The Oracle only uses content that’s Published.
- Knowledge Base Screen
  - The Admin opens Knowledge Base from the main navigation.
  - The screen shall include:
    - the content listing (below)
    - + Add content (see story 6.2)
    - Knowledge Gaps, with the number of new gaps (see story 6.3)
- Content Listing
  - The listing shall show each item with:
    - title
    - content type: Book, Protocol, Blog post, Q&A answer, Symptom chart, Diagnostic tree, Case study or Knowledge gap answer
    - status: Draft, Pending approval, Published, Rejected or Archived
    - version number, and last updated date
  - Pending approval comes first, then newest first.
- Search and Filter
  - Search: by title, or words in the content.
  - Filter: by content type, status and date updated.
- Content Details
  - Selecting an item opens its details, which shall show:
    - title, content type, status, version and last updated date
    - the content itself, to read
    - the linked knowledge gap, if it answers one (see story 6.3)
    - version history: earlier versions, with who changed them and when
    - for Rejected items, the Super Admin’s reason
- Pending Content
  - The Admin can see items waiting for approval, but can’t approve or reject them. Only the Super Admin can (Session 5).
  - Pending items show their status, with no Approve or Reject buttons.
- Editing Content
  - The Admin selects Edit on any item, changes the title, content type or text, and saves.
  - Saving creates a new version, saved as Pending approval.
  - The Super Admin is notified, and the Oracle keeps using the current published version until the new one is approved.
  - Drafts can be edited, and sent for approval, at any time.
- Archiving and Restoring
  - Archive: the item stops being used by the Oracle, but is kept, with its history.
  - Restore: brings an archived item back as Published.
  - Roll back: the Admin can publish an earlier version from the version history.
  - Content is archived, never deleted.
- When Changes Take Effect
  - Approved, archived, restored or rolled-back content reaches the Oracle without an app release, within the update time agreed with Tkxel (to confirm, Session 5 action item).
  - Archiving or rolling back a Wellness Protocol also updates what Clients see in their Wellness Plan.
- Logging
  - Every edit, archive, restore and roll back is recorded in the audit logs.
Acceptance Criteria:
- Screen: Given the Admin opens Knowledge Base, when it loads, then it shows the content listing, + Add content, and Knowledge Gaps with the number of new gaps.
- Listing: Given the listing loads, when it’s shown, then each item shows its title, type, status, version and last updated date, with Pending approval first.
- Search and filter: Given the Admin searches or filters, when results load, then only matching items are shown.
- Details: Given the Admin selects an item, when details open, then they show its content, any linked knowledge gap, and its version history.
- No approving: Given a pending item, when the Admin opens it, then Approve & publish and Reject aren’t available.
- Edit: Given the Admin edits an item, when they save, then a new version is saved as Pending approval, the Super Admin is notified, and the Oracle keeps using the current published version.
- Archive and restore: Given a published item, when the Admin archives it, then the Oracle stops using it. Restoring it brings it back.
- Roll back: Given an earlier version, when the Admin rolls back to it, then that version is published.
- Only published content: Given any item, when the Oracle answers a Client, then only Published content is used.
- Logging: Given any change, when it’s made, then it’s recorded in the audit logs.
Alternate Scenario:
- Admin’s edit is rejected
  - The item shows as Rejected, with the Super Admin’s reason. The published version stays as it was.
- Admin’s edit is approved
  - The new version is published, and the Oracle starts using it.
- Wrong version published
  - The Admin rolls back to an earlier version.
- Admin archives a Wellness Protocol
  - It’s no longer shown in Clients’ Wellness Plans.
- Search finds nothing
  - An empty state is shown.
- Action fails
  - The Admin can try again.
Non-functional Requirements:
- The listing should load within 3 seconds.
- Approve and Reject are enforced by the system for the Super Admin only, not only hidden on screen.
- Content is never deleted, only archived, so every version can be traced.
- The knowledge base is stored in the app’s own library in Azure.
- Every change is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- No results: “No content matches your search.”
- Edit sent for approval: “Your changes have been sent to the Super Admin for approval.”
- Archive confirmation: “Archive this content? The Oracle will stop using it, but you can restore it later.”
- Roll back confirmation: “Publish version [X] instead of the current version?”
- Action failed: “We couldn’t do that just now. Please try again.”
### 6.2 - Submit New Content for Approval
## Requirement Statement:
As an Admin, I want to add new content to the knowledge base and send it for approval, so that the Super Admin can review it and the Oracle can learn from it.
### Specifications:
Story Details:
- Where to Add Content
  - From + Add content on the Knowledge Base screen (see story 6.1).
  - From Add answer on a knowledge gap, with the question filled in (see story 6.3).
- What Can Be Added
  - Any of Deborah’s content, including blog posts and live document content. Nothing is synced automatically, so new posts and updates are added here.
- Add Content Form
  - The form shall include:
    - Title (Mandatory)
    - Content type (Mandatory): Book, Protocol, Blog post, Q&A answer, Symptom chart, Diagnostic tree, Case study or Knowledge gap answer
    - Content: upload a file, or type or paste the text (one is Mandatory)
    - Linked knowledge gap (filled in when added from story 6.3)
    - Save as draft, Send for approval and Cancel buttons
  - Files: PDF, Word (DOCX) or text files (sizes and any other formats to confirm with Tkxel).
  - Uploaded files are stored in the app’s own library in Azure. Dropbox isn’t used.
- Drafts
  - Save as draft keeps the content without sending it. The Oracle doesn’t use drafts.
  - Drafts appear in the listing with the status Draft, and can be sent for approval later.
- Sending for Approval
  - The Admin selects Send for approval.
  - The content is saved as Pending approval, and the Super Admin is notified.
  - Only the Super Admin can approve and publish, or reject, it (Session 5).
  - Once approved: it’s Published, version 1, and reaches the Oracle without an app release. If it answers a knowledge gap, the gap is marked Answered (see story 6.3).
  - If rejected: it shows as Rejected, with the Super Admin’s reason.
  - The Admin is notified of the decision (see story 7.1).
- Logging
  - Every addition, draft and submission is recorded in the audit logs.
Acceptance Criteria:
- Opening the form: Given the Admin selects + Add content or Add answer, when the form opens, then it shows the title, content type and content fields.
- Required fields: Given the title, content type or content is missing, when the Admin tries to save or send, then they can’t.
- Upload: Given the Admin uploads a supported file, when it’s added, then it’s stored in the app’s library.
- Unsupported file: Given the file type or size isn’t supported, when it’s uploaded, then an error is shown.
- Draft: Given the Admin saves a draft, when it’s saved, then it shows as Draft, and the Oracle doesn’t use it.
- Sent for approval: Given the Admin sends content for approval, when it’s sent, then it’s Pending approval, the Super Admin is notified, and the Oracle doesn’t use it yet.
- No publishing: Given the Admin is on the form, when they look for Publish, then it isn’t available.
- Knowledge gap: Given the content answers a knowledge gap, when the Super Admin publishes it, then the gap is marked Answered.
- Decision: Given the Super Admin approves or rejects the content, when it’s decided, then the Admin is notified.
- Logging: Given content is added or sent, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- New blog post published on Deborah’s website
  - The Admin adds it here, and sends it for approval.
- Super Admin rejects the content
  - It shows as Rejected, with the reason.
- Admin leaves without saving
  - They’re asked to confirm first.
- Upload fails
  - The Admin can try again.
- Draft finished later
  - The Admin opens it from the listing, and sends it for approval.
Non-functional Requirements:
- Uploaded files are stored in the app’s own library in Azure.
- Publishing is enforced by the system for the Super Admin only.
- Uploads should complete within 30 seconds for supported files.
- Every action is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- Title empty: “Please add a title.”
- Content type not selected: “Please choose a content type.”
- No content: “Please upload a file, or add the text.”
- Unsupported file: “This file type isn’t supported. Please upload a PDF, Word or text file.”
- File too large: “This file is too large. Please upload a smaller file.”
- Draft saved: “Your draft has been saved.”
- Sent for approval: “Your content has been sent to the Super Admin for approval.”
- Upload failed: “We couldn’t upload this file. Please try again.”
### 6.3 - Get Alerted to Knowledge Gaps
## Requirement Statement:
As an Admin, I want to be alerted when the Oracle can’t answer a Client’s question, so that I can add an answer for the Super Admin to approve, and the Oracle can answer it next time.
### Specifications:
Story Details:
- How a Knowledge Gap Is Created
  - The Oracle can’t answer a question from Deborah’s content, and the Client agrees to send it to the support team (see Client stories 3.1 and 10.1).
  - Two things happen:
    - a Knowledge Gap support request, so the team can reply to the Client by email (see story 5.1)
    - a knowledge gap here, so the missing content can be added
- Alerts
  - The Admin is notified of each new knowledge gap (see story 7.1).
  - New gaps are counted in Needs Attention on the Dashboard (see story 2.1), and on the Knowledge Base screen (see story 6.1).
- Knowledge Gap Listing
  - The Admin opens Knowledge Gaps from the Knowledge Base screen, or from the Dashboard.
  - The listing shall show each gap with:
    - the question the Oracle couldn’t answer
    - topic, for example Sleep or Thyroid
    - times asked: similar questions are grouped, so the team can see which gaps matter most
    - status: New, Answer pending, Answered or Dismissed
    - date first and last asked
  - New gaps come first, most asked first.
- Search and Filter
  - Search: by words in the question.
  - Filter: by topic, status and date.
- Privacy
  - The gap shows only the question. It doesn’t show the Client’s name, email or conversation.
  - The Client’s details are only in the linked support request (see story 5.1).
- Answering a Gap
  - The Admin selects Add answer, and the Add Content form opens with the question filled in, and the content type set to Knowledge gap answer (see story 6.2).
  - Once the Admin sends it, the gap shows Answer pending, until the Super Admin publishes the answer.
  - Once published, the gap is marked Answered, and the Oracle can answer similar questions.
- Dismissing a Gap
  - The Admin selects Dismiss, with a reason, for example “Outside the scope of Your Oracle”.
  - Dismissed gaps stay in the listing, and can be reopened.
- Logging
  - Every gap, answer and dismissal is recorded in the audit logs.
Acceptance Criteria:
- Gap created: Given the Client agrees to send an unanswered question, when it’s sent, then a knowledge gap is created here, and a Knowledge Gap support request in story 5.1.
- Alert: Given a new knowledge gap, when it’s created, then the Admin is notified, and it’s counted on the Dashboard and the Knowledge Base screen.
- Listing: Given the Admin opens Knowledge Gaps, when it loads, then each gap shows its question, topic, times asked, status and dates, with New gaps first, most asked first.
- Grouping: Given similar questions are asked, when they’re received, then they’re grouped into one gap, and the times asked increases.
- Privacy: Given a knowledge gap, when it’s shown, then the Client’s name, email and conversation aren’t shown.
- Add answer: Given the Admin selects Add answer, when the form opens, then the question is filled in, and the content type is Knowledge gap answer.
- Answer pending: Given the Admin sends an answer, when it’s sent, then the gap shows Answer pending until the Super Admin publishes it.
- Answered: Given the Super Admin publishes the answer, when it’s published, then the gap is marked Answered.
- Dismiss: Given the Admin dismisses a gap with a reason, when it’s saved, then the gap is marked Dismissed, and can be reopened.
- Logging: Given any change to a gap, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- Same question asked again after it was answered
  - The Oracle should now answer it. If it can’t, the gap is reopened.
- Question is outside the scope of Your Oracle
  - The Admin dismisses it, with a reason.
- Super Admin rejects the answer
  - The gap goes back to New, with the Super Admin’s reason on the answer.
- No gaps
  - An empty state is shown.
- Action fails
  - The Admin can try again.
Non-functional Requirements:
- New knowledge gaps appear, and alerts are sent, within 1 minute.
- Knowledge gaps never show a Client’s personal or health information beyond the question itself.
- Every action is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- No gaps: “There are no knowledge gaps right now.”
- Dismiss reason empty: “Please add a reason for dismissing this gap.”
- Answer sent: “Your answer has been sent to the Super Admin for approval.”
- Gap dismissed: “This gap has been dismissed.”
- Gap reopened: “This gap has been reopened.”
- Action failed: “We couldn’t do that just now. Please try again.”
## 7. Epic: Notifications
### 7.1 - Receive Notifications
## Requirement Statement:
As an Admin, I want to be notified when something needs my attention, so that I can act on requests, knowledge gaps and policy updates quickly.
### Specifications:
Story Details:
- How Notifications Are Sent
  - In-app: in the notification centre (the bell in the admin panel), with a count of unread notifications
  - Email: to the Admin’s email address
  - Tapping a notification opens the right screen.
- Types of Notifications
  - Support requests: a new Talk to Support Team, Consultation Request or Email Change Request (see story 5.1)
  - Knowledge gaps: a new knowledge gap, with the question
  - Deletion requests:
    - Deletion requests:
      - a request has finished its 10-day grace period, and is ready for review (see story 5.2)
      - a reminder when a request is 5 days from its 45-day deadline
  - Knowledge base:
    - the Super Admin has approved or rejected content the Admin sent
  - Policies (TOS): a new version of the Terms of Service, Privacy Policy or Health Consent has been published
- What Isn’t Notified
  - Escalations: they’re recorded for review only, and the team doesn’t follow up with the Client (Session 9). The Admin sees them on the Dashboard and in Escalation Management (see stories 2.1 and 4.1).
  - Client exports: they’re done by the Client in the app.
  - Deletion requests still in their grace period: the team is only notified once the grace period ends.
  - Super Admin only: content waiting for approval, and new Admin set-ups.
- Notification Preferences
  - The Admin can turn email notifications on or off for each type.
  - Deletion deadline reminders can’t be turned off.
  - In-app notifications are always on.
- Privacy
  - Emails never include health information or Client names. They show a general message, for example “You have a new support request to review”, and the details are only shown in the admin panel.
Acceptance Criteria:
- Notification centre: Given the Admin opens the notification centre, when it loads, then notifications are listed newest first, with the unread count on the bell.
- Opening: Given the Admin selects a notification, when it opens, then the right screen opens.
- Requests and gaps: Given a new support request or knowledge gap, when it’s received, then the Admin is notified.
- Deletion ready for review: Given a deletion request’s grace period ends, when it moves to Pending review, then the Admin is notified.
- Deadline reminder: Given a deletion request is 5 days from its 45-day deadline, when that day comes, then the Admin is reminded.
- Content decision: Given the Super Admin approves or rejects content the Admin sent, when it’s decided, then the Admin is notified.
- Policies: Given a new policy version is published, when it goes live, then the Admin is notified.
- Not notified: Given an escalation, a Client export, or a deletion request still in its grace period, when it happens, then no notification is sent.
- Preferences: Given notification preferences, when the Admin changes them, then email notifications turn on or off for each type, except deletion deadline reminders.
- Privacy: Given any email notification, when it’s sent, then it contains no health information or Client names.
Alternate Scenario:
- Email notifications turned off for a type
  - It still appears in the notification centre.
- Notification for something already resolved
  - Opening it shows the item as resolved.
- Email can’t be delivered
  - The notification is still in the notification centre.
Non-functional Requirements:
- Notifications are sent within 1 minute.
- Emails never include health information or Client names.
- Preferences apply straight away, across all devices.
Validation Rules/Errors:
- No notifications: “You’re all caught up.”
- Type that can’t be turned off: “Deletion deadline notifications can’t be turned off.”
- Preferences saved: “Your notification preferences have been updated.”
- Save failed: “We couldn’t update your preferences just now. Please try again.”
## 8. Epic: Profile Management
### 8.1 - Manage My Profile
## Requirement Statement:
As an Admin, I want to view and update my profile and sign out securely, so that my details stay accurate and no one else can use my account.
### Specifications:
Story Details:
- Opening My Profile
  - The Admin opens My Profile from the profile icon in the admin panel.
- My Profile Screen
  - The screen shall include:
    - first name and last name
    - email address
    - role: Admin
    - last sign-in date and time
    - two-step verification: On (always on for the admin panel)
    - links to Reset Password (see story 8.2) and Notification Preferences (see story 7.1)
    - an Edit button
    - a Sign Out button
- Editing My Profile
  - The Admin selects Edit, and can change their first and last name, then selects Save.
  - The email address can’t be edited here, because it’s used to sign in. To use a different email address, the Super Admin deactivates the Admin, and invites them again with the new address (see Super Admin story 7.1).
- Signing Out
  - The Admin selects Sign Out, and a confirmation appears: “Are you sure you want to sign out?”, with Sign Out and Cancel.
  - Once confirmed:
    - the session ends on this device
    - they’re taken to the Sign In screen
    - admin screens can’t be reached afterwards, including through the browser’s back button or history
  - Being signed out automatically after 15 minutes of inactivity is covered in story 1.2.
- Logging
  - Every profile change and sign-out is recorded in the audit logs.
Acceptance Criteria:
- Screen: Given the Admin opens My Profile, when it loads, then it shows their name, email, role, last sign-in, two-step verification status, links to Reset Password and Notification Preferences, Edit and Sign Out.
- Edit name: Given the Admin edits their first or last name, when they save, then the change is saved.
- Email locked: Given the email address, when the Admin tries to edit it, then it can’t be changed here.
- Two-step verification: Given the profile, when it’s shown, then two-step verification shows as On, and can’t be turned off.
- Sign out: Given the Admin selects Sign Out and confirms, when it completes, then their session ends, and they’re taken to the Sign In screen.
- Cancel: Given the confirmation is shown, when the Admin selects Cancel, then they stay signed in.
- Back button: Given the Admin has signed out, when they use the browser’s back button, then no admin screens are shown.
- Logging: Given a profile change or sign-out, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- Admin leaves the edit screen without saving
  - They’re asked to confirm first.
- Sign out cancelled
  - The Admin stays signed in.
- Admin needs a new email address
  - The Super Admin deactivates them, and invites them again with the new address.
- Saving or signing out fails
  - The Admin can try again.
Non-functional Requirements:
- The profile screen should load within 2 seconds.
- Sign-out takes effect straight away, and clears the session from the device.
- Every change and sign-out is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- First or last name empty: “Please enter your first and last name.”
- Leaving without saving: “You have unsaved changes. Leave without saving?”
- Changes saved: “Your profile has been updated.”
- Sign out confirmation: “Are you sure you want to sign out?”
- Action failed: “We couldn’t do that just now. Please try again.
### 8.2 - Reset Password
## Requirement Statement:
As an Admin, I want to change my password while I’m signed in, so that I can keep my account secure.
### Specifications:
Story Details:
- Opening Reset Password
  - From Reset Password on My Profile (see story 8.1).
- Reset Password Screen
  - The screen shall include:
    - Current password field, masked, with a Show / Hide icon (Mandatory)
    - New password field, masked, with a Show / Hide icon (Mandatory)
    - Confirm new password field, masked, with a Show / Hide icon (Mandatory)
    - Save button
    - Forgot your password? link (see story 1.3)
- Password Validation
  - The platform shall:
    - Check the current password is correct
    - Check the new password follows the password rules:
      - Minimum 8 characters
      - At least 1 uppercase letter
      - At least 1 lowercase letter
      - At least 1 number
      - At least 1 special character
    - Check the new password is different from the current password
    - Check the new password and the confirmation match
- After the Password Is Changed
  - The Admin stays signed in on the device they’re using.
  - They’re signed out of any other open sessions.
  - They receive an email confirming the password was changed.
  - Their next sign-in needs the new password and a verification code, as always (see story 1.2).
- Forgotten Current Password
  - The Admin selects Forgot your password?, is signed out, and follows Forget Password (see story 1.3).
- Logging
  - Every password change is recorded in the audit logs.
Acceptance Criteria:
- Opening: Given the Admin is signed in, when they select Reset Password on My Profile, then the Reset Password screen opens.
- Mandatory fields: Given any field is empty, when the Admin selects Save, then a required-field error appears against that field.
- Current password: Given the current password is wrong, when the Admin selects Save, then the password isn’t changed, and an error is shown.
- Password rules: Given the new password doesn’t follow the rules, or is the same as the current one, when the Admin selects Save, then an error is shown.
- Matching: Given the new password and confirmation don’t match, when the Admin selects Save, then an error is shown.
- Show password: Given the Admin selects the eye icon, when it’s toggled, then that password switches between masked and visible.
- Password changed: Given all fields are valid, when the Admin selects Save, then the password is changed, they stay signed in on this device, other sessions end, and a confirmation email is sent.
- Forgotten password: Given the Admin selects Forgot your password?, when it opens, then they’re signed out and taken to Forget Password.
- Logging: Given the password is changed, when it’s saved, then it’s recorded in the audit logs.
Alternate Scenario:
- Wrong current password
  - An error is shown, and the password isn’t changed.
- New password doesn’t meet the rules
  - An error is shown.
- Passwords don’t match
  - An error is shown.
- New password same as current
  - The Admin is asked to choose a different one.
- Admin has forgotten their current password
  - They use Forget Password instead.
- Saving fails
  - The Admin can try again.
Non-functional Requirements:
- Passwords are securely encrypted, and never stored in plain text.
- Other sessions end straight away once the password is changed.
- Confirmation emails contain no Client information.
- Password changes are recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- Field empty: “This field is required.”
- Current password wrong: “Your current password isn’t right. Please try again.”
- New password doesn’t meet the rules: “Your password needs at least 8 characters, including an uppercase letter, a lowercase letter, a number and a special character.”
- Passwords don’t match: “The passwords don’t match. Please try again.”
- New password same as current: “Please choose a password you haven’t used before.”
- Password changed: “Your password has been changed.”
- Save failed: “We couldn’t change your password just now. Please try again.”
