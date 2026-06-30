# 同花顺App热榜数

**文档ID**: 320
**原始链接**: https://tushare.pro/document/2?doc_id=320

---

## 同花顺热榜

接口：ths_hot描述：获取同花顺App热榜数据，包括热股、概念板块、ETF、可转债、港美股等等，每日盘中提取4次，收盘后4次，最晚22点提取一次。限量：单次最大2000条，可根据日期等参数循环获取全部数据积分：用户积5000积分可调取使用，积分获取办法请参阅积分获取办法注意：本接口只限个人学习和研究使用，如需商业用途，请自行联系同花顺解决数据采购问题。

输入参数

<table>
<thead>
<tr>
<th>名称</th>
<th>类型</th>
<th>必选</th>
<th>描述</th>
</tr>
</thead>
<tbody><tr>
<td>trade_date</td>
<td>str</td>
<td>N</td>
<td>交易日期</td>
</tr>
<tr>
<td>ts_code</td>
<td>str</td>
<td>N</td>
<td>TS代码</td>
</tr>
<tr>
<td>market</td>
<td>str</td>
<td>N</td>
<td>热榜类型(热股、ETF、可转债、行业板块、概念板块、期货、港股、热基、美股)</td>
</tr>
<tr>
<td>is_new</td>
<td>str</td>
<td>N</td>
<td>是否最新（默认Y，如果为N则为盘中和盘后阶段采集，具体时间可参考rank_time字段，状态N每小时更新一次，状态Y更新时间为22：30）</td>
</tr>
</tbody></table>

输出参数

<table>
<thead>
<tr>
<th>名称</th>
<th>类型</th>
<th>默认显示</th>
<th>描述</th>
</tr>
</thead>
<tbody><tr>
<td>trade_date</td>
<td>str</td>
<td>Y</td>
<td>交易日期</td>
</tr>
<tr>
<td>data_type</td>
<td>str</td>
<td>Y</td>
<td>数据类型</td>
</tr>
<tr>
<td>ts_code</td>
<td>str</td>
<td>Y</td>
<td>股票代码</td>
</tr>
<tr>
<td>ts_name</td>
<td>str</td>
<td>Y</td>
<td>股票名称</td>
</tr>
<tr>
<td>rank</td>
<td>int</td>
<td>Y</td>
<td>排行</td>
</tr>
<tr>
<td>pct_change</td>
<td>float</td>
<td>Y</td>
<td>涨跌幅%</td>
</tr>
<tr>
<td>current_price</td>
<td>float</td>
<td>Y</td>
<td>当前价格</td>
</tr>
<tr>
<td>concept</td>
<td>str</td>
<td>Y</td>
<td>标签</td>
</tr>
<tr>
<td>rank_reason</td>
<td>str</td>
<td>Y</td>
<td>上榜解读</td>
</tr>
<tr>
<td>hot</td>
<td>float</td>
<td>Y</td>
<td>热度值</td>
</tr>
<tr>
<td>rank_time</td>
<td>str</td>
<td>Y</td>
<td>排行榜获取时间</td>
</tr>
</tbody></table>

接口示例

```

#获取查询月份券商金股
df = pro.ths_hot(trade_date='20240315', market='热股', fields='ts_code,ts_name,hot,concept')

```

数据示例

```
        ts_code ts_name       hot                  concept
0   300750.SZ    宁德时代  214462.0    ["钠离子电池", "储能", "固态电池", "储能概念", "新能源汽车", "宁德时代概念", "电池概念", "锂电池"]
1   300033.SZ    同花顺   214462.0    ["大数据", "人工智能", "云计算", "区块链", "大数据概念", "人工智能概念", "云计算概念", "区块链概念", "互联网金融"]
2   002594.SZ    比亚迪   214462.0    ["新能源车", "新能源汽车", "比亚迪概念", "储能", "固态电池", "储能概念", "新能源汽车概念", "电池概念"]
3   600519.SH    贵州茅台   214462.0    ["白酒", "消费", "白酒概念", "消费概念", "大消费", "消费升级", "消费降级", "消费升级概念"]
4   300760.SZ    迈瑞医疗   214462.0    ["医疗器械", "医疗", "医药", "医疗器械概念", "医疗概念", "医药概念", "医疗健康", "医药健康"]
5   300124.SZ    汇川技术   214462.0    ["工业自动化", "新能源汽车", "储能", "工业机器人", "工业自动化概念", "新能源汽车概念", "储能概念", "工业机器人概念"]
...
```
