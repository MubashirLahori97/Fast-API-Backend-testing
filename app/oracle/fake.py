"""A stand-in Oracle with predictable answers, for development and tests."""

import copy
from collections.abc import Iterator

from app.oracle.contract import (
    HEALTH_FACT,
    LABEL_DIRECTIONS,
    MEDICINE_LINK,
    PRESCRIPTION_DOSE_REFUSAL,
    PRODUCT_LINK,
    SUPPORT_OFFER,
    TEST_LINK,
    TEST_ORDER_REFUSAL,
    ActionStep,
    EarlierConversation,
    GuidanceSummary,
    KnowledgeDocument,
    KnowledgeGapCandidate,
    KnowledgeGapMatch,
    LoggedVisit,
    MedicineLink,
    NotesSpecialty,
    OracleError,
    PlanFocusArea,
    PlanPillar,
    PlanRequest,
    PlanTodo,
    PlanUpdate,
    ProfileContext,
    ProviderNotes,
    Recommendation,
    ReportedLabValue,
    RequestedLab,
    SafetyCheck,
    SafetyContext,
    TestToDiscuss,
    Turn,
    VisitReview,
    Widget,
)

# Story 3.2 in development: a message containing one of these phrases (any case) gets that
# result from the fake safety check, so each level can be tried by hand. The real check is the
# AI team's classifier, which reads the whole message in context rather than looking for words.
SAFETY_TEST_PHRASES: tuple[tuple[str, SafetyCheck], ...] = (
    ("test poison", SafetyCheck(level="emergency", reason="Test", poison_control=True)),
    ("test emergency", SafetyCheck(level="emergency", reason="Test")),
    ("test crisis", SafetyCheck(level="crisis", reason="Test")),
    ("test urgent", SafetyCheck(level="urgent", reason="Test")),
)

# Stories 3.1, 6.1 and 10.1 in development: a reply to a client message containing one of
# these phrases (any case) ends with that widget, after `widgets`. "supplements" applies to
# every profile (app/health/questions.json), so the fact can be tried on any of them.
WIDGET_TEST_PHRASES: tuple[tuple[str, Widget], ...] = (
    (
        "test health fact",
        {
            "kind": HEALTH_FACT,
            "question_key": "supplements",
            "value": [{"name": "Magnesium glycinate", "detail": "Nightly, for sleep"}],
            "other": None,
        },
    ),
    ("test knowledge gap", {"kind": SUPPORT_OFFER, "request_kind": "knowledge_gap"}),
    ("test talk to someone", {"kind": SUPPORT_OFFER, "request_kind": "talk_to_support"}),
    # Story 3.1's links and label directions (6 Nov 19:22). A Genesis product brings the
    # disclosure box; a Drugs.com link or a plain test link doesn't.
    (
        "test genesis product",
        {
            "kind": PRODUCT_LINK,
            "label": "Gen-Pro®",
            "url": "https://shop.example.com/products/gen-pro",
            "product_type": "genesis",
        },
    ),
    (
        "test genesis product",
        {"kind": LABEL_DIRECTIONS, "product": "gen_pro", "directions": "2 pumps, twice daily"},
    ),
    (
        "test drugs link",
        {
            "kind": MEDICINE_LINK,
            "label": "Metformin",
            "url": "https://www.drugs.com/metformin.html",
        },
    ),
    (
        "test order test",
        {
            "kind": TEST_LINK,
            "label": "Full thyroid panel",
            "url": "https://tests.example.com/thyroid-panel",
            "affiliate": False,
        },
    ),
)

# Story 3.1's fixed lines: a client message containing one of these phrases (any case) gets
# that text as the reply instead of `reply`.
REPLY_TEST_PHRASES: tuple[tuple[str, str], ...] = (
    ("test prescription dose", PRESCRIPTION_DOSE_REFUSAL),
    ("test order test", TEST_ORDER_REFUSAL),
)

# Phase 5's canned outputs (stories 3.3 and 3.4). The product link is for adults only: the
# backend drops it for younger profiles.
FAKE_SUMMARY = GuidanceSummary(
    stage="full",
    what_im_hearing=(
        "You’ve been waking around 3am most nights for a few weeks, and feel tired in the day."
    ),
    hypothalamic_connection=(
        "The hypothalamus helps set your sleep and stress rhythms, so it can play a part here."
    ),
    what_this_may_mean=(
        "Waking at the same time each night is often linked to stress hormones, blood sugar or "
        "hormone changes. This is education, not a diagnosis."
    ),
    questions_for_provider=["Could my hormones be affecting my sleep?"],
    tests_worth_discussing=[
        TestToDiscuss(name="Morning cortisol", why="It shows how your stress rhythm is working.")
    ],
    what_you_can_do_now=[ActionStep(text="Try the CALM practice before bed.", protocol="calm")],
    recommendations=[
        Recommendation(
            label="Genesis Gold®",
            url="https://shop.example.com/products/genesis-gold",
            kind="genesis_product",
            why="Supports hypothalamic function.",
            label_directions="4 g per 50 lb of body weight, daily",
        )
    ],
    recommended_next_steps=["Keep a sleep diary for two weeks."],
    provider_visit_relevant=True,
    word_from_the_oracle="You’re doing the right thing by paying attention to this.",
)
FAKE_NOTES = ProviderNotes(
    chief_complaint="Waking at 3am most nights for about three weeks, with daytime tiredness.",
    clinical_context=(
        "Sleep-maintenance insomnia with possible stress-axis involvement. No known conditions."
    ),
    reported_lab_values=[ReportedLabValue(test="TSH", value="3.1 mIU/L")],
    labs_requested=[
        RequestedLab(name="Morning cortisol", reason="To look at my stress rhythm."),
        RequestedLab(
            name="Full thyroid panel", reason="To rule out thyroid causes.", primary=False
        ),
    ],
    questions=["Could my hormones be affecting my sleep?"],
    medications=["Magnesium glycinate, nightly"],
    red_flags=[],
    recommendation="Discuss a sleep and stress plan with my provider.",
)


class FakeOracle:
    """Answers every message the same way. Tests can change what it does:

    - `reply` and `widgets`: the reply's text, and widgets sent after it (then the widget of
      any of WIDGET_TEST_PHRASES in the client's last message);
    - `safety`: the result of every safety check, or `fail_safety = True` to make it fail
      (a message with one of SAFETY_TEST_PHRASES gets that phrase's result instead);
    - `fail_after`: pieces to send before the reply fails part-way.

    `calls` lists the methods called, in order, and `last_*` keep what the last call was given.
    """

    def __init__(self) -> None:
        self.reply = "Thank you for telling me. How long has this been going on?"
        self.widgets: list[Widget] = []
        self.safety = SafetyCheck(level="none")
        self.fail_safety = False
        self.fail_after: int | None = None
        self.calls: list[str] = []
        self.last_safety_context: SafetyContext | None = None
        self.last_context: ProfileContext | None = None
        self.last_history: list[Turn] = []
        self.last_earlier: list[EarlierConversation] = []

    def check_safety(self, context: SafetyContext, text: str) -> SafetyCheck:
        self.calls.append("check_safety")
        self.last_safety_context = context
        if self.fail_safety:
            raise OracleError("The fake safety check failed, as asked.")
        lowered = text.lower()
        for phrase, result in SAFETY_TEST_PHRASES:
            if phrase in lowered:
                return result
        return self.safety

    def stream_reply(
        self, context: ProfileContext, history: list[Turn], earlier: list[EarlierConversation]
    ) -> Iterator[str | Widget]:
        self.calls.append("stream_reply")
        self.last_context, self.last_history, self.last_earlier = context, history, earlier
        last = next((turn.text for turn in reversed(history) if turn.role == "client"), "")
        reply = next(
            (text for phrase, text in REPLY_TEST_PHRASES if phrase in last.lower()), self.reply
        )
        for sent, word in enumerate(reply.split(" ")):
            if self.fail_after is not None and sent == self.fail_after:
                raise OracleError("The fake Oracle stopped part-way, as asked.")
            yield word if sent == 0 else f" {word}"
        yield from self.widgets
        for phrase, widget in WIDGET_TEST_PHRASES:
            if phrase in last.lower():
                yield copy.deepcopy(widget)

    def topic(self, context: ProfileContext, history: list[Turn]) -> str:
        self.calls.append("topic")
        first = next(turn.text for turn in history if turn.role == "client")
        words = first.split()[:6]
        if words and words[0] != "I":
            words[0] = words[0].lower()
        return " ".join(words).rstrip(".?!,")

    # Phase 5 (stories 3.3 and 3.4). Tests can set `summary` or `notes` to what the next call
    # returns (FAKE_SUMMARY and FAKE_NOTES by default), or `fail_summary` / `fail_notes` to
    # make it fail. `last_previous` and `last_specialty` keep what the last call was given.
    summary: GuidanceSummary | None = None
    notes: ProviderNotes | None = None
    fail_summary = False
    fail_notes = False
    last_previous: GuidanceSummary | None = None
    last_specialty: NotesSpecialty | None = None

    def summarize(
        self,
        context: ProfileContext,
        history: list[Turn],
        previous: GuidanceSummary | None = None,
    ) -> GuidanceSummary:
        self.calls.append("summarize")
        self.last_context, self.last_history, self.last_previous = context, history, previous
        if self.fail_summary:
            raise OracleError("The fake summary failed, as asked.")
        return self.summary or FAKE_SUMMARY

    def provider_notes(
        self, context: ProfileContext, history: list[Turn], specialty: NotesSpecialty
    ) -> ProviderNotes:
        self.calls.append("provider_notes")
        self.last_context, self.last_history, self.last_specialty = context, history, specialty
        if self.fail_notes:
            raise OracleError("The fake notes failed, as asked.")
        return self.notes or FAKE_NOTES

    # Phases 6 and 7 (stories 5.2 and 7.1). Tests can set `visit_review` or `plan_update` to
    # what the next call returns (worked out from what it's given by default), or `fail_review`
    # / `fail_plan` to make it fail. `last_visit`, `last_visit_notes` and `last_plan_request`
    # keep what the last call was given.
    visit_review: VisitReview | None = None
    plan_update: PlanUpdate | None = None
    fail_review = False
    fail_plan = False
    last_visit: LoggedVisit | None = None
    last_visit_notes: ProviderNotes | None = None
    last_plan_request: PlanRequest | None = None

    def review_visit(
        self, context: ProfileContext, visit: LoggedVisit, notes: ProviderNotes | None
    ) -> VisitReview:
        self.calls.append("review_visit")
        self.last_context, self.last_visit, self.last_visit_notes = context, visit, notes
        if self.fail_review:
            raise OracleError("The fake visit review failed, as asked.")
        return self.visit_review or _fake_review(visit, notes)

    def wellness_plan(self, context: ProfileContext, request: PlanRequest) -> PlanUpdate:
        self.calls.append("wellness_plan")
        self.last_context, self.last_plan_request = context, request
        if self.fail_plan:
            raise OracleError("The fake Wellness Plan update failed, as asked.")
        return self.plan_update or _fake_plan_update(request)

    # The knowledge base (Super Admin 6.1 to 6.3). `knowledge` holds what was published, by
    # content id; `fail_knowledge` makes publishing and withdrawing fail. Knowledge gaps are
    # grouped only when the questions match apart from case, spaces and punctuation, and get
    # `gap_topic` as their topic (the real Oracle judges similarity and topics itself).
    fail_knowledge = False
    fail_gap_match = False
    gap_topic: str | None = None

    @property
    def knowledge(self) -> dict[str, KnowledgeDocument]:
        if "_knowledge" not in self.__dict__:
            self._knowledge: dict[str, KnowledgeDocument] = {}
        return self._knowledge

    def publish_knowledge(self, document: KnowledgeDocument) -> None:
        self.calls.append("publish_knowledge")
        if self.fail_knowledge:
            raise OracleError("The fake knowledge sync failed, as asked.")
        self.knowledge[document.content_id] = document

    def withdraw_knowledge(self, content_id: str) -> None:
        self.calls.append("withdraw_knowledge")
        if self.fail_knowledge:
            raise OracleError("The fake knowledge sync failed, as asked.")
        self.knowledge.pop(content_id, None)

    def match_knowledge_gap(
        self, question: str, candidates: list[KnowledgeGapCandidate]
    ) -> KnowledgeGapMatch:
        self.calls.append("match_knowledge_gap")
        if self.fail_gap_match:
            raise OracleError("The fake knowledge gap match failed, as asked.")
        wanted = _comparable(question)
        for candidate in candidates:
            if _comparable(candidate.question) == wanted:
                return KnowledgeGapMatch(gap_id=candidate.gap_id, topic=candidate.topic)
        return KnowledgeGapMatch(gap_id=None, topic=self.gap_topic)


def _comparable(question: str) -> str:
    """The question in lower case, with punctuation and extra spaces removed."""
    kept = "".join(char if char.isalnum() else " " for char in question.casefold())
    return " ".join(kept.split())


# Phases 6 and 7's worked-out answers: simple rules over what the call is given, so trying the
# app by hand shows a plan that follows the summaries and visits.
FAKE_PILLARS = [
    PlanPillar(code="nutraceuticals", adjustment="Genesis Gold® daily, with breakfast."),
    PlanPillar(code="diet", adjustment="Start with phase 1 of the Insulin Resistance Diet."),
    PlanPillar(code="activity", adjustment="The standard HIIT routine, three times a week."),
    PlanPillar(code="sleep", adjustment="Aim to be in bed by 10:30pm."),
    PlanPillar(code="mindset", adjustment="Start with a daily five-minute CALM practice."),
]


def _fake_review(visit: LoggedVisit, notes: ProviderNotes | None) -> VisitReview:
    ordered = [lab.name for lab in visit.labs if lab.ordered]
    requested = [lab.name for lab in notes.labs_requested] if notes else []
    return VisitReview(
        questions_answered=list(notes.questions[:1]) if notes else [],
        labs_ordered=[name for name in requested if name in ordered],
        missed=[f"{name} wasn’t ordered" for name in requested if name not in ordered],
        new_medicines=[
            MedicineLink(name=change.name, url="https://www.drugs.com/search.php")
            for change in visit.medicine_changes
            if change.change in ("new", "added")
        ],
    )


def _fake_plan_update(request: PlanRequest) -> PlanUpdate:
    if request.summary is not None:
        summary = request.summary
        todos = [
            PlanTodo(text=f"Ask your provider about a {test.name.lower()} test")
            for test in summary.tests_worth_discussing
        ]
        todos += [
            PlanTodo(text=step.text, protocol=step.protocol, due_in_days=14)
            for step in summary.what_you_can_do_now
        ]
        focus = PlanFocusArea(
            title="What we’re working on",
            recommendations=[step.text for step in summary.what_you_can_do_now],
            time_frame="for 2 to 4 weeks",
            follow_up_in_days=14,
        )
        if request.current is not None:
            return PlanUpdate(focus_areas=[focus], todos=todos)
        return PlanUpdate(
            clinical_summary=summary.what_this_may_mean,
            immediate_dietary_action="Have a protein-rich breakfast within an hour of waking.",
            focus_areas=[focus],
            todos=todos,
            pillars=FAKE_PILLARS,
            products=list(summary.recommendations),
        )
    if request.visit is not None and request.current is not None:
        ordered = [lab.name for lab in request.visit.labs if lab.ordered]
        done = [
            PlanTodo(id=todo.id, text=todo.text, done=True)
            for todo in request.current.todos
            if not todo.done and any(name.lower() in todo.text.lower() for name in ordered)
        ]
        added = [PlanTodo(text=f"Get your {name} done") for name in ordered]
        added += [PlanTodo(text=step.text) for step in request.visit.next_steps]
        return PlanUpdate(todos=[*done, *added])
    return PlanUpdate(changed=False)
