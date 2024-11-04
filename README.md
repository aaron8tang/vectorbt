<div align="center">
    <a href="https://vectorbt.pro/" alt="https://vectorbt.pro/">
        <img src="https://raw.githubusercontent.com/polakowo/vectorbt/master/docs/docs/assets/logo/header-pro.svg" />
    </a>
</div>
<div align="center">
    <a href="https://vectorbt.dev/" alt="https://vectorbt.dev/">
        <img src="https://raw.githubusercontent.com/polakowo/vectorbt/master/docs/docs/assets/logo/header.svg" />
    </a>
</div>
<br>
<p align="center">
    <a href="https://pepy.tech/project/vectorbt" alt="Downloads">
        <img src="https://pepy.tech/badge/vectorbt" />
    </a>
    <a href="https://pypi.org/project/vectorbt" alt="PyPi">
        <img src="https://img.shields.io/pypi/v/vectorbt?color=blueviolet" />
    </a>
    <a href="https://github.com/polakowo/vectorbt/blob/master/LICENSE.md" alt="License">
	<img src="https://img.shields.io/badge/license-Fair%20Code-yellow" />
    </a>
    <a href="https://codecov.io/gh/polakowo/vectorbt" alt="codecov">
        <img src="https://codecov.io/gh/polakowo/vectorbt/branch/master/graph/badge.svg?token=YTLNAI7PS3" />
    </a>
    <a href="https://vectorbt.dev/" alt="Website">
        <img src="https://img.shields.io/website?url=https://vectorbt.dev/" />
    </a>
    <a href="https://mybinder.org/v2/gh/polakowo/vectorbt/HEAD?urlpath=lab" alt="Binder">
        <img src="https://img.shields.io/badge/launch-binder-d6604a" />
    </a>
    <a href="https://gitter.im/vectorbt/community?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge" alt="Join the chat at https://gitter.im/vectorbt/community">
        <img src="https://badges.gitter.im/vectorbt.svg" />
    </a>
</p>
<p align="center">
    <a href="https://pypi.org/project/vectorbt" alt="Python Versions">
        <img src="https://img.shields.io/pypi/pyversions/vectorbt.svg?logo=python&logoColor=white" />
    </a>
</p>

## :sparkles: Usage

vectorbt allows you to easily backtest strategies with a couple of lines of Python code.

* Here is how much profit we would have made if we invested $100 into Bitcoin in 2014:

```python
import vectorbt as vbt

price = vbt.YFData.download('BTC-USD').get('Close')

pf = vbt.Portfolio.from_holding(price, init_cash=100)
pf.total_profit()
```

```plaintext
8961.008555963961
```

* Buy whenever 10-day SMA crosses above 50-day SMA and sell when opposite:

```python
fast_ma = vbt.MA.run(price, 10)
slow_ma = vbt.MA.run(price, 50)
entries = fast_ma.ma_crossed_above(slow_ma)
exits = fast_ma.ma_crossed_below(slow_ma)

pf = vbt.Portfolio.from_signals(price, entries, exits, init_cash=100)
pf.total_profit()
```

```plaintext
16423.251963801864
```

* Generate 1,000 strategies with random signals and test them on BTC and ETH:

```python
import numpy as np

symbols = ["BTC-USD", "ETH-USD"]
price = vbt.YFData.download(symbols, missing_index='drop').get('Close')

n = np.random.randint(10, 101, size=1000).tolist()
pf = vbt.Portfolio.from_random_signals(price, n=n, init_cash=100, seed=42)

mean_expectancy = pf.trades.expectancy().groupby(['randnx_n', 'symbol']).mean()
fig = mean_expectancy.unstack().vbt.scatterplot(xaxis_title='randnx_n', yaxis_title='mean_expectancy')
fig.show()
```

![rand_scatter.svg](https://raw.githubusercontent.com/polakowo/vectorbt/master/docs/docs/assets/images/usage_rand_scatter.svg)

* For fans of hyperparameter optimization: here is a snippet for testing 10,000 window combinations of a 
dual SMA crossover strategy on BTC, USD, and LTC:

```python
symbols = ["BTC-USD", "ETH-USD", "LTC-USD"]
price = vbt.YFData.download(symbols, missing_index='drop').get('Close')

windows = np.arange(2, 101)
fast_ma, slow_ma = vbt.MA.run_combs(price, window=windows, r=2, short_names=['fast', 'slow'])
entries = fast_ma.ma_crossed_above(slow_ma)
exits = fast_ma.ma_crossed_below(slow_ma)

pf_kwargs = dict(size=np.inf, fees=0.001, freq='1D')
pf = vbt.Portfolio.from_signals(price, entries, exits, **pf_kwargs)

fig = pf.total_return().vbt.heatmap(
    x_level='fast_window', y_level='slow_window', slider_level='symbol', symmetric=True,
    trace_kwargs=dict(colorbar=dict(title='Total return', tickformat='%')))
fig.show()
```

<img width="650" src="https://raw.githubusercontent.com/polakowo/vectorbt/master/docs/docs/assets/images/usage_dmac_heatmap.gif">

Digging into each strategy configuration is as simple as indexing with pandas:

```python
pf[(10, 20, 'ETH-USD')].stats()
```

```plaintext
Start                          2015-08-07 00:00:00+00:00
End                            2021-08-01 00:00:00+00:00
Period                                2183 days 00:00:00
Start Value                                        100.0
End Value                                  620402.791485
Total Return [%]                           620302.791485
Benchmark Return [%]                        92987.961948
Max Gross Exposure [%]                             100.0
Total Fees Paid                             10991.676981
Max Drawdown [%]                               70.734951
Max Drawdown Duration                  760 days 00:00:00
Total Trades                                          54
Total Closed Trades                                   53
Total Open Trades                                      1
Open Trade PnL                              67287.940601
Win Rate [%]                                   52.830189
Best Trade [%]                               1075.803607
Worst Trade [%]                               -29.593414
Avg Winning Trade [%]                          95.695343
Avg Losing Trade [%]                          -11.890246
Avg Winning Trade Duration    35 days 23:08:34.285714286
Avg Losing Trade Duration                8 days 00:00:00
Profit Factor                                   2.651143
Expectancy                                   10434.24247
Sharpe Ratio                                    2.041211
Calmar Ratio                                      4.6747
Omega Ratio                                     1.547013
Sortino Ratio                                   3.519894
Name: (10, 20, ETH-USD), dtype: object
```

The same for plotting:

```python
pf[(10, 20, 'ETH-USD')].plot().show()
```

![dmac_portfolio.svg](https://raw.githubusercontent.com/polakowo/vectorbt/master/docs/docs/assets/images/usage_dmac_portfolio.svg)

It's not all about backtesting - vectorbt can be used to facilitate financial data analysis and visualization.

* Let's generate a GIF that animates the %B and bandwidth of Bollinger Bands for different symbols:

```python
symbols = ["BTC-USD", "ETH-USD", "ADA-USD"]
price = vbt.YFData.download(symbols, period='6mo', missing_index='drop').get('Close')
bbands = vbt.BBANDS.run(price)

def plot(index, bbands):
    bbands = bbands.loc[index]
    fig = vbt.make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.15,
        subplot_titles=('%B', 'Bandwidth'))
    fig.update_layout(template='vbt_dark', showlegend=False, width=750, height=400)
    bbands.percent_b.vbt.ts_heatmap(
        trace_kwargs=dict(zmin=0, zmid=0.5, zmax=1, colorscale='Spectral', colorbar=dict(
            y=(fig.layout.yaxis.domain[0] + fig.layout.yaxis.domain[1]) / 2, len=0.5
        )), add_trace_kwargs=dict(row=1, col=1), fig=fig)
    bbands.bandwidth.vbt.ts_heatmap(
        trace_kwargs=dict(colorbar=dict(
            y=(fig.layout.yaxis2.domain[0] + fig.layout.yaxis2.domain[1]) / 2, len=0.5
        )), add_trace_kwargs=dict(row=2, col=1), fig=fig)
    return fig

vbt.save_animation('bbands.gif', bbands.wrapper.index, plot, bbands, delta=90, step=3, fps=3)
```

```plaintext
100%|██████████| 31/31 [00:21<00:00,  1.21it/s]
```

<img width="750" src="https://raw.githubusercontent.com/polakowo/vectorbt/master/docs/docs/assets/images/usage_bbands.gif">

And this is just the tip of the iceberg of what's possible. Check out the [website](https://vectorbt.dev/) to learn more.

## Installation

```sh
pip install -U vectorbt
```

To also install optional dependencies:

```sh
pip install -U "vectorbt[full]"
```

## Colab Notebook

[Google Colaboratory](https://colab.research.google.com/drive/1ibqyrf6LPFlzRb6mkPpl3hxqL6ryNBXI?usp=sharing)

## License

This work is [fair-code](http://faircode.io/) distributed under [Apache 2.0 with Commons Clause](https://github.com/polakowo/vectorbt/blob/master/LICENSE.md) license. 
The source code is open and everyone (individuals and organizations) can use it for free. 
However, it is not allowed to sell products and services that are mostly just this software.

If you have any questions about this or want to apply for a license exception, please [contact the author](mailto:olegpolakow@gmail.com).

Installing optional dependencies may be subject to a more restrictive license.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=polakowo/vectorbt&type=Timeline)](https://star-history.com/#polakowo/vectorbt&Timeline)

## Disclaimer

This software is for educational purposes only. Do not risk money which you are afraid to lose. 
USE THE SOFTWARE AT YOUR OWN RISK. THE AUTHORS AND ALL AFFILIATES ASSUME NO RESPONSIBILITY FOR YOUR TRADING RESULTS.
