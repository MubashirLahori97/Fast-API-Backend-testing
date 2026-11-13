# Your Oracle Clinician — Intake Form Specification

For development team · Genesis Health Products Inc. · v1.2 Oct 2026 — Gender & Sex Variations intake added

Profile Type Routing

The account holder is always an adult (18+). They may create dependent sub-profiles for family members. Profile type determines which health intake form is presented. The routing decision happens immediately after sign-up.

Account created (adult 18+) ↓ Is this profile for you or a family member? ↓ FOR SELF → Health Profile: sex at birth → gender ID → age → route to Adult F or Adult M FOR DEPENDENT → Enter dependent's name + DOB ↓ Age of dependent? ↓ Under 13 → Pediatric intake (filled by parent) 13–17 → Adolescent intake 18+ → Adult intake (F or M path) with proxy flag

**Teenagers (13–17) as primary account holders:** A teen may create their own account directly. They follow the Adolescent intake path. Legal acknowledgment language appears on sign-up (no hard gate, no parental consent requirement, but terms note that users under 18 are using the service with awareness of their age). Content and recommendations adapt to developmental context.

Where Fields Live

| Layer | Purpose | When collected | Mandatory? |
| --- | --- | --- | --- |
| Sign-Up | Account identity, legal, basic analytics | First visit, once | Most required |
| Health Profile | Persistent clinical context for all interactions | Immediately after sign-up; editable anytime | Core fields required |
| Consult Context | Session-specific chief complaint and history | Each new conversation or consultation | Chief complaint required |
| Bot (dynamic) | Clarifying questions the agent asks mid-session | During conversation, driven by AI | N/A — agent-controlled |

Badge Legend

REQUIRED — must be completed to proceed OPTIONAL — can be skipped, improves experience CONDITIONAL — shown only if prior answer triggers it SYSTEM — auto-populated, not user-entered NEW v1.1 / v1.2 — added in a recent version

Key Design Principles from Deborah

- **Decision tree logic throughout:** answers must branch correctly. If male at birth, menstruation questions do not appear. If post-menopausal, cycle questions stop. Trans man may still have periods — gender ID field is how the system knows to ask.
- **No repeated fields:** if medications were entered in the health profile, the consult screen does not ask again. Surface them as a pre-populated review, not a re-entry.
- **Narrative-aware:** the bot handles open narrative input, not just checkbox answers. The health profile uses structured fields; the bot conversation can receive free text.
- **Knowledge base is live:** new articles are authored continuously. The ingestion pipeline must support ongoing sync, not one-time upload.
- **Pronouns:** sex at birth + gender identification together determine pronoun use (he/she/they) throughout the app interface and any generated summaries.
- **Proxy sessions:** when asking about a dependent family member, the Oracle's response mode, escalation thresholds, and recommendation language all adapt to the proxy pathway. See Dependent & Proxy tab.

Sign-Up Fields

Keep sign-up minimal. The goal is to get the client into the system. Clinical detail belongs in the health profile, which is a mandatory next step.

| Field | Type | Status | Notes |
| --- | --- | --- | --- |
| First name | Text | REQUIRED |  |
| Last name | Text | REQUIRED |  |
| Email address | Email | REQUIRED | Used for login and communications |
| Password | Password | REQUIRED | Min 8 chars, 1 uppercase, 1 number |
| Country / region | Dropdown | OPTIONAL | Analytics only — adoption by region, product availability flags. |
| How did you hear about us? | Dropdown + text | OPTIONAL | Referral source analytics |
| Existing Genesis Gold customer? | Yes / No | OPTIONAL | Routes to tailored onboarding copy if Yes |
| Social login (Google / Facebook) | OAuth | OPTIONAL | Low priority; assess technical implications before building. |
| Accept Terms & Privacy Policy | Checkbox | REQUIRED | Single checkbox. Re-prompts only on T&C change or session cache reset. |

**Not at sign-up:** Date of birth, gender, age — all belong in the health profile where they can be used clinically. Sign-up has no age restriction; legal language in T&C acknowledges under-18 users.

Freemium Launch Model

| Tier | Access | Gate |
| --- | --- | --- |
| Free (launch period) | First 3 questions | No card required. After 3rd response, interface grays out with subscription prompt. |
| Subscriber | Full access | Subscription via Stripe. Tiered pricing TBD. |
| Free trial (future promo) | First 3 questions | Same mechanic — reuse for relaunch campaigns without rebuilding. |

**Payment integration:** Stripe (existing account). Products connect via Shopify. App subscriptions through Stripe directly.

Routing Into This Profile

1

**Sex at birth?**

Female→ continue this path · Male→ Adult Male profile · Intersex→ continue this path, note in profile

2

**Gender identification?**

Male / Female / Non-binary / \[text field\] — sets pronouns app-wide (he/she/they)

3

**Reproductive status** (determines menstrual / hormonal question branching)

Pre-menopausal · Peri-menopausal · Post-menopausal (natural) · Surgically menopausal (hysterectomy ± oophorectomy) · Pregnant / postpartum

4

**If peri- or post-menopausal (natural or surgical):** Currently on hormone replacement therapy (HRT)?

Yes→ show HRT detail fields · No→ skip · Previously, not now→ show prior HRT fields

**N/A logic:** Menstrual cycle questions are N/A for post-menopausal, surgically menopausal, and trans female clients. The system suppresses those fields automatically based on reproductive status + gender identification — but always displays the symptom checklist in full with an N/A option per item, since menopausal symptoms apply across all these groups.

Core Health Profile Fields

Identity & Basics

| Field | Type | Status | Notes |
| --- | --- | --- | --- |
| Date of birth | Date | REQUIRED | Age used for developmental context |
| Sex at birth | Select | REQUIRED | Female / Male / Intersex |
| Gender identification | Select + text | REQUIRED | Female / Male / Non-binary / \[write in\]. Sets pronouns throughout app. |
| Reproductive status | Select | REQUIRED | Drives branching for all hormonal questions |

Menopause & HRT Detail — shown if reproductive status is peri-, post-, or surgically menopausal

| Field | Type | Status | Notes |
| --- | --- | --- | --- |
| Age at last period (natural menopause) | Number | CONDITIONAL | Shown if post-menopausal (natural) |
| Hysterectomy? | Yes / No | CONDITIONAL | Shown if surgically menopausal |
| If yes: ovaries removed (oophorectomy)? | Yes / No / Partial | CONDITIONAL | Drives severity context — surgical menopause without oophorectomy differs clinically |
| Age at surgery | Number | CONDITIONAL |  |
| Currently on HRT? | Yes / No / Previously | REQUIRED | Shown for all peri/post/surgical; drives HRT detail block |
| HRT type (if current or prior) | Select + text | CONDITIONAL | Estrogen only / Progesterone only / Combined E+P / Testosterone / Bio-identical / Synthetic / \[write in\] |
| HRT delivery method | Select | CONDITIONAL | Pill / patch / cream / gel / pellet / injection / other |
| How long on HRT? | Text (e.g. "3 years") | CONDITIONAL |  |
| How has HRT helped / not helped? | Text | CONDITIONAL | Rich context for bot recommendations |
| Why did you stop HRT? | Text | CONDITIONAL | Shown if previously on HRT, not currently |

Reproductive History — shown if reproductive status is not "surgically menopausal" or "post-menopausal (natural)"

| Field | Type | Status |
| --- | --- | --- |
| Age at first period (menarche) | Number | CONDITIONAL |
| Are periods regular? | Yes / No | CONDITIONAL |
| Cycle frequency (days) | Number | CONDITIONAL |
| Days of bleeding | Number | CONDITIONAL |
| Pads/tampons on heaviest day | Number | CONDITIONAL |
| Contraceptive method | Select + text | OPTIONAL |
| Number of pregnancies / live births / miscarriages / terminations | Number × 4 | OPTIONAL |
| Postpartum depression history? | Yes / No | CONDITIONAL |
| Mother took DES during pregnancy with you? | Yes / No / Don't know | OPTIONAL |
| Age mother reached menopause | Number | OPTIONAL |

**Trans male clients** who identify as male but were born female may still have periods. The gender identification field is what allows the system to ask appropriately — do not suppress reproductive questions solely based on gender ID when sex at birth is female.

Current Medications & Hormonal Treatments

| Field | Type | Status |
| --- | --- | --- |
| Medications (Rx and OTC) | Repeating: name + reason | REQUIRED |
| Supplements | Repeating: name + reason | REQUIRED |
| Taking Genesis Gold? | Yes / No | OPTIONAL |
| If yes: how long? How has it helped? | Text | CONDITIONAL |
| Previous hormonal treatment | Text: when + results | OPTIONAL |
| Known allergies (food, inhalants, medications) | Text | OPTIONAL |

Lifestyle

| Field | Type | Status |
| --- | --- | --- |
| Average nightly sleep (hours) | Number | REQUIRED |
| Sleep quality notes | Text | OPTIONAL |
| Exercise: type, duration, frequency | Text | OPTIONAL |
| Special diet / food sensitivities | Text | OPTIONAL |
| Daily food intake | Text (breakfast / lunch / dinner / fluids) | OPTIONAL |
| Work schedule / stress level | Text + 1–10 scale | OPTIONAL |
| Supportive partner / family / friends | Yes / No × 3 | OPTIONAL |

Symptom Checklist — Female Hormonal

Client checks all that apply. Each symptom has three response options: **Yes** · **No** · **N/A** — the N/A option is essential for post-menopausal, surgically menopausal, and trans female clients for whom certain symptoms are anatomically inapplicable. Severity scale 1–10 shown inline for pain/intensity items. All checked items feed directly into the bot's initial context.

| Symptom | Response | N/A applies to |
| --- | --- | --- |
| Hot flashes | Yes / No / N/A | — |
| Night sweats | Yes / No / N/A | — |
| Brain fog / mental fogginess | Yes / No / N/A | — |
| Forgetfulness / memory issues | Yes / No / N/A | — |
| Mood swings | Yes / No / N/A | — |
| Irritability | Yes / No / N/A | — |
| Depression | Yes / No / N/A | — |
| Rage / anger outbursts | Yes / No / N/A | — |
| Vaginal dryness | Yes / No / N/A | Trans female (pre-op); mark N/A |
| Poor lubrication with intercourse | Yes / No / N/A | Trans female (pre-op); mark N/A |
| Frequent urination / urgency | Yes / No / N/A | — |
| Low libido / diminished sex drive | Yes / No / N/A | — |
| Clamminess | Yes / No / N/A | — |
| Fatigue — general | Yes / No / N/A | — |
| Insomnia / sleep disturbance | Yes / No / N/A | — |
| Muscle weakness | Yes / No / N/A | — |
| Change in body fat patterns | Yes / No / N/A | — |
| Lower exercise tolerance | Yes / No / N/A | — |
| Decreased stress tolerance | Yes / No / N/A | — |
| Increased susceptibility to illness | Yes / No / N/A | — |
| Menstrual cramps (rate 1–10) | Severity / N/A | Post-menopausal, surgical, trans female |

**N/A suppression logic:** When reproductive status = post-menopausal or surgically menopausal, OR gender identification = trans female, the system should *pre-set* anatomically inapplicable items to N/A rather than hiding them — the client can override if clinically relevant. Menstrual cramps default to N/A for all menopausal and hysterectomy statuses.

Family & Personal Medical History

Client checks all that apply for self and for family. Both columns feed the bot's risk context.

| Condition | Self | Family |
| --- | --- | --- |
| Heart problems / high blood pressure / poor circulation | ☐ | ☐ |
| Lung problems / asthma | ☐ | ☐ |
| Liver / gallbladder | ☐ | ☐ |
| Cancer | ☐ | ☐ |
| Stomach or intestines | ☐ | ☐ |
| Kidney / bladder | ☐ | ☐ |
| Significant injuries | ☐ | ☐ |
| Skeleton / fractures / arthritis / osteoporosis | ☐ | ☐ |
| Reproductive system / hormonal problems | ☐ | ☐ |
| Psychological illness / developmental disorders | ☐ | ☐ |
| Thyroid disease / diabetes | ☐ | ☐ |
| Neurological / headaches | ☐ | ☐ |
| Hospitalizations or surgeries | ☐ | ☐ |
| Other significant illness / chronic disease | ☐ | ☐ |
| Endometriosis / fibroid uterus | ☐ | ☐ |
| Fibrocystic breast condition | ☐ | ☐ |
| Osteoporosis | ☐ | ☐ |
| Alzheimer's disease | ☐ | ☐ |
| Early menopause | ☐ | ☐ |

Each checked item reveals a short text field for elaboration.

Routing Into This Profile

1

**Sex at birth = Male** (routed here from Health Profile step 1)

2

**Gender identification?**

Male / Female / Non-binary / \[text\] — sets pronouns app-wide

3

**Fertility / reproductive concerns?** Yes / No

Yes→ show fertility fields · No→ skip

Core Health Profile Fields

Identity & Basics

| Field | Type | Status | Notes |
| --- | --- | --- | --- |
| Date of birth | Date | REQUIRED |  |
| Sex at birth | Select | REQUIRED | Pre-selected from routing; confirm |
| Gender identification | Select + text | REQUIRED | Sets pronouns app-wide |
| Age at puberty | Number | OPTIONAL | Context for developmental timeline |
| Age stopped growing | Number | OPTIONAL |  |

Reproductive (shown if fertility concern = Yes)

| Field | Type | Status |
| --- | --- | --- |
| Has children? | Yes / No → how many, ages | CONDITIONAL |
| Fertility problems? | Yes / No → male or female factor | CONDITIONAL |
| Contraceptive method | Select + text | OPTIONAL |
| Monthly self-examination of testicles? | Yes / No | OPTIONAL |

Current Medications & Supplements

| Field | Type | Status |
| --- | --- | --- |
| Medications (Rx and OTC) | Repeating: name + reason | REQUIRED |
| Supplements | Repeating: name + reason | REQUIRED |
| Taking Genesis Gold? | Yes / No | OPTIONAL |
| If yes: how long? How has it helped? | Text | CONDITIONAL |
| Known allergies | Text | OPTIONAL |

Lifestyle

| Field | Type | Status |
| --- | --- | --- |
| Wake time / sleep time | Time × 2 | OPTIONAL |
| Average nightly sleep (hours) | Number | REQUIRED |
| Exercise: type, duration, frequency | Text | OPTIONAL |
| Diet / daily food intake | Text | OPTIONAL |
| Work schedule / stress level | Text + 1–10 scale | OPTIONAL |
| Supportive partner / family / friends | Yes / No × 3 | OPTIONAL |

Symptom Checklist — Male Hormonal

- Hot flashes
- Night sweats
- Mood swings
- Irritability
- Depression
- Rage
- Mental fogginess
- Forgetfulness
- Clamminess
- Change in body fat patterns
- Muscle weakness
- Fatigue — general
- Lower exercise tolerance
- Increased susceptibility to illness
- Decreased stress tolerance
- Insomnia
- Diminished sex drive
- Decrease in morning erections
- Reduced erectile firmness

Family & Personal Medical History

Same two-column (self / family) checklist as Adult Female. Conditions list is identical. Each checked item reveals a short text field.

The male profile omits reproductive-system-specific female conditions (endometriosis, fibrocystic breast, early menopause) from the history checklist.

Who Fills This Form

Adolescents aged 13–17 who create their own account, or a dependent profile created by an adult for a teenager. The form is labeled as confidential and age-appropriate. Stars can be placed by anything the teen is concerned about.

**Legal note:** Terms of service acknowledge under-18 use. No hard parental consent gate, but T&C language should state that users under 18 are aware their parent/guardian may be informed in certain circumstances (to be drafted by legal counsel).

Profile Fields

Household Context

| Field | Type | Status |
| --- | --- | --- |
| Date of birth | Date | REQUIRED |
| Sex at birth | Select | REQUIRED |
| Gender identification | Select + text | OPTIONAL |
| Parent / guardian names | Text | OPTIONAL |
| Siblings (names & ages) | Text | OPTIONAL |
| Adults in home & relationship | Text | OPTIONAL |
| Pets in home | Text | OPTIONAL |

Medications, Supplements & Allergies

| Field | Type | Status |
| --- | --- | --- |
| Medications (Rx) | Repeating: name | REQUIRED |
| Vitamins | Text | OPTIONAL |
| Natural supplements | Text | OPTIONAL |
| Allergies | Text | OPTIONAL |

Sleep & Nutrition

| Field | Type | Status |
| --- | --- | --- |
| Bedtime / fall asleep / wake time | Time × 3 | OPTIONAL |
| Breakfast / lunch / dinner / snacks | Text | OPTIONAL |
| Daily fluid intake (oz): water / milk / juice / soda / coffee-tea / alcohol | Number × 6 | OPTIONAL |

Development & Activity

| Field | Type | Status |
| --- | --- | --- |
| Age at puberty onset | Number | OPTIONAL |
| First period (females) | Date | CONDITIONAL |
| Last period (females) | Date | CONDITIONAL |
| Concerns about development? | Text | OPTIONAL |
| Sports / extracurricular activities | Text | OPTIONAL |
| School performance / GPA | Text / Number | OPTIONAL |

Social & Safety

| Field | Type | Status |
| --- | --- | --- |
| Trustworthy friends? | Yes / No | OPTIONAL |
| Trusted adults in life? | Yes / No | OPTIONAL |
| Concerned about recreational drugs? | Yes / No | OPTIONAL |
| Exposed to tobacco smoke? | Yes / No | OPTIONAL |
| Exercises / takes PE? | Yes / No | OPTIONAL |
| Concerned about weight? | Yes / No | OPTIONAL |
| Accidents (broken bones, sutures)? | Yes / No → text | OPTIONAL |
| Always wears seatbelt? | Yes / No | OPTIONAL |
| Rides with intoxicated drivers? | Yes / No | OPTIONAL |
| Wears bicycle helmet? | Yes / No | OPTIONAL |
| Drives? Drinks and drives? | Yes / No → Yes / No | CONDITIONAL |
| Concerns about sexuality or sexual activity? | Yes / No → text (confidential) | OPTIONAL |
| If sexually active: uses contraception? | Yes / No | CONDITIONAL |

Family Medical History

Same checklist as adult forms (heart, lung, thyroid/diabetes, liver, stomach, kidney, neurological, injuries, hospitalizations, skeleton, reproductive, cancer, other, psychological). Each checked item reveals text field.

Who Fills This Form

Children under 13. Always a dependent profile created and managed by an adult account holder (parent or guardian). The parent fills the form on behalf of the child.

Profile Fields

Child Identity & Household

| Field | Type | Status |
| --- | --- | --- |
| Child's date of birth | Date | REQUIRED |
| Parent / guardian names | Text | REQUIRED |
| Siblings (names & ages) | Text | OPTIONAL |
| Adults in home & relationship | Text | OPTIONAL |
| Pets in home | Text | OPTIONAL |

Birth & Developmental History

| Field | Type | Status |
| --- | --- | --- |
| Birth weight | Text | OPTIONAL |
| Problems in pregnancy or at birth | Text | OPTIONAL |
| Breast or bottle fed? Age weaned | Select + number | OPTIONAL |
| Age same-sex parent reached puberty | Number | OPTIONAL |
| Age same-sex parent reached adult height | Number | OPTIONAL |
| Developmental milestones: crawled / walked / spoke / potty trained / slept through night | Age (number) × 5 | OPTIONAL |
| List of accidents by date | Text | OPTIONAL |
| Significant illnesses | Text | OPTIONAL |

Sleep & Nutrition

| Field | Type | Status |
| --- | --- | --- |
| Bedtime / wake time | Time × 2 | OPTIONAL |
| Sleep quality | Good / Poor | OPTIONAL |
| Appetite | Good / Poor | OPTIONAL |
| Breakfast / lunch / dinner / snack | Text | OPTIONAL |
| Daily fluid intake (oz): water / milk / juice / soda / other | Number × 5 | OPTIONAL |
| Recent weight loss or gain | Text | OPTIONAL |

Medications & Allergies

| Field | Type | Status |
| --- | --- | --- |
| Medications (Rx, OTC, herbs, supplements) | Text | OPTIONAL |
| Allergies | Text | OPTIONAL |

School, Activity & Safety

| Field | Type | Status |
| --- | --- | --- |
| How is child doing in school? | Text | OPTIONAL |
| Extracurricular activities? | Text | OPTIONAL |
| Peer relationships | Text | OPTIONAL |
| Family relationships | Text | OPTIONAL |
| Exposed to tobacco smoke? | Yes / No | OPTIONAL |
| Always wears seatbelt? | Yes / No | OPTIONAL |
| Always wears helmet (bike / skate / scooter)? | Yes / No | OPTIONAL |
| Safety concerns at home / school / other | Yes / No × 3 → text | OPTIONAL |

Recent Exams

| Exam | Any problems? | Date of last exam |
| --- | --- | --- |
| Vision | Yes / No | Date |
| Hearing | Yes / No | Date |
| Dental | Yes / No | Date |
| Immunizations up to date? | Yes / No → list immunizations needed |  |

Family Medical History

Same two-column checklist as adult forms. Parent checks for child and family history.

**New in v1.1 — October 2026.** This section was added following the Tkxel sprint meeting in which the dependent-user flow was flagged as a critical design decision. It documents the four-pathway intake flag, pathway-specific response modes, and escalation logic for proxy/dependent sessions.

Why This Matters

Many users will ask the Oracle not about themselves but about a family member — their child, an aging parent, a partner. Each proxy scenario requires a different response mode, a different set of clinical assumptions, and different escalation thresholds. Getting this wrong could mean giving adult-calibrated advice for a pediatric case, or missing a same-day-care emergency in an elderly patient with a lowered fever response.

The Intake Flag Question

Displayed at the start of every new session (after health profile, before consult context). The selected pathway is stored on the session object and governs all response logic for that conversation.

Who are you asking about today? ↓ \[ A \] Myself → Self pathway — standard response mode \[ B \] My child → Pediatric proxy pathway — parent fills all fields; all recommendations go to parent; age-appropriate language throughout \[ C \] My elderly parent or family member → Elderly proxy pathway — adult child or caregiver as reporter; lower escalation threshold; dementia/cognitive changes tracked as red flags \[ D \] My partner or another adult → Partner/general pathway — general health information only; no direct recommendations; explicit disclaimer that Oracle cannot assess third parties

Pathway Details

Pathway A — Self

#### Standard

Default mode. Intake data comes from the user's own health profile. Oracle addresses user directly in second person ("you," their pronoun). All recommendation tiers available.

- Full symptom checklist active
- Personalized lab recommendations
- Direct lifestyle guidance
- Escalation thresholds: adult standard

Pathway B — Pediatric Proxy

#### Parent asking for child

All responses directed to parent. Oracle addresses child in third person ("your son," "your daughter," "your child"). Pediatric health profile must be on the account.

- Age-appropriate clinical context enforced
- Developmental norms applied automatically
- No direct advice to the child
- Escalation: lower threshold — children deteriorate faster
- Red flags: growth delays, behavioral changes, sleep regression

Pathway C — Elderly Proxy

#### Adult child / caregiver asking for aging parent

Reporter is a proxy (adult child, caregiver). Oracle recognizes that all symptom reports are second-hand. Elderly patients may not accurately report or may under-report symptoms.

- Lowest escalation threshold of all pathways
- Any acute change + confusion = sepsis screen
- New incontinence in elderly = UTI until proven otherwise
- Worsening dementia over days = red flag, not progression
- Responses coach the proxy on what to watch, ask, and document
- Oracle explicitly notes limitations of proxy reporting

Pathway D — Partner / Other Adult

#### General information only

Oracle cannot assess a third-party adult who has not consented to the service. Responses are general health information only — no personalized recommendations.

- No profile loaded for the third party
- Oracle says: "I can share general information, but your partner would need their own account for personalized guidance"
- Escalation: user is prompted to encourage the other person to seek care directly
- No recommendations that could be acted on as if from a clinician

Escalation Logic by Pathway

Escalation thresholds differ significantly by pathway. The table below shows how the same symptom cluster would be handled differently depending on who is being described.

Escalation bands

**Self-manage:** lifestyle and supplement guidance; no urgency signal

**Schedule an appointment:** recommend provider visit within 1–2 weeks

**See someone soon:** recommend provider within 24–48 hours; may flag labs to order first

**Seek care today / call 911:** same-day care trigger; in severe cases: emergency services

| Symptom Pattern | Self (A) | Child (B) | Elderly (C) | Partner (D) |
| --- | --- | --- | --- | --- |
| Fatigue + brain fog, no other red flags | Self-manage | Schedule soon | See provider 24–48h | General info only |
| New urinary incontinence (acute onset) | Schedule appt | See provider today | Seek care today — UTI/sepsis screen | General info only |
| Acute confusion + fever | See provider today | ER or urgent care now | Call 911 / ER now | Encourage ER immediately |
| Worsening cognitive symptoms over days | Schedule appt | Pediatric neurology referral | Seek care today — rule out UTI, stroke, medication | General info only |
| Irregular periods + mood changes | Self-manage + lab work | Pediatric endo referral | N/A — post-menopausal | General info only |

**Elderly UTI / Sepsis Protocol (Pathway C):** In elderly patients — especially women — a urinary tract infection may present without classic symptoms (dysuria, burning). New or worsening confusion, increased falls, acute incontinence, or a subtle change in baseline behavior may be the *only* presentation. The Oracle must trigger a same-day care recommendation any time a Pathway C (elderly proxy) session includes: new incontinence, acute-onset confusion, behavioral change over 24–72 hours, or reports of "just not herself." These presentations can progress to urosepsis within hours. The Oracle explicitly names this risk to the caregiver and coaches them on what to tell the triage nurse.

Proxy Profile Requirements

| Pathway | Profile needed? | Who fills it? | Notes |
| --- | --- | --- | --- |
| A — Self | Yes — own health profile | User | Standard flow |
| B — Child proxy | Yes — dependent pediatric profile on account | Parent / guardian | System must offer "add a child's profile" if none exists when this pathway is selected |
| C — Elderly proxy | Optional — can proceed with minimal info | Adult child / caregiver | Oracle can ask key questions conversationally: age, current medications, baseline cognitive status, known conditions. Full health profile not required to trigger escalation logic — escalation happens based on symptom reports alone. |
| D — Partner / adult | No — third-party adults cannot be profiled | N/A | Oracle operates from general information only. Encourage third party to create their own account. |

Session Header / UI Flag

When a proxy pathway is active, the chat interface should display a persistent banner or session label so the Oracle and the user both know the context throughout the conversation.

| Pathway | UI Label (suggested) | Banner color |
| --- | --- | --- |
| A — Self | (no banner — default) | — |
| B — Child | Asking about: \[child's name\], age \[X\] | Green |
| C — Elderly parent | Asking about: \[parent's name\] · Proxy session | Gold |
| D — Partner / adult | General information mode — not a personalized consultation | Grey |

Oracle Response Tone by Pathway

| Pathway | Voice / Tone | Example opening |
| --- | --- | --- |
| A — Self | Direct, second person. Clinical warmth. Empowering. | "What you're describing sounds like classic perimenopause…" |
| B — Child proxy | Warm, parent-to-parent. Reassuring but precise. Third person for child. | "Thank you for bringing this up. At eight years old, the symptoms you're describing in your son…" |
| C — Elderly proxy | Calm, direct, coaching. Explicit about limitations of second-hand reporting. Actionable immediately. | "I want to be straightforward with you — in someone your mother's age, new incontinence combined with increased confusion needs to be evaluated today, not tomorrow…" |
| D — Partner / adult | Informational, non-clinical. Clear disclaimer. Redirects to self-care. | "I can share some general information about what might be behind those symptoms, but for anything personalized, your partner would need their own account…" |

**Implementation note for Tkxel:** The pathway flag (A/B/C/D) must be passed as a system-level context variable to the LangGraph agent at the start of every session — not inferred from conversation. It determines which escalation logic tree the agent runs, which response tone profile is loaded, and whether a dependent profile is looked up from the account. Do not allow the agent to override or reinterpret the pathway flag mid-session.

Approach NEW v1.2

There is no separate intake for intersex or transgender clients. Everyone answers the same short, inclusive core questions, and follow-up questions appear only when they apply. This keeps intake short, avoids gatekeeping anyone into a separate clinical pathway, and gives the agent accurate context for hormone guidance. The AI then gathers deeper history conversationally, as it does for all clients.

**Replaces:** the "Sex at birth" and "Gender identification" fields on the Adult Female, Adult Male and Adolescent forms. Use the expanded wording and options below on every form.

Core Questions — Every Adult Profile

| Field | Question wording | Options | Status |
| --- | --- | --- | --- |
| Gender identity | "How do you describe your gender?" | Woman · Man · Non-binary · Agender · Not listed (write in) · Prefer not to say | REQUIRED "Prefer not to say" counts as an answer |
| Pronouns | "What pronouns should I use for you?" | she/her · he/him · they/them · Write in | REQUIRED Editable anytime |
| Sex assigned at birth | "What sex were you assigned at birth?" | Female · Male · Intersex · Prefer not to say | REQUIRED |
| Organ inventory | "Which of these do you currently have? Choose all that apply." Helper text: "This helps me give hormone guidance that fits your body." | Uterus · Cervix · Ovaries · Testes · Prostate · Breast tissue · None of these · Prefer not to say | OPTIONAL Strongly encouraged |

**Why organ inventory for everyone:** hormone guidance depends on anatomy, not on gender identity or sex at birth alone. It also helps clients who have had a hysterectomy, oophorectomy or prostatectomy, so it is useful well beyond trans and intersex clients.

Conditional Follow-ups

A

**Intersex detail** CONDITIONAL\
Shown when sex assigned at birth = Intersex.\
"If you know the name of your variation, you can add it here." (free text, optional)

Do not show the long list of medical variations. The agent asks conversationally when relevant.

B

**Hormone history** CONDITIONAL\
Shown when gender identity differs from sex assigned at birth, when sex at birth = Intersex, or when gender identity = Non-binary, Agender or Not listed.\
"Are you taking, or have you ever taken, gender-affirming hormones?" Currently · In the past · Never · Prefer not to say\
If currently or in the past: which ones (testosterone · estrogen · progesterone · anti-androgen, e.g. spironolactone · puberty blockers · other), and "Is a healthcare provider overseeing this?" Yes · No

Essential for safe guidance on progesterone, testosterone and Gen-Pro.

C

**Surgical history** OPTIONAL\
Same trigger as B.\
"Have you had any gender-affirming or intersex-related surgeries?" Yes · No · Prefer not to say\
If yes: chest surgery · hysterectomy · removal of ovaries or testes · vaginoplasty · phalloplasty or metoidioplasty · other (write in)

Branching Rules for the Existing Forms

- **Route clinical question sets by anatomy:** organ inventory + sex at birth + reproductive status decide which questions appear. Uterus or ovaries present → menstrual and reproductive questions (with N/A options). Prostate or testes present → male reproductive questions. Intersex or mixed anatomy → show each relevant set.
- **Never route by gender identity alone.** A trans man may still have periods; a trans woman may still need prostate questions.
- **Language:** the agent always uses the client's gender identity and pronouns, and uses neutral anatomical terms ("your uterus," "your prostate") rather than gendered ones.
- **Provider-ready notes:** include gender identity, pronouns, sex assigned at birth, organ inventory and current hormones, so the provider has accurate context. The client can choose which of these appear before downloading.
- **"Prefer not to say"** is always available and never blocks the client from continuing.

Adolescents (13–17)

- Same core questions: gender identity, pronouns, sex assigned at birth. Organ inventory and hormone history are optional.
- Hormone history for teens asks about puberty blockers or hormones and whether a provider is overseeing them.
- Intersex question uses simpler wording: "Some people are born with bodies that are a little different from typical male or female bodies. This is called being intersex. Are you intersex?" Yes · No · I'm not sure · I don't understand the question

**Not in teen intake:** sexual activity, contraception and fertility preservation questions. A parent or advocate may manage the teen's profile, so confidentiality cannot be guaranteed. These topics belong with the teen's provider.\
\
**Legal review required:** laws on gender-affirming care for minors vary by state and country across the launch markets (US, UK, Canada, Australia). Mark the agent's scope for teen hormone questions as *legal/pending* in the Agent Intent Matrix until the attorney confirms.

Pediatric (Under 13)

No change beyond adding Intersex to the sex-at-birth options. The parent can share anything else about the child's body or development in conversation.

Privacy

- Gender identity, pronouns, sex assigned at birth, organ inventory, and hormone and surgical history are highly sensitive data.
- Never send these fields to analytics, ad pixels, Shopify or any third party. Encrypt at rest and in transit.
- Admin dashboards show these only in aggregate, never tied to an identifiable client.
- Clients can edit or delete these answers at any time.
- Attorney to confirm treatment under state consumer health data laws (e.g., Washington's My Health My Data Act), UK GDPR special category data, PIPEDA and the Australia Privacy Act.

**Source note:** question wording is adapted from published inclusive-intake guidance Deborah collected. The full list of intersex variations was intentionally left out of intake; it includes PCOS, which would confuse clients with PCOS who are not intersex.

Purpose

The Consult Context is collected at the start of each new conversation with the Oracle — it provides the session-specific chief complaint and any new information not already in the health profile. It is short, focused, and does not repeat fields already in the profile.

**Display pattern:** Show the client a read-only summary of their saved health profile (medications, known conditions, last update date) before asking the consult questions. Let them confirm or flag anything that has changed. This replaces re-entering the same data.

Consult Fields

| Field | Type | Status | Notes |
| --- | --- | --- | --- |
| Main health concern today | Text (narrative OK) | REQUIRED | This is the chief complaint. Free text — the bot handles narrative. |
| Other health issues to mention | Text | OPTIONAL |  |
| One health goal for this year | Text | OPTIONAL | From the original consult form — powerful for longitudinal context |
| Why haven't you achieved this yet? | Text | OPTIONAL | Self-reflection field — rich context for the bot |
| How many providers have you consulted for this problem? | Number | OPTIONAL | Signals medical complexity and prior care |
| New medications since last visit? | Yes / No → list | CONDITIONAL | Only asks if returning user; profile auto-loads existing meds |
| Anything else to share? | Text | OPTIONAL | Catch-all; often where the most important thing surfaces |

Printable Advocacy Summary

After each session, the app generates a printable summary for the client to bring to their own healthcare provider. This was confirmed as a core feature in Session 1.

- **Contents:** chief complaint, relevant history, the Oracle's recommended lab tests with insurance coding rationale, lifestyle interventions, and any emergency protocol flags
- **Tone:** professional, provider-facing — uses clinical language matching Deborah's lab coat persona
- **Format:** PDF generation from session output (not the intake form itself)

Knowledge Base Ingestion Pipeline

- **Books (PDF):** Hypothalamus Handbook, Hormones in Harmony, Menopause Action Plan — static upload to RAG store. Ask Tayyab about graphics extraction from PDFs (clinical diagrams carry diagnostic meaning).
- **Courses (PDF with embedded graphics):** Same as books. Confirm whether the vector store indexes surrounding text only, or whether images are also processed (OCR / multimodal).
- **Website:** Full crawl of deborahmaragopoulos.com and genesishealth.com. All YouTube content is already transcribed as blog posts — crawl captures both.
- **Live article doc:** Deborah authors new articles continuously (40+ ahead of publish queue as of Oct 2026). **This cannot be a one-time Dropbox upload.** Needs Google Drive sync or webhook for ongoing ingestion. Raise with Tayyab for architecture decision.
- **Q&A corpus:** Gaby's transcripts of live Q&A sessions. Requires de-identification pass (remove participant names — "Emma asks…" → "A member asks…") before ingestion. Deborah will run this through Claude before sending to Tkxel.

Decision Tree Implementation Notes

- **Profile routing:** sex at birth + gender identification + reproductive status together determine which question sets appear. These three fields should be collected early in the health profile flow before branching.
- **No repeated fields:** medications, supplements, and known conditions entered in the health profile must pre-populate the consult context screen as a reviewable summary — never ask for re-entry.
- **Pronoun logic:** gender identification field maps to pronouns (Female → she/her, Male → he/him, Non-binary / other → they/them). Pronouns used throughout app UI and in generated summaries.
- **Menstruation branching:** do not suppress menstrual questions based on gender ID alone when sex at birth is female. Trans men may still have periods. Use sex at birth + reproductive status together for the branch decision.
- **Age-gated content:** adolescent and pediatric profiles receive age-appropriate language. Emergency protocol language, drug interaction warnings, and certain clinical recommendations may differ.
- **Proxy pathway flag:** the A/B/C/D pathway selection (see Dependent & Proxy tab) must be passed as a context variable to LangGraph at session start. It is not inferred — it is explicit. The agent's escalation tree, response tone, and profile loading behavior all branch from this flag.

Accounts Required

| Account | Purpose | Owner | Status |
| --- | --- | --- | --- |
| GitHub | Source code repository under Genesis Health | Genesis Health | Setup with Tayyab |
| Azure | HIPAA-eligible cloud hosting | Genesis Health | Setup with Tayyab |
| Anthropic API | Production AI engine (claude-sonnet-4-20250514) | Genesis Health | Setup with Tayyab |
| Stripe | App subscription payments | Genesis Health | Existing account |
| Shopify | Nutraceutical sales / in-app product links | Genesis Health | Existing account |
| OpenAI API | Tkxel internal dev tooling only — NOT production | Tkxel | Tkxel's cost (confirmed) |

Compliance

- **HIPAA:** Azure HIPAA-eligible infrastructure; BAA in place with Tkxel
- **CCPA / CPRA:** California privacy compliance required
- **GDPR:** International users expected
- **Under-13 data:** No direct account creation for under-13. Data collected under dependent profiles managed by adult account holder. COPPA implications should be reviewed by legal counsel.
- **Proxy sessions:** When a user submits health information about a third party (especially a minor or an elderly dependent), the data handling and consent framework must account for the fact that the data subject and the account holder are different people. Legal review recommended before launch.

**For Tayyab:** The live article doc (Google Drive) needs an ingestion pipeline decision before the knowledge base architecture is finalized. This is a moving target — static Dropbox upload is not sufficient. Also confirm: how does LangGraph receive and persist the pathway flag (A/B/C/D) across a multi-turn session?