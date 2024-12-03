import os
import pandas as pd
import backtrader as bt
import matplotlib.pyplot as plt
from analyzing_tools import Analyzing_Tools
from itertools import product
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

def ADX_River(target_assets, paths,window_1=28):
    #信号结果字典
    results = {}
    #全数据字典，包含计算指标用于检查
    full_info={}
    
    #编写策略主体部分
    for code in target_assets:
        # 读取数据
        daily_data = pd.read_csv(os.path.join(paths['daily'], f"{code}.csv"), index_col=[0])
        daily_data.index = pd.to_datetime(daily_data.index)

        df=daily_data.copy()
        # 计算
        
        #满江红策略
        # 保留一位小数
        df = df.round(0)

        #信号触发
        # 计算每日涨跌幅
        df['涨跌幅'] = (df['close'] - df['open']) / df['open']
        
        # 如果每日涨跌幅在-0.02到0.03之间，则为1，否则为0
        df['涨跌幅标记'] = ((df['涨跌幅'] >= -0.02) & (df['涨跌幅'] <= 0.03)).astype(int)
        
        #涨跌幅连续十天符合
        df['连续涨跌幅']=df['涨跌幅标记'].rolling(window=10).sum()

        # 连续红K线条件：最近10个交易日中至少有7根或以上的K线收红
        
        df['连续红K线'] = (df['close'] > df['open']).astype(int)
        
        df['连续红K线'] = df['连续红K线'].rolling(window=10).sum()
        #合并所有信息，上下信息
        df['diff'] = ((df['连续涨跌幅']==10) & 
                    (df['连续红K线'] >= 7)).astype(int)
        # 添加signal列，使用apply函数
        df['signal_1'] = -1  # 初始化 signal 列为 -1

        for i in range(len(df)):
            if df['diff'][i] > 0:
                for j in range(i, min(i + 1, len(df))):  # 循环处理当天及未来四天
                    df['signal_1'][j] = 1
        
        #ADX策略
        df['high_low'] = df['high'] - df['low']
        df['high_close'] = np.abs(df['high'] - df['close'].shift())
        df['low_close'] = np.abs(df['low'] - df['close'].shift())
        df['TR'] = df[['high_low', 'high_close', 'low_close']].max(axis=1)
        
        # 计算 Directional Movement (+DM 和 -DM)
        df['+DM'] = np.where((df['high'] > df['high'].shift()) & 
                            (df['high'] - df['high'].shift() > df['low'].shift() - df['low']), 
                            df['high'] - df['high'].shift(), 0)
        df['-DM'] = np.where((df['low'].shift() > df['low']) & 
                            (df['low'].shift() - df['low'] > df['high'] - df['high'].shift()), 
                            df['low'].shift() - df['low'], 0)
        
        # 平滑 +DM, -DM 和 TR
        df['smoothed+DM'] = df['+DM'].ewm(alpha=1/window_1, adjust=False).mean()
        df['smoothed-DM'] = df['-DM'].ewm(alpha=1/window_1, adjust=False).mean()
        df['smoothed_TR'] = df['TR'].ewm(alpha=1/window_1, adjust=False).mean()
        
        # 计算 +DI 和 -DI，衡量正向和负向运动的强度
        df['+DI'] = 100 * (df['smoothed+DM'] / df['smoothed_TR'])
        df['-DI'] = 100 * (df['smoothed-DM'] / df['smoothed_TR'])
        
        # 计算 DX 和 ADX，ADX 表示趋势的强度，不考虑趋势的方向
        
        df['DX'] = 100 * np.abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI'])
        df['ADX'] = df['DX'].ewm(alpha=1/window_1, adjust=False).mean()
        df['signal_2'] = 0

        #看多为1，看空为-1
        df.loc[df['+DI'] > df['-DI'], 'signal_2'] = 1
        df.loc[df['+DI'] <= df['-DI'], 'signal_2'] = -1

        df['signal_sum']=df['signal_1']+df['signal_2']
        # 添加signal列，使用apply函数
        df['signal'] = df['signal_sum'].apply(lambda x: 1 if x > -2 else -1)
        result=df
        # 将信号合并回每日数据
        daily_data = daily_data.join(result[['signal']], how='left')
        daily_data[['signal']].fillna(0, inplace=True)
        daily_data=daily_data.dropna()

        # 存储结果
        results[code] = daily_data
        full_info[code]=result

    return results,full_info

# 自定义数据类，包含 'signal'
class PandasDataPlusSignal(bt.feeds.PandasData):
    lines = ('signal',)
    params = (
        ('signal', -1),  # 默认情况下，'signal' 列在最后一列   
    )

# 策略类，包含调试信息和导出方法
class ADX_River_Strategy(bt.Strategy):
    params = (
        ('size_pct',0.166),  # 每个资产的仓位百分比
    )

    def __init__(self):
        self.orders = {}         # 用于跟踪每个资产的订单状态
        self.trade_counts = {}   # 记录每个资产的交易次数
        self.value = []          # 存储组合总净值
        self.dates = []          # 存储日期序列
        self.debug_info = []     # 存储调试信息

        for data in self.datas:
            name = data._name
            self.trade_counts[name] = 0
            self.orders[name] = None

    def next(self):
        total_value = self.broker.getvalue()
        self.value.append(total_value)
        current_date = self.datas[0].datetime.datetime(0)
        self.dates.append(current_date)

        for data in self.datas:
            name = data._name
            position_size = self.getposition(data).size
            signal = data.signal[0]

            # 根据信号执行交易
            if signal == 1 and position_size == 0:
                size = self.calculate_position_size(data)
                self.orders[name] = self.buy(data=data, size=size)
                self.trade_counts[name] += 1

            elif signal == -1 and position_size > 0:
                self.orders[name] = self.close(data=data)
                self.trade_counts[name] += 1


            # 存储调试信息
            self.debug_info.append({
                'Date': current_date,
                'Asset': name,
                'Position': position_size,
                'Signal': signal,
                'Size': self.calculate_position_size(data),
                'Open':data.open[0],
                'High':data.high[0],
                'Low':data.low[0],
                'Volume':data.volume[0],
                'Close': data.close[0],
                'Cash': self.broker.getcash(),
                'Value': total_value,
                'Trades': self.trade_counts[name],
            })


    def calculate_position_size(self, data):
        """
        计算仓位大小
        """
        available_cash = self.broker.getvalue()
        current_price = data.close[0]
        max_investment = available_cash * self.params.size_pct
        max_shares = int(max_investment / current_price)
        return max_shares

    def notify_order(self, order):
        """
        订单完成后重置状态
        """
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            name = order.data._name
            self.orders[name] = None

    def get_net_value_series(self):
        """
        返回净值序列，用于后续分析
        """
        return pd.DataFrame(self.value, index=self.dates)

    def get_debug_df(self):
        """
        返回包含调试信息的DataFrame
        """
        df = pd.DataFrame(self.debug_info)
        df.set_index('Date', inplace=True)
        return df


def run_backtest(strategy, target_assets, strategy_results, cash=100000.0, commission=0.0002, slippage_perc=0.0005, slippage_fixed=None, **kwargs):
    
    cerebro = bt.Cerebro()  # 初始化Cerebro引擎
    cerebro.addstrategy(strategy, **kwargs)  # 添加策略
    
    for code in target_assets:
        data = PandasDataPlusSignal(dataname=strategy_results[code])
        data._name = code  # 为数据设置名称，便于识别
        cerebro.adddata(data)
    
    # 使用setcommission设置股票模式的佣金
    cerebro.broker.setcommission(
        commission=commission,  # 佣金百分比
        stocklike=True  # 将交易设置为股票模式
    )
    
    cerebro.broker.setcash(cash)  # 设置初始资金

    # 设置滑点
    if slippage_perc is not None:
        cerebro.broker.set_slippage_perc(slippage_perc)  # 设置百分比滑点
    elif slippage_fixed is not None:
        cerebro.broker.set_slippage_fixed(slippage_fixed)  # 设置固定点滑点
    
    strategies = cerebro.run()  # 运行回测
    return strategies[0]



#加载分析工具
AT=Analyzing_Tools()


# 定义数据路径
paths = {
    'daily': r'D:\数据库\同花顺ETF跟踪指数量价数据\1d',
    'hourly': r'D:\数据库\同花顺ETF跟踪指数量价数据\1h',
    'min15': r'D:\数据库\同花顺ETF跟踪指数量价数据\15min',
    'pv_export':r"D:\量化交易构建\私募基金研究\股票策略研究\Time_Series_Backtesting\策略净值序列"
}

# 资产列表
target_assets = [
    "000016.SH",
    "000300.SH",
    "000852.SH",
    "000905.SH",
    "399006.SZ",
    "399303.SZ"
]

strtegy_name='ADX_River'

# 生成信号
strategy_results,full_info = ADX_River(target_assets, paths)


# 获取策略实例
strat = run_backtest(ADX_River_Strategy,target_assets,strategy_results,10000000,0,0)

#获取净值
pv=strat.get_net_value_series()

#输出策略名称
pv.to_excel(paths["pv_export"]+'\\'+strtegy_name+'.xlsx')

portfolio_value, returns, drawdown_ts, metrics = AT.performance_analysis(pv, freq='D')

# 获取净值序列
index_price_path=paths['daily']

AT.plot_results('000906.SH',index_price_path,portfolio_value, drawdown_ts, returns, metrics)

# 获取调试信息
debug_df = strat.get_debug_df()

#蒙特卡洛分析

AT.monte_carlo_analysis(strat,num_simulations=10000,num_days=252,freq='D')


#定义参数优化函数
def parameter_optimization(parameter_grid, strategy_function, strategy_class, target_assets, paths, cash=100000.0, commission=0.0002, slippage_perc=0.0005, metric='sharpe_ratio'):   
    """
    执行参数优化，支持一个或两个参数。

    参数：
    - parameter_grid: 字典，包含参数名称和要测试的取值列表。例如：{'window_1': [30, 34, 38]}
    - strategy_function: 生成信号的策略函数，例如 UDVD
    - strategy_class: Backtrader 策略类，例如 UDVD_Strategy
    - target_assets: 资产列表
    - paths: 数据路径字典
    - cash: 初始资金
    - commission: 佣金
    - slippage_perc: 滑点百分比
    - metric: 选择用于评估的绩效指标，默认为 'sharpe_ratio'
    """

    #加载数据类

    # 获取参数名称和取值列表
    param_names = list(parameter_grid.keys())
    param_values = [parameter_grid[key] for key in param_names]

    # 生成所有参数组合
    param_combinations = [dict(zip(param_names, values)) for values in product(*param_values)]

    results = []

    for params in param_combinations:
        print(f"正在测试参数组合：{params}")
        # 生成当前参数下的信号
        strategy_results, full_info = strategy_function(target_assets, paths, **params)

        # 运行回测
        strat = run_backtest(strategy_class, target_assets, strategy_results, cash, commission, slippage_perc)

        # 获取净值序列
        pv = strat.get_net_value_series()

        # 计算绩效指标
        portfolio_value, returns, drawdown_ts, metrics =AT.performance_analysis(pv)

        # 收集指标和参数
        result_entry = {k: v for k, v in params.items()}
        result_entry.update(metrics)
        result_entry=pd.DataFrame(result_entry)
        results.append(result_entry)

    # 将结果转换为 DataFrame
    results_df = pd.concat(results,axis=0)
    results_df=results_df.dropna()

    # 可视化结果
    if len(param_names) == 1:
        # 绘制参数与绩效指标的关系曲线
        param = param_names[0]
        plt.figure(figsize=(10, 6))
        plt.plot(results_df[param], results_df[metric], marker='o')
        plt.xlabel(param)
        plt.ylabel(metric)
        plt.title(f'{metric} vs {param}')
        plt.grid(True)
        plt.show()
    elif len(param_names) == 2:
        # 绘制热力图
        param1 = param_names[0]
        param2 = param_names[1]
        pivot_table = results_df.pivot(index=param1, columns=param2, values=metric)

        plt.figure(figsize=(15, 12))  # 调整图像大小
        sns.heatmap(pivot_table, annot=True, fmt=".4f", cmap='viridis',
                    annot_kws={"size": 8}, linewidths=0.5, linecolor='white')
        plt.title(f'{metric} Heatmap', fontsize=16)
        plt.ylabel(param1, fontsize=14)
        plt.xlabel(param2, fontsize=14)
        plt.xticks(rotation=45)
        plt.yticks(rotation=0)
        plt.tight_layout()  # 自动调整布局
        plt.show()
    else:
        print("无法可视化超过两个参数的结果，请减少参数数量。")

    # 返回结果 DataFrame
    return results_df


# 定义参数网格
parameter_grid = {
    'window_1': range(5, 30,2),
    'window_2':range(20,50,2),
}

# # # 运行参数优化
# results_df = parameter_optimization(
#     parameter_grid=parameter_grid,
#     strategy_function=EMA,
#     strategy_class=EMA_Strategy,
#     target_assets=target_assets,
#     paths=paths,
#     cash=10000000,
#     commission=0.0005,
#     slippage_perc=0.0005,
#     metric='sharpe_ratio'
# )
