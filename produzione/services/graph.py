"""Algoritmi senza database per esplorare grafi materiali anche non validi."""
from collections import defaultdict, deque
from django.core.exceptions import ValidationError


def validate_limit(value):
    if type(value) is not int or not 1 <= value <= 10000:
        raise ValidationError("max_lotti deve essere un intero tra 1 e 10000.")


def walk_lots(start, neighbors, max_lotti):
    validate_limit(max_lotti)
    visited, frontier, omitted = {start}, {start}, set()
    while frontier:
        candidates = set(neighbors(frontier)) - visited
        room = max_lotti - len(visited)
        selected = set(sorted(candidates)[:room])
        omitted.update(candidates - selected)
        visited.update(selected)
        frontier = selected
    return visited, omitted


def has_cycle(edges):
    adjacency, indegree = defaultdict(set), defaultdict(int)
    for source, target in edges:
        indegree.setdefault(source, 0)
        if target not in adjacency[source]:
            adjacency[source].add(target)
            indegree[target] += 1
    queue = deque(node for node, count in indegree.items() if count == 0)
    removed = 0
    while queue:
        node = queue.popleft()
        removed += 1
        for target in adjacency[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    return removed != len(indegree)
