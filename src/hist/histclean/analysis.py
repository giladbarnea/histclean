from __future__ import annotations

import difflib
import re
from collections import defaultdict
from collections.abc import Callable, Iterator

from .core import (
    HISTORY_ENTRY_RE,
    BaseFlag,
    ClusterFlag,
    DuplicateFlag,
    HistoryAnalysis,
    IndividualFlag,
    parse_history_entries,
    remove_timestamp_from_entry,
)

IndividualCleaningStrategy = Callable[[list[list[str]]], Iterator[tuple[int, str]]]
ClusterCleaningStrategy = Callable[[list[list[str]]], Iterator[tuple[int, int]]]

BLACKLIST_PATTERNS = [
    re.compile(r"--version\s*$"),
    re.compile(r"[א-ת]+"),
    re.compile(r"[^\x20-\x7E\t]+"),
    re.compile(r"^ *\n?$"),
    re.compile(r"^.$", re.DOTALL),
]

JACCARD_SIMILARITY_THRESHOLD = 0.5
DIFFLIB_SIMILARITY_THRESHOLD = 0.75
MAX_CLUSTER_LOOKAHEAD = 2


class Config:
    """Configuration for the cleaning pipeline."""

    @property
    def individual_strategies(self) -> list[IndividualCleaningStrategy]:
        return [
            flag_individual_multiline,
            flag_individual_empty,
            flag_individual_blacklist,
            flag_individual_orphaned_backslash,
        ]

    @property
    def cluster_strategies(self) -> list[tuple[ClusterCleaningStrategy, str]]:
        return [
            (flag_cluster_jaccard_similarity, "Consecutive similar entries (Jaccard)"),
            (flag_cluster_difflib_similarity, "Consecutive similar entries (difflib)"),
        ]

    @property
    def duplicate_strategy(self) -> Callable[[list[list[str]]], Iterator[list[int]]]:
        return flag_duplicate_groups


CONFIG = Config()


def flag_individual_multiline(
    all_entries: list[list[str]],
) -> Iterator[tuple[int, str]]:
    """Flag multi-line entries."""
    for index, entry_block in enumerate(all_entries):
        if len(entry_block) > 1:
            yield index, "It is a multi-line entry."


def flag_individual_empty(all_entries: list[list[str]]) -> Iterator[tuple[int, str]]:
    """Flag empty entries."""
    for index, entry_block in enumerate(all_entries):
        first_line_command = remove_timestamp_from_entry(entry_block)
        if not first_line_command.strip():
            yield index, "It is an empty entry."


def flag_individual_blacklist(
    all_entries: list[list[str]],
) -> Iterator[tuple[int, str]]:
    """Flag entries matching blacklist patterns."""
    for index, entry_block in enumerate(all_entries):
        command = remove_timestamp_from_entry(entry_block)
        if match := next(
            (pattern.search(command) for pattern in BLACKLIST_PATTERNS), None
        ):
            yield index, f"Matches '{match.group()}'"


def flag_individual_orphaned_backslash(
    all_entries: list[list[str]],
) -> Iterator[tuple[int, str]]:
    """Flag entries ending with a backslash without a continuation."""
    for index, entry_block in enumerate(all_entries):
        command = remove_timestamp_from_entry(entry_block)
        if not command.rstrip().endswith("\\"):
            continue
        if index + 1 >= len(all_entries):
            continue
        next_entry_block = all_entries[index + 1]
        if next_entry_block and HISTORY_ENTRY_RE.match(next_entry_block[0]):
            yield (
                index,
                "Entry ends with orphaned backslash (line continuation not found)",
            )


def flag_duplicate_groups(all_entries: list[list[str]]) -> Iterator[list[int]]:
    """Group duplicate commands and yield their entry indices."""
    command_to_indices: dict[str, list[int]] = defaultdict(list)
    for index, entry_block in enumerate(all_entries):
        command = remove_timestamp_from_entry(entry_block).strip()
        if command:
            command_to_indices[command].append(index)

    for indices in command_to_indices.values():
        if len(indices) > 1:
            yield sorted(indices)


def are_commands_similar_jaccard(command_one: str, command_two: str) -> bool:
    """Return whether two commands are similar by token Jaccard similarity."""
    tokens_one = set(re.split(r"[/ \s]+", command_one))
    tokens_two = set(re.split(r"[/ \s]+", command_two))
    intersection = tokens_one.intersection(tokens_two)
    union = tokens_one.union(tokens_two)
    if not union:
        return True
    jaccard_similarity = len(intersection) / len(union)
    return jaccard_similarity >= JACCARD_SIMILARITY_THRESHOLD


def are_commands_similar_difflib(command_one: str, command_two: str) -> bool:
    """Return whether two commands are similar by token difflib ratio."""
    if not command_one.strip() or not command_two.strip():
        return False

    tokens_one = set(re.split(r"[/ \s]+", command_one))
    tokens_two = set(re.split(r"[/ \s]+", command_two))
    if not tokens_one or not tokens_two:
        return False

    intersection = tokens_one.intersection(tokens_two)
    diff_one_to_two = tokens_one.difference(tokens_two)
    diff_two_to_one = tokens_two.difference(tokens_one)

    sorted_intersection = " ".join(sorted(intersection))
    sorted_diff_one_to_two = " ".join(sorted(diff_one_to_two))
    sorted_diff_two_to_one = " ".join(sorted(diff_two_to_one))

    first_comparison = f"{sorted_intersection} {sorted_diff_one_to_two}".strip()
    second_comparison = f"{sorted_intersection} {sorted_diff_two_to_one}".strip()

    ratio_one = difflib.SequenceMatcher(None, sorted_intersection, first_comparison).ratio()
    ratio_two = difflib.SequenceMatcher(None, sorted_intersection, second_comparison).ratio()
    ratio_three = difflib.SequenceMatcher(None, first_comparison, second_comparison).ratio()

    return max(ratio_one, ratio_two, ratio_three) >= DIFFLIB_SIMILARITY_THRESHOLD


def flag_cluster_jaccard_similarity(
    all_entries: list[list[str]],
) -> Iterator[tuple[int, int]]:
    """Group similar commands using Jaccard similarity with lookahead."""
    commands = [remove_timestamp_from_entry(entry).strip() for entry in all_entries]
    if len(commands) < 2:
        return

    index = 0
    while index < len(commands):
        current_cluster_indices = [index]
        last_successful_match_index = index
        for candidate_index in range(index + 1, len(commands)):
            if candidate_index - last_successful_match_index > MAX_CLUSTER_LOOKAHEAD:
                break
            is_similar_to_cluster = False
            for cluster_member_index in current_cluster_indices:
                command_one = commands[cluster_member_index]
                command_two = commands[candidate_index]
                if command_one and command_two and are_commands_similar_jaccard(
                    command_one, command_two
                ):
                    is_similar_to_cluster = True
                    break
            if not is_similar_to_cluster:
                continue
            current_cluster_indices.extend(
                range(last_successful_match_index + 1, candidate_index + 1)
            )
            last_successful_match_index = candidate_index
        if len(current_cluster_indices) > 1:
            yield current_cluster_indices[0], current_cluster_indices[-1]
            index = current_cluster_indices[-1] + 1
            continue
        index += 1


def flag_cluster_difflib_similarity(
    all_entries: list[list[str]],
) -> Iterator[tuple[int, int]]:
    """Group similar commands using adjacent difflib checks."""
    commands = [remove_timestamp_from_entry(entry).strip() for entry in all_entries]
    if len(commands) < 2:
        return

    index = 0
    while index < len(commands) - 1:
        next_index = index
        while (
            next_index < len(commands) - 1
            and commands[next_index]
            and commands[next_index + 1]
            and are_commands_similar_difflib(
                commands[next_index], commands[next_index + 1]
            )
        ):
            next_index += 1
        if next_index > index:
            yield index, next_index
            index = next_index + 1
            continue
        index += 1


def merge_flagged_entries(flagged_entries: list[BaseFlag]) -> list[BaseFlag]:
    """Merge and de-duplicate flags."""
    if not flagged_entries:
        return []

    individual_flags: dict[int, IndividualFlag] = {}
    cluster_flags: list[ClusterFlag] = []
    duplicate_flags: list[DuplicateFlag] = []

    for entry in flagged_entries:
        if isinstance(entry, IndividualFlag):
            if entry.entry_index in individual_flags:
                existing_reasons = individual_flags[entry.entry_index].reason_text
                new_reasons = entry.reason_text
                individual_flags[
                    entry.entry_index
                ].reason_text = f"{existing_reasons}\n{new_reasons}"
                continue
            individual_flags[entry.entry_index] = entry
            continue
        if isinstance(entry, ClusterFlag):
            cluster_flags.append(entry)
            continue
        if isinstance(entry, DuplicateFlag):
            duplicate_flags.append(entry)

    merged_clusters: list[ClusterFlag] = []
    if cluster_flags:
        cluster_flags.sort(key=lambda flag: flag.start_index)
        current_cluster = cluster_flags[0]
        for next_cluster in cluster_flags[1:]:
            if next_cluster.start_index <= current_cluster.end_index + 1:
                current_cluster.end_index = max(
                    current_cluster.end_index, next_cluster.end_index
                )
                if next_cluster.reason_text not in current_cluster.reason_text:
                    current_cluster.reason_text += f" / {next_cluster.reason_text}"
                continue
            merged_clusters.append(current_cluster)
            current_cluster = next_cluster
        merged_clusters.append(current_cluster)

    final_flags: list[BaseFlag] = list(merged_clusters)
    cluster_removed_indices: set[int] = set()
    for cluster in merged_clusters:
        cluster_removed_indices.update(cluster.get_indices_to_remove())

    kept_individual_indices = {
        index for index in individual_flags if index not in cluster_removed_indices
    }

    for index, individual_flag in individual_flags.items():
        if index in kept_individual_indices:
            final_flags.append(individual_flag)

    for duplicate_flag in duplicate_flags:
        valid_indices = [
            index
            for index in duplicate_flag.entry_indices
            if index not in cluster_removed_indices and index not in kept_individual_indices
        ]
        if len(valid_indices) > 1:
            duplicate_flag.entry_indices = valid_indices
            final_flags.append(duplicate_flag)

    return sorted(final_flags, key=lambda flag: flag.get_sort_key())


def filter_flags_by_hist_keep(
    flagged_entries: list[BaseFlag], all_entries: list[list[str]]
) -> list[BaseFlag]:
    """Filter out flags that target entries marked with # !keep."""

    def has_hist_keep(index: int) -> bool:
        if index >= len(all_entries):
            return False
        command = remove_timestamp_from_entry(all_entries[index])
        return bool(re.search(r"#\s*!keep\b", command, re.IGNORECASE))

    filtered_flags: list[BaseFlag] = []

    for flag in flagged_entries:
        if isinstance(flag, IndividualFlag):
            if not has_hist_keep(flag.entry_index):
                filtered_flags.append(flag)
            continue

        if isinstance(flag, ClusterFlag):
            indices_to_remove = set(range(flag.start_index, flag.end_index))
            hist_keep_indices = {
                index for index in indices_to_remove if has_hist_keep(index)
            }
            if hist_keep_indices != indices_to_remove:
                filtered_flags.append(flag)
            continue

        if isinstance(flag, DuplicateFlag):
            non_hist_keep_indices = [
                index for index in flag.entry_indices if not has_hist_keep(index)
            ]
            if len(non_hist_keep_indices) > 1:
                flag.entry_indices = non_hist_keep_indices
                filtered_flags.append(flag)

    return filtered_flags


def calculate_indices_to_remove(
    approved_flags: list[BaseFlag], all_entries: list[list[str]]
) -> set[int]:
    """Convert approved flags into entry indices to remove."""
    indices_to_remove: set[int] = set()
    for flag in approved_flags:
        indices_to_remove.update(flag.get_indices_to_remove())

    filtered_indices: set[int] = set()
    for index in indices_to_remove:
        if index < len(all_entries):
            command = remove_timestamp_from_entry(all_entries[index])
            if not re.search(r"#\s*!keep\b", command, re.IGNORECASE):
                filtered_indices.add(index)
            continue
        filtered_indices.add(index)

    return filtered_indices


def analyze_history_lines(original_lines: list[str]) -> HistoryAnalysis:
    """Build the cleaning plan without mutating the history file."""
    if not [line for line in original_lines if line.strip()]:
        return HistoryAnalysis(
            original_lines=original_lines,
            all_entries=[],
            flagged_entries=[],
        )

    all_entries_with_lines = list(parse_history_entries(original_lines))
    all_entries = [block for _, block in all_entries_with_lines]
    entry_line_nums = [line_num for line_num, _ in all_entries_with_lines]
    max_line_num_width = len(str(len(original_lines)))

    flag_context = {
        "all_entries": all_entries,
        "entry_line_nums": entry_line_nums,
        "max_line_num_width": max_line_num_width,
    }

    pipeline_steps = [
        {
            "flag_class": IndividualFlag,
            "strategy": strategy,
        }
        for strategy in CONFIG.individual_strategies
    ]
    pipeline_steps.extend(
        {
            "flag_class": ClusterFlag,
            "strategy": strategy,
            "reason": reason,
        }
        for strategy, reason in CONFIG.cluster_strategies
    )
    pipeline_steps.append({
        "flag_class": DuplicateFlag,
        "strategy": CONFIG.duplicate_strategy,
        "reason": "Duplicate command; keeping the last instance",
    })

    raw_flagged_entries: list[BaseFlag] = []
    for step in pipeline_steps:
        flag_class = step["flag_class"]
        strategy = step["strategy"]
        reason = step.get("reason", "")

        for result in strategy(all_entries):
            if flag_class is IndividualFlag:
                index, single_reason = result
                flag = IndividualFlag(
                    entry_index=index,
                    reasons=[single_reason],
                    **flag_context,
                )
            elif flag_class is ClusterFlag:
                start_index, end_index = result
                flag = ClusterFlag(
                    start_index=start_index,
                    end_index=end_index,
                    reason_text=reason,
                    **flag_context,
                )
            elif flag_class is DuplicateFlag:
                indices = result
                flag = DuplicateFlag(
                    entry_indices=indices,
                    reason_text=reason,
                    **flag_context,
                )
            else:
                continue
            raw_flagged_entries.append(flag)

    merged_flagged_entries = merge_flagged_entries(raw_flagged_entries)
    final_flagged_entries = filter_flags_by_hist_keep(merged_flagged_entries, all_entries)
    return HistoryAnalysis(
        original_lines=original_lines,
        all_entries=all_entries,
        flagged_entries=final_flagged_entries,
    )
