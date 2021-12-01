# Copyright (c) 2021 Oleg Polakow. All rights reserved.
# This code is licensed under Apache 2.0 with Commons Clause license (see LICENSE.md for details)

"""Global registry for cacheables.

Caching in vectorbt is achieved through a combination of decorators and the registry.
Cacheable decorators such as `vectorbt.utils.decorators.cacheable` take a function and wrap
it with another function that behaves like the wrapped function but also takes care of all
caching modalities.

But unlike other implementations such as that of `functools.lru_cache`, the actual caching procedure
doesn't happen nor are the results stored inside the decorators themselves: decorators just register a
so-called "setup" for the wrapped function at the registry (see `CARunSetup`).

## Runnable setups

The actual magic happens within a runnable setup: it takes the function that should be called
and the arguments that should be passed to this function, looks whether the result should be cached,
runs the function, stores the result in the cache, updates the metrics, etc. It then returns the
resulting object to the wrapping function, which in turn returns it to the user. Each setup is stateful
- it stores the cache, the number of hits and misses, and other metadata. Thus, there can be only one
registered setup per each cacheable function globally at a time. To avoid creating new setups for the same
function over and over again, each setup can be uniquely identified by its function through hashing:

```python-repl
>>> import vectorbt as vbt
>>> import numpy as np

>>> my_func = lambda: np.random.uniform(size=1000000)

>>> # Decorator returns a wrapper
>>> my_ca_func = vbt.cached(my_func)

>>> # Wrapper registers a new setup
>>> my_ca_func.get_ca_setup()
<vectorbt.ca_registry.CARunSetup at 0x7f9fd6775a20>

>>> # Another call won't register a new setup but return the existing one
>>> my_ca_func.get_ca_setup()
<vectorbt.ca_registry.CARunSetup at 0x7f9fd6775a20>

>>> # Only one CARunSetup object per wrapper and optionally the instance the wrapper is bound to
>>> hash(my_ca_func.get_ca_setup()) == hash((my_ca_func, None))
True
```

When we call `my_ca_func`, it takes the setup from the registry and calls `CARunSetup.run`.
The caching happens by the setup itself and isn't in any way visible to `my_ca_func`.
To access the cache or any metric of interest, we can ask the setup:

```python-repl
>>> my_setup = my_ca_func.get_ca_setup()

>>> # Cache is empty
>>> my_setup.get_status()
{
    'hash': 4792160544297109364,
    'short_str': '<bound func __main__.<lambda>>',
    'use_cache': True,
    'whitelist': False,
    'caching_enabled': True,
    'hits': 0,
    'misses': 0,
    'total_size': '0 Bytes',
    'total_elapsed': None,
    'total_saved': None,
    'first_run_time': None,
    'last_run_time': None,
    'first_hit_time': None,
    'last_hit_time': None,
    'creation_time': 'now',
    'last_update_time': None
}

>>> # The result is cached
>>> my_ca_func()
>>> my_setup.get_status()
{
    'hash': 4792160544297109364,
    'short_str': '<bound func __main__.<lambda>>',
    'use_cache': True,
    'whitelist': False,
    'caching_enabled': True,
    'hits': 0,
    'misses': 1,
    'total_size': '8.0 MB',
    'total_elapsed': '11.33 milliseconds',
    'total_saved': '0 milliseconds',
    'first_run_time': 'now',
    'last_run_time': 'now',
    'first_hit_time': None,
    'last_hit_time': None,
    'creation_time': 'now',
    'last_update_time': None
}

>>> # The cached result is retrieved
>>> my_ca_func()
>>> my_setup.get_status()
{
    'hash': 4792160544297109364,
    'short_str': '<bound func __main__.<lambda>>',
    'use_cache': True,
    'whitelist': False,
    'caching_enabled': True,
    'hits': 1,
    'misses': 1,
    'total_size': '8.0 MB',
    'total_elapsed': '11.33 milliseconds',
    'total_saved': '11.33 milliseconds',
    'first_run_time': 'now',
    'last_run_time': 'now',
    'first_hit_time': 'now',
    'last_hit_time': 'now',
    'creation_time': 'now',
    'last_update_time': None
}
```

## Enabling/disabling caching

To enable or disable caching, we can invoke `CARunSetup.enable_caching` and `CARunSetup.disable_caching`
respectively. This will set `CARunSetup.use_cache` flag to True or False. Even though we expressed
our disire to change caching rules, the final decision also depends on the global settings and whether
the setup is whitelisted in case caching is disabled globally. This decision is available via
`CARunSetup.caching_enabled`:

```python-repl
>>> my_setup.disable_caching()
>>> my_setup.caching_enabled
False

>>> my_setup.enable_caching()
>>> my_setup.caching_enabled
True

>>> vbt.settings.caching['disable'] = True
>>> my_setup.caching_enabled
False

>>> my_setup.enable_caching()
UserWarning: This operation has no effect: caching is disabled globally and this setup is not whitelisted

>>> my_setup.enable_caching(force=True)
>>> my_setup.caching_enabled
True

>>> vbt.settings.caching['disable_whitelist'] = True
>>> my_setup.caching_enabled
False

>>> my_setup.enable_caching(force=True)
UserWarning: This operation has no effect: caching and whitelisting are disabled globally
```

To disable registration of new setups completely, use `disable_machinery`:

```python-repl
>>> vbt.settings.caching['disable_machinery'] = True
```

## Setup hierarchy

But what if we wanted to change caching rules for an entire instance or class at once?
Even if we changed the setup of every cacheable function declared in the class, how do we
make sure that each future subclass or instance inherits the changes that we applied?
To account for this, vectorbt provides us with a set of setups that both are stateful
and can delegate various operations to their child setups, all the way down to `CARunSetup`.
The setup hierarchy follows the inheritance hierarchy in OOP:

![](/docs/img/setup_hierarchy.svg)

For example, calling `B.get_ca_setup().disable_caching()` would disable caching for each current
and future subclass and instance of `B`, but it won't disable caching for `A` or any other superclass of `B`.
In turn, each instance of `B` would then disable caching for each cacheable property and method in
that instance. As we see, the propagation of this operation is happening from top to bottom.

The reason why unbound setups are stretching outside of their classes in the diagram is
because there is no easy way to derive the class when calling a cacheable decorator,
thus their functions are considered to be living on their own. When calling
`B.f.get_ca_setup().disable_caching()`, we are disabling caching for the function `B.f`
for each current and future subclass and instance of `B`, while all other functions remain untouched.

But what happens when we enable caching for the class `B` and disable caching for the unbound
function `B.f`? Would the future method `b2.f` be cached or not? Quite easy: it would then
inherit the state from the setup that has been updated more recently.

Here is another illustration of how operations are propagated from parents to children:

![](/docs/img/setup_propagation.svg)

The diagram above depicts the following setup hierarchy:

```python-repl
>>> # Populate setups at init
>>> vbt.settings.caching.reset()
>>> vbt.settings.caching['register_lazily'] = False

>>> class A(vbt.Cacheable):
...     @vbt.cached_property
...     def f1(self): pass

>>> class B(A):
...     def f2(self): pass

>>> class C(A):
...     @vbt.cached_method
...     def f2(self): pass

>>> b1 = B()
>>> c1 = C()
>>> c2 = C()

>>> print(vbt.stringify(A.get_ca_setup().get_setup_hierarchy()))
[
    {
        "parent": "<class __main__.B>",
        "children": [
            {
                "parent": "<instance of __main__.B>",
                "children": [
                    "<instance property __main__.B.f1>"
                ]
            }
        ]
    },
    {
        "parent": "<class __main__.C>",
        "children": [
            {
                "parent": "<instance of __main__.C>",
                "children": [
                    "<instance method __main__.C.f2>",
                    "<instance property __main__.C.f1>"
                ]
            },
            {
                "parent": "<instance of __main__.C>",
                "children": [
                    "<instance method __main__.C.f2>",
                    "<instance property __main__.C.f1>"
                ]
            }
        ]
    }
]

>>> print(vbt.stringify(A.f1.get_ca_setup().get_setup_hierarchy()))
[
    "<instance property __main__.C.f1>",
    "<instance property __main__.C.f1>",
    "<instance property __main__.B.f1>"
]

>>> print(vbt.stringify(C.f2.get_ca_setup().get_setup_hierarchy()))
[
    "<instance method __main__.C.f2>",
    "<instance method __main__.C.f2>"
]
```

Let's disable caching for the entire `A` class:

```python-repl
>>> A.get_ca_setup().disable_caching()
>>> A.get_ca_setup().use_cache
False
>>> B.get_ca_setup().use_cache
False
>>> C.get_ca_setup().use_cache
False
```

This disabled caching for `A`, subclasses `B` and `C`, their instances, and any instance function.
But it didn't touch unbound functions such as `C.f1` and `C.f2`:

```python-repl
>>> C.f1.get_ca_setup().use_cache
True
>>> C.f2.get_ca_setup().use_cache
True
```

This is because unbound functions are not children of the classes they are declared in!
Still, any future instance method of `C` won't be cached because it looks which parent
has been updated more recently: the class or the unbound function. In our case,
the class had a more recent update.

```python-repl
>>> c3 = C()
>>> C.f2.get_ca_setup(c3).use_cache
False
```

In fact, if we want to disable an entire class but leave one function untouched,
we need to perform two operations in a particular order: 1) disable caching on the class
and 2) enable caching on the unbound function.

```python-repl
>>> A.get_ca_setup().disable_caching()
>>> C.f2.get_ca_setup().enable_caching()

>>> c4 = C()
>>> C.f2.get_ca_setup(c4).use_cache
True
```

## Getting overview

The main advantage of having a central registry of setups is that we can easily find any setup
registered in any part of vectorbt that matches some condition using `CacheableRegistry.match_setups`.

!!! note
    By default, all setups are registered lazily - no setup is registered until it's run
    or explicitly called. To change this behavior, set `register_lazily` in the global
    settings to False.

For example, let's look which setups have been registered so far:

```python-repl
>>> from vectorbt.ca_registry import ca_registry

>>> ca_registry.match_setups(kind=None)
{<vectorbt.ca_registry.CAClassSetup at 0x7f7fa5df3668>,
 <vectorbt.ca_registry.CAClassSetup at 0x7f7fa0fe3ef0>,
 <vectorbt.ca_registry.CAInstanceSetup at 0x7f7fa5df36d8>,
 <vectorbt.ca_registry.CAInstanceSetup at 0x7f7fa0fe38d0>,
 <vectorbt.ca_registry.CAInstanceSetup at 0x7f7fd056ab38>,
 <vectorbt.ca_registry.CAInstanceSetup at 0x7f7fa5df3f60>,
 <vectorbt.ca_registry.CARunSetup at 0x7f7fd056a7b8>,
 <vectorbt.ca_registry.CARunSetup at 0x7f7fa5df36a0>,
 <vectorbt.ca_registry.CARunSetup at 0x7f7fa5e13048>,
 <vectorbt.ca_registry.CARunSetup at 0x7f7fa5df3630>,
 <vectorbt.ca_registry.CARunSetup at 0x7f7fd056aa58>,
 <vectorbt.ca_registry.CARunSetup at 0x7f7fa5df3208>,
 <vectorbt.ca_registry.CARunSetup at 0x7f7fa5e13080>,
 <vectorbt.ca_registry.CAUnboundSetup at 0x7f7fa5df3588>,
 <vectorbt.ca_registry.CAUnboundSetup at 0x7f7fa5df34e0>}
```

Let's get the runnable setup of any property and method called `f2`:

```python-repl
>>> ca_registry.match_setups('f2', kind='runnable')
{<vectorbt.ca_registry.CARunSetup at 0x7f7fd056a7b8>,
 <vectorbt.ca_registry.CARunSetup at 0x7f7fa5df36a0>,
 <vectorbt.ca_registry.CARunSetup at 0x7f7fa5e13048>}
```

But there is a better way to get an overview: `CAQueryDelegator.get_status_overview`.
It returns a DataFrame with setup statuses as rows:

```python-repl
>>> vbt.CAQueryDelegator('f2', kind='runnable').get_status_overview()
                                               string  use_cache  whitelist  \\
hash
 3506416602224216137  <instance method __main__.C.f2>       True      False
-4747092115268118855  <instance method __main__.C.f2>       True      False
-4748466030718995055  <instance method __main__.C.f2>       True      False

                      caching_enabled  hits  misses total_size total_elapsed  \\
hash
 3506416602224216137             True     0       0    0 Bytes          None
-4747092115268118855             True     0       0    0 Bytes          None
-4748466030718995055             True     0       0    0 Bytes          None

                     total_saved first_run_time last_run_time first_hit_time  \\
hash
 3506416602224216137        None           None          None           None
-4747092115268118855        None           None          None           None
-4748466030718995055        None           None          None           None

                     last_hit_time  creation_time last_update_time
hash
 3506416602224216137          None  9 minutes ago    9 minutes ago
-4747092115268118855          None  9 minutes ago    9 minutes ago
-4748466030718995055          None  9 minutes ago    9 minutes ago
```

## Clearing up

Instance and runnable setups hold only weak references to their instances such that
deleting those instances won't keep them in memory and will automatically remove the setups.

To clear all caches:

```python-repl
>>> vbt.CAQueryDelegator().clear_cache()
```

## Resetting

To reset global caching flags:

```python-repl
>>> vbt.settings.caching.reset()
```

To remove all setups:

```python-repl
>>> vbt.CAQueryDelegator(kind=None).deregister()
```
"""

import inspect
import sys
import warnings
import weakref
from datetime import datetime, timezone, timedelta

import humanize
import pandas as pd

from vectorbt import _typing as tp
from vectorbt.utils import checks
from vectorbt.utils.caching import Cacheable
from vectorbt.utils.datetime_ import to_naive_datetime
from vectorbt.utils.decorators import cacheableT, cacheable_property
from vectorbt.utils.docs import SafeToStr, prepare_for_doc
from vectorbt.utils.hashing import Hashable
from vectorbt.utils.parsing import Regex, hash_args, UnhashableArgsError
from vectorbt.utils.profiling import Timer

__pdoc__ = {}

_GARBAGE = object()


def is_cacheable_function(cacheable: tp.Any) -> bool:
    """Check if `cacheable` is a cacheable function."""
    return callable(cacheable) \
           and hasattr(cacheable, 'is_method') \
           and not cacheable.is_method \
           and hasattr(cacheable, 'is_cacheable') \
           and cacheable.is_cacheable


def is_cacheable_property(cacheable: tp.Any) -> bool:
    """Check if `cacheable` is a cacheable property."""
    return isinstance(cacheable, cacheable_property)


def is_cacheable_method(cacheable: tp.Any) -> bool:
    """Check if `cacheable` is a cacheable method."""
    return callable(cacheable) \
           and hasattr(cacheable, 'is_method') \
           and cacheable.is_method \
           and hasattr(cacheable, 'is_cacheable') \
           and cacheable.is_cacheable


def is_bindable_cacheable(cacheable: tp.Any) -> bool:
    """Check if `cacheable` is a cacheable that can be bound to an instance."""
    return is_cacheable_property(cacheable) or is_cacheable_method(cacheable)


def is_cacheable(cacheable: tp.Any) -> bool:
    """Check if `cacheable` is a cacheable."""
    return is_cacheable_function(cacheable) or is_bindable_cacheable(cacheable)


def get_obj_id(instance: object) -> tp.Tuple[type, int]:
    """Get id of an instance."""
    return type(instance), id(instance)


CAQueryT = tp.TypeVar("CAQueryT", bound="CAQuery")


class CAQuery(Hashable, SafeToStr):
    """Class that represents a query for matching and ranking setups."""

    @classmethod
    def parse(cls: tp.Type[CAQueryT], query_like: tp.Any, use_base_cls: bool = True) -> CAQueryT:
        """Parse a query-like object.

        !!! note
            Not all attribute combinations can be safely parsed by this function.
            For example, you cannot combine cacheable together with options.

        ## Example

        ```python-repl
        >>> import vectorbt as vbt

        >>> CAQuery.parse(func)
        <=> CAQuery(cacheable=func)

        >>> CAQuery.parse("a")
        <=> CAQuery(cacheable='a')

        >>> CAQuery.parse("A.a")
        <=> CAQuery(base_cls='A', cacheable='a')

        >>> CAQuery.parse("A")
        <=> CAQuery(base_cls='A')

        >>> CAQuery.parse("A", use_base_cls=False)
        <=> CAQuery(cls='A')

        >>> CAQuery.parse(vbt.Regex("[A-B]"))
        <=> CAQuery(base_cls=vbt.Regex("[A-B]"))

        >>> CAQuery.parse(dict(my_option=100))
        <=> CAQuery(options=dict(my_option=100))

        >>> CAQuery.parse(123)
        <=> CAQuery(instance=123)
        ```"""
        if query_like is None:
            return CAQuery()
        if isinstance(query_like, CAQuery):
            return query_like
        if isinstance(query_like, CABaseSetup):
            return query_like.query
        if isinstance(query_like, cacheable_property):
            return cls(cacheable=query_like)
        if isinstance(query_like, str) and query_like[0].islower():
            return cls(cacheable=query_like)
        if isinstance(query_like, str) and query_like[0].isupper() and '.' in query_like:
            if use_base_cls:
                return cls(cacheable=query_like.split('.')[1], base_cls=query_like.split('.')[0])
            return cls(cacheable=query_like.split('.')[1], cls=query_like.split('.')[0])
        if isinstance(query_like, str) and query_like[0].isupper():
            if use_base_cls:
                return cls(base_cls=query_like)
            return cls(cls=query_like)
        if isinstance(query_like, Regex):
            if use_base_cls:
                return cls(base_cls=query_like)
            return cls(cls=query_like)
        if isinstance(query_like, type):
            if use_base_cls:
                return cls(base_cls=query_like)
            return cls(cls=query_like)
        if isinstance(query_like, tuple):
            if use_base_cls:
                return cls(base_cls=query_like)
            return cls(cls=query_like)
        if isinstance(query_like, dict):
            return cls(options=query_like)
        if callable(query_like):
            return cls(cacheable=query_like)
        return cls(instance=query_like)

    def __init__(self,
                 cacheable: tp.Optional[tp.Union[tp.Callable, cacheableT, str, Regex]] = None,
                 instance: tp.Optional[Cacheable] = None,
                 cls: tp.Optional[tp.TypeLike] = None,
                 base_cls: tp.Optional[tp.TypeLike] = None,
                 options: tp.Optional[dict] = None) -> None:
        self._cacheable = cacheable
        if instance is not None and instance is not _GARBAGE:
            instance = weakref.ref(instance)
        self._instance = instance
        self._cls = cls
        self._base_cls = base_cls
        self._options = options

    @property
    def cacheable(self) -> tp.Optional[tp.Union[tp.Callable, cacheableT, str, Regex]]:
        """Cacheable object or its name (case-sensitive)."""
        return self._cacheable

    @property
    def instance(self) -> tp.Optional[tp.Union[Cacheable, object]]:
        """Weak reference to the instance `CAQuery.cacheable` is bound to."""
        if self._instance is _GARBAGE:
            return _GARBAGE
        if self._instance is not None and self._instance() is None:
            return _GARBAGE
        return self._instance() if self._instance is not None else None

    @property
    def cls(self) -> tp.Optional[tp.TypeLike]:
        """Class of the instance or its name (case-sensitive) `CAQuery.cacheable` is bound to."""
        return self._cls

    @property
    def base_cls(self) -> tp.Optional[tp.TypeLike]:
        """Base class of the instance or its name (case-sensitive) `CAQuery.cacheable` is bound to."""
        return self._base_cls

    @property
    def options(self) -> tp.Optional[dict]:
        """Options to match."""
        return self._options

    def matches_setup(self, setup: 'CABaseSetup') -> bool:
        """Return whether the setup matches this query.

        ## Example

        Let's evaluate various queries:

        ```python-repl
        >>> import vectorbt as vbt

        >>> class A(vbt.Cacheable):
        ...     @vbt.cached_method(my_option=True)
        ...     def f(self):
        ...         return None

        >>> class B(A):
        ...     pass

        >>> @vbt.cached(my_option=False)
        ... def f():
        ...     return None

        >>> a = A()
        >>> b = B()

        >>> def match_query(query):
        ...     matched = []
        ...     if query.matches_setup(A.f.get_ca_setup()):  # unbound method
        ...         matched.append('A.f')
        ...     if query.matches_setup(A.get_ca_setup()):  # class
        ...         matched.append('A')
        ...     if query.matches_setup(a.get_ca_setup()):  # instance
        ...         matched.append('a')
        ...     if query.matches_setup(A.f.get_ca_setup(a)):  # instance method
        ...         matched.append('a.f')
        ...     if query.matches_setup(B.f.get_ca_setup()):  # unbound method
        ...         matched.append('B.f')
        ...     if query.matches_setup(B.get_ca_setup()):  # class
        ...         matched.append('B')
        ...     if query.matches_setup(b.get_ca_setup()):  # instance
        ...         matched.append('b')
        ...     if query.matches_setup(B.f.get_ca_setup(b)):  # instance method
        ...         matched.append('b.f')
        ...     if query.matches_setup(f.get_ca_setup()):  # function
        ...         matched.append('f')
        ...     return matched

        >>> match_query(vbt.CAQuery())
        ['A.f', 'A', 'a', 'a.f', 'B.f', 'B', 'b', 'b.f', 'f']
        >>> match_query(vbt.CAQuery(cacheable=A.f))
        ['A.f', 'a.f', 'B.f', 'b.f']
        >>> match_query(vbt.CAQuery(cacheable=B.f))
        ['A.f', 'a.f', 'B.f', 'b.f']
        >>> match_query(vbt.CAQuery(cls=A))
        ['A', 'a', 'a.f']
        >>> match_query(vbt.CAQuery(cls=B))
        ['B', 'b', 'b.f']
        >>> match_query(vbt.CAQuery(cls=vbt.Regex('[A-B]')))
        ['A', 'a', 'a.f', 'B', 'b', 'b.f']
        >>> match_query(vbt.CAQuery(base_cls=A))
        ['A', 'a', 'a.f', 'B', 'b', 'b.f']
        >>> match_query(vbt.CAQuery(base_cls=B))
        ['B', 'b', 'b.f']
        >>> match_query(vbt.CAQuery(instance=a))
        ['a', 'a.f']
        >>> match_query(vbt.CAQuery(instance=b))
        ['b', 'b.f']
        >>> match_query(vbt.CAQuery(instance=a, cacheable='f'))
        ['a.f']
        >>> match_query(vbt.CAQuery(instance=b, cacheable='f'))
        ['b.f']
        >>> match_query(vbt.CAQuery(options=dict(my_option=True)))
        ['A.f', 'a.f', 'B.f', 'b.f']
        >>> match_query(vbt.CAQuery(options=dict(my_option=False)))
        ['f']
        ```"""

        if self.cacheable is not None:
            if not isinstance(setup, (CARunSetup, CAUnboundSetup)):
                return False
            if is_cacheable(self.cacheable):
                if setup.cacheable is not self.cacheable and setup.cacheable.func is not self.cacheable.func:
                    return False
            elif callable(self.cacheable):
                if setup.cacheable.func is not self.cacheable:
                    return False
            elif isinstance(self.cacheable, str):
                if setup.cacheable.name != self.cacheable:
                    return False
            elif isinstance(self.cacheable, Regex):
                if not self.cacheable.matches(setup.cacheable.name):
                    return False
            else:
                return False

        if self.instance is not None:
            if not isinstance(setup, (CARunSetup, CAInstanceSetup)):
                return False
            if setup.instance is not self.instance:
                return False

        if self.cls is not None:
            if not isinstance(setup, (CARunSetup, CAInstanceSetup, CAClassSetup)):
                return False
            if isinstance(setup, (CARunSetup, CAInstanceSetup)) \
                    and setup.instance is _GARBAGE:
                return False
            if isinstance(setup, (CARunSetup, CAInstanceSetup)) \
                    and not checks.is_class(type(setup.instance), self.cls):
                return False
            if isinstance(setup, CAClassSetup) \
                    and not checks.is_class(setup.cls, self.cls):
                return False

        if self.base_cls is not None:
            if not isinstance(setup, (CARunSetup, CAInstanceSetup, CAClassSetup)):
                return False
            if isinstance(setup, (CARunSetup, CAInstanceSetup)) \
                    and setup.instance is _GARBAGE:
                return False
            if isinstance(setup, (CARunSetup, CAInstanceSetup)) \
                    and not checks.is_subclass_of(type(setup.instance), self.base_cls):
                return False
            if isinstance(setup, CAClassSetup) \
                    and not checks.is_subclass_of(setup.cls, self.base_cls):
                return False

        if self.options is not None:
            if not isinstance(setup, (CARunSetup, CAUnboundSetup)):
                return False
            for k, v in self.options.items():
                if k not in setup.cacheable.options or setup.cacheable.options[k] != v:
                    return False

        return True

    def __str__(self) -> str:
        return f"{type(self).__name__}(" \
               f"cacheable={self.cacheable}, " \
               f"instance={self.instance}, " \
               f"cls={self.cls}, " \
               f"base_cls={self.base_cls}, " \
               f"options={prepare_for_doc(self.options)})"

    @property
    def hash_key(self) -> tuple:
        return (
            self.cacheable,
            get_obj_id(self.instance) if self.instance is not None else None,
            self.cls,
            self.base_cls,
            tuple(self.options.items()) if self.options is not None else None
        )


class CacheableRegistry:
    """Class that registers setups of cacheables."""

    def __init__(self) -> None:
        self._class_setups = dict()
        self._instance_setups = dict()
        self._unbound_setups = dict()
        self._run_setups = dict()

    @property
    def class_setups(self) -> tp.Dict[int, 'CAClassSetup']:
        """Dict of registered `CAClassSetup` instances by their hash."""
        return self._class_setups

    @property
    def instance_setups(self) -> tp.Dict[int, 'CAInstanceSetup']:
        """Dict of registered `CAInstanceSetup` instances by their hash."""
        return self._instance_setups

    @property
    def unbound_setups(self) -> tp.Dict[int, 'CAUnboundSetup']:
        """Dict of registered `CAUnboundSetup` instances by their hash."""
        return self._unbound_setups

    @property
    def run_setups(self) -> tp.Dict[int, 'CARunSetup']:
        """Dict of registered `CARunSetup` instances by their hash."""
        return self._run_setups

    def get_setup_by_hash(self, hash_: int) -> tp.Optional['CABaseSetup']:
        """Get the setup by its hash."""
        if hash_ in self.class_setups:
            return self.class_setups[hash_]
        if hash_ in self.instance_setups:
            return self.instance_setups[hash_]
        if hash_ in self.unbound_setups:
            return self.unbound_setups[hash_]
        if hash_ in self.run_setups:
            return self.run_setups[hash_]
        return None

    def register_setup(self, setup: 'CABaseSetup') -> None:
        """Register a new setup of type `CABaseSetup`."""
        if isinstance(setup, CARunSetup):
            setups = self.run_setups
        elif isinstance(setup, CAUnboundSetup):
            setups = self.unbound_setups
        elif isinstance(setup, CAInstanceSetup):
            setups = self.instance_setups
        elif isinstance(setup, CAClassSetup):
            setups = self.class_setups
        else:
            raise TypeError(str(type(setup)))
        if hash(setup) in setups:
            raise ValueError(f"Setup '{str(setup)}' already registered")
        setups[hash(setup)] = setup

    def deregister_setup(self, setup: 'CABaseSetup') -> None:
        """Deregister a new setup of type `CABaseSetup`

        Removes the setup from its respective collection.

        To also deregister its children, call the `CASetupDelegatorMixin.deregister` method."""
        if isinstance(setup, CARunSetup):
            setups = self.run_setups
        elif isinstance(setup, CAUnboundSetup):
            setups = self.unbound_setups
        elif isinstance(setup, CAInstanceSetup):
            setups = self.instance_setups
        elif isinstance(setup, CAClassSetup):
            setups = self.class_setups
        else:
            raise TypeError(str(type(setup)))
        if hash(setup) in setups:
            del setups[hash(setup)]

    def get_run_setup(self, cacheable: cacheableT,
                      instance: tp.Optional[Cacheable] = None) -> tp.Optional['CARunSetup']:
        """Get a setup of type `CARunSetup` with this cacheable and instance, or return None."""
        run_setup = self.run_setups.get(CARunSetup.get_hash(cacheable, instance=instance), None)
        if run_setup is not None and run_setup.instance is _GARBAGE:
            self.deregister_setup(run_setup)
            return None
        return run_setup

    def get_unbound_setup(self, cacheable: cacheableT) -> tp.Optional['CAUnboundSetup']:
        """Get a setup of type `CAUnboundSetup` with this cacheable or return None."""
        return self.unbound_setups.get(CAUnboundSetup.get_hash(cacheable), None)

    def get_instance_setup(self, instance: Cacheable) -> tp.Optional['CAInstanceSetup']:
        """Get a setup of type `CAInstanceSetup` with this instance or return None."""
        instance_setup = self.instance_setups.get(CAInstanceSetup.get_hash(instance), None)
        if instance_setup is not None and instance_setup.instance is _GARBAGE:
            self.deregister_setup(instance_setup)
            return None
        return instance_setup

    def get_class_setup(self, cls: tp.Type[Cacheable]) -> tp.Optional['CAClassSetup']:
        """Get a setup of type `CAInstanceSetup` with this class or return None."""
        return self.class_setups.get(CAClassSetup.get_hash(cls), None)

    def match_setups(self,
                     query_like: tp.MaybeIterable[tp.Any] = None,
                     collapse: bool = False,
                     kind: tp.Optional[tp.MaybeIterable[str]] = 'runnable',
                     exclude: tp.Optional[tp.MaybeIterable['CABaseSetup']] = None,
                     exclude_children: bool = True,
                     filter_func: tp.Optional[tp.Callable] = None) -> tp.Set['CABaseSetup']:
        """Match all setups registered in this registry against `query_like`.

        `query_like` can be one or more query-like objects that will be parsed using `CAQuery.parse`.

        Set `collapse` to True to remove child setups that belong to any matched parent setup.

        `kind` can be one or multiple of the following:

        * 'class' to only return class setups (instances of `CAClassSetup`)
        * 'instance' to only return instance setups (instances of `CAInstanceSetup`)
        * 'unbound' to only return unbound setups (instances of `CAUnboundSetup`)
        * 'runnable' to only return runnable setups (instances of `CARunSetup`)

        Set `exclude` to one or multiple setups to exclude. To not exclude their children,
        set `exclude_children` to False.

        !!! note
            `exclude_children` is applied only when `collapse` is True.

        `filter_func` can be used to filter out setups. For example, `lambda setup: setup.caching_enabled`
        includes only those setups that have caching enabled. It must take a setup and return a boolean
        of whether to include this setup in the final results."""
        if not checks.is_iterable(query_like) or isinstance(query_like, (str, tuple)):
            query_like = [query_like]
        query_like = list(map(CAQuery.parse, query_like))
        if kind is None:
            kind = {'class', 'instance', 'unbound', 'runnable'}
        if exclude is None:
            exclude = set()
        if isinstance(exclude, CABaseSetup):
            exclude = {exclude}
        else:
            exclude = set(exclude)

        matches = set()
        if not collapse:
            if isinstance(kind, str):
                if kind.lower() == 'class':
                    setups = set(self.class_setups.values())
                elif kind.lower() == 'instance':
                    setups = set(self.instance_setups.values())
                elif kind.lower() == 'unbound':
                    setups = set(self.unbound_setups.values())
                elif kind.lower() == 'runnable':
                    setups = set(self.run_setups.values())
                else:
                    raise ValueError(f"kind '{kind}' is not supported")
                for setup in setups:
                    if setup not in exclude:
                        for q in query_like:
                            if q.matches_setup(setup):
                                if filter_func is None or filter_func(setup):
                                    matches.add(setup)
                                break
            elif checks.is_iterable(kind):
                matches = set.union(*[self.match_setups(
                    query_like,
                    kind=k,
                    collapse=collapse,
                    exclude=exclude,
                    exclude_children=exclude_children,
                    filter_func=filter_func
                ) for k in kind])
            else:
                raise TypeError(f"kind must be either a string or a sequence of strings, not {type(kind)}")
        else:
            if isinstance(kind, str):
                kind = {kind}
            else:
                kind = set(kind)
            collapse_setups = set()
            if 'class' in kind:
                class_matches = set()
                for class_setup in self.class_setups.values():
                    for q in query_like:
                        if q.matches_setup(class_setup):
                            if filter_func is None or filter_func(class_setup):
                                if class_setup not in exclude:
                                    class_matches.add(class_setup)
                                if class_setup not in exclude or exclude_children:
                                    collapse_setups |= class_setup.child_setups
                            break
                for class_setup in class_matches:
                    if class_setup not in collapse_setups:
                        matches.add(class_setup)
            if 'instance' in kind:
                for instance_setup in self.instance_setups.values():
                    if instance_setup not in collapse_setups:
                        for q in query_like:
                            if q.matches_setup(instance_setup):
                                if filter_func is None or filter_func(instance_setup):
                                    if instance_setup not in exclude:
                                        matches.add(instance_setup)
                                    if instance_setup not in exclude or exclude_children:
                                        collapse_setups |= instance_setup.child_setups
                                break
            if 'unbound' in kind:
                for unbound_setup in self.unbound_setups.values():
                    if unbound_setup not in collapse_setups:
                        for q in query_like:
                            if q.matches_setup(unbound_setup):
                                if filter_func is None or filter_func(unbound_setup):
                                    if unbound_setup not in exclude:
                                        matches.add(unbound_setup)
                                    if unbound_setup not in exclude or exclude_children:
                                        collapse_setups |= unbound_setup.child_setups
                                break
            if 'runnable' in kind:
                for run_setup in self.run_setups.values():
                    if run_setup not in collapse_setups:
                        for q in query_like:
                            if q.matches_setup(run_setup):
                                if filter_func is None or filter_func(run_setup):
                                    if run_setup not in exclude:
                                        matches.add(run_setup)
                                break
        return matches


ca_registry = CacheableRegistry()
"""Default registry of type `CacheableRegistry`."""


class CAMetrics:
    """Abstract class that exposes various metrics related to caching."""

    @property
    def hits(self) -> int:
        """Number of hits."""
        raise NotImplementedError

    @property
    def misses(self) -> int:
        """Number of misses."""
        raise NotImplementedError

    @property
    def total_size(self) -> int:
        """Total size of cached objects."""
        raise NotImplementedError

    @property
    def total_elapsed(self) -> tp.Optional[timedelta]:
        """Total number of seconds elapsed during running the function."""
        raise NotImplementedError

    @property
    def total_saved(self) -> tp.Optional[timedelta]:
        """Total number of seconds saved by using the cache."""
        raise NotImplementedError

    @property
    def first_run_time(self) -> tp.Optional[datetime]:
        """Time of the first run."""
        raise NotImplementedError

    @property
    def last_run_time(self) -> tp.Optional[datetime]:
        """Time of the last run."""
        raise NotImplementedError

    @property
    def first_hit_time(self) -> tp.Optional[datetime]:
        """Time of the first hit."""
        raise NotImplementedError

    @property
    def last_hit_time(self) -> tp.Optional[datetime]:
        """Time of the last hit."""
        raise NotImplementedError

    @property
    def metrics(self) -> dict:
        """Dict with all metrics."""
        return dict(
            hits=self.hits,
            misses=self.misses,
            total_size=self.total_size,
            total_elapsed=self.total_elapsed,
            total_saved=self.total_saved,
            first_run_time=self.first_run_time,
            last_run_time=self.last_run_time,
            first_hit_time=self.first_hit_time,
            last_hit_time=self.last_hit_time
        )


class CABaseSetup(CAMetrics):
    """Base class that exposes properties and methods for cache management."""

    def __init__(self,
                 registry: CacheableRegistry = ca_registry,
                 use_cache: tp.Optional[bool] = None,
                 whitelist: tp.Optional[bool] = None) -> None:
        self._registry = registry
        self._use_cache = use_cache
        self._whitelist = whitelist
        self._creation_time = datetime.now(timezone.utc)
        self._use_cache_lut = None
        self._whitelist_lut = None

    @property
    def query(self) -> CAQuery:
        """Query to match this setup."""
        raise NotImplementedError

    @property
    def registry(self) -> CacheableRegistry:
        """Registry of type `CacheableRegistry`."""
        return self._registry

    @property
    def use_cache(self) -> tp.Optional[bool]:
        """Whether caching is enabled."""
        return self._use_cache

    @property
    def whitelist(self) -> tp.Optional[bool]:
        """Whether to cache even if caching was disabled globally."""
        return self._whitelist

    @property
    def caching_enabled(self) -> tp.Optional[bool]:
        """Whether caching is enabled in this setup.

        Caching is disabled when any of the following apply:

        * `CARunSetup.use_cache` is False
        * Caching is disabled globally and `CARunSetup.whitelist` is False
        * Caching and whitelisting are disabled globally

        Returns None if `CABaseSetup.use_cache` or `CABaseSetup.whitelist` is None."""
        from vectorbt._settings import settings
        caching_cfg = settings['caching']

        if self.use_cache is None or self.whitelist is None:
            return None
        if self.use_cache:
            if not caching_cfg['disable'] or (self.whitelist and not caching_cfg['disable_whitelist']):
                return True
        return False

    def register(self) -> None:
        """Register setup using `CacheableRegistry.register_setup`."""
        self.registry.register_setup(self)

    def deregister(self) -> None:
        """Register setup using `CacheableRegistry.deregister_setup`."""
        self.registry.deregister_setup(self)

    def enable_whitelist(self) -> None:
        """Enable whitelisting."""
        self._whitelist = True
        self._whitelist_lut = datetime.now(timezone.utc)

    def disable_whitelist(self) -> None:
        """Disable whitelisting."""
        self._whitelist = False
        self._whitelist_lut = datetime.now(timezone.utc)

    def enable_caching(self, force: bool = False, silence_warnings: tp.Optional[bool] = None) -> None:
        """Enable caching.

        Set `force` to True to whitelist this setup."""
        from vectorbt._settings import settings
        caching_cfg = settings['caching']

        if silence_warnings is None:
            silence_warnings = caching_cfg['silence_warnings']

        self._use_cache = True
        if force:
            self._whitelist = True
        else:
            if caching_cfg['disable'] and not caching_cfg['disable_whitelist'] and not silence_warnings:
                warnings.warn("This operation has no effect: caching is disabled globally and this setup "
                              "is not whitelisted", stacklevel=2)
        if caching_cfg['disable'] and caching_cfg['disable_whitelist'] and not silence_warnings:
            warnings.warn("This operation has no effect: caching and whitelisting "
                          "are disabled globally", stacklevel=2)
        self._use_cache_lut = datetime.now(timezone.utc)

    def disable_caching(self, clear_cache: bool = True) -> None:
        """Disable caching.

        Set `clear_cache` to True to also clear the cache."""
        self._use_cache = False
        if clear_cache:
            self.clear_cache()
        self._use_cache_lut = datetime.now(timezone.utc)

    @property
    def creation_time(self) -> tp.datetime:
        """Time when this setup was created."""
        return self._creation_time

    @property
    def use_cache_lut(self) -> tp.Optional[datetime]:
        """Last time `CABaseSetup.use_cache` was updated."""
        return self._use_cache_lut

    @property
    def whitelist_lut(self) -> tp.Optional[datetime]:
        """Last time `CABaseSetup.whitelist` was updated."""
        return self._whitelist_lut

    @property
    def last_update_time(self) -> tp.Optional[datetime]:
        """Last time any of `CABaseSetup.use_cache` and `CABaseSetup.whitelist` were updated."""
        if self.use_cache_lut is None:
            return self.whitelist_lut
        elif self.whitelist_lut is None:
            return self.use_cache_lut
        elif self.use_cache_lut is None and self.whitelist_lut is None:
            return None
        return max(self.use_cache_lut, self.whitelist_lut)

    def clear_cache(self) -> None:
        """Clear the cache."""
        raise NotImplementedError

    @property
    def short_str(self) -> str:
        """Convert this setup into a short readable string."""
        raise NotImplementedError

    def get_status(self, readable: bool = True) -> dict:
        """Get status of the setup as a dict with metrics."""
        string = str(self)
        total_size = self.total_size
        total_elapsed = self.total_elapsed
        total_saved = self.total_saved
        first_run_time = self.first_run_time
        last_run_time = self.last_run_time
        first_hit_time = self.first_hit_time
        last_hit_time = self.last_hit_time
        creation_time = self.creation_time
        last_update_time = self.last_update_time

        if readable:
            string = self.short_str
            total_size = humanize.naturalsize(total_size)
            if total_elapsed is not None:
                minimum_unit = 'seconds' if total_elapsed.total_seconds() >= 1 else 'milliseconds'
                total_elapsed = humanize.precisedelta(total_elapsed, minimum_unit)
            if total_saved is not None:
                minimum_unit = 'seconds' if total_saved.total_seconds() >= 1 else 'milliseconds'
                total_saved = humanize.precisedelta(total_saved, minimum_unit)
            if first_run_time is not None:
                first_run_time = humanize.naturaltime(to_naive_datetime(first_run_time))
            if last_run_time is not None:
                last_run_time = humanize.naturaltime(to_naive_datetime(last_run_time))
            if first_hit_time is not None:
                first_hit_time = humanize.naturaltime(to_naive_datetime(first_hit_time))
            if last_hit_time is not None:
                last_hit_time = humanize.naturaltime(to_naive_datetime(last_hit_time))
            if creation_time is not None:
                creation_time = humanize.naturaltime(to_naive_datetime(creation_time))
            if last_update_time is not None:
                last_update_time = humanize.naturaltime(to_naive_datetime(last_update_time))

        return dict(
            hash=hash(self),
            string=string,
            use_cache=self.use_cache,
            whitelist=self.whitelist,
            caching_enabled=self.caching_enabled,
            hits=self.hits,
            misses=self.misses,
            total_size=total_size,
            total_elapsed=total_elapsed,
            total_saved=total_saved,
            first_run_time=first_run_time,
            last_run_time=last_run_time,
            first_hit_time=first_hit_time,
            last_hit_time=last_hit_time,
            creation_time=creation_time,
            last_update_time=last_update_time
        )


class CASetupDelegatorMixin(CAMetrics):
    """Mixin class that delegates cache management to child setups."""

    @property
    def child_setups(self) -> tp.Set[CABaseSetup]:
        """Child setups."""
        raise NotImplementedError

    def get_setup_hierarchy(self, readable: bool = True) -> tp.List[dict]:
        """Get the setup hierarchy by recursively traversing the child setups."""
        results = []
        for setup in self.child_setups:
            if readable:
                setup_obj = setup.short_str
            else:
                setup_obj = setup
            if isinstance(setup, CASetupDelegatorMixin):
                results.append(dict(
                    parent=setup_obj,
                    children=setup.get_setup_hierarchy(readable=readable)
                ))
            else:
                results.append(setup_obj)
        return results

    def delegate(self, func: tp.Callable,
                 exclude: tp.Optional[tp.MaybeIterable['CABaseSetup']] = None, **kwargs) -> None:
        """Delegate a function to all child setups.

        `func` must take the setup and return nothing. If the setup is an instance of
        `CASetupDelegatorMixin`, it must additionally accept `exclude`."""
        if exclude is None:
            exclude = set()
        if isinstance(exclude, CABaseSetup):
            exclude = {exclude}
        else:
            exclude = set(exclude)
        for setup in self.child_setups:
            if setup not in exclude:
                if isinstance(setup, CASetupDelegatorMixin):
                    func(setup, exclude=exclude, **kwargs)
                else:
                    func(setup, **kwargs)

    def deregister(self, **kwargs) -> None:
        """Calls `CABaseSetup.deregister` on each child setup."""
        self.delegate(lambda setup, **_kwargs: setup.deregister(**_kwargs), **kwargs)

    def enable_whitelist(self, **kwargs) -> None:
        """Calls `CABaseSetup.enable_whitelist` on each child setup."""
        self.delegate(lambda setup, **_kwargs: setup.enable_whitelist(**_kwargs), **kwargs)

    def disable_whitelist(self, **kwargs) -> None:
        """Calls `CABaseSetup.disable_whitelist` on each child setup."""
        self.delegate(lambda setup, **_kwargs: setup.disable_whitelist(**_kwargs), **kwargs)

    def enable_caching(self, **kwargs) -> None:
        """Calls `CABaseSetup.enable_caching` on each child setup."""
        self.delegate(lambda setup, **_kwargs: setup.enable_caching(**_kwargs), **kwargs)

    def disable_caching(self, **kwargs) -> None:
        """Calls `CABaseSetup.disable_caching` on each child setup."""
        self.delegate(lambda setup, **_kwargs: setup.disable_caching(**_kwargs), **kwargs)

    def clear_cache(self, **kwargs) -> None:
        """Calls `CABaseSetup.clear_cache` on each child setup."""
        self.delegate(lambda setup, **_kwargs: setup.clear_cache(**_kwargs), **kwargs)

    @property
    def hits(self) -> int:
        return sum([setup.hits for setup in self.child_setups])

    @property
    def misses(self) -> int:
        return sum([setup.misses for setup in self.child_setups])

    @property
    def total_size(self) -> int:
        return sum([setup.total_size for setup in self.child_setups])

    @property
    def total_elapsed(self) -> tp.Optional[timedelta]:
        total_elapsed = None
        for setup in self.child_setups:
            elapsed = setup.total_elapsed
            if elapsed is not None:
                if total_elapsed is None:
                    total_elapsed = elapsed
                else:
                    total_elapsed += elapsed
        return total_elapsed

    @property
    def total_saved(self) -> tp.Optional[timedelta]:
        total_saved = None
        for setup in self.child_setups:
            saved = setup.total_saved
            if saved is not None:
                if total_saved is None:
                    total_saved = saved
                else:
                    total_saved += saved
        return total_saved

    @property
    def first_run_time(self) -> tp.Optional[datetime]:
        first_run_times = []
        for setup in self.child_setups:
            first_run_time = setup.first_run_time
            if first_run_time is not None:
                first_run_times.append(first_run_time)
        if len(first_run_times) == 0:
            return None
        return list(sorted(first_run_times))[0]

    @property
    def last_run_time(self) -> tp.Optional[datetime]:
        last_run_times = []
        for setup in self.child_setups:
            last_run_time = setup.last_run_time
            if last_run_time is not None:
                last_run_times.append(last_run_time)
        if len(last_run_times) == 0:
            return None
        return list(sorted(last_run_times))[-1]

    @property
    def first_hit_time(self) -> tp.Optional[datetime]:
        first_hit_times = []
        for setup in self.child_setups:
            first_hit_time = setup.first_hit_time
            if first_hit_time is not None:
                first_hit_times.append(first_hit_time)
        if len(first_hit_times) == 0:
            return None
        return list(sorted(first_hit_times))[0]

    @property
    def last_hit_time(self) -> tp.Optional[datetime]:
        last_hit_times = []
        for setup in self.child_setups:
            last_hit_time = setup.last_hit_time
            if last_hit_time is not None:
                last_hit_times.append(last_hit_time)
        if len(last_hit_times) == 0:
            return None
        return list(sorted(last_hit_times))[-1]

    def get_status_overview(self, readable: bool = True) -> tp.Optional[tp.Frame]:
        """Get a DataFrame out of status dicts of child setups."""
        if len(self.child_setups) == 0:
            return None
        status_overview = pd.DataFrame([setup.get_status(readable=readable) for setup in self.child_setups])
        status_overview.set_index('hash', inplace=True)
        status_overview.index.name = 'hash'
        return status_overview


class CABaseDelegatorSetup(CABaseSetup, CASetupDelegatorMixin):
    """Base class acting as a stateful setup that delegates cache management to child setups.

    First delegates the work and only then changes its own state."""

    @property
    def child_setups(self) -> tp.Set[CABaseSetup]:
        """Get child setups that match `CABaseDelegatorSetup.query`."""
        return self.registry.match_setups(self.query, kind='collapse')

    def deregister(self, **kwargs) -> None:
        CASetupDelegatorMixin.deregister(self, **kwargs)
        CABaseSetup.deregister(self)

    def enable_whitelist(self, **kwargs) -> None:
        CASetupDelegatorMixin.enable_whitelist(self, **kwargs)
        CABaseSetup.enable_whitelist(self)

    def disable_whitelist(self, **kwargs) -> None:
        CASetupDelegatorMixin.disable_whitelist(self, **kwargs)
        CABaseSetup.disable_whitelist(self)

    def enable_caching(self, force: bool = False, silence_warnings: tp.Optional[bool] = None, **kwargs) -> None:
        CASetupDelegatorMixin.enable_caching(self, force=force, silence_warnings=silence_warnings, **kwargs)
        CABaseSetup.enable_caching(self, force=force, silence_warnings=silence_warnings)

    def disable_caching(self, clear_cache: bool = True, **kwargs) -> None:
        CASetupDelegatorMixin.disable_caching(self, clear_cache=clear_cache, **kwargs)
        CABaseSetup.disable_caching(self, clear_cache=False)

    def clear_cache(self, **kwargs) -> None:
        CASetupDelegatorMixin.clear_cache(self, **kwargs)


CAClassSetupT = tp.TypeVar("CAClassSetupT", bound="CAClassSetup")


class CAClassSetup(CABaseDelegatorSetup, Hashable, SafeToStr):
    """Class that represents a setup of a cacheable class.

    The provided class must subclass `vectorbt.utils.caching.Cacheable`.

    Delegates cache management to its child subclass setups of type `CAClassSetup` and
    child instance setups of type `CAInstanceSetup`.

    If `use_cash` or `whitelist` are None, inherits a non-empty value from its superclass setups
    using the method resolution order (MRO).

    !!! note
        Unbound setups are not children of class setups. See notes on `CAUnboundSetup`."""

    @staticmethod
    def get_hash(cls: tp.Type[Cacheable]) -> int:
        return hash((cls,))

    @staticmethod
    def get_cacheable_superclasses(cls: tp.Type[Cacheable]) -> tp.List[tp.Type[Cacheable]]:
        """Get an ordered list of the cacheable superclasses of a class."""
        superclasses = []
        for super_cls in inspect.getmro(cls):
            if issubclass(super_cls, Cacheable):
                if super_cls is not cls:
                    superclasses.append(super_cls)
        return superclasses

    @staticmethod
    def get_superclass_setups(registry: CacheableRegistry, cls: tp.Type[Cacheable]) -> tp.List['CAClassSetup']:
        """Setups of type `CAClassSetup` of each in `CAClassSetup.get_cacheable_superclasses`."""
        setups = []
        for super_cls in CAClassSetup.get_cacheable_superclasses(cls):
            if registry.get_class_setup(super_cls) is not None:
                setups.append(super_cls.get_ca_setup())
        return setups

    @staticmethod
    def get_cacheable_subclasses(cls: tp.Type[Cacheable]) -> tp.List[tp.Type[Cacheable]]:
        """Get an ordered list of the cacheable subclasses of a class."""
        subclasses = []
        for sub_cls in cls.__subclasses__():
            if issubclass(sub_cls, Cacheable):
                if sub_cls is not cls:
                    subclasses.append(sub_cls)
            subclasses.extend(CAClassSetup.get_cacheable_subclasses(sub_cls))
        return subclasses

    @staticmethod
    def get_subclass_setups(registry: CacheableRegistry, cls: tp.Type[Cacheable]) -> tp.List['CAClassSetup']:
        """Setups of type `CAClassSetup` of each in `CAClassSetup.get_cacheable_subclasses`."""
        setups = []
        for super_cls in CAClassSetup.get_cacheable_subclasses(cls):
            if registry.get_class_setup(super_cls) is not None:
                setups.append(super_cls.get_ca_setup())
        return setups

    @staticmethod
    def get_unbound_cacheables(cls: tp.Type[Cacheable]) -> tp.Set[cacheableT]:
        """Get a set of the unbound cacheables of a class."""
        members = inspect.getmembers(cls, is_bindable_cacheable)
        return {attr for attr_name, attr in members}

    @staticmethod
    def get_unbound_setups(registry: CacheableRegistry, cls: tp.Type[Cacheable]) -> tp.Set['CAUnboundSetup']:
        """Setups of type `CAUnboundSetup` of each in `CAClassSetup.get_unbound_cacheables`."""
        setups = set()
        for cacheable in CAClassSetup.get_unbound_cacheables(cls):
            if registry.get_unbound_setup(cacheable) is not None:
                setups.add(cacheable.get_ca_setup())
        return setups

    @classmethod
    def get(cls: tp.Type[CAClassSetupT],
            cls_: tp.Type[Cacheable],
            registry: CacheableRegistry = ca_registry,
            **kwargs) -> tp.Optional[CAClassSetupT]:
        """Get setup from `CacheableRegistry` or register a new one.

        `**kwargs` are passed to `CAClassSetup.__init__`."""
        from vectorbt._settings import settings
        caching_cfg = settings['caching']

        if caching_cfg['disable_machinery']:
            return None

        setup = registry.get_class_setup(cls_)
        if setup is not None:
            return setup
        return cls(cls_, registry=registry, **kwargs)

    def __init__(self,
                 cls_: tp.Type[Cacheable],
                 registry: CacheableRegistry = ca_registry,
                 use_cache: tp.Optional[bool] = None,
                 whitelist: tp.Optional[bool] = None) -> None:
        checks.assert_subclass_of(cls_, Cacheable)

        CABaseDelegatorSetup.__init__(
            self,
            registry=registry,
            use_cache=use_cache,
            whitelist=whitelist
        )

        self._cls = cls_

        if use_cache is None or whitelist is None:
            superclass_setups = self.superclass_setups[::-1]
            for setup in superclass_setups:
                if use_cache is None:
                    if setup.use_cache is not None:
                        self._use_cache = setup.use_cache
                if whitelist is None:
                    if setup.whitelist is not None:
                        self._whitelist = setup.whitelist

        self.register()

    @property
    def query(self) -> CAQuery:
        return CAQuery(base_cls=self.cls)

    @property
    def cls(self) -> tp.Type[Cacheable]:
        """Cacheable class."""
        return self._cls

    @property
    def superclass_setups(self) -> tp.List['CAClassSetup']:
        """See `CAClassSetup.get_superclass_setups`."""
        return self.get_superclass_setups(self.registry, self.cls)

    @property
    def subclass_setups(self) -> tp.List['CAClassSetup']:
        """See `CAClassSetup.get_subclass_setups`."""
        return self.get_subclass_setups(self.registry, self.cls)

    @property
    def unbound_setups(self) -> tp.Set['CAUnboundSetup']:
        """See `CAClassSetup.get_unbound_setups`."""
        return self.get_unbound_setups(self.registry, self.cls)

    @property
    def instance_setups(self) -> tp.Set['CAInstanceSetup']:
        """Setups of type `CAInstanceSetup` of instances of the class."""
        matches = set()
        for instance_setup in self.registry.instance_setups.values():
            if instance_setup.class_setup is self:
                matches.add(instance_setup)
        return matches

    @property
    def any_use_cache_lut(self) -> tp.Optional[datetime]:
        """Last time `CABaseSetup.use_cache` was updated in this class or any of its superclasses."""
        max_use_cache_lut = self.use_cache_lut
        for setup in self.superclass_setups:
            if setup.use_cache_lut is not None:
                if max_use_cache_lut is None or setup.use_cache_lut > max_use_cache_lut:
                    max_use_cache_lut = setup.use_cache_lut
        return max_use_cache_lut

    @property
    def any_whitelist_lut(self) -> tp.Optional[datetime]:
        """Last time `CABaseSetup.whitelist` was updated in this class or any of its superclasses."""
        max_whitelist_lut = self.whitelist_lut
        for setup in self.superclass_setups:
            if setup.whitelist_lut is not None:
                if max_whitelist_lut is None or setup.whitelist_lut > max_whitelist_lut:
                    max_whitelist_lut = setup.whitelist_lut
        return max_whitelist_lut

    @property
    def child_setups(self) -> tp.Set[tp.Union['CAClassSetup', 'CAInstanceSetup']]:
        return set(self.subclass_setups) | self.instance_setups

    def __str__(self) -> str:
        return f"{type(self).__name__}(" \
               f"cls={self.cls})"

    @property
    def short_str(self) -> str:
        return f"<class {self.cls.__module__}.{self.cls.__name__}>"

    @property
    def hash_key(self) -> tuple:
        return (self.cls,)


CAInstanceSetupT = tp.TypeVar("CAInstanceSetupT", bound="CAInstanceSetup")


class CAInstanceSetup(CABaseDelegatorSetup, Hashable, SafeToStr):
    """Class that represents a setup of an instance that has cacheables bound to it.

    The provided instance must be of `vectorbt.utils.caching.Cacheable`.

    Delegates cache management to its child setups of type `CARunSetup`.

    If `use_cash` or `whitelist` are None, inherits a non-empty value from its parent class setup."""

    @staticmethod
    def get_hash(instance: Cacheable) -> int:
        return hash((get_obj_id(instance),))

    @classmethod
    def get(cls: tp.Type[CAInstanceSetupT],
            instance: Cacheable,
            registry: CacheableRegistry = ca_registry,
            **kwargs) -> tp.Optional[CAInstanceSetupT]:
        """Get setup from `CacheableRegistry` or register a new one.

        `**kwargs` are passed to `CAInstanceSetup.__init__`."""
        from vectorbt._settings import settings
        caching_cfg = settings['caching']

        if caching_cfg['disable_machinery']:
            return None

        setup = registry.get_instance_setup(instance)
        if setup is not None:
            return setup
        return cls(instance, registry=registry, **kwargs)

    def __init__(self,
                 instance: Cacheable,
                 registry: CacheableRegistry = ca_registry,
                 use_cache: tp.Optional[bool] = None,
                 whitelist: tp.Optional[bool] = None) -> None:
        checks.assert_instance_of(instance, Cacheable)

        CABaseDelegatorSetup.__init__(
            self,
            registry=registry,
            use_cache=use_cache,
            whitelist=whitelist
        )

        self._instance = weakref.ref(instance, lambda ref: registry.deregister_setup(self))

        if use_cache is None or whitelist is None:
            class_setup = self.class_setup
            if use_cache is None:
                if class_setup.use_cache is not None:
                    self._use_cache = class_setup.use_cache
            if whitelist is None:
                if class_setup.whitelist is not None:
                    self._whitelist = class_setup.whitelist

        self.register()

    @property
    def query(self) -> CAQuery:
        return CAQuery(instance=self.instance)

    @property
    def instance(self) -> tp.Union[Cacheable, object]:
        """Weak reference to the instance."""
        if self._instance() is None:
            return _GARBAGE
        return self._instance()

    @property
    def contains_garbage(self) -> bool:
        """Whether instance was destroyed."""
        return self.instance is _GARBAGE

    @property
    def class_setup(self) -> tp.Optional[CAClassSetup]:
        """Setup of type `CAClassSetup` of the cacheable class of the instance."""
        if self.contains_garbage:
            return None
        return CAClassSetup.get(type(self.instance), self.registry)

    @property
    def unbound_setups(self) -> tp.Set['CAUnboundSetup']:
        """Setups of type `CAUnboundSetup` of unbound cacheables declared in the class of the instance."""
        if self.contains_garbage:
            return set()
        return self.class_setup.unbound_setups

    @property
    def run_setups(self) -> tp.Set['CARunSetup']:
        """Setups of type `CARunSetup` of cacheables bound to the instance."""
        if self.contains_garbage:
            return set()
        matches = set()
        for run_setup in self.registry.run_setups.values():
            if run_setup.instance_setup is self:
                matches.add(run_setup)
        return matches

    @property
    def child_setups(self) -> tp.Set['CARunSetup']:
        return self.run_setups

    def __str__(self) -> str:
        return f"{type(self).__name__}(" \
               f"instance={self.instance})"

    @property
    def short_str(self) -> str:
        if self.contains_garbage:
            return "<destroyed object>"
        return f"<instance of {type(self.instance).__module__}.{type(self.instance).__name__}>"

    @property
    def hash_key(self) -> tuple:
        return (get_obj_id(self.instance),)


CAUnboundSetupT = tp.TypeVar("CAUnboundSetupT", bound="CAUnboundSetup")


class CAUnboundSetup(CABaseDelegatorSetup, Hashable, SafeToStr):
    """Class that represents a setup of an unbound cacheable property or method.

    An unbound callable is a callable that was declared in a class but is not bound
    to any instance (just yet).

    !!! note
        Unbound callables are just regular functions - they have no parent setups. Even though they
        are formally declared in a class, there is no easy way to get a reference to the class
        from the decorator itself. Thus, searching for child setups of a specific class won't return
        unbound setups.

    Delegates cache management to its child setups of type `CARunSetup`.
    One unbound cacheable property or method can be bound to multiple instances, thus there is
    one-to-many relationship between `CAUnboundSetup` and `CARunSetup` instances.

    !!! hint
        Use class attributes instead of instance attributes to access unbound callables."""

    @staticmethod
    def get_hash(cacheable: cacheableT) -> int:
        return hash((cacheable,))

    @classmethod
    def get(cls: tp.Type[CAUnboundSetupT],
            cacheable: cacheableT,
            registry: CacheableRegistry = ca_registry,
            **kwargs) -> tp.Optional[CAUnboundSetupT]:
        """Get setup from `CacheableRegistry` or register a new one.

        `**kwargs` are passed to `CAUnboundSetup.__init__`."""
        from vectorbt._settings import settings
        caching_cfg = settings['caching']

        if caching_cfg['disable_machinery']:
            return None

        setup = registry.get_unbound_setup(cacheable)
        if setup is not None:
            return setup
        return cls(cacheable, registry=registry, **kwargs)

    def __init__(self,
                 cacheable: cacheableT,
                 registry: CacheableRegistry = ca_registry,
                 use_cache: bool = False,
                 whitelist: bool = False) -> None:
        if not is_bindable_cacheable(cacheable):
            raise TypeError("cacheable must be either cacheable_property or cacheable_method")

        CABaseDelegatorSetup.__init__(
            self,
            registry=registry,
            use_cache=use_cache,
            whitelist=whitelist
        )
        self._cacheable = cacheable

        self.register()

    @property
    def query(self) -> CAQuery:
        return CAQuery(cacheable=self.cacheable)

    @property
    def cacheable(self) -> cacheableT:
        """Cacheable object."""
        return self._cacheable

    @property
    def run_setups(self) -> tp.Set['CARunSetup']:
        """Setups of type `CARunSetup` of bound cacheables."""
        matches = set()
        for run_setup in self.registry.run_setups.values():
            if run_setup.unbound_setup is self:
                matches.add(run_setup)
        return matches

    @property
    def child_setups(self) -> tp.Set['CARunSetup']:
        return self.run_setups

    def __str__(self) -> str:
        return f"{type(self).__name__}(" \
               f"cacheable={self.cacheable})"

    @property
    def short_str(self) -> str:
        if is_cacheable_property(self.cacheable):
            return f"<unbound property {self.cacheable.func.__module__}.{self.cacheable.func.__name__}>"
        return f"<unbound method {self.cacheable.func.__module__}.{self.cacheable.func.__name__}>"

    @property
    def hash_key(self) -> tuple:
        return (self.cacheable,)


CARunSetupT = tp.TypeVar("CARunSetupT", bound="CARunSetup")


class CARunResult(Hashable, SafeToStr):
    """Class that represents a cached result of a run.

    !!! note
        Hashed solely by the hash of the arguments `args_hash`."""

    @staticmethod
    def get_hash(args_hash: int) -> int:
        return hash((args_hash,))

    def __init__(self, args_hash: int, result: tp.Any, timer: Timer) -> None:
        self._args_hash = args_hash
        self._result = result
        self._timer = timer
        self._run_time = datetime.now(timezone.utc)
        self._hits = 0
        self._first_hit_time = None
        self._last_hit_time = None

    @property
    def args_hash(self) -> int:
        """Hash of the arguments."""
        return self._args_hash

    @property
    def result(self) -> tp.Any:
        """Result of the run."""
        return self._result

    @property
    def timer(self) -> Timer:
        """Timer used to measure the execution time."""
        return self._timer

    @property
    def result_size(self) -> int:
        """Get size of the result in memory."""
        return sys.getsizeof(self.result)

    @property
    def run_time(self) -> datetime:
        """Time of the run."""
        return self._run_time

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def first_hit_time(self) -> tp.Optional[datetime]:
        """Time of the first hit."""
        return self._first_hit_time

    @property
    def last_hit_time(self) -> tp.Optional[datetime]:
        """Time of the last hit."""
        return self._last_hit_time

    def hit(self) -> tp.Any:
        """Hit the result."""
        hit_time = datetime.now(timezone.utc)
        if self.first_hit_time is None:
            self._first_hit_time = hit_time
        self._last_hit_time = hit_time
        self._hits += 1
        return self.result

    def __str__(self) -> str:
        return f"{type(self).__name__}(" \
               f"args_hash={self.args_hash}, " \
               f"result={self.result})"

    @property
    def hash_key(self) -> tuple:
        return (self.args_hash,)


class CARunSetup(CABaseSetup, Hashable, SafeToStr):
    """Class that represents a runnable cacheable setup.

    Takes care of running functions and caching the results using `CARunSetup.run`.

    Accepts as `cacheable` either `vectorbt.utils.decorators.cacheable_property`,
    `vectorbt.utils.decorators.cacheable_method`, or `vectorbt.utils.decorators.cacheable`.

    Hashed by the callable and optionally the id of the instance its bound to.
    This way, it can be uniquely identified among all setups.

    !!! note
        Cacheable properties and methods must provide an instance.

        Only one instance per each unique combination of `cacheable` and `instance` can exist at a time.

    If `use_cash` or `whitelist` are None, inherits a non-empty value either from its parent instance setup
    or its parent unbound setup. If both setups have non-empty values, takes the one that has been
    updated more recently.

    !!! note
        Use `CARunSetup.get` class method instead of `CARunSetup.__init__` to create a setup. The class method
        first checks whether a setup with the same hash has already been registered, and if so, returns it.
        Otherwise, creates and registers a new one. Using `CARunSetup.__init__` will throw an error if there
        is a setup with the same hash."""

    @staticmethod
    def get_hash(cacheable: cacheableT, instance: tp.Optional[Cacheable] = None) -> int:
        return hash((cacheable, get_obj_id(instance) if instance is not None else None))

    @classmethod
    def get(cls: tp.Type[CARunSetupT],
            cacheable: cacheableT,
            instance: tp.Optional[Cacheable] = None,
            registry: CacheableRegistry = ca_registry,
            **kwargs) -> tp.Optional[CARunSetupT]:
        """Get setup from `CacheableRegistry` or register a new one.

        `**kwargs` are passed to `CARunSetup.__init__`."""
        from vectorbt._settings import settings
        caching_cfg = settings['caching']

        if caching_cfg['disable_machinery']:
            return None

        setup = registry.get_run_setup(cacheable, instance=instance)
        if setup is not None:
            return setup
        return cls(cacheable, instance=instance, registry=registry, **kwargs)

    def __init__(self,
                 cacheable: cacheableT,
                 instance: tp.Optional[Cacheable] = None,
                 registry: CacheableRegistry = ca_registry,
                 use_cache: tp.Optional[bool] = None,
                 whitelist: tp.Optional[bool] = None,
                 max_size: tp.Optional[int] = None,
                 ignore_args: tp.Optional[tp.Iterable[tp.AnnArgQuery]] = None) -> None:
        if not is_cacheable(cacheable):
            raise TypeError("cacheable must be either cacheable_property, cacheable_method, or cacheable")
        if instance is None:
            if is_cacheable_property(cacheable):
                raise ValueError("CARunSetup requires an instance for cacheable_property")
            elif is_cacheable_method(cacheable):
                raise ValueError("CARunSetup requires an instance for cacheable_method")
        else:
            checks.assert_instance_of(instance, Cacheable)
            if is_cacheable_function(cacheable):
                raise ValueError("Cacheable functions can't have an instance")

        CABaseSetup.__init__(
            self,
            registry=registry,
            use_cache=use_cache,
            whitelist=whitelist
        )

        self._cacheable = cacheable
        if instance is not None:
            instance = weakref.ref(instance, lambda ref: registry.deregister_setup(self))
        self._instance = instance
        self._max_size = max_size
        self._ignore_args = ignore_args
        self._cache = {}

        if use_cache is None or whitelist is None:
            instance_setup = self.instance_setup
            unbound_setup = self.unbound_setup
            if use_cache is None:
                if instance_setup is not None \
                        and unbound_setup is not None \
                        and instance_setup.use_cache is not None \
                        and unbound_setup.use_cache is not None:
                    if unbound_setup.use_cache_lut is not None \
                            and (instance_setup.class_setup.any_use_cache_lut is None or
                                 unbound_setup.use_cache_lut > instance_setup.class_setup.any_use_cache_lut):
                        # Unbound setup was updated more recently than any superclass setup
                        self._use_cache = unbound_setup.use_cache
                    else:
                        self._use_cache = instance_setup.use_cache
                elif instance_setup is not None and instance_setup.use_cache is not None:
                    self._use_cache = instance_setup.use_cache
                elif unbound_setup is not None and unbound_setup.use_cache is not None:
                    self._use_cache = unbound_setup.use_cache
            if whitelist is None:
                if instance_setup is not None \
                        and unbound_setup is not None \
                        and instance_setup.whitelist is not None \
                        and unbound_setup.whitelist is not None:
                    if unbound_setup.whitelist_lut is not None \
                            and (instance_setup.class_setup.any_whitelist_lut is None or
                                 unbound_setup.whitelist_lut > instance_setup.class_setup.any_whitelist_lut):
                        # Unbound setup was updated more recently than any superclass setup
                        self._whitelist = unbound_setup.whitelist
                    else:
                        self._whitelist = instance_setup.whitelist
                elif instance_setup is not None and instance_setup.whitelist is not None:
                    self._whitelist = instance_setup.whitelist
                elif unbound_setup is not None and unbound_setup.whitelist is not None:
                    self._whitelist = unbound_setup.whitelist

        self.register()

    @property
    def query(self) -> CAQuery:
        return CAQuery(cacheable=self.cacheable, instance=self.instance)

    @property
    def cacheable(self) -> cacheableT:
        """Cacheable object."""
        return self._cacheable

    @property
    def instance(self) -> tp.Optional[tp.Union[Cacheable, object]]:
        """Weak reference to the instance `CARunSetup.cacheable` is bound to."""
        if self._instance is not None and self._instance() is None:
            return _GARBAGE
        return self._instance() if self._instance is not None else None

    @property
    def contains_garbage(self) -> bool:
        """Whether instance was destroyed."""
        return self.instance is _GARBAGE

    @property
    def instance_setup(self) -> tp.Optional[CAInstanceSetup]:
        """Setup of type `CAInstanceSetup` of the instance this cacheable is bound to."""
        if self.instance is None or self.contains_garbage:
            return None
        return CAInstanceSetup.get(self.instance, self.registry)

    @property
    def unbound_setup(self) -> tp.Optional[CAUnboundSetup]:
        """Setup of type `CAUnboundSetup` of the unbound cacheable."""
        return self.registry.get_unbound_setup(self.cacheable)

    @property
    def max_size(self) -> tp.Optional[int]:
        """Maximum number of entries in `CARunSetup.cache`."""
        return self._max_size

    @property
    def ignore_args(self) -> tp.Optional[tp.Iterable[tp.AnnArgQuery]]:
        """Arguments to ignore when hashing."""
        return self._ignore_args

    @property
    def cache(self) -> tp.Dict[int, CARunResult]:
        """Dict of cached `CARunResult` instances by their hash."""
        return self._cache

    @property
    def hits(self) -> int:
        return sum([run_result.hits for run_result in self.cache.values()])

    @property
    def misses(self) -> int:
        return len(self.cache)

    @property
    def total_size(self) -> int:
        return sum([run_result.result_size for run_result in self.cache.values()])

    @property
    def total_elapsed(self) -> tp.Optional[timedelta]:
        total_elapsed = None
        for run_result in self.cache.values():
            elapsed = run_result.timer.elapsed(readable=False)
            if total_elapsed is None:
                total_elapsed = elapsed
            else:
                total_elapsed += elapsed
        return total_elapsed

    @property
    def total_saved(self) -> tp.Optional[timedelta]:
        total_saved = None
        for run_result in self.cache.values():
            saved = run_result.timer.elapsed(readable=False) * run_result.hits
            if total_saved is None:
                total_saved = saved
            else:
                total_saved += saved
        return total_saved

    @property
    def first_run_time(self) -> tp.Optional[datetime]:
        if len(self.cache) == 0:
            return None
        return list(self.cache.values())[0].run_time

    @property
    def last_run_time(self) -> tp.Optional[datetime]:
        if len(self.cache) == 0:
            return None
        return list(self.cache.values())[-1].run_time

    @property
    def first_hit_time(self) -> tp.Optional[datetime]:
        first_hit_times = []
        for run_result in self.cache.values():
            if run_result.first_hit_time is not None:
                first_hit_times.append(run_result.first_hit_time)
        if len(first_hit_times) == 0:
            return None
        return list(sorted(first_hit_times))[0]

    @property
    def last_hit_time(self) -> tp.Optional[datetime]:
        last_hit_times = []
        for run_result in self.cache.values():
            if run_result.last_hit_time is not None:
                last_hit_times.append(run_result.last_hit_time)
        if len(last_hit_times) == 0:
            return None
        return list(sorted(last_hit_times))[-1]

    def run_func(self, *args, **kwargs) -> tp.Any:
        """Run the setup's function without caching."""
        if self.instance is not None:
            return self.cacheable.func(self.instance, *args, **kwargs)
        return self.cacheable.func(*args, **kwargs)

    def get_args_hash(self, *args, **kwargs) -> int:
        """Get the hash of the passed arguments.

        `CARunSetup.ignore_args` gets extended with `ignore_args` under `caching` in
        `vectorbt._settings.settings`."""
        from vectorbt._settings import settings
        caching_cfg = settings['caching']

        ignore_args = list(caching_cfg['ignore_args'])
        if self.ignore_args is not None:
            ignore_args.extend(list(self.ignore_args))

        return hash_args(
            self.cacheable.func,
            args if self.instance is None else (get_obj_id(self.instance), *args),
            kwargs,
            ignore_args=ignore_args
        )

    def run_func_and_cache(self, *args, **kwargs) -> tp.Any:
        """Run the setup's function and cache the result.

        Hashes the arguments using `CARunSetup.get_args_hash`, runs the function using
        `CARunSetup.run_func`, wraps the result using `CARunResult`, and uses the hash
        as a key to store the instance of `CARunResult` into `CARunSetup.cache` for later retrieval."""
        args_hash = self.get_args_hash(*args, **kwargs)
        run_result_hash = CARunResult.get_hash(args_hash)
        if run_result_hash in self.cache:
            return self.cache[run_result_hash].hit()
        if self.max_size is not None and self.max_size <= len(self.cache):
            del self.cache[list(self.cache.keys())[0]]
        with Timer() as timer:
            result = self.run_func(*args, **kwargs)
        run_result = CARunResult(args_hash, result, timer=timer)
        self.cache[run_result_hash] = run_result
        return result

    def run(self, *args, **kwargs) -> tp.Any:
        """Run the setup and cache it depending on a range of conditions.

        Runs `CARunSetup.run_func` if caching is disabled or arguments are not hashable,
        and `CARunSetup.run_func_and_cache` otherwise."""
        if self.caching_enabled:
            try:
                return self.run_func_and_cache(*args, **kwargs)
            except UnhashableArgsError:
                pass
        return self.run_func(*args, **kwargs)

    def clear_cache(self) -> None:
        """Clear the cache."""
        self.cache.clear()

    def __str__(self) -> str:
        return f"{type(self).__name__}(" \
               f"cacheable={self.cacheable}, " \
               f"instance={self.instance})"

    @property
    def short_str(self) -> str:
        if self.contains_garbage:
            return "<destroyed object>"
        if is_cacheable_property(self.cacheable):
            return f"<instance property {type(self.instance).__module__}." \
                   f"{type(self.instance).__name__}.{self.cacheable.func.__name__}>"
        if is_cacheable_method(self.cacheable):
            return f"<instance method {type(self.instance).__module__}." \
                   f"{type(self.instance).__name__}.{self.cacheable.func.__name__}>"
        return f"<func {self.cacheable.__module__}.{self.cacheable.__name__}>"

    @property
    def hash_key(self) -> tuple:
        return self.cacheable, get_obj_id(self.instance) if self.instance is not None else None


class CAQueryDelegator(CASetupDelegatorMixin):
    """Class that delegates any setups that match a query.

    `*args`, `collapse`, and `**kwargs` are passed to `CacheableRegistry.match_setups`."""

    def __init__(self, *args, registry: CacheableRegistry = ca_registry, collapse: bool = True, **kwargs) -> None:
        self._args = args
        kwargs['collapse'] = collapse
        self._kwargs = kwargs
        self._registry = registry

    @property
    def args(self) -> tp.Args:
        """Arguments."""
        return self._args

    @property
    def kwargs(self) -> tp.Kwargs:
        """Keyword arguments."""
        return self._kwargs

    @property
    def registry(self) -> CacheableRegistry:
        """Registry of type `CacheableRegistry`."""
        return self._registry

    @property
    def child_setups(self) -> tp.Set[CABaseSetup]:
        """Get child setups by matching them using `CacheableRegistry.match_setups`."""
        return self.registry.match_setups(*self.args, **self.kwargs)
