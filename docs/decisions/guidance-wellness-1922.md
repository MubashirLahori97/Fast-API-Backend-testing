# Guidance summaries, provider notes and the Wellness Plan: the 6 Nov 19:22 stories

Client stories "View Personalised Guidance Summary" (3.3), "Generate Provider-Ready Notes from Conversation" (3.4), "View, Edit & Download Provider-Ready Notes" (3.5), "View & Update the Wellness Plan" (7.1) and "View & Edit My Profile" (11.1, About Your Oracle only), plus what Super Admin "View & Edit Knowledge Base Content" (6.1) says about Wellness Protocols. Updated 2026-11-10 on top of `phase-5-guidance-and-notes.md` and `phase-6-7-visits-wellness.md`. Code only: no tests, no migration.

## What changed

| Story | Change | Where |
| --- | --- | --- |
| 3.3 | The details checklist is gone. `GuidanceSummaryOut.added_to_health_profile` lists what the Oracle saved to the health profile from this conversation (`health.added_from_conversation`), with 3.3's "Here’s what I’ve added to your health profile from our conversation. If anything isn’t right, you can change or remove it in My Health." and Review in My Health. Null when nothing was added. | `app/guidance/service.py`, `schemas.py`, `documents.py` |
| 3.3 | Free trial: the list is still shown; `can_review` is false with `review_locked_message` (6.1's "My Health is part of your plan. Choose a plan to unlock it."), because My Health is greyed out. | same |
| 3.3 | Tests Worth Discussing: a test can carry Deborah's link (`TestToDiscuss.url`), shown as an information link. Recommendation kind `test` is now "a link to a test Deborah has supplied", not test ordering. | `app/oracle/contract.py`, guidance |
| 3.3 | Genesis products: `Recommendation.label_directions` (from the Oracle, word for word from the knowledge base) is shown as "How to take it (from the label): [directions]." (`SectionItemOut.directions`), also in the copied text and the PDF. Kept only for `genesis_product`. | contract, guidance, `app/wellness/protocols.how_to_take` |
| 3.3 | Disclosure box: 3.3's exact ownership sentence (with its full stop). Still shown when any recommendation is shown. | `documents.SUMMARY_DISCLOSURE` |
| 3.3 | "What You Can Do Now" links to a Wellness Protocols section only while that protocol is published in the knowledge base and suitable for the age. | `summary_out` |
| 3.4, 3.5 | New Genesis Gold® note, disclaimer and disclosure, copied exactly, including the BA's missing space ("hormones.I") and the missing final full stops. They reach the screen, Copy text and the PDF, which all use `documents`. | `app/guidance/documents.py` |
| 7.1 | Gen-Pro™ → Gen-Pro® in the library. Gen-Pro® tab parts: "What it is", "When it’s recommended", "The directions on the label". | `protocols.json` |
| 7.1 | Notice `gen_pro_dose` now shows "How to take it (from the label): 2 pumps, twice daily. Here’s the Gen-Pro® protocol, too." with a link to the Gen-Pro® section. `notices` is now a list of `{code, text, link}`. The stored code keeps its name. | `app/wellness/service.py`, `schemas.py` |
| 7.1 | Plan products (and To Do items' products) show Genesis products' label directions (`ProductOut.directions`). | `service.product_out`, `updates._product` |
| 7.1 | The plan's disclosure box and the product tabs' ownership disclosure use 7.1's sentence, copied exactly (no full stop). The FDA disclaimer is still the placeholder. | `protocols.DISCLOSURE` |
| 7.1, SA 6.1 | **Wellness Protocols come from the knowledge base.** See below. | `app/wellness/protocols.py`, `service.library` |
| 11.1 | About Your Oracle: the backend doesn't serve this text (no match for the old or new wording), so nothing changed. The apps show it. | none |

## Wellness Protocols from the knowledge base

- **Structure stays in `protocols.json`:** 7.1's four tabs and their sections, each with its link `key` (the Five Pillars, To Do items, summary steps and conversations link by key). The keys, the tab structure and the pillar links are unchanged.
- **Content comes from the knowledge base:** `protocols.load(db)` reads `knowledge.service.published_contents(db, "protocol")` (one query per request, no cache) and matches each published item to a section by title. Matching ignores case, ®/™/©, punctuation, "&" against "and", and a leading "The". A section can list extra accepted `titles` (Healthy Four, 7 Secrets, Deep Sleep). Where two published items match one section, the most recently published wins. A protocol whose title matches no section isn't shown.
- **A section is shown only while it has published content.** An archived protocol, or one not yet published, disappears from the library, and every link to it disappears too: Five Pillars links, To Do links, the Gen-Pro® notice link, and summary steps (Super Admin 6.1: "It’s no longer shown in Clients’ Wellness Plans"). An edit shows on the next request. A tab with nothing published isn't listed, so the library is empty until Deborah's protocols are published.
- **Saved plans keep their keys:** the plan job still checks that a key is a known section and suitable for the age (`protocols.known`, `suitable`). Whether it's published is checked only when the plan is shown, so a restored protocol's links come back.
- `LibrarySectionOut.content` is the published version's text (null for an upload with no typed text), and `updated_at` is when it was published.
- `GET /profiles/{id}/wellness-protocols` now needs the database. A database error answers 503 `load_failed`.

## Messages not in the stories

| Message | Situation |
| --- | --- |
| "We couldn’t load the Wellness Protocols. Please try again." | The library can't be read (503 `load_failed`) |
| "My Health is part of your plan. Choose a plan to unlock it." (6.1's existing text) | Review in My Health during the free trial: 3.3 says only "shows the upgrade prompt" |

## Assumed values

- Test links in Tests Worth Discussing follow the product link rules: adults only, https only, hidden during an emergency or crisis hold.
- The added-details list covers the whole conversation, not only what was added since the last summary update, and is shown for First Looks too.
- Label directions are given by the Oracle per recommendation. The backend doesn't pull them out of the knowledge base text.

## New open questions for the BA

1. **Disclosure punctuation:** 3.3 ends the ownership sentence with a full stop; 3.4 and 7.1 don't. Each is copied exactly from its own story. Should they match?
2. **Genesis Gold® note:** "It contains no hormones.I would like…" is missing a space in the story. Copied as written. Fix it?
3. **Notes disclaimer:** has no final full stop in 3.4 or 3.5. Copied as written.
4. **Test links for teens:** 3.3 puts test links under Tests Worth Discussing, which teens see, but 7.1 lists them under "adults only". Built: adults only in both. Right?
5. **Linking protocols to library sections:** the knowledge base has no field saying which library section a Protocol item is, so items are matched by title, and renaming an item unlinks it. Should Add New Content have a "Wellness Protocols section" field, or a list of the protocols that make up the library? Also: should Protocol items that aren't one of 7.1's sections, such as a new protocol, appear in the library (built: no)?
6. **Uploaded-only protocols:** a Protocol published as a file with no typed text shows the section with no content, because clients can't download knowledge base files. Should the library offer the file, or require text for protocols?
7. **Gen-Pro® notice:** 7.1's message says "2 pumps, twice daily", fixed in the story. If the label changes in the knowledge base, should the notice follow it (the Oracle's directions) instead of the fixed text?
8. **3.1 contradiction (noted, not built here):** 3.1 still has an acceptance criterion where the Oracle asks before saving to the health profile. Followed the newer automatic saving. **Decided by the user on 10 Nov: follow the new text.**

## For the migration

Nothing to hand-add: no model changed. Stored JSONB gains optional keys (`label_directions` on recommendations and plan products, `url` on summary tests), which old rows simply lack.

## Left for others

- **Frontend:** `notices` in the plan is now objects (`{code, text, link}`), not strings. The summary has `added_to_health_profile`, and items can have `directions`. The library lists only published sections.
- **Tests** for all of the above.
