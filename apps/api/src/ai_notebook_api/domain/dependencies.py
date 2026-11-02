from __future__ import annotations

from collections.abc import Mapping, Set
from uuid import UUID


class DependencyCycleError(ValueError):
    pass


class DelegationDepthExceeded(ValueError):
    pass


def validate_dependency_graph(
    graph: Mapping[UUID, Set[UUID]], *, max_depth: int = 32
) -> list[UUID]:
    """Return a deterministic topological order and enforce longest-path depth."""
    if max_depth < 1:
        raise ValueError("max_depth must be at least 1")
    nodes = set(graph)
    for task_id, dependencies in graph.items():
        missing = set(dependencies) - nodes
        if missing:
            raise ValueError(
                f"task {task_id} references dependencies outside the plan: "
                f"{sorted(map(str, missing))}"
            )

    visiting: set[UUID] = set()
    longest_depth: dict[UUID, int] = {}
    ordered: list[UUID] = []

    def visit(node: UUID) -> int:
        if node in visiting:
            raise DependencyCycleError(f"dependency cycle includes task {node}")
        if node in longest_depth:
            return longest_depth[node]

        visiting.add(node)
        dependency_depths = [visit(dependency) for dependency in sorted(graph[node], key=str)]
        visiting.remove(node)

        depth = 1 + max(dependency_depths, default=0)
        if depth > max_depth:
            raise DelegationDepthExceeded(f"task dependency depth exceeds {max_depth}")

        longest_depth[node] = depth
        ordered.append(node)
        return depth

    for node in sorted(nodes, key=str):
        visit(node)
    return ordered


def validate_delegation_depth(*, current_depth: int, max_depth: int = 8) -> None:
    if max_depth < 1 or current_depth < 0:
        raise ValueError("delegation depths must be non-negative and max_depth must be positive")
    if current_depth >= max_depth:
        raise DelegationDepthExceeded(f"delegation depth limit {max_depth} reached")
