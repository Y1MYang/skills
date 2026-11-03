"""Filesystem equivalence for validated relative paths, including missing tails."""

from __future__ import annotations

import os
from pathlib import Path
import stat


class PathIdentityError(ValueError):
    def __init__(self, message: str, code: str = "path-identity-unknown"):
        super().__init__(message)
        self.code = code


def _stat(path: Path):
    try:
        return path.stat()
    except FileNotFoundError:
        return None


def _same_object(left, right) -> bool:
    if not left.st_ino or not right.st_ino:
        raise PathIdentityError("The filesystem did not provide a verifiable object identity.")
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _windows_case_sensitive(directory: Path) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(directory), 0, 7, None, 3, 0x02000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise PathIdentityError("Cannot inspect the directory naming semantics.")
    try:
        flags = wintypes.DWORD()
        if not kernel.GetFileInformationByHandleEx(handle, 23, ctypes.byref(flags), ctypes.sizeof(flags)):
            raise PathIdentityError("The filesystem did not provide directory case-sensitivity information.")
        return bool(flags.value & 1)
    finally:
        kernel.CloseHandle(handle)


def _windows_names_equal(left: str, right: str) -> bool:
    import ctypes
    from ctypes import wintypes

    compare = ctypes.WinDLL("kernel32", use_last_error=True).CompareStringOrdinal
    compare.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int, wintypes.BOOL]
    compare.restype = ctypes.c_int
    result = compare(left, -1, right, -1, True)
    if result == 0:
        raise PathIdentityError("Cannot compare filesystem component names.")
    return result == 2


def _common_prefix(root: Path, left: tuple, right: tuple, check) -> bool:
    parent = root
    case_sensitive = os.name != "nt"
    for left_name, right_name in zip(left, right):
        if check is not None:
            check()
        parent_info = _stat(parent)
        if parent_info is not None:
            if not stat.S_ISDIR(parent_info.st_mode):
                raise PathIdentityError("A declared path cannot descend through an ordinary file.", "invalid-path")
            if os.name == "nt":
                case_sensitive = _windows_case_sensitive(parent)
        left_path, right_path = parent / left_name, parent / right_name
        left_info, right_info = _stat(left_path), _stat(right_path)
        if left_name == right_name:
            equivalent = True
        elif left_info is not None and right_info is not None:
            equivalent = _same_object(left_info, right_info)
        elif case_sensitive:
            equivalent = left_name == right_name
        else:
            equivalent = _windows_names_equal(left_name, right_name)
        if not equivalent:
            return False
        # Once this parent is missing, retain the last existing ancestor's rule.
        parent = left_path if left_info is not None else right_path
    return True


def paths_equivalent(root, left: str, right: str, *, check=None) -> bool:
    root = Path(root)
    if check is not None:
        check()
    left_parts, right_parts = Path(left).parts, Path(right).parts
    if left_parts == right_parts:
        return True
    left_info, right_info = _stat(root / left), _stat(root / right)
    if left_info is not None and right_info is not None and _same_object(left_info, right_info):
        return True
    return len(left_parts) == len(right_parts) and _common_prefix(root, left_parts, right_parts, check)


def paths_overlap(root, left: str, right: str, *, check=None) -> bool:
    if paths_equivalent(root, left, right, check=check):
        return True
    return _common_prefix(Path(root), Path(left).parts, Path(right).parts, check)


def unique_paths(root, paths, *, reject_duplicates: bool = True, check=None) -> list[str]:
    """Keep first display spellings; reject aliases or treat inputs as a set."""
    unique = []
    for path in paths:
        if check is not None:
            check()
        duplicate = any(paths_equivalent(root, path, previous, check=check) for previous in unique)
        if duplicate:
            if reject_duplicates:
                raise PathIdentityError("Declared paths identify the same filesystem location.", "duplicate-path")
        else:
            unique.append(path)
    return unique
