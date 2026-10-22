"""Dataset sequence discovery ignores folders whose name starts with a dot (issue #105).

The fetch commands create ``.downloads`` and ``.work`` inside the dataset root. They are not sequences, and a sweep
that tried to load one failed. One helper, :func:`navkit.euroc_eval.list_sequence_dirs`, lists the sequences, and the
six places that used to repeat the listing call it.

Hidden names sort before upper-case letters, so a caller that still lists them reaches them first. Each caller test
therefore only needs to see which name the loader is asked for first.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from navkit import euroc_eval, fault_classification, multipath_study, separability, slow_ramp, vision_ramp
from navkit.euroc_eval import list_sequence_dirs

NAMES = ["MH_01_easy", "MH_02_easy"]


def _root(tmp_path: Path, sequences: list[str] | None = None) -> Path:
    root = tmp_path / "euroc"
    root.mkdir()
    for name in NAMES if sequences is None else sequences:
        (root / name).mkdir()
    (root / ".downloads").mkdir()
    (root / ".work").mkdir()
    (root / "README.txt").write_text("not a sequence\n")
    return root


# --------------------------------------------------------------------------------------------- the helper


def test_the_helper_returns_the_sequences_sorted_and_nothing_else(tmp_path):
    assert list_sequence_dirs(_root(tmp_path, ["MH_02_easy", "MH_01_easy"])) == NAMES


def test_the_helper_accepts_a_string_and_a_path(tmp_path):
    root = _root(tmp_path)
    assert list_sequence_dirs(str(root)) == list_sequence_dirs(root) == NAMES


def test_a_symlinked_sequence_directory_is_returned_and_a_hidden_symlink_is_not(tmp_path):
    root = _root(tmp_path)
    target = tmp_path / "elsewhere" / "MH_03_medium"
    target.mkdir(parents=True)
    (root / "MH_03_medium").symlink_to(target, target_is_directory=True)
    (root / ".hidden_link").symlink_to(target, target_is_directory=True)
    assert list_sequence_dirs(root) == [*NAMES, "MH_03_medium"]


def test_a_symlink_to_a_file_and_a_broken_symlink_are_not_sequences(tmp_path):
    root = _root(tmp_path)
    (root / "file_link").symlink_to(root / "README.txt")
    (root / "broken_link").symlink_to(tmp_path / "missing", target_is_directory=True)
    assert list_sequence_dirs(root) == NAMES


def test_a_root_with_only_hidden_folders_has_no_sequences(tmp_path):
    assert list_sequence_dirs(_root(tmp_path, [])) == []


def test_a_missing_root_raises_file_not_found_error_and_names_the_path(tmp_path):
    missing = tmp_path / "no" / "such" / "root"
    with pytest.raises(FileNotFoundError) as info:
        list_sequence_dirs(missing)
    # The error carries the path it was given. The text of the message quotes it with escaped backslashes on
    # Windows, so the attribute is compared and not the text.
    assert os.fspath(info.value.filename) == os.fspath(missing)
    assert info.value.filename is not None


def test_a_root_that_is_a_file_raises_what_the_callers_raised_before(tmp_path):
    file = tmp_path / "root.txt"
    file.write_text("x")
    with pytest.raises(NotADirectoryError):
        list_sequence_dirs(file)
    with pytest.raises(NotADirectoryError):
        os.listdir(file)  # the behaviour the six listings had


# -------------------------------------------------------------------------------------------- the callers


class _Reached(Exception):
    """Raised by the fake loader on its first call, carrying the sequence name it was asked for."""


def _first_name(monkeypatch, module, call):
    """The sequence name that ``call`` asks the loader for first, with the module's ``dataset_loader`` replaced."""

    def loader(root, name):
        raise _Reached(name)

    monkeypatch.setattr(module, "dataset_loader", lambda dataset: (loader, "unused"))
    with pytest.raises(_Reached) as info:
        call()
    return str(info.value)


CALLERS = {
    "fault_classification.sweep_rows": (
        fault_classification,
        lambda root: fault_classification.sweep_rows("euroc", root, 1),
    ),
    "fault_classification.confirm_sweep": (
        fault_classification,
        lambda root: fault_classification.confirm_sweep("euroc", root),
    ),
    "multipath_study.sweep_rows": (
        multipath_study,
        lambda root: multipath_study.sweep_rows("euroc", root, (("white", 1.0),), (0,)),
    ),
    "separability.honest_rows": (separability, lambda root: separability.honest_rows("euroc", root, ("shipped",), 1)),
    "slow_ramp.sweep_rows": (slow_ramp, lambda root: slow_ramp.sweep_rows("euroc", root, ("shipped",), 1)),
    "vision_ramp.sweep_rows": (vision_ramp, lambda root: vision_ramp.sweep_rows("euroc", root, ("shipped",), 1)),
}


@pytest.mark.parametrize("name", sorted(CALLERS))
def test_a_caller_asks_for_the_first_real_sequence_and_never_a_hidden_folder(name, tmp_path, monkeypatch):
    module, call = CALLERS[name]
    root = _root(tmp_path)
    assert _first_name(monkeypatch, module, lambda: call(root)) == "MH_01_easy"


@pytest.mark.parametrize("name", sorted(CALLERS))
def test_a_caller_with_one_stub_next_to_hidden_folders_reaches_the_stub(name, tmp_path, monkeypatch):
    module, call = CALLERS[name]
    root = _root(tmp_path, ["V1_01_easy"])
    assert _first_name(monkeypatch, module, lambda: call(root)) == "V1_01_easy"


@pytest.mark.parametrize("name", sorted(CALLERS))
def test_a_caller_with_only_hidden_folders_loads_nothing(name, tmp_path, monkeypatch):
    module, call = CALLERS[name]
    root = _root(tmp_path, [])
    calls: list[str] = []

    def loader(root, name):
        calls.append(name)
        raise AssertionError("no sequence should be loaded")

    monkeypatch.setattr(module, "dataset_loader", lambda dataset: (loader, "unused"))
    try:
        call(root)
    except Exception as exc:  # what a caller does with no sequences is its own business; it must not load a hidden one
        assert not isinstance(exc, AssertionError), exc
    assert calls == []


def test_no_caller_lists_the_directories_itself_any_more():
    """The six listings are the helper now; a new copy of the expression would bring the bug back."""
    src = Path(euroc_eval.__file__).resolve().parent
    offenders = []
    for path in sorted(src.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "os.listdir(root)" in text and path.name != "euroc_eval.py":
            offenders.append(path.name)
    assert offenders == []
