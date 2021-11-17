# Copyright (c) 2021 Oleg Polakow. All rights reserved.
# This code is licensed under Apache 2.0 with Commons Clause license (see LICENSE.md for details)

"""Root pandas accessors.

An accessor adds additional “namespace” to pandas objects.

The `vectorbt.root_accessors` registers a custom `vbt` accessor on top of each `pd.Series`
and `pd.DataFrame` object. It is the main entry point for all other accessors:

```plaintext
vbt.base.accessors.BaseSR/DFAccessor           -> pd.Series/DataFrame.vbt.*
vbt.generic.accessors.GenericSR/DFAccessor     -> pd.Series/DataFrame.vbt.*
vbt.signals.accessors.SignalsSR/DFAccessor     -> pd.Series/DataFrame.vbt.signals.*
vbt.returns.accessors.ReturnsSR/DFAccessor     -> pd.Series/DataFrame.vbt.returns.*
vbt.ohlcv.accessors.OHLCVDFAccessor            -> pd.DataFrame.vbt.ohlc.* and pd.DataFrame.vbt.ohlcv.*
vbt.px_accessors.PXSR/DFAccessor               -> pd.Series/DataFrame.vbt.px.*
```

Additionally, some accessors subclass other accessors building the following inheritance hiearchy:

```plaintext
vbt.base.accessors.BaseSR/DFAccessor
    -> vbt.generic.accessors.GenericSR/DFAccessor
        -> vbt.signals.accessors.SignalsSR/DFAccessor
        -> vbt.returns.accessors.ReturnsSR/DFAccessor
        -> vbt.ohlcv_accessors.OHLCVDFAccessor
    -> vbt.px_accessors.PXSR/DFAccessor
```

So, for example, the method `pd.Series.vbt.to_2d_array` is also available as
`pd.Series.vbt.returns.to_2d_array`.

Class methods of any accessor can be conveniently accessed using `pd_acc`, `sr_acc`, and `df_acc` shortcuts:

```python-repl
>>> import vectorbt as vbt

>>> vbt.pd_acc.signals.generate
<bound method SignalsAccessor.generate of <class 'vectorbt.signals.accessors.SignalsAccessor'>>
```

!!! note
    Accessors in vectorbt are not cached, so querying `df.vbt` twice will also call `Vbt_DFAccessor` twice.
    You can change this in global settings."""

import warnings

import pandas as pd
from pandas.core.accessor import DirNamesMixin

from vectorbt import _typing as tp
from vectorbt.generic.accessors import GenericAccessor, GenericSRAccessor, GenericDFAccessor
from vectorbt.utils.config import Configured

ParentAccessorT = tp.TypeVar("ParentAccessorT", bound=object)
AccessorT = tp.TypeVar("AccessorT", bound=object)


class Accessor:
    """Accessor."""

    def __init__(self, name: str, accessor: tp.Type[AccessorT]) -> None:
        self._name = name
        self._accessor = accessor

    def __get__(self, obj: ParentAccessorT, cls: DirNamesMixin) -> AccessorT:
        if obj is None:
            return self._accessor
        if isinstance(obj, (pd.Series, pd.DataFrame)):
            accessor_obj = self._accessor(obj)
        elif isinstance(obj, Configured):
            accessor_obj = obj.replace(cls_=self._accessor)
        else:
            accessor_obj = self._accessor(obj.obj)
        return accessor_obj


class CachedAccessor:
    """Cached accessor.

    !!! warning
        Does not prevent from using old index data if the object's index has been changed in-place."""

    def __init__(self, name: str, accessor: tp.Type[AccessorT]) -> None:
        self._name = name
        self._accessor = accessor

    def __get__(self, obj: ParentAccessorT, cls: DirNamesMixin) -> AccessorT:
        if obj is None:
            return self._accessor
        if isinstance(obj, (pd.Series, pd.DataFrame)):
            accessor_obj = self._accessor(obj)
        elif isinstance(obj, Configured):
            accessor_obj = obj.replace(cls_=self._accessor)
        else:
            accessor_obj = self._accessor(obj.obj)
        object.__setattr__(obj, self._name, accessor_obj)
        return accessor_obj


def register_accessor(name: str, cls: tp.Type[DirNamesMixin]) -> tp.Callable:
    """Register a custom accessor.

    `cls` must subclass `pandas.core.accessor.DirNamesMixin`."""

    def decorator(accessor: tp.Type[AccessorT]) -> tp.Type[AccessorT]:
        from vectorbt._settings import settings
        caching_cfg = settings['caching']

        if hasattr(cls, name):
            warnings.warn(
                f"registration of accessor {repr(accessor)} under name "
                f"{repr(name)} for type {repr(cls)} is overriding a preexisting "
                f"attribute with the same name.",
                UserWarning,
                stacklevel=2,
            )
        if caching_cfg['use_cached_accessors']:
            setattr(cls, name, CachedAccessor(name, accessor))
        else:
            setattr(cls, name, Accessor(name, accessor))
        cls._accessors.add(name)
        return accessor

    return decorator


def register_series_accessor(name: str) -> tp.Callable:
    """Decorator to register a custom `pd.Series` accessor on top of the `pd.Series`."""
    return register_accessor(name, pd.Series)


def register_dataframe_accessor(name: str) -> tp.Callable:
    """Decorator to register a custom `pd.DataFrame` accessor on top of the `pd.DataFrame`."""
    return register_accessor(name, pd.DataFrame)


# By subclassing DirNamesMixin, we can build accessors on top of each other
class Vbt_Accessor(DirNamesMixin, GenericAccessor):
    """The main vectorbt accessor for both `pd.Series` and `pd.DataFrame`."""

    def __init__(self, obj: tp.Series, **kwargs) -> None:
        self._obj = obj

        DirNamesMixin.__init__(self)
        GenericAccessor.__init__(self, obj, **kwargs)


@register_series_accessor("vbt")
class Vbt_SRAccessor(DirNamesMixin, GenericSRAccessor):
    """The main vectorbt accessor for `pd.Series`."""

    def __init__(self, obj: tp.Series, **kwargs) -> None:
        self._obj = obj

        DirNamesMixin.__init__(self)
        GenericSRAccessor.__init__(self, obj, **kwargs)


@register_dataframe_accessor("vbt")
class Vbt_DFAccessor(DirNamesMixin, GenericDFAccessor):
    """The main vectorbt accessor for `pd.DataFrame`."""

    def __init__(self, obj: tp.Frame, **kwargs) -> None:
        self._obj = obj

        DirNamesMixin.__init__(self)
        GenericDFAccessor.__init__(self, obj, **kwargs)


def register_vbt_accessor(name: str, parent: tp.Type[DirNamesMixin] = Vbt_Accessor) -> tp.Callable:
    """Decorator to register an accessor on top of a parent accessor."""
    return register_accessor(name, parent)


def register_sr_vbt_accessor(name: str, parent: tp.Type[DirNamesMixin] = Vbt_SRAccessor) -> tp.Callable:
    """Decorator to register a `pd.Series` accessor on top of a parent accessor."""
    return register_accessor(name, parent)


def register_df_vbt_accessor(name: str, parent: tp.Type[DirNamesMixin] = Vbt_DFAccessor) -> tp.Callable:
    """Decorator to register a `pd.DataFrame` accessor on top of a parent accessor."""
    return register_accessor(name, parent)


pd_acc = Vbt_Accessor
"""Shortcut for `Vbt_Accessor`."""

sr_acc = Vbt_SRAccessor
"""Shortcut for `Vbt_SRAccessor`."""

df_acc = Vbt_DFAccessor
"""Shortcut for `Vbt_DFAccessor`."""
