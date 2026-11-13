import {jobs,datasets} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {chart} from '../components/common/chart.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {esc,fmt,date,notify} from '../utils/dom.js';

function aggregatePanel(bt){
 const a=bt.aggregate;
 return '<section class="panel"><div class="section-title"><h2>'+esc(bt.title)+'</h2><span>误差分子分母跨周加总</span></div>'
 +'<div class="metrics compact-metrics">'
 +[['滚动折数',a.folds,'折'],['对账天数',a.days,'天'],['HW 滚动MAE',a.mae,'份/天'],['HW 滚动WAPE',a.wape,'%'],['上周同日WAPE',a.naive_wape,'%'],['绝对误差合计',a.abs_error_sum,'份'],['实领合计',a.actual_sum,'份'],['带符号差合计',a.bias_sum,'份']]
  .map(([k,v,u])=>'<div><span>'+esc(k)+'</span><strong>'+esc(fmt(v))+'<small>'+esc(u)+'</small></strong></div>').join('')
 +'</div><p class="hint pool-rule">口径：'+esc(a.rule)+' 各周WAPE不参与算术平均。</p>'
 + table(bt.columns,bt.rows)
 +'</section>';
}

function foldList(bt){
 return '<section class="panel"><div class="section-title"><h2>每周训练截止日与逐日对账</h2><span>点击周次展开7天明细</span></div><div class="fold-list">'
 +bt.folds.map(f=>'<div class="fold-card"><button type="button" class="fold-head" data-fold-toggle="'+f.fold+'">'
   +'<span class="fold-no">第'+f.fold+'折</span>'
   +'<span>训练截止 <strong>'+esc(f.train_cutoff)+'</strong>（'+f.train_days+'天）</span>'
   +'<span>预测窗 '+esc(f.window_start)+' → '+esc(f.window_end)+'</span>'
   +'<span>HW周MAE '+esc(fmt(f.mae))+' / 基线 '+esc(fmt(f.naive_mae))+'</span>'
   +'<small class="fold-cue">展开逐日对账 ↓</small></button>'
   +'<div class="fold-daily" id="fold-daily-'+f.fold+'" hidden>'+table(bt.daily_columns,f.days)+'</div></div>').join('')
 +'</div></section>';
}

function snapshotPanel(j,datasetName){
 const s=j.result?.snapshot;
 if(!s)return '';
 return '<section class="method-sheet compact snapshot-sheet"><p class="eyebrow">INPUT SNAPSHOT / 不可变记录</p>'
 +'<div class="snapshot-grid">'
 +[['绑定数据批次',datasetName||('#'+j.dataset_id)],['记录条数',s.record_count+' 条'],['记录起',s.date_start],['记录止',s.date_end],['α / 天数 / 缓冲',s.alpha+' / '+s.horizon+' / '+s.safety_pct+'%'],['记录指纹 SHA256',s.checksum]]
  .map(([k,v])=>'<div><span>'+esc(k)+'</span><strong>'+esc(v)+'</strong></div>').join('')
 +'</div><p class="hint">'+esc(s.note)+'</p></section>';
}

// 与后端同一口径：plan=ceil(forecast*(1+p/100)-1e-9)，仅作用于页面建议量。
function planWithBuffer(forecast,pct){
 return Math.ceil(forecast*(1+pct/100)-1e-9);
}

function planPanel(j){
 const r=j.result, rows=r.table.rows, initial=Number(j.params.safety_pct??0);
 const body=rows.map((row,i)=>'<tr data-row="'+i+'" data-forecast="'+row.forecast+'">'
   +'<td>'+esc(row.date)+'</td><td>'+esc(row.weekday)+'</td><td class="cell-forecast">'+esc(fmt(row.forecast))+'</td>'
   +'<td class="cell-buffer"></td><td class="cell-plan"></td></tr>').join('');
 return '<section class="panel"><div class="section-title"><h2>未来备餐建议（同一批数据）</h2><span>基础预测与回测不随缓冲变化</span></div>'
 +'<div class="buffer-sim"><label>计划安全缓冲(%)<input type="number" id="buffer-sim" min="0" max="20" step="0.5" value="'+esc(initial)+'"></label>'
 +'<div class="buffer-totals"><span>基础预测合计 <strong id="forecast-total"></strong> 份</span><span>缓冲合计 <strong id="buffer-total"></strong> 份</span><span>建议备餐合计 <strong id="plan-total"></strong> 份</span></div></div>'
 +'<div class="table-wrap"><table><thead><tr>'+r.table.columns.map(c=>'<th>'+esc(c.label)+'</th>').join('')+'</tr></thead><tbody id="plan-body">'+body+'</tbody></table></div>'
 +'<p class="hint">调缓冲只在本页重算“额外缓冲/建议备餐”，回测指标、基础预测与已归档结果均不变；需要留痕时请用新参数另建试验。</p></section>';
}

export async function results(id){
 workspace.jobs=await jobs.list();const j=id?await jobs.get(id):(workspace.jobs.find(j=>j.id===workspace.selectedJob)||workspace.jobs[0]);
 if(j&&!workspace.jobs.some(x=>x.id===j.id))workspace.jobs.push(j);
 if(!j)return heading('04 / REVIEW','结果复核','尚无分析结果。')+'<div class="empty">先到分析工作台，选择批次并提交一次计算。<a href="#/workbench">前往工作台 ↗</a></div>';
 workspace.selectedJob=j.id;const r=j.result||{};
 const bt=r.backtest;
 let lineage='';
 try{
  const allDatasets=workspace.datasets.length?workspace.datasets:await datasets.list();
  workspace.datasets=allDatasets;
  const byId=Object.fromEntries(allDatasets.map(d=>[d.id,d]));
  const current=byId[j.dataset_id];
  const chain=[];
  let cursor=current?.supersedes_id,guard=0;
  while(cursor&&byId[cursor]&&guard<20){chain.push(byId[cursor].name);cursor=byId[cursor].supersedes_id;guard++;}
  lineage=current?('<p class="hint lineage-line">批次溯源：'+esc(current.name)+(chain.length?' · 替代自 '+esc(chain.join(' → ')):' · 首批数据')+'；旧批次与其试验结果均未改写。</p>'):'';
 }catch{ lineage=''; }
 return heading('04 / REVIEW','结果复核与业务解释',j.name,'<button class="button" id="refresh-results">刷新结果 ↻</button>')
 +'<div class="result-selector"><label>分析记录<select id="select-job">'+workspace.jobs.map(x=>'<option value="'+x.id+'" '+(x.id===j.id?'selected':'')+'>'+esc(x.name)+' · '+esc(x.status)+'</option>').join('')+'</select></label>'+status(j.status)+'<span>'+date(j.created_at)+'</span><span class="approval">'+(j.approved?'已获业务批准':'待负责人复核')+'</span></div>'
 +(j.status==='completed'
   ?'<section class="result-lead"><p class="eyebrow">COMPUTED FINDING</p><h2>'+esc(r.summary)+'</h2><div class="metrics">'+(r.metrics||[]).map(m=>'<div><span>'+esc(m.label)+'</span><strong>'+esc(fmt(m.value))+'<small>'+esc(m.unit||'')+'</small></strong></div>').join('')+'</div></section>'
   +(bt?aggregatePanel(bt):'')
   +(bt?foldList(bt):'')
   +'<section class="panel">'+chart(r.chart)+'</section>'
   +planPanel(j)
   +'<div class="two-columns"><section class="panel"><div class="section-title"><h2>业务解释</h2><span>由计算结果生成</span></div><ol class="questions">'+(r.findings||[]).map(v=>'<li>'+esc(v)+'</li>').join('')+'</ol>'+(r.warnings||[]).map(v=>'<p class="warning">'+esc(v)+'</p>').join('')+'</section>'
   +'<div>'+snapshotPanel(j,(workspace.datasets.find(d=>d.id===j.dataset_id)||{}).name)+lineage+'<section class="method-sheet compact"><p class="eyebrow">REPRODUCIBILITY</p><h3>计算口径与参数</h3><p>'+esc(r.method)+'</p><pre>'+esc(JSON.stringify(j.params,null,2))+'</pre>'+(session.user.role==='admin'&&!j.approved?'<button class="primary" id="approve-job">批准此业务结论</button>':'')+'<p class="hint">仅批准结果可进入定时分发档案。</p></section></div></div>'
   :'<section class="panel empty">'+(j.status==='failed'?'计算失败：'+esc(j.error)+'。请返回工作台调整参数或数据。':'后台正在执行计算。点击刷新结果查看最新进展。')+'<a href="#/workbench">返回工作台 ↗</a></section>');
}

function bindBufferSim(){
 const input=document.querySelector('#buffer-sim');
 const body=document.querySelector('#plan-body');
 if(!input||!body)return;
 const apply=()=>{
  let pct=Number(input.value);
  if(!Number.isFinite(pct))pct=0;
  pct=Math.min(20,Math.max(0,pct));
  let forecastTotal=0,bufferTotal=0,planTotal=0;
  body.querySelectorAll('tr[data-row]').forEach(tr=>{
   const forecast=Number(tr.dataset.forecast);
   const plan=planWithBuffer(forecast,pct);
   const buffer=Math.round((plan-forecast)*10)/10;
   tr.querySelector('.cell-buffer').textContent=fmt(buffer);
   tr.querySelector('.cell-plan').textContent=fmt(plan);
   forecastTotal+=forecast;bufferTotal+=buffer;planTotal+=plan;
  });
  document.querySelector('#forecast-total').textContent=fmt(Math.round(forecastTotal*10)/10);
  document.querySelector('#buffer-total').textContent=fmt(Math.round(bufferTotal*10)/10);
  document.querySelector('#plan-total').textContent=fmt(planTotal);
 };
 input.addEventListener('input',apply);apply();
}

export function bindResults(refresh){
 document.querySelector('#refresh-results')?.addEventListener('click',refresh);
 document.querySelector('#select-job')?.addEventListener('change',e=>{workspace.selectedJob=Number(e.target.value);location.hash='#/results/'+e.target.value;});
 document.querySelectorAll('[data-fold-toggle]').forEach(btn=>btn.addEventListener('click',()=>{
  const box=document.querySelector('#fold-daily-'+btn.dataset.foldToggle);
  if(!box)return;
  box.hidden=!box.hidden;
  btn.querySelector('.fold-cue').textContent=box.hidden?'展开逐日对账 ↓':'收起逐日对账 ↑';
 }));
 bindBufferSim();
 document.querySelector('#approve-job')?.addEventListener('click',async()=>{try{await jobs.approve(workspace.selectedJob);notify('已批准，可创建分发计划');await refresh();}catch(e){notify(e.message,true);}});
}
