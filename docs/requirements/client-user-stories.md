# Client user stories

Client section of *Genesis Health/The Oracle - User Stories* (BA: Atiya Abid), synced from https://docs.google.com/document/d/1u94uQ0yDgEwk5TF1tu9VB97aF9NtCG7pdAm-MYp9NVs/edit by `scripts/sync_user_stories.py`. Do not edit by hand: changes are overwritten on the next sync. In scope for the backend: the build order and decisions are in `docs/PLAN.md`.

## 1. Epic: Login Module
### 1.1 - Sign Up
## Requirement Statement:
As a new Client, I want to create my Your Oracle account, so that I can begin my health journey with the Oracle.
### Specifications:
Story Details:
- Welcome & Disclaimer Screen
  - Shown to everyone before the sign-up form, on the Mobile App and Web App.
  - The screen shall show:
“Oracle’s content comes from the published works of Deborah Maragopoulos, MN FNP. Oracle is an AI health education tool. It is not a person, and it is not Deborah or any other nurse, nurse practitioner, physician or licensed health care provider. Using Oracle does not mean you are hiring or consulting a clinician, and it does not create a clinician–patient relationship. Deborah does not review your conversations.
If you’d like to talk with a person, you can contact our support team.
In an emergency, call 911. If you’re thinking about harming yourself, call or text 988.”
- A Continue button opens the sign-up form.
- Sign Up Form
  - The sign-up screen shall include:
    - First name field
    - Date of birth field
    - Country, State and ZIP code fields
    - Email field
    - Password and Confirm password fields
    - Terms of Service and Privacy Policy checkbox
    - Create Account button
    - Sign in redirect link
- Sign Up Steps
  - Step 1: the Client enters their first name and date of birth. Only the first name is asked.
  - Step 2: the Client enters their country, state and ZIP code. Only the United States can be selected.
  - Step 3: the Client enters their email and password, accepts the Terms of Service and Privacy Policy, and clicks Create Account.
  - Step 4: the Client verifies their email with a code.
- Age Check
  - After Step 2, the platform shall compare the date of birth with the age of majority for the selected state:
    - 18 in most states and Washington, D.C.
    - 19 in Alabama and Nebraska
    - 21 in Mississippi
  - If the Client has reached it: they continue to Step 3.
  - If not: sign-up stops, and no account is created. The Client is asked to have a parent or guardian add them as a family member (see story 1.5).
- Registration Validation
  - The platform shall:
    - Validate the email format (example@domain.com)
    - Prevent duplicate accounts using the same email
    - Validate password requirements:
      - Minimum 8 characters
      - At least 1 uppercase letter
      - At least 1 lowercase letter
      - At least 1 number
      - At least 1 special character
- Email Verification
  - The platform shall send a 6-digit code to the Client’s email.
  - The code:
    - is valid for 10 minutes and can be used once
    - stops working after 5 wrong attempts
    - can be resent after 60 seconds
- After Verification
  - The account is created, and the device is trusted for 30 days.
  - The free trial starts (see story 9.1).
  - The Client is redirected to onboarding (see story 2.1).
Acceptance Criteria:
- Disclaimer first: Given someone opens the app to sign up, when the first screen loads, then the Welcome & Disclaimer screen is shown before the sign-up form.
- Continue: Given the Welcome & Disclaimer screen, when the person taps Continue, then the sign-up form opens.
- Successful sign-up: Given a Client has reached their state’s age of majority and fills in all fields correctly, when they verify the code, then their account is created and they are redirected to onboarding.
- Under age: Given a Client’s date of birth is below their state’s age of majority, when they complete Step 2, then sign-up stops and no account is created.
- U.S. only: Given the country field, when the Client opens it, then only the United States is available.
- Required fields: Given any field is empty, when the Client tries to continue, then a validation error appears against that field.
- Duplicate email: Given the email already has an account, when the Client clicks Create Account, then the system shows an error and offers Sign In.
- Code verification: Given the Client enters the correct code within 10 minutes, when they submit it, then their email is verified.
- Sign In navigation: Given the Client clicks “Sign in”, when the action is triggered, then they are redirected to the sign-in screen.
Alternate Scenario:
- Below the age of majority
  - The Client enters a date of birth below their state’s age of majority.
  - The system stops sign-up.
  - A message asks them to have a parent or guardian add them.
- Email already registered
  - The Client enters an email that already has an account.
  - The system shows an error and offers Sign In.
- Code not received or expired
  - The Client requests a new code after 60 seconds.
  - The new code replaces the old one.
- Too many wrong codes
  - The Client enters a wrong code 5 times.
  - The code stops working, and the Client must request a new one.
Non-functional Requirements:
- Passwords must be securely encrypted and never stored in plain text.
- Personal details are stored in the HIPAA-compliant cloud (Azure).
- Sign-up details are never shared with analytics tools, ad pixels or Shopify.
- The age-of-majority table can be updated without an app release.
- The sign-up experience shall be responsive across mobile and web.
Validation Rules/Errors:
- First name empty: “Please enter your first name.”
- Date of birth empty or in the future: “Please enter a valid date of birth.”
- State or ZIP code empty or invalid: “Please enter a valid state and ZIP code.”
- State is empty or invalid: “Please enter a valid state.”
- Below the age of majority: “Please ask a parent or guardian to add you as a family member.”
- Invalid email: “Please enter a valid email address.”
- Email already in use: “An account with this email already exists. Please sign in.”
- Password doesn’t meet the rules: “Your password needs at least 8 characters, including an uppercase letter, a lowercase letter, a number and a special character.”
- Passwords don’t match: “The passwords don’t match.”
- Terms not accepted: “Please accept the Terms of Service and Privacy Policy to continue.”
- Wrong code: “That code isn’t right. Please try again.”
- Code expired, or too many attempts: “Please request a new code.”
### 1.2 - Sign In - (2FA Code)
## Requirement Statement:
As a Client, I want to securely sign in using my email and password, so that I can access my account.
### Specifications:
Story Details:
- For delete account request users: No new routing. During the grace period, the Client signs in as normal.
- Sign In Screen
  - The Sign In screen shall include:
    - Email field (Mandatory)
    - Password field, masked (Mandatory), with a Show / Hide icon
    - Sign In button
    - Forget Password link (see story 1.3)
    - Sign up redirect link (see story 1.1)
  - If a policy has been updated, the Client accepts it before reaching this screen (see story 12.2).
- Sign In Validation
  - The platform shall:
    - Validate the email format (example@domain.com)
    - Check the email and password together, and show one general error if either is wrong, without saying which one
    - Lock the account temporarily after 3 failed attempts in a row
- Two-Step Verification
  - Trusted device: the Client is signed in without a code.
  - New device or browser, after a password reset, or when the 30-day trusted period has ended: the platform shall send a 6-digit code to the Client’s email.
  - The code:
    - is valid for 10 minutes and can be used once
    - stops working after 5 wrong attempts
    - can be resent after 60 seconds
  - After the code is verified, the device is trusted for 30 days.
- Where the Client Goes After Signing In
  - The platform shall check the account in this order, and take the Client to the first screen that applies:
    - Account in its deletion notice period: the Client, or an invited teen on that account, with a message that the account will be deleted on [date]. They can download their data.
    - Account being deleted (after the grace period): a message that the account is being deleted, and is no longer available.”
    - Consent revoked: the Terms of Service, Privacy Policy and Health Consent screen. The Client must accept all three before seeing their data. Their data was kept (see story 11.4).
    - Onboarding not finished: back to the exact question where they stopped, with earlier answers saved (see stories 2.1 and 2.3).
    - Teen whose access is paused: a message asking them to speak to their parent or guardian, because the parent’s Family plan is no longer active (see story 1.5).
    - Teen who has lost access: the teen is taken straight to the Privacy & Data screen in the app, with a message at the top explaining their access is paused. They can use Export My Data and Delete My Information there. Everything else in the app is locked (see story 11.4)
    - Teen who has reached the age of majority: the Create My Account message (see story 1.6).
    - Free trial ended without a subscription: the plan screen (see story 8.1).
    - Everything else: the Home Dashboard (see story 4.1).
- Session Management
  - Web App: the Client is signed out after 30 minutes of inactivity, and must sign in again after 12 hours.
  - Mobile App: the app locks after 15 minutes in the background, and unlocks with Face ID, fingerprint or the device passcode. The Client stays signed in for up to 30 days on a trusted device.
  - If a session ends during a conversation, the conversation is saved, and resumes after signing in.
- Logging
  - Every sign-in attempt, successful or failed, is recorded in the backend logs.
Acceptance Criteria:
- Successful sign-in: Given a Client enters a valid email and password on a trusted device, when they click Sign In, then they’re signed in without a code.
- New device: Given a Client signs in on a new device or browser, when their email and password are valid, then they must enter the emailed code before continuing.
- Invalid credentials: Given the email or password is wrong, when the Client clicks Sign In, then one general error is shown, without saying which field is wrong.
- Required fields: Given the email or password is empty, when the Client clicks Sign In, then a required-field error appears against that field.
- Show password: Given the Client clicks the eye icon, when it’s toggled, then the password switches between masked and visible.
- Account lock: Given 3 failed attempts in a row, when the Client tries again, then the account is temporarily locked, and they’re directed to Forget Password.
- Teen access paused: Given the parent’s Family plan isn’t active, when a teen signs in, then they see the access-paused message, with no billing details.
- Given a teen has lost access, when they sign in, then they can only see the Privacy & Data in the app, with the access-paused message, and everything else is locked.
- Account being deleted: Given an account’s grace period has ended, when the Client or an invited teen tries to sign in, then they see the account-being-deleted message, and can’t use the app.
- Grace period: Given an account is in its grace period, when the Client signs in, then they use the app as normal, with the deletion banner.
- After sign-in: Given the Client is signed in, when the account is checked, then they’re taken to the first screen that applies, in the order listed above.
- Session timeout: Given the Client is inactive on the Web App for 30 minutes, when the time passes, then they’re signed out.
Alternate Scenario:
- Incorrect email or password
  - The Client enters a wrong email or password.
  - The system shows a general error, and the attempt counts towards the lock.
- 3 failed attempts
  - The account is temporarily locked.
  - The Client is directed to Forget Password (see story 1.3).
- Code incorrect or expired
  - The Client stays on the Verification screen, and can request a new code after 60 seconds.
- Consent previously revoked
  - The Client accepts the Terms of Service, Privacy Policy and Health Consent again.
  - Their previous data is still there.
- Teen’s access paused
  - The parent’s Family plan has been cancelled, downgraded or has a failed payment.
  - The teen sees the access-paused message, and can’t use the app until the plan is active again.
- Account deactivated by the support team
  - The Client can’t sign in, and sees a deactivated message.
- Session ends mid-conversation
  - The conversation is saved, and resumes after the Client signs in again.
Non-functional Requirements:
- Passwords must be securely encrypted, and never stored in plain text.
- Authentication responses should complete within 3 seconds.
- Verification codes should arrive by email within 2 minutes.
- Trusted-device details must be stored securely, and removed when the Client signs out.
- Authentication logs must be retained for at least six years (BAA Section 13), and aren’t shown in the app.
- The sign-in flow must follow OWASP authentication best practices, on both Mobile and Web.
Validation Rules/Errors:
- Email empty: “Email is required.”
- Invalid email format: “Please enter a valid email address.”
- Password empty: “Password is required.”
- Email or password incorrect: “Incorrect email or password. Please try again.”
- Code empty: “Please enter the verification code sent to your email.”
- Code incorrect: “That code doesn’t match. Please check your email and try again.”
- Code expired, or too many attempts: “This code has expired. Please request a new one.”
- Account locked: “Your account has been temporarily locked after too many attempts. Please reset your password to continue.”
- Account deactivated: “Your account has been deactivated. Please contact the support team for help.”
- Teen access paused: “Your access is paused. Please ask your parent or guardian. You can still download your data or ask for it to be deleted here.”
- Account being deleted: “Your account is being deleted, so it’s no longer available.”
- Grace period banner: “Your account is scheduled for deletion on [date].”
- Signed out after inactivity: “You’ve been signed out after a period of inactivity. Please sign in again.”
### 1.3 - Forget Password
## Requirement Statement:
As a Client, I want to reset my password if I forget it, so that I can securely regain access to my account.
### Specifications:
Story Details:
- Forget Password Screen
  - The Client opens it from the Forget Password link on the Sign In screen.
  - The screen shall include:
    - Email field (Mandatory)
    - Send Reset Link button
    - Back to Sign In link
- Sending the Reset Link
  - The Client enters their email and clicks Send Reset Link.
  - The platform shall:
    - Validate the email format (example@domain.com)
    - Send a reset link to the email, if an account exists for it
    - Show the same message whether or not the account exists, so nobody can find out which emails are registered
- Reset Link
  - The link is valid for 60 minutes, and can be used once.
  - It stops working once it’s used, once the password is changed, or when a newer link is requested.
- Reset Password Screen
  - The link opens a screen that shall include:
    - New Password field, masked, with a Show / Hide icon (Mandatory)
    - Confirm New Password field, masked, with a Show / Hide icon (Mandatory)
    - Reset Password button
  - The new password must follow the password rules:
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
    - At least 1 special character
  - The new password can’t be the same as the current password.
- After the Password Is Reset
  - The Client is signed out on all devices, and trusted devices are cleared.
  - A temporary lock from failed sign-in attempts is removed.
  - The Client receives an email confirming the password was changed.
  - The Client is taken to the Sign In screen. Their next sign-in needs a verification code (see story 1.2).
- Teens
  - Teens with their own login reset their password the same way (see story 1.5).
- Logging
  - Every reset request and password change is recorded in the backend logs.
Acceptance Criteria:
- Reset requested: Given the Client enters a valid email, when they click Send Reset Link, then the same confirmation message is shown, whether or not the account exists.
- Reset email: Given an account exists for the email, when the reset is requested, then a reset link is sent to it.
- Link expiry: Given more than 60 minutes have passed, or the link has been used, when the Client opens it, then the link no longer works.
- Newer link: Given the Client requests a new link, when it’s sent, then any earlier link stops working.
- Successful reset: Given the Client enters a valid new password and confirms it, when they click Reset Password, then the password is changed and they’re taken to Sign In.
- After reset:
  - The Client is signed out on all devices.
  - Trusted devices are cleared.
  - Any temporary lock is removed.
  - A confirmation email is sent.
- Next sign-in: Given the password has been reset, when the Client signs in, then a verification code is required.
Alternate Scenario:
- Email not registered
  - The Client enters an email with no account.
  - The same confirmation message is shown, and no email is sent.
- Link expired or already used
  - The Client opens an old link.
  - The system shows a message, and the Client requests a new link.
- Passwords don’t match
  - The Client stays on the Reset Password screen, and sees an error.
- Same as the current password
  - The Client is asked to choose a different password.
- Account was locked
  - The Client resets their password, and the lock is removed.
Non-functional Requirements:
- Reset links must be unique, single use and time-limited.
- Reset emails should arrive within 2 minutes, and contain no health information.
- Passwords must be securely encrypted, and never stored in plain text.
- All reset events must be recorded in the backend logs, and retained for at least six years (BAA Section 13).
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
### 1.4 - Sign out
## Requirement Statement:
As a Client, I want to sign out of my account.
### Specifications:
Story Details:
- The Client can tap “Sign Out” from the Profile & Settings menu, on the Mobile App or Web App.
- The system displays a confirmation prompt: “Are you sure you want to sign out?” with Sign Out and Cancel options.
- If confirmed, the system ends the Client’s session.
- Any ongoing conversation with the Oracle is saved, so the Client can continue it after signing back in.
- The Client is redirected to the Sign In screen.
- Signing out applies to the whole account, including any family member profiles the Client manages.
Acceptance Criteria:
- The Client can access Sign Out from clicking on the profile button on dashboard
- A confirmation prompt is displayed before signing out.
- Selecting Cancel keeps the Client signed in on the same screen.
- Selecting Sign Out ends the session and redirects the Client to the Sign In screen.
- Ongoing conversations are saved and available after the Client signs back in.
- After signing out, the Client cannot access any app screens, including by using the device’s back button, without signing in again.
Alternate Scenario:
- The Client cancels the sign-out from the confirmation prompt.
- The Client loses internet connection while signing out, and the session is ended once the connection returns.
- The Client is signed in on more than one device, and signing out on one device doesn’t sign them out of the others.
- The Client’s session times out after a period of inactivity, and they are signed out automatically.
Non-functional Requirements:
- The session must be fully ended on the device, and session tokens cleared on sign-out.
- Sign-out should complete within 2 seconds.
- Sign-out activity is recorded in the backend logs and retained for six years
Validation Rules/Errors:
- “Are you sure you want to sign out?”
- “You’ve been signed out. Please sign in again to continue.”
- “Your session has expired. Please sign in again.”
### 1.5 - Teen Sign Up (Parent Invite)
## Requirement Statement:
As a Teen, I want to accept my parent’s invite and create my own login, so that I can talk to the Oracle privately about my health.
### Specifications:
Story Details:
- Parent Starts the Invite
  - Only parents on the Family plan can invite a teen to their own account (Session 9; Miro board: “linked to your Family Plan”).
  - During the free trial or on the Individual plan: the parent sees the upgrade prompt instead (see story 8.1).
- Parent Starts the Invite
  - When adding a teen family member, the parent chooses Teen with their own account (“Invite your teen to create their own private Oracle account”).
  - Privacy disclaimer: before continuing, the parent sees a Teen account privacy disclaimer:
    - their teen will receive their own private Your Oracle account
    - the parent won’t be able to view the teen’s conversations, health information or activity
    - the teen can use the account while under the age of majority, and manages their own account independently once they reach it
  - The parent selects I understand & continue.
  - The parent enters the teen’s email address: “Enter your teen’s email address. We’ll send them an invitation to create their own Oracle account linked to your Family Plan.”
  - Confirmation: “Invitation sent. We’ve emailed [teen email] with instructions to create their Oracle account.”
- Invite Email
  - Subject: “You’ve been invited to join Your Oracle”
  - Message: “You’ve been invited to create your own Your Oracle account as part of a Family Plan. Set up your account to start using Oracle.”
  - Button: Finish Sign Up
  - The invite link is unique and tied to the parent’s family account, so the teen doesn’t go through the normal sign-up.
- Teen Account Setup
  - Before setting up their account, the teen sees the Welcome & Disclaimer screen (see story 1.1), and taps Continue.
  - Create Password:
    - Email (filled in from the invite, and can’t be changed)
    - Password
    - Confirm Password
  - About You:
    - Preferred name or first name
    - Date of birth
    - City
    - State
    - Country
  - The order of the screens is left to the UI designer.
  - There’s no consent step and no subscription step, because the parent gave consent and pays.
- Age and Eligibility Check
  - The platform shall work out the teen’s age category from their date of birth, state and country.
  - If they fall within the teen or minor category: they continue into the teen experience, and see:
    - Welcome to Your Oracle
    - This is your own private space to learn about your health. Ask me anything you’re curious about, and I’ll help you understand what’s going on and what you can talk about with your provider.
- Profile Basics
  - The teen answers sex assigned at birth, gender identity and pronouns (see story 2.3).
  - They then go straight into their own Oracle chat.
- Family plan ends (cancelled, downgraded to Individual, or payment failed)
  - the teen’s access is paused, not deleted
  - when they sign in, they’re taken straight to the Privacy & Data screen in the app, with the message: “Your access is paused. Please ask your parent or guardian. You can still download your data or ask for it to be deleted here.” (no billing details)
  - on that screen, they can use Export My Data and Delete My Information. Everything else in the app is locked (see story 11.4).
  - the parent is told the teen’s access is paused, and nothing about the teen’s activity (see story 12.1)
  - Family plan active again: the teen’s access is restored, with their history intact.
- What the Teen Can and Can’t Do
  - Can: have conversations with the Oracle, a guidance summary, a Wellness Plan or provider notes.
  - Can’t:
    - revoke consent
    - access subscriptions and billing
    - get product recommendations, add family members
  - Export My Data: the teen can download a copy of their own data in the app, at any time, including while their access is paused (see story 11.4).
  - Delete My Information: they can request to delete all their information, at any time, including while their access is paused.
- Reaching the Age of Majority
  - Two weeks before: the teen gets a reminder that they’ll need an adult plan, because this account will stop.
  - On the day: they can no longer use this account (see story 1.6).
Acceptance Criteria:
- Family plan only: Given the parent isn’t on the Family plan, when they choose Teen with their own account, then they see the upgrade prompt instead.
- Privacy disclaimer: Given a parent on the Family plan chooses Teen with their own account, when they continue, then they must accept the Teen account privacy disclaimer first.
- Disclaimer first: Given the teen opens the invite link, when the first screen loads, then the Welcome & Disclaimer screen is shown before account setup.
- Invite sent: Given the parent enters the teen’s email, when they confirm, then the “Invitation sent” message shows, and the teen receives the invite email.
- Unique link: Given the teen opens the invite link, when it loads, then it opens the teen setup, not the normal sign-up.
- Email locked: Given the teen is on the setup screen, when it loads, then their email is filled in and can’t be changed.
- No consent or subscription: Given the teen is setting up their account, when the screens are shown, then there’s no consent step and no subscription step.
- Teen category: Given the teen’s date of birth, state and country put them in the teen category, when the check runs, then they see the “Your Oracle for teens” message.
- Profile basics: Given the teen has finished setup, when they continue, then they answer sex at birth, gender identity and pronouns, and then land in their Oracle chat.
- Restrictions: Given the teen is signed in, when they use the app, every feature is available to them.
- Parent privacy: Given the parent is signed in, when they view their family members, then they can’t see the teen’s conversations, health information or activity.
- Access paused: Given the parent’s Family plan ends, when the teen signs in, they can only see Privacy & Data in the app, with the access-paused message, and everything else is locked.
- Export while paused: Given a teen’s access is paused, when they tap Export My Data, then their data downloads in the app.
- Access restored: Given the Family plan is active again, when the teen signs in, then their access is back, with their history intact.
- Reminder: Given the teen is two weeks from the age of majority, when that date arrives, then they receive the reminder.
- Account stops: Given the teen reaches the age of majority, when they try to sign in, then they can no longer use this account.
Alternate Scenario:
- Parent not on the Family plan
  - The parent tries to invite a teen.
  - The upgrade prompt is shown, and no invite is sent.
- Invite link expired or invalid
  - The teen sees a message, and asks the parent to send a new invite.
- Teen already has an account
  - The invite redirects them to Sign In.
- Parent’s Family plan ends
  - The teen’s access is paused, and the parent is told.
  - The teen can still export their data, or request deletion, in Privacy & Data.
  - Their history is kept, and full access returns when the plan is active again.
- Teen requests to delete their information
  - The request is sent for processing (see story 11.4).
- Teen reaches the age of majority
  - They get a reminder two weeks before.
  - On the day, they can no longer use this account (see story 1.6).
Non-functional Requirements:
- Invite links must be unique, single use, time-limited, and tied to the parent’s family account.
- The teen’s access must follow the parent’s Family plan status straight away.
- The teen’s conversations, health information and activity are stored separately, and can never be seen from the parent’s account.
- Teen accounts are stored in the HIPAA-compliant cloud (Azure).
- Invite and access emails contain no health information.
- Passwords must be securely encrypted, and never stored in plain text.
Validation Rules/Errors:
- Parent not on the Family plan: “Inviting your teen to their own account is part of the Family plan. Upgrade to invite [Name].”
- Disclaimer not accepted: “Please confirm you understand your teen’s account privacy to continue.”
- Teen’s email empty or invalid: “Please enter a valid email address for your teen.”
- Invitation sent: “Invitation sent. We’ve emailed [teen email] with instructions to create their Oracle account.”
- Invite link expired or invalid: “This invite has expired. Please ask your parent or guardian to send a new one.”
- Password doesn’t meet the rules: “Your password needs at least 8 characters, including an uppercase letter, a lowercase letter, a number and a special character.”
- Passwords don’t match: “The passwords don’t match.”
- Date of birth, city, state or country empty: “Please complete this field.”
- Teen access paused: “Your access is paused. Please ask your parent or guardian. You can still download your data or ask for it to be deleted here.”
- Parent told access is paused: “[Name]’s access is paused because your Family plan has ended. Renew to restore it.”
- Reminder before the age of majority: “In two weeks, you’ll reach adult age. You’ll need an adult plan to keep using Your Oracle.”
- Age of majority reached: “You’ve reached adult age, so this account is no longer available. Please create your own account to continue.”
### 1.6 - Teen Reaches the Age of Majority
## Requirement Statement:
As a Teen who is reaching the age of majority, I want to be told in advance and be able to move to my own adult account, so that I can keep using Your Oracle and keep my history.
### Specifications:
Story Details:
- Age Check
  - The platform shall check each teen’s date of birth against the age of majority for their state:
    - 18 in most states and Washington, D.C.
    - 19 in Alabama and Nebraska
    - 21 in Mississippi
- Reminder Two Weeks Before
  - Two weeks before the teen reaches the age of majority, the system shall give them a reminder that they’ll need an adult plan, because their teen account will stop (see story 12.1).
- Once They’ve Reached It
  - The teen can no longer use their teen account.
  - When they sign in, they see a message saying they’ve reached adult age, with a Create My Account button.
- Creating Their Own Account
  - The teen clicks Create My Account, and follows the adult sign-up (see story 1.1).
  - Their first name, date of birth and email are filled in from their teen account.
  - Their new account starts with the free trial, like any new Client (see story 9.1).
- Their History
  - Their conversations and health profile move to their new account when it’s created.
  - They can see their history during the free trial.
  - If they don’t subscribe after the trial, their history is kept. It’s only deleted if they choose to delete it (see story 11.4).
- The Parent’s Account
  - When the new adult account is created:
    - the teen’s profile is removed from the parent’s account, and the parent gets that family member place back
    - the parent is told that their teen now has their own independent account
  - The parent isn’t told about anything else.
- After the Move
  - The new account follows the adult rules for their age, including the Wellness Plan, provider notes and the other modules.
  - The teen account is closed.
- Logging
  - The reminder, the account stopping, the new account and the history move are all recorded in the backend logs.
Acceptance Criteria:
- Reminder: Given a teen is two weeks from the age of majority, when that date arrives, then they receive the reminder.
- Account stops: Given the teen has reached the age of majority, when they sign in, then they can’t use the teen account, and they’re shown the Create My Account message.
- Sign-up prefilled: Given the teen clicks Create My Account, when the adult sign-up opens, then their first name, date of birth and email are filled in.
- History moved: Given the new adult account is created, when they sign in, then their history is there, including during the free trial.
- History kept: Given the new adult doesn’t subscribe after the trial, when the trial ends, then their history is kept until they choose to delete it.
- Parent’s family place: Given the new adult account is created, when the parent views their family members, then the teen is no longer listed, and the family member place is free.
- Parent notified: Given the new adult account is created, when it’s set up, then the parent is told their teen now has an independent account.
- Adult rules: Given the account is set up, when they use the app, then the adult modules and questions apply.
Alternate Scenario:
- Teen ignores the reminder
  - Once they reach the age of majority, the teen account still stops, and they see the Create My Account message when they sign in.
- Teen never creates an account
  - Their history is kept, and the parent isn’t notified.
- New adult doesn’t subscribe after the trial
  - Their history is kept until they choose to delete it.
- Teen has moved to another state
  - Waiting on Deborah’s attorney (see the routing document, section 6).
- History move fails
  - The history is kept safe, and the move is tried again.
Non-functional Requirements:
- The age check should run every day, using the age-of-majority table, which can be updated without an app release.
- History must move in full, and never be visible from both the teen account and the new account at the same time.
- History is never deleted automatically, only when the user asks.
- All data is stored in the HIPAA-compliant cloud (Azure).
- Reminder and notification emails contain no health information.
- Every step is recorded in the backend logs, and retained for at least six years (BAA Section 13).
Validation Rules/Errors:
- Reminder two weeks before: “In two weeks, you’ll reach adult age. You’ll need an adult plan to keep using Your Oracle.”
- Age of majority reached: “You’ve reached adult age, so this account is no longer available. Please create your own account to continue.”
- History moved: “Your history has been moved to your new account.”
- History move failed: “We couldn’t move your history just now. We’ll try again shortly.”
- Parent notified: “[Teen’s first name] now has their own Your Oracle account. Their place in your family plan is free again.”
## 2. Epic: Client Onboarding (Health Intake)
### 2.1 - Onboarding (Myself)
## Requirement Statement:
As a Client, I want to complete a short health intake about myself, so that the Oracle can address me correctly and start personalising its guidance from my first conversation.
### Specifications:
Story Details:
- When Onboarding Starts
  - Straight after sign-up and email verification (see story 1.1).
  - This flow is for adults only. Teens follow story 2.3.
- Onboarding Screens
  - Screen 1, Who is this profile for?
    - Options: Myself / For a family member
    - Choosing For a family member follows story 2.2.
  - Screen 2, Sex assigned at birth (Mandatory)
    - Options: Male / Female / Intersex / Prefer not to say
  - Screen 3, Gender (Mandatory): “How would you describe your gender?”
    - Options: Woman / Man / Non-binary / Agender / Not listed (write in) / Prefer not to say
  - Screen 4, Pronouns (Mandatory)
    - Options: He/Him / She/Her / They/Them / Other (write in)
    - For Agender or Not listed, They/Them is selected by default, and the Client can change it.
  - The date of birth isn’t asked here, because it was given at sign-up.
- What Onboarding Doesn’t Ask
  - No body, hormone or surgery questions. The follow-up questions for Path A, Path B and gender “Prefer not to say” are asked by the Oracle in conversation (see the routing document).
- Progress
  - Each answer is saved as the Client goes. If they leave part-way, they return to the same screen at their next sign-in (see story 1.2).
  - A Back button lets them change an earlier answer.
- After Onboarding
  - The Client sees two options:
    - Start with the Oracle: opens a conversation (see story 3.1)
    - Complete my intake: opens the health profile form in My Health (see story 6.1)
Acceptance Criteria:
- Starts after sign-up: Given an adult Client has verified their email, when sign-up finishes, then onboarding opens at “Who is this profile for?”
- Myself route: Given the Client chooses Myself, when they continue, then they’re asked sex at birth, gender and pronouns, in that order.
- Mandatory answers: Given a question is unanswered, when the Client tries to continue, then they can’t move on.
- Write-in: Given the Client chooses Not listed or Other, when they continue, then they must type their answer.
- Default pronouns: Given the Client chooses Agender or Not listed, when the pronoun screen opens, then They/Them is selected by default.
- No body questions: Given onboarding, when it runs, then no body, hormone or surgery questions are asked.
- Resume: Given the Client left part-way, when they sign in again, then they return to the same screen, with earlier answers saved.
- After onboarding: Given the Client finishes, when the last answer is saved, then they see Start with the Oracle and Complete my intake.
Alternate Scenario:
- Client leaves part-way: they return to the same screen at their next sign-in.
- Client goes back: they change an earlier answer, and the later screens update to match.
- Client chooses For a family member: they follow story 2.2.
Non-functional Requirements:
- Each answer should save straight away.
- Sex at birth, gender and pronouns are encrypted, stored in the HIPAA-compliant cloud (Azure), and never shared with analytics tools, ad pixels or Shopify.
- The question options can be updated without an app release.
- Onboarding must be responsive on Mobile and Web.
Validation Rules/Errors:
- Question not answered: “Please choose an option to continue.”
- “Not listed” left empty: “Tell me in your own words how you describe your gender.”
- “Other” pronouns left empty: “Tell me which pronouns you’d like me to use.”
- Saving failed: “We couldn’t save your answer just now. Please try again.”
### 2.2 - Onboarding (Family Member)
## Requirement Statement:
As a Client, I want to add a family member and complete a short health intake for them, so that I can talk with the Oracle about their health as their medical advocate.
### Specifications:
Story Details:
- Family Intake Entry
  - The Client can start adding a family member from:
    - For a family member, on the “Who is this profile for?” screen (see story 2.1)
    - Add Family Member, in their family profiles (see story 8.1)
  - The platform shall:
    - Show the upgrade prompt first, if the Client’s plan doesn’t include family members (see story 9.1)
    - Not offer this option to teens (see story 2.3)
- Intake Screens
  - Each screen shall include:
    - the question, using [Name] with a capital first letter, even if typed in lowercase
    - the answer options
    - a Back button to change an earlier answer
    - the tree background, which grows and blooms with each completed step
  - Step 1- Who are they to you? (Mandatory)
    - Options: Parent / Child / Partner / Someone else
    - The intake moves on when an option is selected.
  - Step 2 -  What’s their first name? (Mandatory)
    - First name field, and a Continue button
  - Step 3 - When was [Name] born? (Mandatory)
    - Scroll picker for month, day and year, and a Continue button
  - Step 4 - Before we set up [Name]’s profile (Mandatory)
    - Message: “As [Name]’s medical advocate, you’ll manage their profile and talk with the Oracle on their behalf. We just need to confirm you have their permission or the authority to do this.”
    - Options (one only), then Continue:
      - [Name] knows I’m adding them and has agreed for me to be their medical advocate
      - I’m [Name]’s parent or legal guardian
      - [Name] can’t make this decision themselves, and I’m authorised to act for them (for example, as their healthcare proxy or power of attorney)
  - Step 5 -  What was [Name]’s sex assigned at birth? (Mandatory)
    - Options: Male / Female / Intersex / Prefer not to say
    - The intake moves on when an option is selected.
  - Step 6 -  How does [Name] describe their gender? (Mandatory)
    - Under 13: Girl / Boy / Non-binary / Agender / Not listed (write in) / Prefer not to say
    - 13 and over: Woman / Man / Non-binary / Agender / Not listed (write in) / Prefer not to say
  - Step 7 - What are [Name]’s preferred pronouns? (Mandatory)
    - Options: He/Him / She/Her / They/Them / Other (write in)
    - For Agender or Not listed, They/Them is selected by default, and can be changed.
- Age Groups
  - After Step 3, the platform shall work out [Name]’s age group, using the age of majority for the Client’s state:
    - 18 in most states and Washington, D.C.
    - 19 in Alabama and Nebraska
    - 21 in Mississippi
  - The age groups are:
    - Under 13:
      - Parent-managed only, and never gets their own login.
      - The Oracle gives child-appropriate guidance to the Client.
      - No reproductive, puberty or product questions.
    - 13 up to the age of majority (teen):
      - The Oracle gives education-only guidance, with no product names or recommendations.
      - The Teen Profile Choice is shown.
    - Age of majority to 59: the Oracle gives standard adult guidance.
    - 60 and over: the Oracle adjusts its guidance in conversation, without reproductive status questions.
- Teen Profile Choice (teens only, Mandatory)
  - Shown after Step 3. The Client chooses one option:
    - Teen with their own account
      - The Client sees the Teen account privacy disclaimer, and enters [Name]’s email.
      - An invite is sent (see story 1.5).
      - Steps 4 to 7 are skipped, and [Name] answers their own onboarding questions (see story 2.3).
    - Manage [Name]’s profile myself
      - [Name] doesn’t get a login.
      - The Client completes Steps 4 to 7, and talks to the Oracle on [Name]’s behalf.
      - The teen rules still apply (education only, no products).
- Intake Completion
  - The Oracle shows: “Thank you, [Client’s First Name]. I’m glad you’re here for [Name]. Tell me what’s been going on, and I’ll ask what I need as we go.”
  - The Client taps Start a conversation about [Name], and is taken to Ask the Oracle for [Name] (see story 3.1).
  - The family member version of the Health Consent is shown after the first question (see story 3.1).
- After the Intake
  - The platform shall:
    - Add [Name]’s profile to the profile toggle, and make it the active profile
    - Keep [Name]’s conversations and health profile separate from the Client’s own
  - The Oracle speaks to the Client as the advocate, and refers to [Name] by name and pronouns.
  - The Client can edit [Name]’s details, or remove [Name]’s profile (see story 8.2).
- Saving Progress
  - Each answer is saved as the Client goes.
  - If the Client leaves part-way, they resume from the same step.
Acceptance Criteria:
- Start points: Given the Client is on “Who is this profile for?” or their family profiles, when they select add a family member, then the family intake opens.
- Plan check: Given the Client’s plan doesn’t include family members, when they try to add one, then the upgrade prompt is shown first.
- Step order: Given the intake is open, when the Client moves through it, then the steps appear in order: relationship, first name, date of birth, teen profile choice (teens only), medical advocate consent, sex at birth, gender, pronouns.
- Continue vs auto-advance: Given the first name, date of birth and consent steps, when they’re completed, then the intake moves on only after Continue. The other steps move on when an option is selected.
- Age group: Given the date of birth is entered, when the age is worked out, then [Name] is placed in the right age group, using the age of majority for the Client’s state.
- Teen choice: Given [Name] is a teen, when Step 3 is completed, then the Client must choose Teen with their own account or Manage [Name]’s profile myself.
- Own account: Given the Client chooses Teen with their own account, when they confirm, then the invite in story 1.5 is sent, and Steps 4 to 7 are skipped.
- Managed by the Client: Given the Client chooses Manage [Name]’s profile myself, when they continue, then they complete Steps 4 to 7, and [Name] has no login.
- Under-13 options: Given [Name] is under 13, when Step 6 opens, then Girl and Boy are shown instead of Woman and Man.
- Consent required: Given no consent option is selected, when the Client taps Continue, then they can’t move on.
- Write-in: Given Not listed or Other is selected, when the Client continues, then the text field must be completed.
- Completion: Given the Client finishes, when the last answer is saved, then the completion screen shows their first name and the Start a conversation about [Name] button.
- Active profile: Given the intake is complete, when the Client continues, then [Name]’s profile appears in the profile toggle and becomes active.
- Family limit: Given the Client has used all the family places in their plan, when they try to add another, then they must purchase an add-on first.
- Resume: Given the Client leaves part-way, when they return, then they resume from the same step.
Alternate Scenario:
- Plan doesn’t include family members
  - The Client tries to add a family member.
  - The upgrade prompt is shown, and the intake doesn’t start until they upgrade.
- Family limit reached
  - The Client has added all the family members in their plan.
  - They’re asked to add another member as an add-on.
- Missing first name or consent
  - The Client taps Continue without entering a first name or choosing a consent option.
  - An error is shown, and the Client stays on the step.
- Write-in left empty
  - The Client selects Not listed or Other but leaves the text field empty.
  - An error is shown, and the Client stays on the step.
- Teen with their own account
  - The Client enters [Name]’s email, and the invite is sent.
  - [Name] completes their own onboarding (see story 2.3).
- Client manages the teen’s profile
  - The Client completes Steps 4 to 7, and [Name] has no login.
- Client leaves or cancels
  - The Client closes the app part-way, and resumes from the same step later.
  - If they cancel, no profile is created.
Non-functional Requirements:
- Each step should load within 2 seconds.
- Answers must be saved after each step, so no progress is lost.
- The age-of-majority table can be updated without an app release.
- Family members’ details must be encrypted at rest and in transit, stored in the HIPAA-compliant cloud (Azure), and never shared with analytics tools, ad pixels or Shopify.
- The medical advocate consent must be recorded with the date and time for audit purposes. The option selected isn’t shown to the support team.
- Text on every step must stay readable over the tree background, including on screens with many options.
Validation Rules/Errors:
- First name empty: “What should I call them? Please enter their first name.”
- Date of birth empty or in the future: “Please enter a valid date of birth for [Name].”
- No teen option selected: “Please choose how you’d like to set up [Name]’s profile.”
- No consent option selected: “Please let me know how you’re able to look after [Name]’s health.”
- “Not listed” left empty: “Tell me in your own words how [Name] describes their gender.”
- “Other” pronouns left empty: “Tell me which pronouns you’d like me to use for [Name].”
- Plan doesn’t include family members: “Adding family members is part of the Family plan. Upgrade to add [Name].”
- Family limit reached: “You’ve added all the family members included in your plan. Add another member to continue.”
### 2.3 - Onboarding (Teen)
## Requirement Statement:
As a Teen, I want to complete a short health intake about myself, so that the so that the Oracle can speak to me correctly in my own private conversations.
### Specifications:
Story Details:
- Teen Onboarding Entry
  - Onboarding starts straight after the teen sets up their account from the parent’s invite (see story 1.5).
  - The platform shall:
    - Only show this flow to teens in the teen age group, worked out from their date of birth and state (see story 1.5)
    - Not show the “Who is this profile for?” screen, because teens can’t add family members
- Teen Welcome
  - Before the questions, the teen sees:
    - Welcome to Your Oracle
    - “This is your own private space to learn about your health. Ask me anything you’re curious about, and I’ll help you understand what’s going on and what you can talk about with your provider.”
    - Continue button
- Onboarding Screens
  - Each screen shall include:
    - the question
    - the answer options
    - a Back button to change an earlier answer
  - Screen 1, Sex assigned at birth (Mandatory)
    - Options: Male / Female / Intersex / Prefer not to say
  - Screen 2, Gender (Mandatory): “How would you describe your gender?”
    - Options: Woman / Man / Non-binary / Agender / Not listed (write in) / Prefer not to say
  - Screen 3, Pronouns (Mandatory)
    - Options: He/Him / She/Her / They/Them / Other (write in)
    - For Agender or Not listed, They/Them is selected by default, and can be changed.
- What Onboarding Doesn’t Ask
  - No body, hormone or surgery questions. Any follow-up questions are asked by the Oracle in conversation (see the routing document).
- After Onboarding: The teen sees the same options as an independent Client:
- Start with the Oracle: opens a conversation (see story 3.1)
- Complete my intake: opens the health profile form in My Health (see story 6.1)
- Everything is education only.
- Privacy
  - The platform shall keep the teen’s answers private. The parent can’t see them.
- Saving Progress
  - Each answer is saved as the teen goes.
  - If they leave part-way, they return to the same screen at their next sign-in.
Acceptance Criteria:
- Welcome shown: Given a teen has set up their account, when onboarding opens, then they see the Your Oracle for teens message first.
- No family option: Given a teen is onboarding, when the questions start, then the first question is sex at birth, with no option to add a family member.
- Question order: Given the teen continues, when they answer, then they’re asked sex at birth, gender and pronouns, in that order.
- Mandatory answers: Given a question is unanswered, when the teen tries to continue, then they can’t move on.
- Write-in: Given Not listed or Other is selected, when the teen continues, then the text field must be completed.
- Default pronouns: Given the teen chooses Agender or Not listed, when the pronoun screen opens, then They/Them is selected by default.
- Straight to chat: Given the teen finishes, when the last answer is saved, then they go straight into their own Oracle chat.
- Parent privacy: Given the parent is signed in, when they view their family members, then they can’t see the teen’s answers.
- Resume: Given the teen leaves part-way, when they sign in again, then they return to the same screen, with earlier answers saved.
Alternate Scenario:
- Teen leaves part-way
  - The teen closes the app before finishing.
  - At their next sign-in, they return to the same screen.
- Teen goes back
  - The teen taps Back, and changes an earlier answer.
- Write-in left empty
  - The teen selects Not listed or Other, but leaves the text field empty.
  - An error is shown, and the teen stays on the screen.
Non-functional Requirements:
- Each screen should load within 2 seconds, and each answer should save straight away.
- The teen’s answers must be stored separately from the parent’s account, in the HIPAA-compliant cloud (Azure).
- The teen’s answers must never be shared with analytics tools, ad pixels or Shopify.
- Onboarding must be responsive on Mobile and Web.
Validation Rules/Errors:
- Question not answered: “Please choose an option to continue.”
- “Not listed” left empty: “Tell me in your own words how you describe your gender.”
- “Other” pronouns left empty: “Tell me which pronouns you’d like me to use.”
- Saving failed: “We couldn’t save your answer just now. Please try again.”
### 2.4 - Onboarding (Teen Reaching the Age of Majority)
## Requirement Statement:
As a new adult who has moved from a teen account, I want to check my details, start my free trial and choose a plan, so that I can keep using Your Oracle as an independent Client without starting over.
### Specifications:
Story Details:
- ### Onboarding Entry
  - ### This flow starts straight after the new adult creates their own account from their teen account (see story 1.6).
  - ### The platform shall:
    - ### Move their whole account history to the new account, including their sex at birth, gender, pronouns, conversations and health profile
    - ### Not ask any onboarding questions again
- ### Editing Their Details
  - ### If they want to change their details, they do it in their profile settings (see story 12.1):
    - ### Gender identity and pronouns: can be changed
    - ### Date of birth and sex assigned at birth: can’t be changed
- ### Free Trial
  - ### As a new independent Client, their account starts with the 14-day free trial, like any new Client (see story 9.1).
  - ### During the free trial:
    - ### they can have conversations with the Oracle, for their own profile only
    - ### they can see their history from the teen account
    - ### the other features are shown greyed out, until they subscribe
    - ### adding family members isn’t available
  - ### The Home Dashboard shows how many days are left in the trial, with a Choose a plan button.
- ### Choosing a Plan
  - ### The new adult can choose a plan at any time during or after the trial (see story 10.1):
    - ### Individual: their own profile, with all modules (Wellness Plan, provider notes, My Health and the others)
    - ### Family: their own profile plus 3 family members, with paid add-ons for more
  - ### Once they subscribe, all modules for their plan are unlocked.
  - ### If the trial ends without a subscription:
    - ### they see the upgrade prompt
    - ### their history is kept until they choose to delete it (see story 1.6)
- ### After Account Creation
  - ### The new adult goes straight to the Home Dashboard (see story 4.1), where they can:
    - ### continue a previous conversation, or start a new one (see story 3.1)
    - ### choose a plan
  - ### Adding family members: they can add family members later from their family profiles, once they’re on the Family plan (see story 8.1).
### Acceptance Criteria:
- ### History moved: Given the new adult account is created, when they sign in, then their sex at birth, gender, pronouns, conversations and health profile are all there.
- ### No repeat onboarding: Given the new adult account is created, when they sign in for the first time, then they aren’t asked the onboarding questions again.
- ### Editing details: Given the new adult opens their profile settings, when they edit their details, then they can change their gender identity and pronouns, but not their date of birth or sex at birth.
- ### Free trial starts: Given the new adult account is created, when they reach the Home Dashboard, then the 14-day free trial has started, and the days left are shown.
- ### Trial access: Given the new adult is on the free trial, when they use the app, then they can have conversations and see their history, and other features are greyed out.
- ### Choose a plan: Given the new adult taps Choose a plan, when the plan screen opens, then Individual and Family are shown.
- ### Subscribing: Given the new adult subscribes, when payment succeeds, then all modules for their plan are unlocked.
- ### Family members: Given the new adult isn’t on the Family plan, when they try to add a family member, then the upgrade prompt is shown.
- ### Trial ends: Given the trial ends without a subscription, when they sign in, then they see the upgrade prompt, and their history is kept.
### Alternate Scenario:
- ### Wants to change their details
  - ### The new adult opens their profile settings, and changes their gender identity or pronouns.
- ### Subscribes during the trial
  - ### The new adult chooses a plan before the trial ends.
  - ### All modules for that plan unlock straight away.
- ### Doesn’t subscribe
  - ### The trial ends, and the upgrade prompt is shown.
  - ### Their history is kept until they choose to delete it.
- ### Wants to add a family member
  - ### The new adult is shown the upgrade prompt for the Family plan.
- ### History move fails
  - ### The history is kept safe, and the move is tried again (see story 1.6).
- ### Payment fails
  - ### The new adult stays on the free trial, and can try again.
### Non-functional Requirements:
- ### The account history must move in full from the teen account.
- ### History is never deleted automatically, only when the user asks.
- ### All data is stored in the HIPAA-compliant cloud (Azure), and never shared with analytics tools, ad pixels or Shopify.
- ### Payments go through Stripe, Apple Pay or Google Pay, and card details are never stored by the app.
- ### The Home Dashboard should load within 2 seconds.
### Validation Rules/Errors:
- ### Free trial started: “Your 14-day free trial has started. Choose a plan anytime to unlock everything.”
- ### Family member on the wrong plan: “Adding family members is part of the Family plan. Upgrade to add someone.”
- ### Trial ended: “Your free trial has ended. Choose a plan to keep using Your Oracle.”
- ### Payment failed: “We couldn’t process your payment. Please check your details or try another way to pay.”
- ### Date of birth or sex at birth edit attempted: “Your date of birth and sex assigned at birth can’t be changed.”
## 3. Epic: Ask the Oracle
### 3.1 - Start or Continue a Conversation
### Requirement Statement:
As a Client, I want to start a new conversation or continue a previous one with the Oracle, so that I can get personalised guidance about my health, or my family member’s health,
Specifications:
Story Details:
- Entry Points
  - The Client can open a conversation, on the Mobile App or Web App, from:
    - Start with the Oracle, at the end of onboarding (see stories 2.1 and 2.2)
    - Ask the Oracle, on the Home Dashboard (see story 4.1)
    - a previous conversation in their conversation list
  - Teens with their own account go straight into their chat after signing in (see story 2.3).
  - Every conversation belongs to the active profile (the Client or a family member), shown at the top. The Client can switch profiles using the profile toggle (see story 4.2).
- New Conversation Screen
  - The screen shall include:
    - Top bar: a Back button, and the active profile’s initial, which opens the profile toggle
    - AI header, always visible once the chat begins: “You’re chatting with Oracle, an AI system, not a human or a licensed clinician.”
    - Oracle avatar: the tree
    - Opening question:
      - For the Client: “How are you feeling today?”
      - For a family member: “How is [Name] feeling today?”
    - Suggested starter questions: scrollable chips based on the profile, for example “Why am I so exhausted all the time?”, “My labs look normal but I feel terrible” or “Hormone imbalance”. For a family member, they use the family member’s name and pronouns.
    - Symptoms: the Hypothalamus Symptom Check, asked once on this screen
    - Message box:
      - Placeholder: “Ask me anything”
      - Microphone: voice-to-text (Release 2)
      - Send: active once a message is typed or symptoms are selected
  - There’s no upload option. Clients can type lab values into the message instead.
  - The typed message and the ticked symptoms are read together, not one instead of the other.
- First Conversation
  - Step 1: the Client shares their concern by typing, tapping a starter question, or selecting symptoms.
  - Step 2: the safety check runs on the message first (see story 3.2).
    - If an emergency or crisis is detected: the safety response is shown straight away, before the Health Consent. Once the Client selects an option (for example, I’m safe now), the Health Consent appears.
    - If not: the Health Consent appears straight away.
  - Step 3: the Health Consent appears before the Oracle gives any guidance, once per profile:
    - For the Client:
      - Title: “Can the Oracle use your health information?”
      - Checkbox: “I accept the Health Consent”, linked to the full document
      - Button: Agree and continue
    - For a family member:
      - Title: “Can the Oracle use [Name]’s health information?”
      - Checkbox: “I confirm I’m [Name]’s medical advocate, and I accept the Health Consent”
      - Button: Agree and continue
    - Teens with their own account: don’t see it, because the parent gave consent.
  - Step 4: the conversation continues, following the question routing below.
-

  - Step 3: the conversation continues, following the question routing below.
- Returning Client
  - The Client sees their recent conversations for the active profile, each with its topic and date (for example, “Waking at 3am · 3 days ago”).
  - Continue a conversation:
    - the full history is displayed
    - the Oracle picks up where they left off, for example: “Welcome back, [First Name]. Last time we talked about waking at 3am. How have your nights been since then?”
  - Start a new conversation: opens the New Conversation Screen, without the Health Consent again.
  - In both cases:
    - The Oracle asks “Any new medications since we last spoke?” when medicines matter to the concern.
    - For adults and advocates, it checks in on Wellness Plan items that are due. For example: “You were going to ask your provider about a thyroid panel. Did you manage to get that done?”
- ⚑ Question Routing: Age, Sex at Birth, Body and Gender

Link: [Health Intake Routing](https://docs.google.com/document/d/1xqem26u29VbeD16zQ6rFeW-b0A52DCLQq7xh6rFbUK0/edit?usp=sharing)

  - Before its first reply, the platform shall load the active profile:
    - Age group: from the date of birth, and the age of majority for the state given at sign-up (18 in most states, 19 in Alabama and Nebraska, 21 in Mississippi)
    - Sex assigned at birth: Male, Female, Intersex or Prefer not to say
    - Gender identity and pronouns: Woman, Man, Non-binary, Agender, Not listed, Prefer not to say (Girl and Boy for under-13s)
    - Profile type: the Client, a family member, or a teen with their own account
    - Everything already answered: in the health profile, past conversations, logged visits and the Wellness Plan
  - Routing by age group:
    - Under 13 (family member only):
      - The advocate answers.
      - The Oracle asks about medications and allergies first, then growth, milestones, sleep, school and safety when relevant.
      - No reproductive, puberty, Genesis Gold or product questions.
    - Teens (13 up to the age of majority):
      - Teen-friendly, non-judgemental wording.
      - Puberty or periods first, as relevant, then medications and supplements.
      - Later, when relevant: home, sleep, school, wellbeing and safety, and “Is there anything you’re worried about?”
      - Everything is education only:
        - no Genesis Gold question
        - no product names or recommendations
        - no dosing
        - no interpretation of their own lab results
      - They get the guidance summary, Wellness Plan and provider notes (see stories 3.3, 3.4 and 7.1), written as education.
      - Teen with their own account: sees these in their own account. The parent can’t see them.
      - Teen managed by a parent: the parent sees them, as the teen’s advocate.
    - Age of majority to 59: the full adult questions for their body.
    - 60 and over:
      - No reproductive status question.
      - For a female body, the Oracle still asks about HRT.
      - Medications and supplements are asked early.
  - Routing by body (sex at birth and “Your body”):
    - Body questions follow the “Your body” answers when they’re given, otherwise sex assigned at birth:
      - Uterus or ovaries (or female at birth): periods, menopause and HRT
      - Testes or prostate (or male at birth): puberty, growth and fertility
      - Both (or intersex at birth): puberty and periods, with “I’m not sure / I want to describe” always available
    - Sex at birth “Prefer not to say” and “Your body” skipped: general questions only. The Oracle may ask gently later, and the Client can say no.
  - Routing by gender identity:
    - Gender identity sets the wording and pronouns only. It never decides the body questions.
    - Non-binary, Agender and Not listed use neutral wording (they/them unless the Client chose otherwise).
  - Follow-up body questions (asked in conversation):
    - They’re part of the health profile, and are also available as optional in My Health (see story 6.1).
    - The Oracle shows a privacy notice first, and every question can be skipped.
    - Path A, sex at birth is Intersex or Prefer not to say: intersex variation → “Your body” → hormone history → surgery history.
    - Path B, gender differs from sex at birth:
      - “Your body” → puberty → gender-affirming hormones → provider → context
      - then the questions for the body they were born with (hormone details, surgeries, and periods if “Uterus” was ticked)
      - The version follows their sex assigned at birth.
      - Teens in Path B only get “Your body”, puberty, hormones and provider.
    - Gender “Prefer not to say” (sex at birth Male or Female): “Your body” only, then the standard questions for their body.
    - Gender matches sex at birth: no follow-up questions.
  - Family members:
    - The Oracle speaks to the Client as the advocate, and words every question about the family member, using their name and pronouns. For example: “Has Azka started her periods?”
    - Questions follow the family member’s age group, body and gender, not the Client’s.
- How Questions Are Asked
  - The concern comes first. The Oracle understands the concern before asking any profile questions. For example: “How long has this been going on?”
  - “Asked first” questions: only when they relate to the concern. Medication and supplement questions are asked once, before any guidance.
  - Follow-up questions come from the answer before them, as the routing document sets out. For example:
    - “Post-menopausal” → “At what age was your last period?”
    - “Surgically menopausal” → hysterectomy and ovaries questions
    - Peri-, post- or surgically menopausal → “Are you currently on hormone therapy (HRT)?”
  - “Asked later” questions: only when they help the current concern. For example:
    - insomnia → sleep and stress
    - weight concerns → diet, exercise and lean body mass
  - Symptom checklists: follow the body (“Your body” answers, or sex at birth). The Client can mark any item N/A.
  - Never repeat: the Oracle never asks for something already answered. If a saved answer may be out of date, it confirms instead: “Last time you mentioned you were peri-menopausal. Is that still right?”
  - One question at a time, with tap-to-answer options (Yes / No, single choice, sliders, the Add Medicine widget), while still allowing a typed answer.
- Other Conversation Behaviour
  - Lab values:
    - The Oracle explains what the test measures, the reference range on the report, what can affect it, and what to ask their provider.
    - It never says what the number means for that person.
  - Medicines:
    - The Oracle provides link to Drugs.com for medicine information.
    - It advises speaking to a provider or pharmacist if there may be an interaction.
    - It never tells the Client to stop, start or change a medicine.
    - It never gives a dose for a prescription medicine.
  - Products and links (adults only):
    - When relevant, the Oracle links to test links: links to tests Deborah has already supplied, which the Client can look into for themselves
    - No test ordering: there’s no test-ordering feature in the app. The Oracle only shares links Deborah has supplied, as information
    - When Genesis products/affiliate links are recommended, one disclosure box at the end of the reply says: “Genesis Health Products, which makes Your Oracle, also makes and sells Genesis Gold®, Sacred Seven® and Gen-Pro®.”
    - Genesis products: when the Oracle recommends Genesis Gold®, Sacred Seven® or Gen-Pro®, it gives the basic directions from the label, for example “How to take it (from the label): 2 pumps, twice daily.” It doesn’t work out an amount for the Client, or change the dose.
  - Lean body mass: for weight, diet or nutrition concerns, the Oracle asks for height, weight and measurements, and calculates lean body mass (not BMI).
  - Provider referrals: only when relevant. Not every conversation ends with “see your provider”.
  - Education reminders: the Oracle reminds the Client from time to time that this is health education.
  - Saving to the profile: the Oracle automatically saves the symptoms or medicines based on the questioning. The client can change anything they want to by going to my health section.
  - In-chat cards:
    - a skippable “Complete your health profile” card
    - a “Consult with support team” card when asked (see story 10.1)
  - Outside the Oracle’s content: the Oracle offers to send the question to the support team, and logs it as a Knowledge Gap.
  - Safety: every message is checked before the Oracle replies (see story 3.2).
  - Guidance summary: Guidance summary: once there’s enough context, for every profile, including teens, where it’s education only (see story 3.3).
  - Free trial: when it ends without a subscription, the message box is locked, and the upgrade prompt is shown (see story 9.1).
- Example Conversations
  - Woman, 47, female body, night sweats:
    - The Oracle asks how long the night sweats have been going on.
    - It asks “Which best describes you now?” The Client taps “Peri-menopausal”.
    - It asks about HRT, then medications and supplements, then offers the female checklist.
  - Teen, 16, own account, male body, always tired:
    - The Oracle asks about puberty, then medications and supplements.
    - Later, sleep and school questions.
    - Education only, with no product suggestions.
  - Woman, 64, assigned male at birth (Path B), insomnia:
    - After the privacy notice: “Your body” (she ticks “Prostate”), then puberty and gender-affirming hormones.
    - Then medications, supplements and sleep questions.
    - Prostate questions still apply. No period questions.
  - Advocate for a child, 8, stomach aches:
    - The Oracle asks who cares for Leo, then about medications and allergies.
    - Later, food, drink and school questions.
    - No puberty or product questions.
Acceptance Criteria:
- Start points: Given the Client is at the end of onboarding, on the Home Dashboard or in their conversation list, when they choose a conversation option, then the conversation opens.
- AI header: Given a conversation has started, when the screen is shown, then the AI header is always visible.
- Symptoms once: Given the Client ticks symptoms and types a message, when they send it, then both are read together, and symptoms aren’t asked again.
- No uploads: Given the conversation screen, when it’s shown, then there’s no upload option.
- Health Consent: Given an adult or advocate sends their first message for a profile, when it’s sent, then the Health Consent appears once. Teens with their own account don’t see it.
- Concern first: Given a new conversation, when the Oracle replies, then it asks about the concern before any profile questions.
- Age routing: Given a profile’s date of birth and state, when questions are asked, then they follow that age group’s rules.
- Body routing: Given “Your body” answers exist, when body questions are asked, then they follow those answers. Otherwise, they follow sex at birth.
- Gender routing: Given a gender identity, when the Oracle words a question, then it uses the profile’s pronouns, and gender never changes which body questions are asked.
- Follow-up questions: Given a Path A, Path B or gender “Prefer not to say” profile, when body questions become relevant, then the privacy notice is shown, and “Your body” is asked first.
- Teens: Given a teen profile, when the Oracle replies or creates a summary, Wellness Plan or provider notes, then everything is education only, with no product names, dosing or interpretation of their own lab results.
- Never repeat: Given an answer is already saved, when it’s relevant again, then the Oracle doesn’t ask it again.
- Lab values: Given the Client types a lab value, when the Oracle replies, then it explains the test without interpreting the number.
- Test links: Given a test is relevant to the conversation, when the Oracle mentions it, then it shares a link Deborah has supplied, with no ordering in the app.
- Label directions: Given an adult receives a Genesis product recommendation, when the Oracle replies, then it gives the basic directions from the label, without working out an amount for the Client or changing the dose.
- No prescription dosing: Given the Client asks about a prescription medicine, when the Oracle replies, then it doesn’t give a dose.
- Products and Links: relevant product links should be provided wherever in the conversation and external links like [drugs.com](http://drugs.com)
- Disclosure: Given an adult receives a Genesis product recommendation, when the reply ends, then one disclosure box, with the ownership sentence, is shown at the bottom.
- Saving: Given the Oracle learns something lasting, when it wants to save it, then it asks the Client first.
- Resume: Given the connection drops, when the Client returns, then the conversation resumes where it left off.
Alternate Scenario:
- Health Consent not accepted
  - The Oracle can’t reply until the Client accepts.
- Client skips the follow-up questions
  - Body questions follow sex at birth.
  - The Oracle doesn’t ask again in that conversation.
- Client types a long story
  - The Oracle picks the answers out of it, instead of asking each question again.
- Saved answer out of date
  - The Oracle confirms it, for example when the Client is now post-menopausal.
- Client switches to a family member mid-way
  - A separate conversation opens for that profile.
- Teen asks about Genesis products
  - The Oracle gives education only, with no product names.
- Client mentions a medicine that may interact
  - The Oracle gives a link to Drugs.com, and advises speaking to a pharmacist or provider.
- Client asks how much of a Genesis product to take
  - The Oracle gives the basic directions from the label.
- Client asks for a dose of a prescription medicine
  - The Oracle doesn’t give one, and suggests asking their provider or pharmacist.
- Client asks the Oracle to order a test
  - The Oracle explains it can’t order tests, and shares the link so the Client can look into it themselves.
- Client doesn’t know their measurements
  - The Oracle continues without lean body mass.
- Question outside the Oracle’s content
  - The Oracle offers to send it to the support team.
- Emergency signs
  - The safety path starts (see story 3.2).
- Free trial ends mid-conversation
  - The message box is locked, and the upgrade prompt is shown.
- Lost connection
  - The conversation resumes where it left off.
Non-functional Requirements:
- The Oracle should start replying within 3 seconds.
- Question routing must follow the Health Intake Routing document, kept as a configurable rule set that can change without an app release.
- Every message and answer is saved as it’s sent, and conversations are kept separate for each profile.
- The Oracle uses only Deborah’s approved content, with no open-internet retrieval.
- Gender, sex at birth, body, hormone and surgery answers are encrypted, stored in the HIPAA-compliant cloud (Azure), and never sent to analytics tools, ad pixels or Shopify.
- Teen conversations can never be seen from the parent’s account.
- The Oracle follows the AI guardrails: no diagnosing, no prescribing, no dosing for prescription medicines (Genesis products follow the directions on the label), and no wording that implies a healthcare licence (California AB 489).
- Label directions come only from the knowledge base, word for word.
Validation Rules/Errors:
- Health Consent not accepted: “Please accept the Health Consent so I can help you.”
- Confirming saved information: “Last time you mentioned [answer]. Is that still right?”
- Checklist offer: “Would you like to go through a quick checklist of other symptoms?”
- Possible medicine interaction: “[Medicine] can interact with [existing medicine], so please check with your pharmacist or provider.”
- Measurement not valid: “That measurement doesn’t look quite right. Could you check it for me?”
- Question outside the Oracle’s content: “I’m not able to guide you on that one, but I don’t want to leave you without an answer. Shall I send it to the support team? They’ll get back to you within one business day.”
- Free trial ended: “Your free trial has ended. Choose a plan to keep talking with me.”
- Lost connection: “It looks like you’ve lost connection. Don’t worry, I’ll pick up where we left off.”
- Label directions: “How to take it (from the label): [directions].”
- Prescription dose asked for: “I can’t give a dose for a prescription medicine. Your provider or pharmacist can help with that.”
- Disclosure box: “Genesis Health Products, which makes Your Oracle, also makes and sells Genesis Gold®, Sacred Seven® and Gen-Pro®.”
- Ordering a test asked for: “I can’t order tests, but here’s a link where you can find out more about it.”
### 3.2 -  Escalation / Emergency Detection
### Requirement Statement:
As a Client, I want the Oracle to recognise when what I’m describing is an emergency or urgent, so that I’m guided to the right care straight away and The Oracle’s team is made aware.
### Specifications:
Story Details:
- Safety Check on Every Message
  - Before replying, the platform shall check every message for signs of an emergency, a mental health crisis, or an urgent concern.
  - The Oracle reads the whole message in context, not single words.
    - For example, “I’m bleeding a lot, but I’m definitely not hemorrhaging” must not trigger an emergency just because of the word “hemorrhage”.
  - If the Client says the Oracle got it wrong, the Oracle apologises and continues the conversation.
- Three Levels
  - Emergency (for example, chest pain with shortness of breath, signs of a stroke, or very heavy bleeding):
    - The Oracle tells the Client to call 911 now.
    - It shows two options: I’ve called for help and I’m safe now.
    - The conversation can’t continue until one is selected.
  - Crisis (for example, thoughts of self-harm or suicide):
    - The Oracle responds with care, and shares the 988 Suicide & Crisis Lifeline (call or text 988).
    - In immediate danger, it tells the Client to call 911.
    - It shows I’ve reached out for help and I’m safe now before continuing.
  - Urgent (for example, symptoms that need a provider soon, but not an emergency):
    - The Oracle advises seeing a provider within 24 hours.
    - The conversation continues.
- Emergency Numbers
  - Your Oracle is for U.S. users, so the Oracle shows U.S. numbers: 911, 988, and Poison Control (1-800-222-1222) where relevant.
  - If the device’s location shows the Client is outside the U.S., the Oracle tells them to call their local emergency number.
  - No phone number is collected or used.
- After an Emergency or Crisis
  - No checking on the Client: the platform doesn’t follow up, call or send check-ins after an emergency or crisis. Acting on the advice is the Client’s responsibility.
  - Recorded for review: an escalation is recorded for the support team to review, for example to check for false alarms (see Super Admin story 4.1). The team doesn’t contact the Client about it.
  - When the Client comes back: the Oracle can ask how things went, for example “What happened at the emergency room?”
- Family Members
  - The Oracle speaks to the advocate about the family member, for example “Call 911 for [Name] now.”
  - The escalation is linked to the family member’s profile.
- Teens With Their Own Account
  - The same safety path applies.
  - Emergency or crisis: the parent is told that their teen may need help.
  - To protect the teen’s privacy, the parent isn’t shown the conversation.
Acceptance Criteria:
- Every message checked: Given the Client sends a message, when it’s received, then it’s checked for emergency, crisis or urgent signs before the Oracle replies.
- Context, not keywords: Given a message mentions a symptom word but makes clear it isn’t an emergency, when it’s checked, then no emergency is triggered.
- Emergency: Given an emergency is detected, when the Oracle replies, then it tells the Client to call 911, and the conversation can’t continue until they select I’ve called for help or I’m safe now.
- Crisis: Given a crisis is detected, when the Oracle replies, then it shares 988 (and 911 for immediate danger), and the Client must select an option before continuing.
- Urgent: Given an urgent concern is detected, when the Oracle replies, then it advises seeing a provider within 24 hours, and the conversation continues.
- Outside the U.S.: Given the device’s location is outside the U.S., when an emergency is detected, then the Client is told to call their local emergency number.
- No follow-up: Given an emergency or crisis has been handled in the conversation, when the conversation ends, then no follow-up, call or check-in is sent.
- Recorded: Given an emergency or crisis or urgent case, when it’s detected, then an escalation is recorded for the support team to review.
- Family member: Given the active profile is a family member, when an emergency is detected, then the Oracle speaks to the advocate, and the escalation is linked to the family member’s profile.
- Teen emergency or crisis: Given a teen with their own account has an emergency or crisis, when it’s detected, then the parent is told their teen may need help, without seeing the conversation.
Alternate Scenario:
- False alarm from a single word
  - The Client uses a word like “hemorrhage”, but says it isn’t an emergency.
  - The Oracle doesn’t escalate, and continues normally.
- The Oracle gets it wrong
  - The Client says it isn’t an emergency.
  - The Oracle apologises, and continues the conversation.
- Client selects I’m safe now
  - The conversation continues.
- Client doesn’t respond
  - The conversation stays paused until they choose an option.
- Client never comes back
  - No follow-up is sent.
- Client is travelling outside the U.S.
  - The Oracle tells them to call their local emergency number.
- Location unavailable
  - The Oracle shows the U.S. numbers.
- Emergency about a family member
  - The Oracle speaks to the advocate.
- Teen emergency or crisis
  - The teen sees 911 or 988.
  - The parent is told their teen may need help.
Non-functional Requirements:
- The safety check must finish before any reply is shown.
- Escalation rules are tested against a set of test cases before every release, including false alarms. Deborah is providing more test cases (Session 9).
- Escalation records are stored in the HIPAA-compliant cloud (Azure), and retained for at least six years (BAA Section 13).
- The parent’s notification about a teen’s emergency or crisis contains no conversation content.
- The Oracle never diagnoses. It only directs the Client to the right help.
Validation Rules/Errors:
- Emergency: “This could be a medical emergency. Please call 911 now.”
- Crisis: “I’m really glad you told me. You don’t have to go through this alone. Please call or text 988 to talk to someone now. If you’re in immediate danger, call 911.”
- Urgent: “This is something to get checked soon. Please contact your provider within the next 24 hours.”
- Outside the U.S.: “Please call your local emergency number now.”
- Option not selected: “Please let me know you’re safe before we continue.”
- Oracle got it wrong: “I’m sorry, I misunderstood. Thank you for letting me know. Let’s carry on.”
- Parent told about a teen’s emergency: “[Name] may need urgent help. Please check on them now. If you think they’re in danger, call 911.”
- Parent told about a teen in crisis: “[Name] may need some support right now. Please check in with them. If you think they’re in danger, call 911. You can also call or text 988.”
### 3.3 -  View Personalised Guidance Summary
### Requirement Statement:
As a Client, I want to see a personalised guidance summary once the Oracle understands my concern, so that I know what may be happening, what I can do now, and what to ask my healthcare provider.
### Specifications:
Story Details:
- When the Summary Appears
  - Once the Oracle has enough context from the conversation, it shares the guidance summary automatically, without asking first.
  - The Oracle introduces it with a short line, for example: “Thank you for sharing all of that. Here’s what I’m seeing.”
  - Asking early: the Client can ask for the summary early, for example “Tell me what you think so far”. The Oracle then shares a First Look (see below).
  - Not every topic is a new summary: when the Client explores another symptom in the same conversation, the Oracle answers it in the conversation and updates the existing summary when relevant. It doesn’t produce a new full summary each time (Session 10).
- Summary Sections
  - The summary is shown section by section, for easy reading, in this order:
    - What I’m Hearing: a short recap of the concern, symptoms and relevant history the Client shared.
    - Hypothalamic Connection: how the concern links back to the hypothalamus. Shown only when there’s a clear link.
    - What This May Mean: possible explanations, in plain, educational language. Never a diagnosis.
    - Questions for Your Provider: questions the Client can take to their healthcare provider.
    - Tests Worth Discussing: tests to raise with a provider, and why each one matters. For discussion only, not orders.
      - If the Client typed lab values, this section explains what each test measures and what can affect it, but never what the number means for them.
      - Where Deborah has supplied a link for a test, it’s shown as an information link. Nothing is ordered through the app.
    - What You Can Do Now: practical steps, such as sleep, diet or the CALM practice, with links to the matching section of the Wellness Protocols library rather than repeating them in full
    - Recommendations (adults only): where relevant, product suggestions such as Genesis Gold®, with links to the Genesis Shopify store, Deborah’s Fullscript store, Drugs.com (for medicines), links to tests Deborah has supplied or other recommended products. Genesis products include the basic directions from the label, for example “How to take it (from the label): 4 g per 50 lb of body weight, daily.”
    - Recommended Next Steps: what to do next. This may include seeing a provider, but only when it’s relevant. Not every summary ends with a provider visit.
    - A Word from the Oracle: a short, warm, encouraging note in the Oracle’s voice.
  - Disclosure box (when Genesis products/affiliate links are recommended):
    - one box at the very end, below the recommendations (Session 9)
    - says: “Genesis Health Products, which makes Your Oracle, also makes and sells Genesis Gold®, Sacred Seven® and Gen-Pro®.”
    - not repeated after each product mention
  - Disclaimer: every summary ends with: “This is educational guidance from the Oracle, an AI system. It isn’t a diagnosis or prescription.”
  - No Deborah name, photo or credentials appear anywhere in the summary.
- First Look (Early Summary)
  - If the Client asks before the Oracle has enough information, it shares what it can say so far.
  - It explains what else it needs to know, and completes the full summary once the Client answers.
- Updating the Summary
  - If the Client shares more information after the summary is shown, the Oracle updates it.
- Products
  - Products are mentioned only in the Recommendations section, never in the explanation of tests or lab values (Session 9).
  - Product suggestions include the note: “Genesis Gold® contains no hormones. Please let your provider know if you start it alongside any medication.”
  - Never shown to teens or children, or during an active emergency (see story 3.2).
- Teens
  - Teens get the full summary, written as education only:
    - no product names or recommendations
    - no dosing
    - no interpretation of their own lab results
  - Teen with their own account: sees the summary in their own account. The parent can’t see it.
  - Teen managed by a parent: the parent sees it, as the teen’s advocate.
- After the Summary (Subscribed Client)
  - The Client can Download Summary (PDF) to keep, print or share.
  - Below the summary, the Client sees a checklist of new details the Oracle picked up, such as a new medication or a symptom. These are saved automatically, because the Client accepted the Health Consent.
  - Disclaimer (shown above the list): “Here’s what I’ve added to your health profile from our conversation. If anything isn’t right, you can change or remove it in My Health.”
  - A Review in My Health button opens the health profile (see story 6.1).
  - If nothing new was learned, the list isn’t shown.
  - New recommendations are added to the top of the Wellness Plan (see story 7.1).
  - The summary is saved to My Visit Notes for that conversation (see story 5.1).
  - A follow-up check-in is sent two weeks later, asking how the Client is doing (see story 12.1).
  - The Client can choose:
    - Create notes for my provider (see story 3.4), offered when a provider visit is relevant
    - Continue the conversation
    - Consult with support team (see story 10.1)
- Free Trial Client
  - The Client sees the full summary in the app.
  - Download Summary (PDF) is locked, with an upgrade prompt.
  - The health details are still saved. The Review in My Health button shows the upgrade prompt, because My Health is greyed out during the trial.
  - Wellness Plan updates are locked, with an upgrade prompt.
  - When the trial ends, the Client sees the upgrade prompt (see story 9.1).
- Family Members
  - The summary is written to the Client as the advocate, using the family member’s name and pronouns.
  - The family member’s age shapes the content. For example, teens get education only, and older adults get age-adjusted guidance.
Acceptance Criteria:
- Shown automatically: Given the Oracle has enough context, when it replies, then it shares the summary automatically, with a short introduction.
- No repeat full summaries: Given a summary already exists in the conversation, when the Client explores another symptom, then the Oracle answers in the conversation and updates the summary when relevant, without creating a new full summary.
- Section order: Given the summary is shown, when the Client reads it, then the sections appear in the agreed order, one at a time.
- Hypothalamic Connection: Given the concern has no clear link to the hypothalamus, when the summary is shown, then that section is left out.
- No diagnosis: Given any summary, when it’s shown, then it never states a diagnosis, prescribes treatment or orders tests.
- Lab values: Given the Client typed lab values, when the summary is shown, then it explains the tests without interpreting the numbers.
- Wellness Protocols: Given What You Can Do Now is shown, when it mentions a protocol, then it links to the matching section of the Wellness Protocols library instead of repeating it.
- Products: Given an adult, when products are relevant, then they appear only in Recommendations, with the basic directions from the label and the product note.
- Disclosure box: Given Genesis products/affiliate links were recommended, when the summary ends, then one disclosure box, with the ownership sentence, is shown below them.
- Disclaimer: Given any summary, when it ends, then the educational disclaimer is shown.
- Provider visit only when relevant: Given a concern that doesn’t need a provider, when the summary is shown, then it doesn’t recommend a provider visit.
- First Look: Given the Client asks early, when the Oracle doesn’t have enough information, then it shares a First Look, and the full summary follows later.
- Teens: Given a teen profile, when the summary is shown, then it’s education only, with no products, dosing or lab interpretation.
- Subscribed Client: Given a subscribed Client, when the summary is shown, then they can download it, see what’s been added to their health profile, and see new recommendations added to their Wellness Plan.
- Added to the health profile: Given the Oracle learned new health details in the conversation, when the summary is shown, then the details are already saved, and listed below the summary with the disclaimer and a Review in My Health button.
- Nothing new: Given the Oracle learned nothing new, when the summary is shown, then the list isn’t shown.
- Free trial: Given a free trial Client, when they view the summary, then download and Wellness Plan updates show an upgrade prompt.
- Follow-up: Given a summary was shared, when two weeks pass, then the Client receives a follow-up check-in.
Alternate Scenario:
- Client asks early
  - The Oracle shares a First Look, and completes the summary once it has more information.
- Client shares more afterwards
  - The Oracle updates the summary.
- Client explores another symptom in the same conversation
  - The Oracle answers in the conversation, and updates the summary when relevant.
- No hypothalamic link
  - The Hypothalamic Connection section isn’t shown.
- Teen profile
  - The summary is education only, with no products.
- Something added isn’t right
  - The Client taps Review in My Health, and changes or removes it there.
- Free trial Client taps Download or the Wellness Plan
  - The upgrade prompt is shown.
- Emergency during the conversation
  - The safety path is followed instead (see story 3.2).
- PDF download fails
  - The Client can try again.
Non-functional Requirements:
- The summary should be generated within 10 seconds of the Oracle having enough context.
- The PDF should be ready to download within 5 seconds.
- Summary content must come only from Deborah’s approved content and the Client’s own information.
- The summary follows the AI guardrails: no diagnosis, no prescriptions, no dosing for prescription medicines (Genesis products follow the directions on the label), and no wording that implies a healthcare licence (California AB 489).
- Product links only open the store or partner site. No health information is sent to Shopify or any partner.
- Summaries and PDFs are encrypted, and stored in the HIPAA-compliant cloud (Azure).
Validation Rules/Errors:
- Summary introduction: “Thank you for sharing all of that. Here’s what I’m seeing.”
- Added to the health profile: “Here’s what I’ve added to your health profile from our conversation. If anything isn’t right, you can change or remove it in My Health.”
- Product note: “Genesis Gold® contains no hormones. Please let your provider know if you start it alongside any medication.”
- Free trial, download locked: “Subscribe to download and keep your guidance.”
- Free trial, Wellness Plan locked: “Subscribe to get your personal Wellness Plan.”
- Download failed: “We couldn’t download your summary. Please try again.”
- Disclosure box: “Genesis Health Products, which makes Your Oracle, also makes and sells Genesis Gold®, Sacred Seven® and Gen-Pro®.”
### 3.4 -  Generate Provider-Ready Notes from Conversation
### Requirement Statement:
As a Client, I want the Oracle to turn our conversation into notes for my healthcare provider, so that I can go into my appointment prepared, with my symptoms, history, questions and requested tests clearly set out.
### Specifications:
Story Details:
- When Notes Can Be Created
  - The Client can create provider-ready notes:
    - by tapping Create notes for my provider under the guidance summary (see story 3.3), which is offered when a provider visit is relevant
    - when the Oracle offers them during an urgent escalation (see story 3.2)
    - by asking in the conversation, for example “Can you make notes for my doctor?”
  - Notes are always created from a conversation, and belong to that conversation and the active profile.
  - If the Client asks before the Oracle has enough information, the Oracle asks a few more questions first.
- Appointment Card
  - The appointment card shall include:
    - Specialty: dropdown (Mandatory), with the options from the “For My Provider” template:
      - Primary Care / Family Medicine
      - OB-GYN
      - Endocrinology
      - Integrative / Functional Medicine
      - Rheumatology
      - Neurology
      - Urology
      - Cardiology
      - Psychiatry
      - Other (opens a text box to write in any other specialty)
    - Provider name: text field (Optional)
    - Appointment date: date picker (Optional)
  - The specialty is required because it shapes the notes: a provider can only order tests or refer within their own scope (Session 7).
  - The provider’s name and the date are optional, because only the type of provider is needed (Sessions 4 and 7).
- Appointment Details: Two Scenarios
  - Scenario A, the Client already mentioned the appointment:
    - The Oracle picks up what the Client said, for example “I’m seeing my cardiologist on Friday”.
    - It confirms before creating the notes: “You mentioned you’re seeing your cardiologist on Friday. Shall I prepare the notes for that visit?”
    - Yes: the notes are created using what the Oracle picked up.
    - Change details: the appointment card opens, filled in, for the Client to correct. A specialty that isn’t on the list is filled in under “Other”.
  - Scenario B, the appointment hasn’t been mentioned:
    - Step 1: the Oracle asks: “Have you booked an appointment with a provider?”
      - Yes: the appointment card opens, empty, for the Client to fill in.
      - Not yet: the Oracle suggests the type of provider to see, based on the conversation, and uses it as the specialty.
      - Skip: the notes are created without appointment details, for a primary care provider.
    - Step 2: the Client taps Create my notes.
- Editing Appointment Details
  - Appointment details can be edited at any time, from the Edit appointment button on the notes in the conversation, or from My Visit Notes (see story 3.5).
  - If the specialty changes: the Oracle updates the questions, requested tests and referral advice, and tells the Client.
  - If the provider name or date changes: the header is updated, and the reminders are rescheduled.
  - If a date is removed: the reminders are cancelled, and the 7-day booking follow-up is scheduled instead.
  - Notes created with “Not yet” or “Skip” can have appointment details added later.
- Notes Tailored to the Specialty
  - The questions and requested tests are written for the type of provider the Client is seeing, or the one the Oracle suggested.
  - For “Other”: the Oracle interprets what was written (for example, “naturopath”). If it can’t tell, it asks one clarifying question.
  - If that provider is unlikely to address part of the concern: the notes say so and suggest a referral. For example: “You may need a referral to an endocrinologist for a full thyroid panel.”
  - If the Client is seeing a primary care provider first (for example, under an HMO): the notes say which specialist referral to ask for.
- Notes Sections (“For My Provider” template)
  - Header:
    - First name: the Client’s first name, or the family member’s first name. No last name is collected (Session 9).
    - Date of birth
    - Specialty
    - Provider name and appointment date, shown only if known
  - What this is: “A summary prepared by Your Oracle based on my symptoms, history and our conversation. I am bringing this to help my provider understand the full picture.”
  - 1. Chief complaint: the main concern, how long it has been going on, and key symptoms.
  - 2. Clinical context: what the Oracle identified, in plain clinical language, including relevant history, medications and the hypothalamic connection where there is one.
    - Lab values the Client typed are listed as the Client reported them, with no interpretation. This applies to every account (Deborah’s email, 28 Oct).
  - 3. Labs I am requesting: primary tests and tests to also request, each with a short reason. Written as the Client’s request, never as an order.
  - 4. Questions for my provider: tailored to the specialty.
  - 5. Current medications and supplements:
    - taken from the health profile and the conversation
    - adults only, if the Client takes or is starting Genesis Gold®: “Genesis Gold® is a nutraceutical formulation designed to support hypothalamic function. It contains no hormones.I would like your awareness as I begin a trial of at least 90 days.”
  - Red flags screened by the Oracle: any urgent signs found in the conversation, or “No urgent red flags identified in this session.”
  - The Oracle’s recommendation to me: the suggested next steps from the guidance.
  - Disclosure box (only if the notes mention Genesis products/affiliate links): one box at the end, saying: “Genesis Health Products, which makes Your Oracle, also makes and sells Genesis Gold®, Sacred Seven® and Gen-Pro®”
  - Disclaimer: “This document was prepared by Your Oracle, an AI health education tool developed by Genesis Health Products Inc. It is not a diagnosis, a prescription, or a substitute for professional medical care”
  - No Deborah name, photo or credentials appear in the notes.
- Family Members, Teens and Children
  - Family member: the first name and date of birth are the family member’s, and the notes show they were prepared by the Client as medical advocate.
  - Teens: notes are written as education only, with no products or dosing.
    - Teen with their own account: sees the notes in their own account. The parent can’t see them.
    - Teen managed by a parent: the parent sees them, as the teen’s advocate.
  - Children under 13: the notes never mention Genesis Gold® or any product.
  - Wording uses the profile’s pronouns.
- After the Notes Are Created
  - The notes open in the conversation, with an Edit appointment button, and are saved to My Visit Notes for that conversation.
  - Viewing, downloading, printing and copying are covered in story 3.5.
  - Appointment date known: the Client gets a reminder before the appointment, and a follow-up after it asking how it went (see story 12.1).
  - No appointment date: the Client gets a booking follow-up after 7 days (see story 12.1).
Acceptance Criteria:
- Creating notes: Given the Client is in a conversation, when they tap Create notes for my provider, accept the Oracle’s offer during an urgent escalation, or ask for notes, then the notes flow starts.
- Appointment card: Given the appointment card is open, when the Client fills it in, then specialty is mandatory, “Other” needs a written specialty, and provider name and date are optional.
- Scenario A: Given the Client already mentioned their appointment, when notes are requested, then the Oracle confirms those details first, and the Client can confirm or correct them.
- Scenario B: Given no appointment was mentioned, when notes are requested, then the Oracle asks whether one is booked, and the Client can fill in the card, answer Not yet, or skip.
- Editing: Given notes exist, when the Client changes the specialty, then the questions, tests and referral advice are updated. Changing the name or date updates the header and reminders.
- Template: Given notes are created, when they’re shown, then they follow the template sections in order, with the header and disclaimer.
- First name only: Given notes are created, when the header is shown, then it uses the first name only.
- Lab values: Given the Client typed lab values, when the notes are created, then the values are listed as reported, with no interpretation.
- Tests: Given tests are listed, when the notes are shown, then they’re written as the Client’s request, never as orders.
- Genesis Gold note: Given the Client is an adult taking or starting Genesis Gold, when the notes are created, then the Genesis Gold note is included. It’s never included for teens or children.
- Disclosure box: Given the notes mention Genesis products/affiliate links, when they’re shown, then one disclosure box, with the ownership sentence, appears at the end.
- No diagnosis: Given any notes, when they’re shown, then they never diagnose, prescribe, or describe the Oracle as a clinician (California AB 489).
- Family member: Given the notes are for a family member, when they’re shown, then the family member is the patient, and the Client is shown as medical advocate.
- Teens: Given the notes are for a teen, when they’re created, then they’re education only, with no products, and only the teen (own account) or the advocate (managed by a parent) can see them.
- Saved: Given the notes are created, when they’re shown, then they’re saved to My Visit Notes for that conversation.
- Reminders: Given an appointment date is known, when the notes are saved, then a reminder and a follow-up are scheduled. Without a date, the 7-day booking follow-up is scheduled.
Alternate Scenario:
- Mentioned details are wrong
  - The Client corrects them on the appointment card before the notes are created.
- Appointment changes
  - The Client edits the details, and the notes and reminders update.
- Unclear “Other” specialty
  - The Oracle asks what kind of provider it is.
- Not booked yet, or skipped
  - The notes are created, and the Client can add the details later.
- Appointment date in the past
  - The Oracle tells them the date has passed.
  - It offers Choose a new date, or Log this visit (see story 5.2).
- Provider unlikely to address part of the concern
  - The notes suggest a referral.
- Not enough information yet
  - The Oracle asks a few more questions first.
- Emergency active in the conversation
  - Notes are created only after the Client confirms they’re safe (see story 3.2).
- Notes can’t be created
  - The Client can try again.
Non-functional Requirements:
- Notes should be generated, or updated after an edit, within 10 seconds.
- The specialty list is configurable, so options can change without an app release.
- Notes use provider-facing clinical language, written from the Client’s point of view (“I am bringing this…”).
- Notes content comes only from the conversation, the health profile and Deborah’s approved content.
- Notes are encrypted, stored in the HIPAA-compliant cloud (Azure), and never shared with analytics tools, ad pixels or Shopify.
- A teen’s notes in their own account can never be seen from the parent’s account.
Validation Rules/Errors:
- Specialty not selected: “Please choose what kind of provider you’re seeing, so I can tailor the notes.”
- “Other” left empty: “Please tell me what kind of provider this is.”
- Unclear “Other” specialty: “Just to check, what kind of provider is [text]? For example, a GP, a specialist or a naturopath.”
- Appointment date in the past: “That date has already passed. Would you like to choose a new date, or log this visit?”
- Confirming a mentioned appointment: “You mentioned you’re seeing your [specialty] on [date]. Shall I prepare the notes for that visit?”
- Not yet booked: “From what you’ve shared, a [specialty] would be a good place to start. I’ve put together notes you can take with you when you book.”
- Notes ready: “Your notes for [Provider name] are ready. Take them with you to your appointment.” / “Your notes are ready. Take them with you when you see your provider.”
- Notes updated after an edit: “I’ve updated your notes for your [specialty] appointment.”
- Notes couldn’t be created: “I couldn’t create your notes just now. Please try again.”
### 3.5 View, Edit & Download Provider-Ready Notes
### Requirement Statement:
As a Client, I want to view my provider-ready notes, update the appointment details and download, print or copy them, so that I can take accurate notes to my appointment in whichever way suits me.
### Specifications:
Story Details:
- Where the Notes Can Be Opened
  - The Client can open provider-ready notes:
    - from the notes card in the conversation, right after they’re created (see story 3.4)
    - from My Visit Notes, where every set of notes is listed under its conversation (see story 5.1)
  - Notes always open for the active profile. A family member’s notes are only shown when that family member’s profile is active.
- Notes Screen
  - The notes screen shall include:
    - Top bar:
      - a Back button
      - the notes title, for example “Notes for my Cardiology appointment”
      - the date the notes were created
    - Appointment details at the top: specialty, provider name and appointment date (the last two only if known), with an Edit appointment button
    - Notes content, in the template order:
      - header (first name, date of birth, specialty, provider name, appointment date)
      - what this is
      - chief complaint
      - clinical context
      - labs I am requesting
      - questions for my provider
      - current medications and supplements
      - red flags screened by the Oracle
      - the Oracle’s recommendation
      - disclosure box (only if Genesis products/affiliate links are mentioned)
      - Disclaimer: “This document was prepared by Your Oracle, an AI health education tool developed by Genesis Health Products Inc. It is not a diagnosis, a prescription, or a substitute for professional medical care”
    - Actions at the bottom:
      - Download PDF
      - Print
      - Copy text
      - Back to conversation, which opens the conversation the notes came from
- What Can Be Edited
  - Appointment details only: specialty, provider name and appointment date can be edited at any time (see story 3.4).
    - The notes content is read-only. If the Client wants something changed or added, they go back to the conversation and tell the Oracle. For example: “Can you add a question about my iron levels?”
    - When the Oracle updates the notes from the conversation, the notes screen shows the latest version.
  - Download, Print and Copy
    - Download PDF:
      - creates a PDF of the notes, laid out for Letter and A4 paper
      - named with the first name, specialty and date, for example “Notes_Sarah_Cardiology_12-Nov-2026.pdf”
      - saved to the device’s downloads (Web), or offered through the share sheet (Mobile)
    - Print: opens the device’s print dialog, with the same layout as the PDF.
    - Copy text: copies the full notes as plain text, for pasting into an email or a provider’s patient portal. The Client sees a confirmation.
    - Every PDF, printout and copied text includes the disclaimer, and the disclosure box when Genesis products/affiliate links are mentioned
  - Subscribed and Free Trial Clients
    - Subscribed Client: can view, edit appointment details, download, print and copy.
    - Free trial Client:
      - can view the notes and edit the appointment details in the app
      - download, print and copy are locked, with an upgrade prompt (see story 9.1)
  - Family Members and Teens
    - Family member: the first name and date of birth are the family member’s, and the notes show they were prepared by the Client as medical advocate. The PDF file name uses the family member’s first name.
    - Teen with their own account:
      - can view, download, print and copy their own notes, because their access comes through the parent’s Family plan
      - the parent can’t see the teen’s notes
    - Teen managed by a parent: the parent sees the notes, as the teen’s advocate.
Acceptance Criteria:
- Opening notes: Given notes exist, when the Client opens them from the conversation or from My Visit Notes, then they open for the active profile only.
- Notes screen: Given the notes screen is open, when it loads, then it shows the appointment details with Edit appointment, the full notes in template order, and the Download PDF, Print, Copy text and Back to conversation actions.
- Editing: Given the Client edits the notes, when they make changes, then only the specialty, provider name and appointment date can be changed. The content is read-only.
- Latest version: Given the Oracle updates the notes from the conversation, when the Client opens them, then the latest version is shown.
- Download: Given a subscribed Client taps Download PDF, when the PDF is created, then it uses the first name, specialty and date in the file name, and is laid out for Letter and A4.
- Print: Given the Client taps Print, when the dialog opens, then it uses the same layout as the PDF.
- Copy: Given the Client taps Copy text, when the notes are copied, then the full notes are copied as plain text, and a confirmation is shown.
- Disclaimer and disclosure: Given notes are downloaded, printed or copied, when the output is created, then it includes the disclaimer, and the disclosure box when Genesis products/affiliate links are mentioned.
- Free trial: Given a free trial Client taps Download PDF, Print or Copy text, when the action is triggered, then an upgrade prompt is shown.
- Family member: Given the notes are for a family member, when they’re shown or downloaded, then the family member is the patient, and the Client is shown as medical advocate.
- Teen privacy: Given a teen with their own account has notes, when the parent is signed in, then the parent can’t see them.
Alternate Scenario:
- Client wants to change the content
  - They’re sent back to the conversation to ask the Oracle.
- Appointment rebooked
  - The Client edits the details from the notes screen.
- Client switches profile while notes are open
  - They’re taken to that profile’s My Visit Notes.
- Free trial Client taps Download PDF, Print or Copy text
  - The upgrade prompt is shown.
- No printer set up
  - The device’s own message is shown.
- PDF download fails
  - The Client can try again.
- Client is offline
  - Notes already opened can still be viewed.
  - Download and edits wait until they’re back online.
Non-functional Requirements:
- The notes screen should load within 2 seconds.
- The PDF should be ready within 5 seconds, and print cleanly on Letter and A4 paper.
- Downloaded PDFs are generated on request, and not stored on shared servers beyond what’s needed to deliver them.
- Notes are encrypted, stored in the HIPAA-compliant cloud (Azure), and never shared with analytics tools, ad pixels or Shopify.
- A teen’s notes in their own account can never be seen from the parent’s account.
- Notes screens and PDFs meet accessibility basics: readable font sizes, sufficient contrast, and screen-reader labels on actions.
Validation Rules/Errors:
- Copied: “Your notes have been copied.”
- Download complete: “Your notes have been downloaded.”
- Notes updated: “I’ve updated your notes for your [specialty] appointment.”
- Free trial lock: “Subscribe to download, print and copy your provider notes.”
- Download failed: “We couldn’t download your notes. Please try again.”
- Copy failed: “We couldn’t copy your notes. Please try again.”
- Offline: “You’re offline. You can read your notes, but downloading and editing will be available when you’re back online.”
## 4. Epic: Home Dashboard
### 4.1 - View Home Dashboard
### Requirement Statement:
As a Client, I want a home dashboard that shows where I left off and what to do next, so that I can quickly continue my health journey, or my family member’s.
### Specifications:
Story Details:
- 1. When the Dashboard Appears
  - the Home Dashboard opens after sign-in, once any updated policies are accepted and onboarding is complete (see story 1.2).
  - It always shows the active profile’s information. The active profile is shown in the profile icon at the top right (see story 4.2).
  - Top Bar
    - The top bar shall include:
      - Greeting in the Oracle’s voice, for example “Good morning, Sarah”, or “Here’s Azka’s space” for a family member
      - Notifications bell, with a count of unread notifications (see story 12.1)
      - Profile icon, showing the active profile’s initial, which opens the profile toggle (see story 4.2)
  - Dashboard Widgets (in this order, shown only when relevant)
    - Continue your conversation (primary, at the top):
      - shows the last conversation’s topic and date, with a Continue button
      - if there’s no conversation yet, it shows Ask the Oracle instead, with the placeholder “Ask me anything”
    - Wellness Plan:
      - shown once the profile has a Wellness Plan
      - shows the current focus item and progress dots (like a pill organiser, Session 7), with a View plan button (see story 7.1)
    - Complete your health profile:
      - shows the profile completion percentage, with a Complete now button that opens the health profile form (see story 6.1)
      - hidden once the profile is complete
    - Update your health profile:
      - shown at 3, 6 and 12 months after the last update, and after a logged provider visit (Session 7)
      - for example: “It’s been 6 months. Has anything changed? Let’s make sure I have the latest.”
    - What’s next: one or two suggested next steps, for example:
      - “Your Cardiology appointment is on 14 Nov. Your notes are ready.”
      - “How did your visit go? Log it here.” (see story 5.2)
      - “You were going to try the sleep protocol. How is it going?”
    - My Visit Notes: quick access to visit notes and saved summaries (see story 5.1).
    - My Health: quick access to the health profile (see story 7.1).
    - My Family:
      - shows the family profiles, with Add family member (see story 8.1)
      - invited teens show their status: Invite sent, Joined or Access paused (see story 1.5)
      - Family plan only. On the free trial or the Individual plan, it shows the upgrade prompt instead.
    - Consult with support team: a card to ask the support team about a consultation (see story 10.1).
  - Free Trial
    - A banner shows how many days are left in the 14-day trial, with a Choose a plan button (see story 9.1).
    - During the trial:
      - Continue your conversation and Ask the Oracle work as normal
      - the other widgets are shown greyed out, and tapping them shows the upgrade prompt (Session 9)
      - My Family isn’t available
    - When the trial ends without a subscription, the dashboard shows the upgrade prompt.
  - Family Member Profile Active
    - Every widget shows the family member’s information: their conversations, Wellness Plan, notes and health profile.
    - Wording uses their name and pronouns, for example “Continue Azka’s conversation”.
    - The My Family widget is hidden while a family member’s profile is active.
  - Teens
    - Teens with their own account use the same dashboard as an independent Client:
      - Continue your conversation, or Ask the Oracle
      - Wellness Plan
      - Complete your health profile, and Update your health profile
      - What’s next
      - My Visit Notes
      - My Health
    - They don’t see:
      - My Family
      - plans, billing or the free trial banner (their access comes through the parent’s Family plan)
      - any product promotion
    - Everything they see is education only.
    - Teens managed by a parent: shown in the parent’s dashboard when their profile is active, with no product promotion.
Acceptance Criteria:
- Dashboard: Given the Client has signed in and finished onboarding, when the dashboard opens, then it shows the active profile’s information.
- Greeting: Given the dashboard opens, when the greeting is shown, then it uses the active profile’s name and the time of day.
- Widget order: Given the dashboard opens, when widgets are shown, then they appear in the agreed order, and only when relevant.
- Conversation: Given there’s a previous conversation, when the dashboard opens, then Continue your conversation shows it. Otherwise, Ask the Oracle is shown.
- Wellness Plan: Given a Wellness Plan exists, when the dashboard opens, then the Wellness Plan card shows the current focus and progress dots.
- Health profile: Given the profile isn’t complete, when the dashboard opens, then Complete your health profile shows the percentage. It’s hidden once complete.
- Update reminder: Given 3, 6 or 12 months have passed since the last update, or a visit was logged, when the dashboard opens, then Update your health profile is shown.
- What’s next: Given there are upcoming appointments or visits to log, when the dashboard opens, then What’s next shows them.
- My Family: Given the Client is on the Family plan, when they open My Family, then they see their family profiles and invited teens’ status. On the free trial or the Individual plan, the upgrade prompt is shown.
- Consult: Given the Client taps Consult with support team, when it opens, then the request flow in story 10.1 starts.
- Free trial: Given the Client is on the free trial, when the dashboard opens, then the days left are shown, only the conversation works, and other widgets are greyed out.
- Family member: Given a family member’s profile is active, when the dashboard opens, then every widget shows that person’s information and uses their name.
- Teens: Given a teen with their own account signs in, when the dashboard opens, then they see the same widgets as an independent Client, without My Family, plans, billing or products.
Alternate Scenario:
- New Client with no conversations
  - They see Ask the Oracle instead of Continue your conversation.
- Profile complete
  - Complete your health profile isn’t shown.
- No Wellness Plan yet
  - The Wellness Plan card isn’t shown.
- Free trial Client taps a greyed-out widget
  - The upgrade prompt is shown.
- Individual plan Client taps My Family
  - The upgrade prompt for the Family plan is shown.
- Teen with their own account signs in
  - They see the independent Client dashboard, without My Family, plans, billing or products.
- Client switches to a family member
  - The dashboard reloads for that profile.
- Free trial ends
  - The dashboard shows the upgrade prompt.
- Dashboard can’t load
  - The Client can try again.
Non-functional Requirements:
- The dashboard should load within 2 seconds.
- Widgets update automatically when something changes, for example a new conversation or a logged visit.
- Only the active profile’s information is ever shown.
- A teen’s dashboard in their own account can never be seen from the parent’s account.
- The layout works on Mobile and Web, in portrait and landscape.
Validation Rules/Errors:
- Greeting: “Good morning, [First Name]” / “Good afternoon, [First Name]” / “Good evening, [First Name]”
- Family member greeting: “Here’s [Name]’s space”
- Update reminder: “It’s been [time] since we last updated your profile. Has anything changed?”
- Free trial: “[X] days left in your free trial.”
- Greyed-out widget tapped: “This is part of your plan. Choose a plan to unlock it.”
- My Family on the wrong plan: “Adding family members is part of the Family plan. Upgrade to add someone.”
- Dashboard couldn’t load: “We couldn’t load your dashboard. Please try again.”
### 4.2 - Switch Profiles - Global Profile Toggle
### Requirement Statement:
As a Client, I want to tap my profile icon and see my own profile and my family members’ profiles, so that I can switch between them from anywhere in the app.
### Specifications:
Story Details:
- Profile Icon
  - The profile icon appears at the top right of every main screen: Home Dashboard, Ask the Oracle, My Visit Notes, My Health and Wellness Plan.
  - It shows the active profile’s initial, so the Client always knows whose information they’re looking at.
- Profile Panel
  - Tapping the profile icon opens a profile panel, like an account switcher. The panel shall include:
    - Active profile at the top:
      - for the Client’s own profile: initial, first name and email address
      - for a family member: first name and relationship, for example “Azka · Daughter”
      - a Manage profile button, which opens Profile & Account (see story 11.1)
    - Other profiles listed below:
      - the Client’s own profile, marked “You”, if a family member is active
      - each family member, with their initial, first name, relationship and age, for example “Rose · Mother · 78”
    - Add family member: opens the family member intake (see story 2.2)
    - Sign out (see story 1.4)
    - a Close (X) button
- Who Appears in the Panel
  - Family members managed by the Client, including teens managed by a parent: listed, and can be switched to.
  - Invited teens with their own account: not listed, because the parent can’t see their information. They only appear in My Family, with their status (see stories 4.1 and 8.2).
- Adding a Family Member
  - Add family member is only available on the Family plan.
  - On the free trial or the Individual plan: the upgrade prompt is shown instead.
  - When all 3 family places are used: the Client is asked to add another member as a paid add-on.
- Switching Profile
  - Tapping another profile makes it the active profile, and the panel closes.
  - The whole app switches to that profile: dashboard, conversations, My Visit Notes, health profile and Wellness Plan.
  - The Client stays on the same type of screen. For example, switching while on My Visit Notes shows the new profile’s My Visit Notes.
  - A short confirmation is shown: “You’re now viewing Azka’s profile.”
  - If the Client switches while a conversation is open, the current conversation is saved, and the new profile’s conversation list opens.
- Teens With Their Own Account
  - Their panel shows only their own profile, with Manage profile and Sign out.
  - There’s no Add family member, and no other profiles.
- Advocate-Only Clients
  - A Client in advocate-only mode has no profile of their own (see story 11.4).
  - The panel shows only their family members, and the first family member is active after sign-in.
- Default Profile After Sign-In
  - The Client’s own profile is active, or the first family member’s for advocate-only Clients.
Acceptance Criteria:
- Profile icon: Given the Client is on any main screen, when it loads, then the profile icon is shown with the active profile’s initial.
- Profile panel: Given the Client taps the profile icon, when the panel opens, then it shows the active profile at the top with Manage profile, the other profiles below, Add family member, Sign out and Close.
- Profile details: Given profiles are listed, when the panel is shown, then the Client’s own profile shows their first name and email, and family members show their first name, relationship and age. The Client’s own profile is marked “You” when a family member is active.
- Invited teens: Given the Client has invited a teen with their own account, when the panel opens, then that teen isn’t listed.
- Managed teens: Given the Client manages a teen’s profile, when the panel opens, then that teen is listed and can be switched to.
- Switching: Given the Client taps another profile, when it’s selected, then it becomes active, the panel closes, and a confirmation is shown.
- Same screen: Given the Client switches profile, when the switch completes, then every module shows only the new profile’s information, and the Client stays on the same type of screen.
- Open conversation: Given a conversation is open, when the Client switches profile, then the conversation is saved first.
- Add family member: Given the Client taps Add family member, when they’re on the Family plan, then the family intake opens. On the free trial or Individual plan, the upgrade prompt is shown. When all places are used, the add-on is offered.
- Teen with own account: Given a teen with their own account opens the panel, when it’s shown, then only their own profile, Manage profile and Sign out are available.
- Advocate-only: Given the Client is in advocate-only mode, when the panel opens, then only their family members are shown.
- Default profile: Given the Client signs in, when the app opens, then their own profile is active, or the first family member’s for advocate-only Clients.
Alternate Scenario:
- No family members
  - The panel shows only the Client’s own profile and Add family member.
- Family member limit reached
  - The Client is asked to add another member as an add-on.
- Not on the Family plan
  - Add family member shows the upgrade prompt.
- Switching mid-conversation
  - The conversation is saved, and the new profile’s conversation list opens.
- Active family member removed
  - The app switches back to the Client’s own profile.
- Teen with their own account
  - The panel shows only their own profile.
- Advocate-only mode
  - Only family members are shown.
Non-functional Requirements:
- The panel should open within 1 second, and switching profile should complete within 2 seconds.
- Switching profile must fully clear the previous profile’s information from the screen, so no information is mixed between profiles.
- An invited teen’s information can never be shown in the parent’s panel.
- The panel is accessible: each profile has a screen-reader label with the first name and relationship.
Validation Rules/Errors:
- Switched profile: “You’re now viewing [Name]’s profile.”
- Not on the Family plan: “Adding family members is part of the Family plan. Upgrade to add someone.”
- Family member limit reached: “You’ve added all the family members included in your plan. Add another member to continue.”
- Switch failed: “We couldn’t switch profiles. Please try again.”
## 5. Epic: My Visit Notes
### 5.1 - View, Download & Manage Visit Notes
### Requirement Statement:
As a Client, I want to see all my visit notes in one place, download them and keep my appointment details up to date, so that I’m prepared for each provider visit.
### Specifications:
Story Details:
- Opening My Visit Notes
  - The Client can open My Visit Notes, on the Mobile App or Web App, from:
    - the My Visit Notes card on the Home Dashboard (see story 4.1)
    - the main navigation
    - an appointment notification (see story 12.1)
  - The Client sees only the active profile’s notes, and can switch profiles using the profile icon (see story 4.2).
  - There are no Labs or Attachments tabs (Session 9).
- Notes List
  - Each note appears as a card, showing the date it was created, its title and a one-line preview.
  - The list includes:
    - guidance summaries saved from conversations
    - provider-ready notes created from conversations
    - logged visits
  - Order:
    - notes with an upcoming appointment come first, soonest first, with an Upcoming label (for example, “Upcoming · Cardiology · 14 Nov”)
    - all other notes follow, newest first
  - Card actions:
    - Not logged yet: notes whose visit hasn’t been logged show a Log visit button (see story 5.2).
    - Logged visits: show Ask the Oracle, to talk the visit through, and an Edit icon.
  - Search: by title, topic, specialty or provider name.
- Opening a Note
  - The Client taps a card to open it:
    - Guidance summary: opens the summary (see story 3.3).
    - Provider-ready notes: opens the notes, with the appointment details at the top and an Edit appointment button (see story 3.5).
    - Logged visit: opens the visit log (see story 5.2).
- Editing Appointment Details
  - The Client taps Edit appointment, and can change the specialty, provider name and appointment date (see story 3.4).
  - If the specialty changes: the Oracle updates the questions, tests and referral advice.
  - If the date changes: reminders are rescheduled, and the note moves to the right place in the list.
- Downloading
  - The Client can download a guidance summary or provider-ready notes as a PDF.
  - Each PDF:
    - includes the disclaimer, and the disclosure box when Genesis products or affiliate links are mentioned
    - prints cleanly on Letter and A4 paper
    - is named with the first name, note type and date, for example “Provider-Notes_Sarah_Cardiology_14-Nov-2026.pdf”
  - Provider-ready notes can also be printed, or copied as text.
  - Logged visits stay in the app, and can’t be downloaded.
- Family Members and Teens
  - Family member: only that family member’s notes are shown, and PDFs use their first name and show the Client as medical advocate.
  - Teen with their own account: sees their own notes. The parent can’t see them.
  - Teen managed by a parent: the parent sees the teen’s notes, as advocate.
- Free Trial
  - My Visit Notes is greyed out, with an upgrade prompt (Session 9).
  - Notes can still be viewed inside the conversation they came from (see story 3.5).
Acceptance Criteria:
- Opening: Given the Client is subscribed, when they open My Visit Notes from the dashboard, the main navigation or a notification, then it opens with the active profile’s notes.
- No tabs: Given My Visit Notes is open, when it loads, then there are no Labs or Attachments tabs.
- Cards: Given notes exist, when the list loads, then each card shows the date created, title and preview.
- Order: Given there are notes with upcoming appointments, when the list loads, then they’re listed first, soonest first, followed by all other notes, newest first.
- Card actions: Given a note’s visit hasn’t been logged, when it’s shown, then it has a Log visit button. Logged visits show Ask the Oracle and Edit.
- Search: Given the Client searches, when they type, then notes are found by title, topic, specialty or provider name.
- Opening a note: Given the Client taps a card, when it opens, then the right screen for that type of note is shown.
- Editing: Given the Client edits appointment details, when they save, then the notes, reminders and list order update to match.
- Download: Given the Client downloads a guidance summary or provider-ready notes, when the PDF is created, then it uses the first name, note type and date in the file name, and includes the disclaimer and, when relevant, the disclosure box.
- Logged visits: Given a logged visit, when the Client looks for a download option, then none is offered.
- Teen privacy: Given a teen with their own account has notes, when the parent is signed in, then the parent can’t see them.
- Free trial: Given a free trial Client taps My Visit Notes, when it’s opened, then the upgrade prompt is shown.
Alternate Scenario:
- No notes yet
  - The empty message is shown, with a prompt to start a conversation.
- Appointment date passes
  - The note loses its Upcoming label, and moves down the list.
- Appointment rebooked
  - The Client edits the date, and the note moves to the right place.
- Referred to a different provider
  - The Client edits the specialty, and the notes update.
- Free trial Client opens My Visit Notes
  - The upgrade prompt is shown.
- Download fails
  - The Client can try again.
- Client is offline
  - Notes already opened can still be viewed, and downloads wait until they’re back online.
Non-functional Requirements:
- The screen should load within 2 seconds, and search results should appear within 1 second.
- A PDF should be ready within 5 seconds.
- The list re-sorts automatically when an appointment date passes or is edited.
- Notes and PDFs are encrypted, stored in the HIPAA-compliant cloud (Azure), and never shared with analytics tools, ad pixels or Shopify.
- A teen’s notes in their own account can never be seen from the parent’s account.
Validation Rules/Errors:
- No notes yet: “You don’t have any visit notes yet. Start a conversation and I’ll help you get ready for your next appointment.”
- No search results: “No notes match your search.”
- Specialty not selected when editing: “Please choose what kind of provider you’re seeing, so I can tailor the notes.”
- “Other” specialty left empty: “Please tell me what kind of provider this is.”
- Appointment date in the past: “That date has already passed. Would you like to choose a new date, or log this visit?”
- Free trial: “My Visit Notes is part of your plan. Choose a plan to unlock it.”
- Download failed: “We couldn’t download your notes. Please try again.”
- List couldn’t load: “We couldn’t load your notes. Please try again.”
- Offline: “You’re offline. You can see notes you’ve already opened, and downloads will be available when you’re back online.”
### 5.2 - Log Provider Visit Outcome
### Requirement Statement:
As a Client, I want to record what happened at my provider visit, so that the Oracle can update my guidance, Wellness Plan and health profile based on what my provider said and did.
### Specifications:
Story Details:
- Starting a Log
  - The Client can log a visit:
    - by tapping Log visit on a note card (see story 5.1)
    - from the post-visit notification: “Your [specialty] appointment was on [date]. How did it go?” (see story 12.1)
    - from What’s next on the Home Dashboard (see story 4.1)
  - The Client can also log any visit on its own, for example an unplanned urgent care visit, by tapping + Log a visit on My Visit Notes.
- Pre-filled Details
  - The Log your visit screen opens with what’s already known filled in:
    - visit linked to provider-ready notes: the specialty, provider name, visit date, the reason for the visit and the requested labs
    - standalone visit: only the first name and date of birth
- Log Your Visit Form
  - The form follows the Provider Visit Summary template, and shall include:
    - Visit date (Mandatory)
    - Why you went: what they wanted help with (Mandatory), and how long it’s been going on
    - Provider seen:
      - specialty (Mandatory, dropdown with “Other”)
      - provider name (Optional)
      - practice or clinic
      - follow-up appointment
    - What I took away: the diagnosis or impression given, their own understanding, and any concerns that weren’t addressed
    - Labs ordered:
      - each lab, with who ordered it and its status (Pending, Drawn or Resulted)
      - labs requested in the notes are already listed, so the Client can mark which were ordered
    - Changes in prescriptions or supplements:
      - each medicine, with its change (New, Dose increased, Dose decreased, Discontinued, Continued or Added) and new dose
      - adults only: their Genesis Gold® or Sacred Seven® status
    - Next steps: each with a priority (Routine, Schedule or Urgent)
    - Your own notes: anything else they want to remember
  - There’s no upload option.
  - For a linked visit, the Oracle’s notes for this visit are shown, read-only, as a reminder of what the Client planned to raise.
- Saving
  - The Client taps Save.
  - A linked note’s card changes from “Not logged yet” to show Ask the Oracle and Edit.
  - A standalone visit appears as a new card.
- What the Oracle Does With the Visit
  - It compares the visit with the provider-ready notes: which questions were answered, which labs were ordered, and what was missed.
  - Medicines:
    - it asks before adding medicine changes to the health profile
    - it links to Drugs.com for new medicines, and advises checking with a pharmacist or provider if there may be an interaction
  - Wellness Plan: it adds new next steps and labs, and marks items the provider has addressed (see story 7.1).
  - Lab results: it schedules a reminder for when results are expected. When they come in, the Client can type the values into a conversation. The Oracle explains them, but never interprets them (see story 3.1).
  - It asks: “Would you like to talk about what your provider said?” If the Client says yes, a conversation about the visit opens.
- Editing
  - The Client taps Edit on a logged visit to update it.
  - Changes go through the same steps as saving.
- Deleting
  - The Client taps Delete visit log on the edit screen, and confirms.
  - If the visit added items to the Wellness Plan, the Client chooses whether to keep or remove them.
  - What happens when a visit log is deleted:
    - a linked note goes back to “Not logged yet”; a standalone visit’s card is removed
    - the Oracle no longer uses the visit in future guidance, and past conversations stay as they are
    - medicine changes already saved to the health profile stay there
    - reminders from the visit are cancelled
    - the deletion is recorded in the backend logs for six years (BAA Section 13)
- Family Members and Teens
  - Family member: the Client logs, edits or deletes the visit as their advocate, using the family member’s details.
  - Teen with their own account: logs their own visits. The parent can’t see them.
  - Teen managed by a parent: the parent logs them, as an advocate.
  - Teens and children: the Genesis Gold® and Sacred Seven® field isn’t shown.
- Free Trial
  - Logging a visit isn’t available during the free trial, because My Visit Notes is greyed out (see story 5.1).
Acceptance Criteria:
- Starting a log: Given a subscribed Client, when they tap Log visit on a note card, the post-visit notification, What’s next, or + Log a visit, then the Log your visit form opens.
- Pre-filled details: Given a linked visit, when the form opens, then the known details are filled in. For a standalone visit, only the first name and date of birth are.
- Template: Given the form is open, when it loads, then it follows the Provider Visit Summary template, with no upload option.
- Mandatory fields: Given the Client taps Save, when visit date, why you went or specialty is empty, then they can’t save. Everything else is optional.
- Rows: Given the Labs, Medicines or Next steps sections, when the Client adds items, then they can add more than one row.
- Saving: Given the Client saves, when the visit is linked, then the note’s card updates. A standalone visit is added as a new card.
- Oracle’s actions: Given a visit is saved, when the Oracle processes it, then it compares it with the notes, asks before updating the health profile, links new medicines to Drugs.com, updates the Wellness Plan, and schedules a lab results reminder.
- Talk it through: Given a visit is saved, when the Oracle replies, then it offers to talk the visit through.
- Lab results: Given the Client types lab results into a conversation, when the Oracle replies, then it explains them without interpreting them.
- Edit and delete: Given a logged visit, when the Client edits or deletes it, then the changes or deletion effects apply as described.
- Teens: Given a teen profile, when the form opens, then the Genesis Gold® and Sacred Seven® field isn’t shown. A teen’s own logs can’t be seen by the parent.
- Free trial: Given a free trial Client, when they try to log a visit, then the upgrade prompt is shown.
Alternate Scenario:
- Standalone visit
  - The Client logs it with nothing pre-filled except their first name and date of birth.
- Provider didn’t order the requested labs
  - The Client leaves them unmarked, and the Oracle notes what was missed.
- Client doesn’t add a medicine change to their profile
  - The visit is saved, and the health profile stays as it is.
- New medicine may interact
  - The Oracle links to Drugs.com, and advises checking with a pharmacist or provider.
- Next step marked Urgent
  - The Oracle reminds them to follow it up.
- Client closes the form without saving
  - They’re asked to confirm before leaving.
- Client declines to talk it through
  - The visit is saved, and they can talk it through later.
- Client deletes a visit and keeps its Wellness Plan items
  - The items stay in the Wellness Plan.
- Free trial Client tries to log a visit
  - The upgrade prompt is shown.
- Saving or deleting fails
  - The Client can try again.
Non-functional Requirements:
- The form should open, pre-filled, within 2 seconds, and save or delete within 3 seconds.
- Entered information is saved as a draft while the Client fills in the form, so nothing is lost if the app closes.
- The Oracle only updates the health profile after the Client confirms.
- Visit logs are encrypted, stored in the HIPAA-compliant cloud (Azure), and never shared with analytics tools, ad pixels or Shopify.
- A teen’s own visit logs can never be seen from the parent’s account.
- Deletion events are recorded in the backend logs, and retained for six years
Validation Rules/Errors:
- Visit date missing: “Please add the date of your visit.”
- Visit date in the future: “That date hasn’t happened yet. Please choose the date of your visit.”
- “Why you went” left empty: “Please tell me what you went in for.”
- Specialty not selected: “Please choose what kind of provider you saw.”
- “Other” specialty left empty: “Please tell me what kind of provider this was.”
- Next step marked Urgent: “You marked this as urgent. Please make sure you follow up with your provider.”
- Possible medicine interaction: “[Medicine] can interact with [existing medicine], so please check with your pharmacist or provider.”
- Closing without saving: “You have unsaved changes. Leave without saving?”
- Deleting a visit log: “Delete this visit log? This can’t be undone.”
- Deleted visit added Wellness Plan items: “This visit added [X] items to your Wellness Plan. Keep them, or remove them too?”
- Free trial: “Logging visits is part of your plan. Choose a plan to unlock it.”
- Save failed: “We couldn’t save your visit just now. Please try again.”
- Delete failed: “We couldn’t delete your visit log just now. Please try again.”
## 6. Epic: My Health
### 6.1 - View, Edit & Complete Health Profile
### Requirement Statement:
As a Client, I want to view, update and complete my health profile, so that the Oracle always has an accurate picture of my health, or my family member’s, without asking the same questions again.
### Specifications:
Story Details:
1.  Opening My Health
1.  The Client can open My Health, on the Mobile App or Web App, from:
1.  the My Health card on the Home Dashboard
2.  the main navigation
3.  the Complete your health profile and Update your health profile widgets (see story 4.1)
2.  The Client sees only the active profile’s health information, and can switch profiles using the profile icon (see story 4.2).
2.  Top of My Health
1.  Wellness Plan card:
1.  the current focus, for example “Immediate dietary action”
2.  progress, for example “0/8”, with progress dots
3.  an arrow to open the full Wellness Plan (see story 7.1)
4.  It isn’t counted in profile completion, because it’s ongoing.
2.  Check-in card: when a check-in is due, for example “Check in with the Oracle · Due today · about 2 minutes”, with a Check in now button. It opens a short conversation to follow up on Wellness Plan items, or review the profile (see story 12.1).
3.  Health profile heading: shows the completion status, for example “Complete” or “60% complete”, with a Complete my profile button while it isn’t complete.
1.  The percentage counts only the questions that apply to the profile, as set out in the routing document.
2.  Optional and sensitive questions, and the main wellness goal, aren’t counted.
4.  Hypothalamus Circle Map
1.  Deborah’s predefined map, with the Client’s symptoms highlighted the highlighting comes from their health profile and their conversations, and updates as they share more
2.  shown with the line “This map shows how symptoms can connect to the hypothalamus. It isn’t a diagnosis.”
3.  Deborah’s map, shown as a static graphic, which the Client can view, download and print.
3.  Health Profile Sections

Link: [Health Intake Routing](https://docs.google.com/document/d/1xqem26u29VbeD16zQ6rFeW-b0A52DCLQq7xh6rFbUK0/edit?usp=sharing)

1.  Each section shows its answers, and an Edit icon where editing is allowed.
2.  About you:
1.  Date of birth and sex assigned at birth (Male, Female, Intersex or Prefer not to say): read-only, because they decide which questions apply.
2.  Gender identity (Woman, Man, Non-binary, Agender, Not listed (write in) or Prefer not to say; Girl or Boy for under-13s) and pronouns: can be edited at any time. If pronouns weren’t set, the field shows Add.
3.  My main wellness goal: what the Client most wants to work on. It can be updated at any time, but isn’t required to complete the profile.
4.  Follow-up body questions: shown only for the groups below, with a privacy notice first. All optional, and they can be edited or deleted at any time.
1.  Privacy notice: answers are optional, used only to tailor education, never sold or shared with advertisers, encrypted, and editable or deletable anytime. Placeholder text until the attorney’s final wording is in.
2.  Path A, sex at birth is Intersex or Prefer not to say:
1.  Intersex variation (Yes / No / I don’t know / Prefer not to say, with the variation’s name if Yes)
2.  Your body
3.  Hormone history (pre-filled from the HRT answers)
4.  Surgery history
3.  Path B, gender differs from sex at birth:
1.  Your body
2.  Deborah’s gender-affirming questions: puberty, hormones, provider and context
3.  then the version for the body they were born with: hormone details, how long, surgeries, and periods if “Uterus” was ticked
4.  Teens in Path B: Your body, puberty, hormones and provider only.
4.  Gender “Prefer not to say” (sex at birth Male or Female): Your body only.
5.  Gender matches sex at birth: none of these sections are shown.
5.  Body and hormones: shown according to the age group and the “Your body” answers (or sex at birth):
1.  periods, menopause and HRT, for a uterus or ovaries
2.  puberty, growth and fertility, for testes or a prostate
3.  both, for intersex clients
6.  Medications, supplements and allergies: each with its name and reason, and whether the Client takes Genesis Gold® (adults only).
7.  Lifestyle: sleep, exercise, diet, work and stress, and support (adults).
8.  Symptoms: the hormonal checklists that match the body. The Client can mark items N/A.
9.  Health checks (adults): last physical, bloodwork, screenings and immunisations. Screenings follow the body, for example a Pap smear for a cervix, or prostate screening for a prostate.
10. Medical history: the Client’s own history and their family’s.
11. Teens and children: the teen or child questions, in place of the adult sections.
1.  Teen questions cover home, school, wellbeing and safety, sexual health (OK to ask, never to advise) and puberty blockers.
2.  Child questions cover birth, growth, milestones, school and safety.
4.  Viewing
1.  Answers saved from a conversation show where they came from, for example “Added from our conversation on 12 Oct”.
2.  Questions not yet answered show “Not answered yet” or Add.
5.  Editing
1.  The Client taps Edit on a section, changes any answer using the same type of input as onboarding (dropdowns, date pickers, Yes / No, and medicine fields with name and reason), and taps Save.
2.  In About you, only gender identity and pronouns can be changed. The Oracle uses the new wording straight away.
3.  If a change affects which questions apply (for example, a new reproductive status, or updated “Your body” answers), the new follow-up questions appear, and ones that no longer apply are hidden.
6.  Completing the Profile
1.  The Client taps Complete my profile, and the remaining questions open as a form, section by section (Session 10).
2.  The Oracle also asks these questions in conversation when they’re relevant (see story 3.1).
3.  The Client can stop at any time. Their answers are saved, and they can continue later.
4.  At 100%, the heading shows “Complete”, and the Client sees a short celebration: “That’s everything I need. Thank you for taking the time.” (Session 7)
7.  Keeping the Profile Up to Date
1.  The Client is reminded to review their profile at 3, 6 and 12 months after the last update, and after a logged provider visit (see stories 4.1 and 12.1).
2.  Health details the Oracle learns in conversation are saved automatically, and listed below the guidance summary (see story 3.3). The Client can change or remove any of them here.
3.  After a logged provider visit, the Oracle asks the Client before updating their health profile (see story 5.2).
4.  Saved changes are used in every future conversation, guidance summary, provider note and Wellness Plan update.
8.  Age Changes
1.  When a profile moves into a new age group (for example, a teen managed by a parent reaches the age of majority), the questions for the new age group become available, and the Client is invited to complete them.
2.  Teens with their own account move to their own adult account instead (see story 1.6).
9.  Family Members and Teens
1.  Family member: the Client views and edits the profile as their advocate. Questions use the family member’s name and pronouns, for example “Is [Name] taking any medications?”
2.  Teen with their own account: manages their own My Health. The parent can’t see it.
3.  Teen managed by a parent: the parent views and edits it, as advocate.
10. Free Trial
1.  My Health is greyed out during the free trial, with an upgrade prompt (see story 9.1).
Acceptance Criteria:
- Opening: Given a subscribed Client, when they open My Health from the dashboard, the main navigation or the profile widgets, then the active profile’s health information is shown.
- Wellness Plan card: Given a Wellness Plan exists, when My Health opens, then the card shows the current focus and progress, and opens the full plan.
- Check-in card: Given a check-in is due, when My Health opens, then the card is shown, and Check in now opens the check-in conversation.
- Completion: Given the profile isn’t complete, when My Health opens, then the percentage counts only the questions that apply, excluding optional and sensitive questions and the main wellness goal.
- About you: Given the About you section, when the Client edits it, then only gender identity and pronouns can change. Date of birth and sex at birth are read-only.
- Follow-up sections: Given a profile in Path A, Path B or gender “Prefer not to say”, when My Health opens, then only that group’s follow-up sections are shown, after the privacy notice. Profiles whose gender matches their sex at birth don’t see them.
- Hormone pre-fill: Given the Client answered the HRT questions, when hormone history opens, then it’s pre-filled.
- Teens: Given a teen profile, when My Health opens, then the teen sections are shown, including sexual health and puberty blocker questions.
- Viewing: Given answers came from a conversation, when they’re shown, then their source is shown. Unanswered questions show “Not answered yet” or Add.
- Follow-ups update: Given the Client changes an answer that drives follow-up questions, when they save, then the new follow-ups appear and old ones are hidden.
- Sensitive answers: Given an optional sensitive answer, when the Client edits or deletes it, then the change is saved.
- Complete my profile: Given the Client taps Complete my profile, when it opens, then the remaining questions open as a form, and progress is saved if they stop.
- Added from a conversation: Given the Oracle saved details from a conversation, when the Client opens My Health, then each one shows “Added from our conversation on [date]”, and can be changed or removed.
- 100%: Given all applicable questions are answered, when the last one is saved, then the heading shows “Complete”, with the celebration message.
- Reminders: Given 3, 6 or 12 months have passed, or a visit was logged, when the time comes, then a profile review reminder is sent.
- Age change: Given a managed profile reaches a new age group, when My Health opens, then the new questions are available.
- Family member: Given a family member’s profile, when the Client edits it, then questions use the family member’s name and pronouns.
- Teen privacy: Given a teen with their own account, when the parent is signed in, then the parent can’t see the teen’s My Health.
- Free trial: Given a free trial Client taps My Health, when it opens, then the upgrade prompt is shown.
- Circle Map: Given the Client opens My Health, when it loads, then the Hypothalamus Circle Map is shown, with their symptoms highlighted.
Alternate Scenario:
- Only onboarding done
  - Most sections show “Not answered yet”.
- No Wellness Plan yet
  - The Wellness Plan card isn’t shown.
- No check-in due
  - The check-in card isn’t shown.
- Client stops part-way through Complete my profile
  - Their answers are saved, and they continue later.
- Reproductive status changes
  - New follow-up questions appear.
- “Your body” skipped
  - Body questions follow sex at birth.
- Client deletes an optional sensitive answer
  - It’s removed, and the Oracle stops using it.
- Client tries to change date of birth or sex at birth
  - They’re told these can’t be changed.
- Client changes gender identity or pronouns
  - The Oracle uses the new wording straight away.
- Managed teen reaches the age of majority
  - The adult questions become available.
- Free trial Client opens My Health
  - The upgrade prompt is shown.
- Client leaves an edit screen without saving
  - They’re asked to confirm first.
- Saving fails, or the Client is offline
  - The Client can try again, or changes are saved when they’re back online.
Non-functional Requirements:
- My Health should load within 2 seconds, and saving a section should take no more than 3 seconds.
- Answers are saved as a draft while the Client edits, so nothing is lost if the app closes.
- The questions shown, and the completion status, follow the routing document, kept as a configurable rule set that can change without an app release.
- Health information is encrypted, and stored in the HIPAA-compliant cloud (Azure).
- Your body, intersex variation, hormone, surgery, gender identity and sex at birth answers are never sent to analytics tools, ad pixels or Shopify.
- A teen’s own health profile can never be seen from the parent’s account.
- Every change to the health profile is recorded in the backend logs, with the date and whether it came from the Client or a conversation, and retained for six years (BAA Section 13).
Validation Rules/Errors:
- Date of birth or sex at birth edit attempted: “Your date of birth and sex assigned at birth can’t be changed here. If something is wrong, please contact the support team.”
- “Not listed” or “Other” left empty: “Tell me in your own words how you identify.” / “Tell me which pronouns you’d like me to use.”
- Medicine or supplement added without a name: “Please add the name of the medication or supplement.”
- Invalid number (for example, age at first period or hours of sleep): “That number doesn’t look quite right. Could you check it for me?”
- Deleting an optional sensitive answer: “Remove this answer? I won’t use it in your guidance any more.”
- Leaving without saving: “You have unsaved changes. Leave without saving?”
- Changes saved: “Thanks, I’ve updated your health profile.”
- Profile reaches 100%: “That’s everything I need. Thank you for taking the time.”
- Free trial: “My Health is part of your plan. Choose a plan to unlock it.”
- Save failed: “We couldn’t save your changes just now. Please try again.”
- Offline: “You’re offline. You can see your profile, and changes will be saved when you’re back online.”
## 7. Epic: My Wellness Plan
### 7.1 - View & Update the Wellness Plan
### Requirement Statement:
As a Client, I want my Wellness Plan to be created and kept up to date automatically from my conversations, and to view it in one place, so that I can follow my progress and always know what to focus on next.
### Specifications:
Story Details:
- Automatic Creation
  - The Wellness Plan is created automatically by the system. The Client doesn’t create it themselves.
  - It’s created when the Oracle shares a profile’s first guidance summary, using the conversation, the health profile and Deborah’s approved content (see story 3.3).
  - The Client sees: “I’ve started your Wellness Plan. It’s where we’ll keep track of everything we’re working on together.”
  - Who has a plan:
    - the Client
    - each family member on the Family plan, viewed by the Client as advocate
    - teens, with education only (see “Teens and Children” below)
  - Each profile has one Wellness Plan, however many conversations there are.
- Opening the Plan
  - The Client can open the plan from:
    - the Wellness Plan card on the Home Dashboard (see story 4.1)
    - the Wellness Plan card at the top of My Health (see story 6.1)
    - the Wellness Plan link in a guidance summary (see story 3.3)
    - a plan update notification (see story 12.1)
  - The plan shown is always the active profile’s, using their name, for example “Azka’s Wellness Plan”. The Client can switch using the profile icon (see story 4.2).
- Wellness Plan Card
  - The card shows the current focus, for example “Immediate dietary action”, and progress through the To Do list, for example “0/8”, with progress dots.
  - Each dot fills when an item is done, like a pill organiser (Session 7).
- Plan Screen
  - The plan screen shall include “Last updated” and the date at the top, followed by the two parts of the plan.
  - The Client always sees the latest version of their plan. Earlier versions aren’t shown.
  - Part 1, personal to the Client:
    - Clinical summary: a short, plain-language overview of what the Oracle has identified.
    - Immediate dietary action: the one most important diet change to start now, shown as a highlighted callout.
    - Focus areas:
      - one section for each concern being worked on, for example “Sleep and night sweats” or “Gut health”
      - newest at the top
      - each can be expanded to see its recommendations and time frame, for example “for 2 to 4 weeks”
    - To Do list: the concrete steps, for example “Ask your provider about a full thyroid panel”.
      - Each item has a tick box, and shows as open or done, with the date completed.
  - Part 2, the Five Pillars: the foundation of Deborah’s approach, shown as an accordion. Each pillar opens to show the Client’s personal adjustments, and a See the protocol link to the matching section of the Wellness Protocols library:
    - Foundational Nutraceuticals (adults only):
      - Personal adjustment: whether Genesis Gold® alone, or with Sacred Seven®, is recommended, plus any condition-specific supplements.
      - Link: the Genesis Gold® tab, and the Sacred Seven® tab when recommended.
    - Diet:
      - Personal adjustment: the Client’s DMAR® Healthy Four targets, worked out from their lean body mass and weight, and their current Insulin Resistance Diet phase.
      - Link: Healthy Four, and the Insulin Resistance Diet.
    - Activity:
      - Personal adjustment: any changes to the standard HIIT routine.
      - Link: HIIT, and Contraction-Relaxation.
    - Sleep:
      - Personal adjustment: for example, a target bedtime.
      - Link: Sleep: Deep Sleep & Longevity, and the 7 Secrets to Healthy Hormones.
    - Mindset:
      - Personal adjustment: for example, a daily CALM practice to start with.
      - Link: CALM, and the Healing Meditation.
    - If the Client’s lean body mass isn’t known, the Diet pillar shows: “Share your measurements with me, and I’ll work out your personal targets.”
- Using the Plan
  - Ticking items: the Client ticks a To Do item to mark it done, and the progress dots update straight away. They can untick an item marked done by mistake.
  - Ask the Oracle: each focus area and To Do item has an Ask the Oracle option, which opens a conversation about it. For example: “Can you explain why I should try the Insulin Resistance Diet?”
- Automatic Updates
  - The plan is a running document, and the system keeps it current (Session 7).
  - Whenever something new is saved for that profile, the system checks whether it changes the plan, and updates it straight away. It only looks at the new item, not everything saved before.
  - The plan is updated automatically when:
    - a conversation ends with a new guidance summary: the new recommendations are added (see story 3.3)
    - the Client logs or edits a provider visit: the provider’s next steps and tests are added to the To Do list, and anything already done is ticked off (see story 5.2)
    - the Client updates their health profile: for example, a new medicine is checked against the plan so nothing conflicts, and new measurements update the Diet pillar’s Healthy Four targets (see story 6.1)
  - Lab values: if the Client types lab values in a conversation, the plan can suggest discussing them with a provider. It never says what the numbers mean for them (Deborah’s email, 28 Oct).
  - How new items are placed:
    - New information about something already in the plan updates that part, instead of adding it twice.
    - Something new becomes a new focus area at the top. Existing focus areas stay, and move down.
  - Example: Sarah’s plan already has a “Sleep” focus area.
    - She starts a new conversation about bloating, and the system adds a new “Gut health” focus area at the top.
    - A week later, she logs a visit where her GP ordered a thyroid panel. The system adds “Get your thyroid panel done” to her To Do list, and ticks off “Ask your provider about a thyroid panel”.
  - Showing updates: every update shows “Last updated” with the date at the top of the plan, and the Client is notified (see story 12.1).
- Safety Rules for Protocols and Products

ð Attach: “Oracle · Wellness Protocols” document, the source of the dosing notes and protocols these rules apply to

  - Genesis Gold®: before recommending it, the Oracle checks the health profile for hyperthyroidism. If it’s there, the Oracle suggests starting with Sacred Seven® alone, and asking the provider before adding Genesis Gold®.
  - Gen-Pro®: the Oracle gives the basic directions from the label, “How to take it (from the label): 2 pumps, twice daily”, and links to the Gen-Pro® protocol. It never sets a different dose.
  - Gender-affirming hormones: for anyone on them, the Oracle can explain how Gen-Pro® and supplements relate to their hormones, but always adds: “Talk with the provider who manages your hormones before adding progesterone or other hormone products.”
  - Liver-Kidney Cleanse and Gallbladder Flush:
    - added only after the Oracle has checked the profile for reasons not to (for example, pregnancy, gallstones, kidney disease or diabetes)
    - the Oracle suggests the Beet Test first
  - Teens and children: updates never add Genesis Gold®, Sacred Seven®, Gen-Pro®, any other product, or any cleanse.
- Products, Links and Disclosure (adults only)
  - Only links are shown for products:
    - the Genesis Shopify store
    - Deborah’s Fullscript store
    - Test links Deborah has supplied
    - other recommended products
  - No prices, discounts, “buy now” or “Subscribe & Save” are shown anywhere in the plan or the library.
  - The product disclaimer is shown within the plan whenever products appear (Session 9).
  - Disclosure box: one box is shown whenever Genesis products/affiliate link appear, saying: “Genesis Health Products, which makes Your Oracle, also makes and sells Genesis Gold®, Sacred Seven® and Gen-Pro®”
- No Contradictions
  - Before adding anything, the system checks it against the rest of the plan and the profile’s medicines, so a new recommendation never conflicts with an existing one.
  - If a provider’s new prescription conflicts with an item in the plan, the Oracle flags it: “Your new prescription may not go well with item 6 in your plan. Please mention it to your provider or pharmacist.”
- Following Up on Items (Session 7)
  - When a time frame ends, or a To Do item is due, the Oracle asks in a conversation or check-in. For example: “We talked about the sleep routine for two weeks. How has it been going?”
  - When the Client starts any new conversation, the Oracle uses the plan as context. For example: “Is the indigestion we talked about keeping you up, or is it the hot flashes?”
- Completing and Removing Items
  - To Do items are marked done when the Client ticks them, or confirms them in a conversation or check-in, for example “Yes, I had the blood test”. Either way, the Oracle won’t ask about it again.
  - Focus areas are removed by the system when the Client confirms the concern has resolved, or the course is finished. For example: “You’re no longer having insomnia? I’ll take that off your plan.”
  - The Five Pillars stay for the long term. They change only when a pillar’s recommendation is adjusted, for example moving to the next Insulin Resistance Diet phase.
- Wellness Protocols Library

ð Attached: “Oracle · Wellness Protocols” document, the source content for the library

  - Deborah’s protocols in one place, with four tabs:
    - Genesis Gold®: what it is, what’s inside, what it supports, and how to take it
    - Sacred Seven®: what it is, when it’s recommended, and how to take it
    - Gen-Pro®: what it is, when it’s recommended, and the directions on the label
    - Lifestyle protocols:
      - Nutrition (the DMAR® Healthy Four)
      - the Insulin Resistance Diet
      - the Beet Test
      - the Liver-Kidney Cleanse
      - HIIT
      - Contraction-Relaxation
      - CALM
      - the Healing Meditation
      - the 7 Secrets to Healthy Hormones
      - Sleep: Deep Sleep & Longevity
  - Product tabs:
    - each shows its FDA disclaimer and the ownership disclosure
    - only a “Shop” link to the Genesis Shopify store, using the app’s own link
  - CALM links to the full guide on Deborah’s blog.
  - Where the library opens from: the Home Dashboard, the Five Pillars, and links in conversations. Every link opens the right tab and section.
  - The Beet Test and the cleanses aren’t linked from the Five Pillars. They’re linked only when the Oracle recommends them.
- Teens and Children
  - Teens get a Wellness Plan, created and updated automatically, and written as education only:
    - no Genesis Gold®, Sacred Seven®, Gen-Pro®, any product, dosing or cleanses
    - the Foundational Nutraceuticals pillar isn’t shown
    - in the library, the product tabs, shop links and cleanse protocols aren’t shown
  - Teen with their own account: sees their own plan. The parent can’t see it.
  - Teen managed by a parent: the parent sees it, as advocate.
  - Children under 13: no products or cleanses, viewed by the advocate.
- Free Trial
  - No plan is created or updated for free trial Clients.
  - The Wellness Plan is greyed out, with a short description of what it is and an upgrade prompt (see story 9.1).
Acceptance Criteria:
- Created automatically: Given a subscribed Client’s first guidance summary, when it’s shared, then the system creates their Wellness Plan. The Client never creates it themselves.
- One plan per profile: Given a profile has many conversations, when the plan is viewed, then there’s only one running plan.
- Opening: Given a subscribed Client, when they open the plan from the dashboard, My Health, a guidance summary or a notification, then the active profile’s plan opens.
- Latest version: Given the plan has been updated, when the Client opens it, then only the latest version is shown, with “Last updated” and the date.
- Card: Given a plan exists, when the card is shown, then it shows the current focus and To Do progress with dots.
- Plan screen: Given the plan opens, when it loads, then it shows “Last updated”, the clinical summary, the immediate dietary action, focus areas (newest first), the To Do list and the Five Pillars.
- Ticking items: Given the Client ticks or unticks a To Do item, when it changes, then the progress dots and completion date update straight away, and the Oracle doesn’t ask about it again.
- Pillars: Given a pillar is opened, when it expands, then it shows the personal adjustments and a link to the matching library section.
- Diet targets: Given lean body mass is known, when the Diet pillar opens, then it shows the Healthy Four targets. Otherwise, it asks for measurements.
- Updated automatically: Given a new guidance summary, a logged or edited visit, or a health profile change, when it’s saved, then the system updates the plan straight away, using only the new item.
- Lab values: Given the Client typed lab values, when the plan updates, then it never interprets them.
- Placement: Given new information about an existing concern, when the plan updates, then that focus area updates. A new concern is added at the top, and existing focus areas stay.
- Safety rules:
  - Genesis Gold® isn’t recommended without checking for hyperthyroidism.
  - The Oracle gives the basic directions from the label for Gen-Pro®, and never sets a different dose.
  - The gender-affirming hormones line is always shown when relevant.
  - Cleanses are added only after the safety checks, never for teens or children.
- Links only: Given any product item or product tab, when it’s shown, then only links appear, with no prices, discounts, “buy now” or “Subscribe & Save”.
- Disclosure: Given Genesis products or affiliate links appear, when the plan is shown, then the disclaimer and one disclosure box appear within it.
- No contradictions: Given a new item, when it’s added, then it never conflicts with existing items or medicines. A conflicting new prescription is flagged.
- Updates shown: Given the plan updates, when the Client opens it, then “Last updated” shows the date, and the Client is notified.
- Follow-ups: Given an item’s time frame ends or it’s due, when the Client next talks to the Oracle, then it follows up on it.
- Focus areas removed: Given the Client confirms a concern has resolved, when the plan updates, then that focus area is removed.
- Ask the Oracle: Given the Client taps Ask the Oracle on an item, when it opens, then a conversation about that item starts.
- Library: Given the library opens, when it loads, then it has the Genesis Gold®, Sacred Seven®, Gen-Pro® and Lifestyle protocols tabs, and links open the right section.
- Product tabs: Given a product tab, when it’s shown, then it includes its FDA disclaimer, the ownership disclosure, and a Shop link to the Genesis Shopify store.
- Teens and children: Given a teen or child profile, when the plan or library is created, updated or opened, then it’s education only, with no products, dosing, cleanses, Foundational Nutraceuticals pillar, product tabs or shop links.
- Teen privacy: Given a teen with their own account, when the parent is signed in, then they can’t see the teen’s plan.
- Free trial: Given a free trial Client, when a guidance summary is shared or they open the plan, then no plan is created, and they see the description and upgrade prompt.
Alternate Scenario:
- No plan yet
  - The Client hasn’t had a guidance summary, and sees the “no plan yet” message.
- New concern
  - The system adds it at the top of the plan.
- Same concern in a second conversation
  - The existing focus area is updated, not duplicated.
- Short-term concern (for example, a cold)
  - It goes to the top, and comes off once resolved.
- Lean body mass unknown
  - The Diet pillar asks for measurements.
- Item ticked by mistake
  - The Client unticks it.
- All To Do items done
  - The Client sees a well-done message.
- Hyperthyroidism in the profile
  - The Oracle suggests starting with Sacred Seven® alone, and checking with their provider.
- Client asks how to take Gen-Pro®
  - The Oracle gives the basic directions from the label.
- Cleanse not suitable (for example, the Client is pregnant)
  - It isn’t added.
- New prescription conflicts with the plan
  - The Oracle flags it.
- Concern hasn’t improved
  - The focus area stays.
- Visit log that added items is deleted
  - The Client chooses whether to keep or remove those items (see story 5.2).
- Client taps Shop
  - The Genesis Shopify store opens.
- Client switches to a family member
  - That family member’s plan is shown.
- Teen’s plan or library
  - It’s education only, with no products, product tabs or cleanses.
- Free trial Client
  - No plan is created, and the upgrade prompt is shown.
- Plan can’t load or update, or the Client is offline
  - The Client can try again, or sees the plan they already loaded.
Non-functional Requirements:
- The plan should be created or updated within 10 seconds of new information being saved.
- The plan and the library should load within 2 seconds, and ticking an item should update the plan within 1 second.
- Every plan update is recorded in the backend with the date and what changed, for audit. Only the latest version is shown to the Client.
- Plan content comes only from the Client’s information and Deborah’s approved content, including the Wellness Protocols in the knowledge base.
- The safety rules are kept in the AI guardrails, and library content is managed by Deborah’s team, so both can be updated without an app release.
- Each library section has its own link target, so links open the exact section.
- Shop links open Shopify as an external link only, and no health information is sent to Shopify (SOW Appendix C).
- The plan follows the AI guardrails: no diagnosis, no prescriptions, no dosing for prescription medicines (Genesis products follow the directions on the label), and no wording that implies a healthcare licence
- Plans are encrypted, stored in the HIPAA-compliant cloud (Azure), and never shared with analytics tools, ad pixels or Shopify.
- A teen’s own plan can never be seen from the parent’s account.
Validation Rules/Errors:
- Plan created: “I’ve started your Wellness Plan. It’s where we’ll keep track of everything we’re working on together.”
- Plan updated: “Your Wellness Plan has been updated.”
- Focus area removed: “Your Wellness Plan has been updated, because you’ve confirmed you’re no longer having these issues.”
- No plan yet: “Your Wellness Plan will appear here after our first conversation. Tell me how you’re feeling, and we’ll get started.”
- Lean body mass unknown: “Share your measurements with me, and I’ll work out your personal targets.”
- All To Do items done: “You’ve completed everything on your list. Well done!”
- Hyperthyroidism in the profile: “Because of your thyroid, it’s best to start with Sacred Seven® on its own and check with your provider before adding Genesis Gold®.”
- How to take Gen-Pro®: “How to take it (from the label): 2 pumps, twice daily. Here’s the Gen-Pro® protocol, too.”
- Gender-affirming hormones: “Talk with the provider who manages your hormones before adding progesterone or other hormone products.”
- Cleanse not suitable: “A cleanse isn’t the right fit for you right now. Let’s focus on other ways to support your body.”
- New prescription conflicts: “Your new prescription may not go well with item [X] in your plan. Please mention it to your provider or pharmacist.”
- Free trial: “Subscribe to get your personal Wellness Plan.”
- Item couldn’t be updated: “We couldn’t update this item just now. Please try again.”
- Plan couldn’t be updated: “I couldn’t update your Wellness Plan just now. I’ll try again shortly.”
- Plan couldn’t load: “We couldn’t load your Wellness Plan. Please try again.”
- Offline: “You’re offline. You can see your plan, and any changes will be saved when you’re back online.”
-

## 8. Epic: Family Management
### 8.1 - Add Family Member
### Requirement Statement:
As a Client, I want to add a family member to my account, so that I can look after their health as their medical advocate.
### Specifications:
Story Details:
- Where to Add a Family Member
  - The Client can add a family member, on the Mobile App or Web App, from:
    - For a family member, during onboarding (see story 2.1)
    - Add family member, on the My Family card on the Home Dashboard (see story 4.1)
    - Add family member, in the profile panel (see story 4.2)
    - + Add family member, on the Manage Family screen (see story 8.2)
  - Teens with their own account can’t add family members.
- Plan Check
  - Family members are part of the Family plan.
  - On the free trial or the Individual plan: tapping Add family member shows the upgrade prompt for the Family plan (see story 9.1).
- Family Member Places
  - The Family plan includes the account holder plus 3 active family members (1 + 3).
  - Invited teens with their own account count towards the limit, the same as family members managed by the Client.
  - An invited teen uses a place as soon as the invite is sent, so a place must be free to send it.
  - Only active family members count. Disabled family members don’t (see story 8.2).
  - The Manage Family screen shows how many are in use, for example “2 of 3 active family members”.
- When All Places Are Used
  - Tapping Add family member offers a paid add-on for another family member. The price is set by the admin team in the admin panel (see Super Admin story 8.1).
  - The Client can buy the add-on and continue, or disable another family member to free a place (see story 8.2).
- Adding the Family Member
  - The Client goes through the family member intake (see story 2.2):
    - Who are they to you? (Parent, Child, Partner, Someone else)
    - Their first name
    - Their date of birth
    - Teens only: Teen with their own account, or Manage [Name]’s profile myself
    - Medical advocate consent
    - Sex assigned at birth
    - Gender identity
    - Pronouns
- Age Groups
  - Worked out from the family member’s date of birth, using the age of majority for the Client’s state (18 in most states, 19 in Alabama and Nebraska, 21 in Mississippi):
    - Under 13: parent-managed only. They never get their own login.
    - Teens (13 up to the age of majority): education only, with no products.
      - Teen with their own account: an invite is sent, and the teen sets up their own login (see story 1.5).
      - Managed by the Client: the Client manages the profile as advocate.
    - Age of majority and over: standard guidance for their age.
- Once Added
  - Family members managed by the Client:
    - appear as active in the profile panel and on the Manage Family screen
    - become the active profile
    - the Oracle opens: “Thank you, [Client’s first name]. I’m glad you’re here for [Name]. Tell me what’s been going on, and I’ll ask what I need as we go.”
    - the Client can start a conversation about them, and their Wellness Plan is created automatically after their first guidance summary (see story 7.1)
  - Invited teens:
    - appear on the Manage Family screen with their status (Invite sent, Joined or Access paused)
    - don’t appear in the profile panel (see story 4.2)
Acceptance Criteria:
- Entry points: Given the Client is on the Family plan, when they tap add a family member from onboarding, the Home Dashboard, the profile panel or the Manage Family screen, then the family member intake opens.
- Plan check: Given the Client is on the free trial or the Individual plan, when they tap Add family member, then the upgrade prompt for the Family plan is shown.
- Places shown: Given the Manage Family screen opens, when it loads, then it shows how many of the 3 active places are in use, including invited teens.
- Invited teens count: Given the Client invites a teen with their own account, when the invite is sent, then the teen uses one of the family member places.
- Disabled members: Given a family member is disabled, when places are counted, then they don’t count towards the limit.
- All places used: Given 3 active family members, including invited teens, when the Client adds or invites another, then a paid add-on is offered, with the option to disable another family member instead.
- Intake: Given the Client adds a family member, when the intake runs, then it includes medical advocate consent, and the teen choice for teens.
- Age groups: Given the date of birth is entered, when the age is worked out, then the family member is placed in the right age group, using the age of majority for the Client’s state.
- Managed member added: Given a managed family member is added, when the intake finishes, then they’re active, appear in the profile panel and on Manage Family, and become the active profile.
- Invited teen added: Given the Client invites a teen, when the invite is sent, then the teen appears on Manage Family with their status, but not in the profile panel.
- Teens can’t add: Given a teen with their own account, when they look for Add family member, then it isn’t available.
Alternate Scenario:
- Not on the Family plan
  - The Client sees the upgrade prompt, and can upgrade or cancel.
- All places used, Client buys an add-on
  - The family member is added after payment.
- All places used, Client disables another member
  - A place is freed, and the new member is added.
- All places used when inviting a teen
  - The Client is offered an add-on, or can disable another family member, before the invite is sent.
- Client declines the upgrade or add-on
  - No family member is added.
- Payment fails
  - No family member is added, and the Client can try again.
- Client leaves the intake part-way
  - They can finish it later.
- No consent option selected
  - The Client can’t continue.
- Child under 13
  - They’re added as parent-managed only.
- Teen
  - The Client chooses to invite them, or manage their profile.
Non-functional Requirements:
- The family member limit and the add-on price are configurable by the admin team, without an app release.
- Payments go through the agreed payment providers (Stripe, Apple Pay, Google Pay).
- The age-of-majority table can be updated without an app release.
- The medical advocate consent is recorded with the date and time.
- Each family member’s information is kept separate, encrypted, stored in the HIPAA-compliant cloud (Azure), and never shared with analytics tools, ad pixels or Shopify.
Validation Rules/Errors:
- Not on the Family plan: “Adding family members is part of the Family plan. Upgrade to add [Name].”
- All places used: “You have 3 active family members, the most your plan includes. Add another member, or turn off another family member to make room.”
- Payment failed: “We couldn’t process your payment. Please check your payment details and try again.”
- No consent option selected: “Please let me know how you’re able to look after [Name]’s health.”
- First name left empty: “What should I call them? Please enter their first name.”
- No teen option selected: “Please choose how you’d like to set up [Name]’s profile.”
### 8.2 - Manage Family Profiles

Requirement Statement:
As a Client, I want to see and manage all my family members in one place, so that I can keep their details up to date, choose which profiles are active, and look after each of them.
### Specifications:
Story Details:
- Opening Manage Family
  - The Client opens it from Profile & Account (see story 11.1), or the My Family card on the Home Dashboard (see story 4.1).
  - Manage Family is part of the Family plan (see story 8.1).
- Manage Family Screen
  - The screen shall include:
    - Places in use at the top, for example “2 of 3 active family members”, including invited teens
    - A card for each family member managed by the Client, with:
      - their initial, first name and relationship, for example “Azka · Child”
      - their age
      - their health profile completion, for example “60% complete” (see story 6.1)
      - an Active toggle (on or off)
      - a ⋯ menu with View & edit, and Remove
    - A card for each invited teen, with:
      - their initial, first name and relationship
      - their status: Invite sent, Joined, Turned off or Access paused (see story 1.5)
      - an Active toggle (on or off)
      - a ⋯ menu with Resend invite (while the invite is pending), and Remove
      - No health information, completion or View & edit, because the parent can’t see the teen’s information.
    - + Add family member button (see story 8.1)
- Switching to a Family Member
  - The Client taps an active, managed family member’s card, and that family member becomes the active profile across the app (see story 4.2).
  - The Client sees: “You’re now viewing [Name]’s profile.”
  - Disabled family members and invited teens can’t be switched to.
- Turning a Profile Off
  - The Client switches the Active toggle off on a family member’s card, and confirms.
  - For a managed family member:
    - They no longer count towards the limit, and their place becomes free.
    - Their information is kept, but they’re hidden from the profile panel, and can’t be used for conversations.
    - Reminders, follow-ups and Wellness Plan check-ins for them are paused.
    - If they were the active profile, the app switches back to the Client’s own profile.
  - For an invited teen:
    - They no longer count towards the limit, and their place becomes free.
    - The teen loses access to their account while it’s off. When they sign in, they can see their Privacy & Data in the app only, where they can still export their data or request deletion (see story 11.4).
    - The teen’s information is kept, and the parent still can’t see it.
  - In both cases, the card stays on the Manage Family screen, greyed out, marked “Turned off”.
- Turning a Profile Back On
  - The Client switches the Active toggle on.
  - A place is free:
    - managed family member: active again, appears in the profile panel, and their reminders and follow-ups resume
    - invited teen: their access is restored, with their information intact
  - All places are used: the Client is offered a paid add-on, or can turn off another family member first.
- Viewing and Editing a Managed Family Member
  - The Client opens View & edit and sees their details:
    - Can be edited: first name, relationship, gender identity and pronouns
    - Read-only: date of birth and sex assigned at birth, because they decide which questions apply (the same rule as story 6.1)
    - Health profile: a link opens their full health profile (see story 6.1)
  - The Client taps Save, and the Oracle uses the updated details straight away.
- Invited Teens
  - Resend invite: sends a new invite email, and the old link stops working.
  - Access paused: shown when the Family plan isn’t active (see story 1.5).
  - Reaching the age of majority: once the teen creates their own account, their card is removed, and the place is freed (see story 1.6).
- Removing a Managed Family Member
  - The Client taps Remove in the ⋯ menu.
  - Confirmation: the Client sees what will happen, and types [Name]’s first name to confirm.
  - Deletion request:
    - The Client receives an acknowledgement straight away.
    - 10-day grace period: [Name]’s profile stays fully usable, so the Client can keep using it and download [Name]’s information. [Name]’s card shows “Scheduled for deletion on [date]”.
    - After 10 days, [Name]’s profile is locked, and the request goes to the Super Admin (see Super Admin story 5.2).
  - Review and deletion: the Super Admin checks for any legal hold, and completes the deletion within 45 calendar days of the request (CCPA/CPRA). The Client is notified once it’s done.
  - What happens when the deletion is completed:
    - Their information: their health profile, conversations, guidance summaries, provider-ready notes, visit logs and Wellness Plan are permanently deleted, including from backups (BAA Sections 18 and 32).
    - Active profile: if they were the active profile, the app switches back to the Client’s own profile (or, for advocate-only Clients, to another family member).
    - Places: their place becomes free.
    - Reminders: all reminders and follow-ups for them are cancelled.
    - Escalations: any open escalations stay with the support team until closed.
    - Record keeping: the request and the deletion are recorded in the backend logs, and retained for six years (BAA Section 13).
- Removing an Invited Teen
  - The Client taps Remove in the ⋯ menu, and confirms.
  - What happens:
    - The teen’s place becomes free straight away.
    - The teen is notified, and keeps full use of their account for 10 days, so they can download their data.
    - After 10 days, the teen’s account is locked, the request goes to the Super Admin, and the account and data are deleted within 45 calendar days of the removal.
  - The removal is recorded in the backend logs, and retained for six years.
- Advocate-Only Clients
  - A Client who has deleted their own data and manages only family members (see story 11.4) sees only their family members.
  - They can’t turn off or remove their last active family member.
Acceptance Criteria:
- Screen: Given the Client opens Manage Family, when it loads, then it shows how many of the 3 active places are in use (including invited teens), a card for each family member, and Add family member.
- Managed member cards: Given a managed family member, when their card is shown, then it shows their first name, relationship, age, health profile completion, an Active toggle, and a ⋯ menu with View & edit and Remove.
- Invited teen cards: Given an invited teen, when their card is shown, then it shows their first name, relationship, status and an Active toggle, with Resend invite (while pending) and Remove, and no health information.
- Switching: Given an active, managed family member, when the Client taps their card, then they become the active profile across the app. Disabled members and invited teens can’t be switched to.
- Turning off a managed member: Given the Client turns a managed profile off, when they confirm, then a place is freed, their information is kept, they’re hidden from the profile panel, their reminders pause, and their card shows “Turned off”.
- Turning off an invited teen: Given the Client turns an invited teen off, when they confirm, then a place is freed, the teen loses access, and the teen’s information is kept.
- Switch back: Given the turned-off member was the active profile, when they’re turned off, then the app switches back to the Client’s own profile.
- Turning on: Given a place is free, when the Client turns a profile on, then it’s active straight away, and an invited teen gets their access back. When all places are used, a paid add-on is offered, with the option to turn off another member.
- Editing: Given View & edit is open, when the Client makes changes, then first name, relationship, gender identity and pronouns can be edited. Date of birth and sex at birth are read-only.
- Resend invite: Given an invite is pending, when the Client taps Resend invite, then a new invite email is sent, and the old link stops working.
- Removing a managed member: Given the Client removes a managed family member and types their name, when they confirm, then the Client is acknowledged, and the profile stays usable for 10 days, showing its deletion date.
- After the grace period: Given 10 days have passed, when the grace period ends, then the profile is locked, and the request goes to the Super Admin.
- Deletion completed: Given the Super Admin completes the deletion, when it’s done, then all the information is permanently removed within 45 calendar days of the request, unless a legal hold applies, the place is freed, reminders are cancelled, and the Client is notified.
- Removing an invited teen: Given the Client removes an invited teen, when they confirm, then the place is freed, the teen is notified, keeps full use for 10 days, and their account and data are then deleted.
- Advocate-only: Given an advocate-only Client, when they try to turn off or remove their last active family member, then they can’t.
Alternate Scenario:
- Client turns a profile off, then back on
  - Their information is all still there.
- Invited teen turned off
  - The teen sees a message asking them to speak to their parent or guardian.
  - Access returns when the profile is turned back on.
- Invited teen removed
  - To have their data deleted, the teen emails the support team from their registered email address
- Client keeps using a family member’s profile during the grace period
  - Everything works as normal until the deletion date.
- All places used when turning a profile on
  - The Client buys an add-on, or turns off another member first.
- Invite not accepted
  - The Client resends the invite.
- Invited teen removed
  - The teen loses access, and their data is kept. They can export it or request deletion in Privacy & Data.
- Invited teen reaches the age of majority
  - Their card is removed once they create their own account, and the place is freed.
- Typed name doesn’t match
  - The deletion isn’t requested.
- Deletion is on legal hold
  - The deletion waits, and the Client is told.
- Advocate-only Client tries to remove their last member
  - They’re asked to delete their account instead.
- Action fails
  - The Client can try again.
Non-functional Requirements:
- The Manage Family screen should load within 2 seconds, and switching or toggling a profile should complete within 2 seconds.
- The family member limit and the add-on price are configurable by the admin team, without an app release.
- Turning a profile off keeps all its information. Nothing is deleted.
- An invited teen’s access must follow their Active toggle straight away.
- Deletion requests are acknowledged straight away, have a 10-day grace period with full use, and are completed within 45 calendar days of the request, including from backups, unless a legal hold applies (CCPA/CPRA).
- Each family member’s information is kept separate, encrypted, stored in the HIPAA-compliant cloud (Azure), and never shared with analytics tools, ad pixels or Shopify.
- An invited teen’s information can never be seen or deleted from the parent’s account.
- Every edit, toggle, invite, removal, deletion request and deletion is recorded in the backend logs, and retained for six years (BAA Section 13).
Validation Rules/Errors:
- Turning a profile off: “Turn off [Name]’s profile? Their information will be kept, and you can turn it back on any time.”
- Turning off an invited teen: “Turn off [Name]’s access? They won’t be able to use Your Oracle until you turn it back on. Their information will be kept.”
- Profile turned off: “[Name]’s profile is turned off.”
- Teen’s access turned off (shown to the teen): “Teen’s access turned off (shown to the teen): “Your access is paused. Please ask your parent or guardian. You can still download your data or ask for it to be deleted here.”
- All places used when turning on: “You have 3 active family members, the most your plan includes. Add another member, or turn off another family member first.”
- Payment failed: “We couldn’t process your payment. Please check your payment details and try again.”
- Invite resent: “We’ve sent [Name] a new invite.”
- Removing an invited teen: “Remove [Name] from your family? [Name] will have 10 days to keep using Your Oracle and download their information. After that, their account and information will be deleted.”
- Advocate-only Client removes the last member: “[Name] is the only active person on your account. To remove them, please delete your account instead.”
- First name left empty: “Please enter their first name.”
- “Not listed” or “Other” left empty: “Tell me in your own words how [Name] identifies.” / “Tell me which pronouns you’d like me to use for [Name].”
- Date of birth or sex at birth edit attempted: “[Name]’s date of birth and sex assigned at birth can’t be changed here. If something is wrong, please contact the support team.”
- Delete confirmation: “Delete [Name]’s data? All of [Name]’s information will be permanently deleted. This can’t be undone.”
- Typed name doesn’t match: “Please type [Name]’s first name to confirm.”
- Deletion requested: “Your request has been received. [Name]’s profile will be deleted after [date]. You can keep using it until then.”
- Deletion completed: “[Name]’s data has been deleted.”
- Changes saved: “Thanks, I’ve updated [Name]’s details.”
- Action failed: “We couldn’t do that just now. Please try again.”
- Shown to the removed teen: “Your parent or guardian has removed you from their family plan. You can keep using Your Oracle and download your information until [date]. After that, your account and information will be deleted.”
## 9. Epic: Subscription Activation
### 9.1 - Start Free Trial & Activate Subscription
Requirement Statement:
As a Client, I want to try the Oracle for free and then subscribe when I’m ready, so that I can see its value before I pay, and keep my access afterwards.
### Specifications:
Story Details:
- Starting the Free Trial
  - Every new Client starts a free trial automatically when they create their account (see story 1.1).
  - New adults moving from a teen account also start a free trial (see story 1.6).
  - The trial lasts 14 days, set by the admin team in the admin panel (Session 9).
- What the Free Trial Includes
  - conversations with the Oracle, for the Client’s own profile only
  - the guidance summary, viewed in the conversation (see story 3.3)
  - provider-ready notes, viewed in the conversation (see story 3.4)
- What’s Greyed Out During the Free Trial
  - Each shows an upgrade prompt when tapped (Session 9):
    - My Health (see story 6.1)
    - My Visit Notes and visit logging (see stories 5.1 and 5.2)
    - the Wellness Plan (see story 7.1)
    - adding family members (see story 8.1)
    - downloading, printing or copying guidance summaries and provider notes (see stories 3.3 and 3.5)
- During the Trial
  - The Home Dashboard shows how many days are left, with a Choose a plan button (see story 4.1).
  - The Client is reminded before the trial ends (see story 12.1).
- When the Trial Ends Without a Subscription
  - The message box is locked, and the Client sees the upgrade prompt when they sign in or open a conversation (see stories 1.2 and 3.1).
  - The Client can still sign in and see the plan screen.
  - Their history is kept.
- Plan Screen
  - The Client opens it from Choose a plan, an upgrade prompt, or Profile & Account (see story 11.3).
  - The plan screen shall include:
    - Individual plan: the monthly price, and what’s included:
      - unlimited conversations with the Oracle
      - personalised guidance
      - provider-ready notes to download and print
      - My Visit Notes and visit logging
      - My Health
      - a Wellness Plan
      - the Client’s own profile only
    - Family plan: the monthly price, and what’s included:
      - everything in the Individual plan
      - the Client plus 3 family members, each with their own Wellness Plan
      - inviting teens to their own account (see story 1.5)
    - Extra family members: the monthly price per extra family member (add-on), Family plan only
    - Renewal disclaimer: “Your subscription renews automatically each month until you cancel. You can cancel anytime in Profile & Account.”
  - The plans are described as “unlimited conversations with the Oracle”, not “unlimited consultations”.
  - All prices come from the admin panel.
- Subscribing (First Payment)
  - The Client chooses a plan, taps Subscribe, and chooses how to pay: Apple Pay, Google Pay, or card through Stripe (SOW).
  - They confirm the price and the renewal disclaimer.
  - Once the payment succeeds:
    - the subscription is active straight away
    - everything included in their plan is unlocked
    - their existing conversations, summaries and notes from the trial are kept
    - they see a confirmation, and receive a receipt by email
- Add-ons (per Family Member)
  - When a Family plan Client already has 3 active family members (including invited teens) and adds, invites or turns on another, they see the add-on price per family member (see stories 8.1 and 8.2).
  - The Client confirms, and the add-on is added to their monthly subscription, charged from that day.
- Teens
  - Teens with their own account don’t see the plan screen, and can’t subscribe.
  - Their access is covered by the parent’s Family plan, and pauses if the Family plan ends (see story 1.5).
Acceptance Criteria:
- Trial starts: Given a new Client creates their account, when sign-up finishes, then a 14-day free trial starts automatically.
- Trial access: Given a Client is on the free trial, when they use the app, then they can have conversations and see guidance summaries and provider notes in the conversation, for their own profile only.
- Greyed out: Given a Client is on the free trial, when they tap My Health, My Visit Notes, the Wellness Plan, Add family member, or download, print or copy, then an upgrade prompt is shown.
- Days left: Given a Client is on the free trial, when the dashboard opens, then the days left are shown, and they’re reminded before the trial ends.
- Trial ends: Given the trial ends without a subscription, when the Client signs in or opens a conversation, then the message box is locked, the upgrade prompt is shown, and their history is kept.
- Plan screen: Given the Client opens the plan screen, when it loads, then it shows the Individual and Family plans with their prices and what’s included, the add-on price per family member, and the renewal disclaimer.
- Prices: Given any price is shown, when the plan screen loads, then it comes from the admin panel.
- Paying: Given the Client subscribes, when they pay, then they can use Apple Pay, Google Pay or card (Stripe), and must confirm the price and renewal disclaimer.
- Subscribed: Given the payment succeeds, when the subscription starts, then it’s active straight away, the plan’s features unlock, trial data is kept, and a receipt is emailed.
- Add-ons: Given a Family plan Client has 3 active family members, when they add, invite or turn on another, then the add-on price is shown, and added to the subscription once confirmed.
- Teens: Given a teen with their own account, when they use the app, then they don’t see the plan screen, and can’t subscribe.
Alternate Scenario:
- Trial ends during a conversation
  - The message box is locked, and the upgrade prompt is shown.
- Client subscribes before the trial ends
  - They keep everything from the trial.
- Payment fails or is cancelled
  - The Client stays on the trial (or locked), and can try again.
- Client returns weeks after the trial ended
  - They subscribe, and their history is still there.
- Trial Client tries to add a family member
  - The upgrade prompt for the Family plan is shown.
- Individual plan Client tries to add a family member
  - The upgrade prompt for the Family plan is shown.
- Client subscribes on iPhone, then signs in on the Web App
  - Their subscription is recognised.
- Client adds a 4th family member
  - They confirm the add-on.
- Client declines the add-on
  - No family member is added.
Non-functional Requirements:
- Payments are processed by Stripe, Apple Pay and Google Pay, and card details are never stored by the app.
- The trial length, plan prices and add-on price are configurable in the admin panel, without an app release.
- Access changes (unlocking after payment, locking at trial end) apply within a few seconds.
- Subscription and payment events are recorded in the backend logs.
Validation Rules/Errors:
- Greyed-out feature tapped during the trial: “This is part of your plan. Choose a plan to unlock it.”
- Trial ending soon: “Your free trial ends in [X] days. Choose a plan to keep talking with me.”
- Trial ended: “Your free trial has ended. Choose a plan to keep talking with me.”
- Family member on the wrong plan: “Adding family members is part of the Family plan. Upgrade to add someone.”
- Payment failed: “We couldn’t process your payment. Please check your details or try another way to pay.”
- Payment cancelled: “Your payment was cancelled. You can subscribe whenever you’re ready.”
- Subscription active: “You’re all set. Welcome to the [Individual / Family] plan.”
- Add-on confirmation: “Adding [Name] will add [price] a month to your subscription. Continue?”
## 10. Epic: Support & Consultations
### 10.1 - Contact the Support Team & Consult With Support Team
Requirement Statement:
As a Client, I want to reach the support team when the Oracle can’t help, when I need a person, or when I’m interested in a consultation, so that I’m never left without an answer.
### Specifications:
Story Details:
- When the System Routes the Client to the Support Team
  - Question outside Deborah’s content (knowledge gap):
    - The Oracle says it can’t answer this one, and offers to send it to the support team: “I’m not able to guide you on that one, but I don’t want to leave you without an answer. Shall I send it to the support team? They’ll get back to you within one business day.”
    - If the Client agrees, a support request is sent as a Knowledge Gap, with the question and the Client’s details.
    - The admin team is alerted to the gap, so the missing content can be added (see Super Admin story 6.3).
  - The Client asks for a person in the conversation, for example “Can I talk to someone?”:
    - The Oracle offers to send a message to the support team.
    - If the Client agrees, a support request is sent as Talk to the Support Team, with the Client’s message.
  - Emergency, crisis or urgent concern:
    - The Oracle follows the safety path (see story 3.2).
    - An escalation is recorded for the team to review, not a support request.
    - The team doesn’t follow up or check in on the Client about it.
  - For knowledge gaps and person requests, the Client sees: “I’ve let the support team know. They’ll get back to you by email within one business day.”
- When the Client Contacts the Support Team Themselves
  - The Client taps Contact support team from Profile & Account (see story 11.1).
  - A short form opens, with:
    - How can we help? (text box, Mandatory)
    - Send button
  - The request is sent to the support email as Talk to the Support Team, with the Client’s first name, email address and the active profile.
  - The Client sees: “Thanks, your message has been sent. The support team will reply by email within one business day.”
- Consult With Support Team
  - The Client taps Consult with support team from:
    - the Home Dashboard card (see story 4.1)
    - the guidance summary (see story 3.3)
    - a conversation, when the Oracle suggests it or the Client asks
    - Profile & Account
  - A short form opens, with:
    - What would you like help with? (text box, Mandatory)
    - Send button
  - A Consultation Request is sent to the support team, with the Client’s first name, email address and the active profile.
  - What happens next (outside the app):
    - The support team contacts the Client by email, and decides whether a consultation is right for them.
    - Any consultation is booked and paid outside the app.
  - The app doesn’t show consultation prices, a booking page or payment for consultations.
  - The Client sees: “Thanks, the support team will get in touch by email to talk about the next steps.”
- What Happens Next
  - Every request appears in the support team’s list (see Super Admin story 5.1).
  - The team replies to the Client by email, and marks the request resolved.
- Family Members and Teens
  - Family members: requests show which profile they’re about, so the team knows who the question concerns, for example “Sent by Sarah about Azka”.
  - Teens with their own account:
    - can contact the support team themselves
    - don’t see Consult with support team
Acceptance Criteria:
- Knowledge gap: Given the Oracle can’t answer a question, when it replies, then it offers to send the question to the support team. If the Client agrees, a Knowledge Gap request is sent, and the admin team is alerted.
- Asking for a person: Given the Client asks for a person, when the Oracle replies, then it offers to send a message. If the Client agrees, a Talk to the Support Team request is sent.
- Emergencies: Given an emergency, crisis or urgent concern, when it’s detected, then the safety path is followed, an escalation is recorded, and no support request, follow-up or check-in is sent.
- Reply time: Given a request is sent, when the Client sees the confirmation, then it says the team will reply by email within one business day.
- Contact form: Given the Client opens Contact support team from Profile & Account, when they send a message, then the message is mandatory, and the request is sent with their details and the active profile.
- Consult with support team: Given the Client taps Consult with support team, when they send the form, then a Consultation Request is sent to the support team, with their details and the active profile.
- No booking in the app: Given the Client is in the Consult with support team flow, when it’s shown, then no price, booking page or payment is shown.
- Support list: Given any request is sent, when the team opens their list, then it appears there, showing which profile it’s about.
- Teens: Given a teen with their own account, when they use the app, then they can contact the support team, but don’t see Consult with support team.
Alternate Scenario:
- Client declines to send an unanswered question
  - The conversation continues.
- Client sends the form without a message
  - An error is shown, and the form isn’t sent.
- Client doesn’t reply to the team’s email
  - The team sends an in-app reminder.
- Client asks about a family member
  - The request shows that profile.
- Client is offline when sending
  - The request is sent once they’re back online.
- Sending fails
  - The Client can try again.
Non-functional Requirements:
- Requests reach the support email and the admin support list within 1 minute.
- No health information is sent outside the app with a consultation request, beyond what the Client writes in the form.
- Request messages are encrypted, stored in the HIPAA-compliant cloud (Azure), and only visible to authorised Super Admin and Admin users.
- All contact with the Client is by email or in-app message. No phone contact.
Validation Rules/Errors:
- Message left empty: “Please tell us how we can help.”
- Request sent: “Thanks, your message has been sent. The support team will reply by email within one business day.”
- Question sent from a conversation: “I’ve let the support team know. They’ll get back to you by email within one business day.”
- Consultation request sent: “Thanks, the support team will get in touch by email to talk about the next steps.”
- Sending failed: “We couldn’t send your message just now. Please try again.”
- Offline: “You’re offline. We’ll send your message as soon as you’re back online.
## 11. Epic: Profile & Account Management
### 11.1 - View & Edit My Profile
Requirement Statement:
As a Client, I want to view and update my account details and reach my settings in one place, so that my account stays accurate and easy to manage.
### Specifications:
Story Details:
- Opening the Profile
  - The Client opens Profile & Account from the main navigation, or from Manage profile in the profile panel (see story 4.2).
- Profile & Account Screen
  - The screen shall include:
    - the Client’s initial, first name and email address
    - their address: country, state and ZIP code
    - an Edit button
    - the settings menu (below)
- Editing Account Details
  - The Client taps Edit, and can change:
    - First name
    - State and ZIP code:
      - Country can’t be changed, because Your Oracle is for U.S. users only.
      - The state decides the age of majority used for age rules. It only changes if the Client changes it.
  - The Client taps Save to save their changes.
- Changing State: Age Rules
  - When the Client changes their state, the platform shall check their date of birth against the new state’s age of majority:
    - 18 in most states and Washington, D.C.
    - 19 in Alabama and Nebraska
    - 21 in Mississippi
  - Still at or above the age of majority: the change is saved, and nothing else changes.
  - Now below the age of majority (for example, a 20-year-old moving to Mississippi):
    - Before saving, the Client sees a message explaining that teen rules will apply in their new state until they reach its age of majority. They choose Confirm or Cancel.
    - If they confirm:
      - the change is saved
      - the teen rules apply straight away: education only, with no product names or recommendations, no dosing, and no interpretation of their own lab results (see story 3.1)
      - their history is kept
    - If they cancel: nothing changes.
  - When they reach the new state’s age of majority: the adult rules apply again automatically.
  - Every state change, and any change of age rules, is recorded in the backend logs.
- Changing the Email Address
  - The email address is shown but can’t be edited directly, because it’s used to sign in.
  - The Client taps Request email change below it, enters the new email address, and taps Send request.
  - The request is sent to the support team as an Email Change Request (see Super Admin story 5.1).
  - Until it’s done, the profile shows “Email change requested”, and the Client keeps signing in with their current email address.
  - The support team changes the email address in the admin panel to the one the Client requested.
  - Once the email address is changed:
    - the Client receives a confirmation at both their old and new email addresses
    - they’re signed out on all devices, and their trusted devices are cleared
    - the next time they sign in, with the new email address, they complete two-step verification again, as on a new device (see story 1.2)
- Settings Menu
  - The settings menu shall include links to:
    - My Health (see story 6.1)
    - Manage Family (see story 8.2)
    - Subscription & Billing (see story 11.3)
    - Notification Preferences (see story 12.1)
    - Change Password (see story 11.2)
    - Privacy & Data (see story 11.4)
    - Contact support team, and Consult with support team (see story 10.1)
    - About Your Oracle: “Oracle’s content comes from the published works of Deborah Maragopoulos, MN FNP. Oracle is an AI tool, not a person or a licensed clinician, and using it does not connect you with Deborah or any provider.”
    - Terms of Service and Privacy Policy
    - Sign Out (see story 1.4)
- Teens With Their Own Account
  - Their settings menu doesn’t include Manage Family, Subscription & Billing, or Consult with support team.
- Advocate-Only Clients
  - A Client who has deleted their own data (see story 11.4) sees their account details and settings, but no health profile of their own.
Acceptance Criteria:
- Opening: Given the Client is signed in, when they open Profile & Account from the main navigation or the profile panel, then the screen opens.
- Screen: Given the screen opens, when it loads, then it shows the Client’s first name, email address and address, with Edit and the settings menu.
- Editing: Given the Client taps Edit, when they change their first name, state or ZIP code, and tap Save, then the changes are saved.
- Country locked: Given the Client is editing their address, when they look at the country, then it can’t be changed.
- State change, still adult: Given the Client changes their state, when they’re still at or above the new state’s age of majority, then the change is saved, and nothing else changes.
- State change, now under age: Given the Client changes their state, when they’d be below the new state’s age of majority, then they see the teen rules message, and must confirm before the change is saved.
- Teen rules applied: Given the Client confirms, when the change is saved, then the teen rules apply straight away, and their history is kept.
- Adult rules return: Given a Client on teen rules reaches the new state’s age of majority, when that date arrives, then the adult rules apply again automatically.
- No phone: Given the profile, when it’s shown, then there’s no phone number field.
- Email locked: Given the email address, when the Client tries to edit it, then it can’t be edited directly.
- Email change request: Given the Client sends an email change request, when it’s sent, then the profile shows “Email change requested”, and they keep signing in with their current email until the support team makes the change.
- Email changed: Given the support team changes the email, when it’s done, then the Client is notified at both addresses, signed out on all devices, trusted devices are cleared, and two-step verification is needed at the next sign-in.
- Settings menu: Given the settings menu, when the Client taps an item, then the right screen opens.
- Teens: Given a teen with their own account, when the settings menu is shown, then Manage Family, Subscription & Billing and Consult with support team aren’t included.
Alternate Scenario:
- Client changes state and is still an adult there
  - The change is saved.
- Client changes state and falls below its age of majority
  - They confirm, and the teen rules apply until they reach that age.
- Client cancels the state change
  - Nothing changes.
- Email change to an address already in use
  - An error is shown, and the request isn’t sent.
- Email change to the current address
  - An error is shown.
- Second email change request while one is pending
  - The Client is told one is already pending.
- Email changed while the Client is signed in
  - They’re signed out, and asked to sign in again with the new address.
- Client leaves the edit screen without saving
  - They’re asked to confirm first.
- Advocate-only mode
  - The Client sees their account details and settings, with no health profile of their own.
- Saving or sending the request fails
  - The Client can try again.
Non-functional Requirements:
- The screen should load within 2 seconds, and changes should save within 3 seconds.
- The age-of-majority table can be updated without an app release.
- Age rules change straight away after a confirmed state change, and again automatically on the date the Client reaches the age of majority.
- Email change requests reach the support team’s list within 1 minute.
- When the email address changes, all sessions and trusted devices for the account are cleared straight away.
- Every change to account details, including state changes and email changes made by the support team, is recorded in the backend logs with the date, time and who made it (BAA Section 13).
- Account details are encrypted, and stored in the HIPAA-compliant cloud (Azure).
Validation Rules/Errors:
- First name empty: “Please enter your first name.”
- State empty: “Please choose your state.”
- ZIP code empty or invalid: “Please enter a valid ZIP code.”
- State change moves the Client below the age of majority: “In [State], the age of majority is [age]. If you change your state, teen rules will apply until you turn [age]. This means I’ll share health education only, without product recommendations. Do you want to continue?”
- New email address not valid: “Please enter a valid email address.”
- New email address same as current: “That’s already your email address.”
- New email address already in use: “An account with this email address already exists.”
- Email change already pending: “You’ve already asked to change your email address. The support team will update it soon.”
- Email change requested: “Your request has been sent. The support team will update your email address and let you know.”
- Email address changed: “Your email address has been changed to [new email]. Please sign in again with your new email address. We’ll send you a verification code to confirm it’s you.”
- Leaving without saving: “You have unsaved changes. Leave without saving?”
- Changes saved: “Your details have been updated.”
- Save or request failed: “We couldn’t do that just now. Please try again.”
### 11.2 - Reset Password
### Requirement Statement:
As a Client, I want to reset my password while I’m signed in.
### Specifications:
Story Details:
- Opening Reset Password
  - The Client opens it from Change Password in the settings menu (see story 11.1).
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
    - Check the new password follows the password rules (the same as story 1.1):
      - Minimum 8 characters
      - At least 1 uppercase letter
      - At least 1 lowercase letter
      - At least 1 number
      - At least 1 special character
    - Check the new password is different from the current password
    - Check the new password and the confirmation match
- After the Password Is Changed
  - The Client stays signed in on the device they’re using.
  - They’re signed out on all other devices, and those trusted devices are cleared. Signing in on them again needs a verification code (see story 1.2).
  - They receive an email confirming the password was changed.
- Forgotten Current Password
  - The Client taps Forgot your password?, is signed out, and follows Forget Password (see story 1.3).
- Teens
  - Teens with their own account change their password the same way.
Acceptance Criteria:
- Opening: Given the Client is signed in, when they tap Change Password in the settings menu, then the Reset Password screen opens.
- Mandatory fields: Given any field is empty, when the Client taps Save, then a required-field error appears against that field.
- Current password: Given the current password is wrong, when the Client taps Save, then the password isn’t changed, and an error is shown.
- Password rules: Given the new password doesn’t follow the rules, or is the same as the current one, when the Client taps Save, then an error is shown.
- Matching: Given the new password and confirmation don’t match, when the Client taps Save, then an error is shown.
- Show password: Given the Client taps the eye icon, when it’s toggled, then that password switches between masked and visible.
- Password changed: Given all fields are valid, when the Client taps Save, then the password is changed, they stay signed in on this device, are signed out on all other devices, and receive a confirmation email.
- Other devices: Given the password was changed, when the Client signs in on another device, then a verification code is required.
- Forgotten password: Given the Client taps Forgot your password?, when it opens, then they’re signed out and taken to Forget Password.
Alternate Scenario:
- Wrong current password
  - An error is shown, and the password isn’t changed.
- New password doesn’t meet the rules
  - An error is shown.
- Passwords don’t match
  - An error is shown.
- New password same as current
  - The Client is asked to choose a different one.
- Client has forgotten their current password
  - They use Forget Password instead.
- Saving fails
  - The Client can try again.
Non-functional Requirements:
- Passwords are stored hashed, never in plain text.
- Signing out other devices, and clearing their trusted status, happens straight away once the password is changed.
- Confirmation emails contain no health information.
- Password changes are recorded in the backend logs, with the date and time (BAA Section 13).
Validation Rules/Errors:
- Field empty: “This field is required.”
- Current password wrong: “Your current password isn’t right. Please try again.”
- New password doesn’t meet the rules: “Your password needs at least 8 characters, including an uppercase letter, a lowercase letter, a number and a special character.”
- Passwords don’t match: “The passwords don’t match. Please try again.”
- New password same as current: “Please choose a password you haven’t used before.”
- Password changed: “Your password has been changed.”
- Save failed: “We couldn’t change your password just now. Please try again.”
### 11.3 - Manage Billing & Subscription
### Requirement Statement:
As a Client, I want to view and manage my subscription and billing, so that I stay in control of what I pay for.
### Specifications:
Story Details:
- Opening Subscription & Billing
  - The Client opens it from the settings menu (see story 11.1).
  - Teens with their own account don’t see it, because their access comes through the parent’s Family plan (see story 1.5).
- Current Plan
  - The screen shall show:
    - their plan (Free trial, Individual or Family), and its status (Trial, Active, Payment issue or Cancelled)
    - the next billing date and amount
    - Family plan only: how many family members are in use, for example “3 of 3 active family members” (including invited teens), and any add-on members with their monthly price
    - the renewal disclaimer: “Your subscription renews automatically each month until you cancel.”
- Upgrading and Downgrading
  - Upgrade:
    - from the free trial to the Individual or Family plan (see story 9.1)
    - from the Individual plan to the Family plan, which unlocks family members
    - adding add-on family members on the Family plan (see story 8.1)
  - Downgrade:
    - removing add-on members, by turning off or removing a family member (see story 8.2). The add-on charge stops from the next billing date.
    - from the Family plan to the Individual plan, from the next billing date. Before confirming, the Client sees what will happen to their family members (see below).
- What Happens to Family Members When the Family Plan Ends
  - The Family plan ends when the Client cancels it, downgrades to Individual, or a payment isn’t fixed by the end of the grace period.
  - Family members managed by the Client:
    - their profiles are turned off, and their information is kept
    - they’re hidden from the profile panel, and can’t be used for conversations
    - their reminders, follow-ups and Wellness Plan check-ins are paused
    - if one was the active profile, the app switches back to the Client’s own profile
  - Invited teens:
    - their access is paused, and their information is kept
    - they see: “Your access is paused. Please ask your parent or guardian. You can still download your data or ask for it to be deleted here.” And show the sign in option there.
    - when they sign in, they can only see Privacy & Data in the app, where they can export their data or request deletion (see story 1.5)
    - the parent is told (see story 12.1)
  - When the Family plan is active again:
    - managed family members are turned back on, with their information intact
    - invited teens’ access is restored, with their information intact
    - if there are more family members than the plan’s places, the Client chooses which to turn back on, or adds add-ons (see story 8.2)
- Payment Method
  - The Client can view their payment method, for example “Visa ending 4417” or Apple Pay, and tap Change to update it.
  - If they subscribed through Apple or Google, they’re directed to their App Store or Google Play subscription settings.
- Billing History
  - Where supported, the Client sees their past payments, each with the date, amount and status, and can download each receipt.
  - For Apple and Google subscriptions, billing history is kept in the App Store or Google Play.
- Cancelling
  - The Client taps Cancel subscription, sees what they’ll lose, and confirms.
  - Their access continues until the end of the current billing period (Session 9). After that, they return to the locked state, as when a trial ends (see story 9.1).
  - Their information, and their family members’ information, is kept. Cancelling isn’t the same as deleting the account (see story 11.4).
  - Add-on charges end with the subscription.
- Payment Failure
  - If a renewal payment fails, the status shows “Payment issue”, and the Client is asked to update their payment method.
  - Their access continues during a grace period.
Acceptance Criteria:
- Opening: Given the Client is signed in, when they open Subscription & Billing from the settings menu, then the screen opens. Teens with their own account don’t see it.
- Current plan: Given the screen opens, when it loads, then it shows the plan, status, next billing date and amount, and the renewal disclaimer. Family plan Clients also see family members in use and add-on members.
- Upgrading: Given the Client upgrades from the trial, from Individual to Family, or adds an add-on, when the payment succeeds, then the change applies straight away.
- Downgrading: Given the Client removes an add-on or downgrades from Family to Individual, when they confirm, then the change applies from the next billing date.
- Managed members when the plan ends: Given the Family plan ends, when it ends, then managed family members’ profiles are turned off, their information is kept, and their reminders are paused.
- Invited teens when the plan ends: Given the Family plan ends, when it ends, then invited teens’ access is paused, their information is kept, and the parent is told.
- Plan active again: Given the Family plan is active again, when it starts, then managed family members are turned back on, and invited teens’ access is restored, with all information intact.
- Payment method: Given the Client taps Change, when they update their payment method, then it’s saved. Apple and Google subscriptions link to the store settings.
- Billing history: Given past payments exist, when the Client opens billing history, then each payment shows its date, amount and status, with a downloadable receipt, where supported.
- Cancelling: Given the Client cancels, when they confirm, then access continues until the end of the billing period, all information is kept, and add-ons end with the subscription.
- Payment failure: Given a renewal fails, when the status updates, then it shows “Payment issue”, the Client is asked to update their payment method, and access continues during the grace period.
Alternate Scenario:
- Client cancels, then subscribes again before the billing period ends
  - Their subscription continues, without a break.
- Client downgrades from Family to Individual
  - From the next billing date, managed family members are turned off, and invited teens’ access is paused. All their information is kept.
- Client upgrades back to the Family plan
  - Family members are turned back on, and invited teens’ access is restored.
- More family members than places when the plan restarts
  - The Client chooses which to turn back on, or adds add-ons.
- Card expires, and the renewal fails
  - The status shows “Payment issue” until the Client updates their payment method.
- Payment isn’t fixed by the end of the grace period
  - Access is locked, family members are turned off, and invited teens’ access is paused.
- Client subscribed through Apple, and tries to cancel in the app
  - They’re directed to the App Store.
- Client removes an add-on member part-way through the month
  - The charge stops from the next billing date.
- Client is still on the trial
  - There’s no billing history yet.
- Updating the payment method fails
  - The Client can try again.
Non-functional Requirements:
- Billing changes are applied through Stripe, Apple or Google within a few seconds.
- Card details are never stored by the app.
- Family members’ profiles and invited teens’ access follow the Family plan’s status straight away.
- Turning family members off because the plan has ended never deletes their information.
- Receipts are available to download for as long as the Client has an account.
- Subscription and billing events are recorded in the backend logs.
Validation Rules/Errors:
- Cancel confirmation: “Cancel your subscription? You’ll keep access until [date]. After that, you won’t be able to talk with me or see your Wellness Plan until you subscribe again.”
- Subscription cancelled: “Your subscription has been cancelled. You have access until [date].”
- Downgrade to Individual: “Moving to the Individual plan will turn off your family members’ profiles from [date]. Their information will be kept, and you can turn them back on by returning to the Family plan. Do you want to continue?”
- Renewal failed: “We couldn’t renew your subscription. Please update your payment method to keep your access.”
- Payment method updated: “Your payment method has been updated.”
- Apple or Google subscription: “You subscribed through [App Store / Google Play]. Please manage your subscription there.”
- Choosing family members to turn back on: “Your plan includes 3 family members. Choose who to turn back on, or add another member.”
- Action failed: “We couldn’t do that just now. Please try again.”
### 11.4 - Revoke Consent / Delete Account - (Export My Data)
### Requirement Statement:
As a Client, I want to export my data, revoke my consent, or request deletion of my account, so that I stay in control of my information.
### Specifications:
Story Details:
- Privacy & Data Screen
  - The Client opens Privacy & Data from the settings menu (see story 11.1).
  - The screen shall include:
    - the Terms of Service, Privacy Policy and Health Consent the Client accepted, with the version and date of each
    - Export My Data
    - Revoke Consent
    - Delete Account
- Export My Data
  - The Client taps Export My Data, and the file is created and downloaded straight away, inside the app.
  - A short loading indicator shows while the file is created, usually a few seconds.
  - Mobile App: the file is saved through the phone’s share or save options. Web App: it downloads in the browser.
  - What’s included: their health profile, conversations, guidance summaries, provider-ready notes, visit logs and Wellness Plan.
  - No support team is involved, and nothing is sent by email.
- Revoke Consent
  - The Client taps Revoke Consent, sees what will happen, and confirms.
  - Once confirmed:
    - their consent is withdrawn
    - they’re signed out straight away, on all devices
    - the Oracle stops using their information, and notifications stop
    - their data isn’t deleted: everything saved before revoking is kept
    - this applies to the whole account, including the profiles of family members they manage
    - invited teens lose access too, because the parent gave consent for them. When they sign in, they can only see Privacy & Data in the app, where they can export their data or request deletion. Their data is kept.
  - When they sign in again:
    - they’re shown the Terms of Service, Privacy Policy and Health Consent
    - they can’t see their data or do anything else until they accept
    - once they accept, they continue as before, with all their data (see story 1.2)
    - invited teens’ access is restored, with their data intact
  - Revoking consent and giving it again are both recorded in the audit logs.
- Delete Account
  - The Client taps Delete Account.
  - Before confirming, they’re asked: “Would you like to export your data first?”
  - If they have family members or invited teens, they see the disclaimer, with the names of everyone affected, before confirming.
  - Disclaimer: “Deleting your account will permanently delete your information, and the information of everyone on your account, including your family members and any teens on your plan. You’ll all have 10 days to keep using Your Oracle and download your information before the deletion begins. This can’t be undone.”
  - The Client confirms.
  - First release: deleting the account deletes everyone’s data. The option to stay as advocate only will be added in a later release.
- What Happens After Confirming
  - Acknowledgement: the Client receives an email straight away, confirming the request and the date the grace period ends.
  - 10-day grace period:
    - the Client keeps full use of the app, and nothing is locked
    - a banner on every screen shows: “Your account is scheduled for deletion on [date].”
    - they can download their data at any time from Privacy & Data
    - invited teens on their account are notified at the start, keep full use of their own account, and can download their data
  - After the grace period:
    - the account, and invited teens’ accounts, are locked
    - the request goes to the Super Admin for review (see Super Admin story 5.2)
  - Deletion: the Super Admin checks for any legal hold, and the deletion is completed within 45 calendar days of the request (CCPA/CPRA).
  - What’s deleted: the Client’s account, all managed family members’ data, and invited teens’ accounts and data.
  - The Client receives an email once the deletion is complete.
- Teens With Their Own Account
  - Their Privacy & Data screen shows Export My Data and Delete My Information.
  - They can’t revoke consent, because the parent gave it.
  - Export My Data: works the same as for adults, in their own app. It includes only their own data.
  - Delete My Information:
    - the teen sees what will happen, and confirms
    - they receive an acknowledgement straight away
    - 10-day grace period: they keep full use of their account, with the same banner, and can download their data
    - after the grace period, their account is locked, and the request goes to the Super Admin
    - the deletion is completed within 45 calendar days of the request
    - once it’s done, the teen’s account is closed, they’re removed from the parent’s family, and the place is freed
  - Teens who have lost access (removed, turned off, Family plan ended, or the parent revoked consent or hasn’t accepted a policy update): when they sign in, they only see Privacy & Data in the app, with Export My Data and Delete My Information. Everything else stays locked until their access is restored.
  - The parent can’t see the teen’s requests, or the teen’s information.
- Admin Side
  - Deletion requests appear in the support team’s list once the grace period ends, and the team is notified. Exports don’t involve the team.
- Record Keeping
  - Every export, revocation, re-consent, deletion request, acknowledgement, grace period and deletion is recorded in the audit logs, and retained for six years.
Acceptance Criteria:
- Privacy & Data screen: Given the Client opens Privacy & Data, when it loads, then it shows the accepted Terms of Service, Privacy Policy and Health Consent with their versions and dates, and the Export My Data, Revoke Consent and Delete Account options.
- Export: Given the Client taps Export My Data, when the file is created, then it downloads straight away, inside the app.
- Revoke consent: Given the Client confirms Revoke Consent, when it’s revoked, then they’re signed out on all devices, the Oracle stops using their information, notifications stop, and no data is deleted.
- Invited teens on revoke: Given the Client revokes consent, when it’s revoked, then their invited teens lose access, and their data is kept.
- Re-consent: Given consent was revoked, when the Client signs in again and accepts, then they continue as before, and invited teens’ access is restored.
- Teen who has lost access: Given a teen has lost access, when they sign in, then only Privacy & Data is visible to them, and they can export their data or request deletion.
- Before deleting: Given the Client taps Delete Account, when the confirmation opens, then they’re offered the chance to export their data first.
- Disclaimer: Given the Client has family members or invited teens, when they tap Delete Account, then they see the disclaimer, with everyone affected listed, before confirming.
- Acknowledgement: Given the Client confirms Delete Account, when the request is sent, then they receive an acknowledgement email straight away, with the date the grace period ends.
- Grace period: Given the grace period has started, when the Client or an invited teen uses the app, then everything works as normal, the deletion banner is shown, and they can download their data.
- After the grace period: Given 10 days have passed, when the grace period ends, then the account and invited teens’ accounts are locked, and the request goes to the Super Admin.
- Deletion completed: Given the Super Admin completes the deletion, when it’s done, then the Client’s data, all managed family members’ data, and invited teens’ accounts and data are deleted, within 45 calendar days of the request, unless a legal hold applies, and the Client is emailed.
- Teens’ Privacy & Data: Given a teen with their own account opens Privacy & Data, when it loads, then they see Export My Data and Delete My Information, and can’t revoke consent.
- Teen export: Given a teen requests an export, when it’s ready, then it includes only their own data, and downloads in their own app.
- Parent’s export: Given a parent requests an export, when it’s prepared, then it never includes their invited teens’ data.
- Teen deletion: Given a teen requests deletion, when the grace period ends and the deletion is completed, then their account is closed, they’re removed from the parent’s family, and the place is freed.
- Records: Given any action, when it happens, then it’s recorded in the audit logs.
Alternate Scenario:
- Client revokes consent, then signs in and accepts
  - They continue as before, with all their data, and invited teens’ access is restored.
- Client revokes consent, then signs in but doesn’t accept
  - They stay on the consent screen, and invited teens stay paused.
- Deletion with no family members
  - The Client keeps full use for 10 days, then the account is locked and deleted.
- Client deletes their account, with family members and invited teens
  - Everyone keeps full use for 10 days, then all the data is deleted.
- Client or teen downloads their data during the grace period
  - They use Export My Data in Privacy & Data.
- Teen exports their data
  - It downloads straight away, inside their app.
- Teen requests deletion
  - They keep full use for 10 days, then their account is locked and deleted.
- Account already scheduled for deletion
  - The Client is told.
- Legal hold
  - The deletion can’t be completed yet, and the Client is told.
- Request can’t be processed
  - The Client can try again later.
- Export fails
  - The Client is told in the app, and can try again.
Non-functional Requirements:
- The export file should be created and start downloading within 10 seconds.
- Exports can only be downloaded by the signed-in account holder, and aren’t stored on the server after downloading.
- Deletion requests are acknowledged straight away, have a 10-day grace period with full use of the app, and are completed within 45 calendar days of the request, including from backups, unless a legal hold applies (CCPA/CPRA).
- The grace period ends automatically after 10 days, and the account is locked at that point.
- When consent is revoked, the Client’s data, and their invited teens’ data, is kept but not used by the Oracle, analytics or notifications until consent is given again.
- An invited teen’s data can never be seen or exported from the parent’s account.
- All actions are recorded in the audit logs, and retained for six years.
Validation Rules/Errors:
- While creating the file: “Getting your data ready…”
- Downloaded: “Your data has been downloaded.”
- Export failed: “We couldn’t download your data just now. Please try again.”
- Before deleting: “Would you like to export your data before deleting your account?”
- Revoke confirmation: “If you revoke your consent, you’ll be signed out and won’t be able to use Your Oracle. Your information will be kept. Any teens with their own account on your plan will also lose access until you give your consent again.”
- Signing in after revoking: “Please accept our Terms of Service, Privacy Policy and Health Consent to continue.”
- Teen access paused after revoke (shown to the teen): “Your access is paused. Please ask your parent or guardian. You can still download your data or ask for it to be deleted here.”
- Deletion complete (sent to an invited teen): “Your account has been deleted because your parent or guardian deleted their account. To keep using Your Oracle, a parent or guardian will need to sign up again and add you.”
- Delete confirmation: “Delete your account? You’ll have 10 days to keep using Your Oracle and download your information. After that, it will be permanently deleted.”
- Delete with family members or teens: “Deleting your account will permanently delete your information, and the information of everyone on your account, including your family members and any teens on your plan. You’ll all have 10 days to keep using Your Oracle and download your information before the deletion begins. This can’t be undone.”
- Acknowledgement (email): “We’ve received your request to delete your account. You can keep using Your Oracle and download your information until [date]. After that, your account will be deleted.”
- Grace period banner: “Your account is scheduled for deletion on [date].”
- Shown to invited teens: “Your parent or guardian has asked to delete their account. You can keep using Your Oracle and download your information until [date]. After that, your account and information will be deleted.”
- Teen deletion confirmation: “Delete all your information? You’ll have 10 days to keep using Your Oracle and download your information. After that, your account will be closed.”
- Account locked after the grace period: “Your account is being deleted, so it’s no longer available.”
- Already scheduled for deletion: “Your account is already scheduled for deletion.”
- Request couldn’t be processed: “We can’t process your request at the moment. Please try again later.”
## 12. Epic: Notifications
### 12.1 - Notifications & Reminders
### Requirement Statement:
As a Client, I want to receive timely reminders and updates, and choose which ones I get, so that I stay on track with my health without being overwhelmed.
### Specifications:
Story Details:
- How Notifications Are Sent
  - In-app: in the notification centre (the bell icon on the Home Dashboard, see story 4.1)
  - Push notifications: on the Mobile App, if the Client allows them
  - Email: for account, billing and request updates
  - There are no SMS notifications, because no phone number is collected.
- Notification Centre
  - The bell icon shows the number of unread notifications.
  - The list shows the newest first. Each notification shows its message, the profile it’s about (for example, “Azka”), and when it was sent.
  - Tapping a notification opens the right screen, and switches to the right profile if needed. For example, “How did your Cardiology appointment go?” opens Log your visit for that note.
  - The Client can mark all notifications as read.
- Types of Notifications
  - Guidance follow-ups:
    - a follow-up two weeks after a guidance summary: “It’s been two weeks since we talked about [topic]. How are you feeling?” (see story 3.3)
  - Appointments:
    - a reminder before an appointment added to provider-ready notes (see story 3.4)
    - a follow-up after the appointment: “How did your [specialty] appointment go?” (see story 5.2)
    - a booking follow-up 7 days after notes were created without an appointment date: “Have you booked your appointment yet?”
    - a reminder when lab results are expected (see story 5.2)
  - Wellness Plan:
    - “Your Wellness Plan has been updated.” (see story 7.1)
    - check-ins when a Wellness Plan item’s time frame ends, or an item is due: “Check in with the Oracle: about 2 minutes.” (see story 7.1)
  - Health profile:
    - review reminders at 3, 6 and 12 months after the last update, and after a logged visit (see story 6.1)
    - a reminder to complete the health profile
  - Inactivity: a check-in after 30 days without using the app: “It’s been a while. How have you been?”
  - Subscription and billing:
    - a reminder before the 14-day free trial ends, and when it has ended (see story 9.1)
    - a failed renewal (see story 11.3)
    - family members turned off, or back on, when the Family plan ends or restarts (see story 11.3)
  - Requests and account:
    - deletion acknowledged, grace period reminder, deletion complete, and email address changed (see stories 11.1 and 11.4)
  - Teens with their own account, sent to the parent:
    - access paused or restored: “Your access is paused. Please ask your parent or guardian. You can still download your data or ask for it to be deleted in Privacy & Data.”
    - emergency or crisis: the parent is told their teen may need help, without any conversation content (see story 3.2)
    - teen creates their own account: “[Name] now has their own Your Oracle account. Their place in your family plan is free again.” (see story 1.6)
  - Teens with their own account, sent to the teen:
    - the invite email, “You’ve been invited to join Your Oracle” (see story 1.5)
    - the two-week reminder before the age of majority (see story 1.6)
    - access paused: “Your access is paused. Please ask your parent or guardian. You can still download your data or ask for it to be deleted in Privacy & Data.” (see stories 1.5, 8.2 and 11.4)
    - their own guidance follow-ups, appointment, Wellness Plan and health profile reminders, the same as an adult
    - deletion notice: “Your account and information will be deleted on [date]. You can keep using Your Oracle and download your information until then.” Sent when the parent deletes their account, removes the teen, or the teen asks for deletion (see stories 8.2 and 11.4).
    - grace period reminder: “Your account will be deleted tomorrow. Download your information now if you’d like a copy.”
    - deletion complete (sent to an invited teen): “Your account has been deleted because your parent or guardian deleted their account. To keep using Your Oracle, a parent or guardian will need to sign up again and add you.” Note: this only applies when the parent deletes their account. If the teen asks to delete their own information, they get the normal “deletion complete” message.
- Notification Preferences
  - The Client opens Notification Preferences from the settings menu (see story 11.1), and can:
    - turn each type on or off: guidance follow-ups, appointments, Wellness Plan, health profile and inactivity
    - choose push, email or both for each type
- Notifications That Can’t Be Turned Off
  - Subscription and billing, requests and account, deletion notices and all teen safety and access notifications
  - They’re shown in Notification Preferences, but can’t be switched off.
- Family Members and Teens
  - Managed family members: reminders are sent to the Client for each family member’s profile, and show their name. For example: “How did Azka’s appointment go?”
  - Teens with their own account: their reminders go to the teen, not the parent. The parent only gets the teen notifications listed above, which never include the teen’s health information.
- Revoked Consent
  - Once a Client revokes consent, all their notifications stop until they give consent again (see story 11.4).
Acceptance Criteria:
- Notification centre: Given the Client opens the notification centre, when it loads, then the bell shows the unread count, and notifications are listed newest first, with the message, profile and time.
- Opening a notification: Given the Client taps a notification, when it opens, then the right screen opens for the right profile.
- Mark as read: Given unread notifications, when the Client taps mark all as read, then the count clears.
- Types: Given each notification type, when its time comes, then it’s sent for the right profile.
- No SMS: Given any notification, when it’s sent, then it’s in-app, push or email only.
- Preferences: Given Notification Preferences, when the Client changes a type, then they can turn it on or off, and choose push, email or both.
- Can’t turn off: Given subscription and billing, requests and account, or teen safety and access notifications, when the Client tries to turn them off, then they can’t.
- Managed family members: Given a reminder for a managed family member, when it’s sent, then it shows the family member’s name.
- Teen notifications to the parent: Given a teen with their own account, when their access changes, they have an emergency or crisis, or they create their own account, then the parent is notified, with no health information.
- Teens’ own reminders: Given a teen with their own account, when their reminders are due, then they go to the teen, not the parent.
- Revoked consent: Given consent is revoked, when notifications are due, then none are sent until consent is given again.
Alternate Scenario:
- Push turned off in phone settings
  - Only in-app and email notifications are sent.
- Client turns off Wellness Plan check-ins
  - They stop receiving them.
- Client taps a notification about a family member
  - The app switches to that profile.
- Notification for something that no longer exists (for example, a deleted visit log)
  - The Client sees a message.
- Appointment date changes
  - Its reminders are rescheduled.
- Family plan ends
  - The parent is told their family members are turned off, and invited teens’ access is paused.
- Teen in crisis
  - The parent is told their teen may need support.
- Client revokes consent
  - All notifications stop.
Non-functional Requirements:
- Push notifications and emails never include health details. They show a general message, for example “You have a new update from the Oracle”, and the details are shown only once the Client opens the app.
- Notifications to a parent about a teen never include the teen’s health information or conversation content.
- Notifications are sent within 1 minute of their scheduled time. Teen safety notifications are sent straight away.
- The timing of reminders (for example, the 2-week follow-up and the 30-day inactivity check-in) is configurable by the admin team, without an app release.
- Preferences are saved straight away, and apply across all the Client’s devices.
- Notifications are never sent for turned-off or deleted family member profiles.
Validation Rules/Errors:
- No notifications yet: “You’re all caught up.”
- Notification for something that no longer exists: “This item is no longer available.”
- Type that can’t be turned off: “These notifications keep you safe and your account up to date, so they can’t be turned off.”
- Preferences saved: “Your notification preferences have been updated.”
- Save failed: “We couldn’t update your preferences just now. Please try again.”
### 12.2 - Policy Updates
### Requirement Statement:
As a Client, I want to be told when the Terms of Service, Privacy Policy or Health Consent change, and accept the new version, so that I always know how my information is used.
### Specifications:
Story Details:
- When a Policy Changes
  - The admin team publishes a new version of the Terms of Service, Privacy Policy or Health Consent in the admin panel, which requires every Client to accept it again (see Super Admin stories 9.1 and 9.2).
- Telling the Client
  - By email: “We’ve updated our [Policy name]. You’ll be asked to review and accept it the next time you open Your Oracle.”
  - Signed-in Clients: their session ends, so they see the updated policy the next time they open the app.
- Policy Update Screen
  - The first screen the Client sees, on the Mobile App or Web App, is the updated policy. It shall include:
    - the name of the updated policy and its new version date
    - the full updated policy, to read
    - a checkbox: “I have read and accept the updated [Policy name]” (Mandatory)
    - an Accept and continue button
- Accepting the Update
  - Step 1: the Client reads and accepts the updated policy.
  - Step 2: the Sign In screen appears (see story 1.2).
  - Step 3: the Client signs in as usual.
  - Step 4: once signed in, their acceptance is recorded against their account, with the policy version, date and time.
- If the Client Doesn’t Accept
  - They stay on the policy screen, and can’t continue to Sign In.
  - The updated policy is shown again the next time they open the app.
- More Than One Updated Policy
  - If several policies are updated at the same time, the Client accepts each one on the same screen before continuing to Sign In.
- Health Consent and Family Members
  - When the Health Consent is updated, the Client accepts it before signing in.
  - Once signed in, they confirm it as medical advocate for each family member, including invited teens, before continuing to the app.
- Teens With Their Own Account
  - Teens aren’t shown the policy update screen, because the parent gave consent for them (see story 1.5).
  - Until the parent accepts the updated policies, the teen’s access is paused. When they sign in, they see: “our access is paused. Please ask your parent or guardian. You can still download your data or ask for it to be deleted here.”
  - Once the parent accepts, including confirming the Health Consent for the teen, the teen’s access is restored, with their information intact.
- Accepted Versions
  - The Client can see which version of each policy they accepted, and when, in Privacy & Data (see story 11.4).
- New Clients
  - Clients signing up after an update accept the latest Terms of Service and Privacy Policy during sign-up (see story 1.1), and the latest Health Consent at their first conversation (see story 3.1). They aren’t shown this screen.
Acceptance Criteria:
- Telling Clients: Given the admin team publishes a new policy version, when it’s published, then every Client is emailed, and signed-in sessions end.
- First screen: Given a policy has been updated, when the Client next opens the app, then the updated policy is the first screen shown, before Sign In.
- Screen content: Given the policy screen is shown, when it loads, then it shows the policy name, version date, the full policy, a mandatory checkbox, and Accept and continue.
- Accepting: Given the Client ticks the checkbox, when they tap Accept and continue, then they continue to Sign In.
- Recorded: Given the Client signs in after accepting, when they’re signed in, then their acceptance is recorded with the version, date and time.
- Not accepted: Given the Client doesn’t accept, when they try to continue, then they can’t, and the policy is shown again on their next visit.
- Several policies: Given several policies are updated, when the screen is shown, then all of them are accepted on the same screen before Sign In.
- Family members: Given the Health Consent is updated, when the Client signs in, then they confirm it for each family member, including invited teens, before continuing.
- Teen paused: Given a policy is updated, when the parent hasn’t accepted it yet, then the teen’s access is paused, and they see the access-paused message.
- Teen access paused (shown to the teen): “Your access is paused. Please ask your parent or guardian. You can still download your data or ask for it to be deleted here.”
- Teen restored: Given the parent accepts the updated policies and confirms the Health Consent for the teen, when it’s recorded, then the teen’s access is restored.
- Teens don’t accept: Given a teen with their own account, when a policy is updated, then they aren’t shown the policy screen.
- Accepted versions: Given the Client opens Privacy & Data, when it loads, then their accepted versions and dates are shown.
- New Clients: Given a Client signs up after an update, when they sign up, then they accept the latest versions during sign-up and their first conversation instead.
Alternate Scenario:
- Client was signed in when the policy was updated
  - Their session ends.
- Client opens the app, doesn’t accept, and closes it
  - The policy is shown again next time.
- Client accepts but doesn’t complete sign-in
  - The policy is shown again on their next visit.
- Two policies updated at the same time
  - Both are accepted on the same screen.
- Client manages family members
  - They confirm the updated Health Consent for each of them after signing in.
- Client has invited teens
  - The teens’ access is paused until the Client accepts, and confirms the Health Consent for each teen.
- Teen signs in before the parent has accepted
  - They see the access-paused message.
- Advocate-only mode
  - The Client confirms the updated Health Consent for their family members.
- Consent was revoked (see story 11.4)
  - The Client is shown the latest versions when they sign in again.
- Saving the acceptance fails
  - The Client can try again.
Non-functional Requirements:
- The updated policy screen must appear before the Sign In screen, and before any health information is shown.
- An acceptance only counts once the Client has signed in and it’s recorded against their account.
- Invited teens’ access pauses as soon as a policy update is published, and is restored straight away once the parent’s acceptance is recorded.
- Every acceptance is recorded in the audit logs, with the Client, policy, version, date and time, and retained for six years.
- Policy text is managed by the admin team in the admin panel, so it can be updated without an app release.
- Policy update emails contain no health information.
Validation Rules/Errors:
- Checkbox not ticked: “Please confirm you’ve read and accept the updated [Policy name] to continue.”
- Health Consent for a family member not confirmed: “Please confirm the updated Health Consent for [Name] to continue.”
- Teen access paused (shown to the teen): “Your access is paused. Please ask your parent or guardian.”
- Accepted: “Thanks, you’re all set.”
- Saving failed: “We couldn’t save your acceptance just now. Please try again.”
