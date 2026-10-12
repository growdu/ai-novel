"""diff 工具：对比两版章节，输出 unified diff。"""
import difflib


def unified_diff(old_text, new_text, fromfile="old", tofile="new", n=3):
    if not old_text:
        old_text = ""
    if not new_text:
        new_text = ""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile, n=n, lineterm="")
    return "".join(diff)


def stats_diff(old_text, new_text):
    if not old_text and not new_text:
        return {"added": 0, "removed": 0, "same": 0, "similarity": 1.0}
    old_lines = set(old_text.splitlines())
    new_lines = set(new_text.splitlines())
    added = new_lines - old_lines
    removed = old_lines - new_lines
    same = old_lines & new_lines
    total = len(added) + len(removed) + len(same)
    similarity = len(same) / total if total else 1.0
    return {
        "added": len(added),
        "removed": len(removed),
        "same": len(same),
        "similarity": similarity,
    }
