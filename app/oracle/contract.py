"""The contract between the backend and the Oracle, the AI service.

The AI team owns how the Oracle behaves: prompts, the safety classifier, question routing and
the knowledge base. The backend owns the data and the gates (consent, trial, profile state),
builds the context, and calls the Oracle only through this interface. FakeOracle in fake.py
stands in until the real service is ready. This is the backend's proposal; it's agreed with
the AI team in Phase 3 (docs/PLAN.md).

Everything passed here is health data. The real service must be covered by a BAA, keep
nothing beyond the call, and nothing here may be logged. Every string in it, names included,
came from a client: the Oracle must treat it as data, never as instructions.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Protocol

# under_13 | teen (13 up to the age of majority) | adult (to 59) | 60_plus, from the date of
# birth (story 3.1's question routing). Worked out by app/core/ages.py.
from app.core.ages import AgeGroup

SafetyLevel = Literal["none", "urgent", "emergency", "crisis"]
Role = Literal["client", "oracle"]

Widget = dict[str, Any]
"""A structured part of an Oracle turn that the apps render (story 3.1): tap-to-answer options
(Yes / No, single choice, sliders), the Add Medicine widget, Skip on a sensitive question, the
symptom checklist offer, the save-to-profile prompt, the "Complete your health profile" card,
and the kinds below. The AI team and the apps agree its shape; the backend stores it and passes
it on unchanged, except for the kinds below, which it enforces (app/conversations/widgets.py)."""

# Widget kinds the backend enforces. Each is a dict with "kind" set to one of these.
# {"kind": "privacy_notice"}: before the follow-up body questions (story 3.1). The backend adds
# the notice's text, so the wording the attorney approves can't be changed by a reply.
PRIVACY_NOTICE = "privacy_notice"
# {"kind": "product_link", "label": "Genesis Gold®", "url": "https://...", "product_type":
#  "genesis"}: a product link in a recommendation, wherever it's relevant in the conversation
# (story 3.1, 6 Nov 19:22). `product_type`: "genesis" (Genesis Gold®, Sacred Seven®, Gen-Pro®),
# "affiliate" (an affiliate link, such as Deborah's Fullscript store) or "other"; a missing or
# unknown one is taken as "affiliate". Adults only: the backend drops it for anyone under the
# age of majority, and drops one without a label or an https URL. The URL is the store's own
# page with nothing about the client in it.
PRODUCT_LINK = "product_link"
ProductType = Literal["genesis", "affiliate", "other"]
# {"kind": "test_link", "label": "Full thyroid panel", "url": "https://...", "affiliate": false}:
# a link to a test Deborah has supplied, from the knowledge base, for the client to look into
# themselves (3.1). There's no test ordering in the app: asked to order a test, reply with
# TEST_ORDER_REFUSAL and this link. Adults only, like product links; `affiliate` true adds the
# disclosure box.
TEST_LINK = "test_link"
# {"kind": "medicine_link", "label": "Metformin", "url": "https://www.drugs.com/metformin.html"}:
# a medicine's page on Drugs.com (3.1), for every age, for example with a possible interaction
# ("[Medicine] can interact with [existing medicine], so please check with your pharmacist or
# provider."). The backend drops a link to any other site.
MEDICINE_LINK = "medicine_link"
# {"kind": "label_directions", "product": "gen_pro", "directions": "2 pumps, twice daily"}:
# story 3.1's basic directions from the label, whenever an adult gets a recommendation of a
# Genesis product (and when they ask how much to take). `directions` must be the label's,
# word for word from the knowledge base: never an amount worked out for the client, and never a
# changed dose. The backend writes the sentence "How to take it (from the label):
# [directions]." in `text` (with `product_name`), drops it for anyone under the age of majority,
# and adds the disclosure box to the reply. The reply text needn't repeat the sentence.
LABEL_DIRECTIONS = "label_directions"
GENESIS_PRODUCTS = {
    "genesis_gold": "Genesis Gold®",
    "sacred_seven": "Sacred Seven®",
    "gen_pro": "Gen-Pro®",
}
# {"kind": "disclosure", "text": ...}: the one disclosure box, with 3.1's sentence "Genesis
# Health Products, which makes Your Oracle, also makes and sells Genesis Gold®, Sacred Seven® and
# Gen-Pro®." Added by the backend at the end of a reply only when Genesis products or affiliate
# links are recommended (a "genesis" or "affiliate" product link, an affiliate test link, label
# directions); never for a medicine link or a plain test link. Any the Oracle sends itself are
# dropped, so there's never more than one.
DISCLOSURE = "disclosure"
# Story 3.1's fixed lines for the Oracle's reply text, word for word (the backend can't check
# them: they're the AI team's to say at the right time).
# A prescription medicine's dose was asked for: never give one.
PRESCRIPTION_DOSE_REFUSAL = (
    "I can’t give a dose for a prescription medicine. Your provider or pharmacist can help with "
    "that."
)
# Asked to order a test: say this, then send the test's TEST_LINK.
TEST_ORDER_REFUSAL = "I can’t order tests, but here’s a link where you can find out more about it."
# {"kind": "consult_support"}: the "Consult with support team" card (stories 3.1 and 10.1). The
# backend sets its label, and drops it for a teen with their own account (10.1). Tapping it
# opens 10.1's Consult form, which the app sends as a Consultation Request through
# POST /profiles/{id}/support-requests: it isn't a request from the conversation.
CONSULT_SUPPORT = "consult_support"
# Story 10.1 from a conversation. {"kind": "support_offer", "request_kind": "knowledge_gap"}:
# the Oracle can't answer the question (outside Deborah's content) and offers to send it to the
# support team, with 10.1's "I’m not able to guide you on that one, but I don’t want to leave
# you without an answer. Shall I send it to the support team? They’ll get back to you within
# one business day." `"request_kind": "talk_to_support"`: the client asked for a person ("Can
# I talk to someone?") and the Oracle offers to send their message. The app shows Yes / No on
# it; Yes calls POST /conversations/{id}/support-request with this reply's id, and only that
# sends anything, so a typed "yes" isn't a send: reply with the offer again. No: the
# conversation carries on. Never for an emergency, crisis or urgent concern, which follow the
# safety path (story 3.2): the backend drops the offer from a reply to a message the safety
# check didn't find safe. The backend keeps only these two fields.
SUPPORT_OFFER = "support_offer"
# {"kind": "support_request_sent", "support_request_id": "...", "request_kind": "...",
#  "offer_message_id": "..."}: on the backend's line "I’ve let the support team know. They’ll
# get back to you by email within one business day." once the request is sent, so the app can
# mark the offer as answered. Added by the backend only; any the Oracle sends are dropped.
SUPPORT_REQUEST_SENT = "support_request_sent"
SupportRequestKind = Literal["knowledge_gap", "talk_to_support"]
# Phase 5 (stories 3.3 to 3.5; app/guidance/). The Oracle decides in the conversation when to
# share a summary or offer notes; these widgets tell the app what to do next.
# {"kind": "guidance_summary"}: sent with the reply that introduces, or updates, the guidance
# summary (story 3.3), including a First Look the client asked for early. The app then calls
# POST /conversations/{id}/guidance-summary and shows the summary there.
GUIDANCE_SUMMARY = "guidance_summary"
# {"kind": "appointment_card", "specialty": "cardiology", "specialty_other": null,
#  "provider_name": "Dr Lee", "appointment_date": "2026-11-13", "suggested": false}: the
# Oracle is ready to create provider-ready notes (story 3.4). Scenario A: filled in with what
# the client mentioned, after "You mentioned you’re seeing your [specialty] on [date]. Shall I
# prepare the notes for that visit?". Scenario B "Yes": empty. "Not yet": the specialty the
# Oracle suggests, with "suggested": true. Every field is optional. `specialty` is a code from
# settings.provider_specialties; anything else is moved to "other" with the text as
# `specialty_other` (app/guidance/specialties.py). The app shows the card, then calls
# POST /conversations/{id}/provider-notes.
APPOINTMENT_CARD = "appointment_card"
# {"kind": "update_provider_notes"}: the client asked in the conversation for a change to their
# notes ("Can you add a question about my iron levels?"). The app calls
# POST /provider-notes/{id}/refresh for the notes the client means.
UPDATE_PROVIDER_NOTES = "update_provider_notes"
# {"kind": "provider_notes", "notes_id": "..."}: the card for a set of notes in the
# conversation, with its Edit appointment button. Added by the backend only; any the Oracle
# sends are dropped.
PROVIDER_NOTES = "provider_notes"
# Stories 3.1, 3.3 and 6.1 (6 Nov 19:22; app/health/). {"kind": "health_fact", "question_key":
#  "medications", "value": [{"name": "Metformin", "detail": "Blood sugar"}], "other": null}:
# something lasting the Oracle learned from the questioning, such as a symptom or a medicine.
# It's saved automatically, without asking (the client accepted the Health Consent; "Would you
# like me to add this to your health profile?" is gone). `question_key`, `value` and `other`
# follow app/health/questions.json and app/health/values.py; ProfileContext.health lists the
# questions and codes. Medicines, supplements and allergies (named lists) and symptoms
# (checklists) are added to what's saved, so send only what's new; any other answer replaces
# the saved one. Save only from the latest client message: something the client changed or
# removed in My Health is gone from `health.answered` on purpose, so don't save it again from
# older messages. The backend saves it with the reply, marked as added from the conversation
# (My Health shows "Added from our conversation on [date]"; the guidance summary lists it), and
# doesn't stream or keep the widget. One that doesn't fit the profile's questions, or changes
# nothing, is dropped. Saved during the free trial too. Not for a logged visit's changes, which
# the client confirms first (VisitReview.profile_updates, story 5.2).
HEALTH_FACT = "health_fact"

Answer = dict[str, Any]
"""What the client tapped in reply to a widget, sent with the message text (the label they
saw), for example {"value": "peri_menopausal"} or {"skipped": true}. Same agreement as
Widget."""


@dataclass(frozen=True)
class HealthAnswer:
    """One answered question of the profile's health profile (story 6.1) that applies to it
    now. Story 3.1's "Never repeat": the Oracle doesn't ask it again, and when the answer may
    be out of date it confirms it instead ("Last time you mentioned [answer]. Is that still
    right?"), saving the new one as a health_fact widget."""

    key: str  # the question's code (app/health/questions.json)
    section: str
    question: str  # worded for the profile ("Is Azka taking any medications?")
    answer: str  # the answer in words
    value: Any  # the stored value or codes, in the shape a health_fact widget sends
    other: str | None  # the write-in, with the choice that takes one
    sensitive: bool  # a sensitive question: never brought up unless it helps the concern
    from_conversation: bool  # saved from a health_fact, and not changed in My Health since
    updated_at: datetime


@dataclass(frozen=True)
class HealthQuestion:
    """A question that applies to the profile, isn't answered yet, and may be asked in
    conversation. The Oracle asks it as `when_asked` says (the Health Intake Routing document's
    Part 3), and saves the answer as a health_fact widget with these codes."""

    key: str
    section: str
    question: str  # worded for the profile
    # choice | multi_choice | checklist | text | number | scale | date | time | named_list |
    # history (app/health/values.py has each kind's value)
    kind: str
    choices: tuple[tuple[str, str], ...]  # (code, label), only those shown to the profile
    write_in_choice: str | None  # the choice whose write-in goes in `other`
    optional: bool
    sensitive: bool  # skippable, like every follow-up body question (3.1)
    # asked_first: the first time it's relevant to the concern; asked_later: only when it helps
    # the current concern; conversation: the follow-up body questions, after the privacy notice
    # ("Your body" first); onboarding: never asked by the Oracle.
    when_asked: str = "asked_later"


@dataclass(frozen=True)
class HealthContext:
    """The profile's health profile (story 6.1), as it is when the reply starts. Removed
    answers, and answers to questions that no longer apply, aren't in it, so the Oracle stops
    using them (6.1). Empty when the caller doesn't fill it in.

    The routing (routing document, Part 1) comes with it, so the Oracle words and orders the
    body questions. Health data, like everything else here."""

    answered: tuple[HealthAnswer, ...] = ()
    unanswered: tuple[HealthQuestion, ...] = ()
    # a: sex at birth Intersex or Prefer not to say; b: gender differs from sex at birth;
    # gender_prefer_not_to_say: "Your body", then the standard body questions; none: no
    # follow-up questions.
    follow_up_path: str = "none"
    # Which body questions apply: female (uterus or ovaries), male (testes or prostate),
    # intersex (both) or general (none known: general questions only, ask gently if needed).
    body_route: str = "general"
    organs: tuple[str, ...] = ()  # "Your body" codes, ticked or assumed from sex at birth
    body_from_your_body: bool = False  # False: "Your body" skipped, so sex at birth decides
    # Path B only: say this before the gender-affirming questions (decision 33).
    opening_line: str | None = None


@dataclass(frozen=True)
class ProfileContext:
    """What the Oracle knows about the profile before it asks anything (story 3.1, section 5).

    Each field is picked on purpose. The date of birth is only sent as an age group, and the
    advocate consent option is never sent. Visits and the Wellness Plan join this in Phases 6
    and 7. Under the age of majority, every reply is education only, with no products (3.1)."""

    is_self: bool  # False: a family member, and the client is their advocate
    first_name: str  # the profile's own first name
    advocate_first_name: str  # the account holder, who the Oracle is always speaking to
    relationship: str | None  # family members: parent | child | partner | someone_else
    age_group: AgeGroup
    sex_at_birth: str  # male | female | intersex | prefer_not_to_say
    # woman | man | non_binary | agender | not_listed | prefer_not_to_say (app/profiles/options.py)
    gender_identity: str
    gender_identity_other: str | None  # the write-in with not_listed
    pronouns: str | None  # he_him | she_her | they_them | other
    pronouns_other: str | None  # the write-in with other
    # Story 6.1's health profile: what's already answered (never asked again, story 3.1) and
    # what's still open. Filled in for replies; empty where the caller leaves it out.
    health: HealthContext = field(default_factory=HealthContext)
    # Stories 5.2 and 7.1: the profile's logged visits, newest first (a deleted log is never
    # here: the Oracle stops using it), and its Wellness Plan, which every new conversation
    # uses as context and follows up on. Empty where the caller leaves them out: fill them with
    # app.visits.service.oracle_visits and app.wellness.service.oracle_plan.
    visits: "tuple[LoggedVisit, ...]" = ()
    wellness_plan: "CurrentPlan | None" = None
    # Story 3.1's profile type "a teen with their own account" (1.5): the teen is talking for
    # themself, in private; first_name and advocate_first_name are both the teen's. Everything
    # is education only, with no product names, dosing or reading of their own lab results, and
    # never suggests the parent will see the conversation. A teen managed by a parent is
    # is_self false with age_group "teen" instead. Fill with the account's account_type.
    teen_own_account: bool = False


@dataclass(frozen=True)
class SafetyContext:
    """All the safety check gets about the profile. It runs on every message, before the
    Health Consent is accepted (story 3.2), so it gets nothing more."""

    is_self: bool
    age_group: AgeGroup


@dataclass(frozen=True)
class Turn:
    """One message, oldest first."""

    role: Role
    text: str
    widgets: list[Widget] = field(default_factory=list)  # Oracle turns
    answer: Answer | None = None  # client turns


@dataclass(frozen=True)
class EarlierConversation:
    """One of the profile's earlier conversations, so the Oracle doesn't ask again for what
    it was already told, and can follow up ("Any new medications since we last spoke?")."""

    topic: str | None
    last_message_at: datetime
    turns: list[Turn]  # its latest messages, oldest first


@dataclass(frozen=True)
class SafetyCheck:
    """Story 3.2. The level is judged on the whole message in context, never on single words:
    "I’m bleeding a lot, but I’m definitely not hemorrhaging" is not an emergency. The backend
    shows the story's fixed advice for the level and records an escalation; an emergency or a
    crisis pauses the conversation until the client picks an option."""

    level: SafetyLevel
    # Why, in one line, for the support team's review (Super Admin story 4.1). It's health data:
    # kept with the message (purged with it), never in the 6-year escalation record, never
    # shown to the client.
    reason: str | None = None
    # A poisoning or an overdose: the advice adds Poison Control's number (US only).
    poison_control: bool = False


# Phase 5: the guidance summary (story 3.3) and provider-ready notes (3.4). Rules for both:
#
# - Content comes only from Deborah's approved content and what the client shared. No
#   diagnosis, prescription, dosing or ordered tests, and no wording that implies a healthcare
#   licence (California AB 489). No Deborah name, photo or credentials anywhere.
# - Lab values the client typed are explained, never interpreted: say what each test measures
#   and what can affect it, never what the client's number means for them, whatever the age.
# - Products and links are for adults only (age_group "adult" or "60_plus"), never in the
#   explanation of tests or lab values. The backend drops them for anyone younger.
# - The backend writes the fixed texts itself (the introduction, the product note, the
#   disclosure box, the disclaimer, the notes' header and "What this is"), so they're not
#   part of what the Oracle returns. Every string returned is plain text, no markup.

SummaryStage = Literal["first_look", "full"]
RecommendationKind = Literal["genesis_product", "partner_product", "medicine", "test", "other"]


@dataclass(frozen=True)
class TestToDiscuss:
    """A test to raise with a provider (3.3's "Tests Worth Discussing"), for discussion only."""

    name: str
    # Why it matters. For a lab value the client typed: what the test measures and what can
    # affect it, never what the number means for them.
    why: str
    # A link Deborah has supplied for this test, shown as an information link (3.3). Nothing is
    # ordered through the app. Adults only, like other links; https only.
    url: str | None = None


@dataclass(frozen=True)
class ActionStep:
    """A practical step for "What You Can Do Now" (sleep, diet, the CALM practice)."""

    text: str
    # The Wellness Protocols library section it links to (story 7.1), instead of repeating the
    # protocol in full: a section key from app/wellness/protocols.json. The backend shows the
    # link only while that protocol is published in the knowledge base.
    protocol: str | None = None


@dataclass(frozen=True)
class Recommendation:
    """One product or link in 3.3's Recommendations section (adults only): Genesis Gold® on the
    Genesis Shopify store, Deborah's Fullscript store, Drugs.com for a medicine, a link to a
    test Deborah has supplied, or another recommended product. No prices. The URL is the
    store's own page with nothing about the client in it: no health information goes to
    Shopify or any partner. The backend drops one without a label or an https URL."""

    label: str  # e.g. "Genesis Gold®"
    url: str
    # genesis_product adds 3.3's product note ("Genesis Gold® contains no hormones...").
    kind: RecommendationKind
    why: str | None = None  # one line on why it's suggested
    # Genesis products only (Genesis Gold®, Sacred Seven®, Gen-Pro®): the basic directions
    # from the label, word for word from the knowledge base, never an amount worked out for
    # the client (e.g. "4 g per 50 lb of body weight, daily"). The backend shows it as "How to
    # take it (from the label): [directions]."
    label_directions: str | None = None


@dataclass(frozen=True)
class GuidanceSummary:
    """Story 3.3's guidance summary, one per conversation. Shared when the Oracle has enough
    context (the reply that introduces it carries a GUIDANCE_SUMMARY widget), or as a First
    Look when the client asks early. The backend shows the sections in the story's order and
    leaves out empty ones."""

    stage: SummaryStage  # first_look: what the Oracle can say so far
    what_im_hearing: str  # a short recap of the concern, symptoms and relevant history
    what_this_may_mean: str  # possible explanations, in plain educational language
    word_from_the_oracle: str  # a short, warm, encouraging note in the Oracle's voice
    # None when there's no clear link to the hypothalamus: the section is then left out.
    hypothalamic_connection: str | None = None
    questions_for_provider: list[str] = field(default_factory=list)
    tests_worth_discussing: list[TestToDiscuss] = field(default_factory=list)
    what_you_can_do_now: list[ActionStep] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)  # adults only
    # May include seeing a provider, but only when it's relevant.
    recommended_next_steps: list[str] = field(default_factory=list)
    # A provider visit is relevant: the app offers "Create notes for my provider".
    provider_visit_relevant: bool = False
    # First Look: what else the Oracle needs to know before the full summary.
    still_needed: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NotesSpecialty:
    """Who the notes are for (story 3.4's appointment card). The provider's name and the
    appointment date aren't sent: the backend puts them in the header, and only the type of
    provider shapes the notes."""

    code: str  # a code from settings.provider_specialties, or "other"
    name: str  # its label, or what the client wrote for "other" (e.g. "naturopath")
    # False: the client hasn't booked yet, and this is the Oracle's suggestion ("Not yet"), or
    # they skipped the card and the notes are for a primary care provider.
    booked: bool


NotesStatus = Literal["ready", "more_information", "unclear_specialty"]


@dataclass(frozen=True)
class ReportedLabValue:
    """A lab value exactly as the client typed it, listed with no interpretation (3.4)."""

    test: str
    value: str  # with its unit, as reported


@dataclass(frozen=True)
class RequestedLab:
    """3.4's "Labs I am requesting": written as the client's request, never as an order."""

    name: str
    reason: str  # a short reason
    primary: bool = True  # False: a test to also request


@dataclass(frozen=True)
class ProviderNotes:
    """Story 3.4's "For My Provider" notes, in the client's voice ("I am bringing this…"), in
    provider-facing clinical language, tailored to the specialty: the questions and tests are
    ones that provider can act on. Where that provider is unlikely to address part of the
    concern, or the client sees primary care first (an HMO, say), `referral` says which
    referral to ask for.

    The status says whether notes were written:
    - "ready": the sections are filled in;
    - "more_information": the Oracle needs a few more answers first; `question` is what it
      asks, and the backend adds it to the conversation;
    - "unclear_specialty": it can't tell what kind of provider an "other" specialty is; the
      backend asks 3.4's "Just to check, what kind of provider is [text]?..."."""

    status: NotesStatus = "ready"
    question: str | None = None
    chief_complaint: str = ""  # the main concern, how long, and key symptoms
    # What the Oracle identified, in plain clinical language: relevant history, medications and
    # the hypothalamic connection where there is one.
    clinical_context: str = ""
    reported_lab_values: list[ReportedLabValue] = field(default_factory=list)
    labs_requested: list[RequestedLab] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)  # tailored to the specialty
    # Current medications and supplements, from the conversation (and the health profile once
    # Phase 4 adds it to the context).
    medications: list[str] = field(default_factory=list)
    # The client takes or is starting Genesis Gold®: the backend adds 3.4's note (adults only).
    taking_genesis_gold: bool = False
    # Urgent signs found in the conversation. Empty: the backend writes "No urgent red flags
    # identified in this session."
    red_flags: list[str] = field(default_factory=list)
    recommendation: str = ""  # the suggested next steps from the guidance
    referral: str | None = None  # e.g. "You may need a referral to an endocrinologist for..."
    # The notes mention a Genesis product or an affiliate link: the backend adds the one
    # disclosure box. Never for teens or children, who get no products.
    mentions_products: bool = False


# Phases 6 and 7: logged provider visits (story 5.2) and the Wellness Plan (story 7.1). The
# Phase 5 rules above apply: Deborah's approved content and the client's own information only,
# no diagnosis, prescription or dosing (Genesis products follow the label's directions, word for
# word from the knowledge base, never a different dose), lab values explained and never
# interpreted, and products, dosing and cleanses for adults only. The backend drops products,
# product and cleanse protocols and the Foundational Nutraceuticals pillar for anyone under the
# age of majority, and writes the fixed texts itself (the story's notices, the disclaimer, the
# disclosure box, the pillars' library links).

LabStatus = Literal["pending", "drawn", "resulted"]
MedicineChangeKind = Literal[
    "new", "dose_increased", "dose_decreased", "discontinued", "continued", "added"
]
NextStepPriority = Literal["routine", "schedule", "urgent"]
# Adults only: their Genesis Gold® or Sacred Seven® status after the visit.
GenesisStatus = Literal["taking", "started", "stopped", "not_taking"]


@dataclass(frozen=True)
class VisitLab:
    """A lab from 5.2's "Labs ordered". `ordered` is false for a lab the notes requested that
    the provider didn't order."""

    name: str
    ordered: bool
    ordered_by: str | None = None
    status: LabStatus | None = None


@dataclass(frozen=True)
class MedicineChange:
    name: str
    change: MedicineChangeKind
    new_dose: str | None = None  # as the client wrote it; the Oracle never sets one


@dataclass(frozen=True)
class NextStep:
    text: str
    priority: NextStepPriority


@dataclass(frozen=True)
class LoggedVisit:
    """A provider visit as the client logged it (story 5.2's Provider Visit Summary). The
    provider's name and practice aren't sent: only the type of provider shapes the guidance."""

    visit_date: date
    reason: str  # why they went
    duration: str | None  # how long it's been going on
    specialty: str  # its label, or what the client wrote for "Other"
    follow_up_date: date | None
    diagnosis: str | None  # the diagnosis or impression they were given
    understanding: str | None  # their own understanding
    unaddressed_concerns: str | None
    labs: list[VisitLab] = field(default_factory=list)
    medicine_changes: list[MedicineChange] = field(default_factory=list)
    genesis_gold: GenesisStatus | None = None  # adults only
    sacred_seven: GenesisStatus | None = None  # adults only
    next_steps: list[NextStep] = field(default_factory=list)
    own_notes: str | None = None


@dataclass(frozen=True)
class MedicineLink:
    """A new medicine's Drugs.com page (5.2). The backend keeps only https links to drugs.com."""

    name: str
    url: str


@dataclass(frozen=True)
class MedicineInteraction:
    """5.2's "[Medicine] can interact with [existing medicine], so please check with your
    pharmacist or provider." The backend writes the sentence."""

    medicine: str
    existing_medicine: str


@dataclass(frozen=True)
class ProposedAnswer:
    """A change to the health profile the visit suggests, such as the medications list with a
    new medicine added or a discontinued one taken off. Shaped like a HEALTH_FACT widget: the
    backend saves it as a pending fact, so the client confirms it before the profile changes
    (5.2: "it asks before adding medicine changes to the health profile")."""

    question_key: str  # "medications" or "supplements"
    value: Any
    other: str | None = None


@dataclass(frozen=True)
class VisitReview:
    """Story 5.2's "What the Oracle does with the visit": the comparison with the
    provider-ready notes, and the medicines."""

    questions_answered: list[str] = field(default_factory=list)  # from the notes' questions
    labs_ordered: list[str] = field(default_factory=list)  # requested in the notes and ordered
    # Questions not answered, requested labs not ordered, concerns not addressed.
    missed: list[str] = field(default_factory=list)
    new_medicines: list[MedicineLink] = field(default_factory=list)
    interactions: list[MedicineInteraction] = field(default_factory=list)
    profile_updates: list[ProposedAnswer] = field(default_factory=list)


PlanTrigger = Literal["guidance_summary", "visit_logged", "visit_edited", "health_profile"]
PillarCode = Literal["nutraceuticals", "diet", "activity", "sleep", "mindset"]
# Story 7.1's safety notices; the backend shows each one's fixed text.
PlanNotice = Literal[
    "hyperthyroid_sacred_seven_first",  # hyperthyroidism: Sacred Seven® alone first
    # Asked how to take Gen-Pro®: the label's directions and its protocol link (the stored code
    # keeps its old name)
    "gen_pro_dose",
    "gender_affirming_hormones",  # on gender-affirming hormones
    "cleanse_not_suitable",  # a cleanse isn't right for them now (pregnancy, gallstones...)
]
FocusAreaRemoval = Literal["resolved", "course_finished"]


@dataclass(frozen=True)
class PlanFocusArea:
    """A focus area: one concern being worked on ("Sleep and night sweats").

    In CurrentPlan it's one the plan has, with its id. In PlanUpdate, `id` names the one to
    update or remove (`remove`, after the client confirmed the concern resolved or the course
    finished), and no id adds a new one at the top."""

    id: str | None = None
    title: str = ""
    recommendations: list[str] = field(default_factory=list)
    time_frame: str | None = None  # e.g. "for 2 to 4 weeks"
    # When its time frame ends: the backend schedules a check-in that day.
    follow_up_in_days: int | None = None
    remove: FocusAreaRemoval | None = None


@dataclass(frozen=True)
class PlanTodo:
    """A To Do item ("Ask your provider about a full thyroid panel"). In PlanUpdate, `id` names
    one to update, tick off (`done`: a visit or check-in confirmed it) or remove; no id adds
    one."""

    id: str | None = None
    text: str = ""
    # The Wellness Protocols library section it links to: a section key from
    # app/wellness/protocols.json, shown while that protocol is published in the knowledge base.
    protocol: str | None = None
    product: Recommendation | None = None  # adults only; a link, never a price
    due_in_days: int | None = None  # due then: the backend schedules a check-in that day
    done: bool = False
    remove: bool = False


@dataclass(frozen=True)
class HealthyFourTarget:
    """One of the DMAR® Healthy Four targets, worked out from lean body mass and weight."""

    name: str  # e.g. "Protein"
    target: str  # e.g. "90 g a day"


@dataclass(frozen=True)
class PlanPillar:
    """One of the Five Pillars' personal adjustments. They stay for the long term and change
    only when a recommendation is adjusted."""

    code: PillarCode
    adjustment: str | None = None
    # Foundational Nutraceuticals: Sacred Seven® is recommended too (its library link is shown).
    sacred_seven: bool = False
    # Diet: None while lean body mass isn't known (the pillar then asks for measurements).
    healthy_four: list[HealthyFourTarget] | None = None
    insulin_resistance_phase: str | None = None  # Diet: the current phase


@dataclass(frozen=True)
class CurrentPlan:
    """The profile's Wellness Plan as it is now, with its items' ids."""

    clinical_summary: str
    immediate_dietary_action: str | None
    focus_areas: list[PlanFocusArea]  # newest first
    todos: list[PlanTodo]  # with `done`
    pillars: list[PlanPillar]
    products: list[Recommendation]
    notices: list[PlanNotice]


@dataclass(frozen=True)
class PlanRequest:
    """What changed for the profile. Story 7.1: "It only looks at the new item, not everything
    saved before", so only the new item is sent, with the plan and the profile context (whose
    `health` holds the medicines to check new items against)."""

    trigger: PlanTrigger
    current: CurrentPlan | None  # None: create the plan (the profile's first full summary)
    summary: GuidanceSummary | None = None  # trigger guidance_summary
    visit: LoggedVisit | None = None  # triggers visit_logged and visit_edited
    # trigger health_profile: the change is in context.health; nothing else is sent.


@dataclass(frozen=True)
class PlanUpdate:
    """The changes to make. Story 7.1's placement rules: new information about something in the
    plan updates that item (by id) instead of adding it twice; a new concern is a new focus area
    at the top, and the others stay. Before adding anything, check it against the rest of the
    plan and the profile's medicines, so nothing conflicts.

    `changed` false: nothing to change. Every other field left as None (or an empty list)
    keeps what the plan has. Creating a plan needs `clinical_summary` and all five pillars."""

    changed: bool = True
    clinical_summary: str | None = None
    immediate_dietary_action: str | None = None
    focus_areas: list[PlanFocusArea] = field(default_factory=list)
    todos: list[PlanTodo] = field(default_factory=list)
    pillars: list[PlanPillar] = field(default_factory=list)  # only the ones that change
    products: list[Recommendation] | None = None  # adults only; the whole list
    notices: list[PlanNotice] | None = None  # the whole list
    # To Do ids a new prescription may not go well with: the backend shows 7.1's "Your new
    # prescription may not go well with item [X] in your plan...". The whole list.
    conflicts: list[str] | None = None


# Super Admin stories 6.1 to 6.3: the knowledge base (app/knowledge/). Its content is
# Deborah's public material, not health data, and only Published content reaches the Oracle.
# A knowledge gap's question is a client's own words, so it is health data like the rest.


@dataclass(frozen=True)
class KnowledgeDocument:
    """A published item of the knowledge base, for the AI team's store (chunks and
    embeddings). The Oracle answers only from what it has been given this way."""

    content_id: str  # stable across versions: a newer version replaces the older one
    version: int
    title: str
    # book | protocol | blog_post | qa_answer | symptom_chart | diagnostic_tree | case_study |
    # knowledge_gap_answer
    content_type: str
    text: str | None  # typed or pasted text
    # An uploaded PDF, Word (DOCX) or text file, for the AI team's extraction.
    file_name: str | None = None
    file_media_type: str | None = None
    file_data: bytes | None = None


@dataclass(frozen=True)
class KnowledgeGapCandidate:
    """An earlier knowledge gap that a new unanswered question may be the same as."""

    gap_id: str
    question: str
    topic: str | None


@dataclass(frozen=True)
class KnowledgeGapMatch:
    gap_id: str | None  # the candidate it's the same question as, or None for a new gap
    topic: str | None  # a short topic for the gap listing, e.g. "Sleep" or "Thyroid"


class OracleError(Exception):
    """Raised by the Oracle client for any failure, including a timeout. Its message must never
    contain anything from the request: the backend logs the class name only."""


class Oracle(Protocol):
    """The client enforces its own time limits and raises OracleError when one is passed. The
    backend can't stop a call that's blocked waiting, so these are required:

    - check_safety: 2 seconds (story 3.2);
    - stream_reply: 3 seconds to the first piece (story 3.1), 15 seconds between pieces, and
      the whole reply within settings.reply_timeout_seconds;
    - topic: 10 seconds."""

    def check_safety(self, context: SafetyContext, text: str) -> SafetyCheck:
        """Story 3.2: runs on every client message, before any reply and before the Health
        Consent."""
        ...

    def stream_reply(
        self,
        context: ProfileContext,
        history: list[Turn],
        earlier: list[EarlierConversation],
        *,
        conversation_id: str | None = None,
    ) -> Iterator[str | Widget]:
        """The reply to the last client turn: pieces of text in the order they're generated,
        and any widgets (dicts) for the apps to show with it. The text pieces, joined, are the
        reply's whole text.

        `conversation_id` is our conversation's id, for a service that keeps the thread's
        history itself (the clinician streaming chat API uses it as its thread id).
        It's an id, never health data.

        `context.health` is the health profile: never ask again for what's in `answered`
        (story 3.1's "Never repeat"), and save anything lasting (symptoms, medicines) as a
        HEALTH_FACT widget, without asking first (6 Nov 19:22).

        Story 3.1's guardrails: never a dose for a prescription medicine
        (PRESCRIPTION_DOSE_REFUSAL); medicines link to Drugs.com (MEDICINE_LINK); tests are
        TEST_LINKs Deborah supplied, never ordered (TEST_ORDER_REFUSAL); Genesis Gold®,
        Sacred Seven® and Gen-Pro® come with LABEL_DIRECTIONS from the knowledge base, word for
        word; product links (PRODUCT_LINK) wherever they're relevant. Products, test links and
        label directions are for adults only, and the backend adds the disclosure box. A
        question outside Deborah's content, or a request for a person, gets a SUPPORT_OFFER widget
        (story 10.1); the history then shows the backend's SUPPORT_REQUEST_SENT line once the
        client has sent it, so it isn't offered again.

        Never called while an emergency or crisis hold is open (story 3.2). The history then
        holds the backend's safety advice (an Oracle turn), anything typed during the hold, and
        the option the client picked (a client turn whose answer is {"safety_option": ...}).
        If the client says it wasn't an emergency, the reply apologises with 3.2's "I’m sorry,
        I misunderstood. Thank you for letting me know. Let’s carry on." """
        ...

    def topic(self, context: ProfileContext, history: list[Turn]) -> str:
        """A few words for the conversation list (story 3.1), written to follow "Last time we
        talked about", for example "waking at 3am". The apps capitalise it for the list."""
        ...

    def summarize(
        self,
        context: ProfileContext,
        history: list[Turn],
        previous: GuidanceSummary | None = None,
    ) -> GuidanceSummary:
        """Story 3.3: the conversation's guidance summary, within 10 seconds. `previous` is the
        summary already shared in this conversation, if any: update it with what the client
        has shared since, rather than writing a new one from scratch (Session 10).

        A family member's summary is written to the client as their advocate, with the
        member's name and pronouns, and shaped by their age group: teens get the full summary
        as education only (no products, no dosing), older adults age-adjusted guidance.
        Recommendations are for adults only; lab values are explained, never interpreted (see
        the rules above). Never called during an emergency or crisis hold (story 3.2)."""
        ...

    def provider_notes(
        self, context: ProfileContext, history: list[Turn], specialty: NotesSpecialty
    ) -> ProviderNotes:
        """Story 3.4: provider-ready notes from the conversation, for the specialty, within 10
        seconds. Called again when the specialty changes or the client asks for a change in
        the conversation; the history then includes what they asked.

        The context never has a date of birth or the provider's name: the backend writes the
        header (first name only, date of birth, specialty, provider, date). For a family
        member, the member is the patient and the client their medical advocate. Teens and
        children: education only, with no products, dosing or Genesis Gold®. Lab values are
        listed as reported, never interpreted. Never called during an emergency or crisis hold
        (story 3.2)."""
        ...

    def review_visit(
        self, context: ProfileContext, visit: LoggedVisit, notes: ProviderNotes | None
    ) -> VisitReview:
        """Story 5.2, after a visit is logged or edited, within 10 seconds. `notes` are the
        provider-ready notes the visit was for (None for a standalone visit): say which of
        their questions were answered, which requested labs were ordered, and what was missed.
        Link new medicines to Drugs.com, name possible interactions with the medicines in
        `context.health`, and propose the medicine changes as ProposedAnswers (never saved
        until the client confirms)."""
        ...

    def wellness_plan(self, context: ProfileContext, request: PlanRequest) -> PlanUpdate:
        """Story 7.1: creates the profile's Wellness Plan from its first full guidance summary,
        or updates it from one new item (a summary, a logged or edited visit, a health profile
        change), within 10 seconds. A visit adds the provider's next steps and tests to the To
        Do list and ticks off what's already done. A new prescription that may not go well with
        an item is flagged in `conflicts`. A lab value the client typed can only become a
        suggestion to discuss it with a provider, never an interpretation. Before Genesis Gold®,
        check for hyperthyroidism; cleanses only after the safety checks, with the Beet Test
        first. Teens and children: education only, with no products, dosing or cleanses."""
        ...

    def publish_knowledge(self, document: KnowledgeDocument) -> None:
        """Super Admin 6.1 and 6.2: the item's published version, new or changed, for the
        Oracle to use from now on in place of any earlier version of the same `content_id`.
        Called in the admin's request, before it's saved (no sync job since 6 Nov 19:22): an
        OracleError cancels the change and the admin tries again. Publishing the same version
        again is not an error. Should answer within a few seconds."""
        ...

    def withdraw_knowledge(self, content_id: str) -> None:
        """Super Admin 6.1: the item was archived (or isn't published); the Oracle stops using
        it. Withdrawing an item it doesn't have is not an error. Called in the admin's request,
        like publish_knowledge."""
        ...

    def match_knowledge_gap(
        self, question: str, candidates: list[KnowledgeGapCandidate]
    ) -> KnowledgeGapMatch:
        """Super Admin 6.3: a question the Oracle couldn't answer, which the client agreed to
        send to the team. Say which candidate it's the same question as (similar questions are
        grouped into one gap), or None, and give it a short topic. Within 10 seconds."""
        ...
