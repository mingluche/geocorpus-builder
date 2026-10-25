"""Reproduce eight manuscript result figures from existing experiment outputs (manuscript Figs. 2-9).
No experiment results are generated or altered by this script.
Run with the project's geospatial Python environment (see README).
"""
from pathlib import Path
import json, hashlib, argparse, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, MaxNLocator
import geopandas as gpd
import rasterio
from rasterio.windows import from_bounds, Window
from shapely.geometry import Point
from PIL import Image, ImageOps, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[3])
args = parser.parse_args()
ROOT = args.root
REAL = ROOT / 'experiments/2026-10-16/results/real_protocol_main'
CONTROL = ROOT / 'experiments/2026-10-16/results/controlled_20261016T100106326636Z'
BENCH = ROOT / 'experiments/2026-10-16/results/benchmarks_protocol'
VECTOR = ROOT / 'experiments/2026-10-16/data/derived/basinatlas_asia_level6/BasinATLAS_v10_lev06_asia.shp'
RASTER = ROOT / 'experiments/2026-10-16/data/raw/elev/wc2.1_2.5m_elev.tif'
for folder in ['png', 'svg', 'pdf', 'plot_data', 'qa']:
    (OUT/folder).mkdir(exist_ok=True, parents=True)
plt.rcParams.update({
    'font.family': 'Arial', 'font.size': 9, 'axes.titlesize': 10,
    'axes.labelsize': 9, 'xtick.labelsize': 8, 'ytick.labelsize': 8,
    'axes.spines.top': False, 'axes.spines.right': False,
    'axes.linewidth': .7, 'axes.edgecolor': '#777777',
    'text.color': '#24313B', 'axes.labelcolor': '#24313B',
    'xtick.color': '#4A5158', 'ytick.color': '#4A5158',
    'grid.color': '#E2E6E8', 'grid.linewidth': .6,
    'figure.facecolor': 'white', 'axes.facecolor': 'white',
    'savefig.facecolor': 'white', 'svg.fonttype': 'none', 'pdf.fonttype': 42,
})
BLUE, TEAL, ORANGE, RED, GREY = '#326A9E', '#278C82', '#CF8B3B', '#BE5C5C', '#B5BEC5'
DARK = '#24313B'
STAGES = ['real_A_base', 'real_A_reuse', 'real_B_base', 'real_B_reuse',
          'real_C_csv_base', 'real_C_csv_reuse', 'real_C_parquet_base', 'real_C_parquet_reuse']
LABELS = ['A vector | base', 'A vector | reuse', 'B raster | base', 'B raster | reuse',
          'C CSV | base', 'C CSV | reuse', 'C Parquet | base', 'C Parquet | reuse']
summary = json.loads((REAL/'evaluation_summary_v2.json').read_text(encoding='utf-8'))
cases = pd.DataFrame(summary['cases']).set_index('stage').loc[STAGES].reset_index()
samples = pd.read_csv(REAL/'prepared/sample_membership.csv')
allocation = pd.read_csv(REAL/'prepared/stratum_allocation.csv')
controlled = pd.read_csv(CONTROL/'controlled_protocol_comparison.csv')
STATS = ['mean','median','std','min','max','count']
controlled = controlled.loc[controlled.statistic.isin(STATS)].copy()
assert controlled.chapter3_protocol_pass.dtype == bool
assert len(controlled) == 432 and controlled.chapter3_protocol_pass.sum() == 359
bench_all = pd.read_csv(BENCH/'all_measurements.csv')
bench = bench_all.loc[bench_all.repeat.isin([1,2,3])].copy()
assert len(bench_all)==36 and len(bench)==27
assert (bench.exit_code==0).all() and bench.workflow_completed.all()
bench['peak_rss_MiB'] = bench.peak_rss_bytes / 2**20
bench['statistics_stage_share'] = bench.statistics_seconds/(bench.statistics_seconds+bench.build_seconds)
figures = []

def csv(df, name):
    df.to_csv(OUT/'plot_data'/name, index=False, encoding='utf-8-sig')

def title(ax, letter, text):
    ax.set_title(f'({letter})  {text}', loc='left', pad=11, fontweight='bold')

def grid(ax, axis='y'):
    ax.set_axisbelow(True)
    ax.grid(axis=axis, alpha=.85)

def save(fig, stem, name):
    fig.savefig(OUT/'png'/f'{stem}.png', dpi=400, bbox_inches='tight', pad_inches=.10)
    fig.savefig(OUT/'svg'/f'{stem}.svg', bbox_inches='tight', pad_inches=.10)
    fig.savefig(OUT/'pdf'/f'{stem}.pdf', bbox_inches='tight', pad_inches=.10)
    plt.close(fig)
    figures.append({'stem':stem,'title':name})
    print('SAVED', stem, flush=True)

# FIGURE 2: spatial distribution and basin area/elevation.
all_basins = gpd.read_file(VECTOR, columns=['HYBAS_ID','SUB_AREA','ele_mt_sav'])
eligible = all_basins.loc[all_basins.geometry.is_valid].copy()
assert len(all_basins)==2489 and len(eligible)==2351
prepared = gpd.read_file(REAL/'prepared/prepared_vector.gpkg',
                         columns=['region_id','cohort','sample_order','SUB_AREA','ele_mt_sav','stratum'])
assert samples.groupby('cohort').size().to_dict()=={'base':100,'nested_only':800,'reuse':100}
from make_fig02 import render_figure02
render_figure02(eligible, prepared, samples, OUT)
figures.append({'stem': 'Fig02_case_study_sampling', 'title': '流域样本的空间分布与地形特征'})
print('SAVED Fig02_case_study_sampling', flush=True)
csv(eligible.drop(columns='geometry').assign(eligible=True),'Fig02_eligible_population.csv')
csv(samples,'Fig02_sample_membership.csv');csv(allocation,'Fig02_stratum_allocation.csv')

# FIGURE 3: retain every observed output, distinguishing audit states.
valid=cases.valid_emitted_numeric_primary_records.to_numpy()
nonfinite=cases.nonfinite_primary_records.to_numpy()
linked=cases.derived_with_existing_evidence_count.to_numpy()
unlinked=cases.derived_without_evidence_count.to_numpy()
assert np.array_equal(valid+nonfinite,cases.emitted_primary_records)
assert (cases.emitted_primary_records+cases.derived_record_count).sum()==26086
fig,ax=plt.subplots(figsize=(10.0,4.7))
y=np.arange(8); left=np.zeros(8)
parts=[(valid,BLUE,'Finite, verified primary'),(nonfinite,RED,'Non-finite primary'),
       (linked,TEAL,'Derived with evidence links'),(unlinked,ORANGE,'Derived without evidence links')]
for vals,col,label in parts:
    ax.barh(y,vals,left=left,color=col,height=.64,label=label,edgecolor='white',linewidth=.5)
    for yy,ll,v in zip(y,left,vals):
        if v>=180:ax.text(ll+v/2,yy,f'{int(v):,}',ha='center',va='center',fontsize=8.3,color='white')
    left+=vals
for yy,total,nf in zip(y,left,nonfinite):
    ax.text(total+65,yy,f'{int(total):,}',va='center',fontsize=9,fontweight='bold')
    if nf: ax.text(total+470,yy,f'{int(nf)} non-finite',va='center',fontsize=8,color=RED)
ax.set_yticks(y,LABELS);ax.invert_yaxis();ax.set_xlim(0,5200)
ax.set_xticks([0,1000,2000,3000,4000]);ax.xaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v:,.0f}'))
ax.set_xlabel('Emitted records per project'); grid(ax,'x')
ax.legend(ncol=2,frameon=False,loc='lower left',bbox_to_anchor=(0,1.02),fontsize=8.7,columnspacing=1.9)
fig.subplots_adjust(left=.20,right=.99,top=.82,bottom=.18)
fig.text(.20,.035,'Eight projects: 26,086 records = 19,000 primary + 7,086 derived.  Evidence linkage alone does not establish semantic validity.',fontsize=8,color='#5A636B')
save(fig,'Fig03_output_composition','多路径语料产出及记录审计状态')
csv(cases[['stage','emitted_primary_records','valid_emitted_numeric_primary_records','nonfinite_primary_records',
           'derived_record_count','derived_with_existing_evidence_count','derived_without_evidence_count',
           'reference_eligible_unique_facts','unique_valid_retained_reference_facts']],'Fig03_output_composition.csv')

# FIGURE 4: use raster-derived results only, not duplicated reference-input tables.
audit=pd.concat([pd.read_csv(REAL/stage/'primary_audit.csv').assign(cohort=cohort)
                 for stage,cohort in [('real_B_base','base'),('real_B_reuse','reuse')]],ignore_index=True)
finite=np.isfinite(audit.reference_value)&np.isfinite(audit.evidence_value)
cont=audit.loc[finite&audit.statistic.ne('count')].copy()
counts=audit.loc[finite&audit.statistic.eq('count')].copy()
assert len(cont)==4950 and len(counts)==990
assert np.equal(counts.reference_value,counts.evidence_value).all()
cont['absolute_error']=np.abs(cont.evidence_value-cont.reference_value)
cont['tolerance']=5e-5+1e-6*np.abs(cont.reference_value)
cont['tolerance_normalized_error']=cont.absolute_error/cont.tolerance
assert cont.tolerance_normalized_error.max()<=1
variables=['elevation','prec_01','prec_07','tavg_01','tavg_07']
var_titles=['Elevation (m)','January precipitation (mm)','July precipitation (mm)',
            'January temperature (°C)','July temperature (°C)']
fig,axes=plt.subplots(2,3,figsize=(11.6,7.0))
fig.subplots_adjust(left=.075,right=.97,bottom=.13,top=.93,wspace=.37,hspace=.43)
for ax,vv,lab,letter in zip(axes.flat,variables,var_titles,'abcde'):
    data=cont[cont.variable==vv]
    lo=min(data.reference_value.min(),data.evidence_value.min());hi=max(data.reference_value.max(),data.evidence_value.max())
    span=hi-lo;lo-=span*.04;hi+=span*.04
    ax.plot([lo,hi],[lo,hi],color='#4D555A',lw=.8,ls='--',zorder=1)
    for cohort,col in [('base',BLUE),('reuse',ORANGE)]:
        ss=data[data.cohort==cohort]
        ax.scatter(ss.reference_value,ss.evidence_value,s=8,color=col,alpha=.48,edgecolors='none',label=cohort.title(),zorder=2)
    ax.set_xlim(lo,hi);ax.set_ylim(lo,hi)
    ax.set_xlabel('Independent reference');ax.set_ylabel('Software evidence value')
    ax.xaxis.set_major_locator(MaxNLocator(4));ax.yaxis.set_major_locator(MaxNLocator(4))
    grid(ax);title(ax,letter,lab)
    ax.text(.04,.95,f'n = {len(data):,}\nmax |error| = {data.absolute_error.max():.2g}',
            transform=ax.transAxes,va='top',fontsize=8)
axes[0,0].legend(frameon=False,loc='lower right',fontsize=8,markerscale=1.5)
mat=cont.pivot_table(index='variable',columns='statistic',values='tolerance_normalized_error',aggfunc='max').loc[variables,STATS[:-1]]
ax=axes[1,2];im=ax.imshow(mat,cmap='YlGnBu',vmin=0,vmax=1,aspect='auto')
for i in range(5):
    for j in range(5):
        v=mat.iloc[i,j];ax.text(j,i,f'{v:.3f}',ha='center',va='center',color='white' if v>.60 else DARK,fontsize=8.4)
ax.set_xticks(range(5),['Mean','Median','SD','Min','Max'])
ax.set_yticks(range(5),['Elev.','Prec. Jan','Prec. Jul','Temp. Jan','Temp. Jul'])
ax.set_xlabel('Continuous statistic');title(ax,'f','Maximum error / tolerance')
cb=fig.colorbar(im,ax=ax,fraction=.05,pad=.03);cb.set_ticks([0,.5,1]);cb.set_label('Acceptance limit = 1',fontsize=8)
fig.text(.075,.035,(r'4,950 finite continuous statistics met $|e| \leq 5\times10^{-5}+10^{-6}|x_{\mathrm{ref}}|$; 990 non-empty pixel counts matched exactly.' '\n' 'Empty-zone records are evaluated separately in Fig. 5. Only the raster path is shown; CSV/Parquet are not independent statistical replications.'),fontsize=8,color='#5A636B',linespacing=1.5)
save(fig,'Fig04_independent_numeric_agreement','栅格统计与独立参考结果的数值一致性')
csv(cont[['cohort','region_id','variable','statistic','reference_value','evidence_value','absolute_error','tolerance','tolerance_normalized_error']],
    'Fig04_finite_continuous_comparisons.csv')
csv(mat.reset_index(),'Fig04_maximum_normalized_errors.csv')
csv(counts[['cohort','region_id','variable','reference_value','evidence_value']],'Fig04_nonempty_count_comparisons.csv')

# FIGURE 5: two actual empty basins over the real WorldClim pixel grid.
empty_ids=['R_4060018340','R_4060559760']
empty_rows=prepared.set_index('region_id').loc[empty_ids]
fig=plt.figure(figsize=(10.3,7.1))
gs=fig.add_gridspec(2,2,height_ratios=[1.5,.78],hspace=.67,wspace=.28)
axes=[fig.add_subplot(gs[0,0]),fig.add_subplot(gs[0,1])]
points=[]
with rasterio.open(RASTER) as src:
    for ax,rid,letter in zip(axes,empty_ids,'ab'):
        geom=empty_rows.loc[rid].geometry
        minx,miny,maxx,maxy=geom.bounds
        padding=src.res[0]*1.15
        win=from_bounds(minx-padding,miny-padding,maxx+padding,maxy+padding,src.transform)
        c0=int(np.floor(win.col_off));r0=int(np.floor(win.row_off))
        c1=int(np.ceil(win.col_off+win.width));r1=int(np.ceil(win.row_off+win.height))
        win=Window(c0,r0,c1-c0,r1-r0)
        arr=src.read(1,window=win,masked=True)
        mask=np.ma.getmaskarray(arr)
        tf=src.window_transform(win)
        xx=tf.c+np.arange(arr.shape[1]+1)*tf.a
        yy=tf.f+np.arange(arr.shape[0]+1)*tf.e
        ax.pcolormesh(xx,yy,mask.astype(int),cmap=ListedColormap(['#EDF3F6','#D6DADD']),vmin=0,vmax=1,
                      edgecolors='white',linewidth=.8,shading='flat',zorder=0)
        inside=0
        for i in range(arr.shape[0]):
            for j in range(arr.shape[1]):
                x,y=tf*(j+.5,i+.5);is_inside=geom.contains(Point(x,y))
                is_valid=not bool(mask[i,j]);inside+=int(is_inside and is_valid)
                points.append({'region_id':rid,'longitude':x,'latitude':y,'valid_pixel':is_valid,
                               'centre_inside_basin':is_inside,'elevation_m':float(arr.data[i,j]) if is_valid else np.nan})
                ax.scatter(x,y,s=20 if is_valid else 16,marker='o' if is_valid else 'x',
                           c=BLUE if is_valid else '#8E969B',linewidths=.65,zorder=2)
        assert inside==0
        gpd.GeoSeries([geom],crs=prepared.crs).plot(ax=ax,color=ORANGE,alpha=.33,edgecolor='none',zorder=3)
        gpd.GeoSeries([geom],crs=prepared.crs).boundary.plot(ax=ax,color='#A85A08',linewidth=1.8,zorder=4)
        ax.set_xlim(xx[0],xx[-1]);ax.set_ylim(yy[-1],yy[0]);ax.set_aspect(1/np.cos(np.deg2rad((miny+maxy)/2)))
        ax.xaxis.set_major_locator(MaxNLocator(4));ax.yaxis.set_major_locator(MaxNLocator(4))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v:.2f}°E'))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v:.2f}°N'))
        title(ax,letter,f'{rid}  |  {empty_rows.loc[rid,"SUB_AREA"]:.1f} km²')
        ax.text(.03,.96,'Valid centres inside basin: 0',transform=ax.transAxes,va='top',fontsize=8.5,
                bbox=dict(facecolor='white',edgecolor='none',alpha=.88,pad=3))
legend_handles=[Patch(facecolor=ORANGE,edgecolor='#A85A08',alpha=.65,label='Basin boundary'),
                Line2D([],[],marker='o',linestyle='',color=BLUE,label='Valid cell centre',markersize=4),
                Line2D([],[],marker='x',linestyle='',color='#8E969B',label='NoData cell centre',markersize=4)]
fig.legend(handles=legend_handles,loc='center',bbox_to_anchor=(.53,.492),ncol=3,frameon=False,fontsize=8.5)
ax=fig.add_subplot(gs[1,:])
empty_audits=[]
for stage in ['real_B_base','real_C_csv_base','real_C_parquet_base']:
    dd=pd.read_csv(REAL/stage/'primary_audit.csv');dd=dd[dd.region_id.isin(empty_ids)]
    for stat in STATS:
        ss=dd[dd.statistic==stat]
        empty_audits.append({'stage':stage,'statistic':stat,'record_count':len(ss),
                            'finite_records':int(np.isfinite(ss.evidence_value).sum()),
                            'zero_records':int(ss.evidence_value.eq(0).sum()),
                            'nonfinite_records':int((~np.isfinite(ss.evidence_value)).sum())})
em=pd.DataFrame(empty_audits)
emat=em.pivot(index='stage',columns='statistic',values='finite_records').loc[
    ['real_B_base','real_C_csv_base','real_C_parquet_base'],STATS].to_numpy()
ax.imshow(emat,cmap=ListedColormap(['#F7E8E5','#DAEEE9']),vmin=0,vmax=10,aspect='auto')
for i in range(3):
    for j in range(6):
        ax.text(j,i,'count = 0\n10 records' if emat[i,j]==10 else 'NaN\n10 records',ha='center',va='center',
                color=TEAL if emat[i,j]==10 else '#9F4747',fontsize=8.5)
ax.set_xticks(range(6),['Mean','Median','SD','Min','Max','Count'])
ax.set_yticks(range(3),['B raster','C CSV','C Parquet'])
ax.set_xticks(np.arange(-.5,6,1),minor=True);ax.set_yticks(np.arange(-.5,3,1),minor=True)
ax.grid(which='minor',color='white',linewidth=2);ax.tick_params(which='minor',length=0)
title(ax,'c','Observed representation of the 10 empty basin–variable combinations')
fig.subplots_adjust(left=.105,right=.98,bottom=.13,top=.93)
fig.text(.105,.035,'Top: actual elevation-raster grid (2.5 arc-min); all five rasters use the same pixel grid.  Bottom: two basins × five variables.\nContinuous statistics are undefined without valid pixels. The independent tables retain count = 0; the raster path emits NaN for count.',fontsize=8,color='#5A636B',linespacing=1.5)
save(fig,'Fig05_empty_zone_spatial_diagnosis','真实空分区的空间诊断及输出差异')
csv(pd.DataFrame(points),'Fig05_local_pixel_centres.csv');csv(em,'Fig05_empty_zone_outputs.csv')

# FIGURE 6: the complete six-statistic controlled protocol, including failures.
variants=['sentinel_declared_nodata','nan_declared_nodata','sentinel_explicit_override','signed_nan_sentinel',
          'float32_precision','positive_no_nodata','nan_no_nodata','all_zero_no_nodata','signed_zero_no_nodata']
variant_labels=['Sentinel; declared NoData','NaN; declared NoData','Sentinel; explicit override',
                'Signed + NaN + sentinel','Float32 precision','Positive; no NoData',
                'NaN; no NoData','All zero; no NoData','Signed + zero; no NoData']
polygons=['full_aligned','sub_aligned','cross_cell_edges','partial_outside_extent','outside_extent',
          'touch_extent_only','inside_without_cell_center','triangle_partial_cells']
polygon_labels=['Full,\naligned','Subset,\naligned','Cross-cell\nedges','Partly\noutside',
                'Outside\nextent','Extent\ntouch only','Inside; no\ncell centre','Triangle']
cmat=controlled.groupby(['variant','polygon']).chapter3_protocol_pass.sum().unstack().loc[variants,polygons]
assert (controlled.groupby(['variant','polygon']).size()==6).all()
assert (cmat==6).to_numpy().sum()==54
stat_pass=controlled.groupby('statistic').chapter3_protocol_pass.agg(['sum','count']).loc[STATS]
fig=plt.figure(figsize=(11.7,6.1));gs=fig.add_gridspec(1,2,width_ratios=[3.2,1.08],wspace=.31)
a=fig.add_subplot(gs[0,0]);b=fig.add_subplot(gs[0,1])
colors=['#C56E61','#D78D73','#E4AD89','#EDD2AA','#D5E3D1','#9EC9BF','#2C7A7B']
cmap=ListedColormap(colors);norm=BoundaryNorm(np.arange(-.5,7.5),7)
im=a.imshow(cmat,cmap=cmap,norm=norm,aspect='auto')
for i in range(9):
    for j in range(8):
        val=int(cmat.iloc[i,j]);a.text(j,i,f'{val}/6',ha='center',va='center',fontsize=8.8,color='white' if val in [0,6] else DARK)
a.set_xticks(range(8),polygon_labels);a.set_yticks(range(9),variant_labels)
a.set_xticks(np.arange(-.5,8,1),minor=True);a.set_yticks(np.arange(-.5,9,1),minor=True)
a.grid(which='minor',color='white',linewidth=1.1);a.tick_params(which='minor',length=0)
a.axhline(3.5,color='white',lw=3);a.axhline(4.5,color='white',lw=3)
title(a,'a','Passed statistics in each controlled spatial scenario')
cb=fig.colorbar(im,ax=a,orientation='horizontal',fraction=.045,pad=.19,aspect=35)
cb.set_ticks(range(7));cb.set_label('Number of passed statistics out of six',fontsize=8)
y=np.arange(6);passed=stat_pass['sum'].to_numpy();failed=72-passed
b.barh(y,passed,color=TEAL,height=.65,label='Passed')
b.barh(y,failed,left=passed,color=RED,height=.65,label='Failed')
for yy,pp,ff in zip(y,passed,failed):
    b.text(pp/2,yy,f'{pp}/72',ha='center',va='center',color='white',fontsize=8.5)
    if ff:b.text(pp+ff/2,yy,str(ff),ha='center',va='center',color='white',fontsize=8)
b.set_yticks(y,['Mean','Median','SD','Min','Max','Count']);b.invert_yaxis();b.set_xlim(0,72)
b.set_xticks([0,24,48,72]);b.set_xlabel('Controlled comparisons');grid(b,'x')
title(b,'b','By statistic')
b.legend(frameon=False,loc='upper left',bbox_to_anchor=(0,-.12),ncol=2,fontsize=8)
fig.subplots_adjust(left=.235,right=.985,top=.86,bottom=.17)
fig.text(.235,.95,'359 / 432 comparisons passed  ·  54 / 72 spatial scenarios passed all six statistics',fontsize=10,fontweight='bold')
fig.text(.235,.035,'Nine synthetic 10×10 rasters × eight polygons × six statistics.  The four NoData-focused scenarios (top rows) passed 192/192.\nFloat32 precision passed 46/48; these synthetic scenarios do not estimate the frequency of errors in real environmental data.',fontsize=8,color='#5A636B',linespacing=1.5)
save(fig,'Fig06_controlled_test_matrix','受控栅格测试的完整通过情况与统计量差异')
csv(controlled,'Fig06_controlled_six_statistics.csv');csv(cmat.reset_index(),'Fig06_passes_by_scenario.csv')
csv(stat_pass.reset_index(),'Fig06_passes_by_statistic.csv')

# FIGURE 7: evidence linkage, units, and derived-record audit are separate dimensions.
fig=plt.figure(figsize=(11.5,5.4));gs=fig.add_gridspec(1,2,width_ratios=[1.0,1.5],wspace=.50)
a=fig.add_subplot(gs[0,0]);b=fig.add_subplot(gs[0,1])
coverage=np.column_stack([100*cases.source_association_numerator/cases.source_association_denominator,
                          100*cases.physical_unit_present_numerator/cases.physical_unit_expected_denominator])
im=a.imshow(coverage,cmap='Blues',vmin=0,vmax=100,aspect='auto')
for i,row in cases.iterrows():
    pairs=[(row.source_association_numerator,row.source_association_denominator),
           (row.physical_unit_present_numerator,row.physical_unit_expected_denominator)]
    for j,(n,d) in enumerate(pairs):
        a.text(j,i,f'{n:,} / {d:,}\n{100*n/d:.0f}%',ha='center',va='center',fontsize=8.1,
               color='white' if coverage[i,j]>65 else DARK)
a.set_xticks([0,1],['Evidence linkage','Physical unit present']);a.tick_params(axis='x',labelsize=8)
a.set_yticks(range(8),LABELS)
a.set_xticks(np.arange(-.5,2,1),minor=True);a.set_yticks(np.arange(-.5,8,1),minor=True)
a.grid(which='minor',color='white',linewidth=1);a.tick_params(which='minor',length=0)
title(a,'a','Primary-record audit')
cb=fig.colorbar(im,ax=a,orientation='horizontal',fraction=.045,pad=.14,aspect=30)
cb.set_ticks([0,40,100]);cb.set_label('Coverage (%)',fontsize=8)
der=cases[cases.derived_record_count.gt(0)].copy(); y=np.arange(len(der))
finite_derived=der.derived_numeric_verified_pass_count.to_numpy()
nonfinite_comparison=der.derived_with_existing_evidence_count.to_numpy()-finite_derived
missing=der.derived_without_evidence_count.to_numpy()
assert np.array_equal(nonfinite_comparison,[15,0,15,0,15,0])
left=np.zeros(len(der))
for vals,col,label in [(finite_derived,TEAL,'Finite comparison, independently rechecked'),
                       (nonfinite_comparison,RED,'Linked comparison, non-finite'),
                       (missing,ORANGE,'Cross-variable/statistic rule, no evidence link')]:
    b.barh(y,vals,left=left,color=col,height=.64,edgecolor='white',linewidth=.5,label=label)
    for yy,ll,v in zip(y,left,vals):
        if v>30:b.text(ll+v/2,yy,str(v),ha='center',va='center',color='white',fontsize=8.7)
    left+=vals
for yy,tt in zip(y,left):b.text(tt+20,yy,f'{int(tt):,}',va='center',fontsize=8.5)
b.set_yticks(y,[LABELS[STAGES.index(st)] for st in der.stage]);b.invert_yaxis()
b.set_xlim(0,1310);b.set_xticks([0,300,600,900,1200]);b.set_xlabel('Derived records per project');grid(b,'x')
title(b,'b','Derived-record audit')
b.legend(frameon=False,loc='upper left',bbox_to_anchor=(-.02,-.13),fontsize=8,ncol=1,labelspacing=.7)
fig.subplots_adjust(left=.16,right=.98,top=.91,bottom=.28)
fig.text(.16,.045,'Unit denominators exclude pixel-count records.  Each base project has 15 linked but non-finite comparison records.\nThe 686 unlinked derived records per raster/table project are not treated as reliable environmental quantitative statements.',fontsize=8,color='#5A636B',linespacing=1.5)
save(fig,'Fig07_evidence_and_metadata_audit','基础记录元数据与派生记录证据质量审计')
csv(cases[['stage','source_association_numerator','source_association_denominator',
           'physical_unit_present_numerator','physical_unit_expected_denominator']], 'Fig07_primary_audit.csv')
csv(der[['stage','derived_record_count','derived_with_existing_evidence_count','derived_without_evidence_count',
         'derived_numeric_verifiable_count','derived_numeric_verified_pass_count']].assign(
             linked_nonfinite_comparisons=nonfinite_comparison), 'Fig07_derived_audit.csv')


# FIGURE 8: observed scalability; repeat 0 is not a warm-up-controlled experiment.
COLORS = {1: BLUE, 3: TEAL, 5: ORANGE}
MARKERS = {1: 'o', 3: 's', 5: '^'}
metrics = ['statistics_seconds','build_seconds','workflow_seconds',
           'throughput_base_units_per_second','peak_rss_MiB','statistics_stage_share']
bgroup = bench.groupby(['n_objects','n_rasters'], sort=True)
bsum = bgroup[metrics].agg(['min','median','max'])
flat = bsum.copy()
flat.columns = ['_'.join(cc) for cc in flat.columns]
csv(flat.reset_index(), 'Fig08_Fig09_benchmark_summary.csv')
csv(bench, 'Fig08_Fig09_runs_used.csv')
csv(bench_all.loc[bench_all.repeat.eq(0)], 'Fig08_Fig09_excluded_first_runs.csv')

def scale_curve(ax, column, ylabel, letter, heading, limits=None):
    for nr in [1,3,5]:
        sub = bsum.xs(nr, level='n_rasters').sort_index()
        xx = sub.index.to_numpy(dtype=float)
        med = sub[(column,'median')].to_numpy()
        low = sub[(column,'min')].to_numpy()
        high = sub[(column,'max')].to_numpy()
        col = COLORS[nr]
        ax.fill_between(xx,low,high,color=col,alpha=.12,linewidth=0)
        ax.errorbar(xx, med, yerr=[med-low,high-med], color=col, marker=MARKERS[nr],
                    markersize=5, lw=1.6, capsize=3, elinewidth=.8,
                    label=f'{nr} raster' + ('s' if nr>1 else ''))
    ax.set_xticks([100,500,1000]); ax.set_xlim(50,1050)
    ax.set_xlabel('Number of basin objects');ax.set_ylabel(ylabel)
    if limits is not None: ax.set_ylim(*limits)
    title(ax,letter,heading);grid(ax)

fig,axes=plt.subplots(1,2,figsize=(10.9,4.5))
scale_curve(axes[0],'workflow_seconds','Workflow time (s)','a','End-to-end runtime',(0,10.8))
scale_curve(axes[1],'throughput_base_units_per_second','Primary output records / s','b','Observed output rate',(0,4100))
axes[0].legend(frameon=False,loc='upper left',fontsize=8.5)
maxrow = bsum.loc[(1000,5)]
axes[0].annotate(f'{maxrow[("workflow_seconds","median")]:.3f} s',
                 xy=(1000,maxrow[('workflow_seconds','median')]),xytext=(-48,12),
                 textcoords='offset points',fontsize=8.5,color=ORANGE,fontweight='bold')
axes[1].annotate(f'{maxrow[("throughput_base_units_per_second","median")]:,.1f} / s',
                 xy=(1000,maxrow[('throughput_base_units_per_second','median')]),xytext=(-66,11),
                 textcoords='offset points',fontsize=8.5,color=ORANGE,fontweight='bold')
fig.subplots_adjust(left=.075,right=.985,top=.90,bottom=.25,wspace=.31)
fig.text(.075,.045,'Markers: median of subsequent runs 1–3; whiskers and shading: observed minimum–maximum. First run (repeat 0) excluded; cache uncontrolled.\nOutput rate counts emitted primary records, including records not accepted by the quality audit; it is not a rate of verified environmental facts.',
         fontsize=8,color='#5A636B',linespacing=1.5)
save(fig,'Fig08_runtime_scaling','对象数与栅格数增加时的运行时间和基础记录输出速率')

# FIGURE 9: per-run stage composition and absolute peak resident memory.
fig=plt.figure(figsize=(10.9,5.0));gs=fig.add_gridspec(1,2,width_ratios=[1.1,1.05],wspace=.34)
a=fig.add_subplot(gs[0,0]);b=fig.add_subplot(gs[0,1])
order=[(n,r) for n in [100,500,1000] for r in [1,3,5]]
shares=np.array([bsum.loc[kk,('statistics_stage_share','median')] for kk in order])*100
y=np.arange(9)
a.barh(y,shares,color=BLUE,height=.66,label='Zonal statistics')
a.barh(y,100-shares,left=shares,color=TEAL,height=.66,label='Corpus build + write')
for yy,v in zip(y,shares):
    a.text(v/2,yy,f'{v:.1f}%',va='center',ha='center',fontsize=8.3,color='white')
    a.text(v+(100-v)/2,yy,f'{100-v:.1f}',va='center',ha='center',fontsize=7.4,color='white')
a.set_yticks(y,[f'{n:,} objects | {r} raster'+('s' if r>1 else '') for n,r in order])
a.invert_yaxis();a.set_xlim(0,100);a.set_xticks([0,25,50,75,100])
a.set_xlabel('Median per-run share of measured stage sum (%)')
a.legend(frameon=False,ncol=1,loc='upper left',bbox_to_anchor=(0,-.12),fontsize=8.5)
title(a,'a','Measured stage-time composition')
scale_curve(b,'peak_rss_MiB','Peak resident memory (MiB)','b','Absolute process peak RSS',(145,275))
b.legend(frameon=False,loc='upper left',fontsize=8.5)
b.annotate(f'{maxrow[("peak_rss_MiB","median")]:.1f} MiB',xy=(1000,maxrow[('peak_rss_MiB','median')]),
           xytext=(-64,12),textcoords='offset points',fontsize=8.5,color=ORANGE,fontweight='bold')
fig.subplots_adjust(left=.17,right=.985,top=.91,bottom=.26)
fig.text(.17,.045,'Stage proportions are calculated within each run, then summarized across runs 1–3; their denominator is statistics + build time.\nRSS is the absolute process peak, sampled every 50 ms. Curves show medians and observed min–max, not confidence intervals.',
         fontsize=8,color='#5A636B',linespacing=1.5)
save(fig,'Fig09_stage_cost_and_memory','阶段耗时构成与进程峰值内存')
stage_data=bench[['n_objects','n_rasters','repeat','statistics_seconds','build_seconds','statistics_stage_share']].copy()
stage_data['build_stage_share']=1-stage_data.statistics_stage_share
csv(stage_data,'Fig09_per_run_stage_composition.csv')

# Numeric QA and input provenance. These checks concern the existing files, not new experiments.
validation = {
    'experiment_results_modified': False,
    'new_experiments_run': False,
    'source_basins': len(all_basins), 'eligible_basins': len(eligible),
    'invalid_geometries_excluded': len(all_basins)-len(eligible),
    'base_sample_n': int(samples.cohort.eq('base').sum()),
    'reuse_sample_n': int(samples.cohort.eq('reuse').sum()),
    'output_records': int((cases.emitted_primary_records+cases.derived_record_count).sum()),
    'primary_records': int(cases.emitted_primary_records.sum()),
    'derived_records': int(cases.derived_record_count.sum()),
    'nonfinite_primary_records': int(cases.nonfinite_primary_records.sum()),
    'independent_raster_finite_continuous_comparisons': len(cont),
    'max_continuous_absolute_error': float(cont.absolute_error.max()),
    'max_continuous_tolerance_normalized_error': float(cont.tolerance_normalized_error.max()),
    'nonempty_pixel_counts_exact_matches': len(counts),
    'controlled_comparisons': len(controlled),
    'controlled_passed': int(controlled.chapter3_protocol_pass.sum()),
    'controlled_failed': int((~controlled.chapter3_protocol_pass).sum()),
    'controlled_scenarios_all_six_passed': int((cmat==6).to_numpy().sum()),
    'benchmark_runs_total': len(bench_all), 'benchmark_runs_in_figures': len(bench),
    'max_scale_workflow_seconds_median': float(maxrow[('workflow_seconds','median')]),
    'max_scale_peak_rss_MiB_median': float(maxrow[('peak_rss_MiB','median')]),
    'max_scale_primary_records_per_second_median': float(maxrow[('throughput_base_units_per_second','median')]),
    'benchmark_range_interpretation': 'Observed min/max of runs 1-3; not a confidence interval. Cache uncontrolled.',
    'stage_proportion_denominator': 'statistics_seconds + build_seconds, calculated per run before taking median',
    'figure_count': len(figures),
}
assert len(figures)==8
assert validation['primary_records']==19000 and validation['derived_records']==7086
assert validation['nonfinite_primary_records']==160
(OUT/'qa'/'numeric_validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
provenance=[]
source_files=[REAL/'evaluation_summary_v2.json',REAL/'prepared/sample_membership.csv',REAL/'prepared/stratum_allocation.csv',
              CONTROL/'controlled_protocol_comparison.csv',BENCH/'all_measurements.csv']
for st in STAGES:
    source_files.append(REAL/st/'primary_audit.csv')
    if (REAL/st/'derived_audit.csv').exists():source_files.append(REAL/st/'derived_audit.csv')
for p in source_files:
    provenance.append({'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,
                       'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
for p in [VECTOR,RASTER,REAL/'prepared/prepared_vector.gpkg']:
    provenance.append({'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,
                       'note':'Large spatial input; file size recorded, data not redistributed in the figure package.'})
(OUT/'qa'/'input_provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'qa'/'figure_index.json').write_text(json.dumps(figures,ensure_ascii=False,indent=2),encoding='utf-8')

# Contact sheet: separate from high-resolution publication panels.
thumb_w,thumb_h=850,590
sheet=Image.new('RGB',(thumb_w*2,thumb_h*4),'#EDF0F2')
font_path=Path('C:/Windows/Fonts/arial.ttf')
font=ImageFont.truetype(str(font_path),20) if font_path.exists() else ImageFont.load_default()
draw=ImageDraw.Draw(sheet)
for i,entry in enumerate(figures):
    im=Image.open(OUT/'png'/f'{entry["stem"]}.png').convert('RGB')
    thumb=ImageOps.contain(im,(thumb_w-30,thumb_h-60),Image.Resampling.LANCZOS)
    x=(i%2)*thumb_w; y=(i//2)*thumb_h
    draw.rounded_rectangle((x+7,y+7,x+thumb_w-7,y+thumb_h-7),radius=8,fill='white')
    draw.text((x+20,y+16),entry['stem'],fill=DARK,font=font)
    sheet.paste(thumb,(x+(thumb_w-thumb.width)//2,y+51+(thumb_h-65-thumb.height)//2))
sheet.save(OUT/'qa'/'figure_overview.png')
export=[]
for entry in figures:
    p=OUT/'png'/f'{entry["stem"]}.png'
    with Image.open(p) as im:
        export.append(dict(entry,png_width=im.width,png_height=im.height,dpi=im.info.get('dpi')))
(OUT/'qa'/'export_dimensions.json').write_text(json.dumps(export,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(validation,ensure_ascii=False,indent=2),flush=True)
