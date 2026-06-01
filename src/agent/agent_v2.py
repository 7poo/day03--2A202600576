import os
import re
import json
import time
from typing import List, Dict, Any, Optional, Callable
from src.core.llm_provider import LLMProvider
from src.telemetry.logger import logger
from src.telemetry.metrics import tracker


# ------------------------------------------------------------------
# Tool Schema Registry
# Each tool declares expected argument names so v2 can pre-validate
# before sending args to the function. This catches hallucinated arg
# names before they cause a TypeError.
# ------------------------------------------------------------------

TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "get_student_info": {
        "required": ["student_id"],
        "optional": [],
        "example": '{"tool": "get_student_info", "args": {"student_id": "STU001"}}',
    },
    "evaluate_submission": {
        "required": ["submission_text", "rubric"],
        "optional": ["model"],
        "example": '{"tool": "evaluate_submission", "args": {"submission_text": "...", "rubric": "..."}}',
    },
    "compute_group_score": {
        "required": ["group_inputs"],
        "optional": ["bonus_inputs"],
        "example": '{"tool": "compute_group_score", "args": {"group_inputs": {...}}}',
    },
    "compute_individual_score": {
        "required": ["individual_inputs"],
        "optional": [],
        "example": '{"tool": "compute_individual_score", "args": {"individual_inputs": {...}}}',
    },
}

# Few-Shot examples embedded in the system prompt to reduce PARSE_ERROR rate.
FEW_SHOT_EXAMPLES = """
=== EXAMPLE INTERACTION 1 ===
User Query: What are the submissions for student STU001?

Thought: I need to look up student STU001's information including submissions. I'll use the get_student_info tool.
Action: {"tool": "get_student_info", "args": {"student_id": "STU001"}}
Observation: {"student": {"id": "STU001", "name": "Nguyen Van A"}, "submissions": [...], "summary": {"num_submissions": 3}}

Thought: I now have all the information needed.
Final Answer: Student STU001 (Nguyen Van A) has 3 submissions on record.

=== EXAMPLE INTERACTION 2 ===
User Query: Grade this submission: "The agent uses ReAct loop" using the rubric "Must explain Thought-Action-Observation".

Thought: I need to evaluate the submission against the rubric. I'll use the evaluate_submission tool.
Action: {"tool": "evaluate_submission", "args": {"submission_text": "The agent uses ReAct loop", "rubric": "Must explain Thought-Action-Observation"}}
Observation: {"status": "success", "score": 6, "feedback": "Partially correct. Missing Observation step."}

Thought: I now have the evaluation result.
Final Answer: Score: 6/10. Feedback: Partially correct. Missing Observation step.
"""


class ReActAgentV2:
    """
    ReAct Agent v2 — improved over v1 with the following changes:

    1. Few-Shot examples in system prompt → reduces PARSE_ERROR by ~40%
       (measured in ablation: experiments/results/ablation_results.md)
    2. Tool schema pre-validation → catches hallucinated arg names before
       they cause TypeError, gives targeted hints
    3. Per-step retry budget (max_retries_per_step) → format errors no
       longer burn a main step; agent gets a targeted correction hint
    4. Targeted correction messages → instead of generic "use correct format",
       v2 returns the exact expected JSON with an example for that tool
    5. Error observation triage → detects [ERROR] prefix in observations
       and injects an explicit recovery hint into the next prompt
    """

    def __init__(
        self,
        llm: LLMProvider,
        tools: List[Dict[str, Any]],
        max_steps: int = 5,
        max_retries_per_step: int = 2,
    ):
        self.llm = llm
        self.tools = {t["name"]: t for t in tools}
        self.tools_list = tools
        self.max_steps = max_steps
        self.max_retries_per_step = max_retries_per_step
        self.history: List[str] = []

    # ------------------------------------------------------------------
    # System Prompt (v2 — with Few-Shot examples)
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        tool_descriptions = "\n".join(
            [f'  - {t["name"]}: {t["description"]}' for t in self.tools_list]
        )

        return (
            "You are a helpful AI assistant that solves tasks step by step.\n"
            "You have access to the following tools:\n"
            f"{tool_descriptions}\n\n"
            "You MUST follow this EXACT format for EVERY step:\n\n"
            "Thought: <your reasoning about what to do next>\n"
            'Action: {"tool": "<tool_name>", "args": {"<arg1>": "<value1>", ...}}\n'
            "Observation: <result will be inserted by the system>\n\n"
            "Rules:\n"
            "1. Always start with a Thought.\n"
            "2. After each Thought, output EXACTLY ONE Action line as valid JSON.\n"
            "3. Do NOT invent tool names — only use names from the list above.\n"
            "4. Do NOT output an Observation yourself — the system inserts it.\n"
            "5. When you have enough information, respond with:\n"
            "   Thought: I now have all the information needed.\n"
            "   Final Answer: <your complete answer to the user>\n"
            "6. Only output raw JSON in the Action line — no markdown fences.\n"
            "7. Check the tool's required arguments before calling it.\n\n"
            f"--- EXAMPLES (follow this exact format) ---\n{FEW_SHOT_EXAMPLES}\n"
            "--- END EXAMPLES ---\n"
        )

    # ------------------------------------------------------------------
    # Core ReAct Loop (v2)
    # ------------------------------------------------------------------

    def run(self, user_input: str) -> str:
        logger.log_event(
            "AGENT_V2_START",
            {
                "input": user_input,
                "model": self.llm.model_name,
                "max_steps": self.max_steps,
                "max_retries_per_step": self.max_retries_per_step,
                "version": "v2",
            },
        )

        self.history = []
        steps = 0
        total_tokens_used = 0
        total_cost = 0.0
        parse_errors = 0
        tool_errors = 0

        while steps < self.max_steps:
            steps += 1
            retries = 0

            # Per-step retry loop for format errors — does NOT burn steps
            while retries <= self.max_retries_per_step:
                prompt = self._build_prompt(user_input)

                try:
                    result = self.llm.generate(
                        prompt, system_prompt=self.get_system_prompt()
                    )
                except Exception as e:
                    logger.log_event("LLM_ERROR", {"step": steps, "error": str(e)})
                    self.history.append(f"Observation: [ERROR] LLM call failed: {e}")
                    break

                content: str = result.get("content", "")
                usage: dict = result.get("usage", {})
                latency_ms: int = result.get("latency_ms", 0)
                provider: str = result.get("provider", "unknown")

                tracker.track_request(provider, self.llm.model_name, usage, latency_ms)
                total_tokens_used += usage.get("total_tokens", 0)
                total_cost += tracker.calculate_cost(self.llm.model_name, usage)

                logger.log_event(
                    "AGENT_V2_STEP",
                    {
                        "step": steps,
                        "retry": retries,
                        "llm_response": content[:500],
                        "latency_ms": latency_ms,
                        "tokens": usage,
                    },
                )

                # Check for Final Answer
                final_answer = self._parse_final_answer(content)
                if final_answer is not None:
                    logger.log_event(
                        "AGENT_V2_END",
                        {
                            "steps": steps,
                            "status": "final_answer",
                            "total_tokens": total_tokens_used,
                            "total_cost_usd": round(total_cost, 6),
                            "parse_errors": parse_errors,
                            "tool_errors": tool_errors,
                        },
                    )
                    return final_answer

                # Parse Action
                action_json = self._parse_action(content)
                thought = self._parse_thought(content)

                if action_json is None:
                    parse_errors += 1
                    retries += 1
                    logger.log_event(
                        "PARSE_ERROR_V2",
                        {
                            "step": steps,
                            "retry": retries,
                            "error": "Could not parse Action JSON",
                            "raw_output": content[:300],
                        },
                    )
                    if retries <= self.max_retries_per_step:
                        # Targeted correction — include correct format example
                        self.history.append(
                            f"Thought: {thought}\n"
                            "Observation: [SYSTEM FORMAT ERROR] Your Action line was not valid JSON. "
                            "You MUST output exactly one line like:\n"
                            '  Action: {"tool": "tool_name", "args": {"key": "value"}}\n'
                            "Do NOT use markdown fences. Try again."
                        )
                        continue
                    else:
                        # Exhausted retries for this step — log and move to next
                        self.history.append(
                            f"Thought: {thought}\n"
                            "Observation: [SYSTEM] Format error persists after retries. "
                            "Proceeding — try a different approach."
                        )
                        break

                # Pre-validate tool arguments (v2 improvement)
                tool_name = action_json.get("tool", "")
                tool_args = action_json.get("args", {})

                validation_error = self._validate_tool_args(tool_name, tool_args)
                if validation_error:
                    retries += 1
                    logger.log_event(
                        "TOOL_VALIDATION_ERROR",
                        {
                            "step": steps,
                            "retry": retries,
                            "tool": tool_name,
                            "args": tool_args,
                            "error": validation_error,
                        },
                    )
                    if retries <= self.max_retries_per_step:
                        self.history.append(
                            f"Thought: {thought}\n"
                            f"Observation: [SYSTEM ARG ERROR] {validation_error}"
                        )
                        continue
                    # Fall through with potentially wrong args — let tool handle it

                # Execute tool
                observation = self._execute_tool(tool_name, tool_args)
                if str(observation).startswith("[ERROR]"):
                    tool_errors += 1

                logger.log_event(
                    "TOOL_CALL_V2",
                    {
                        "step": steps,
                        "tool": tool_name,
                        "args": tool_args,
                        "observation": str(observation)[:300],
                        "is_error": str(observation).startswith("[ERROR]"),
                    },
                )

                # Error observation triage (v2 improvement)
                obs_text = str(observation)
                if obs_text.startswith("[ERROR]") and "does not exist" in obs_text:
                    obs_text += (
                        f" Available tools: {list(self.tools.keys())}. "
                        "Please use one of these exact tool names."
                    )

                history_block = (
                    f"Thought: {thought}\n"
                    f'Action: {json.dumps({"tool": tool_name, "args": tool_args})}\n'
                    f"Observation: {obs_text}"
                )
                self.history.append(history_block)
                break  # Successful step — exit retry loop

        logger.log_event(
            "AGENT_V2_END",
            {
                "steps": steps,
                "status": "max_steps_exceeded",
                "total_tokens": total_tokens_used,
                "total_cost_usd": round(total_cost, 6),
                "parse_errors": parse_errors,
                "tool_errors": tool_errors,
            },
        )
        return (
            f"[AGENT V2 TIMEOUT] Reached max {self.max_steps} steps without final answer. "
            f"Parse errors: {parse_errors}, Tool errors: {tool_errors}. "
            f"Last context:\n" + "\n".join(self.history[-2:])
        )

    # ------------------------------------------------------------------
    # Prompt Builder
    # ------------------------------------------------------------------

    def _build_prompt(self, user_input: str) -> str:
        parts = [f"User Query: {user_input}"]
        if self.history:
            parts.append("\n--- Previous Steps ---")
            parts.extend(self.history)
            parts.append("--- End Previous Steps ---\n")
            parts.append("Continue reasoning from where you left off.")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Tool Schema Validation (v2 new feature)
    # ------------------------------------------------------------------

    def _validate_tool_args(self, tool_name: str, args: Dict[str, Any]) -> Optional[str]:
        """
        Check that required args are present for the given tool.
        Returns an error string with a hint, or None if valid.
        """
        if tool_name not in self.tools:
            return None  # hallucination handled downstream

        schema = TOOL_SCHEMAS.get(tool_name)
        if schema is None:
            return None  # no schema registered — skip validation

        missing = [k for k in schema["required"] if k not in args]
        if missing:
            example = schema.get("example", "")
            return (
                f"Missing required argument(s) for '{tool_name}': {missing}. "
                f"Correct format example: {example}"
            )
        return None

    # ------------------------------------------------------------------
    # Parsing Helpers (same as v1, kept for self-containedness)
    # ------------------------------------------------------------------

    def _parse_final_answer(self, text: str) -> Optional[str]:
        match = re.search(
            r"Final\s*Answer\s*:\s*(.+)", text, re.IGNORECASE | re.DOTALL
        )
        return match.group(1).strip() if match else None

    def _parse_thought(self, text: str) -> str:
        match = re.search(
            r"Thought\s*:\s*(.+?)(?=Action\s*:|Final\s*Answer\s*:|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        return match.group(1).strip() if match else text.strip()

    def _parse_action(self, text: str) -> Optional[Dict[str, Any]]:
        # Strategy 1: Action: { ... }
        match = re.search(
            r"Action\s*:\s*(\{.+?\})\s*$", text, re.IGNORECASE | re.DOTALL | re.MULTILINE
        )
        raw_json = match.group(1) if match else None

        # Strategy 2: markdown fences
        if raw_json is None:
            match = re.search(
                r"Action\s*:\s*```(?:json)?\s*(\{.+?\})\s*```",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            raw_json = match.group(1) if match else None

        # Strategy 3: first JSON-like object after "Action"
        if raw_json is None:
            match = re.search(
                r"Action\s*:.*?(\{[^{}]*\})", text, re.IGNORECASE | re.DOTALL
            )
            raw_json = match.group(1) if match else None

        if raw_json is None:
            return None

        try:
            parsed = json.loads(raw_json)
            if "tool" not in parsed:
                return None
            if "args" not in parsed:
                parsed["args"] = {}
            return parsed
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------
    # Tool Execution (same as v1)
    # ------------------------------------------------------------------

    def _execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name not in self.tools:
            logger.log_event(
                "HALLUCINATION_ERROR",
                {"tool_requested": tool_name, "available": list(self.tools.keys())},
            )
            return (
                f"[ERROR] Tool '{tool_name}' does not exist. "
                f"Available tools: {list(self.tools.keys())}"
            )

        tool = self.tools[tool_name]
        func: Optional[Callable] = tool.get("function")

        if func is None:
            return f"[ERROR] Tool '{tool_name}' has no callable function registered."

        try:
            start = time.time()
            result = func(**args) if isinstance(args, dict) else func(args)
            elapsed_ms = int((time.time() - start) * 1000)

            logger.log_event(
                "TOOL_EXECUTION_V2",
                {"tool": tool_name, "execution_time_ms": elapsed_ms, "success": True},
            )
            return str(result)

        except TypeError as e:
            logger.log_event(
                "TOOL_ARG_ERROR",
                {"tool": tool_name, "args": args, "error": str(e)},
            )
            schema = TOOL_SCHEMAS.get(tool_name, {})
            hint = f" Expected args: {schema.get('required', [])}." if schema else ""
            return f"[ERROR] Invalid arguments for tool '{tool_name}': {e}.{hint}"

        except Exception as e:
            logger.log_event(
                "TOOL_RUNTIME_ERROR",
                {"tool": tool_name, "args": args, "error": str(e)},
            )
            return f"[ERROR] Tool '{tool_name}' raised an exception: {e}"


# ------------------------------------------------------------------
# Convenience factory
# ------------------------------------------------------------------

def create_agent_v2(
    llm: LLMProvider,
    tools: List[Dict[str, Any]],
    max_steps: int = 5,
    max_retries_per_step: int = 2,
) -> ReActAgentV2:
    """Create and return a configured ReActAgentV2 instance."""
    return ReActAgentV2(
        llm=llm,
        tools=tools,
        max_steps=max_steps,
        max_retries_per_step=max_retries_per_step,
    )
