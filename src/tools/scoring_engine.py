from typing import Dict, Any
from src.telemetry.logger import logger


DEFAULT_GROUP_WEIGHTS = {
    "chatbot_baseline": 2,
    "agent_v1": 7,
    "agent_v2": 7,
    "tool_design": 4,
    "trace_quality": 9,
    "evaluation_analysis": 7,
    "flowchart_insight": 5,
    "code_quality": 4,
}


class ScoringEngine:
    """Compute group and individual scores using simple rule-based logic.

    - group_inputs: dict mapping the category keys to achieved points (or booleans where appropriate)
    - bonus_inputs: dict mapping bonus categories to booleans or numeric points
    - individual_inputs: dict with keys 'technical', 'debugging', 'insights', 'future' numeric scores
    """

    def __init__(self, weights: Dict[str, int] = None):
        self.weights = weights or DEFAULT_GROUP_WEIGHTS

    def compute_group_score(self, group_inputs: Dict[str, Any], bonus_inputs: Dict[str, Any] = None) -> Dict[str, Any]:
        # Base score calculation: if input is boolean, map to full weight
        base = 0
        breakdown = {}
        for k, w in self.weights.items():
            v = group_inputs.get(k)
            if isinstance(v, bool):
                pts = w if v else 0
            elif v is None:
                pts = 0
            else:
                # allow direct numeric (cap to weight)
                try:
                    pts = float(v)
                except Exception:
                    pts = 0
                if pts > w:
                    pts = w
            breakdown[k] = pts
            base += pts

        bonus_total = 0
        bonus_breakdown = {}
        if bonus_inputs:
            for bk, bv in bonus_inputs.items():
                # expect numeric or boolean
                if isinstance(bv, bool):
                    # map known bonus mapping
                    mapping = {"extra_monitoring": 3, "extra_tools": 2, "failure_handling": 3, "live_demo": 5, "ablation": 2}
                    pts = mapping.get(bk, 0) if bv else 0
                else:
                    try:
                        pts = float(bv)
                    except Exception:
                        pts = 0
                bonus_breakdown[bk] = pts
                bonus_total += pts

        group_score = base + bonus_total
        group_score_capped = min(60, group_score)

        result = {
            "base": base,
            "bonus": bonus_total,
            "capped": group_score_capped,
            "breakdown": breakdown,
            "bonus_breakdown": bonus_breakdown,
        }
        logger.log_event("SCORING_GROUP_COMPUTE", result)
        return result

    def compute_individual_score(self, individual_inputs: Dict[str, float]) -> Dict[str, Any]:
        # Expect keys: technical (15), debugging (10), insights (10), future (5)
        tech = min(15, float(individual_inputs.get('technical', 0)))
        debug = min(10, float(individual_inputs.get('debugging', 0)))
        insights = min(10, float(individual_inputs.get('insights', 0)))
        future = min(5, float(individual_inputs.get('future', 0)))

        total = tech + debug + insights + future
        result = {"technical": tech, "debugging": debug, "insights": insights, "future": future, "total": total}
        logger.log_event("SCORING_INDIVIDUAL_COMPUTE", result)
        return result


def example():
    se = ScoringEngine()
    group_inputs = {"chatbot_baseline": True, "agent_v1": True, "agent_v2": False, "tool_design": 3, "trace_quality": 8, "evaluation_analysis": 6, "flowchart_insight": 4, "code_quality": 3}
    bonus = {"extra_monitoring": True, "extra_tools": False, "failure_handling": True}
    individual = {"technical": 12, "debugging": 9, "insights": 8, "future": 4}
    print(se.compute_group_score(group_inputs, bonus))
    print(se.compute_individual_score(individual))


if __name__ == "__main__":
    example()
