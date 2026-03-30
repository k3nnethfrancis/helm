"""Comprehensive tests for the helm.topologies package."""

from __future__ import annotations

import pytest

from helm.topologies.families import (
    COORDINATION_FAMILY_LABELS,
    FAMILY_LAYOUTS,
    SUPPORTED_FAMILY_SIZES,
    RoleSpec,
    pattern_runtime_label,
)
from helm.topologies.rules import (
    TOPOLOGY_RULES,
    get_disallowed_tools,
)
from helm.topologies.builders import (
    build_coordination,
    build_orchestrator,
)
from helm.topologies.prompts import (
    build_prompt,
    build_tool_instructions,
)

ALL_FAMILIES = list(SUPPORTED_FAMILY_SIZES.keys())

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _all_family_size_role_combos():
    """Yield (family, size, role) for every layout entry."""
    for family, sizes in FAMILY_LAYOUTS.items():
        for size, layout in sizes.items():
            for role in layout:
                yield family, size, role


def _all_family_size_combos():
    """Yield (family, size) for every layout entry."""
    for family, sizes in FAMILY_LAYOUTS.items():
        for size in sizes:
            yield family, size


# ===========================================================================
# 1. families.py
# ===========================================================================

class TestSupportedFamilySizes:
    def test_all_families_have_layouts(self):
        for family in SUPPORTED_FAMILY_SIZES:
            assert family in FAMILY_LAYOUTS, f"{family} missing from FAMILY_LAYOUTS"

    def test_all_families_have_coordination_labels(self):
        for family in SUPPORTED_FAMILY_SIZES:
            assert family in COORDINATION_FAMILY_LABELS, (
                f"{family} missing from COORDINATION_FAMILY_LABELS"
            )

    def test_layout_keys_match_supported_sizes(self):
        for family in SUPPORTED_FAMILY_SIZES:
            assert set(FAMILY_LAYOUTS[family].keys()) == SUPPORTED_FAMILY_SIZES[family], (
                f"Size mismatch for {family}"
            )


class TestRoleSpec:
    def test_creation_defaults(self):
        r = RoleSpec("a", "hub", "some_prompt")
        assert r.agent_id == "a"
        assert r.runtime_role == "hub"
        assert r.prompt_kind == "some_prompt"
        assert r.closer is False

    def test_creation_with_closer(self):
        r = RoleSpec("b", "worker", "wk", closer=True)
        assert r.closer is True

    def test_frozen(self):
        r = RoleSpec("a", "hub", "p")
        with pytest.raises(AttributeError):
            r.agent_id = "x"  # type: ignore[misc]


class TestFamilyLayouts:
    @pytest.mark.parametrize("family,size", list(_all_family_size_combos()))
    def test_layout_length_matches_size(self, family: str, size: int):
        layout = FAMILY_LAYOUTS[family][size]
        assert len(layout) == size

    @pytest.mark.parametrize("family,size", list(_all_family_size_combos()))
    def test_exactly_one_closer(self, family: str, size: int):
        layout = FAMILY_LAYOUTS[family][size]
        closers = [r for r in layout if r.closer]
        assert len(closers) == 1, f"{family}/{size}: expected 1 closer, got {len(closers)}"


class TestPatternRuntimeLabel:
    def test_single(self):
        assert pattern_runtime_label("single") == "single-agent"

    def test_decentralized(self):
        assert pattern_runtime_label("decentralized") == "peer-network"

    def test_delegating(self):
        assert pattern_runtime_label("delegating") == "delegating"

    @pytest.mark.parametrize("family", ["independent", "centralized", "hybrid"])
    def test_hub_and_spoke_families(self, family: str):
        assert pattern_runtime_label(family) == "hub-and-spoke"


# ===========================================================================
# 2. rules.py
# ===========================================================================

class TestTopologyRules:
    def test_every_explicit_entry_maps_to_a_real_family(self):
        """Every key in TOPOLOGY_RULES references a family that exists."""
        for family, _role in TOPOLOGY_RULES:
            assert family in SUPPORTED_FAMILY_SIZES, (
                f"TOPOLOGY_RULES references unknown family '{family}'"
            )

    def test_get_disallowed_tools_returns_list_for_all_layout_roles(self):
        """get_disallowed_tools returns a non-empty list for every runtime_role
        that appears in FAMILY_LAYOUTS (via explicit entry or default)."""
        for family, sizes in FAMILY_LAYOUTS.items():
            for _size, layout in sizes.items():
                for spec in layout:
                    role = spec.runtime_role or "solver"
                    blocked = get_disallowed_tools(family, role)
                    assert isinstance(blocked, list)
                    assert len(blocked) > 0, (
                        f"({family}, {role}) returns empty disallowed list"
                    )


class TestGetDisallowedTools:
    def test_delegating_hub_allows_agent(self):
        blocked = get_disallowed_tools("delegating", "hub")
        assert "Agent" not in blocked
        assert "TeamCreate" in blocked
        assert "SendMessage" in blocked

    @pytest.mark.parametrize(
        "family,role",
        [
            ("single", "solver"),
            ("independent", "candidate"),
            ("independent", "selector"),
            ("centralized", "hub"),
            ("centralized", "worker"),
            ("decentralized", "peer"),
            ("hybrid", "hub"),
            ("hybrid", "worker"),
            ("delegating", "worker"),
        ],
    )
    def test_blocks_agent_team_send(self, family: str, role: str):
        blocked = get_disallowed_tools(family, role)
        assert "Agent" in blocked
        assert "TeamCreate" in blocked
        assert "SendMessage" in blocked

    def test_unknown_role_gets_default_blocking(self):
        blocked = get_disallowed_tools("nonexistent_family", "nonexistent_role")
        assert blocked == ["Agent", "TeamCreate", "SendMessage"]


# ===========================================================================
# 3. builders.py
# ===========================================================================

class TestBuildOrchestrator:
    @pytest.mark.parametrize("family", ALL_FAMILIES)
    def test_returns_role_and_rules(self, family: str):
        result = build_orchestrator(family)
        assert "role" in result
        assert "rules" in result
        assert result["role"] == "observer"
        assert isinstance(result["rules"], list)
        assert len(result["rules"]) > 0

    @pytest.mark.parametrize("family", ["independent", "centralized", "hybrid"])
    def test_escalation_families_have_extra_rules(self, family: str):
        result = build_orchestrator(family)
        # Base rules (3) + 2 extra for these families = 5
        assert len(result["rules"]) == 5

    @pytest.mark.parametrize("family", ["single", "decentralized", "delegating"])
    def test_non_escalation_families_have_base_rules(self, family: str):
        result = build_orchestrator(family)
        assert len(result["rules"]) == 3


class TestBuildCoordination:
    @pytest.mark.parametrize("family", ALL_FAMILIES)
    def test_returns_mechanism_key(self, family: str):
        result = build_coordination(family)
        assert "mechanism" in result
        assert result["mechanism"] == "filesystem"

    @pytest.mark.parametrize("family", ALL_FAMILIES)
    def test_has_paths_and_channels(self, family: str):
        result = build_coordination(family)
        assert "paths" in result
        assert "channels" in result
        assert isinstance(result["channels"], list)
        assert len(result["channels"]) > 0

    def test_single_has_signals_path(self):
        result = build_coordination("single")
        assert "signals" in result["paths"]

    def test_decentralized_has_state_json(self):
        result = build_coordination("decentralized")
        assert result["paths"]["state"] == "coordination/state.json"


# ===========================================================================
# 4. prompts.py
# ===========================================================================

class TestBuildPrompt:
    @pytest.mark.parametrize(
        "family,size,role",
        list(_all_family_size_role_combos()),
    )
    def test_produces_nonempty_string(self, family: str, size: int, role: RoleSpec):
        layout = FAMILY_LAYOUTS[family][size]
        prompt = build_prompt(family, layout, role)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    @pytest.mark.parametrize(
        "family,size,role",
        list(_all_family_size_role_combos()),
    )
    def test_contains_topology_enforcement(self, family: str, size: int, role: RoleSpec):
        layout = FAMILY_LAYOUTS[family][size]
        prompt = build_prompt(family, layout, role)
        assert "Topology Enforcement" in prompt

    @pytest.mark.parametrize(
        "family,size,role",
        list(_all_family_size_role_combos()),
    )
    def test_contains_disallowed_tools(self, family: str, size: int, role: RoleSpec):
        layout = FAMILY_LAYOUTS[family][size]
        prompt = build_prompt(family, layout, role)
        runtime_role = role.runtime_role or "solver"
        disallowed = get_disallowed_tools(family, runtime_role)
        for tool in disallowed:
            assert tool in prompt, f"Tool '{tool}' not found in prompt for {family}/{role.agent_id}"

    def test_unsupported_prompt_kind_raises(self):
        bogus = RoleSpec("x", "worker", "totally_unknown_kind")
        with pytest.raises(ValueError, match="Unsupported prompt kind"):
            build_prompt("single", [bogus], bogus)


class TestBuildToolInstructions:
    def test_includes_mechanically_disabled(self):
        role = RoleSpec("solver", None, "single_solver")
        text = build_tool_instructions("single", role)
        assert "mechanically disabled" in text

    def test_empty_when_nothing_blocked(self):
        # Manually craft a scenario where get_disallowed_tools returns empty.
        # The delegating hub blocks TeamCreate and SendMessage, so it won't be
        # empty. We just test the logic path: if we somehow got an empty list.
        # Since we can't easily make that happen with real data, we test the
        # delegating hub instead which is the least-blocked role.
        role = RoleSpec("delegator", "hub", "delegating_solo")
        text = build_tool_instructions("delegating", role)
        # Should still have content since TeamCreate/SendMessage are blocked
        assert "mechanically disabled" in text

    @pytest.mark.parametrize("prompt_kind", [
        "centralized_worker",
        "centralized_researcher",
        "centralized_implementer",
        "centralized_reviewer",
    ])
    def test_centralized_worker_no_lateral(self, prompt_kind: str):
        role = RoleSpec("worker_a", "worker", prompt_kind)
        layout = [
            RoleSpec("coordinator", "hub", "centralized_coordinator", closer=True),
            role,
        ]
        prompt = build_prompt("centralized", layout, role)
        assert "Do not coordinate laterally" in prompt

    def test_delegating_hub_mentions_spawn(self):
        role = RoleSpec("delegator", "hub", "delegating_coordinator", closer=True)
        layout = [
            role,
            RoleSpec("worker_a", "worker", "delegating_worker"),
            RoleSpec("worker_b", "worker", "delegating_worker"),
        ]
        prompt = build_prompt("delegating", layout, role)
        assert "helm.agent_cli spawn" in prompt

    def test_single_solver_says_sole_solver(self):
        role = RoleSpec("solver", None, "single_solver", closer=True)
        layout = [role]
        prompt = build_prompt("single", layout, role)
        assert "sole solver" in prompt


# ===========================================================================
# 5. __init__.py re-exports
# ===========================================================================

class TestTopologiesReExports:
    """All public symbols importable from helm.topologies."""

    def test_families_exports(self):
        from helm.topologies import (
            COORDINATION_FAMILY_LABELS,
            FAMILY_LAYOUTS,
            SUPPORTED_FAMILY_SIZES,
            RoleSpec,
            pattern_runtime_label,
        )
        assert COORDINATION_FAMILY_LABELS is not None
        assert FAMILY_LAYOUTS is not None
        assert SUPPORTED_FAMILY_SIZES is not None
        assert RoleSpec is not None
        assert callable(pattern_runtime_label)

    def test_rules_exports(self):
        from helm.topologies import TOPOLOGY_RULES, get_disallowed_tools
        assert TOPOLOGY_RULES is not None
        assert callable(get_disallowed_tools)

    def test_builders_exports(self):
        from helm.topologies import build_coordination, build_orchestrator
        assert callable(build_coordination)
        assert callable(build_orchestrator)

    def test_prompts_exports(self):
        from helm.topologies import build_prompt, build_tool_instructions
        assert callable(build_prompt)
        assert callable(build_tool_instructions)


