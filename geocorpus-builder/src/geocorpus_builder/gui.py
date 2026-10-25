"""GeoCorpus Builder GUI — Streamlit Web Interface."""

from __future__ import annotations

import shutil, sys, tempfile, os
from pathlib import Path

import streamlit as st

_src = Path(__file__).parent.parent
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from geocorpus_builder.spatial import SpatialQueryEngine
from geocorpus_builder.spatial.registry import STANDARD_GRID_LEVELS
from geocorpus_builder.config.project import GeoCorpusProject
from geocorpus_builder.io import read_jsonl
from geocorpus_builder.rag.agent import GeoCorpusAgent

CONTACT_EMAIL = "huyuanming0525@link.cuhk.edu.hk"
ERROR_FOOTER = f"\n\n---\n*如问题持续，请联系 {CONTACT_EMAIL}*"

st.set_page_config(page_title="GeoCorpus Builder", layout="wide")

# ── Helpers ──

def _find_projects(search_dir: Path, max_depth: int = 2) -> list[Path]:
    """Discover GeoCorpus projects under a directory."""
    projects = []
    search_dir = search_dir.resolve()
    # Check self
    if (search_dir / "geocorpus_config.json").exists() or (search_dir / "corpus" / "corpus_units.jsonl").exists():
        projects.append(search_dir)
    # Check children
    if search_dir.is_dir():
        for child in sorted(search_dir.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                if (child / "geocorpus_config.json").exists() or (child / "corpus" / "corpus_units.jsonl").exists():
                    projects.append(child)
                elif max_depth > 1:
                    for grandchild in sorted(child.iterdir()):
                        if grandchild.is_dir() and not grandchild.name.startswith("."):
                            if (grandchild / "geocorpus_config.json").exists() or (grandchild / "corpus" / "corpus_units.jsonl").exists():
                                projects.append(grandchild)
    return projects[:10]


def _load_project(path: Path) -> bool:
    """Load a project path. Returns True if valid."""
    if path.exists():
        st.session_state["project"] = str(path.resolve())
        return True
    return False


# ── Sidebar ──
with st.sidebar:
    st.title("GeoCorpus Builder")
    st.caption("v0.1 · GS(2024)0650")

    st.divider()

    # ── Project discovery ──
    work_dir = Path(st.session_state.get("work_dir", str(Path.cwd())))
    discovered = _find_projects(work_dir)

    if discovered:
        st.subheader("已发现项目")
        current_proj = st.session_state.get("project", "")
        options = [str(p) for p in discovered]
        labels = [f"{p.name}  ({p})" for p in discovered]
        default_idx = 0
        for i, opt in enumerate(options):
            if opt == current_proj:
                default_idx = i
                break

        selected_label = st.selectbox(
            "选择项目", labels, index=default_idx,
            label_visibility="collapsed",
            key="project_selector"
        )
        selected_idx = labels.index(selected_label) if selected_label in labels else 0
        selected_path = options[selected_idx]

        if selected_path != current_proj:
            _load_project(Path(selected_path))
            st.rerun()

    # ── Manual path input ──
    with st.expander("手动输入路径 或 切换工作目录"):
        manual_path = st.text_input("项目路径", value="", placeholder="D:/workroom/Geodata/my_project")
        if manual_path and st.button("加载此路径"):
            if _load_project(Path(manual_path)):
                st.rerun()
        new_work = st.text_input("搜索目录", value=str(work_dir), placeholder="D:/workroom/Geodata")
        if new_work != str(work_dir) and st.button("扫描此目录"):
            st.session_state["work_dir"] = new_work
            st.rerun()

    st.divider()

    # ── Project status ──
    proj_root = Path(st.session_state.get("project", "")) if st.session_state.get("project") else None

    if proj_root:
        corpus_file = proj_root / "corpus" / "corpus_units.jsonl"
        evidence_file = proj_root / "evidence" / "evidence_links.jsonl"
        config_file = proj_root / "geocorpus_config.json"
        is_valid = corpus_file.exists() or config_file.exists()

        if is_valid:
            st.success(f"**{proj_root.name}**")
            st.caption(str(proj_root))

            c1, c2 = st.columns(2)
            if corpus_file.exists():
                units = read_jsonl(corpus_file)
                links = read_jsonl(evidence_file) if evidence_file.exists() else []
                with c1:
                    st.metric("语料", len(units))
                with c2:
                    st.metric("证据", len(links))
            else:
                st.caption("项目就绪，尚未构建")
            if st.button("📁 打开目录", use_container_width=True):
                os.startfile(str(proj_root))
        else:
            st.warning("未识别为有效项目")

    if not discovered and not proj_root:
        st.info("未发现项目。请扫描目录或手动输入路径。")

    st.divider()

    # ── Quick actions ──
    if not proj_root:
        if st.button("创建新项目", use_container_width=True, type="primary", key="sidebar_new_project"):
            st.session_state["nav"] = "项目管理"
    else:
        if st.button("查询语料库", use_container_width=True, key="sidebar_query"):
            st.session_state["nav"] = "查询"
        if st.button("构建语料", use_container_width=True, key="sidebar_build"):
            st.session_state["nav"] = "语料构建"

    st.divider()
    st.caption("Web GUI · 本地运行，数据不出本机")
    st.caption(f"问题反馈: {CONTACT_EMAIL}")



# ── Global error display ──
if "errors" in st.session_state and st.session_state["errors"]:
    for err in st.session_state["errors"][-5:]:
        st.error(err)
    c1, c2 = st.columns([1, 5])
    with c1:
        if st.button("清除", key="clear_errors"):
            st.session_state["errors"] = []

def _show_error(msg):
    if "errors" not in st.session_state:
        st.session_state["errors"] = []
    st.session_state["errors"].append(msg)
    st.session_state["errors"] = st.session_state["errors"][-20:]

# ── Main content ──
nav = st.session_state.get("nav", "空间数据层")
tabs = st.tabs(["空间数据层", "栅格分析", "项目管理", "语料构建", "查询", "协同"])

# Sync nav with clicked tab via a hack: check which tab has content rendered
engine = SpatialQueryEngine()


# ═══════════════════ TAB 1: Spatial ═══════════════════
with tabs[0]:
    st.header("空间数据层")

    tab_s1, tab_s2, tab_s3 = st.tabs(["已安装的层", "导入 SHP 矢量", "导入 TIFF/NC 栅格"])

    with tab_s1:
        layers = engine.list_layers()
        rasters = engine.registry.list_rasters()

        col_v, col_r = st.columns(2)
        with col_v:
            st.subheader(f"矢量层 ({len(layers)})")
            if layers:
                import pandas as pd
                df_v = pd.DataFrame([{
                    "ID": l.layer_id, "名称": l.layer_name, "类型": l.layer_type,
                    "要素": l.feature_count, "字段": ", ".join(l.fields[:3])
                } for l in layers])
                st.dataframe(df_v, use_container_width=True, hide_index=True, height=200)
            else:
                st.info("暂无矢量层")

        with col_r:
            st.subheader(f"栅格层 ({len(rasters)})")
            if rasters:
                import pandas as pd
                df_r = pd.DataFrame([{
                    "ID": r["raster_id"], "名称": r.get("layer_name",""),
                    "格式": r.get("format","?").upper(), "变量": r.get("variable","-"),
                    "网格": r.get("grid_level","?"), "CRS": r.get("target_crs","?")
                } for r in rasters])
                st.dataframe(df_r, use_container_width=True, hide_index=True, height=200)
            else:
                st.info("暂无栅格层")

        # SHP → corpus
        if layers and proj_root:
            st.divider()
            st.subheader("SHP 属性 → 语料")
            st.caption("将矢量层的属性表直接转换为语料单元")
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                layer_for_corpus = st.selectbox("选择矢量层", [l.layer_id for l in layers],
                                                 key="shp2corpus_layer",
                                                 label_visibility="collapsed")
            with c2:
                prefix = st.text_input("ID前缀", "SPATIAL", key="shp2corpus_prefix",
                                        label_visibility="collapsed")
            with c3:
                if st.button("转为语料", key="shp2corpus_btn", use_container_width=True, type="primary"):
                    with st.spinner(f"转换 {layer_for_corpus}..."):
                        try:
                            n_units, n_ev = engine.layer_to_corpus(layer_for_corpus, proj_root, prefix)
                            st.success(f"新增 {n_units} 语料, {n_ev} 证据")
                            st.rerun()
                        except Exception as e:
                            _show_error(str(e)); st.error(f"{e}{ERROR_FOOTER}")

        # Map preview
        st.divider()
        st.subheader("地图预览")
        map_cols = st.columns([3, 1, 1])
        all_layer_ids = [l.layer_id for l in layers]
        with map_cols[0]:
            selected = st.multiselect("选择图层", all_layer_ids,
                                       default=all_layer_ids[:1] if all_layer_ids else [],
                                       label_visibility="collapsed")
        with map_cols[1]:
            if st.button("生成地图", use_container_width=True):
                if not selected:
                    st.warning("请先选择至少一个图层")
                else:
                    try:
                        out = Path(tempfile.mkstemp(suffix=".png")[1])
                        engine.show(selected, out, title=" + ".join(selected), dpi=100)
                        st.image(str(out), use_container_width=True)
                    except Exception as e:
                        _show_error(str(e)); st.error(str(e))
        with map_cols[2]:
            pt_lon = st.number_input("经度", value=91.0, format="%.4f")
            pt_lat = st.number_input("纬度", value=30.0, format="%.4f")
            if st.button("定位", use_container_width=True):
                result = engine.locate(pt_lon, pt_lat)
                st.json(result)

    with tab_s2:
        st.subheader("导入 SHP → GeoParquet")
        uploaded = st.file_uploader("上传 SHP 文件组 (.shp + .shx + .dbf + .prj)",
                                     type=["shp","shx","dbf","prj"], accept_multiple_files=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            layer_id = st.text_input("Layer ID", "cn_custom")
            layer_type = st.selectbox("类型", ["admin_boundary","river_basin","climate_zone","terrain","custom"])
        with c2:
            layer_name = st.text_input("名称", "自定义层")
            name_field = st.text_input("名称字段", "name")
        with c3:
            id_field = st.text_input("ID 字段", "gb")
            if st.button("导入 SHP", type="primary", use_container_width=True) and uploaded:
                if len(uploaded) < 3:
                    st.error("需要同时上传 .shp .shx .dbf .prj")
                else:
                    tmp_dir = Path(tempfile.mkdtemp())
                    for f in uploaded:
                        (tmp_dir / f.name).write_bytes(f.read())
                    shp_files = list(tmp_dir.glob("*.shp"))
                    if shp_files:
                        try:
                            from geocorpus_builder.spatial.importer import import_shapefile
                            import_shapefile(shp_files[0], layer_id, layer_name, layer_type, name_field, id_field)
                            st.success(f"已导入: {layer_id}")
                            st.rerun()
                        except Exception as e:
                            _show_error(str(e)); st.error(f"{e}{ERROR_FOOTER}")
                    shutil.rmtree(tmp_dir, ignore_errors=True)

    with tab_s3:
        st.subheader("导入 TIFF/NC 栅格 → 固定网格体系")
        raster_path_input = st.text_input("文件路径", placeholder="D:/data/dem.tif 或 .nc")

        c1, c2, c3 = st.columns(3)
        with c1:
            raster_id = st.text_input("Raster ID", "dem_30m")
            target_crs = st.text_input("目标 CRS", "EPSG:4326")
        with c2:
            raster_name = st.text_input("名称", "DEM 30m")
            grid_level = st.selectbox("网格级别", ["auto"] + list(STANDARD_GRID_LEVELS.keys()))
        with c3:
            raster_var = st.text_input("变量", "elevation")
            do_reproject = st.checkbox("重投影到目标 CRS")

        if st.button("导入栅格", type="primary") and raster_path_input:
            rp = Path(raster_path_input)
            if rp.exists():
                gl = None if grid_level == "auto" else grid_level
                dest = engine.registry.register_raster(raster_id, rp, {
                    "layer_name": raster_name, "variable": raster_var
                }, grid_level=gl, target_crs=target_crs, reproject=do_reproject)
                full = engine.registry.get_raster_meta(raster_id)
                src = full.get("source_crs","?") if full else "?"
                tgt = full.get("target_crs","?") if full else "?"
                rp_flag = full.get("reprojected",False) if full else False
                st.success(f"已导入: {dest.name} | CRS: {src}{'→' if rp_flag else '≠'}{tgt}")
                st.rerun()
            else:
                st.error("文件不存在")


# ═══════════════════ TAB 2: Geography Analysis ═══════════════════
with tabs[1]:
    st.header("地理分析")

    sub_a1, sub_a2, sub_a3, sub_a4 = st.tabs(
        ["分区统计", "地形分析", "时间序列", "空间自相关"]
    )

    # ── Sub: Zonal stats ──
    with sub_a1:
        st.subheader("栅格分区统计")
        mode = st.radio("模式", ["单文件", "批量目录"], horizontal=True, key="zonal_mode")
        if mode == "单文件":
            c1, c2 = st.columns(2)
            with c1:
                raster_path = st.text_input("栅格文件", placeholder="D:/data/thickness_2024.tif", key="zs_r")
                vector_path = st.text_input("矢量边界", placeholder="D:/data/boundary.shp", key="zs_v")
            with c2:
                zonal_id_field = st.text_input("ID 字段", "region_id", key="zs_id")
                zonal_stats_select = st.multiselect("统计量",
                    ["mean","median","std","min","max","count","sum","p10","p90","cv"],
                    default=["mean","median","std","min","max","count"], key="zs_st")
                zonal_output = st.text_input("输出 CSV", placeholder="D:/data/result.csv", key="zs_o")
            if st.button("运行", type="primary", key="zs_btn") and raster_path and vector_path and zonal_output:
                rp, vp, op = Path(raster_path), Path(vector_path), Path(zonal_output)
                if rp.exists() and vp.exists():
                    with st.spinner("计算中..."):
                        try:
                            result = engine.zonal_stats(rp, vp, op, id_field=zonal_id_field,
                                                         stats_list=zonal_stats_select)
                            st.success(f"已保存: {result}")
                            import pandas as pd
                            st.dataframe(pd.read_csv(result).head(10), use_container_width=True, hide_index=True)
                        except Exception as e:
                            _show_error(str(e)); st.error(f"{e}{ERROR_FOOTER}")
        else:
            c1, c2 = st.columns(2)
            with c1:
                batch_dir = st.text_input("栅格目录", placeholder="D:/data/rasters/", key="bd")
                vector_path2 = st.text_input("矢量边界", placeholder="D:/data/boundary.shp", key="bd_v")
                pattern = st.text_input("文件匹配", "*.tif,*.nc", key="bd_p")
            with c2:
                batch_output = st.text_input("输出目录", placeholder="D:/data/stats/", key="bd_o")
                batch_id = st.text_input("ID 字段", "region_id", key="bd_id")
                if st.button("批量处理", type="primary", key="bd_btn") and batch_dir and vector_path2 and batch_output:
                    bd, vp2, bo = Path(batch_dir), Path(vector_path2), Path(batch_output)
                    if bd.exists() and vp2.exists():
                        with st.spinner("批量计算中..."):
                            try:
                                results = engine.batch_zonal_stats(bd, vp2, bo, id_field=batch_id, pattern=pattern)
                                st.success(f"完成: {len(results)} 个文件")
                            except Exception as e:
                                _show_error(str(e)); st.error(str(e))

    # ── Sub: Terrain analysis ──
    with sub_a2:
        st.subheader("DEM 地形分析")
        st.caption("从 DEM 栅格计算坡度、坡向、起伏度、地形位置指数")
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            dem_path = st.text_input("DEM 文件", placeholder="D:/data/dem.tif", key="ta_dem")
        with c2:
            ta_vector = st.text_input("边界矢量", placeholder="D:/data/boundary.shp", key="ta_vec")
            ta_output = st.text_input("输出 CSV", placeholder="D:/data/terrain_stats.csv", key="ta_out")
        with c3:
            ta_id = st.text_input("ID字段", "region_id", key="ta_id")
            if st.button("地形分析", type="primary", key="ta_btn", use_container_width=True) and dem_path:
                dp, vp, op = Path(dem_path), Path(ta_vector), Path(ta_output)
                if dp.exists() and vp.exists():
                    with st.spinner("计算坡度坡向..."):
                        try:
                            result = engine.terrain_analysis(dp, vp, op, ta_id)
                            st.success(f"已保存: {result}")
                            import pandas as pd
                            st.dataframe(pd.read_csv(result).head(10), use_container_width=True, hide_index=True)
                        except ImportError as e:
                            st.error(f"缺少依赖: {e}")
                        except Exception as e:
                            _show_error(str(e)); st.error(f"{e}{ERROR_FOOTER}")

    # ── Sub: Time series ──
    with sub_a3:
        st.subheader("时间序列分析")
        st.caption("检测多年度数据的趋势和季节性")
        c1, c2 = st.columns([3, 1])
        with c1:
            ts_csv_manual = st.text_input("统计CSV路径", placeholder="D:/data/timeseries.csv", key="ts_csv")
            ts_csv_project = ""
            if proj_root:
                stats_dir = proj_root / "statistics"
                if stats_dir.exists():
                    csv_files = list(stats_dir.glob("*.csv")) + list(stats_dir.glob("*.parquet"))
                    if csv_files:
                        options = ["(手动输入)"] + [str(f) for f in csv_files]
                        ts_sel = st.selectbox("或选择项目内的文件", options, key="ts_sel")
                        if ts_sel != "(手动输入)":
                            ts_csv_project = ts_sel
            ts_csv = ts_csv_project or ts_csv_manual
        with c2:
            ts_id = st.text_input("ID字段", "region_id", key="ts_id")
            ts_val = st.text_input("值字段", "mean", key="ts_val")
            ts_time = st.text_input("时间字段", "year", key="ts_time")
            if st.button("趋势分析", type="primary", key="ts_btn", use_container_width=True) and ts_csv:
                try:
                    results = engine.time_series_analysis(Path(ts_csv), ts_id, ts_val, ts_time)
                    if results:
                        import pandas as pd
                        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
                except Exception as e:
                    _show_error(str(e)); st.error(str(e))

    # ── Sub: Spatial autocorrelation ──
    with sub_a4:
        st.subheader("空间自相关分析")
        st.caption("Moran's I — 衡量地理现象的集聚/离散/随机分布")
        c1, c2 = st.columns([3, 1])
        with c1:
            sa_csv = st.text_input("统计CSV", placeholder="D:/data/regional_stats.csv", key="sa_csv")
            sa_layer = st.selectbox("邻接参照层（定义空间权重）",
                                     [l.layer_id for l in engine.list_layers()], key="sa_layer")
        with c2:
            sa_id = st.text_input("ID字段", "region_id", key="sa_id")
            sa_val = st.text_input("值字段", "mean", key="sa_val")
            if st.button("Moran's I", type="primary", key="sa_btn", use_container_width=True) and sa_csv:
                try:
                    results = engine.spatial_autocorr(Path(sa_csv), sa_id, sa_val, None, sa_layer)
                    for r in results:
                        if "error" in r:
                            st.warning(r["error"])
                        else:
                            i_val = r["moran_i"]
                            p_val = r["p_value"]
                            pattern = r["pattern"]
                            if i_val > 0.1:
                                st.success(f"Moran's I = {i_val} (p≈{p_val}) → **{pattern}分布**")
                                st.caption("正相关：相近区域值相似（符合地理第一定律）")
                            elif i_val < -0.1:
                                st.warning(f"Moran's I = {i_val} (p≈{p_val}) → **{pattern}分布**")
                                st.caption("负相关：相近区域值相反")
                            else:
                                st.info(f"Moran's I = {i_val} (p≈{p_val}) → **{pattern}分布**")
                                st.caption("无显著空间自相关")
                except Exception as e:
                    _show_error(str(e)); st.error(str(e))


# ═══════════════════ TAB 3: Project ═══════════════════
with tabs[2]:
    st.header("项目管理")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("初始化新项目")
        default_workdir = st.session_state.get("work_dir", str(Path.cwd()))
        new_path = st.text_input("项目路径",
                                  str(Path(default_workdir) / "my_project"),
                                  key="newp")
        c_a, c_b = st.columns(2)
        with c_a:
            domain = st.text_input("领域 (domain)", "cryosphere")
        with c_b:
            subdomain = st.text_input("子领域 (subdomain)", "glacier")
        if st.button("创建项目", type="primary", key="create_proj_btn"):
            try:
                p = Path(new_path)
                if p.exists() and list(p.iterdir()):
                    st.warning(f"目录已存在: {p}")
                else:
                    GeoCorpusProject.init(p, domain=domain, subdomain=subdomain)
                    st.success(f"已创建: {p}")
                    st.session_state["project"] = str(p.resolve())
                    st.session_state["work_dir"] = str(p.parent)
                    st.rerun()
            except PermissionError:
                st.error(f"没有写入权限: {new_path}")
            except Exception as e:
                st.error(f"创建失败: {e}")

    with c2:
        st.subheader("导入统计文件")
        if proj_root:
            stats_files = st.file_uploader("上传 CSV/Parquet 统计文件",
                                            type=["csv","parquet"], accept_multiple_files=True)
            if stats_files and st.button("导入到项目", type="primary"):
                dest_dir = proj_root / "statistics"
                dest_dir.mkdir(exist_ok=True)
                for f in stats_files:
                    (dest_dir / f.name).write_bytes(f.read())
                st.success(f"已导入 {len(stats_files)} 个文件到 statistics/")
                st.rerun()

            # Show current stats
            stats_dir = proj_root / "statistics"
            if stats_dir.exists():
                files = list(stats_dir.glob("*"))
                if files:
                    st.subheader(f"已导入的统计文件 ({len(files)})")
                    for f in sorted(files):
                        col_f, col_d = st.columns([4, 1])
                        with col_f:
                            st.write(f"  `{f.name}` ({f.stat().st_size/1024:.0f} KB)")
                        with col_d:
                            if st.button("删", key=f"del_{f.name}"):
                                f.unlink()
                                st.rerun()
        else:
            st.info("请先加载项目")


# ═══════════════════ TAB 4: Build ═══════════════════
with tabs[3]:
    st.header("语料构建")

    if proj_root:
        c1, c2, c3 = st.columns(3)
        with c1:
            id_prefix = st.text_input("ID 前缀", "GC_BUILT",
                                       help="多团队协作时用不同前缀区分")
        with c2:
            spatial_enrich = st.checkbox("空间富化", value=True,
                                          help="自动追加省/市/县归属")
        with c3:
            build_profile = st.selectbox("构建配置", ["auto", "glacier"],
                                          help="auto=自动检测表结构, glacier=冰川专用")

        if st.button("构建语料", type="primary", use_container_width=True, key="build_btn"):
            from geocorpus_builder.builder.engine import BuildOrchestrator
            try:
                project = GeoCorpusProject.discover(proj_root)
                if build_profile != "auto":
                    project.config.build_profile = build_profile
                orch = BuildOrchestrator(project)
                with st.spinner("构建中..."):
                    report = orch.build(spatial_enrich=spatial_enrich, id_prefix=id_prefix)
                # Verify save
                units_file = proj_root / "corpus" / "corpus_units.jsonl"
                evidence_file = proj_root / "evidence" / "evidence_links.jsonl"
                saved_units = len(read_jsonl(units_file)) if units_file.exists() else 0
                saved_evidence = len(read_jsonl(evidence_file)) if evidence_file.exists() else 0
                st.success(f"新增 {report.units_created} 语料、{report.evidence_created} 证据 | "
                           f"共 {saved_units} 语料、{saved_evidence} 证据已保存")
                st.caption(f"文件: {units_file}")
                if report.warnings:
                    with st.expander(f"{len(report.warnings)} 个警告"):
                        for w in report.warnings:
                            st.warning(w)
                # Force sidebar refresh
                st.rerun()
            except Exception as e:
                st.error(f"构建失败: {e}{ERROR_FOOTER}")
    else:
        st.info("请先加载项目")

    # ── Corpus browser (with or without project loaded) ──
    if proj_root:
        st.divider()
        st.subheader("语料浏览")

        corpus_file = proj_root / "corpus" / "corpus_units.jsonl"
        evidence_file = proj_root / "evidence" / "evidence_links.jsonl"

        if not corpus_file.exists():
            st.info("尚未构建语料")
        else:
            all_units = read_jsonl(corpus_file)
            all_evidence = read_jsonl(evidence_file) if evidence_file.exists() else []
            ev_map = {e["evidence_id"]: e for e in all_evidence}

            # Filters
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                filter_type = st.selectbox("类型", ["全部"] + sorted({u.get("text_type","?") for u in all_units}), key="f_type")
            with c2:
                filter_domain = st.selectbox("领域", ["全部"] + sorted({u.get("domain","?") for u in all_units}), key="f_domain")
            with c3:
                filter_var = st.selectbox("变量", ["全部"] + sorted({u.get("variable","?") for u in all_units}), key="f_var")
            with c4:
                search_text = st.text_input("搜索", placeholder="corpus_id / geo_object_id / 关键词", key="f_search")

            filtered = all_units
            if filter_type != "全部":
                filtered = [u for u in filtered if u.get("text_type") == filter_type]
            if filter_domain != "全部":
                filtered = [u for u in filtered if u.get("domain") == filter_domain]
            if filter_var != "全部":
                filtered = [u for u in filtered if u.get("variable") == filter_var]
            if search_text:
                st_lower = search_text.lower()
                filtered = [u for u in filtered if st_lower in u.get("text","").lower()
                           or st_lower in u.get("corpus_id","").lower()
                           or st_lower in u.get("geo_object_id","").lower()]

            st.caption(f"{len(filtered)} / {len(all_units)} 条语料")

            if filtered:
                import pandas as pd
                rows = []
                for u in filtered[:50]:
                    regs = u.get("spatial_regions", {})
                    prov = ""
                    # cn_provinces or cn_sheng are provincial-level layers
                    _prov_layers = {"cn_provinces", "cn_sheng"}
                    for lid, info in regs.items():
                        if lid in _prov_layers or "sheng" in lid:
                            prov = info.get("name", "") or info.get("name_zh", "")
                            if prov:
                                break
                    rows.append({
                        "corpus_id": u["corpus_id"],
                        "类型": u.get("text_type", ""),
                        "对象": u.get("geo_object_id", ""),
                        "变量": u.get("variable", ""),
                        "时间": u.get("time_range", ""),
                        "省份": prov,
                        "证据": len(u.get("evidence_ids", [])),
                        "文本": u.get("text", "")[:60] + ("..." if len(u.get("text",""))>60 else ""),
                    })
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True, height=300)

                # Detail view
                st.subheader("详情")
                selected_cid = st.selectbox("选择语料单元查看证据链", [u["corpus_id"] for u in filtered], key="detail_select")
                selected_unit = next((u for u in filtered if u["corpus_id"] == selected_cid), None)
                if selected_unit:
                    col_a, col_b = st.columns([3, 2])
                    with col_a:
                        st.markdown(f"**{selected_unit['corpus_id']}**")
                        st.write(selected_unit["text"])
                        st.caption(f"类型: {selected_unit.get('text_type','?')} | "
                                   f"领域: {selected_unit.get('domain','?')} | "
                                   f"空间尺度: {selected_unit.get('spatial_scale','?')} | "
                                   f"置信度: {selected_unit.get('confidence','?')}")
                    with col_b:
                        regs = selected_unit.get("spatial_regions", {})
                        if regs:
                            st.caption("空间归属")
                            for lid, info in regs.items():
                                st.write(f"{lid}: {info.get('name','?')} ({info.get('id','?')})")
                        if selected_unit.get("lon") and selected_unit.get("lat"):
                            st.caption(f"坐标: ({selected_unit['lon']}, {selected_unit['lat']})")

                    st.divider()
                    st.subheader("证据链")
                    eids = selected_unit.get("evidence_ids", [])
                    if eids:
                        for eid in eids:
                            ev = ev_map.get(eid)
                            if ev:
                                with st.expander(f"{eid} — {ev.get('variable','?')} {ev.get('statistic','?')} = {ev.get('value','?')} {ev.get('unit','')}"):
                                    st.json(ev)
                            else:
                                st.warning(f"{eid}: 未找到对应证据记录")
                    else:
                        st.caption("（无证据链接 — 定义类或方法类语料）")
            else:
                st.info("无匹配的语料单元")


# ═══════════════════ TAB 5: Query ═══════════════════
with tabs[4]:
    st.header("语料库查询")

    if proj_root:
        c1, c2 = st.columns([3, 1])
        with c1:
            question = st.text_area("输入问题", "A流域的平均高程是多少？", height=80,
                                     label_visibility="collapsed")
        with c2:
            backend = st.selectbox("后端", ["cli", "deepseek", "anthropic"], index=0)
            api_key_input = st.text_input("API Key", type="password",
                                           placeholder="sk-xxx (留空=模板模式)")
            if st.button("查询", type="primary", use_container_width=True):
                actual_key = api_key_input
                if not actual_key and backend == "deepseek":
                    actual_key = os.environ.get("DEEPSEEK_API_KEY")
                elif not actual_key and backend == "anthropic":
                    actual_key = os.environ.get("ANTHROPIC_API_KEY")

                with st.spinner("检索证据中..."):
                    agent = GeoCorpusAgent(
                        corpus_dir=proj_root, language="zh",
                        llm_backend=backend if actual_key else "cli",
                        api_key=actual_key,
                    )
                    result = agent.answer(question)

                st.divider()
                st.markdown(result.answer)
                st.caption(f"类型: {result.question_type} · 置信度: {result.confidence} · 证据: {len(result.evidence_ids)} 条")
                if result.missing_tables:
                    st.warning(f"缺失表: {', '.join(result.missing_tables)}")
    else:
        st.info("请先加载项目")


# ═══════════════════ TAB 6: Collaborate ═══════════════════
with tabs[5]:
    st.header("团队协同")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("导出")
        if proj_root:
            export_name = st.text_input("导出文件名", f"{proj_root.name}.tar.gz")
            export_path = str(proj_root.parent / export_name)
            st.caption(f"将保存到: {export_path}")
            if st.button("导出项目", type="primary", use_container_width=True):
                from geocorpus_builder.collaboration import export_project
                out = export_project(proj_root, Path(export_path))
                st.success(f"已导出 ({out.stat().st_size/1024:.0f} KB)")
        else:
            st.info("请先加载项目")

    with c2:
        st.subheader("合并")
        if proj_root:
            merge_src = st.text_input("源文件", placeholder="D:/shared/team_a.tar.gz 或目录路径")
            merge_strategy = st.selectbox("冲突处理", ["跳过重复", "覆盖", "重命名"],
                                           help="skip=跳过 / overwrite=覆盖 / rename=加后缀")
            strategy_map = {"跳过重复": "skip", "覆盖": "overwrite", "重命名": "rename"}
            if st.button("合并到当前项目", type="primary", use_container_width=True) and merge_src:
                from geocorpus_builder.collaboration import merge_into_project
                stats = merge_into_project(proj_root, Path(merge_src), strategy_map[merge_strategy])
                st.success(f"语料 +{stats.get('corpus_added',0)} · 证据 +{stats.get('evidence_added',0)} · "
                           f"跳过 {stats.get('skipped',0)}")
        else:
            st.info("请先加载项目")
