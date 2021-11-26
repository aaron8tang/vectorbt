# Copyright (c) 2021 Oleg Polakow. All rights reserved.
# This code is licensed under Apache 2.0 with Commons Clause license (see LICENSE.md for details)

"""Utilities for working with templates."""

from copy import copy
from string import Template

import numpy as np
import pandas as pd

import vectorbt as vbt
from vectorbt import _typing as tp
from vectorbt.utils import checks
from vectorbt.utils.config import set_dict_item, merge_dicts
from vectorbt.utils.docs import SafeToStr, prepare_for_doc
from vectorbt.utils.hashing import Hashable
from vectorbt.utils.parsing import get_func_arg_names


class CustomTemplate(Hashable, SafeToStr):
    """Base class for substituting templates."""

    def __init__(self,
                 template: tp.Any,
                 mapping: tp.Optional[tp.Mapping] = None,
                 strict: tp.Optional[bool] = None,
                 sub_id: tp.Optional[tp.MaybeCollection[Hashable]] = None) -> None:
        self._template = template
        if mapping is None:
            mapping = {}
        self._mapping = mapping
        self._strict = strict
        self._sub_id = sub_id

    @property
    def template(self) -> tp.Any:
        """Template to be processed."""
        return self._template

    @property
    def mapping(self) -> tp.Mapping:
        """Mapping object passed to the initializer."""
        return self._mapping

    @property
    def strict(self) -> tp.Optional[bool]:
        """Whether to raise an error if processing template fails.

        If not None, overrides `strict` passed by `deep_substitute`."""
        return self._strict

    @property
    def sub_id(self) -> tp.Optional[tp.MaybeCollection[Hashable]]:
        """Substitution id or ids at which to evaluate this template

        Checks against `sub_id` passed by `deep_substitute`."""
        return self._sub_id

    def meets_sub_id(self, sub_id: tp.Optional[Hashable] = None) -> bool:
        """Return whether the substitution id of the template meets the global substitution id."""
        if self.sub_id is not None and sub_id is not None:
            if isinstance(self.sub_id, int):
                if sub_id != self.sub_id:
                    return False
            else:
                if sub_id not in self.sub_id:
                    return False
        return True

    def resolve_mapping(self, mapping: tp.Optional[tp.Mapping] = None,
                        sub_id: tp.Optional[Hashable] = None) -> tp.Kwargs:
        """Resolve `CustomTemplate.mapping`.

        Merges `template.mapping` in `vectorbt._settings.settings`, `CustomTemplate.mapping`, and `mapping`.
        Automatically appends `sub_id`, `np` (NumPy), `pd` (Pandas), and `vbt` (vectorbt)."""
        from vectorbt._settings import settings
        template_cfg = settings['template']

        return merge_dicts(
            template_cfg['mapping'],
            dict(
                sub_id=sub_id,
                np=np,
                pd=pd,
                vbt=vbt
            ),
            self.mapping,
            mapping
        )

    def resolve_strict(self, strict: tp.Optional[bool] = None) -> bool:
        """Resolve `CustomTemplate.strict`.

        If `strict` is None, uses `template.strict` in `vectorbt._settings.settings`."""
        if strict is None:
            strict = self.strict
        if strict is None:
            from vectorbt._settings import settings
            template_cfg = settings['template']

            strict = template_cfg['strict']
        return strict

    def substitute(self,
                   mapping: tp.Optional[tp.Mapping] = None,
                   strict: tp.Optional[bool] = None,
                   sub_id: tp.Optional[Hashable] = None) -> tp.Any:
        """Abstract method to substitute the template `CustomTemplate.template` using
        the mapping from merging `CustomTemplate.mapping` and `mapping`."""
        raise NotImplementedError

    @property
    def hash_key(self) -> tuple:
        return (
            self.template,
            tuple(self.mapping.items()),
            self.strict,
            self.sub_id if (self.sub_id is None or isinstance(self.sub_id, int)) else tuple(self.sub_id)
        )

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(" \
               f"template=\"{self.template}\", " \
               f"mapping={prepare_for_doc(self.mapping)}, " \
               f"strict=\"{self.strict}\", " \
               f"sub_id={self.sub_id})"


class Sub(CustomTemplate):
    """Template string to substitute parts with the respective values from `mapping`.

    Always returns a string."""

    def substitute(self,
                   mapping: tp.Optional[tp.Mapping] = None,
                   strict: tp.Optional[bool] = None,
                   sub_id: tp.Optional[Hashable] = None) -> tp.Any:
        """Substitute parts of `Sub.template` as a regular template."""
        if not self.meets_sub_id(sub_id):
            return self
        mapping = self.resolve_mapping(mapping=mapping, sub_id=sub_id)
        strict = self.resolve_strict(strict=strict)

        try:
            return Template(self.template).substitute(mapping)
        except KeyError as e:
            if strict:
                raise e
        return self


class Rep(CustomTemplate):
    """Template string to be replaced with the respective value from `mapping`."""

    def substitute(self,
                   mapping: tp.Optional[tp.Mapping] = None,
                   strict: tp.Optional[bool] = None,
                   sub_id: tp.Optional[Hashable] = None) -> tp.Any:
        """Replace `Rep.template` as a key."""
        if not self.meets_sub_id(sub_id):
            return self
        mapping = self.resolve_mapping(mapping=mapping, sub_id=sub_id)
        strict = self.resolve_strict(strict=strict)

        try:
            return mapping[self.template]
        except KeyError as e:
            if strict:
                raise e
        return self


class RepEval(CustomTemplate):
    """Template expression to be evaluated with `mapping` used as locals."""

    def substitute(self,
                   mapping: tp.Optional[tp.Mapping] = None,
                   strict: tp.Optional[bool] = None,
                   sub_id: tp.Optional[Hashable] = None) -> tp.Any:
        """Evaluate `RepEval.template` as an expression."""
        if not self.meets_sub_id(sub_id):
            return self
        mapping = self.resolve_mapping(mapping=mapping, sub_id=sub_id)
        strict = self.resolve_strict(strict=strict)

        try:
            return eval(self.template, {}, mapping)
        except NameError as e:
            if strict:
                raise e
        return self


class RepFunc(CustomTemplate):
    """Template function to be called with argument names from `mapping`."""

    def substitute(self,
                   mapping: tp.Optional[tp.Mapping] = None,
                   strict: tp.Optional[bool] = None,
                   sub_id: int = 0) -> tp.Any:
        """Call `RepFunc.template` as a function."""
        if not self.meets_sub_id(sub_id):
            return self
        mapping = self.resolve_mapping(mapping=mapping, sub_id=sub_id)
        strict = self.resolve_strict(strict=strict)

        func_arg_names = get_func_arg_names(self.template)
        func_kwargs = dict()
        for k, v in mapping.items():
            if k in func_arg_names:
                func_kwargs[k] = v

        try:
            return self.template(**func_kwargs)
        except TypeError as e:
            if strict:
                raise e
        return self


def has_templates(obj: tp.Any) -> tp.Any:
    """Check if the object has any templates."""
    if isinstance(obj, (Template, CustomTemplate)):
        return True
    if isinstance(obj, dict):
        for k, v in obj.items():
            if has_templates(v):
                return True
    if isinstance(obj, (tuple, list, set, frozenset)):
        for v in obj:
            if has_templates(v):
                return True
    return False


def deep_substitute(obj: tp.Any,
                    mapping: tp.Optional[tp.Mapping] = None,
                    strict: tp.Optional[bool] = None,
                    make_copy: bool = True,
                    sub_id: tp.Optional[Hashable] = None) -> tp.Any:
    """Traverses the object recursively and, if any template found, substitutes it using a mapping.

    Traverses tuples, lists, dicts and (frozen-)sets. Does not look for templates in keys.

    If `strict` is True, raises an error if processing template fails. Otherwise, returns the original template.

    !!! note
        If the object is deep (such as a dict or a list), creates a copy of it if any template found inside,
        thus loosing the reference to the original. Make sure to do a deep or hybrid copy of the object
        before proceeding for consistent behavior, or disable `make_copy` to override the original in place.

    ## Example

    ```python-repl
    >>> import vectorbt as vbt

    >>> vbt.deep_substitute(vbt.Sub('$key', {'key': 100}))
    100
    >>> vbt.deep_substitute(vbt.Sub('$key', {'key': 100}), {'key': 200})
    200
    >>> vbt.deep_substitute(vbt.Sub('$key$key'), {'key': 100})
    100100
    >>> vbt.deep_substitute(vbt.Rep('key'), {'key': 100})
    100
    >>> vbt.deep_substitute([vbt.Rep('key'), vbt.Sub('$key$key')], {'key': 100})
    [100, '100100']
    >>> vbt.deep_substitute(vbt.RepFunc(lambda key: key == 100), {'key': 100})
    True
    >>> vbt.deep_substitute(vbt.RepEval('key == 100'), {'key': 100})
    True
    >>> vbt.deep_substitute(vbt.RepEval('key == 100', strict=True))
    NameError: name 'key' is not defined
    >>> vbt.deep_substitute(vbt.RepEval('key == 100', strict=False))
    <vectorbt.utils.template.RepEval at 0x7fe3ad2ab668>
    ```
    """
    if mapping is None:
        mapping = {}

    if not has_templates(obj):
        return obj

    if isinstance(obj, CustomTemplate):
        return obj.substitute(mapping=mapping, strict=strict, sub_id=sub_id)
    if isinstance(obj, Template):
        return obj.substitute(mapping=mapping)
    if isinstance(obj, dict):
        if make_copy:
            obj = copy(obj)
        for k, v in obj.items():
            set_dict_item(obj, k, deep_substitute(v, mapping=mapping, strict=strict, sub_id=sub_id), force=True)
        return obj
    if isinstance(obj, list):
        if make_copy:
            obj = copy(obj)
        for i in range(len(obj)):
            obj[i] = deep_substitute(obj[i], mapping=mapping, strict=strict, sub_id=sub_id)
        return obj
    if isinstance(obj, (tuple, set, frozenset)):
        result = []
        for o in obj:
            result.append(deep_substitute(o, mapping=mapping, strict=strict, sub_id=sub_id))
        if checks.is_namedtuple(obj):
            return type(obj)(*result)
        return type(obj)(result)
    return obj
