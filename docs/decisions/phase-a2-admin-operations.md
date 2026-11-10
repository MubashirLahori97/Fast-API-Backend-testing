# Phase A part 2, the admin panel's operations: decisions

Built on 5 and 6 Nov 2026 against the Super Admin stories 2.1, 3.1, 3.2, 4.1, 5.1, 5.2, 6.1 to 6.3, 8.1, 8.2, 9.1 and 9.2, and the Admin stories for the same areas. Code only: no tests and no migration yet (see the end). Admin sign-in, Admin Management, the admin's profile, audit logs and admin notifications are part 1 (another build).

## What was built

| Area | Where | Endpoints (all under `/api/v1`) |
| --- | --- | --- |
| Dashboard (2.1) | `app/admin/dashboard/` | `GET /admin/dashboard`, `GET /admin/dashboard/refresh` (polling; not activity) |
| Clients (3.1, 3.2) | `app/admin/clients/` | `GET /admin/clients`, `GET /admin/clients/{id}`, `POST .../deactivate`, `POST .../reactivate` |
| Escalations (4.1) | `app/admin/escalations/` | `GET /admin/escalations`, `GET .../{id}`, `PUT .../{id}/notes`, `POST .../{id}/review` |
| Support requests (5.1) | `app/admin/support/` | `GET /admin/support-requests`, `GET .../{id}`, `PUT .../notes`, `POST .../resolve`, `POST .../reopen`, `POST .../change-email` |
| Deletion requests (5.2) | `app/admin/deletions/` | `GET /admin/deletion-requests`, `POST` (teen, by email), `GET .../{id}`, `PUT .../notes`, `PUT .../checklist`, `POST .../start-review`, `.../complete`, `.../legal-hold`, `.../lift-legal-hold`, `.../decline` |
| Knowledge base (6.1 to 6.3) | `app/admin/knowledge/`, `app/knowledge/` | `GET /admin/knowledge`; contents: `GET`, `POST`, `GET/PUT .../{id}`, `GET .../{id}/versions/{n}`, `POST .../approve`, `.../reject`, `.../archive`, `.../restore`, `.../roll-back`; files: `POST /admin/knowledge/files`, `GET .../files/{id}`; gaps: `GET`, `GET .../{id}`, `POST .../dismiss`, `POST .../reopen` |
| Plans and pricing (8.1, 8.2) | `app/admin/plans/`, `app/billing/catalog.py` | `GET /admin/plans`, `POST`, `GET .../{id}`, `PATCH .../{id}`, `POST .../{id}/publish` |
| Policies (9.1, 9.2) | `app/admin/policies/` | `GET /admin/policies`, `GET .../{kind}`, `GET/PUT .../{kind}/versions/{id}` (PUT always 409), `POST/PUT .../{kind}/draft`, `GET .../draft/preview`, `POST .../draft/publish`; public `GET /policies/{policy_version_id}` |
| Jobs | `app/admin/jobs.py`, `app/knowledge/jobs.py` | `admin.sweep` (every 30 s), `admin_plans.price_change_emails`, `admin_plans.price_change_email`, `knowledge.sync_content` |

`app/admin/operations.py` gathers the routers; `app/main.py` mounts it, and the public policy router after the accounts router (so `/policies/current` matches first).

## Design choices

### Access

- Every endpoint uses `AdminSession`, except plans and pricing (`SuperAdminSession`: Admins get 403 `super_admin_only`, clients the usual 404).
- Inside the shared areas, the Super Admin's extras are checked in the services:
    - the Dashboard's subscription and free trial metrics, subscribers over time and Content to review;
    - Client Details' subscription section and the listing's plan column and filter (an Admin filtering by plan gets 403);
    - approving and rejecting knowledge base content.
- These fields are `None` for Admins and the endpoints use `response_model_exclude_none`, so they're **never sent**, not just hidden (Admin 2.1 and 3.1's non-functional requirements).
- **Policies:** Admins can publish too. Super Admin 9.1 and 9.2 both say "Admins can use this story, the same as the Super Admin"; this differs from the docstring of `super_admin_session`.

### Dashboard

- Aggregate queries only: no names, conversations or health details.
- **Needs Attention** shows what's open now:
    - escalations not yet reviewed, by level (no overdue count);
    - open support requests, by type (`support.open_counts`);
    - open deletion requests, and those due within 2 business days (legal holds aside);
    - new knowledge gaps;
    - for the Super Admin, content waiting for approval.
    - With nothing open, `all_clear` is true and `message` is "You’re all caught up."
- **KPIs and graphs** cover a range of UTC days (default: the last 30), in weekly periods (from Monday), or monthly ones for ranges over 182 days. A range with no sign-ups, activity, conversations, escalations or conversions gets "There’s no data for this date range."
- **Definitions** (approximations, see the questions):
    - total registered clients: adult client accounts created before the range's end;
    - active clients: a session in use during the range (`created_at` before its end and `last_seen_at` after its start);
    - total conversations: conversations started in the range, deleted ones included;
    - active subscribers: subscriptions that give access now, by plan;
    - free trial: clients with no subscription whose trial hasn't ended, and conversions (subscriptions started in the range);
    - subscribers over time: subscriptions started before, and not ended by, each period's end, by their current plan.
- **Top Health Topics** groups `conversations.topic` (the Oracle's short topic, lower-cased). A topic needs `dashboard_topic_min_count` (5) conversations to appear, so a rare topic can't point to one client. Top `dashboard_topic_limit` (10), highest first.
- **Teen Accounts** (filled in on 6 Nov, after Phase 3b): the card is `teens.service.dashboard_counts` (joined, invite sent, access paused), which is what's true now, whatever the range. The graph counts teen accounts whose `teen_accounts.joined_at` is before each period's end; a teen who has since created an adult account (1.6) has no row, so drops out of earlier periods too.
- **Who's a teen:** every query asks `users.account_type = 'teen'` (`common.is_teen()`), so an aged-out teen counts as a teen until they create their adult account, and an adult whose state changed never does.
- A database error gives 503 `dashboard_unavailable`, "We couldn’t load the dashboard. Please try again."

### Clients

- Only `role = client` accounts. An admin's id gets the same 404 as an unknown one.
- **Listing**, newest first:
    - **status**, computed in SQL in this order: deactivated, deletion requested (an open whole-account request), consent revoked, then from the subscription. No subscription is Trial; `past_due` is Payment issue; `cancelled` and `ended` are Cancelled; otherwise Active. A teen with their own account has no plan and can't revoke consent, so of 3.1's statuses they're Deactivated, Deletion requested or Active; whether their access is paused is in Client Details (`teen_account.access`);
    - **plan**: the plan a subscription gives access to now, else `trial`;
    - **family members**: finished family members; adults only;
    - **last active**: the latest session `last_seen_at`.
- **Client Details**, audited as `admin.client_viewed`:
    - account, consent (accepted Terms and Privacy versions, and the Health Consent versions accepted for the client's own profile, with dates; "Consent revoked" while revoked);
    - managed family members (first name, relationship, age by `ages.age_on`, turned off, deletion requested);
    - activity: last active, conversations, open support and deletion requests, escalations not reviewed (ids for links);
    - the open Email Change Request's id, `can_deactivate` / `can_reactivate`, and the stories' confirmation texts filled in. The teen warning appears only when there are invited teens;
    - the subscription (plan, status, next billing date, add-ons), Super Admin only.
- No conversations, summaries, notes or health profile answers.
- **Deactivate:**
    - `users.status = deactivated`, and every open session revoked with `revoked_reason = account_deactivated`, so the client gets 1.2's deactivated message straight away and at sign-in;
    - the reason is mandatory and goes into the audit event `admin.client_deactivated` (`reason`, `teen_accounts_paused`). 3.2 asks for "who did it, when, and the reason";
    - nothing is deleted, the subscription isn't touched, a pending deletion continues, and notifications stop (`notify` skips deactivated accounts). Repeating it changes nothing.
- **Reactivate:** `status = active`; the client signs in again. Audited as `admin.client_reactivated`.
- **Teens in Client Details:** a parent's `invited_teens` (`teens.service.admin_invited_teens`: first name as the parent typed it, 8.2's status, the teen's account id once joined) and a teen's `teen_account` (`admin_teen_link`: the parent's account and first name, and access active or paused).
- **Deactivating a parent** pauses their invited teens. The access gate already shuts while the parent isn't active (`teens.access.parent_pause_reason` gives `parent_inactive`), so nothing is stored: each joined teen who isn't turned off gets 12.1's `access_paused` notice ("Your access is paused. Please ask your parent or guardian...") and a `teen.access_paused` audit event with reason `parent_deactivated`. The confirmation's count and `teen_accounts_paused` count the same teens.
- **Reactivating a parent** reopens the gate by itself for teens whose parent's Family plan, consent and policies are in order; the rest stay paused. Each reopened teen gets `teen.access_restored` (reason `parent_reactivated`), and `admin.client_reactivated` has `teen_accounts_restored`. Nobody is notified: no story has a text for it (question 13).
- **Deactivating a teen** doesn't touch the parent, who isn't told.
- **Change email address** is on the Email Change Request (`POST /admin/support-requests/{id}/change-email`), through `accounts.service.change_email`. 3.1 only uses it for such a request, and Client Details gives the request's id.

### Escalations

- The listing is built here, because `safety.list_escalations` has no search, profile-type or date filters. Not yet reviewed comes first, then newest first.
- Rows outer-join the account, profile and triggering message, which may be gone.
- **Details**, audited as `escalation.viewed`:
    - the triggering message's text and the Oracle's one-line reason (`messages.safety_reason`);
    - the advice line shown, and the client's choice with its label. "No response" means an emergency or crisis with no choice; urgent asks nothing, so its label is null;
    - `outside_us`, `poison_control`, and for a teen's own account `parent_told_at` (`teens.service.parent_told_at`). A teen's profile is named from their account, like the client's own;
    - the review notes, and who reviewed it and when.
- **Review** goes through `safety.set_review_status`. Any notes sent with it are saved in the same transaction.
- **Review notes** live in `escalation_notes`:
    - one row per escalation, replaced on each save, and deleted with the client's account (`account_id ON DELETE CASCADE`), because they can describe the client's health and the escalation record must hold none for its 6 years (r3's open question);
    - once the account is gone, saving notes gets 409.
- Audit events: `escalation.viewed`, `escalation.note_saved` (never the text), plus the safety package's `escalation.reviewed` and `escalation.review_undone`.

### Support requests

- Thin endpoints over the support package's team functions, which already audit views, notes and status changes.
- Added here:
    - the empty-list message;
    - the date filters as UTC days;
    - 3.1's Change email confirmation in an open Email Change Request's details.
- **Change email:**
    - success answers 3.1's "[First name]’s email address has been changed.";
    - the accounts package's "already used" error is re-worded to 3.1's "An account with this email address already exists.".

### Deletion requests

- **Listing:** open requests first, closest deadline first, then closed ones, newest first.
    - Each row has `business_days_left` (weekdays, negative once overdue).
    - `highlighted` is true when it's open, not on legal hold, and due within `deletion_highlight_business_days` (2).
- **Details**, audited as `deletion.viewed`:
    - **what will be deleted**: the account (everything, transfer, teen) or not (family member, advocate only); the profiles affected, each `deleted`, `transfer_pending`, `transferred` or `kept`; and whether the subscription is kept;
    - **the checklist**: in-app requests start with identity confirmed (5.2: "confirmed automatically" for a signed-in account), and email ones are confirmed at creation;
    - the notes, the legal hold note, and who created and completed it.
- **Team-side data** lives in `deletion_request_reviews`, beside the privacy package's `deletion_requests`: the checklist, internal notes, legal hold note, the email's date, and the deadline reminder time.
- **Completing, the legal hold, lifting it, declining and starting the review** are the privacy package's functions (`complete_request` exists, so it's called; its purge job deletes the data and emails the client).
    - Complete saves the checklist first, so the ticks stay even when completion is refused.
    - The legal hold note is optional; 5.2 says "adds a note" but gives no message for an empty one.
- **+ Create deletion request** (a teen who can't sign in):
    - only a teen's own account (`support.is_teen_account`); anyone else gets 422 `not_a_teen_account`;
    - the date received is required and can't be in the future, and the form's "email came from the registered address" box must be ticked;
    - `requested_at` is that day (00:00 UTC), so the deadline is 10 business days from it;
    - the request is `source = by_email`, `created_by_id` set, and `team_notified_at` set so the privacy sweep doesn't email the team about its own request;
    - the teen's sessions end and their scheduled notifications are cancelled, as for an in-app request.
- **Deadline reminders:** the admin sweep sends `deletion_deadline` (`days`) once per request when it's within 2 business days, never while on legal hold.

### Knowledge base

- **Tables:** `knowledge_contents` (the item), `knowledge_content_versions`, `knowledge_files`, `knowledge_gaps`, `knowledge_gap_requests`.
- **Content is public material**, so it's not treated as health data. Gap questions are clients' words: never in logs, audit events, emails or job payloads. The in-app admin notice shows the question, as the notifications package's `knowledge_gap` kind asks.
- **Versions:**
    - a draft or a version pending approval is edited in place, so a draft later published is still "version 1" (6.2);
    - any other save adds a version;
    - `published_version` is what the Oracle uses unless archived; an Admin's edit is pending while the Oracle keeps the earlier published version;
    - the item's `status` is archived, or the latest version's status.
- **Who can do what:**
    - Super Admin's Publish publishes; an Admin's Publish is Pending approval, and the Super Admin gets `content_awaiting_approval`;
    - only the Super Admin approves or rejects (403 for Admins);
    - Admins can archive, restore and roll back, but roll back only to a version that was published before (already approved). Anything new goes through approval.
- **Roll back** publishes a copy of the earlier version as a new version (`rolled_back_from`), so the history stays in order. An open draft or pending version is marked `superseded`.
- **Archived content** can't be edited or rolled back until restored. Restore brings the item back to its latest version's status (Published if it was).
- **Sync** (`knowledge.sync_content`):
    - every change to what the Oracle uses sets `sync_status = pending` and queues the job;
    - the job calls the new contract methods `publish_knowledge(KnowledgeDocument)` or `withdraw_knowledge(content_id)`, with no row lock held during the call;
    - it records `synced` only if nothing changed meanwhile;
    - a failure sets `failed`, sends `knowledge_sync_failed` once per change, and is retried by the worker.
- **Content Sources** lists the sources (only "Uploaded" in 6.1) with item, published, sync pending and sync failed counts.
- **Uploads:**
    - `POST /admin/knowledge/files` (multipart) takes PDF (`%PDF-`), DOCX (`PK` zip) or UTF-8 text (`.txt`, `.md`), checked by extension and first bytes, up to `knowledge_upload_max_bytes` (20 MB);
    - stored in `knowledge_files` (bytes in Postgres for now, "the app's own library"); content refers to it by `file_id`;
    - errors use 6.2's texts: 415 unsupported, 413 too large, 503 upload failed.
- **Knowledge gaps** are made by the admin sweep from Knowledge Gap support requests not yet linked:
    - the new contract method `match_knowledge_gap(question, candidates)` says which earlier gap it's the same question as, and its topic. Candidates are the 200 most recently asked gaps;
    - a match increases `times_asked`, and reopens an Answered gap (6.3's "asked again after it was answered");
    - otherwise a new gap is made, with `knowledge_gap` sent to the team;
    - each request is committed on its own; an Oracle failure stops the batch until the next sweep;
    - the fake groups questions only when they're the same apart from case, spaces and punctuation.
- **Answering a gap:** publishing content with `knowledge_gap_id` marks the gap Answered (6.2's message becomes 6.3's "This gap has been answered..."). An Admin's answer waits for approval.
- **Dismissing** needs a reason; only a dismissed gap can be reopened.
- **Wellness Protocols:** `knowledge.service.published_contents(db, content_type="protocol")` gives what the Oracle uses now, for Phase 7 (see "Left for other packages").

### Plans and pricing

- **Tables:** `billing_plans` and `billing_plan_price_changes`, in `app/billing/catalog.py`, which billing already read prices from.
- **The launch plans** (`trial`, `individual`, `family`) get their rows from the settings the first time the plans listing is opened (`ensure_launch_plans`). Until then the catalogue uses the settings, so no seed rows are needed.
- **How billing reads them:**
    - the catalogue's functions keep their signatures (no session), so billing didn't change;
    - each process caches the launch rows for `plan_catalog_cache_seconds` (30) and reads them again with its own short session;
    - the admin panel calls `catalog.refresh(db)` after each change, so its own process sees it at once;
    - if the table can't be read, the last copy (or the settings) is used and a warning names only the error class;
    - tests that change plans should call `catalog.clear_cache()`.
- **Inactive:** `catalog.offers()` leaves an inactive plan out, so the plan screen stops showing it. `catalog.is_available(plan)` is there for billing's subscribe check (not called yet).
- **Editing** (`PATCH`):
    - the trial edits only `trial_days`, and can't be made inactive;
    - Individual: monthly price, features, status. Family adds members included and the add-on price;
    - a draft can also be renamed;
    - a price change, or making a plan inactive, needs `confirmed: true`. Without it the answer is 409 `confirmation_required` with the story's text, the price filled in;
    - each change of a price, trial length or members included adds a price history row with who and when.
- **Existing subscribers:** billing already stores each period's price and refreshes it at renewal, so a new price reaches them from their next billing date. A price change emails each renewing subscriber (`admin_plans.price_change_emails` in batches of 100, then one job per email), with the plan's name and new price only.
- **New plans** (8.2) are saved as drafts with a code made from the name. Publishing needs `confirmed` and the payment providers (`_set_up_with_providers`, a `PAYMENT PROVIDERS` hook). Billing sells only Individual and Family today, so publishing a new plan answers 8.2's "We couldn’t set up this plan with the payment providers. Please try again." (503), and the plan stays a draft, as 8.2's alternate scenario says.
- Audit events: `billing.plan_added`, `billing.plan_changed` (fields, old and new prices, status change), `billing.plan_published`, `billing.plan_setup_failed`.

### Policies

- **Tables:** `policy_texts` holds each version's text and summary of changes, and at most one draft per policy.
- **Published texts** are tied to `policy_versions` by kind and version. Nothing changes them: `PUT /admin/policies/{kind}/versions/{id}` always answers 409 with 9.1's "Published versions can’t be changed. Create a new version instead.".
- **The version number** is set automatically: the newest version's last number plus one ("1.0" becomes "1.1"). It's worked out again at publish.
- **+ New version** creates the draft with the live text, or returns the existing draft. Drafts can be empty until publishing.
- **Publish:**
    - needs the text and summary (9.2's messages) and `confirmed` (409 with 9.2's confirmation);
    - the draft becomes the version's text in the same commit as `accounts.service.publish_policy_version` (actor: the admin; `url`: none), which ends client sessions, emails every client and audits it;
    - then the team gets `policy_published`;
    - the title is the live version's title;
    - a database error gives 9.2's "We couldn’t publish this version. Please try again." (503).
- **Acceptance numbers:**
    - who counts: active adult client accounts (teens' parents accept for them);
    - accepted the Terms or Privacy Policy: a `policy_acceptances` row for the live version;
    - accepted the Health Consent: any `health_consents` row they accepted for the live version.
- Views of a policy and of a version are audited (`policy.viewed`, `policy.version_viewed`), as are drafts (`policy.draft_created`, `policy.draft_saved`).
- **`GET /policies/{policy_version_id}`** (no sign-in; the policies are public) gives a published version's text and summary, so policy text changes need no app release.

### Audit events added

`admin.client_viewed`, `admin.client_deactivated`, `admin.client_reactivated`; `escalation.viewed`, `escalation.note_saved`; `deletion.viewed`, `deletion.note_saved`, `deletion.checklist_saved`, `deletion.created_by_team`; `knowledge.content_added`, `.content_edited`, `.content_approved`, `.content_rejected`, `.content_archived`, `.content_restored`, `.content_rolled_back`, `.file_uploaded`, `.gap_created`, `.gap_asked_again`, `.gap_reopened`, `.gap_answered`, `.gap_dismissed`; the billing and policy events above. None holds a note, a question, a reason for rejection or dismissal, or any health data. The one free-text field is the deactivation reason (see question 1).

## Stored codes

| Column | Codes |
| --- | --- |
| `knowledge_contents.content_type`, `knowledge_content_versions.content_type` | `book`, `protocol`, `blog_post`, `qa_answer`, `symptom_chart`, `diagnostic_tree`, `case_study`, `knowledge_gap_answer` |
| `knowledge_contents.source` | `uploaded` |
| `knowledge_contents.status` | `draft`, `pending_approval`, `published`, `rejected`, `archived` |
| `knowledge_content_versions.status` | `draft`, `pending_approval`, `published`, `rejected`, `superseded` |
| `knowledge_contents.sync_status` | `none`, `pending`, `synced`, `failed` |
| `knowledge_files.media_type` | `application/pdf`, the DOCX type, `text/plain` |
| `knowledge_gaps.status` | `new`, `answered`, `dismissed` |
| `billing_plans.plan_type` / `status` | `trial`, `individual`, `family` / `draft`, `active`, `inactive` |
| `policy_texts.status` | `draft`, `published` |
| Admin notification kinds used | `knowledge_gap`, `content_awaiting_approval`, `knowledge_sync_failed`, `deletion_deadline`, `policy_published` |

## Messages not in the stories

| Situation | Code | Message |
| --- | --- | --- |
| Dashboard: end date before start date | `invalid_date_range` (422) | "Please choose an end date on or after the start date." |
| Unknown client, or not a client account | `client_not_found` (404) | "We couldn’t find that client." |
| An Admin filters clients by plan | `super_admin_only` (403) | "Only the Super Admin can do this." (the existing dependency's text) |
| Reasons over 500 characters | `validation_error` | "Please keep the reason to 500 characters or fewer." |
| Notes over 5,000 characters | `validation_error` | "Please keep the notes to 5,000 characters or fewer." |
| Escalation marked not yet reviewed | | "This escalation has been marked as not yet reviewed." |
| Escalation notes saved | | "Your note has been saved." (5.1's) |
| Escalation notes after the account was deleted | `account_deleted` (409) | "This client’s account has been deleted, so notes can’t be added." |
| Deletion checklist saved | | "The review checklist has been saved." |
| Teen deletion for an account that isn't a teen's | `not_a_teen_account` (422) | "Only a teen’s own account can be chosen here." |
| Teen deletion when one is already open | `deletion_already_requested` (409) | "This account already has an open deletion request." |
| Email's date in the future | `validation_error` | "The date the email was received can’t be in the future." |
| Identity box not ticked | `validation_error` | "Please confirm the email came from the address registered to the teen’s account." |
| Checklist hints | | "The request came from the signed-in account holder." / "The email came from the address registered to the account." |
| Content rejected / archived / restored | | "This content has been rejected." / "This content has been archived." / "This content has been restored." |
| Rolled back | | "Version [X] has been published again. The Oracle will start using it shortly." |
| Approve or reject with nothing pending | `nothing_pending` (409) | "There’s nothing waiting for approval on this content." |
| Editing or rolling back archived content | `content_archived` (409) | "Archived content can’t be changed. Please restore it first." |
| Rolling back to the live version | `already_live` (409) | "This version is already the one the Oracle uses." |
| An Admin rolls back to a never-published version | `rollback_needs_approval` (403) | "Only a version that was published before can be published again. Please edit the content instead, and it will be sent for approval." |
| Reopening an answered gap | `gap_not_dismissed` (409) | "Only a dismissed gap can be reopened." |
| Unknown content / version / file / gap | 404 | "We couldn’t find that content." / "...that version." / "...that file. Please upload it again." (422 when given as `file_id`) / "...that knowledge gap." |
| Title over 200 characters | `validation_error` | "Please keep the title to 200 characters or fewer." |
| Unknown plan | `plan_not_found` (404) | "We couldn’t find that plan." |
| A field the plan type doesn't have | `not_editable` (422) | "This can’t be changed for this plan." |
| Making the trial inactive | `trial_always_active` (422) | "The free trial can’t be made inactive." |
| Renaming a published plan | `name_fixed` (422) | "A published plan’s name can’t be changed." |
| Setting a draft's status | `publish_first` (422) | "Please publish this plan first." |
| Publishing a published plan | `already_published` (409) | "This plan has already been published." |
| Too many features, or one too long | `validation_error` | "Please keep it to 20 features or fewer." / "Please keep each feature to 200 characters or fewer." |
| The price change email | | Subject "A change to your plan’s price"; "The price of your [Plan] plan is changing to [price] a month." and/or "The price of each extra family member on your [Plan] plan is changing to [price] a month.", then "You’ll pay the new price from your next billing date. You can change or cancel your plan anytime in Profile & Account." |
| Unknown policy kind / version | 404 | "We couldn’t find that policy." / "We couldn’t find that version." |
| No draft to save, preview or publish | `no_draft` (404) | "There’s no draft of this policy. Please create a new version first." |

## Assumed values (settings)

| Setting | Value | Why |
| --- | --- | --- |
| `admin_list_max_limit` | 200 | Rows per page (default 50) |
| `admin_note_max_length`, `admin_reason_max_length` | 5,000, 500 | No limits in the stories |
| `deletion_highlight_business_days` | 2 | 5.2 and 11.1 |
| `dashboard_topic_limit`, `dashboard_topic_min_count` | 10, 5 | 2.1's privacy rule |
| `admin_sweep_seconds` | 30 | 6.3: gaps and alerts within 1 minute |
| `knowledge_gap_batch_size`, `knowledge_gap_match_candidates` | 50, 200 | Per sweep; also the deadline reminders' batch |
| `knowledge_upload_max_bytes` | 20 MB | 6.2: "sizes to confirm with Tkxel" |
| `knowledge_text_max_length`, `knowledge_title_max_length` | 1,000,000, 200 | Books can be long |
| `plan_max_price_cents`, `plan_max_trial_days`, `plan_max_family_members` | $1,000, 365, 20 | What "a valid price" and "a valid trial length" mean |
| `plan_max_features`, `plan_feature_max_length` | 20, 200 | The plan screen |
| `plan_catalog_cache_seconds` | 30 | How long other processes take to see a plan change |
| `price_change_email_batch_size` | 100 | Like the policy emails |
| `policy_text_max_length`, `policy_summary_max_length` | 200,000, 1,000 | |

## Open questions for the BA

1. **The deactivation reason** is free text in the audit log (3.2 asks for it there), which keeps it for 6 years, even after the data is deleted. Should staff be told never to write health details in it, or should it be a list of reasons?
2. **Escalation review notes** are deleted with the client's account, while the escalation stays 6 years (r3's question). Should the notes be kept with it?
3. **Dashboard definitions:**
    - Does Total Registered Clients include teens with their own account (built: no, they're on the Teen Accounts card)?
    - Is "active" a session in use during the range (built)?
    - Are deleted conversations counted (built: yes)?
    - Top Health Topics groups the Oracle's free-text topics with a minimum of 5. Should the AI team give fixed categories (Sleep, Thyroid...), like the knowledge gaps' topics?
4. **Rolling back as an Admin:** built as allowed only to versions published before. Is that right, or does every Admin roll back need approval?
5. **Price changes:**
    - What notice period applies before existing subscribers pay a new price? Built: they're emailed at once and pay it from the next billing date, however soon that is.
    - What happens to clients above a lowered "family members included" (8.1: "to confirm")?
6. **New plans** can't be sold until billing supports plan codes beyond Individual and Family, and the providers' plan setup exists. Is a new Family-type plan meant to replace Family for new clients, or to sit beside it?
7. **The free trial** can't be made inactive (built), since sign-up always starts one. Right?
8. **Content Sources:** 6.1 lists only "Uploaded". What else belongs on that screen (the AI team's sync state, which we show)? What's the agreed update time with Tkxel?
9. **Knowledge gap questions** stay after the client's account is deleted (the gap never says who asked). 10.1's question 2 asks the same. Should they be removed with the account?
10. **Policies:** should Admins really publish policy versions (9.1 and 9.2 say yes)? Is there a separate family-member text of the Health Consent (9.1: "with a family member version for advocates")? Built: one text per version.
11. **Ended subscriptions** show as "Cancelled" in the client listing, since 3.1's statuses have no "Ended". Right?
12. **A teen deletion by email:** should the team get the usual new-request email and notification? Built: no, since the team made it.
13. **Reactivating a parent:** should their teens be told their access is back (no teen-side text exists), or the parent get 12.1's "[Name]’s access has been restored."? Built: nobody is told.

## Left for other packages

- **Billing** (`app/billing/`, not this build's):
    - read `catalog.trial_days()` and `catalog.family_members_included()` instead of `settings.trial_days` and `settings.family_members_included`. The settings are read in `auth/service.py` (the trial at verification), `privacy/service.py` (a transferred profile's new account), `billing/service.py` (`plans()`, add-ons) and `billing/entitlements.py`;
    - refuse subscribing to a plan where `catalog.is_available(plan)` is false;
    - support new plan codes (`subscriptions.plan`'s check, `PaidPlan`) and add plan and price setup to `PaymentProvider`. Then `admin.plans.service._set_up_with_providers` can return True, and price changes can update the providers (the `PAYMENT PROVIDERS` comments).
- **Accounts:** `PolicyOut` could carry the text and summary, or the apps can read `GET /policies/{id}`. New versions are published with no `url`.
- **Phase 7 (Wellness):** 6.1 says Wellness Protocols are knowledge base content, while `app/wellness/` reads `protocols.json`. Reconcile them through `knowledge.service.published_contents(db, "protocol")`.
- **AI team:** the three new contract methods, `publish_knowledge`, `withdraw_knowledge` and `match_knowledge_gap`.

## The migration

New tables, which autogenerate should produce whole with their check constraints: `knowledge_files`, `knowledge_gaps`, `knowledge_gap_requests`, `knowledge_contents`, `knowledge_content_versions`, `billing_plans`, `billing_plan_price_changes`, `policy_texts`, `escalation_notes`, `deletion_request_reviews`. Check in the generated file:

- **The circular foreign keys:** `knowledge_gaps.answer_content_id` and `knowledge_contents.knowledge_gap_id`. The first is `use_alter`, so it must be created with `op.create_foreign_key` after both tables.
- **Indexes:**
    - the functional unique index `uq_billing_plans_name` on `lower(name)`. Autogenerate may skip or mis-render expression indexes; add it by hand if missing;
    - the partial unique indexes keep their `postgresql_where`: `uq_billing_plans_one_trial` (`plan_type = 'trial'`) and `uq_policy_texts_one_draft` (`status = 'draft'`).
- **Defaults:**
    - `server_default=clock_timestamp()` on `knowledge_content_versions.created_at` and `billing_plan_price_changes.changed_at`;
    - the `server_default`s on `deletion_request_reviews.identity_confirmed` and `legal_hold_checked` (false), and on `policy_texts.text`, `summary_of_changes` (`''`) and `status`.
- **Column types:** `billing_plans.features` is `ARRAY(VARCHAR)`; `knowledge_files.data` is `BYTEA`.
- **Foreign keys' `ON DELETE`:**
    - CASCADE: `escalation_notes.escalation_id` and `.account_id`, `deletion_request_reviews.deletion_request_id`, `knowledge_gap_requests.support_request_id` and `.gap_id`, `knowledge_content_versions.content_id`, `billing_plan_price_changes.plan_id`;
    - RESTRICT: `knowledge_content_versions.file_id`;
    - SET NULL: the `*_by_id` columns.

Nothing changes on existing tables. There are no seed rows (the launch plans are created from the settings when the admin panel first opens) and no data changes. Optional, recommended triggers, as for `audit_events`:

- refuse UPDATE and DELETE of `policy_texts` rows whose `status = 'published'` (9.1: published versions can never be changed or deleted);
- refuse DELETE on `knowledge_contents` and `knowledge_content_versions` (6.1: content is archived, never deleted).

## Added during integration

- **The catalogue is read everywhere:** the trial's length at verification (`auth/service.py`) and for a transferred profile's new account (`privacy/service.py`), the Family plan's places (`billing/entitlements.py`, `billing/service.py`'s add-ons) and the plan screen's `trial_days` now come from `catalog.trial_days()` and `catalog.family_members_included()`. The teens package still read `settings.trial_days` when this was written; see the integration notes in its decisions file.
- **Inactive plans can't be chosen:** subscribing or changing to an inactive plan answers 409 `plan_unavailable` "That plan isn’t available any more. Please choose another plan." (not in the stories). A client whose subscription is still on that plan keeps it, and can subscribe to it again while the paid period lasts (11.3's resume).
- **Not done:** new plan codes beyond Individual and Family, and plan and price setup through `PaymentProvider`. Publishing a new plan still answers 8.2's "setup failed" message.
- **Both triggers are in migration `10e70f9b0139`** (`policy_texts_published_frozen`, and `knowledge_contents_no_delete` / `knowledge_content_versions_no_delete`). One consequence: deleting an admin account who published a policy text would fail, because the `*_by_id` SET NULL updates a published row. Admin accounts are deactivated, never deleted, in the stories.
