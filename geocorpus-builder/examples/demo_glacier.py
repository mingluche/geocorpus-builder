"""
GeoCorpus-Builder 完整演示脚本
==============================
从零开始：初始化项目 → 创建模拟空间数据 → 导入数据 → 构建语料 → 校验 → 查询
"""

import json
import shutil
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon, Point, box

# 将项目 src 加入 path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from geocorpus_builder.main import cli
from geocorpus_builder.io import read_jsonl
from geocorpus_builder.spatial import SpatialQueryEngine

DEMO_DIR = Path(__file__).parent / "demo_project"


def banner(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def create_mock_spatial_data():
    """创建一套简化的中国省级边界数据 (GeoParquet)，用于演示空间查询。"""
    banner("Step 0: 创建模拟中国省级空间数据层")
    data_dir = Path(__file__).parent.parent / "src" / "geocorpus_builder" / "spatial" / "data"

    # 青藏高原周边省份的简化矩形边界 (实际使用时替换为真实 SHP)
    provinces = [
        {"adcode": "110000", "name_zh": "北京市", "name_en": "Beijing",
         "geometry": Polygon([(115.4, 39.4), (117.5, 39.4), (117.5, 41.1), (115.4, 41.1)])},
        {"adcode": "120000", "name_zh": "天津市", "name_en": "Tianjin",
         "geometry": Polygon([(116.7, 38.5), (118.0, 38.5), (118.0, 40.3), (116.7, 40.3)])},
        {"adcode": "130000", "name_zh": "河北省", "name_en": "Hebei",
         "geometry": Polygon([(113.5, 36.0), (119.8, 36.0), (119.8, 42.6), (113.5, 42.6)])},
        {"adcode": "540000", "name_zh": "西藏自治区", "name_en": "Tibet",
         "geometry": Polygon([(78.4, 26.9), (99.1, 26.9), (99.1, 36.5), (78.4, 36.5)])},
        {"adcode": "630000", "name_zh": "青海省", "name_en": "Qinghai",
         "geometry": Polygon([(89.4, 31.5), (103.0, 31.5), (103.0, 39.3), (89.4, 39.3)])},
        {"adcode": "650000", "name_zh": "新疆维吾尔自治区", "name_en": "Xinjiang",
         "geometry": Polygon([(73.5, 34.3), (96.4, 34.3), (96.4, 49.2), (73.5, 49.2)])},
        {"adcode": "510000", "name_zh": "四川省", "name_en": "Sichuan",
         "geometry": Polygon([(97.3, 26.0), (108.5, 26.0), (108.5, 34.3), (97.3, 34.3)])},
        {"adcode": "530000", "name_zh": "云南省", "name_en": "Yunnan",
         "geometry": Polygon([(97.5, 21.1), (106.2, 21.1), (106.2, 29.3), (97.5, 29.3)])},
        {"adcode": "620000", "name_zh": "甘肃省", "name_en": "Gansu",
         "geometry": Polygon([(92.8, 32.6), (108.7, 32.6), (108.7, 42.8), (92.8, 42.8)])},
    ]

    gdf = gpd.GeoDataFrame(provinces, crs="EPSG:4326")
    gdf.to_parquet(data_dir / "cn_provinces.geoparquet")

    meta = {
        "layer_id": "cn_provinces",
        "layer_name": "中国省级行政区划",
        "layer_type": "admin_boundary",
        "geometry_type": "polygon",
        "crs": "EPSG:4326",
        "name_field": "name_zh",
        "id_field": "adcode",
        "fields": ["adcode", "name_zh", "name_en"],
        "feature_count": len(gdf),
        "source": "demo_mock_data",
        "imported_at": "2026-05-24",
        "notes": "演示用简化的矩形边界，实际使用时替换为真实SHP导入的数据",
    }
    (data_dir / "cn_provinces.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  [OK] 已创建 {len(gdf)} 个省份的模拟边界数据")


def create_sample_glacier_data():
    """创建模拟冰川统计数据 (Parquet)。"""
    banner("Step 1: 创建模拟冰川统计表")

    demo_dir = DEMO_DIR
    stats_dir = demo_dir / "statistics"
    stats_dir.mkdir(parents=True, exist_ok=True)

    # ---- glacier_yearly_stats: 冰川逐年厚度统计 ----
    yearly_data = []
    glaciers = [
        # (id, lon, lat, 所在省份)
        ("GL_PUMORI", 86.9, 28.0, "西藏"),     # 普莫里峰附近
        ("GL_NOIJINKANGSANG", 90.2, 29.0, "西藏"),  # 宁金岗桑峰
        ("GL_QILIAN_01", 100.2, 38.5, "青海"),       # 祁连山
        ("GL_QILIAN_02", 99.5, 39.0, "甘肃"),        # 祁连山西段
        ("GL_TIANSHAN_01", 86.5, 43.2, "新疆"),      # 天山
        ("GL_TIANSHAN_02", 85.0, 42.8, "新疆"),      # 天山
        ("GL_HABA", 100.1, 27.4, "云南"),             # 哈巴雪山
        ("GL_GONGGA", 101.9, 29.6, "四川"),           # 贡嘎山
    ]

    for year in range(2017, 2025):
        for gid, lon, lat, prov in glaciers:
            base_thickness = 100 + (int(gid.encode().hex(), 16) % 50)
            trend = -1.5 + (hash(gid) % 10) * 0.1
            noise = (hash(f"{gid}{year}") % 20 - 10) * 0.3
            thickness = base_thickness + trend * (year - 2017) + noise
            yearly_data.append({
                "glacier_id": gid,
                "year": year,
                "mean": round(thickness, 2),
                "median": round(thickness + (hash(gid) % 5 - 2), 2),
                "p10": round(thickness - 25, 2),
                "p90": round(thickness + 20, 2),
                "variable": "glacier_thickness",
                "lon": lon,
                "lat": lat,
            })

    yearly_df = pd.DataFrame(yearly_data)
    yearly_df.to_parquet(stats_dir / "glacier_yearly_stats.parquet")

    # ---- glacier_change_stats: 冰川变化统计 ----
    change_data = []
    for gid, lon, lat, prov in glaciers:
        start_thick = yearly_df[
            (yearly_df["glacier_id"] == gid) & (yearly_df["year"] == 2017)
        ]["mean"].values[0]
        end_thick = yearly_df[
            (yearly_df["glacier_id"] == gid) & (yearly_df["year"] == 2024)
        ]["mean"].values[0]
        change_data.append({
            "glacier_id": gid,
            "mean_change": round(end_thick - start_thick, 2),
            "thinning_rate_myr": round((end_thick - start_thick) / 7, 3),  # m/yr over 7 years
            "time_range": "2017-2024",
            "variable": "glacier_thickness_change",
            "lon": lon,
            "lat": lat,
        })

    change_df = pd.DataFrame(change_data)
    change_df.to_parquet(stats_dir / "glacier_change_stats.parquet")

    print(f"  [OK] 创建了 {len(yearly_data)} 条冰川逐年统计记录 ({len(glaciers)} 条冰川 x 8 年)")
    print(f"  [OK] 创建了 {len(change_data)} 条冰川变化统计记录")


def step_init():
    """初始化 GeoCorpus 项目。"""
    banner("Step 2: geocorpus init")
    cli(["init", str(DEMO_DIR), "--domain", "cryosphere", "--subdomain", "glacier"],
        standalone_mode=False)

    # 列出项目文件
    for p in sorted(DEMO_DIR.rglob("*")):
        if p.is_file() and "__pycache__" not in str(p):
            print(f"  {p.relative_to(DEMO_DIR)}")


def step_ingest():
    """演示 ingest 命令：将 crosswalk 数据采集成 evidence_links。"""
    banner("Step 3: geocorpus ingest (crosswalk)")

    # 创建一个冰川-网格 crosswalk 表
    cw = pd.DataFrame({
        "object_id": ["GL_PUMORI", "GL_PUMORI", "GL_QILIAN_01", "GL_QILIAN_01"],
        "grid_id": ["G1001", "G1002", "G2001", "G2002"],
        "area_fraction": [0.65, 0.35, 0.80, 0.20],
        "weight": [0.65, 0.35, 0.80, 0.20],
    })
    cw_path = DEMO_DIR / "statistics" / "crosswalk.csv"
    cw.to_csv(cw_path, index=False)

    cli(["ingest", str(cw_path), "-t", "crosswalk",
         "-o", str(DEMO_DIR / "evidence" / "crosswalk_links.jsonl")],
        standalone_mode=False)


def step_build():
    """演示 build 命令：从 Parquet 数据生成语料单元 + 空间富化。"""
    banner("Step 4: geocorpus build --spatial-enrich")
    cli(["build", "-p", str(DEMO_DIR), "--spatial-enrich"], standalone_mode=False)

    # 查看生成结果
    units = read_jsonl(DEMO_DIR / "corpus" / "corpus_units.jsonl")
    links = read_jsonl(DEMO_DIR / "evidence" / "evidence_links.jsonl")

    spatial_links = [l for l in links if "SPATIAL" in l.get("evidence_id", "")]
    print(f"\n  生成结果:")
    print(f"    语料单元: {len(units)} 条")
    print(f"    证据链接: {len(links)} 条 (其中 {len(spatial_links)} 条空间归属)")

    print("\n  语料单元示例:")
    for u in units[:3]:
        regions = u.get("spatial_regions", {})
        prov = regions.get("cn_provinces", {}).get("name", "未知")
        print(f"    [{u['corpus_id']}] {u['text'][:60]}...")
        print(f"      -> 省份归属: {prov}, 证据: {', '.join(u['evidence_ids'][:3])}")

    # 统计各省份的冰川分布
    print("\n  各省冰川分布 (来自空间富化):")
    prov_count = {}
    for u in units:
        regions = u.get("spatial_regions", {})
        prov = regions.get("cn_provinces", {}).get("name", "未知")
        prov_count[prov] = prov_count.get(prov, 0) + 1
    for prov, count in sorted(prov_count.items(), key=lambda x: -x[1]):
        print(f"    {prov}: {count // 2} 条冰川")  # //2 because each glacier has mean+median


def step_validate():
    """演示 validate 命令：校验语料数据质量。"""
    banner("Step 5: geocorpus validate")
    try:
        cli(["validate", str(DEMO_DIR), "-r", "summary"], standalone_mode=False)
    except SystemExit:
        pass


def step_query():
    """演示 query 命令：基于证据的问答。"""
    banner("Step 6: geocorpus query (RAG 问答)")

    questions = [
        "祁连山冰川的厚度变化趋势如何？",
        "天山地区有哪些冰川？",
        "2017-2024年西藏的冰川平均厚度变化是多少？",
    ]

    for q in questions:
        print(f"\n  >>> 问题: {q}")
        print("  ---")
        cli(["query", "-p", str(DEMO_DIR), "-q", q], standalone_mode=False)


def step_spatial_demo():
    """演示 geocorpus spatial 命令组。"""
    banner("Step 7: geocorpus spatial 空间查询演示")

    # 列出空间层
    print("\n[spatial list]")
    cli(["spatial", "list"], standalone_mode=False)

    # 点位定位
    print("\n[spatial locate] 天山某冰川坐标")
    cli(["spatial", "locate", "--lon", "86.5", "--lat", "43.2", "-f", "json"],
        standalone_mode=False)

    # 邻接查询
    print("\n[spatial neighbors] 青海省的邻接省份")
    cli(["spatial", "neighbors", "630000", "--layer", "cn_provinces"],
        standalone_mode=False)

    # 距离计算
    print("\n[spatial distance] 珠峰大本营 → 贡嘎山")
    cli(["spatial", "distance",
         "--geom-a", "POINT(86.85 28.0)",
         "--geom-b", "POINT(101.9 29.6)"],
        standalone_mode=False)


def step_python_api_demo():
    """演示 Python API：在代码中直接调用空间查询引擎。"""
    banner("Step 8: Python API 演示 (SpatialQueryEngine)")

    engine = SpatialQueryEngine()
    layers = engine.list_layers()
    print(f"  已注册空间层: {len(layers)} 个")

    # 点位归属批量查询
    test_points = [
        (116.4, 39.9, "北京天安门"),
        (91.1, 29.7, "拉萨布达拉宫"),
        (101.7, 36.6, "西宁"),
        (87.6, 43.8, "乌鲁木齐"),
    ]
    print("\n  点位→省份归属:")
    for lon, lat, name in test_points:
        result = engine.locate(lon, lat)
        prov = result.get("cn_provinces", {}).get("name_zh", "未知")
        print(f"    ({lon}, {lat}) {name:12s} -> {prov}")

    # 多边形重叠分析
    glacier_box = box(86.0, 27.5, 91.0, 29.5)  # 一个覆盖西藏部分区域的矩形
    overlaps = engine.overlap(glacier_box, "cn_provinces")
    print(f"\n  矩形区域 (86-91°E, 27.5-29.5°N) 重叠分析:")
    for o in overlaps:
        print(f"    {o['name_zh']}: 占比 {o['area_fraction']:.2%}")

    # 邻接分析
    neighbors = engine.neighbors("540000", "cn_provinces")
    print(f"\n  与西藏自治区邻接的省份: {len(neighbors)} 个")
    for n in neighbors:
        print(f"    - {n['name_zh']}")


def main():
    # 清理旧的演示项目
    if DEMO_DIR.exists():
        shutil.rmtree(DEMO_DIR)

    print("GeoCorpus-Builder 完整演示")
    print("=" * 60)

    create_mock_spatial_data()
    step_init()
    create_sample_glacier_data()
    step_ingest()
    step_build()
    step_validate()
    step_query()
    step_spatial_demo()
    step_python_api_demo()

    # 清理
    shutil.rmtree(DEMO_DIR)
    # 删除 mock 空间数据 (避免污染真实数据)
    data_dir = Path(__file__).parent.parent / "src" / "geocorpus_builder" / "spatial" / "data"
    for f in data_dir.glob("cn_provinces.*"):
        if f.suffix in (".geoparquet", ".meta.json"):
            f.unlink()
    print(f"\n{'=' * 60}")
    print("  演示完成!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
