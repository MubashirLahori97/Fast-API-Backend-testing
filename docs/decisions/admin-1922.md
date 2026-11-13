# Admin panel: the BA's 6 Nov 19:22 Admin and Super Admin stories

Built on 10 Nov 2026 against Super Admin 3.1, 6.1 to 6.3, 7.2, 9.1, 9.2, 10.1 and 11.1, and Admin 3.1, 6.1 to 6.3, 7.1, 8.1 and 8.2 (deletion-related parts excluded: they're the deletion work's). Code only: no tests, no migration (the parallel build's rules). Earlier decisions stay in `phase-a1-admin-access.md` and `phase-a2-admin-operations.md`; this file records what changed.

## What changed

| Story | Change | Where |
| --- | --- | --- |
| 3.1 Client Details | `health_profile`: the client's own health profile, read-only, for the Super Admin and Admins, teens with their own account included | `app/admin/clients/health.py`, `schemas.py` (`HealthProfileView`), `service.client_detail` |
| 9.1, 9.2 Consent Management | Super Admin only (`SuperAdminSession`): an Admin gets 403 `super_admin_only`, a client 404. The public `GET /policies/{id}` is unchanged | `app/admin/policies/router.py` |
| 10.1 Audit Logs | Super Admin only, the same way. Admins' actions are still recorded | `app/admin/audit/router.py` |
| 7.2 Admin Permissions | the list adds "Consent Management, and viewing the Audit Logs" | `app/admin/admins/service.py` |
| 6.1 to 6.3 Knowledge base | no Content Sources, no source field, no sync job or failed-sync alert; Send for approval for Admins; Answer pending; Admins' decision notices | `app/knowledge/`, `app/admin/knowledge/` |
| 11.1, Admin 7.1 | `knowledge_sync_failed` removed; `content_approved` and `content_rejected` added (to the Admin who sent it) | `app/admin/notifications/kinds.py`, `service.notify_admins(recipient_id=...)` |
| Admin 8.1, 8.2 | already built as Super Admin 12.1 and 12.2; the stories' messages match. Docstrings now name Admin 8.1 and 8.2 | `app/admin/profile/` |

## Design choices

### Client Details' health profile (3.1)

- **Which profile:** the account's own (`is_self`) profile only, for adults and for teens with their own account. 3.1 says "the health profile"; family members' health profiles aren't shown (question 1).
- **Read through `app/health/service.health_profile_out`**, the same view My Health gives the client (only the questions that apply, with their answers), not `get_health_profile`, whose trial lock is the client's, not the admin's. `app/health/` isn't changed.
- **Read-only:** the copy drops what's only for editing: About you's `editable` is empty, `prefill` is null, and each answer's `conversation_id` is null (conversations aren't shown). `remove_confirmation` isn't included.
- **Null when there's nothing to show**: no own profile, or no date of birth yet (no question applies). The endpoint uses `response_model_exclude_none`, so null fields inside the health profile (for example an unanswered question's `answer`) are left out of the JSON rather than sent as null.
- **Audit:** every view is still `admin.client_viewed`, now with `details: {"health_profile_shown": true|false}` (no health data), so a view that showed health information can be found.
- Pending health facts (`health_facts`, waiting for the client's confirmation) aren't shown: they aren't part of the health profile until confirmed.

### Super Admin only: Consent Management and Audit Logs

- Both routers take `SuperAdminSession`. The audit service's Admin rules (hiding the `subscriptions` category) are left in place; no Admin reaches them now.
- Admins still get the `policy_published` notification (Admin 7.1 keeps it).

### Knowledge base (6.1 to 6.3)

- **Removed:** `knowledge_contents.source` and its check, the sync columns (`sync_status`, `sync_requested_at`, `synced_version`, `synced_at`, `sync_failed_at`) and their check, the `knowledge.sync_content` job (`app/knowledge/jobs.py` deleted, and its import in `app/worker.py`), Content Sources on `GET /admin/knowledge`, the `source` filter and field, and the detail's sync fields. `GET /admin/knowledge` now returns `new_gaps` and `pending_approval`.
- **How published changes still reach the Oracle** (6.1: "without an app release"): `knowledge.service.deliver(db, item, oracle)` calls the contract's `publish_knowledge` (the live version) or `withdraw_knowledge` (archived, never published) in the admin's request, after the change is flushed and with the item's row lock held, before the commit. If the Oracle fails, the change is rolled back and the admin gets the stories' "We couldn’t do that just now. Please try again." (503 `action_failed`), so the two never disagree for long and nothing needs a retry job or a failed-sync alert. If the commit itself fails after the Oracle accepted, trying again republishes (publishing the same version again is not an error). The contract's docstrings say so.
- **Buttons:** `action` is `draft` (everyone), `publish` (Super Admin only; an Admin gets 403 `super_admin_only`, "Only the Super Admin can do this.": Admin 6.2's "Publishing is enforced by the system") or `send_for_approval` (Admins only; the Super Admin gets 422 `invalid_action`).
- **Messages for an Admin's save:** new content "Your content has been sent to the Super Admin for approval." (Admin 6.2); an edit "Your changes have been sent to the Super Admin for approval." (Admin 6.1); content linked to a knowledge gap "Your answer has been sent to the Super Admin for approval." (Admin 6.3), for both new and edited answers.
- **`can_review`** on the details: true only for the Super Admin on a Pending approval item (Admin 6.1: no Approve or Reject buttons for Admins). Approve and Reject stay refused for Admins in the service.
- **Rejected items stay in the listing** as Rejected, with the reason on the details (this was already so; the docstrings now say it).
- **Decision notices (Admin 6.2, 7.1):** approving or rejecting tells the Admin who last saved the pending version (`updated_by_id`, else `created_by_id`), with `content_approved` or `content_rejected` (category `knowledge_base`, screen `content_review`, target: the item). The Super Admin isn't told of their own decision. The texts don't name the content: a knowledge gap answer's title is prefilled from the client's question.
- **Fixed:** an Admin's save used the kind `content_awaiting_approval`, which didn't exist; it's `content_pending_approval` now.

### Knowledge gaps (6.3)

- **New status `answer_pending`** (`knowledge.models.GAP_STATUSES`). An Admin's answer sent for approval (new or edited content with `knowledge_gap_id`) makes a New gap Answer pending, sets `answer_content_id` to it, and is audited as `knowledge.gap_answer_pending`. A gap that's Answered or Dismissed isn't changed.
- **Approved:** the gap is Answered, as before (`knowledge.gap_answered`).
- **Rejected:** if the gap is Answer pending with this answer, it goes back to New (`knowledge.gap_answer_rejected`); `answer_content_id` keeps pointing at the rejected answer, so the gap's details show `answer_content.status = rejected` and `answer_content.rejection_reason` ("with the reason on the answer").
- **Admins dismiss and reopen** gaps (already allowed by `AdminSession`).
- Asked again while Answer pending: the count goes up and the status stays.
- Not counted as "new gaps" on the Dashboard or the Knowledge Base screen: only New is.

### Stored codes

- `knowledge_gaps.status`: `new`, `answer_pending`, `answered`, `dismissed`.
- Admin notification kinds: `content_approved`, `content_rejected` added; `knowledge_sync_failed` removed.
- Audit actions added: `knowledge.gap_answer_pending`, `knowledge.gap_answer_rejected`. `admin.client_viewed` gains `health_profile_shown`.
- Error codes added: `invalid_action` (422), `action_failed` (503, an Oracle failure on delivery).

## Messages not in the stories

| Situation | Message |
| --- | --- |
| The Super Admin sends `send_for_approval` | "Please choose Save as draft or Publish." |
| `content_approved` notice (in-app / email) | "The Super Admin has approved content you sent. It’s now published." / "Content you sent has been approved" (title "Content approved") |
| `content_rejected` notice (in-app / email) | "The Super Admin has rejected content you sent. Open it to see the reason." / "Content you sent has been rejected" (title "Content rejected") |

## Assumed values

None new. The Oracle's delivery has no timeout setting of its own (the contract asks for a few seconds).

## Open questions for the BA

1. **Whose health profile in Client Details?** 3.1 says "the health profile". We show the account holder's own (or the teen's own). Should family members' health profiles be shown too?
2. **Admin 3.1 contradicts itself:** its Privacy line still says Client Details doesn't show "health profile answers", while its new criterion shows the health profile read-only. We followed the newest criterion. Its "Health Information: includes health information only which would get updated as the user converse with the Oracle" also reads as if only Oracle-learned answers count; we show the whole health profile, since every answer can be updated in conversation. **Decided by the user on 10 Nov: follow the new text.**
3. **Admins seeing health information.** Admins now see clients' health profiles (both 3.1s), while subscription details are kept from them. Has the HIPAA minimum-necessary review covered Admins seeing health profiles?
4. **"Nothing is synced automatically"** (6.2): we read it as no automatic import from Deborah's website and no sync job, and give published changes to the Oracle in the publishing request (an Oracle failure means "try again"). Is that the agreed way with Tkxel, and what's the agreed update time?
5. **An Admin's answer to a dismissed or answered gap:** we leave the gap's status as it is (only a New gap becomes Answer pending). Right?
6. **Who is told of a decision** when the Super Admin edits an Admin's pending content and publishes it directly: nobody, as that isn't an approval. Should the Admin be told?

## For the migration (autogenerate misses or needs checking)

- `knowledge_contents`: drop `source`, `sync_status`, `sync_requested_at`, `synced_version`, `synced_at`, `sync_failed_at`, with `ck_knowledge_contents_source` and `ck_knowledge_contents_sync_status` (autogenerate drops the columns; check the constraints go too).
- `knowledge_gaps`: replace `ck_knowledge_gaps_status` with `status IN ('new', 'answer_pending', 'answered', 'dismissed')` (autogenerate doesn't see check changes).
- Data: `DELETE FROM admin_notifications WHERE kind = 'knowledge_sync_failed'` (the notification centre reads each row's kind from `KINDS`), and `DELETE FROM jobs WHERE kind = 'knowledge.sync_content'` (no handler any more).
