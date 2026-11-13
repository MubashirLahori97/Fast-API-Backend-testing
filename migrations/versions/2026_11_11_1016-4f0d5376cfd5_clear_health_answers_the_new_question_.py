"""Clear health answers the new question bank can't use.

Revision ID: 4f0d5376cfd5
Revises: 978c5998e7e1
Create Date: 2026-11-11 10:16:33.811126

"""

# ruff: noqa: E501  (the SQL below is copied from docs/decisions/phase-4-routing-doc.md as is)

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4f0d5376cfd5"
down_revision: str | Sequence[str] | None = "978c5998e7e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The health profile's question bank was rebuilt to the BA's Health Intake Routing document
# (docs/decisions/phase-4-routing-doc.md). These delete the answers the new bank can't use:
# keys it no longer has, and kept keys whose stored value no longer fits. Dev data only.
DATA_STEP = r"""
-- 1. Keys removed from the bank (26).
DELETE FROM health_answers WHERE question_key IN (
  'bone_density','child_birth','child_growth','child_milestones','child_safety',
  'colon_screening','conditions','cycle_regularity','diet','exercise','family_history',
  'growth_concerns','hormone_history_details','sleep_quality','support','symptoms_cycle',
  'symptoms_general','teen_home','teen_puberty_blockers','teen_safety','teen_school',
  'teen_sexual_health','teen_wellbeing','teen_worries','vaccinations','work');

-- 2. Kept keys whose kind changed.
DELETE FROM health_answers WHERE question_key IN ('allergies')
  AND jsonb_typeof(answer->'value') <> 'string';                     -- named_list -> text
DELETE FROM health_answers WHERE question_key IN ('amab_hormone_method','surgery_history')
  AND jsonb_typeof(answer->'value') <> 'string';                     -- multi -> single choice
DELETE FROM health_answers WHERE question_key = 'hrt_type'
  AND jsonb_typeof(answer->'value') <> 'array';                      -- single -> multi choice
DELETE FROM health_answers WHERE question_key IN ('pap_smear','mammogram','prostate_screening')
  AND answer->>'value' !~ '^\d{4}-\d{2}-\d{2}$';                     -- ranges -> dates
DELETE FROM health_answers WHERE question_key = 'child_school'
  AND answer->>'value' IN ('well','okay','hard','not_started');      -- choice -> text

-- 3. Kept keys whose codes changed.
DELETE FROM health_answers WHERE question_key = 'hormone_history'
  AND answer->>'value' NOT IN ('yes','no');
DELETE FROM health_answers WHERE question_key = 'ovaries_removed'
  AND answer->>'value' NOT IN ('yes','no','partial');
DELETE FROM health_answers WHERE question_key = 'periods_started'
  AND answer->>'value' NOT IN ('yes','no','describe');
DELETE FROM health_answers WHERE question_key = 'puberty_started'
  AND answer->>'value' NOT IN ('yes','no');
DELETE FROM health_answers WHERE question_key = 'reproductive_status'
  AND answer->>'value' = 'menstruating';
DELETE FROM health_answers h WHERE h.question_key = 'symptoms_female' AND EXISTS (
  SELECT 1 FROM jsonb_array_elements_text(
    coalesce(h.answer->'value'->'selected','[]') || coalesce(h.answer->'value'->'not_applicable','[]')) c
  WHERE c NOT IN ('hot_flashes','night_sweats','brain_fog','forgetfulness','mood_swings',
    'irritability','depression','rage','vaginal_dryness','poor_lubrication','urinary_urgency',
    'low_libido','clamminess','fatigue','insomnia','muscle_weakness','body_fat_change',
    'lower_exercise_tolerance','lower_stress_tolerance','illness_susceptibility','menstrual_cramps'));
DELETE FROM health_answers h WHERE h.question_key = 'symptoms_male' AND EXISTS (
  SELECT 1 FROM jsonb_array_elements_text(
    coalesce(h.answer->'value'->'selected','[]') || coalesce(h.answer->'value'->'not_applicable','[]')) c
  WHERE c NOT IN ('hot_flashes','night_sweats','mood_swings','irritability','depression','rage',
    'mental_fogginess','forgetfulness','clamminess','body_fat_change','muscle_weakness','fatigue',
    'lower_exercise_tolerance','illness_susceptibility','lower_stress_tolerance','insomnia',
    'low_sex_drive','fewer_morning_erections','reduced_erectile_firmness'));
"""


def upgrade() -> None:
    """Upgrade schema."""
    for statement in DATA_STEP.split(";"):
        code = "\n".join(
            line for line in statement.splitlines() if not line.strip().startswith("--")
        ).strip()
        if code:
            op.execute(code)


def downgrade() -> None:
    """Downgrade schema."""
    # The deleted answers can't be brought back, and the schema didn't change.
