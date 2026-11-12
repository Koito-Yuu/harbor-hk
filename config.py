from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "hk.db"
STATIC_DIR = BASE_DIR / "static"

for _p in (DATA_DIR, RAW_DIR):
    _p.mkdir(parents=True, exist_ok=True)

APP_NAME = "Harbor · 港股投研台"
APP_VERSION = "1.0.0"
PORT = int(os.environ.get("HK_PORT", "8767"))

TZ = "Asia/Hong_Kong"
BUYBACK_START = os.environ.get("HK_BUYBACK_START", "2026-01-01")
SHORT_START = os.environ.get("HK_SHORT_START", "2025-06-01")
UNIVERSE_MIN_MCAP = 3.0  # 亿港元，低于此市值不进入市场广度统计

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

INDICES = [
    {"code": "HSI", "name": "恒生指数", "short": "恒指"},
    {"code": "HSCEI", "name": "恒生中国企业指数", "short": "国企指数"},
    {"code": "HSTECH", "name": "恒生科技指数", "short": "恒生科技"},
]

# 核心观察池：用于行业温度、估值锚与深度财务跟踪
CORE_POOL = [
    ("00700", "腾讯控股", "互联网平台"),
    ("09988", "阿里巴巴-W", "互联网平台"),
    ("03690", "美团-W", "互联网平台"),
    ("09618", "京东集团-SW", "互联网平台"),
    ("09999", "网易-S", "互联网平台"),
    ("01024", "快手-W", "互联网平台"),
    ("09888", "百度集团-SW", "互联网平台"),
    ("03888", "金山软件", "互联网平台"),
    ("09961", "携程集团-S", "互联网平台"),
    ("00780", "同程旅行", "互联网平台"),
    ("02423", "贝壳-W", "互联网平台"),
    ("01810", "小米集团-W", "硬科技/半导体"),
    ("00981", "中芯国际", "硬科技/半导体"),
    ("01347", "华虹半导体", "硬科技/半导体"),
    ("00522", "ASMPT", "硬科技/半导体"),
    ("02382", "舜宇光学科技", "硬科技/半导体"),
    ("00285", "比亚迪电子", "硬科技/半导体"),
    ("02018", "瑞声科技", "硬科技/半导体"),
    ("09660", "地平线机器人-W", "硬科技/半导体"),
    ("00020", "商汤-W", "硬科技/半导体"),
    ("06160", "百济神州", "医药生物"),
    ("01801", "信达生物", "医药生物"),
    ("02359", "药明康德", "医药生物"),
    ("02269", "药明生物", "医药生物"),
    ("01093", "石药集团", "医药生物"),
    ("01177", "中国生物制药", "医药生物"),
    ("03692", "翰森制药", "医药生物"),
    ("09926", "康方生物", "医药生物"),
    ("06990", "科伦博泰生物-B", "医药生物"),
    ("02196", "复星医药", "医药生物"),
    ("00005", "汇丰控股", "金融"),
    ("03988", "中国银行", "金融"),
    ("00939", "建设银行", "金融"),
    ("01398", "工商银行", "金融"),
    ("03968", "招商银行", "金融"),
    ("02318", "中国平安", "金融"),
    ("01299", "友邦保险", "金融"),
    ("02628", "中国人寿", "金融"),
    ("00388", "香港交易所", "金融"),
    ("02601", "中国太保", "金融"),
    ("02388", "中银香港", "金融"),
    ("00016", "新鸿基地产", "地产/收租"),
    ("00001", "长和", "地产/收租"),
    ("01109", "华润置地", "地产/收租"),
    ("00688", "中国海外发展", "地产/收租"),
    ("00083", "信和置业", "地产/收租"),
    ("00823", "领展房产基金", "地产/收租"),
    ("01997", "九龙仓置业", "地产/收租"),
    ("01209", "华润万象生活", "地产/收租"),
    ("09992", "泡泡玛特", "消费"),
    ("02020", "安踏体育", "消费"),
    ("02331", "李宁", "消费"),
    ("06862", "海底捞", "消费"),
    ("09633", "农夫山泉", "消费"),
    ("00291", "华润啤酒", "消费"),
    ("01044", "恒安国际", "消费"),
    ("01929", "周大福", "消费"),
    ("06690", "海尔智家", "消费"),
    ("01876", "百威亚太", "消费"),
    ("00322", "康师傅控股", "消费"),
    ("06969", "思摩尔国际", "消费"),
    ("00883", "中国海洋石油", "能源/资源"),
    ("00857", "中国石油股份", "能源/资源"),
    ("00386", "中国石油化工股份", "能源/资源"),
    ("01088", "中国神华", "能源/资源"),
    ("01898", "中煤能源", "能源/资源"),
    ("02899", "紫金矿业", "能源/资源"),
    ("03993", "洛阳钼业", "能源/资源"),
    ("01378", "中国宏桥", "能源/资源"),
    ("00902", "华能国际电力股份", "能源/资源"),
    ("00916", "龙源电力", "能源/资源"),
    ("01211", "比亚迪股份", "汽车/工业"),
    ("09868", "小鹏汽车-W", "汽车/工业"),
    ("02015", "理想汽车-W", "汽车/工业"),
    ("09866", "蔚来-SW", "汽车/工业"),
    ("00175", "吉利汽车", "汽车/工业"),
    ("02333", "长城汽车", "汽车/工业"),
    ("00669", "创科实业", "汽车/工业"),
    ("00941", "中国移动", "电讯/公用"),
    ("00762", "中国联通", "电讯/公用"),
    ("00728", "中国电信", "电讯/公用"),
    ("00002", "中电控股", "电讯/公用"),
    ("00003", "香港中华煤气", "电讯/公用"),
    ("00006", "电能实业", "电讯/公用"),
]

CORE = [{"code": c, "name": n, "sector": s} for c, n, s in CORE_POOL]
CORE_MAP = {x["code"]: x for x in CORE}
SECTOR_ORDER = [
    "互联网平台",
    "硬科技/半导体",
    "医药生物",
    "金融",
    "地产/收租",
    "消费",
    "能源/资源",
    "汽车/工业",
    "电讯/公用",
]

SOURCES = [
    {
        "name": "港交所 · 股份回购报告",
        "detail": "每日 SRRPT*.xls，覆盖全部上市公司场内/场外回购披露",
        "url": "https://www3.hkexnews.hk/reports/sharerepur/sbn.asp",
    },
    {
        "name": "腾讯财经 · 港股行情",
        "detail": "实时/延迟报价、市值、PE/PB、股息率、52 周区间、日 K",
        "url": "https://gu.qq.com/",
    },
    {
        "name": "AKShare · 港股财务与南向资金",
        "detail": "东方财富财务指标与港股通历史资金流",
        "url": "https://github.com/akfamily/akshare",
    },
    {
        "name": "港交所 · 证券名单",
        "detail": "全市场上市证券名录与板块分类",
        "url": "https://www.hkex.com.hk/",
    },
    {
        "name": "HKEX · 权益披露 (DION)",
        "detail": "5%+ 大股东、董事及最高行政人员的权益与增减持披露",
        "url": "https://di.hkex.com.hk/di/NSSrchCorp.aspx?src=MAIN&lang=EN&g_lang=en",
    },
    {
        "name": "SFC · 淡仓持仓汇总",
        "detail": "证监会每周《指定股份的合计须申报淡仓》CSV，覆盖全市场可卖空标的的持仓股数与市值",
        "url": "https://www.sfc.hk/en/Regulatory-functions/Market/Short-position-reporting/Aggregated-reportable-short-positions-of-specified-shares",
    },
    {
        "name": "HKMA · 每日金融数据",
        "detail": "银行体系总结余、HIBOR、基准利率、兑换保证与外汇基金数据",
        "url": "https://www.hkma.gov.hk/eng/data-publications-and-research/data-and-statistics/daily-monetary-statistics/",
    },
    {
        "name": "HKAB · HIBOR 定盘",
        "detail": "港元同业拆息各期限定盘曲线",
        "url": "https://www.hkab.org.hk/en/rates/hibor",
    },
    {
        "name": "FRED · 美国利率与汇率",
        "detail": "美债 2Y/10Y/30Y、实际利率、SOFR、VIX、USD/HKD、USD/CNY",
        "url": "https://fred.stlouisfed.org/",
    },
]

OSS_CREDITS = [
    ("AKShare", "Apache-2.0", "开源财经数据接口，用于财务指标与南向资金", "https://github.com/akfamily/akshare"),
    ("Apache ECharts", "Apache-2.0", "交互式图表引擎", "https://echarts.apache.org/"),
    ("Flask", "BSD-3-Clause", "轻量 Web 服务", "https://flask.palletsprojects.com/"),
    ("pandas / xlrd", "BSD-3-Clause", "表格数据解析", "https://pandas.pydata.org/"),
    ("OpenBB", "AGPL-3.0", "投研平台交互与指标设计参考（未复用代码）", "https://github.com/OpenBB-finance/OpenBB"),
    ("yfinance", "Apache-2.0", "港股行情备选数据源评估（未启用）", "https://github.com/ranaroussi/yfinance"),
    ("Futu OpenAPI", "Apache-2.0", "券商级行情/回购数据方案评估（需 OpenD 与账户，未启用）", "https://github.com/FutunnOpen/py-futu-api"),
]
