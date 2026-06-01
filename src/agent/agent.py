import os
import re
import json
import uuid
import time
from typing import List, Dict, Any, Optional
from src.core.llm_provider import LLMProvider
from src.telemetry.logger import logger
from src.tools.db_tool import db_tool
from src.tools import model_evaluator

class ReActAgent:
    """
    SKELETON: A ReAct-style Agent that follows the Thought-Action-Observation loop.
    Students should implement the core loop logic and tool execution.
    """
    
    def __init__(self, llm: LLMProvider, tools: List[Dict[str, Any]], max_steps: int = 5):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.history = []

    def get_system_prompt(self) -> str:
        """
        TODO: Implement the system prompt that instructs the agent to follow ReAct.
        Should include:
        1.  Available tools and their descriptions.
        2.  Format instructions: Thought, Action, Observation.
        """
        tool_descriptions = "\n".join([f"- {t['name']}: {t['description']}" for t in self.tools])
        return f"""
        You are an intelligent assistant. You have access to the following tools:
        {tool_descriptions}

        Use the following format:
        Thought: your line of reasoning.
        Action: tool_name(arguments)
        Observation: result of the tool call.
        ... (repeat Thought/Action/Observation if needed)
        Final Answer: your final response.
        """

    def run(self, user_input: str) -> str:
        """
        TODO: Implement the ReAct loop logic.
        1. Generate Thought + Action.
        2. Parse Action and execute Tool.
        3. Append Observation to prompt and repeat until Final Answer.
        """
        trace_id = str(uuid.uuid4())
        logger.log_event("AGENT_START", {"input": user_input, "model": self.llm.model_name, "trace_id": trace_id})

        system_prompt = self.get_system_prompt()
        current_prompt = user_input
        steps = 0

        while steps < self.max_steps:
            # call LLM provider
            try:
                result = self.llm.generate(current_prompt, system_prompt=system_prompt)
                content = result.get('content') or ''
                usage = result.get('usage')
                latency = result.get('latency_ms') if result.get('latency_ms') is not None else None
            except Exception as e:
                logger.log_event('LLM_ERROR', {'error': str(e), 'trace_id': trace_id})
                return f"LLM error: {e}"

            logger.log_event('LLM_RESPONSE', {'trace_id': trace_id, 'step': steps, 'content': content})

            # check for Final Answer
            m_final = re.search(r"Final Answer:\s*(.*)", content, flags=re.S)
            if m_final:
                final = m_final.group(1).strip()
                logger.log_event('AGENT_FINAL', {'trace_id': trace_id, 'final': final, 'steps': steps})
                return final

            # parse Action: tool_name(args)
            m = re.search(r"Action:\s*([a-zA-Z0-9_]+)\((.*)\)", content, flags=re.S)
            if m:
                tool_name = m.group(1).strip()
                args_raw = m.group(2).strip()
                # try json parse
                args = None
                try:
                    args = json.loads(args_raw)
                except Exception:
                    # fallback: single string arg
                    args = {'arg': args_raw.strip('"\'')}

                obs = self._execute_tool(tool_name, args, trace_id=trace_id, step=steps)
                # append observation and continue
                obs_text = json.dumps(obs) if not isinstance(obs, str) else obs
                current_prompt = current_prompt + f"\nObservation: {obs_text}\n"
            else:
                # no Action found, stop to avoid infinite loop
                logger.log_event('AGENT_NO_ACTION', {'trace_id': trace_id, 'content_preview': content[:200]})
                return content

            steps += 1

        logger.log_event("AGENT_END", {"steps": steps, "trace_id": trace_id})
        return "Max steps reached without Final Answer"

    def _execute_tool(self, tool_name: str, args: str) -> str:
        """
        Helper method to execute tools by name.
        """
        # Support built-in tools: db_query, model_eval
        if tool_name == 'db_query':
            student_id = args.get('student_id') if isinstance(args, dict) else args
            res = db_tool.get_student_info(student_id)
            return res

        if tool_name == 'model_eval':
            # args: submission_text or submission_path, rubric dict optional
            rubric = args.get('rubric') if isinstance(args, dict) else None
            submission_text = None
            if isinstance(args, dict) and args.get('submission_path'):
                path = args.get('submission_path')
                try:
                    with open(path, 'r', encoding='utf-8') as fh:
                        submission_text = fh.read()
                except Exception as e:
                    return {'error': f'file_read_error: {e}'}
            elif isinstance(args, dict) and args.get('submission_text'):
                submission_text = args.get('submission_text')
            else:
                # fallback: try arg 'arg'
                if isinstance(args, dict) and args.get('arg'):
                    submission_text = args.get('arg')

            api_key = getattr(self.llm, 'api_key', None)
            model_name = getattr(self.llm, 'model_name', 'gpt-4o-mini')
            if submission_text is None:
                return {'error': 'no_submission_text'}

            eval_res = model_evaluator.evaluate_submission(submission_text, rubric or {}, api_key=api_key, model=model_name)
            return eval_res

        # fallback: try to match provided tools list
        for tool in self.tools:
            if tool['name'] == tool_name:
                return { 'result': f"Simulated call to {tool_name}" }
        return { 'error': f"Tool {tool_name} not found." }
