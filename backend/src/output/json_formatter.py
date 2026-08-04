"""Consistent JSON output wrapper for single- and multi-plan SBC extractions."""

PLAN_ROOT_KEY = "Plan_Information_List"


def is_plan_object(data: dict) -> bool:
    return isinstance(data, dict) and "plan_information" in data


def unwrap_plans(data) -> list[dict]:
    """Return plan objects from wrapped or legacy flat JSON."""
    if isinstance(data, list):
        return [item for item in data if is_plan_object(item)]

    if not isinstance(data, dict):
        return []

    if PLAN_ROOT_KEY in data:
        plans = data[PLAN_ROOT_KEY]
        if isinstance(plans, list):
            return [item for item in plans if is_plan_object(item)]
        if is_plan_object(plans):
            return [plans]
        return []

    if is_plan_object(data):
        return [data]

    return []


def wrap_plans(plans: list[dict]) -> dict:
    """Wrap one or more plan objects in the standard root structure."""
    return {PLAN_ROOT_KEY: list(plans)}
