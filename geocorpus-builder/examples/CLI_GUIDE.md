# GeoCorpus-Builder CLI 操作指南

## 环境要求

```bash
pip install geocorpus-builder[spatial]    # 含 geopandas + shapely + rasterio
```

## 数据准备

假设你手上有三个文件：

| 文件 | 说明 |
|------|------|
| `china_province.shp` | 中国省级行政区划边界 |
| `glacier_boundaries.shp` | 冰川多边形边界（含字段 `glacier_id`, `glacier_name`） |
| `thickness_2024.tif` | 2024年冰川厚度栅格 |
| `thickness_2017.tif` | 2017年冰川厚度栅格 |

---

## 第一步：导入空间数据层（一次性）

将中国省界和冰川边界转为 GeoParquet，写死到包内：

```bash
# 省级行政区划
geocorpus spatial import china_province.shp \
  --layer cn_provinces \
  --layer-name "中国省级行政区划" \
  --layer-type admin_boundary \
  --name-field name_zh \
  --id-field adcode

# 冰川边界（可选: 如需查询冰川自身边界）
geocorpus spatial import glacier_boundaries.shp \
  --layer glaciers \
  --layer-name "冰川边界" \
  --name-field glacier_name \
  --id-field glacier_id
```

验证：
```bash
geocorpus spatial list
# 应显示 cn_provinces 和 glaciers 两个层
```

---

## 第二步：TIFF 分区统计

对每个 TIFF 栅格，以冰川多边形为单位计算统计值：

```bash
# 2024年冰川厚度
geocorpus spatial zonal-stats \
  --raster thickness_2024.tif \
  --vector glacier_boundaries.shp \
  --output stats/thickness_2024.csv \
  --id-field glacier_id

# 2017年冰川厚度
geocorpus spatial zonal-stats \
  --raster thickness_2017.tif \
  --vector glacier_boundaries.shp \
  --output stats/thickness_2017.csv \
  --id-field glacier_id

# 其他变量（例如 DEM 高程）
geocorpus spatial zonal-stats \
  --raster dem.tif \
  --vector glacier_boundaries.shp \
  --output stats/dem.csv \
  --id-field glacier_id \
  --stats "mean,median,std,min,max"
```

> `--stats` 可选: mean, median, std, min, max, count, sum。默认全部计算。

生成的 CSV 示例 (`stats/thickness_2024.csv`)：

| glacier_id | mean | median | std | min | max | count | lon | lat | variable |
|------------|-------|--------|-----|-----|-----|-------|------|------|----------|
| GL001 | 120.5 | 121.0 | 15.3 | 80.2 | 155.0 | 3420 | 86.92 | 28.02 | thickness_2024 |
| GL002 | 95.3 | 96.0 | 12.1 | 65.0 | 130.5 | 2801 | 90.15 | 29.05 | thickness_2024 |

---

## 第三步：初始化项目

```bash
geocorpus init ./glacier_project --domain cryosphere --subdomain glacier
```

目录结构：
```
glacier_project/
├── geocorpus_config.json
├── corpus/          # 语料单元输出目录
├── evidence/        # 证据链接输出目录
├── data/            # 种子数据
├── statistics/      # 统计表存放目录
└── templates/       # 自定义模板（可选）
```

---

## 第四步：采集统计结果为证据

```bash
# 拷贝CSV到项目
cp stats/thickness_2024.csv glacier_project/statistics/
cp stats/thickness_2017.csv glacier_project/statistics/

# 转换为 evidence_links
geocorpus ingest glacier_project/statistics/thickness_2024.csv \
  -t raster \
  --variable glacier_thickness \
  --time-range 2024

geocorpus ingest glacier_project/statistics/thickness_2017.csv \
  -t raster \
  --variable glacier_thickness \
  --time-range 2017
```

---

## 第五步：构建语料 + 空间富化

```bash
geocorpus build -p glacier_project --spatial-enrich
```

这一步会：
- 从统计表渲染中文语料文本
- 用 `lon`/`lat` 自动判断每条冰川属于哪个省份
- 生成省归属证据链接

输出：
```
Build complete: 136 corpus units, 272 evidence links
  [spatial] Enriched 136 region assignments across 1 spatial layers
```

---

## 第六步：数据质量校验

```bash
geocorpus validate glacier_project

# JSON 格式报告
geocorpus validate glacier_project -r json

# 仅摘要
geocorpus validate glacier_project -r summary
```

---

## 第七步：查询

```bash
# 单次查询
geocorpus query -p glacier_project -q "西藏哪些冰川变薄最快？"

# 交互模式
geocorpus query -p glacier_project --interactive
```

查询结果示例：
```
问题: 西藏哪些冰川变薄最快？
类型: data_query | 置信度: high

根据语料库中的证据记录，找到 8 条相关数据：

- glacier_thickness mean = 118.2 m （对象: GL_PUMORI, 时间: 2024, 来源: thickness_2024.csv, 证据ID: EV_0003）
- glacier_thickness mean = 120.5 m （对象: GL_PUMORI, 时间: 2017, 来源: thickness_2017.csv, 证据ID: EV_0001）

缺失的数据表: glacier_change_stats
建议: 请先使用 geocorpus ingest 导入变化统计，再重新查询。

引用证据: EV_0001, EV_0003, EV_SPATIAL_0001, EV_SPATIAL_0002
```

---

## 额外：构建变化统计

如果你需要 2017→2024 的变化量，可以先生成一个 change 表：

```python
import pandas as pd

t2017 = pd.read_csv("stats/thickness_2017.csv")
t2024 = pd.read_csv("stats/thickness_2024.csv")

change = t2017[["glacier_id", "lon", "lat"]].copy()
change["mean_change"] = t2024["mean"].values - t2017["mean"].values
change["time_range"] = "2017-2024"
change["variable"] = "glacier_thickness_change"
change.to_parquet("glacier_project/statistics/glacier_change_stats.parquet")
```

然后重新 build：
```bash
geocorpus build -p glacier_project --spatial-enrich
geocorpus query -p glacier_project -q "2017到2024年西藏冰川平均厚度变化多少？"
```

---

## Space 查询（独立使用）

```bash
# 查看所有空间层
geocorpus spatial list

# 经纬度定位
geocorpus spatial locate --lon 86.9 --lat 28.0

# 查询邻接省份
geocorpus spatial neighbors 540000 --layer cn_provinces

# 两点距离
geocorpus spatial distance \
  --geom-a "POINT(86.9 28.0)" \
  --geom-b "POINT(116.4 39.9)"
```

---

## 命令速查

| 命令 | 用途 |
|------|------|
| `geocorpus spatial import` | SHP → GeoParquet |
| `geocorpus spatial zonal-stats` | TIFF + 矢量 → 统计CSV |
| `geocorpus spatial list` | 列出空间层 |
| `geocorpus spatial locate` | 经纬度 → 所属区域 |
| `geocorpus spatial neighbors` | 区域邻接查询 |
| `geocorpus init` | 初始化项目 |
| `geocorpus ingest` | 统计表 → evidence_links |
| `geocorpus build --spatial-enrich` | 统计表 → 语料 + 空间归属 |
| `geocorpus validate` | 数据质量校验 |
| `geocorpus query` | 基于证据的问答 |
