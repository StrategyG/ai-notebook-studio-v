from uuid import uuid4

import pytest

from ai_notebook_api.domain.dependencies import (
    DelegationDepthExceeded,
    DependencyCycleError,
    validate_delegation_depth,
    validate_dependency_graph,
)


def test_dependency_graph_returns_dependencies_before_dependents() -> None:
    first, second, third = uuid4(), uuid4(), uuid4()
    ordered = validate_dependency_graph({first: set(), second: {first}, third: {first, second}})
    assert ordered.index(first) < ordered.index(second) < ordered.index(third)


def test_dependency_graph_rejects_cycles() -> None:
    first, second = uuid4(), uuid4()
    with pytest.raises(DependencyCycleError):
        validate_dependency_graph({first: {second}, second: {first}})


def test_dependency_graph_rejects_missing_nodes() -> None:
    first = uuid4()
    with pytest.raises(ValueError, match="outside the plan"):
        validate_dependency_graph({first: {uuid4()}})


def test_dependency_graph_rejects_excessive_depth() -> None:
    nodes = [uuid4() for _ in range(5)]
    graph = {nodes[0]: set()}
    for parent, child in zip(nodes, nodes[1:], strict=False):
        graph[child] = {parent}
    with pytest.raises(DelegationDepthExceeded):
        validate_dependency_graph(graph, max_depth=3)


def test_delegation_depth_limit_is_enforced() -> None:
    validate_delegation_depth(current_depth=3, max_depth=4)
    with pytest.raises(DelegationDepthExceeded):
        validate_delegation_depth(current_depth=4, max_depth=4)
