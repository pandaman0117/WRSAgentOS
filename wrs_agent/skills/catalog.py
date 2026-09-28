"""Pure operations on discovered contracts; no global or built-in skill registry."""

from pydantic import ValidationError

from wrs_agent.errors import AgentError


def validate_skill(name, version, args, *, registry):
    entry = registry.get(name)
    if entry is None:
        raise AgentError("unknown_skill")
    if version != entry.version:
        raise AgentError("skill_version_mismatch")
    try:
        return entry.arguments.model_validate(args)
    except ValidationError:
        raise AgentError("invalid_arguments") from None


def require_contract(name, version, offered, *, node_id=None, stage=None):
    if name not in offered:
        raise AgentError("skill_not_on_node", node_id=node_id, stage=stage)
    if version is not None and offered[name] != version:
        raise AgentError("skill_version_mismatch", node_id=node_id, stage=stage)


def resolve_routes(offered, overrides=None):
    """Resolve unique providers. Overrides pin a provider, including while offline."""
    providers = {}
    for node, names in offered.items():
        for name in names:
            providers.setdefault(name, set()).add(node)
    routes = dict(overrides or {})
    ambiguous = set()
    for name, nodes in providers.items():
        if name in routes:
            continue
        if len(nodes) == 1:
            routes[name] = next(iter(nodes))
        else:
            ambiguous.add(name)
    return routes, ambiguous


def skill_specs(features, bindings):
    result = {}
    for name, node in bindings.items():
        cap = features.get(node)
        if cap is None:
            continue
        spec = cap.specs.get(name)
        if (
            spec is not None and spec.name == name
            and cap.skills.get(name) == spec.version
        ):
            result[name] = spec.model_copy(deep=True)
    return result


def lookup_skills(features, bindings):
    """Return every available contract; prompt selection is a separate concern."""
    return [spec for _, spec in sorted(skill_specs(features, bindings).items())]
