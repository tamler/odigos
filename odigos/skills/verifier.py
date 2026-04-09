"""Surrogate skill verifier — informationally isolated quality validation."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odigos.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

PASS_THRESHOLDS = {0: 0.6, 1: 0.7, 2: 0.8}
DEFAULT_SCENARIO_COUNT = 3
ESCALATED_SCENARIO_COUNT = 5


@dataclass
class ScenarioResult:
    scenario: str
    response: str
    assertions: list[str] = field(default_factory=list)
    passed: list[bool] = field(default_factory=list)
    score: float = 0.0


@dataclass
class VerificationResult:
    passed: bool
    overall_score: float
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    diagnostics: str | None = None
    escalation_level: int = 0


class SkillVerifier:
    """Validates skill quality using an informationally isolated LLM session."""

    def __init__(self, llm_client, prompts_dir="data/prompts", skill_registry=None, db=None):
        self._llm = llm_client
        self._prompts_dir = Path(prompts_dir)
        self._registry = skill_registry
        self._db = db

    async def verify(
        self,
        task_description: str,
        output_artifacts: list[tuple[str, str]],
        escalation_level: int = 0,
    ) -> VerificationResult:
        """Generic interface. Evaluates each artifact against task_description.

        output_artifacts: list of (scenario, response) tuples.
        """
        threshold = PASS_THRESHOLDS.get(escalation_level, PASS_THRESHOLDS[0])
        eval_template = self._load_prompt("verification_evaluate.md")

        escalation_instructions = self._escalation_instructions(escalation_level)

        scenario_results: list[ScenarioResult] = []
        scores: list[float] = []
        all_diagnostics: list[str] = []

        for scenario, response in output_artifacts:
            prompt = (
                eval_template
                .replace("{task_description}", task_description)
                .replace("{scenario}", scenario)
                .replace("{response}", response)
                .replace("{escalation_instructions}", escalation_instructions)
            )

            llm_response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1000,
            )

            parsed = self._parse_json(llm_response.content)

            raw_assertions = parsed.get("assertions", [])
            assertion_texts = [a.get("text", "") for a in raw_assertions]
            assertion_passed = [bool(a.get("passed", False)) for a in raw_assertions]

            score = float(parsed.get("overall_score", 0.0))
            diag = parsed.get("diagnostics")

            sr = ScenarioResult(
                scenario=scenario,
                response=response,
                assertions=assertion_texts,
                passed=assertion_passed,
                score=score,
            )
            scenario_results.append(sr)
            scores.append(score)

            if diag:
                all_diagnostics.append(diag)

        overall_score = sum(scores) / len(scores) if scores else 0.0
        passed = overall_score >= threshold
        diagnostics = "\n".join(all_diagnostics) if all_diagnostics else None

        return VerificationResult(
            passed=passed,
            overall_score=overall_score,
            scenario_results=scenario_results,
            diagnostics=diagnostics,
            escalation_level=escalation_level,
        )

    async def verify_skill(self, skill_name: str) -> VerificationResult:
        """Skill-specific wrapper.

        Step 1: Generate scenarios (isolated — only sees name + description).
        Step 2: Run each scenario through the skill (LLM with system_prompt).
        Step 3: Evaluate outputs via verify().
        Step 4: Store verification record in DB (if available).
        """
        if self._registry is None:
            raise ValueError("skill_registry is required for verify_skill()")

        skill = self._registry.get(skill_name)
        if skill is None:
            raise ValueError(f"Skill '{skill_name}' not found in registry")

        escalation_level = getattr(skill, "escalation_level", 0)

        # Step 1: Generate scenarios (isolated — no system_prompt)
        scenarios = await self._generate_scenarios(
            skill_name=skill.name,
            skill_description=skill.description,
            escalation_level=escalation_level,
        )

        # Step 2: Run each scenario through the skill
        artifacts: list[tuple[str, str]] = []
        for scenario in scenarios:
            skill_response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": skill.system_prompt},
                    {"role": "user", "content": scenario},
                ],
                temperature=0.7,
                max_tokens=1000,
            )
            artifacts.append((scenario, skill_response.content))

        # Step 3: Evaluate
        result = await self.verify(
            task_description=skill.description,
            output_artifacts=artifacts,
            escalation_level=escalation_level,
        )

        # Step 4: Persist to DB
        if self._db is not None:
            await self._store_verification(skill_name, scenarios, result)

        return result

    async def _generate_scenarios(
        self,
        skill_name: str,
        skill_description: str,
        escalation_level: int = 0,
    ) -> list[str]:
        """Generate test scenarios. Isolated — only sees name + description."""
        scenario_count = (
            ESCALATED_SCENARIO_COUNT if escalation_level > 0 else DEFAULT_SCENARIO_COUNT
        )
        escalation_instructions = self._escalation_instructions(escalation_level)

        template = self._load_prompt("verification_scenarios.md")
        prompt = (
            template
            .replace("{skill_name}", skill_name)
            .replace("{skill_description}", skill_description)
            .replace("{scenario_count}", str(scenario_count))
            .replace("{escalation_instructions}", escalation_instructions)
        )

        response = await self._llm.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=800,
        )

        parsed = self._parse_json(response.content)
        scenarios = parsed.get("scenarios", [])

        if not scenarios or not isinstance(scenarios, list):
            logger.warning(
                "Failed to parse scenarios for skill '%s', using generic fallback",
                skill_name,
            )
            scenarios = [f"Please demonstrate your capabilities as described: {skill_description}"]

        return [str(s) for s in scenarios]

    def _load_prompt(self, filename: str) -> str:
        """Load a prompt template from the prompts directory."""
        path = self._prompts_dir / filename
        return path.read_text()

    def _parse_json(self, content: str) -> dict:
        """Parse JSON from LLM response, handling markdown fences."""
        text = content.strip()

        # Strip ```json ... ``` or ``` ... ``` fences
        if text.startswith("```"):
            lines = text.splitlines()
            # Drop the opening fence line and the closing fence
            inner_lines = []
            for i, line in enumerate(lines):
                if i == 0:
                    continue
                if line.strip() == "```":
                    break
                inner_lines.append(line)
            text = "\n".join(inner_lines).strip()

        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            logger.warning("Parsed JSON is not a dict: %r", result)
            return {}
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse JSON from LLM response: %s", exc)
            return {}

    def _escalation_instructions(self, escalation_level: int) -> str:
        """Return escalation-level-specific instructions for prompt templates."""
        if escalation_level == 0:
            return ""
        if escalation_level == 1:
            return (
                "This is an escalated verification. Apply stricter standards. "
                "The skill must demonstrate reliable and consistent quality."
            )
        return (
            "This is a high-escalation verification. Apply rigorous standards. "
            "The skill must perform at an expert level with no significant gaps."
        )

    async def _store_verification(
        self,
        skill_name: str,
        scenarios: list[str],
        result: VerificationResult,
    ) -> None:
        """Persist verification record to skill_verifications table."""
        record_id = str(uuid.uuid4())
        scenarios_json = json.dumps(scenarios)
        results_json = json.dumps(
            [
                {
                    "scenario": sr.scenario,
                    "response": sr.response,
                    "assertions": sr.assertions,
                    "passed": sr.passed,
                    "score": sr.score,
                }
                for sr in result.scenario_results
            ]
        )

        try:
            await self._db.execute(
                """
                INSERT INTO skill_verifications
                    (id, skill_name, scenarios_json, results_json,
                     overall_score, escalation_level, diagnostics)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    skill_name,
                    scenarios_json,
                    results_json,
                    result.overall_score,
                    result.escalation_level,
                    result.diagnostics,
                ),
            )
            await self._db.commit()
        except Exception as exc:
            logger.error("Failed to store verification record for '%s': %s", skill_name, exc)
