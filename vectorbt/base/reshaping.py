# Copyright (c) 2021 Oleg Polakow. All rights reserved.
# This code is licensed under Apache 2.0 with Commons Clause license (see LICENSE.md for details)

"""Functions for reshaping arrays.

Reshape functions transform a Pandas object/NumPy array in some way."""

import functools
import itertools

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import _broadcast_shape

from vectorbt import _typing as tp
from vectorbt.base import indexes, wrapping
from vectorbt.utils import checks
from vectorbt.utils.config import resolve_dict, merge_dicts
from vectorbt.utils.parsing import get_func_arg_names


def shape_to_tuple(shape: tp.ShapeLike) -> tp.Shape:
    """Convert a shape-like object to a tuple."""
    if isinstance(shape, int):
        return (shape,)
    return tuple(shape)


def shape_to_2d(shape: tp.ShapeLike) -> tp.Shape:
    """Convert a shape-like object to a 2-dim shape."""
    shape = shape_to_tuple(shape)
    if len(shape) == 1:
        return shape[0], 1
    return shape


def index_to_series(arg: tp.Index) -> tp.Series:
    """Convert Index to Series."""
    return arg.to_series().reset_index(drop=True)


def to_any_array(arg: tp.ArrayLike, raw: bool = False, convert_index: bool = True) -> tp.AnyArray:
    """Convert any array-like object to an array.

    Pandas objects are kept as-is."""
    if not raw and checks.is_any_array(arg):
        if convert_index and checks.is_index(arg):
            return index_to_series(arg)
        return arg
    return np.asarray(arg)


def to_pd_array(arg: tp.ArrayLike, convert_index: bool = True) -> tp.PandasArray:
    """Convert any array-like object to a Pandas object."""
    if checks.is_pandas(arg):
        if convert_index and checks.is_index(arg):
            return index_to_series(arg)
        return arg
    arg = np.asarray(arg)
    if arg.ndim == 0:
        arg = arg[None]
    if arg.ndim == 1:
        return pd.Series(arg)
    if arg.ndim == 2:
        return pd.DataFrame(arg)
    raise ValueError("Wrong number of dimensions: cannot convert to Series or DataFrame")


def soft_to_ndim(arg: tp.ArrayLike, ndim: int, raw: bool = False) -> tp.AnyArray:
    """Try to softly bring `arg` to the specified number of dimensions `ndim` (max 2)."""
    arg = to_any_array(arg, raw=raw)
    if ndim == 1:
        if arg.ndim == 2:
            if arg.shape[1] == 1:
                if checks.is_frame(arg):
                    return arg.iloc[:, 0]
                return arg[:, 0]  # downgrade
    if ndim == 2:
        if arg.ndim == 1:
            if checks.is_series(arg):
                return arg.to_frame()
            return arg[:, None]  # upgrade
    return arg  # do nothing


def to_1d(arg: tp.ArrayLike, raw: bool = False) -> tp.AnyArray1d:
    """Reshape argument to one dimension. 

    If `raw` is True, returns NumPy array.
    If 2-dim, will collapse along axis 1 (i.e., DataFrame with one column to Series)."""
    arg = to_any_array(arg, raw=raw)
    if arg.ndim == 2:
        if arg.shape[1] == 1:
            if checks.is_frame(arg):
                return arg.iloc[:, 0]
            return arg[:, 0]
    if arg.ndim == 1:
        return arg
    elif arg.ndim == 0:
        return arg.reshape((1,))
    raise ValueError(f"Cannot reshape a {arg.ndim}-dimensional array to 1 dimension")


to_1d_array = functools.partial(to_1d, raw=True)


def to_2d(arg: tp.ArrayLike, raw: bool = False, expand_axis: int = 1) -> tp.AnyArray2d:
    """Reshape argument to two dimensions. 

    If `raw` is True, returns NumPy array.
    If 1-dim, will expand along axis 1 (i.e., Series to DataFrame with one column)."""
    arg = to_any_array(arg, raw=raw)
    if arg.ndim == 2:
        return arg
    elif arg.ndim == 1:
        if checks.is_series(arg):
            if expand_axis == 0:
                return pd.DataFrame(arg.values[None, :], columns=arg.index)
            elif expand_axis == 1:
                return arg.to_frame()
        return np.expand_dims(arg, expand_axis)
    elif arg.ndim == 0:
        return arg.reshape((1, 1))
    raise ValueError(f"Cannot reshape a {arg.ndim}-dimensional array to 2 dimensions")


to_2d_array = functools.partial(to_2d, raw=True)


def to_dict(arg: tp.ArrayLike, orient: str = 'dict') -> dict:
    """Convert object to dict."""
    arg = to_pd_array(arg)
    if orient == 'index_series':
        return {arg.index[i]: arg.iloc[i] for i in range(len(arg.index))}
    return arg.to_dict(orient)


def repeat(arg: tp.ArrayLike, n: int, axis: int = 1, raw: bool = False) -> tp.AnyArray:
    """Repeat each element in `arg` `n` times along the specified axis."""
    arg = to_any_array(arg, raw=raw)
    if axis == 0:
        if checks.is_pandas(arg):
            return wrapping.ArrayWrapper.from_obj(arg).wrap(
                np.repeat(arg.values, n, axis=0), index=indexes.repeat_index(arg.index, n))
        return np.repeat(arg, n, axis=0)
    elif axis == 1:
        arg = to_2d(arg)
        if checks.is_pandas(arg):
            return wrapping.ArrayWrapper.from_obj(arg).wrap(
                np.repeat(arg.values, n, axis=1), columns=indexes.repeat_index(arg.columns, n))
        return np.repeat(arg, n, axis=1)
    else:
        raise ValueError("Only axis 0 and 1 are supported")


def tile(arg: tp.ArrayLike, n: int, axis: int = 1, raw: bool = False) -> tp.AnyArray:
    """Repeat the whole `arg` `n` times along the specified axis."""
    arg = to_any_array(arg, raw=raw)
    if axis == 0:
        if arg.ndim == 2:
            if checks.is_pandas(arg):
                return wrapping.ArrayWrapper.from_obj(arg).wrap(
                    np.tile(arg.values, (n, 1)), index=indexes.tile_index(arg.index, n))
            return np.tile(arg, (n, 1))
        if checks.is_pandas(arg):
            return wrapping.ArrayWrapper.from_obj(arg).wrap(
                np.tile(arg.values, n), index=indexes.tile_index(arg.index, n))
        return np.tile(arg, n)
    elif axis == 1:
        arg = to_2d(arg)
        if checks.is_pandas(arg):
            return wrapping.ArrayWrapper.from_obj(arg).wrap(
                np.tile(arg.values, (1, n)), columns=indexes.tile_index(arg.columns, n))
        return np.tile(arg, (1, n))
    else:
        raise ValueError("Only axis 0 and 1 are supported")


IndexFromLike = tp.Union[None, str, int, tp.Any]
"""Any object that can be coerced into a `index_from` argument."""


def broadcast_index(args: tp.Sequence[tp.AnyArray],
                    to_shape: tp.Shape,
                    index_from: IndexFromLike = None,
                    axis: int = 0,
                    ignore_sr_names: tp.Optional[bool] = None,
                    **kwargs) -> tp.Optional[tp.Index]:
    """Produce a broadcast index/columns.

    Args:
        args (iterable of array_like): Array-like objects.
        to_shape (tuple of int): Target shape.
        index_from (any): Broadcasting rule for this index/these columns.

            Accepts the following values:

            * 'keep' or None - keep the original index/columns of the objects in `args`
            * 'stack' - stack different indexes/columns using `vectorbt.base.indexes.stack_indexes`
            * 'strict' - ensure that all Pandas objects have the same index/columns
            * 'reset' - reset any index/columns (they become a simple range)
            * integer - use the index/columns of the i-th object in `args`
            * everything else will be converted to `pd.Index`

        axis (int): Set to 0 for index and 1 for columns.
        ignore_sr_names (bool): Whether to ignore Series names if they are in conflict.

            Conflicting Series names are those that are different but not None.
        **kwargs: Keyword arguments passed to `vectorbt.base.indexes.stack_indexes`.

    For defaults, see `broadcasting` in `vectorbt._settings.settings`.

    !!! note
        Series names are treated as columns with a single element but without a name.
        If a column level without a name loses its meaning, better to convert Series to DataFrames
        with one column prior to broadcasting. If the name of a Series is not that important,
        better to drop it altogether by setting it to None.
    """
    from vectorbt._settings import settings
    broadcasting_cfg = settings['broadcasting']

    if ignore_sr_names is None:
        ignore_sr_names = broadcasting_cfg['ignore_sr_names']
    index_str = 'columns' if axis == 1 else 'index'
    to_shape_2d = (to_shape[0], 1) if len(to_shape) == 1 else to_shape
    # maxlen stores the length of the longest index
    maxlen = to_shape_2d[1] if axis == 1 else to_shape_2d[0]
    new_index = None
    args = list(args)

    if index_from is None or (isinstance(index_from, str) and index_from.lower() == 'keep'):
        return None
    if isinstance(index_from, int):
        # Take index/columns of the object indexed by index_from
        if not checks.is_pandas(args[index_from]):
            raise TypeError(f"Argument under index {index_from} must be a pandas object")
        new_index = indexes.get_index(args[index_from], axis)
    elif isinstance(index_from, str):
        if index_from.lower() == 'reset':
            # Ignore index/columns
            new_index = pd.RangeIndex(start=0, stop=maxlen, step=1)
        elif index_from.lower() in ('stack', 'strict'):
            # Check whether all indexes/columns are equal
            last_index = None  # of type pd.Index
            index_conflict = False
            for arg in args:
                if checks.is_pandas(arg):
                    index = indexes.get_index(arg, axis)
                    if last_index is not None:
                        if not checks.is_index_equal(index, last_index):
                            index_conflict = True
                    last_index = index
                    continue
            if not index_conflict:
                new_index = last_index
            else:
                # If pandas objects have different index/columns, stack them together
                for arg in args:
                    if checks.is_pandas(arg):
                        index = indexes.get_index(arg, axis)
                        if axis == 1 and checks.is_series(arg) and ignore_sr_names:
                            # ignore Series name
                            continue
                        if checks.is_default_index(index):
                            # ignore simple ranges without name
                            continue
                        if new_index is None:
                            new_index = index
                        else:
                            if index_from.lower() == 'strict':
                                # If pandas objects have different index/columns, raise an exception
                                if not checks.is_index_equal(index, new_index):
                                    raise ValueError(
                                        f"Broadcasting {index_str} is not allowed when {index_str}_from=strict")
                            # Broadcasting index must follow the rules of a regular broadcasting operation
                            # https://docs.scipy.org/doc/numpy/user/basics.broadcasting.html#general-broadcasting-rules
                            # 1. rule: if indexes are of the same length, they are simply stacked
                            # 2. rule: if index has one element, it gets repeated and then stacked

                            if checks.is_index_equal(index, new_index):
                                continue
                            if len(index) != len(new_index):
                                if len(index) > 1 and len(new_index) > 1:
                                    raise ValueError("Indexes could not be broadcast together")
                                if len(index) > len(new_index):
                                    new_index = indexes.repeat_index(new_index, len(index))
                                elif len(index) < len(new_index):
                                    index = indexes.repeat_index(index, len(new_index))
                            new_index = indexes.stack_indexes([new_index, index], **kwargs)
        else:
            raise ValueError(f"Invalid value '{index_from}' for {'columns' if axis == 1 else 'index'}_from")
    else:
        new_index = index_from
    if new_index is not None:
        if maxlen > len(new_index):
            if isinstance(index_from, str) and index_from.lower() == 'strict':
                raise ValueError(f"Broadcasting {index_str} is not allowed when {index_str}_from=strict")
            # This happens only when some numpy object is longer than the new pandas index
            # In this case, new pandas index (one element) must be repeated to match this length.
            if maxlen > 1 and len(new_index) > 1:
                raise ValueError("Indexes could not be broadcast together")
            new_index = indexes.repeat_index(new_index, maxlen)
    else:
        # new_index=None can mean two things: 1) take original metadata or 2) reset index/columns
        # In case when index_from is not None, we choose 2)
        new_index = pd.RangeIndex(start=0, stop=maxlen, step=1)
    return new_index


def wrap_broadcasted(old_arg: tp.AnyArray,
                     new_arg: tp.Array,
                     is_pd: bool = False,
                     new_index: tp.Optional[tp.Index] = None,
                     new_columns: tp.Optional[tp.Index] = None) -> tp.AnyArray:
    """If the newly brodcasted array was originally a Pandas object, make it Pandas object again
    and assign it the newly broadcast index/columns."""
    if is_pd:
        if checks.is_pandas(old_arg):
            if new_index is None:
                # Take index from original pandas object
                old_index = indexes.get_index(old_arg, 0)
                if old_arg.shape[0] == new_arg.shape[0]:
                    new_index = old_index
                else:
                    new_index = indexes.repeat_index(old_index, new_arg.shape[0])
            if new_columns is None:
                # Take columns from original pandas object
                old_columns = indexes.get_index(old_arg, 1)
                new_ncols = new_arg.shape[1] if new_arg.ndim == 2 else 1
                if len(old_columns) == new_ncols:
                    new_columns = old_columns
                else:
                    new_columns = indexes.repeat_index(old_columns, new_ncols)
        if new_arg.ndim == 2:
            return pd.DataFrame(new_arg, index=new_index, columns=new_columns)
        if new_columns is not None and len(new_columns) == 1:
            name = new_columns[0]
            if name == 0:
                name = None
        else:
            name = None
        return pd.Series(new_arg, index=new_index, name=name)
    return new_arg


def align_pd_arrays(args: tp.Iterable[tp.ArrayLike],
                    align_index: bool = True,
                    align_columns: bool = True) -> tp.List[tp.ArrayLike]:
    """Align Pandas arrays against common index and/or column levels using 
    `vectorbt.base.indexes.align_indexes`."""
    args = list(args)
    if align_index:
        index_to_align = []
        for i in range(len(args)):
            if checks.is_pandas(args[i]) and len(args[i].index) > 1:
                index_to_align.append(i)
        if len(index_to_align) > 1:
            indexes_ = [args[i].index for i in index_to_align]
            if len(set(map(len, indexes_))) > 1:
                index_indices = indexes.align_indexes(indexes_)
                for i in index_to_align:
                    args[i] = args[i].iloc[index_indices[index_to_align.index(i)]]
    if align_columns:
        cols_to_align = []
        for i in range(len(args)):
            if checks.is_frame(args[i]) and len(args[i].columns) > 1:
                cols_to_align.append(i)
        if len(cols_to_align) > 1:
            indexes_ = [args[i].columns for i in cols_to_align]
            if len(set(map(len, indexes_))) > 1:
                col_indices = indexes.align_indexes(indexes_)
                for i in cols_to_align:
                    args[i] = args[i].iloc[:, col_indices[cols_to_align.index(i)]]
    return args


def broadcast(*args,
              to_shape: tp.Optional[tp.ShapeLike] = None,
              to_pd: tp.Optional[tp.MaybeMappingSequence[bool]] = None,
              to_frame: tp.Optional[bool] = None,
              align_index: tp.Optional[bool] = None,
              align_columns: tp.Optional[bool] = None,
              index_from: tp.Optional[IndexFromLike] = None,
              columns_from: tp.Optional[IndexFromLike] = None,
              require_kwargs: tp.MaybeMappingSequence[tp.KwargsLike] = None,
              keep_raw: tp.MaybeMappingSequence[bool] = False,
              min_one_dim: tp.MaybeMappingSequence[bool] = True,
              return_meta: bool = False,
              **kwargs) -> tp.Any:
    """Bring any array-like object in `args` to the same shape by using NumPy broadcasting.

    See [Broadcasting](https://docs.scipy.org/doc/numpy/user/basics.broadcasting.html).

    Can broadcast Pandas objects by broadcasting their index/columns with `broadcast_index`.

    Args:
        *args (array_like): Array-like objects.

            If the first and only argument is a mapping, will return a dict.
        to_shape (tuple of int): Target shape. If set, will broadcast every element in `args` to `to_shape`.
        to_pd (bool, sequence or mapping): Whether to convert output arrays to Pandas objects, otherwise returns
            raw NumPy arrays. If None, converts only if there is at least one Pandas object among them.

            Can be provided per argument.
        to_frame (bool): Whether to convert all Series to DataFrames.
        align_index (bool): Whether to align index of Pandas objects using multi-index.

            Pass None to use the default.
        align_columns (bool): Whether to align columns of Pandas objects using multi-index.

            Pass None to use the default.
        index_from (any): Broadcasting rule for index.

            Pass None to use the default.
        columns_from (any): Broadcasting rule for columns.

            Pass None to use the default.
        require_kwargs (dict, sequence or mapping): Keyword arguments passed to `np.require`.

            Can be provided per argument.
        keep_raw (bool, sequence or mapping): Whether to keep the raw version of each array.
            Defaults to False.

            Only makes sure that the array can be broadcast to the target shape.
            Mostly used for flexible indexing.

            Can be provided per argument.
        min_one_dim (bool, sequence or dict): Whether to convert constants into 1-dim arrays.
            Defaults to True.

            Can be provided per argument.
        return_meta (bool): Whether to also return new shape, index and columns.
        **kwargs: Keyword arguments passed to `broadcast_index`.

    For defaults, see `broadcasting` in `vectorbt._settings.settings`.

    Any argument that can be passed as a mapping can include a key '_default'
    with the default value for other keys.

    ## Example

    Without broadcasting index and columns:

    ```python-repl
    >>> import numpy as np
    >>> import pandas as pd
    >>> from vectorbt.base.reshaping import broadcast

    >>> v = 0
    >>> a = np.array([1, 2, 3])
    >>> sr = pd.Series([1, 2, 3], index=pd.Index(['x', 'y', 'z']), name='a')
    >>> df = pd.DataFrame(
    ...     [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
    ...     index=pd.Index(['x2', 'y2', 'z2']),
    ...     columns=pd.Index(['a2', 'b2', 'c2']))

    >>> for i in broadcast(
    ...     v, a, sr, df,
    ...     index_from='keep',
    ...     columns_from='keep',
    ... ): print(i)
       0  1  2
    0  0  0  0
    1  0  0  0
    2  0  0  0
       0  1  2
    0  1  2  3
    1  1  2  3
    2  1  2  3
       a  a  a
    x  1  1  1
    y  2  2  2
    z  3  3  3
        a2  b2  c2
    x2   1   2   3
    y2   4   5   6
    z2   7   8   9
    ```

    Taking index and columns from the argument at specific position:

    ```python-repl
    >>> for i in broadcast(
    ...     v, a, sr, df,
    ...     index_from=2,
    ...     columns_from=3
    ... ): print(i)
       a2  b2  c2
    x   0   0   0
    y   0   0   0
    z   0   0   0
       a2  b2  c2
    x   1   2   3
    y   1   2   3
    z   1   2   3
       a2  b2  c2
    x   1   1   1
    y   2   2   2
    z   3   3   3
       a2  b2  c2
    x   1   2   3
    y   4   5   6
    z   7   8   9
    ```

    Broadcasting index and columns through stacking:

    ```python-repl
    >>> for i in broadcast(
    ...     v, a, sr, df,
    ...     index_from='stack',
    ...     columns_from='stack'
    ... ): print(i)
          a2  b2  c2
    x x2   0   0   0
    y y2   0   0   0
    z z2   0   0   0
          a2  b2  c2
    x x2   1   2   3
    y y2   1   2   3
    z z2   1   2   3
          a2  b2  c2
    x x2   1   1   1
    y y2   2   2   2
    z z2   3   3   3
          a2  b2  c2
    x x2   1   2   3
    y y2   4   5   6
    z z2   7   8   9
    ```

    Setting index and columns manually:

    ```python-repl
    >>> for i in broadcast(
    ...     v, a, sr, df,
    ...     index_from=['a', 'b', 'c'],
    ...     columns_from=['d', 'e', 'f']
    ... ): print(i)
       d  e  f
    a  0  0  0
    b  0  0  0
    c  0  0  0
       d  e  f
    a  1  2  3
    b  1  2  3
    c  1  2  3
       d  e  f
    a  1  1  1
    b  2  2  2
    c  3  3  3
       d  e  f
    a  1  2  3
    b  4  5  6
    c  7  8  9
    ```

    Passing arguments as a mapping:

    ```python-repl
    >>> broadcast(
    ...     dict(v=v, a=a, sr=sr, df=df),
    ...     index_from='stack'
    ... )
    {'v':       a2  b2  c2
          x x2   0   0   0
          y y2   0   0   0
          z z2   0   0   0,
     'a':       a2  b2  c2
          x x2   1   2   3
          y y2   1   2   3
          z z2   1   2   3,
     'sr':       a2  b2  c2
           x x2   1   1   1
           y y2   2   2   2
           z z2   3   3   3,
     'df':       a2  b2  c2
           x x2   1   2   3
           y y2   4   5   6
           z z2   7   8   9}
    ```

    Keeping all results raw apart from one:

    ```python-repl
    >>> broadcast(
    ...     dict(v=v, a=a, sr=sr, df=df),
    ...     index_from='stack',
    ...     keep_raw=dict(_default=True, df=False),
    ...     require_kwargs=dict(df=dict(dtype=float))
    ... )
    {'v': array([0]),
     'a': array([1, 2, 3]),
     'sr': array([[1],
                  [2],
                  [3]]),
     'df':        a2   b2   c2
           x x2  1.0  2.0  3.0
           y y2  4.0  5.0  6.0
           z z2  7.0  8.0  9.0}
    ```
    """
    from vectorbt._settings import settings
    broadcasting_cfg = settings['broadcasting']

    is_pd = False
    is_2d = False
    if align_index is None:
        align_index = broadcasting_cfg['align_index']
    if align_columns is None:
        align_columns = broadcasting_cfg['align_columns']
    if index_from is None:
        index_from = broadcasting_cfg['index_from']
    if columns_from is None:
        columns_from = broadcasting_cfg['columns_from']
    if checks.is_mapping(args[0]):
        if len(args) > 1:
            raise ValueError("Only one argument is allowed when passing a mapping")
        keys = list(dict(args[0]).keys())
        args = list(args[0].values())
        return_dict = True
    else:
        args = list(args)
        keys = list(range(len(args)))
        return_dict = False

    # Convert to np.ndarray object if not numpy or pandas
    # Also check whether we broadcast to pandas and whether work on 2-dim data
    arr_args = []
    for i in range(len(args)):
        arg = to_any_array(args[i])
        if arg.ndim > 1:
            is_2d = True
        if checks.is_pandas(arg):
            is_pd = True
        arr_args.append(arg)

    # If target shape specified, check again if we work on 2-dim data
    if to_shape is not None:
        if isinstance(to_shape, int):
            to_shape = (to_shape,)
        checks.assert_instance_of(to_shape, tuple)
        if len(to_shape) > 1:
            is_2d = True

    if to_frame is not None:
        # force either keeping Series or converting them to DataFrames
        is_2d = to_frame

    if to_pd is not None:
        # force either raw or pandas
        if checks.is_sequence(to_pd):
            is_pd = any(to_pd)
        elif checks.is_mapping(to_pd):
            is_pd = any([to_pd.get(k, False) for k in keys])
        else:
            is_pd = to_pd

    # Align pandas arrays
    arr_args = align_pd_arrays(arr_args, align_index=align_index, align_columns=align_columns)

    # Convert all pd.Series objects to pd.DataFrame if we work on 2-dim data
    arr_args_2d = [arg.to_frame() if is_2d and checks.is_series(arg) else arg for arg in arr_args]

    # Get final shape
    if to_shape is None:
        to_shape = _broadcast_shape(*map(np.asarray, arr_args_2d))
    if not isinstance(to_shape, tuple):
        to_shape = (to_shape,)
    if len(to_shape) == 0:
        to_shape = (1,)

    # Perform broadcasting
    new_args = []
    for i, arg in enumerate(arr_args_2d):
        if checks.is_sequence(min_one_dim):
            _min_one_dim = min_one_dim[i]
        elif checks.is_mapping(min_one_dim):
            _min_one_dim = min_one_dim.get(keys[i], min_one_dim.get('_default', True))
        else:
            _min_one_dim = min_one_dim
        if _min_one_dim and arg.ndim == 0:
            arg = arg[None]
        bc_arg = np.broadcast_to(arg, to_shape)
        if checks.is_sequence(keep_raw):
            _keep_raw = keep_raw[i]
        elif checks.is_mapping(keep_raw):
            _keep_raw = keep_raw.get(keys[i], keep_raw.get('_default', False))
        else:
            _keep_raw = keep_raw
        if _keep_raw:
            new_args.append(arg)
            continue
        new_args.append(bc_arg)

    # Force to match requirements
    require_kwargs_per_arg = True
    if checks.is_mapping(require_kwargs):
        require_arg_names = get_func_arg_names(np.require)
        if set(require_kwargs) <= set(require_arg_names):
            require_kwargs_per_arg = False
    for i in range(len(new_args)):
        if checks.is_sequence(require_kwargs):
            _require_kwargs = require_kwargs[i]
        elif checks.is_mapping(require_kwargs) and require_kwargs_per_arg:
            _require_kwargs = require_kwargs.get(keys[i], require_kwargs.get('_default', None))
        else:
            _require_kwargs = require_kwargs
        new_args[i] = np.require(new_args[i], **resolve_dict(_require_kwargs))

    if is_pd:
        # Decide on index and columns
        # NOTE: Important to pass arr_args, not arr_args_2d, to preserve original shape info
        new_index = broadcast_index(arr_args, to_shape, index_from=index_from, axis=0, **kwargs)
        new_columns = broadcast_index(arr_args, to_shape, index_from=columns_from, axis=1, **kwargs)
    else:
        new_index, new_columns = None, None

    # Bring arrays to their old types (e.g. array -> pandas)
    for i in range(len(new_args)):
        if checks.is_sequence(keep_raw):
            _keep_raw = keep_raw[i]
        elif checks.is_mapping(keep_raw):
            _keep_raw = keep_raw.get(keys[i], keep_raw.get('_default', False))
        else:
            _keep_raw = keep_raw
        if _keep_raw:
            continue
        if checks.is_sequence(to_pd):
            _is_pd = to_pd[i]
        elif checks.is_mapping(to_pd):
            _is_pd = to_pd.get(keys[i], is_pd)
        else:
            _is_pd = is_pd
        new_args[i] = wrap_broadcasted(
            arr_args[i],
            new_args[i],
            is_pd=_is_pd,
            new_index=new_index,
            new_columns=new_columns
        )

    if return_dict:
        new_args = dict(zip(keys, new_args))
    else:
        new_args = tuple(new_args)
    if len(new_args) > 1 or return_dict:
        if return_meta:
            return new_args, to_shape, new_index, new_columns
        return new_args
    if return_meta:
        return new_args[0], to_shape, new_index, new_columns
    return new_args[0]


def broadcast_to(arg1: tp.ArrayLike,
                 arg2: tp.ArrayLike,
                 to_pd: tp.Optional[bool] = None,
                 index_from: tp.Optional[IndexFromLike] = None,
                 columns_from: tp.Optional[IndexFromLike] = None,
                 **kwargs) -> tp.Any:
    """Broadcast `arg1` to `arg2`.

    Pass None to `index_from`/`columns_from` to use index/columns of the second argument.

    Keyword arguments `**kwargs` are passed to `broadcast`.

    ## Example

    ```python-repl
    >>> import numpy as np
    >>> import pandas as pd
    >>> from vectorbt.base.reshaping import broadcast_to

    >>> a = np.array([1, 2, 3])
    >>> sr = pd.Series([4, 5, 6], index=pd.Index(['x', 'y', 'z']), name='a')

    >>> broadcast_to(a, sr)
    x    1
    y    2
    z    3
    Name: a, dtype: int64

    >>> broadcast_to(sr, a)
    array([4, 5, 6])
    ```
    """
    arg1 = to_any_array(arg1)
    arg2 = to_any_array(arg2)
    if to_pd is None:
        to_pd = checks.is_pandas(arg2)
    if to_pd:
        # Take index and columns from arg2
        if index_from is None:
            index_from = indexes.get_index(arg2, 0)
        if columns_from is None:
            columns_from = indexes.get_index(arg2, 1)
    return broadcast(
        arg1,
        to_shape=arg2.shape,
        to_pd=to_pd,
        index_from=index_from,
        columns_from=columns_from,
        **kwargs
    )


def broadcast_to_array_of(arg1: tp.ArrayLike, arg2: tp.ArrayLike) -> tp.Array:
    """Broadcast `arg1` to the shape `(1, *arg2.shape)`.

    `arg1` must be either a scalar, a 1-dim array, or have 1 dimension more than `arg2`.

    ## Example

    ```python-repl
    >>> import numpy as np
    >>> from vectorbt.base.reshaping import broadcast_to_array_of

    >>> broadcast_to_array_of([0.1, 0.2], np.empty((2, 2)))
    [[[0.1 0.1]
      [0.1 0.1]]

     [[0.2 0.2]
      [0.2 0.2]]]
    ```
    """
    arg1 = np.asarray(arg1)
    arg2 = np.asarray(arg2)
    if arg1.ndim == arg2.ndim + 1:
        if arg1.shape[1:] == arg2.shape:
            return arg1
    # From here on arg1 can be only a 1-dim array
    if arg1.ndim == 0:
        arg1 = to_1d(arg1)
    checks.assert_ndim(arg1, 1)

    if arg2.ndim == 0:
        return arg1
    for i in range(arg2.ndim):
        arg1 = np.expand_dims(arg1, axis=-1)
    return np.tile(arg1, (1, *arg2.shape))


def broadcast_to_axis_of(arg1: tp.ArrayLike, arg2: tp.ArrayLike, axis: int,
                         require_kwargs: tp.KwargsLike = None) -> tp.Array:
    """Broadcast `arg1` to an axis of `arg2`.

    If `arg2` has less dimensions than requested, will broadcast `arg1` to a single number.

    For other keyword arguments, see `broadcast`."""
    if require_kwargs is None:
        require_kwargs = {}
    arg2 = to_any_array(arg2)
    if arg2.ndim < axis + 1:
        return np.broadcast_to(arg1, (1,))[0]  # to a single number
    arg1 = np.broadcast_to(arg1, (arg2.shape[axis],))
    arg1 = np.require(arg1, **require_kwargs)
    return arg1


def broadcast_combs(*args: tp.ArrayLike,
                    axis: int = 1,
                    comb_func: tp.Callable = itertools.product,
                    broadcast_kwargs: tp.KwargsLike = None) -> tp.Any:
    """Align an axis of each array using a combinatoric function and broadcast their indexes.

    ## Example

    ```python-repl
    >>> import numpy as np
    >>> from vectorbt.base.reshaping import broadcast_combs

    >>> df = pd.DataFrame([[1, 2, 3], [3, 4, 5]], columns=pd.Index(['a', 'b', 'c'], name='df_param'))
    >>> df2 = pd.DataFrame([[6, 7], [8, 9]], columns=pd.Index(['d', 'e'], name='df2_param'))
    >>> sr = pd.Series([10, 11], name='f')

    >>> new_df, new_df2, new_sr = broadcast_combs((df, df2, sr))

    >>> new_df
    df_param   a     b     c
    df2_param  d  e  d  e  d  e
    0          1  1  2  2  3  3
    1          3  3  4  4  5  5

    >>> new_df2
    df_param   a     b     c
    df2_param  d  e  d  e  d  e
    0          6  7  6  7  6  7
    1          8  9  8  9  8  9

    >>> new_sr
    df_param    a       b       c
    df2_param   d   e   d   e   d   e
    0          10  10  10  10  10  10
    1          11  11  11  11  11  11
    ```"""
    if broadcast_kwargs is None:
        broadcast_kwargs = {}

    args = list(args)
    if len(args) < 2:
        raise ValueError("At least two arguments are required")
    for i in range(len(args)):
        arg = to_any_array(args[i])
        if axis == 1:
            arg = to_2d(arg)
        args[i] = arg
    indices = []
    for arg in args:
        indices.append(np.arange(len(indexes.get_index(to_pd_array(arg), axis))))
    new_indices = list(map(list, zip(*list(comb_func(*indices)))))
    results = []
    for i, arg in enumerate(args):
        if axis == 1:
            if checks.is_pandas(arg):
                results.append(arg.iloc[:, new_indices[i]])
            else:
                results.append(arg[:, new_indices[i]])
        else:
            if checks.is_pandas(arg):
                results.append(arg.iloc[new_indices[i]])
            else:
                results.append(arg[new_indices[i]])
    if axis == 1:
        broadcast_kwargs = merge_dicts(dict(columns_from='stack'), broadcast_kwargs)
    else:
        broadcast_kwargs = merge_dicts(dict(index_from='stack'), broadcast_kwargs)
    return broadcast(*results, **broadcast_kwargs)


def get_multiindex_series(arg: tp.SeriesFrame) -> tp.Series:
    """Get Series with a multi-index.

    If DataFrame has been passed, must at maximum have one row or column."""
    checks.assert_instance_of(arg, (pd.Series, pd.DataFrame))
    if checks.is_frame(arg):
        if arg.shape[0] == 1:
            arg = arg.iloc[0, :]
        elif arg.shape[1] == 1:
            arg = arg.iloc[:, 0]
        else:
            raise ValueError("Supported are either Series or DataFrame with one column/row")
    checks.assert_instance_of(arg.index, pd.MultiIndex)
    return arg


def unstack_to_array(arg: tp.SeriesFrame, levels: tp.Optional[tp.MaybeLevelSequence] = None) -> tp.Array:
    """Reshape `arg` based on its multi-index into a multi-dimensional array.

    Use `levels` to specify what index levels to unstack and in which order.

    ## Example

    ```python-repl
    >>> import pandas as pd
    >>> from vectorbt.base.reshaping import unstack_to_array

    >>> index = pd.MultiIndex.from_arrays(
    ...     [[1, 1, 2, 2], [3, 4, 3, 4], ['a', 'b', 'c', 'd']])
    >>> sr = pd.Series([1, 2, 3, 4], index=index)

    >>> unstack_to_array(sr).shape
    (2, 2, 4)

    >>> unstack_to_array(sr)
    [[[ 1. nan nan nan]
     [nan  2. nan nan]]

     [[nan nan  3. nan]
    [nan nan nan  4.]]]

    >>> unstack_to_array(sr, levels=(2, 0))
    [[ 1. nan]
     [ 2. nan]
     [nan  3.]
     [nan  4.]]
    ```
    """
    # Extract series
    sr: tp.Series = to_1d(get_multiindex_series(arg))
    if sr.index.duplicated().any():
        raise ValueError("Index contains duplicate entries, cannot reshape")

    unique_idx_list = []
    vals_idx_list = []
    if levels is None:
        levels = range(sr.index.nlevels)
    if isinstance(levels, (int, str)):
        levels = (levels,)
    for level in levels:
        vals = indexes.select_levels(sr.index, level).to_numpy()
        unique_vals = np.unique(vals)
        unique_idx_list.append(unique_vals)
        idx_map = dict(zip(unique_vals, range(len(unique_vals))))
        vals_idx = list(map(lambda x: idx_map[x], vals))
        vals_idx_list.append(vals_idx)

    a = np.full(list(map(len, unique_idx_list)), np.nan)
    a[tuple(zip(vals_idx_list))] = sr.values
    return a


def make_symmetric(arg: tp.SeriesFrame, sort: bool = True) -> tp.Frame:
    """Make `arg` symmetric.

    The index and columns of the resulting DataFrame will be identical.

    Requires the index and columns to have the same number of levels.

    Pass `sort=False` if index and columns should not be sorted, but concatenated
    and get duplicates removed.

    ## Example

    ```python-repl
    >>> import pandas as pd
    >>> from vectorbt.base.reshaping import make_symmetric

    >>> df = pd.DataFrame([[1, 2], [3, 4]], index=['a', 'b'], columns=['c', 'd'])

    >>> make_symmetric(df)
         a    b    c    d
    a  NaN  NaN  1.0  2.0
    b  NaN  NaN  3.0  4.0
    c  1.0  3.0  NaN  NaN
    d  2.0  4.0  NaN  NaN
    ```
    """
    checks.assert_instance_of(arg, (pd.Series, pd.DataFrame))
    df: tp.Frame = to_2d(arg)
    if isinstance(df.index, pd.MultiIndex) or isinstance(df.columns, pd.MultiIndex):
        checks.assert_instance_of(df.index, pd.MultiIndex)
        checks.assert_instance_of(df.columns, pd.MultiIndex)
        checks.assert_array_equal(df.index.nlevels, df.columns.nlevels)
        names1, names2 = tuple(df.index.names), tuple(df.columns.names)
    else:
        names1, names2 = df.index.name, df.columns.name

    if names1 == names2:
        new_name = names1
    else:
        if isinstance(df.index, pd.MultiIndex):
            new_name = tuple(zip(*[names1, names2]))
        else:
            new_name = (names1, names2)
    if sort:
        idx_vals = np.unique(np.concatenate((df.index, df.columns))).tolist()
    else:
        idx_vals = list(dict.fromkeys(np.concatenate((df.index, df.columns))))
    df_index = df.index.copy()
    df_columns = df.columns.copy()
    if isinstance(df.index, pd.MultiIndex):
        unique_index = pd.MultiIndex.from_tuples(idx_vals, names=new_name)
        df_index.names = new_name
        df_columns.names = new_name
    else:
        unique_index = pd.Index(idx_vals, name=new_name)
        df_index.name = new_name
        df_columns.name = new_name
    df = df.copy(deep=False)
    df.index = df_index
    df.columns = df_columns
    df_out_dtype = np.promote_types(df.values.dtype, np.min_scalar_type(np.nan))
    df_out = pd.DataFrame(index=unique_index, columns=unique_index, dtype=df_out_dtype)
    df_out.loc[:, :] = df
    df_out[df_out.isnull()] = df.transpose()
    return df_out


def unstack_to_df(arg: tp.SeriesFrame,
                  index_levels: tp.Optional[tp.MaybeLevelSequence] = None,
                  column_levels: tp.Optional[tp.MaybeLevelSequence] = None,
                  symmetric: bool = False,
                  sort: bool = True) -> tp.Frame:
    """Reshape `arg` based on its multi-index into a DataFrame.

    Use `index_levels` to specify what index levels will form new index, and `column_levels` 
    for new columns. Set `symmetric` to True to make DataFrame symmetric.

    ## Example

    ```python-repl
    >>> import pandas as pd
    >>> from vectorbt.base.reshaping import unstack_to_df

    >>> index = pd.MultiIndex.from_arrays(
    ...     [[1, 1, 2, 2], [3, 4, 3, 4], ['a', 'b', 'c', 'd']],
    ...     names=['x', 'y', 'z'])
    >>> sr = pd.Series([1, 2, 3, 4], index=index)

    >>> unstack_to_df(sr, index_levels=(0, 1), column_levels=2)
    z      a    b    c    d
    x y
    1 3  1.0  NaN  NaN  NaN
    1 4  NaN  2.0  NaN  NaN
    2 3  NaN  NaN  3.0  NaN
    2 4  NaN  NaN  NaN  4.0
    ```
    """
    # Extract series
    sr: tp.Series = to_1d(get_multiindex_series(arg))

    if len(sr.index.levels) > 2:
        if index_levels is None:
            raise ValueError("index_levels must be specified")
        if column_levels is None:
            raise ValueError("column_levels must be specified")
    else:
        if index_levels is None:
            index_levels = 0
        if column_levels is None:
            column_levels = 1

    # Build new index and column hierarchies
    new_index = indexes.select_levels(arg.index, index_levels).unique()
    new_columns = indexes.select_levels(arg.index, column_levels).unique()

    # Unstack and post-process
    unstacked = unstack_to_array(sr, levels=(index_levels, column_levels))
    df = pd.DataFrame(unstacked, index=new_index, columns=new_columns)
    if symmetric:
        return make_symmetric(df, sort=sort)
    return df
