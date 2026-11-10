# Super Admin user stories

Super Admin section of *Genesis Health/The Oracle - User Stories* (BA: Atiya Abid), synced from https://docs.google.com/document/d/1u94uQ0yDgEwk5TF1tu9VB97aF9NtCG7pdAm-MYp9NVs/edit by `scripts/sync_user_stories.py`. Do not edit by hand: changes are overwritten on the next sync. Out of scope for the backend for now (see `docs/PLAN.md`).

## 1. Epic: Login Module
### 1.1 - Sign In with 2FA
## Requirement Statement:
As a Super Admin, I want to sign in to the platform securely, so that only I can access the Super Admin Dashboard and the client health information it contains.
### Specifications:
Story Details:
- Super Admin Account
  - There’s one Super Admin account, set up once for Genesis Health Products (Deborah Maragopoulos) at launch (Session 10). It isn’t created through sign-up or an invitation.
- Sign In Screen
  - The Sign In screen shall include:
    - Email field (Mandatory)
    - Password field, masked (Mandatory), with a Show / Hide icon
    - Sign In button
    - Forget Password link (see story 1.2)
- Sign In Validation
  - The platform shall:
    - Validate the email format (example@domain.com)
    - Check the email and password together, and show one general error if either is wrong, without saying which one
    - Lock the account temporarily after 3 failed attempts in a row
- Two-Step Verification (Every Sign-In)
  - After the email and password are checked, the platform shall send a 6-digit code to the Super Admin’s email, at every sign-in, because this account can see every Client’s information.
  - The code:
    - is valid for 10 minutes and can be used once
    - stops working after 5 wrong attempts
    - can be resent after 60 seconds
  - The Verification screen shall include:
    - Verification Code field (Mandatory)
    - Verify button
    - Resend code link
  - Once the code is verified, the Super Admin is taken to the Dashboard (see story 2.1).
- Session Management
  - The Super Admin is signed out after 15 minutes of inactivity.
  - Signing in again always needs a new verification code.
- Logging
  - Every sign-in attempt, successful or failed, is recorded in the audit logs.
Acceptance Criteria:
- Successful sign-in: Given the Super Admin enters a valid email and password, when they enter the emailed code, then they’re taken to the Dashboard.
- 2FA every time: Given any sign-in, when the email and password are valid, then a verification code is always required, on every device.
- Invalid credentials: Given the email or password is wrong, when the Super Admin clicks Sign In, then one general error is shown, without saying which field is wrong.
- Required fields: Given the email or password is empty, when the Super Admin clicks Sign In, then a required-field error appears against that field.
- Show password: Given the Super Admin clicks the eye icon, when it’s toggled, then the password switches between masked and visible.
- Code rules: Given a code is sent, when it’s used after 10 minutes, used twice, or entered wrongly 5 times, then it no longer works.
- Account lock: Given 3 failed attempts in a row, when the Super Admin tries again, then the account is temporarily locked, and they’re directed to Forget Password.
- Inactivity: Given the Super Admin is inactive for 15 minutes, when the time passes, then they’re signed out.
- Logging: Given any sign-in attempt, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- Incorrect email or password
  - A general error is shown, and the attempt counts towards the lock.
- Code incorrect or expired
  - The Super Admin stays on the Verification screen, and can request a new code after 60 seconds.
- 3 failed attempts
  - The account is temporarily locked, and the Super Admin is directed to Forget Password (see story 1.2).
- Signed out after inactivity
  - The Super Admin signs in again, with a new code.
Non-functional Requirements:
- Passwords must be securely encrypted, and never stored in plain text.
- Authentication responses should complete within 3 seconds.
- Verification codes should arrive by email within 2 minutes.
- Authentication logs must be retained for at least six years (BAA Section 13).
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
- Signed out after inactivity: “You’ve been signed out after 15 minutes of inactivity. Please sign in again.”
### 1.2 - Forget Password
## Requirement Statement:
As a Super Admin,, I want to reset my password if I forget it, so that I can securely regain access to my account and dashboard.
### Specifications:
Story Details:
- Forget Password Screen
  - The Super Admin opens it from the Forget Password link on the Sign In screen (see story 1.1).
  - The screen shall include:
    - Email field (Mandatory)
    - Send Reset Link button
    - Back to Sign In link
- Sending the Reset Link
  - The Super Admin enters their email and clicks Send Reset Link.
  - The platform shall:
    - Validate the email format (example@domain.com)
    - Send a reset link to the email, if it belongs to the Super Admin account
    - Show the same message whether or not the email is registered, so nobody can find out which emails have an account
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
  - The Super Admin is signed out of any open sessions.
  - A temporary lock from failed sign-in attempts is removed.
  - The Super Admin receives an email confirming the password was changed.
  - They’re taken to the Sign In screen, and sign in with the new password and a verification code (see story 1.1).
- Logging
  - Every reset request and password change is recorded in the audit logs.
Acceptance Criteria:
- Reset requested: Given the Super Admin enters a valid email, when they click Send Reset Link, then the same confirmation message is shown, whether or not the email is registered.
- Reset email: Given the email belongs to the Super Admin account, when the reset is requested, then a reset link is sent to it.
- Link expiry: Given more than 60 minutes have passed, or the link has been used, when the Super Admin opens it, then the link no longer works.
- Newer link: Given the Super Admin requests a new link, when it’s sent, then any earlier link stops working.
- Password rules: Given the new password doesn’t meet the rules, or matches the current password, when the Super Admin clicks Reset Password, then an error is shown.
- Matching: Given the new password and confirmation don’t match, when the Super Admin clicks Reset Password, then an error is shown.
- Successful reset: Given a valid new password, when the Super Admin clicks Reset Password, then the password is changed, open sessions are ended, any lock is removed, a confirmation email is sent, and they’re taken to Sign In.
- Next sign-in: Given the password has been reset, when the Super Admin signs in, then a verification code is required.
- Logging: Given a reset is requested or completed, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- Email not registered
  - The same confirmation message is shown, and no email is sent.
- Link expired or already used
  - The Super Admin sees a message, and requests a new link.
- Passwords don’t match
  - The Super Admin stays on the Reset Password screen, and sees an error.
- Same as the current password
  - The Super Admin is asked to choose a different password.
- Account was locked
  - The Super Admin resets their password, and the lock is removed.
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
As a Super Admin, I want to view items needing attention along with platform-wide KPIs and analytics, so that I can act quickly on open cases and monitor client growth, Oracle usage and subscriptions.
### Specifications:
Story Details:
- Dashboard Entry
  - The Dashboard is the first screen the Super Admin sees after signing in (see story 1.1).
- Global Date Range Filter
  - A calendar date picker that applies to all KPI cards and graphs.
  - Supports a custom date range, as well as weekly, monthly and yearly views.
  - The Needs Attention strip always shows what’s open now, whatever the date range.
- Needs Attention Strip (at the top, real-time counts)
  - Escalations: escalations not yet reviewed, by level (Emergency, Crisis, Urgent). Links to Escalation Management (see story 4.1).
    - The team doesn’t follow up with Clients about escalations, so there’s no overdue count (Session 9).
  - Support Requests: open requests, by type: Talk to Support Team, Consultation Request, Knowledge Gap and Email Change Request. Links to Support Request Management (see story 5.1).
  - Deletion Requests: requests past their grace period and waiting for review, with the number close to their 45-day deadline. Links to Deletion Requests (see story 5.2).
  - Content to review: content waiting for approval, and new knowledge gaps. Links to Knowledge Base Management (see stories 6.1 and 6.3). Super Admin only (Session 5).
- KPI Cards (real-time numbers, for the selected date range)
  - Total Registered Clients (Session 4): all Clients with their own account on the platform.
  - Active Clients (Session 4): Clients who used the platform within the date range.
  - Total Conversations (Session 4): conversations held with the Oracle.
  - Escalations (Session 4): escalations within the date range, and how many are not yet reviewed.
  - Teen Accounts: teens with their own account (see Client story 1.5), split into:
    - Joined: the teen has set up their account
    - Invite sent: waiting for the teen to sign up
    - Access paused: the parent’s Family plan or consent isn’t active
  - Active Subscribers: Clients with an active paid plan, split into Individual and Family.
  - Free Trial: Clients currently on the 14-day free trial, and how many converted to a paid plan within the date range.
- Graphs
  - Client Growth Over Time: line graph of registered Clients over the date range.
  - Conversations Over Time: bar graph of Oracle conversations, by week or month.
  - Top Health Topics: horizontal bar graph of the health topics Clients ask about most, highest first. It shows Deborah what Clients care about, and what content to write next.
  - Escalation Status Breakdown: donut chart of escalations by status (Not yet reviewed, Reviewed), and by level (Emergency, Crisis, Urgent).
  - Teen Accounts Over Time: line graph of teens with their own account (Joined) over the date range.
  - Subscribers Over Time (Super Admin only): line graph of active subscribers, split into Individual and Family.
- Privacy
  - The Dashboard shows only totals and trends. No Client’s or teen’s name, conversation or health information appears on it.
- Admins
  - Admins see the same Dashboard, without the subscription and free trial metrics, and without Content to review (see the Admin persona).
Acceptance Criteria:
- Dashboard shown: Given the Super Admin signs in, when the Dashboard opens, then it shows the Needs Attention strip, all KPI cards and all graphs.
- Session 4 items: Given the Dashboard, when it loads, then it includes Total Registered Clients, Active Clients, Total Conversations and Escalations, and the Client Growth, Conversations Over Time, Top Health Topics and Escalation Status Breakdown graphs.
- Needs Attention: Given open items exist, when the Dashboard loads, then it shows escalations not yet reviewed (by level), open support requests (by type), pending data requests (with those close to the deadline), and content to review.
- Links: Given the Super Admin selects an item in Needs Attention, when it’s clicked, then the matching management screen opens.
- No overdue count: Given escalations are shown, when the strip loads, then there’s no overdue count.
- Teen accounts: Given teens with their own account exist, when the Dashboard loads, then the Teen Accounts card shows how many have joined, how many invites are pending, and how many are paused, and the graph shows joined teen accounts over time.
- Subscribers: Given the Active Subscribers card and graph, when they’re shown, then they’re split into Individual and Family.
- Free trial: Given the Free Trial card, when it’s shown, then it shows current trial Clients and conversions within the date range.
- Date range: Given the Super Admin changes the date range, when it’s applied, then every KPI card and graph updates. The Needs Attention strip stays on what’s open now.
- Accuracy: Given any KPI or graph, when it’s shown, then it matches the platform data for the date range.
- Real time: Given new activity happens, when the Dashboard is open, then the counts, numbers and graphs update without signing out and back in.
- Topics: Given the Top Health Topics graph, when it’s shown, then topics appear highest first.
- Privacy: Given the Dashboard, when it’s shown, then no Client’s or teen’s personal or health information appears on it.
- Admins: Given an Admin opens the Dashboard, when it loads, then the subscription and free trial metrics and Content to review aren’t shown.
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
  - An error is shown, and the Super Admin can try again.
Non-functional Requirements:
- The Dashboard should load within 3 seconds.
- Counts, KPIs and graphs update in real time.
- Analytics use totals only, and never expose an individual Client’s or teen’s information.
- Subscription and free trial metrics are only shown to the Super Admin.
- The Dashboard is only available to signed-in Super Admin and Admin users.
- The layout works on desktop browsers used for the admin panel.
Validation Rules/Errors:
- No data for the date range: “There’s no data for this date range.”
- Nothing needs attention: “You’re all caught up.”
- Data couldn’t load: “We couldn’t load the dashboard. Please try again.”
## 3. Epic: Client Management
### 3.1 - View Client (Listings & Details)
## Requirement Statement:
As a Super Admin, I want to view and manage all Client accounts, so that I can support Clients, keep account details accurate, and control access to the platform.
### Specifications:
Story Details:
- Client Listing
  - The Super Admin opens Client Management from the main navigation.
  - The listing shall show each account with:
    - first name and email address (no last name or phone number is collected, Session 9)
    - state
    - account type: Adult or Teen (own account, linked to the parent)
    - plan: Free trial, Individual or Family
    - status: Trial, Active, Payment issue, Cancelled, Consent revoked, Deactivated or Scheduled for deletion (during the 10-day grace period) and Being deleted (after the grace period, until the deletion is complete)
    - number of family members (adults only)
    - sign-up date and last active date
  - The newest accounts are shown first.
- Search and Filter
  - Search: by first name or email address.
  - Filter: by account type, plan, status, state and sign-up date.
- Client Details
  - Selecting an account opens the Client Details screen, which shall show:
    - Account: first name, email address, state, ZIP code, account type and sign-up date
    - Subscription: plan, status, next billing date and any add-on members (Super Admin only)
    - Consent: the versions of the Terms of Service, Privacy Policy and Health Consent accepted, and when; or “Consent revoked”
    - Family members:
      - managed family members, with first name, relationship and age
      - invited teens, with their status (Invite sent, Joined, Turned off or Access paused)
    - Teen account: the parent’s account it’s linked to, and whether access is active or paused
    - Activity: last active date, number of conversations, and any open support, deletion or escalation requests
    - Health Information: includes health information only which would get updated as the user converse with the Oracle.
    - Actions: Change email address, and Deactivate or Reactivate (see story 3.2)
  - Privacy: Client Details doesn’t show conversations, guidance summaries, provider notes for the Super Admin or Admins.
- Changing a Client’s Email Address
  - Used when a Client has sent an Email Change Request (see story 5.1).
  - The Super Admin selects Change email address, enters the new address the Client asked for, and confirms.
  - Once changed:
    - the Client is notified at both their old and new addresses
    - they’re signed out on all devices, and their trusted devices are cleared
    - they complete two-step verification at their next sign-in (see Client story 11.1)
  - The related Email Change Request is marked resolved.
- Admins
  - Admins can do everything in this story except see subscription details (Session 5).
- Logging
  - Every view of Client Details, and every email change, is recorded in the audit logs.
Acceptance Criteria:
- Listing: Given the Super Admin opens Client Management, when it loads, then each account shows its first name, email, state, account type, plan, status, family member count, sign-up date and last active date, newest first.
- Search: Given the Super Admin searches by first name or email, when results load, then only matching accounts are shown.
- Filter: Given the Super Admin applies filters, when they’re applied, then only accounts matching every filter are shown.
- Details: Given the Super Admin selects an account, when Client Details opens, then it shows the account, subscription, consent, family members, teen link, activity and actions.
- Teen link: Given a teen account, when its details are shown, then the linked parent account and the teen’s access status are shown.
- Health profile: Given the Super Admin opens Client Details, when it loads, then the health profile is shown read-only, including for teens with their own account. Conversations, guidance summaries, provider notes and visit logs aren’t shown.
- Change email: Given an Email Change Request, when the Super Admin changes the email, then the Client is notified at both addresses, signed out on all devices, their trusted devices are cleared, and the request is marked resolved.
- Admins: Given an Admin opens Client Details, when it loads, then the subscription section isn’t shown.
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
  - The Super Admin can try again.
Non-functional Requirements:
- The listing should load within 3 seconds, and search results within 1 second.
- Only signed-in Super Admin and Admin users can open Client Management.
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
As a Super Admin, I want to deactivate or reactivate a Client’s account, so that I can control who can access the platform while keeping their information.
### Specifications:
Story Details:
- Where to Deactivate or Reactivate
  - From the Client Details screen (see story 3.1).
- Deactivating an Account
  - The Super Admin selects Deactivate, and a confirmation opens, with:
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
  - The Super Admin selects Reactivate, and confirms.
  - The Client can sign in again, with all their information intact. Their notifications restart.
  - For a parent: their invited teens’ access is restored, if their Family plan and consent are still active.
- Subscription
  - Deactivating doesn’t cancel the Client’s subscription. Billing is managed separately (see Client story 11.3).
- Admins
  - Admins can deactivate and reactivate accounts, the same as the Super Admin.
- Logging
  - Every deactivation and reactivation is recorded in the audit logs, with who did it, when, and the reason.
Acceptance Criteria:
- Deactivate: Given the Super Admin selects Deactivate and enters a reason, when they confirm, then the Client is signed out on all devices, can’t sign in, and their information is kept.
- Reason required: Given the reason is empty, when the Super Admin tries to confirm, then they can’t.
- Message to the Client: Given a deactivated Client tries to sign in, when they do, then they see the deactivated message.
- Parent with teens: Given the Super Admin deactivates a parent with invited teens, when they confirm, then the teens’ access is paused, and the confirmation showed how many were affected.
- Teen account: Given the Super Admin deactivates a teen account, when they confirm, then the teen can’t sign in, and the parent’s account isn’t affected.
- Reactivate: Given a deactivated account, when the Super Admin reactivates it, then the Client can sign in again, with all information intact. A parent’s invited teens get their access back.
- Status: Given an account is deactivated or reactivated, when the listing loads, then its status shows correctly.
- Logging: Given any deactivation or reactivation, when it happens, then it’s recorded in the audit logs with the reason.
Alternate Scenario:
- Super Admin cancels
  - Nothing changes.
- Client is signed in when deactivated
  - They’re signed out straight away.
- Parent reactivated, but the Family plan has ended
  - The parent’s access returns, but their invited teens stay paused until the Family plan is active again.
- Account has a pending deletion request
  - It can still be deactivated, and the deletion continues as normal (see story 5.2).
- Action fails
  - The Super Admin can try again.
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
## 4. Epic: Escalation Management
### 4.1 - Manage Escalations
## Requirement Statement:
As a Super Admin, I want to review the escalations the Oracle has recorded, so that I can check how emergencies, crises and urgent concerns were handled, and spot false alarms.
### Specifications:
Story Details:
- The support team doesn’t contact or follow up with clients about escalations: “nobody’s making sure you went” (see Client story 3.2).
- Escalations are recorded for review only. There’s no overdue flag, 24-hour check-in, or Close / Reopen for follow-up.
- Escalation Listing
  - The Super Admin opens Escalation Management from the main navigation, or the Needs Attention strip on the Dashboard (see story 2.1).
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
  - The Super Admin adds any notes, and selects Mark as reviewed.
  - The status changes to Reviewed, with who reviewed it and when.
  - The Super Admin can mark it Not yet reviewed again if needed.
- Admins
  - Admins can review escalations, the same as the Super Admin.
- Logging
  - Every view, review and status change is recorded in the audit logs.
Acceptance Criteria:
- Listing: Given the Super Admin opens Escalation Management, when it loads, then each escalation shows its level, status, profile, reason, date and time, with Not yet reviewed first.
- No follow-up: Given any escalation, when it’s shown, then there’s no overdue flag, check-in or option to contact the Client.
- Search and filter: Given the Super Admin searches or filters, when results load, then only matching escalations are shown.
- Details: Given the Super Admin selects an escalation, when details open, then they show the level, profile, the Oracle’s summary, the triggering message, what the Oracle showed, and what the Client chose.
- Limited conversation: Given escalation details, when they’re shown, then only the triggering message appears, not the rest of the conversation.
- Teen escalations: Given an escalation for a teen with their own account, when details open, then they show whether and when the parent was told.
- Reviewed: Given the Super Admin selects Mark as reviewed, when it’s saved, then the status changes, with the reviewer and time recorded.
- Undo: Given a reviewed escalation, when the Super Admin marks it Not yet reviewed, then it moves back to the top of the list.
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
  - The Super Admin adds a note in the review notes (see the question below).
- Action fails
  - The Super Admin can try again.
Non-functional Requirements:
- New escalations appear in the listing within 1 minute.
- Escalation details show only what’s needed to review the escalation (BAA, minimum necessary).
- Escalation records are stored in the HIPAA-compliant cloud (Azure), and retained for at least six years (BAA Section 13).
- Only signed-in Super Admin and Admin users can see escalations.
Validation Rules/Errors:
- No escalations: “There are no escalations to review.”
- Marked as reviewed: “This escalation has been marked as reviewed.”
- Action failed: “We couldn’t do that just now. Please try again.”
## 5. Epic: Support Request Management
### 5.1 - Manage Support Requests
## Requirement Statement:
As a Super Admin, I want to view and manage the requests Clients send to the support team, so that every Client gets an answer and nothing is missed.
### Specifications:
Story Details:
- Where Requests Come From
  - Talk to Support Team: the Client writes to the team from Profile & Account, or asks for a person in a conversation (see Client story 10.1).
  - Consultation Request: the Client taps Consult with support team (see Client story 10.1).
  - Knowledge Gap: the Oracle couldn’t answer a question, and the Client agreed to send it to the team (see Client story 3.1).
  - Email Change Request: the Client asks to change their email address (see Client story 11.1).
  - Export and deletion requests are managed separately (see story 5.2).
- Request Listing
  - The Super Admin opens Support Requests from the main navigation, or the Needs Attention strip on the Dashboard (see story 2.1).
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
  - The Super Admin adds any notes, and selects Mark as resolved.
  - Email Change Requests are resolved automatically once the email is changed (see story 3.1).
  - The Super Admin can Reopen a resolved request.
- Teen Requests
  - Requests from teens with their own account are shown to the team as normal.
  - The parent never sees them.
- Admins
  - Admins can manage support requests, the same as the Super Admin.
- Logging
  - Every view, note, status change and email change is recorded in the audit logs (see story 10.1).
Acceptance Criteria:
- Listing: Given the Super Admin opens Support Requests, when it loads, then each request shows its type, status, Client, profile, first line and date, with Open requests first, oldest first.
- Search and filter: Given the Super Admin searches or filters, when results load, then only matching requests are shown.
- Details: Given the Super Admin selects a request, when details open, then they show the type, status, Client, profile, full message and notes.
- Knowledge Gap: Given a Knowledge Gap request, when it’s received, then it also appears in Knowledge Base Management.
- Email change: Given an Email Change Request, when the Super Admin changes the email from it, then the request is resolved automatically.
- Consultation Request: Given a Consultation Request, when it’s shown, then there’s no booking, price or payment in the app.
- No in-app reply: Given any request, when the team replies, then it’s by email outside the app.
- Resolve and reopen: Given an Open request, when the Super Admin marks it resolved, then it’s recorded with who and when, and it can be reopened.
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
  - The Super Admin reopens it.
- Action fails
  - The Super Admin can try again.
Non-functional Requirements:
- New requests appear in the listing, and reach the support email, within 1 minute.
- Requests show only what the Client wrote and the account details needed to answer them (BAA, minimum necessary).
- Requests are stored in the HIPAA-compliant cloud (Azure), and only visible to signed-in Super Admin and Admin users.
- Every action is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- No requests: “There are no support requests right now.”
- Marked as resolved: “This request has been marked as resolved.”
- Reopened: “This request has been reopened.”
- Note saved: “Your note has been saved.”
- Action failed: “We couldn’t do that just now. Please try again.”
### 5.2 - Manage Data Deletion Requests
## Requirement Statement:
As a Super Admin, I want to manage Clients’ deletion requests, so that each one is completed correctly and safely.
### Specifications:
Story Details:
- Where Requests Come From
  - Account Deletion: a Client deletes their account, which deletes their data, all managed family members’ data, and their invited teens’ accounts and data (see Client story 11.4).
  - Family Member Deletion: a Client removes a managed family member (see Client story 8.2).
  - Invited Teen Removal: a parent removes an invited teen from their family (see Client story 8.2).
  - Teen Deletion:
    - a teen with their own account asks to delete all their information in the app, including when they’ve lost access (see Client story 11.4)
    - or, if the teen can’t sign in at all, they email the support team, and the Super Admin creates the request (see “Creating a Request for a Teen Who Can’t Sign In” below)
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
  - The Super Admin opens Deletion Requests from the main navigation, or the Needs Attention strip on the Dashboard (see story 2.1).
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
  - The Super Admin selects + Create deletion request, and a form opens, with:
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
  - The Super Admin completes the review checklist, selects Complete deletion, and confirms.
  - What’s deleted, by type:
    - Account Deletion: the Client’s account, all managed family members’ data, and invited teens’ accounts and data
    - Family Member Deletion: that family member’s data only. Their place is freed.
    - Invited Teen Removal: the teen’s account and data
    - Teen Deletion: the teen’s account and data. If they’re still in a parent’s family, they’re removed, and the place is freed. The parent isn’t told why.
  - Data is deleted permanently, including from backups.
  - The Client, and any teen affected, is emailed once the deletion is complete.
- Legal Hold
  - If a legal hold applies, the Super Admin selects Place on legal hold, and adds a note.
  - The status shows On legal hold, and the deletion waits. The Client is told by email.
  - Once the hold is lifted, the deletion continues.
- Admins
  - Admins can manage and create deletion requests, the same as the Super Admin.
- Logging
  - Every request, acknowledgement, grace period, review, deletion and legal hold is recorded in the audit logs. The audit logs themselves are kept for six years, even after the data is deleted.
Acceptance Criteria:
- Listing: Given the Super Admin opens Deletion Requests, when it loads, then each request shows its type, source, status, Client, profile, date received, grace period end and deletion due date, with the closest deadlines first.
- Grace period: Given a request is in its grace period, when it’s shown, then its status is Grace period, and Complete deletion isn’t available.
- Pending review: Given 10 days have passed, when the grace period ends, then the status changes to Pending review, the account is locked, and the team is notified.
- Deadline: Given a request is within 5 days of its 45-day deadline, when the listing loads, then it’s highlighted, and counted on the Dashboard.
- Create a request: Given a teen who can’t sign in emails the support team, when the Super Admin creates a request, then it appears as a Teen Deletion, with the source By email, and goes straight to Pending review.
- Registered email only: Given the email didn’t come from the teen’s registered address, when the Super Admin tries to create the request, then they can’t confirm the identity check.
- Deadline from email: Given a request is created from an email, when it’s saved, then the deadline is 45 calendar days from the date the email was received.
- Details: Given the Super Admin selects a request, when details open, then they show what will be deleted, the review checklist and notes.
- Checklist required: Given the review checklist isn’t complete, when the Super Admin tries to complete the deletion, then they can’t.
- Deletion by type: Given a deletion is completed, when it’s processed, then only the data covered by its type is deleted, including from backups.
- Invited teens: Given an Account Deletion or Invited Teen Removal, when it’s completed, then the teen’s account and data are deleted.
- Legal hold: Given a legal hold applies, when the Super Admin places it, then the deletion waits, and the Client is told.
- Notified: Given a deletion is completed, when it’s done, then the Client, and any teen affected, is emailed.
- Within 45 days: Given a request, when it’s completed, then it’s within 45 calendar days of the request, unless a legal hold applies.
- No exports: Given a Client exports their data, when they do, then no request comes to the team.
- Logging: Given any action, when it happens, then it’s recorded in the audit logs, which are kept for six years.
Alternate Scenario:
- No requests
  - An empty state is shown.
- Request still in its grace period
  - The Super Admin can view it, but can’t complete it yet.
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
  - The Super Admin can try again.
Non-functional Requirements:
- The grace period ends automatically after 10 days, and the status changes without anyone acting.
- Deletions are completed within 45 calendar days of the request, including from backups, unless a legal hold applies (CCPA/CPRA).
- Deletion requests are stored in the HIPAA-compliant cloud (Azure), and only visible to signed-in Super Admin and Admin users.
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
## 6. Epic: Knowledge Base Management
### 6.1 - View & Edit Knowledge Base Content
## Requirement Statement:
As a Super Admin, I want to view, review and edit the content the Oracle learns from, so that the Oracle’s answers always come from my approved, up-to-date work.
### Specifications:
Story Details:
- What the Knowledge Base Is
  - Deborah’s content that the Oracle uses to answer Clients: books, protocols, blog posts, Q&A answers, symptom charts, diagnostic trees, case studies and knowledge gap answers (Session 5).
  - It includes the Wellness Protocols shown to Clients in their Wellness Plan (see Client story 7.1).
  - All content, including blog posts and live document content, is added through Add New Content (see story 6.2).
  - The content is public, so it doesn’t need to be HIPAA compliant (Session 10). It’s kept in the app’s own library in Azure, not in Dropbox.
  - The Oracle only uses content that’s Published.
- Knowledge Base Screen
  - The Super Admin opens Knowledge Base from the main navigation, or Content to review on the Dashboard (see story 2.1).
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
- Reviewing Pending Content
  - Content arrives as Pending approval when an Admin adds or edits it.
  - The Super Admin reviews it, and selects Approve & publish, or Reject with a reason. Rejected items stay in the listing as Rejected.
- Editing Content
  - The Super Admin selects Edit on any item, changes the title, content type or text, and saves.
  - Saving creates a new version, which is published straight away.
  - Drafts can be edited and published at any time.
- Archiving and Restoring
  - Archive: the item stops being used by the Oracle, but is kept, with its history.
  - Restore: brings an archived item back as Published.
  - Roll back: the Super Admin can publish an earlier version from the version history.
  - Content is archived, never deleted.
- When Changes Take Effect
  - Published changes reach the Oracle without an app release, within the update time agreed with Tkxel (to confirm, Session 5 action item).
  - Archiving or editing a Wellness Protocol also updates what Clients see in their Wellness Plan.
- Admins
  - Admins can view, edit, archive, restore and roll back content. Their edits are saved as Pending approval.
  - Only the Super Admin can approve and publish, or reject, content (Session 5).
- Logging
  - Every approval, rejection, edit, archive, restore and roll back is recorded in the audit logs.
Acceptance Criteria:
- Screen: Given the Super Admin opens Knowledge Base, when it loads, then it shows the content listing, + Add content, and Knowledge Gaps with the number of new gaps.
- Listing: Given the listing loads, when it’s shown, then each item shows its title, type, status, version and last updated date, with Pending approval first.
- Search and filter: Given the Super Admin searches or filters, when results load, then only matching items are shown.
- Details: Given the Super Admin selects an item, when details open, then they show its content, any linked knowledge gap, and its version history.
- Approve: Given a pending item, when the Super Admin selects Approve & publish, then it’s published, and the Oracle starts using it.
- Reject: Given a pending item, when the Super Admin rejects it with a reason, then it isn’t published, and shows as Rejected.
- Edit: Given the Super Admin edits an item, when they save, then a new version is created and published.
- Archive and restore: Given a published item, when the Super Admin archives it, then the Oracle stops using it. Restoring it brings it back.
- Roll back: Given an earlier version, when the Super Admin rolls back to it, then that version is published.
- Only published content: Given any item, when the Oracle answers a Client, then only Published content is used.
- Admins: Given an Admin is signed in, when they use the knowledge base, then they can view, edit, archive, restore and roll back content. Their edits are Pending approval, and they can’t approve, publish or reject content.
- Logging: Given any change, when it’s made, then it’s recorded in the audit logs.
Alternate Scenario:
- Nothing pending
  - The listing shows Published content first.
- Content is rejected
  - It stays in the listing as Rejected, with the reason.
- Wrong version published
  - The Super Admin rolls back to an earlier version.
- Super Admin archives a Wellness Protocol
  - It’s no longer shown in Clients’ Wellness Plans.
- Search finds nothing
  - An empty state is shown.
- Action fails
  - The Super Admin can try again.
Non-functional Requirements:
- The listing should load within 3 seconds.
- Published changes reach the Oracle without an app release.
- Content is never deleted, only archived, so every version can be traced.
- The knowledge base is stored in the app’s own library in Azure.
- Every change is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- No results: “No content matches your search.”
- Approved: “This content has been published. The Oracle will start using it shortly.”
- Reject reason empty: “Please add a reason for rejecting this content.”
- Archive confirmation: “Archive this content? The Oracle will stop using it, but you can restore it later.”
- Roll back confirmation: “Publish version [X] instead of the current version?”
- Action failed: “We couldn’t do that just now. Please try again.”
### 6.2 - Add New Content
## Requirement Statement:
As a Super Admin, I want to add new content to the knowledge base, so that the Oracle can learn from my latest work and answer more of my Clients’ questions.
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
    - Save as draft, Publish and Cancel buttons
  - Files: PDF, Word (DOCX) or text files (sizes and any other formats to confirm with Tkxel).
  - Uploaded files are stored in the app’s own library in Azure. Dropbox isn’t used.
- Drafts
  - Save as draft keeps the content without publishing it. The Oracle doesn’t use drafts.
  - Drafts appear in the listing with the status Draft, and can be edited and published later (see story 6.1).
- After Publishing
  - The content appears in the listing as Published, version 1.
  - It reaches the Oracle without an app release, within the agreed update time (see story 6.1).
  - If it was added from a knowledge gap, the gap is marked Answered (see story 6.3).
- Admins
  - Admins can add content, but it’s saved as Pending approval, and only the Super Admin can publish it (Session 5).
- Logging
  - Every addition, draft and publish is recorded in the audit logs.
Acceptance Criteria:
- Opening the form: Given the Super Admin selects + Add content or Add answer, when the form opens, then it shows the title, content type and content fields.
- Required fields: Given the title, content type or content is missing, when the Super Admin tries to save or publish, then they can’t.
- Upload: Given the Super Admin uploads a supported file, when it’s added, then it’s stored in the app’s library.
- Unsupported file: Given the file type or size isn’t supported, when it’s uploaded, then an error is shown.
- Draft: Given the Super Admin saves a draft, when it’s saved, then it shows as Draft, and the Oracle doesn’t use it.
- Published: Given content is published, when it’s saved, then it appears as Published, version 1, and reaches the Oracle without an app release.
- Knowledge gap: Given the content was added from a knowledge gap, when it’s published, then the gap is marked Answered.
- Admins: Given an Admin adds content, when they save it, then it’s Pending approval until the Super Admin publishes it.
- Logging: Given content is added or published, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- New blog post published on Deborah’s website
  - The Super Admin, or an Admin, adds it here.
- Super Admin leaves without saving
  - They’re asked to confirm first.
- Upload fails
  - The Super Admin can try again.
- Draft finished later
  - The Super Admin opens it from the listing, and publishes it.
Non-functional Requirements:
- Uploaded files are stored in the app’s own library in Azure.
- Published content reaches the Oracle without an app release.
- Uploads should complete within 30 seconds for supported files.
- Every action is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- Title empty: “Please add a title.”
- Content type not selected: “Please choose a content type.”
- No content: “Please upload a file, or add the text.”
- Unsupported file: “This file type isn’t supported. Please upload a PDF, Word or text file.”
- File too large: “This file is too large. Please upload a smaller file.”
- Draft saved: “Your draft has been saved.”
- Published: “Your content has been published. The Oracle will start using it shortly.”
- Upload failed: “We couldn’t upload this file. Please try again.”
### 6.3 - Get Alerted to Knowledge Gaps
## Requirement Statement:
As a Super Admin, I want to be alerted when the Oracle can’t answer a Client’s question, so that I can add the missing content and the Oracle can answer it next time.
### Specifications:
Story Details:
- How a Knowledge Gap Is Created
  - The Oracle can’t answer a question from Deborah’s content, and the Client agrees to send it to the support team (see Client stories 3.1 and 10.1).
  - Two things happen:
    - a Knowledge Gap support request, so the team can reply to the Client by email (see story 5.1)
    - a knowledge gap here, so the missing content can be added
- Alerts
  - The Super Admin and Admins are notified of each new knowledge gap (see story 11.1).
  - New gaps are counted in Content to review on the Dashboard (see story 2.1), and on the Knowledge Base screen (see story 6.1).
- Knowledge Gap Listing
  - The Super Admin opens Knowledge Gaps from the Knowledge Base screen, or from the Dashboard.
  - The listing shall show each gap with:
    - the question the Oracle couldn’t answer
    - topic, for example Sleep or Thyroid
    - times asked: similar questions are grouped, so the Super Admin can see which gaps matter most
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
  - The Super Admin selects Add answer, and the Add Content form opens with the question filled in, and the content type set to Knowledge gap answer (see story 6.2).
  - Once the answer is published, the gap is marked Answered, and the Oracle can answer similar questions.
  - Answers from Admins show Answer pending until the Super Admin approves them (see story 6.1).
- Dismissing a Gap
  - The Super Admin selects Dismiss, with a reason, for example “Outside the scope of Your Oracle”.
  - Dismissed gaps stay in the listing, and can be reopened.
- Admins
  - Admins can see knowledge gaps, add answers and dismiss gaps. Their answers are Pending approval until the Super Admin publishes them.
- Logging
  - Every gap, answer and dismissal is recorded in the audit logs.
Acceptance Criteria:
- Gap created: Given the Client agrees to send an unanswered question, when it’s sent, then a knowledge gap is created here, and a Knowledge Gap support request in story 5.1.
- Alert: Given a new knowledge gap, when it’s created, then the Super Admin and Admins are notified, and it’s counted on the Dashboard and the Knowledge Base screen.
- Listing: Given the Super Admin opens Knowledge Gaps, when it loads, then each gap shows its question, topic, times asked, status and dates, with New gaps first, most asked first.
- Grouping: Given similar questions are asked, when they’re received, then they’re grouped into one gap, and the times asked increases.
- Privacy: Given a knowledge gap, when it’s shown, then the Client’s name, email and conversation aren’t shown.
- Add answer: Given the Super Admin selects Add answer, when the form opens, then the question is filled in, and the content type is Knowledge gap answer.
- Answered: Given the answer is published, when it’s saved, then the gap is marked Answered.
- Admin answer: Given an Admin adds an answer, when they send it, then the gap shows Answer pending until the Super Admin publishes it.
- Dismiss: Given a gap is dismissed with a reason, when it’s saved, then the gap is marked Dismissed, and can be reopened.
- Logging: Given any change to a gap, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- Same question asked again after it was answered
  - The Oracle should now answer it. If it can’t, the gap is reopened.
- Question is outside the scope of Your Oracle
  - The Super Admin dismisses it, with a reason.
- Admin’s answer is rejected
  - The gap goes back to New, with the reason on the answer.
- No gaps
  - An empty state is shown.
- Action fails
  - The Super Admin can try again.
Non-functional Requirements:
- New knowledge gaps appear, and alerts are sent, within 1 minute.
- Knowledge gaps never show a Client’s personal or health information beyond the question itself.
- Every action is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- No gaps: “There are no knowledge gaps right now.”
- Dismiss reason empty: “Please add a reason for dismissing this gap.”
- Gap answered: “This gap has been answered. The Oracle will start using your answer shortly.”
- Gap dismissed: “This gap has been dismissed.”
- Gap reopened: “This gap has been reopened.”
- Action failed: “We couldn’t do that just now. Please try again.”
## 7. Epic: Admin Management
### 7.1 - View & Edit Admins
## Requirement Statement:
As a Super Admin, I want to view and manage the Admins on my team, so that the right people have access to the admin panel, and access is removed when someone leaves.
### Specifications:
Story Details:
- Who Can Manage Admins
  - Only the Super Admin can open Admin Management. Admins can’t see it.
- Admin Listing
  - The Super Admin opens Admin Management from the main navigation.
  - The listing shall show each Admin with:
    - first name and last name
    - email address
    - status: Invite pending, Active or Deactivated
    - date added, and last active date
  - The newest Admins are shown first.
  - A + Add Admin button (see story 7.2).
- Search and Filter
  - Search: by name or email address.
  - Filter: by status.
- Admin Details
  - Selecting an Admin opens their details, which shall show:
    - first name, last name and email address
    - status, date added, who added them, and last active date
    - what Admins can do (see “Admin Permissions” in story 7.2)
    - actions: Edit, Deactivate or Reactivate, and Resend invite or Cancel invite (while the invite is pending)
- Editing an Admin
  - The Super Admin selects Edit, and can change the Admin’s first and last name.
  - The email address can’t be edited, because it’s used to sign in. To use a different email address, the Super Admin deactivates the Admin and invites them again with the new address.
- Deactivating an Admin
  - The Super Admin selects Deactivate, adds a reason, and confirms.
  - Once deactivated:
    - the Admin is signed out straight away, and can’t sign in
    - their name stays on everything they did, for example in request notes and the audit logs
    - the status shows Deactivated
  - Admins are deactivated, never deleted, so their history can always be traced.
- Reactivating an Admin
  - The Super Admin selects Reactivate, and confirms.
  - The Admin can sign in again, with a new verification code (see story 1.1).
- Pending Invites
  - Resend invite: sends a new invite email, and the old link stops working (see story 7.2).
  - Cancel invite: the link stops working, and the Admin is removed from the listing.
- Logging
  - Every edit, deactivation, reactivation, resent invite and cancelled invite is recorded in the audit logs.
Acceptance Criteria:
- Super Admin only: Given an Admin is signed in, when they look for Admin Management, then it isn’t available.
- Listing: Given the Super Admin opens Admin Management, when it loads, then each Admin shows their name, email, status, date added and last active date, newest first.
- Search and filter: Given the Super Admin searches or filters, when results load, then only matching Admins are shown.
- Details: Given the Super Admin selects an Admin, when details open, then they show the Admin’s details, who added them, their permissions and the available actions.
- Edit: Given the Super Admin edits an Admin, when they save, then the first and last name are updated. The email address can’t be edited.
- Deactivate: Given the Super Admin deactivates an Admin with a reason, when they confirm, then the Admin is signed out straight away, can’t sign in, and their history is kept.
- Reactivate: Given a deactivated Admin, when the Super Admin reactivates them, then they can sign in again with a new verification code.
- Resend invite: Given an invite is pending, when the Super Admin resends it, then a new invite email is sent, and the old link stops working.
- Cancel invite: Given an invite is pending, when the Super Admin cancels it, then the link stops working, and the Admin is removed from the listing.
- Logging: Given any change, when it’s made, then it’s recorded in the audit logs.
Alternate Scenario:
- No Admins yet
  - An empty state is shown, with + Add Admin.
- Admin is signed in when deactivated
  - They’re signed out straight away.
- Admin needs a different email address
  - The Super Admin deactivates them, and invites them again with the new address.
- Invite has expired
  - The status shows Invite expired, and the Super Admin can resend it.
- Reason left empty when deactivating
  - The Admin isn’t deactivated.
- Action fails
  - The Super Admin can try again.
Non-functional Requirements:
- Admin Management is only available to the signed-in Super Admin.
- Deactivation takes effect straight away, ending all of the Admin’s sessions.
- Admins are never deleted, so every action they took stays traceable.
- Every change is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- No results: “No admins match your search.”
- First or last name empty: “Please enter the admin’s first and last name.”
- Deactivate confirmation: “Deactivate [First name]? They’ll be signed out and won’t be able to sign in until they’re reactivated.”
- Reason left empty: “Please add a reason for deactivating this admin.”
- Deactivated: “[First name] has been deactivated.”
- Reactivated: “[First name] has been reactivated.”
- Invite resent: “We’ve sent [First name] a new invite.”
- Invite cancelled: “The invite for [First name] has been cancelled.”
- Action failed: “We couldn’t do that just now. Please try again.”
### 7.2 - Add New Admin
## Requirement Statement:
As a Super Admin, I want to invite a new Admin to the admin panel, so that my team can help manage Clients, requests and content.
### Specifications:
Story Details:
- Add Admin Form
  - The Super Admin selects + Add Admin on Admin Management (see story 7.1).
  - The form shall include:
    - First name (Mandatory)
    - Last name (Mandatory)
    - Email address (Mandatory)
    - Send invite and Cancel buttons
- Sending the Invite
  - The platform shall:
    - Validate the email format (example@domain.com)
    - Check the email address isn’t already used by an Admin or the Super Admin
    - Send an invite email with a Set up your account link
  - The new Admin appears in the listing with the status Invite pending.
- Invite Link
  - The link is valid for 24 hours, and can be used once.
  - It stops working once it’s used, when a new invite is sent, or when the invite is cancelled (see story 7.1).
- Admin Account Setup
  - The link opens a setup screen, which shall include:
    - Email address (filled in, can’t be changed)
    - Password field, masked, with a Show / Hide icon (Mandatory)
    - Confirm Password field, masked, with a Show / Hide icon (Mandatory)
    - Set up account button
  - The password must follow the password rules:
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
    - At least 1 special character
  - The Admin then verifies their email with a 6-digit code, the same as story 1.1.
  - Once set up: the status changes to Active, and the Super Admin is notified (see story 11.1).
- Signing In as an Admin
  - Admins sign in the same way as the Super Admin: two-step verification at every sign-in, and signed out after 15 minutes of inactivity (see story 1.1).
- Admin Permissions
  - There’s one Admin role. Admins can do everything the Super Admin can, except:
    - Admin Management: adding, editing and deactivating Admins (stories 7.1 and 7.2)
    - Subscriptions:
      - managing plans and pricing (story 8.1)
      - seeing subscription and free trial metrics on the Dashboard (story 2.1)
      - seeing Clients’ subscription details (story 3.1)
    - Approving knowledge base content:
      - only the Super Admin can approve and publish, or reject, content (stories 6.1 to 6.3)
      - Admins can add, edit, archive, restore and roll back content
      - anything Admins add or edit goes to the Super Admin for approval before the Oracle uses it
    - Consent Management (stories 9.1 and 9.2) and viewing the Audit Logs (story 10.1)
- Logging
  - Every invite, setup and sign-in is recorded in the audit logs.
Acceptance Criteria:
- Form: Given the Super Admin selects + Add Admin, when the form opens, then it shows first name, last name and email, all mandatory.
- Email checks: Given the email is invalid, or already used by an Admin or the Super Admin, when the Super Admin selects Send invite, then an error is shown, and no invite is sent.
- Invite sent: Given valid details, when the Super Admin sends the invite, then the invite email is sent, and the Admin appears as Invite pending.
- Link expiry: Given more than 24 hours have passed, or the link has been used, when the Admin opens it, then it no longer works.
- Setup: Given the Admin opens a valid link, when they set a password that follows the rules and verify the code, then their account is Active, and the Super Admin is notified.
- Email locked: Given the setup screen, when it opens, then the email is filled in and can’t be changed.
- Sign-in rules: Given an Admin signs in, when they do, then they need a verification code every time, and are signed out after 15 minutes of inactivity.
- Permissions: Given an Admin is signed in, when they use the admin panel, then they can do everything except manage Admins, see or manage subscriptions, and approve or reject knowledge base content.
- Logging: Given an invite, setup or sign-in, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- Email already used by an Admin
  - An error is shown, and no invite is sent.
- Invite link expired
  - The Admin sees a message, and asks the Super Admin to resend it (see story 7.1).
- Invite cancelled before it’s used
  - The link stops working.
- Passwords don’t match, or don’t follow the rules
  - An error is shown, and the account isn’t set up.
- Admin doesn’t receive the invite
  - The Super Admin resends it (see story 7.1).
- Sending fails
  - The Super Admin can try again.
Non-functional Requirements:
- Invite links are unique, single use, and expire after 24 hours.
- Invite emails should arrive within 2 minutes, and contain no Client information.
- Passwords are securely encrypted, and never stored in plain text.
- Admin permissions are enforced by the system, not only hidden on screen.
- Every action is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- First or last name empty: “Please enter the admin’s first and last name.”
- Invalid email: “Please enter a valid email address.”
- Email already used: “An admin with this email address already exists.”
- Invite sent: “We’ve sent an invite to [email]. It’s valid for 24 hours.”
- Invite link expired: “This invite has expired. Please ask the Super Admin to send a new one.”
- Password doesn’t meet the rules: “Your password needs at least 8 characters, including an uppercase letter, a lowercase letter, a number and a special character.”
- Passwords don’t match: “The passwords don’t match.”
- Account set up: “Your account is ready. Please sign in.”
- Sending failed: “We couldn’t send the invite just now. Please try again.”
## 8. Epic: Subscription & Billing Management
### 8.1 - View & Edit Subscription Plans
## Requirement Statement:
As a Super Admin, I want to view and edit my subscription plans, prices and free trial, so that what Clients see and pay always matches my offer.
### Specifications:
Story Details:
- Who Can Manage Plans
  - Only the Super Admin can open Subscription & Billing. Admins can’t see it (see story 7.2).
- Plans Listing
  - The Super Admin opens Subscription & Billing from the main navigation.
  - The listing shall show each plan with:
    - plan name
    - plan type: Free trial, Individual or Family
    - price: the monthly price, or the trial length for the Free trial
    - Family plan only: the number of family members included, and the price per add-on member
    - status: Active, Draft or Inactive
    - the number of Clients currently on the plan
  - The plans at launch (Session 9):
    - Free trial: 14 days, the Client’s own profile only, conversations only, everything else greyed out
    - Individual: the Client’s own profile, with all modules
    - Family: the Client plus 3 family members, with paid add-ons for more
- Plan Details
  - Selecting a plan opens its details, which shall show:
    - name, type, status and price
    - what’s included: the list of features shown to Clients on the plan screen (see Client story 9.1)
    - Family plan: family members included, and the add-on price
    - Free trial: trial length in days
    - price history: earlier prices, with who changed them and when
- Editing a Plan
  - The Super Admin selects Edit, and can change:
    - Free trial: the trial length in days
    - Individual and Family: the monthly price, and what’s included
    - Family: the number of family members included, and the add-on price
  - Price changes:
    - apply straight away to new subscribers
    - for existing subscribers, apply from their next billing date, after they’ve been told (notice period to confirm)
  - Trial length changes apply to new trials only. Clients already on a trial keep their original length.
  - Fewer family members included: Clients who already have more keep them, and aren’t charged extra until their next billing date (to confirm).
- Turning a Plan Off
  - The Super Admin can set a plan to Inactive, so new Clients can’t choose it.
  - Clients already on the plan keep it.
  - Plans are never deleted, so their history can always be traced.
- What Isn’t Managed Here
  - Consultations: booked and paid outside the app (Session 9), so they have no price in the app.
  - The member discount: only on the Shopify store (Session 9).
  - Teens with their own account: they don’t have a plan. Their access is covered by the parent’s Family plan (see Client story 1.5).
- Payments
  - Prices are kept in step with Stripe, the App Store and Google Play (SOW).
  - App Store and Google Play prices may take time to update, and must match their price options.
- Logging
  - Every change to a plan, price or trial length is recorded in the audit logs, with who made it and when.
Acceptance Criteria:
- Super Admin only: Given an Admin is signed in, when they look for Subscription & Billing, then it isn’t available.
- Listing: Given the Super Admin opens Subscription & Billing, when it loads, then each plan shows its name, type, price, status and number of Clients, plus the family members and add-on price for the Family plan.
- Launch plans: Given the platform launches, when the listing loads, then it shows the Free trial (14 days), the Individual plan and the Family plan.
- Details: Given the Super Admin selects a plan, when details open, then they show what’s included and the price history.
- Edit trial: Given the Super Admin changes the trial length, when they save, then new trials use it, and current trials keep their original length.
- Edit price: Given the Super Admin changes a price, when they save, then new subscribers pay it straight away, and existing subscribers pay it from their next billing date, after being told.
- Edit add-on: Given the Super Admin changes the add-on price or the family members included, when they save, then the Family plan and the Client plan screen update.
- Client plan screen: Given any plan change is saved, when a Client opens the plan screen, then they see the updated prices and features (see Client story 9.1).
- Inactive: Given the Super Admin sets a plan to Inactive, when it’s saved, then new Clients can’t choose it, and current Clients keep it.
- No consultation or discount pricing: Given the plans, when they’re shown, then there’s no consultation price or member discount.
- Logging: Given any change, when it’s saved, then it’s recorded in the audit logs.
Alternate Scenario:
- Price increased
  - Existing subscribers are told before it applies to them.
- Price lowered
  - Existing subscribers pay the lower price from their next billing date.
- Super Admin sets the Family plan to Inactive
  - Current Family plan Clients keep their family members.
- App Store or Google Play price can’t be updated straight away
  - The Super Admin is told, and the change applies once the store has updated.
- Price or trial length invalid
  - The change isn’t saved.
- Action fails
  - The Super Admin can try again.
Non-functional Requirements:
- Plan changes reach the Client plan screen without an app release.
- Prices stay in step with Stripe, the App Store and Google Play.
- Plans are never deleted, only made inactive.
- Every change is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- Price empty or invalid: “Please enter a valid price.”
- Trial length invalid: “Please enter a trial length in days, for example 14.”
- Family members included invalid: “Please enter how many family members are included.”
- Price change confirmation: “Change the price to [price]? New subscribers will pay this straight away. Existing subscribers will pay it from their next billing date, after they’ve been told.”
- Set inactive confirmation: “Make this plan inactive? New Clients won’t be able to choose it. Clients already on it will keep it.”
- Saved: “Your changes have been saved.”
- Store update pending: “Your change has been saved. The App Store and Google Play prices will update once they’re approved.”
- Action failed: “We couldn’t do that just now. Please try again.”
### 8.2 - Add Subscription Plans and Pricing
## Requirement Statement:
As a Super Admin, I want to add a new subscription plan with its price and features, so that I can offer Clients new options as my business grows.
### Specifications:
Story Details:
- Who Can Add Plans
  - Only the Super Admin (see story 7.2).
- Add Plan Form
  - The Super Admin selects + Add plan on Subscription & Billing (see story 8.1).
  - The form shall include:
    - Plan name (Mandatory), for example “Family Plus”
    - Plan type (Mandatory): Individual or Family
    - Monthly price (Mandatory)
    - Family plans only:
      - family members included (Mandatory)
      - price per add-on member (Mandatory)
    - What’s included (Mandatory): the features shown to Clients on the plan screen, one per line
    - Save as draft, Publish and Cancel buttons
  - There’s only one Free trial, so a new trial can’t be added. Its length is edited in story 8.1.
- Drafts
  - Save as draft keeps the plan without showing it to Clients.
  - Drafts appear in the listing with the status Draft, and can be published later.
- Publishing a Plan
  - The Super Admin selects Publish, and confirms.
  - The plan is set up with Stripe, the App Store and Google Play, and appears on the Client plan screen (see Client story 9.1).
  - Its status shows Active.
- Consultations and Discounts
  - Plans can’t include consultations or a member discount. Consultations are booked and paid outside the app, and the member discount is only on the Shopify store (Session 9).
- Logging
  - Every plan added, saved as a draft or published is recorded in the audit logs.
Acceptance Criteria:
- Super Admin only: Given an Admin is signed in, when they look for + Add plan, then it isn’t available.
- Form: Given the Super Admin selects + Add plan, when the form opens, then it shows the plan name, type, monthly price and what’s included, plus family members and the add-on price for Family plans.
- Required fields: Given a mandatory field is empty, when the Super Admin tries to save or publish, then they can’t.
- Draft: Given the Super Admin saves a draft, when it’s saved, then it shows as Draft, and Clients can’t see it.
- Publish: Given the Super Admin publishes a plan, when they confirm, then it’s set up with the payment providers, appears on the Client plan screen, and shows as Active.
- One trial: Given the Super Admin adds a plan, when they choose the type, then Free trial isn’t an option.
- Logging: Given a plan is added, saved or published, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- Plan name already used
  - An error is shown.
- Super Admin leaves without saving
  - They’re asked to confirm first.
- Payment provider setup fails
  - The plan stays as Draft, and the Super Admin can try again.
- App Store or Google Play approval takes time
  - The plan is shown on the Web App first, and on mobile once approved.
Non-functional Requirements:
- New plans reach the Client plan screen without an app release.
- Plans are set up with Stripe, the App Store and Google Play before Clients can choose them.
- Every action is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- Plan name empty: “Please enter a plan name.”
- Plan name already used: “A plan with this name already exists.”
- Plan type not selected: “Please choose a plan type.”
- Price empty or invalid: “Please enter a valid monthly price.”
- Family members or add-on price empty: “Please enter the family members included and the add-on price.”
- What’s included empty: “Please add at least one feature.”
- Publish confirmation: “Publish [plan name]? It will be shown to Clients on the plan screen.”
- Draft saved: “Your draft has been saved.”
- Published: “[Plan name] is now available to Clients.”
- Setup failed: “We couldn’t set up this plan with the payment providers. Please try again.”
## 9. Epic: Consent Management
### 9.1 - View & Edit Policy Versions
## Requirement Statement:
As a Super Admin, I want to view every version of the Terms of Service, Privacy Policy and Health Consent, and see who has accepted them, so that I always know which version is live and whether Clients have agreed to it.
### Specifications:
Story Details:
- Policies Managed Here
  - Terms of Service and Privacy Policy: accepted by Clients at sign-up (see Client story 1.1).
  - Health Consent: accepted before the Oracle’s first reply, once per profile, with a family member version for advocates (see Client story 3.1).
  - Teens with their own account don’t accept policies. Their parent accepts for them (see Client story 12.2).
- Policy Listing
  - The Super Admin opens Consent Management from the main navigation.
  - The listing shall show each policy with:
    - policy name
    - current live version number, and the date it was published
    - acceptance: how many Clients have accepted the new live version, and how many haven’t yet
    - whether a draft of the next version exists
- Policy Details
  - Selecting a policy opens its details, which shall show:
    - the live version’s full text
    - version history: every earlier version, with its version number, publish date and who published it. Each can be opened, read-only.
    - any draft of the next version
- Editing
  - Published versions can’t be edited, so there’s always a record of exactly what each Client agreed to.
  - To change a policy, the Super Admin creates a new version (see story 9.2).
  - Drafts can be edited, previewed and published at any time (see story 9.2).
- Acceptance Records
  - Each Client’s accepted versions, with dates, are shown in Client Details (see story 3.1), and to the Client in Privacy & Data (see Client story 11.4).
- Admins
  - Admins can’t access Consent Management.
- Logging
  - Every view and change is recorded in the audit logs.
Acceptance Criteria:
- Listing: Given the Super Admin opens Consent Management, when it loads, then each policy shows its name, live version, publish date, acceptance numbers, and whether a draft exists.
- Details: Given the Super Admin selects a policy, when details open, then they show the live text, the version history and any draft.
- Earlier versions: Given the version history, when the Super Admin opens an earlier version, then it’s shown read-only.
- No editing published versions: Given a published version, when the Super Admin looks for Edit, then it isn’t available. They’re directed to create a new version.
- Drafts: Given a draft exists, when the Super Admin opens it, then they can edit, preview or publish it.
- Admins: can’t access Consent Management.
- Logging: Given any view or change, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- No draft exists
  - The Super Admin creates a new version (see story 9.2).
- Most Clients haven’t accepted the latest version yet
  - The acceptance numbers show this. Clients are asked when they next open the app (see Client story 12.2).
- Action fails
  - The Super Admin can try again.
Non-functional Requirements:
- Published versions can never be changed or deleted.
- Every accepted version is kept for at least six years, with the Clients who accepted it.
- Policy text is managed here, without an app release.
Validation Rules/Errors:
- Edit attempted on a published version: “Published versions can’t be changed. Create a new version instead.”
- Action failed: “We couldn’t do that just now. Please try again.”
### 9.2 - Add New Policy Version
## Requirement Statement:
As a Super Admin, I want to publish a new version of a policy, so that Clients are told about the change and accept it before continuing to use the app.
### Specifications:
Story Details:
- Creating a New Version
  - From a policy’s details, the Super Admin selects + New version (see story 9.1).
  - The form opens with the live version’s text, ready to edit, and shall include:
    - Version number: set automatically, for example 1.3
    - Policy text (Mandatory)
    - Summary of changes (Mandatory): a short note of what’s changed, shown to Clients
    - Save as draft, Preview and Publish buttons
- Preview
  - Shows the version as Clients will see it on the Policy Update screen (see Client story 12.2).
- Publishing
  - The Super Admin selects Publish, and confirms.
  - What happens:
    - the new version is live straight away, and earlier versions move to the version history
    - every Client is emailed (see Client story 12.2)
    - signed-in sessions end, so Clients see the updated policy the next time they open the app
    - Clients must accept it before they can sign in and continue
    - Health Consent: advocates also confirm it for each family member, including invited teens
    - invited teens: their access is paused until their parent accepts (see Client story 12.2)
    - new Clients accept the latest version at sign-up, or at their first conversation
- Admins
  - Admins can’t access Consent Management.
- Logging
  - Every draft and publish is recorded in the audit logs, with who did it and when.
Acceptance Criteria:
- Form: Given the Super Admin selects + New version, when the form opens, then it’s filled in with the live text, with the version number set automatically.
- Required fields: Given the policy text or summary of changes is empty, when the Super Admin tries to publish, then they can’t.
- Draft: Given the Super Admin saves a draft, when it’s saved, then Clients don’t see it.
- Preview: Given the Super Admin selects Preview, when it opens, then it shows the version as Clients will see it.
- Publish: Given the Super Admin publishes a version, when they confirm, then it’s live, every Client is emailed, signed-in sessions end, and Clients must accept it before continuing.
- Health Consent: Given a new Health Consent is published, when advocates sign in, then they confirm it for each family member, including invited teens.
- Invited teens: Given a new version is published, when the parent hasn’t accepted yet, then their invited teens’ access is paused.
- Logging: Given a draft is saved or a version is published, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- Super Admin leaves without saving
  - They’re asked to confirm first.
- Two policies updated at the same time
  - Clients accept both on the same screen (see Client story 12.2).
- Publishing fails
  - The version stays as a draft, and the Super Admin can try again.
Non-functional Requirements:
- Published versions can never be changed or deleted.
- Emails about policy updates contain no health information.
- Every action is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- Policy text empty: “Please add the policy text.”
- Summary of changes empty: “Please add a short summary of what’s changed.”
- Publish confirmation: “Publish version [X] of the [Policy name]? Every Client will be asked to accept it before they can continue.”
- Draft saved: “Your draft has been saved.”
- Published: “Version [X] of the [Policy name] is now live. Clients have been emailed.”
- Publishing failed: “We couldn’t publish this version. Please try again.”
## 10. Epic: Audit Logging
### 10.1 - View & Export Audit Logs
## Requirement Statement:
As a Super Admin, I want to view and export a complete record of key actions on the platform, so that I can track who did what and when.
### Specifications:
Story Details:
- What’s Recorded
  - Sign-in and security: sign-ins (successful and failed), two-step verification, sign-outs, password resets and account locks, for Clients, teens, Admins and the Super Admin
  - Client accounts: sign-ups, email and state changes, deactivations and reactivations, family members added, turned off or removed, and teen invites
  - Consent: policies accepted, consent revoked and given again
  - Data: exports downloaded by Clients, deletion requests, acknowledgements, grace periods, deletions and legal holds
  - Escalations: escalations recorded, viewed and reviewed, and parents told about a teen
  - Support requests: requests received, notes, and requests resolved or reopened
  - Knowledge base: content added, edited, approved, rejected, archived, restored and rolled back.
  - Admins: invites, set-ups, edits, deactivations and reactivations
  - Plans: plans added or edited, and price changes
  - Admin views: each time an Admin or the Super Admin opens Client Details or an escalation
- Audit Log Screen
  - The Super Admin opens Audit Logs from the main navigation.
  - Each entry shall show:
    - date and time
    - who: name and role (Client, Teen, Admin, Super Admin or System)
    - action, for example “Deletion completed”
    - what it affected, for example the Client account or content item
    - device or IP address, for sign-in events
  - The newest entries come first.
- Search and Filter
  - Search: by name or email.
  - Filter: by date range, role, and category (the groups above).
- Exporting
  - The Super Admin selects Export, and the filtered entries download as a CSV file.
  - The export itself is recorded in the audit logs.
- Privacy
  - Audit logs never include conversations or health information. They record that something happened, not what was said.
- Rules
  - Audit logs can’t be edited or deleted, by anyone.
  - They’re kept for six years, even after a Client’s data is deleted (BAA Section 13).
- Admins
  - Admins can’t access Audit Logs. Their actions are still recorded
Acceptance Criteria:
- Recorded: Given any action in the lists above, when it happens, then an entry is added to the audit logs.
- Entries: Given the Super Admin opens Audit Logs, when it loads, then each entry shows the date and time, who, their role, the action and what it affected, newest first.
- Search and filter: Given the Super Admin searches or filters, when results load, then only matching entries are shown.
- Export: Given the Super Admin selects Export, when it’s ready, then the filtered entries download as a CSV file, and the export is recorded.
- No health information: Given any entry, when it’s shown or exported, then it contains no conversation or health information.
- Can’t change: Given any entry, when anyone tries to edit or delete it, then they can’t.
- Retention: Given an entry, when six years haven’t passed, then it’s kept, even if the Client’s data was deleted.
Alternate Scenario:
- No entries match the filters
  - An empty state is shown.
- Very large export
  - The Super Admin is asked to narrow the date range.
- Export fails
  - The Super Admin can try again.
Non-functional Requirements:
- Entries are added within a few seconds of the action.
- Logs are tamper-proof: they can’t be edited or deleted.
- Logs are kept for at least six years (BAA Section 13), and stored in the HIPAA-compliant cloud (Azure).
- Search results should load within 3 seconds.
Validation Rules/Errors:
- No results: “No entries match your filters.”
- Export too large: “This export is too large. Please choose a shorter date range.”
- Export complete: “Your audit log export has downloaded.”
- Export failed: “We couldn’t export the audit logs. Please try again.”
## 11. Epic: Notifications
### 11.1 - Receive Notifications
## Requirement Statement:
As a Super Admin, I want to be notified when something needs my attention, so that I can act on escalations, requests, knowledge gaps and policy updates quickly.
### Specifications:
Story Details:
- How Notifications Are Sent
  - In-app: in the notification centre (the bell in the admin panel), with a count of unread notifications
  - Email: to the Super Admin’s and Admins’ email addresses
  - Tapping a notification opens the right screen.
- Types of Notifications
  - Support requests: a new Talk to Support Team, Consultation Request or Email Change Request (see story 5.1)
  - Knowledge gaps: a new knowledge gap, with the question (see story 6.3)
  - Deletion requests:
    - a request has finished its 10-day grace period, and is ready for review (see story 5.2)
    - a reminder when a request is 5 days from its 45-day deadline
  - Knowledge base:
    - content waiting for approval (Super Admin only, see story 6.1)
  - Policies (TOS): a new version of the Terms of Service, Privacy Policy or Health Consent has been published (see story 9.2)
  - Admins: a new Admin has set up their account (Super Admin only, see story 7.2)
- What Isn’t Notified
  - Escalations: they’re recorded for review only, and the team doesn’t follow up with the Client. The team sees escalations waiting for review on the Dashboard and in Escalation Management (see stories 2.1 and 4.1).
  - Deletion requests still in their grace period: the team is only notified once the grace period ends.
  - Client exports: they’re done by the Client in the app (see Client story 11.4).
- Notification Preferences
  - Each Admin and the Super Admin can turn email notifications on or off for each type.
  - Deletion deadline reminders can’t be turned off.
  - In-app notifications are always on.
- Privacy
  - Emails never include health information or Client names. They show a general message, for example “You have a new support request to review”, and the details are only shown in the admin panel.
- Admins
  - Admins receive the same notifications as the Super Admin, except content waiting for approval and new Admin set-ups.
Acceptance Criteria:
- Notification centre: Given the Super Admin opens the notification centre, when it loads, then notifications are listed newest first, with the unread count on the bell.
- Opening: Given the Super Admin selects a notification, when it opens, then the right screen opens.
- Requests and gaps: Given a new support request or knowledge gap, when it’s received, then the team is notified.
- Deletion ready for review: Given a deletion request’s grace period ends, when it moves to Pending review, then the team is notified.
- Deadline reminder: Given a deletion request is 5 days from its 45-day deadline, when that day comes, then the team is reminded.
- Knowledge base: Given content is waiting for approval, when it happens, then the Super Admin is notified.
- Policies: Given a new policy version is published, when it goes live, then the team is notified.
- New Admin: Given a new Admin sets up their account, when it’s active, then the Super Admin is notified.
- No escalation notifications: Given an escalation is recorded, when it happens, then no notification is sent. It appears on the Dashboard and in Escalation Management.
- No export notifications: Given a Client exports their data, when they do, then no one is notified.
- Preferences: Given notification preferences, when the Super Admin changes them, then email notifications turn on or off for each type, except deletion deadline reminders.
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
## 12. Epic: Profile Management
### 12.1 - Manage My Profile - (View & Edit, Sign Out)
## Requirement Statement:
As a Super Admin, I want to view and update my profile and sign out securely, so that my details stay accurate and no one else can use my account.
### Specifications:
Story Details:
- Opening My Profile
  - The Super Admin opens My Profile from the profile icon in the admin panel.
- My Profile Screen
  - The screen shall include:
    - first name and last name
    - email address
    - role: Super Admin or Admin
    - last sign-in date and time
    - two-step verification: On (always on for the admin panel, see story 1.1)
    - links to:
      - Reset Password (see story 12.2)
      - Notification Preferences (see story 11.1)
    - an Edit button
    - a Sign Out button
- Editing My Profile
  - The Super Admin selects Edit, and can change their first and last name.
  - They select Save to save their changes.
  - The email address can’t be edited here, because it’s used to sign in:
    - Admins: the Super Admin deactivates them and invites them again with the new address (see story 7.1).
    - Super Admin: the change is made by Tkxel (to confirm).
- Signing Out
  - The Super Admin selects Sign Out, and a confirmation appears: “Are you sure you want to sign out?”, with Sign Out and Cancel.
  - Once confirmed:
    - the session ends on this device
    - they’re taken to the Sign In screen
    - admin screens can’t be reached afterwards, including through the browser’s back button or history
  - Being signed out automatically after 15 minutes of inactivity is covered in story 1.1.
- Admins
  - Admins can use this story, the same as the Super Admin.
- Logging
  - Every profile change and sign-out is recorded in the audit logs.
Acceptance Criteria:
- Screen: Given the Super Admin opens My Profile, when it loads, then it shows their name, email, role, last sign-in, two-step verification status, links to Reset Password and Notification Preferences, Edit and Sign Out.
- Edit name: Given the Super Admin edits their first or last name, when they save, then the change is saved.
- Email locked: Given the email address, when the Super Admin tries to edit it, then it can’t be changed here.
- Two-step verification: Given the profile, when it’s shown, then two-step verification shows as On, and can’t be turned off.
- Sign out: Given the Super Admin selects Sign Out and confirms, when it completes, then their session ends, and they’re taken to the Sign In screen.
- Cancel: Given the confirmation is shown, when the Super Admin selects Cancel, then they stay signed in.
- Back button: Given the Super Admin has signed out, when they use the browser’s back button, then no admin screens are shown.
- Admins: Given an Admin opens My Profile, when they use it, then they can do everything the Super Admin can in this story.
- Logging: Given a profile change or sign-out, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- Super Admin leaves the edit screen without saving
  - They’re asked to confirm first.
- Sign out cancelled
  - The Super Admin stays signed in.
- Super Admin needs a new email address
  - The change is made by Tkxel.
- Saving or signing out fails
  - The Super Admin can try again.
Non-functional Requirements:
- The profile screen should load within 2 seconds.
- Sign-out takes effect straight away, and clears the session from the device.
- Every change and sign-out is recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- First or last name empty: “Please enter your first and last name.”
- Leaving without saving: “You have unsaved changes. Leave without saving?”
- Changes saved: “Your profile has been updated.”
- Sign out confirmation: “Are you sure you want to sign out?”
- Action failed: “We couldn’t do that just now. Please try again.”
### 12.2 - Reset Password
## Requirement Statement:
As a Super Admin, I want to change my password while I’m signed in, so that I can keep my account secure.
### Specifications:
Story Details:
- Opening Reset Password
  - From Reset Password on My Profile (see story 12.1).
- Reset Password Screen
  - The screen shall include:
    - Current password field, masked, with a Show / Hide icon (Mandatory)
    - New password field, masked, with a Show / Hide icon (Mandatory)
    - Confirm new password field, masked, with a Show / Hide icon (Mandatory)
    - Save button
    - Forgot your password? link (see story 1.2)
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
  - The Super Admin stays signed in on the device they’re using.
  - They’re signed out of any other open sessions.
  - They receive an email confirming the password was changed.
  - Their next sign-in needs the new password and a verification code, as always (see story 1.1).
- Forgotten Current Password
  - The Super Admin selects Forgot your password?, is signed out, and follows Forget Password (see story 1.2).
- Admins
  - Admins can use this story, the same as the Super Admin.
- Logging
  - Every password change is recorded in the audit logs.
Acceptance Criteria:
- Opening: Given the Super Admin is signed in, when they select Reset Password on My Profile, then the Reset Password screen opens.
- Mandatory fields: Given any field is empty, when the Super Admin selects Save, then a required-field error appears against that field.
- Current password: Given the current password is wrong, when the Super Admin selects Save, then the password isn’t changed, and an error is shown.
- Password rules: Given the new password doesn’t follow the rules, or is the same as the current one, when the Super Admin selects Save, then an error is shown.
- Matching: Given the new password and confirmation don’t match, when the Super Admin selects Save, then an error is shown.
- Show password: Given the Super Admin selects the eye icon, when it’s toggled, then that password switches between masked and visible.
- Password changed: Given all fields are valid, when the Super Admin selects Save, then the password is changed, they stay signed in on this device, other sessions end, and a confirmation email is sent.
- Forgotten password: Given the Super Admin selects Forgot your password?, when it opens, then they’re signed out and taken to Forget Password.
- Logging: Given the password is changed, when it’s saved, then it’s recorded in the audit logs.
Alternate Scenario:
- Wrong current password
  - An error is shown, and the password isn’t changed.
- New password doesn’t meet the rules
  - An error is shown.
- Passwords don’t match
  - An error is shown.
- New password same as current
  - The Super Admin is asked to choose a different one.
- Super Admin has forgotten their current password
  - They use Forget Password instead.
- Saving fails
  - The Super Admin can try again.
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
