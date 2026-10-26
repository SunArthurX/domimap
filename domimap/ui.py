"""ui — 本地工作台：工作流画布 + 只读运行入口（F2：无模型可用；仅回环监听）。

Dify/Coze 式工作台：枚举当前支持的全部工作流（工作台可直接运行 7 条 + 终端命令 6 条），
选中即在画布呈现节点链，可直接执行（同一 Searcher+seeds 语义，AC-F2-01 三入口同源同序）。
写盘/长任务/需密钥的工作流不入 UI 进程，展示精确命令供终端执行。

安全契约（R08）：stdlib http.server、无第三方依赖；拒绝非回环绑定；所有请求校验回环
Host，写操作另校验 Origin/Referer；页面只用 textContent/DOM API 渲染（资料不执行脚本），
HTML 响应带 CSP（default-src 'none'，仅内联脚本/样式 + 同源 connect）。
"""
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


# 工作台页面：__STATS_JSON__ 在服务时注入（图名/规模/库状态）。渲染一律 DOM API。
PAGE_TEMPLATE = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>domimap 工作台</title>
<style>
:root{--bg:#f3f4f6;--card:#ffffff;--line:#e4e7ec;--ink:#101828;--sub:#5d6b7e;
--acc:#1f5fd6;--acc-ink:#123c8c;--ok:#147a51;--warn:#8a5a00;--err:#b3261e;--chip:#eef1f6;
--hover:#f7f8fa;--line2:#d5dae2}
*{box-sizing:border-box}
body{margin:0;font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
"Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif;
color:var(--ink);background:var(--bg);-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
header{position:sticky;top:0;z-index:20;display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;
padding:12px 24px;background:var(--card);border-bottom:1px solid var(--line)}
@media (prefers-color-scheme:dark){header{background:rgba(23,28,34,.92);backdrop-filter:blur(6px)}}
@media (prefers-color-scheme:light){header{background:rgba(255,255,255,.92);backdrop-filter:blur(6px)}}
header h1{font-size:17px;margin:0;font-weight:650;letter-spacing:.01em}
header .stats{color:var(--sub);font-size:12.5px;display:flex;flex-wrap:wrap;gap:10px}
.stats b{font-weight:600;color:var(--ink)}
.stats span{padding:2px 9px;background:var(--chip);border-radius:5px}
.stats i{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:5px;vertical-align:1px}
.stats .on{background:var(--ok)}.stats .off{background:#b9c2cc}
main{display:flex;align-items:stretch;min-height:calc(100vh - 54px)}
aside{width:248px;flex:none;background:var(--card);border-right:1px solid var(--line);
padding:8px 0;overflow-y:auto}
aside .grp{font-size:11.5px;color:var(--sub);padding:10px 16px 4px;letter-spacing:.04em}
aside .filter{margin:8px 12px 2px}
aside .filter input{width:100%;font:inherit;font-size:12.5px;padding:5px 9px;border:1px solid var(--line2);
border-radius:6px;background:var(--card);color:var(--ink)}
aside .filter input:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px rgba(31,95,214,.13)}
aside button.hidden,#catalog .grp.hidden{display:none}
aside button{display:flex;width:100%;text-align:left;border:0;background:none;cursor:pointer;
padding:8px 16px 8px 14px;font:inherit;color:var(--ink);align-items:center;gap:10px}
aside .zi{flex:none;width:26px;height:26px;border-radius:6px;display:flex;align-items:center;justify-content:center;
font-size:13px;font-weight:650;background:var(--chip);color:var(--sub);border:1px solid var(--line)}
aside button.on .zi,aside button:hover .zi{background:var(--acc);border-color:var(--acc);color:#fff}
aside .txt{min-width:0;flex:1}
aside button.recent .nm::after{content:"";display:inline-block;width:5px;height:5px;
border-radius:50%;background:var(--acc);margin-left:6px;vertical-align:2px}
aside button:hover{background:var(--hover)}
aside button:hover .ps{color:var(--ink)}
aside button.on{background:var(--chip);box-shadow:inset 3px 0 0 var(--acc)}
aside .nm{font-weight:550;display:block}
aside .ps{color:var(--sub);font-size:12px;display:block;margin-top:1px}
.sec{flex:1;display:flex;flex-direction:column;min-width:0;position:relative}
#canvasWrap{flex:none;padding:20px 24px 8px;overflow:auto;
mask-image:linear-gradient(to right,#000 calc(100% - 26px),transparent 100%);-webkit-mask-image:linear-gradient(to right,#000 calc(100% - 26px),transparent 100%)}
#canvasTitle{font-size:15px;font-weight:650;margin:0 0 3px;letter-spacing:.005em}
#canvasSub{color:var(--sub);font-size:12.5px;margin:0 0 12px}
#canvasOuter{position:relative}
.zoombar{position:absolute;right:16px;top:20px;display:flex;gap:6px;z-index:6;align-items:center}
.zoombar button{height:26px;padding:0 8px;border:1px solid var(--line);background:var(--card);
border-radius:6px;cursor:pointer;font:12px/1 inherit;color:var(--sub);box-shadow:0 1px 2px rgba(16,24,40,.08)}
.zoombar button:hover{border-color:var(--acc);color:var(--acc)}
#canvasWrap{position:relative}
#canvasWrap.collapsed{height:58px;overflow:hidden}
#canvasOuter{min-width:100%}
#canvas{position:relative;border-radius:8px;
background-image:radial-gradient(circle,rgba(16,24,40,.075) 1px,transparent 1px);
background-size:16px 16px}
#canvas svg{position:absolute;left:0;top:0;pointer-events:none}
.node{position:absolute;width:140px;min-height:60px;background:var(--card);
border:1px solid var(--line);border-left:3px solid var(--sub);border-radius:7px;
padding:8px 10px;box-shadow:0 1px 2px rgba(16,24,40,.05);transition:box-shadow .15s,border-color .15s}
.node .t{font-weight:600;font-size:12.5px}
.node .s{color:var(--sub);font-size:11px;margin-top:3px;line-height:1.35}
.node .k{display:inline-block;font-size:9.5px;color:var(--sub);letter-spacing:.06em;
border:1px solid var(--line);border-radius:3px;padding:0 4px;margin-bottom:4px;background:var(--hover)}
.node:hover{box-shadow:0 4px 12px -4px rgba(16,24,40,.18);transform:translateY(-1px)}
.node{transition:box-shadow .15s,border-color .15s,transform .15s}
.n-input{border-left-color:#7c5cbf}.n-proc{border-left-color:#3b6ea5}
.n-data{border-left-color:#0f7d8c}.n-gate{border-left-color:var(--warn)}
.n-out{border-left-color:var(--ok)}.n-term{border-left-color:#37424f}
.node.run{box-shadow:0 0 0 3px rgba(31,95,214,.16);border-color:var(--acc)}
svg path.eflow{stroke:var(--acc);stroke-dasharray:7 5;animation:dmflow .45s linear infinite}
@keyframes dmflow{to{stroke-dashoffset:-12}}
.node.run{animation:dmbreath 1.1s ease-in-out infinite}
@keyframes dmbreath{50%{box-shadow:0 0 0 6px rgba(31,95,214,.10)}}
.node.done{animation:dmdone .3s ease-out}
@keyframes dmdone{0%{transform:scale(1)}45%{transform:scale(1.03)}100%{transform:scale(1)}}
@media (prefers-reduced-motion:reduce){.node.run,.node.done{animation:none}}
@media (prefers-reduced-motion:reduce){
svg path.eflow{animation:none}
.node{transition:none}
}
.node.done{border-color:var(--ok)}
.node.fail{border-color:var(--err)}
#panel{margin:0 24px 24px;background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:20px;min-height:220px;box-shadow:0 1px 2px rgba(16,24,40,.04),0 4px 16px -8px rgba(16,24,40,.06)}
#panel h3{margin:0 0 12px;font-size:13.5px;font-weight:650;color:var(--sub);letter-spacing:.02em}
.frow{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;align-items:flex-start}
.frow label{font-size:12.5px;color:var(--sub);flex:none;width:72px;padding-top:7px}
.frow input[type=text],.frow textarea{flex:1;min-width:220px;font:inherit;padding:7px 10px;
border:1px solid var(--line2);border-radius:6px;background:var(--card);transition:border-color .12s,box-shadow .12s}
.frow input:focus,.frow textarea:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px rgba(31,95,214,.13)}
:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.frow input:focus-visible,.frow textarea:focus-visible{outline:none}
#catalog button:focus-visible{outline:2px solid var(--acc);outline-offset:-2px;border-radius:6px}
.frow textarea{min-height:64px;resize:vertical}
.btn{font:inherit;padding:6px 18px;border-radius:6px;border:1px solid var(--acc);
background:var(--acc);color:#fff;cursor:pointer;font-weight:550;letter-spacing:.02em;
transition:background .12s,box-shadow .12s,transform .06s}
.btn:hover:not(:disabled){background:var(--acc-ink,#1a4faf);box-shadow:0 2px 8px -2px rgba(31,95,214,.5)}
.btn:active:not(:disabled){transform:translateY(1px)}
.btn.sub{background:var(--card);color:var(--acc)}
.btn.sub:hover:not(:disabled){box-shadow:none;border-color:var(--acc);background:var(--hover)}
.btn:disabled{opacity:.55;cursor:default}
.btn.busy{position:relative;padding-left:32px}
.btn.busy::before{content:"";position:absolute;left:12px;top:50%;width:11px;height:11px;margin-top:-5.5px;border-radius:50%;border:2px solid rgba(255,255,255,.35);border-top-color:#fff;animation:dmspin .7s linear infinite}
@keyframes dmspin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.btn.busy::before{animation:none}}
.cmd{display:flex;gap:10px;align-items:center;background:#0f1626;color:#d7e0ef;
border-radius:6px;padding:10px 14px;font:13px/1.5 ui-monospace,Menlo,Consolas,monospace;
overflow-x:auto;white-space:pre;font-weight:450}
.note{color:var(--sub);font-size:12.5px;margin:8px 0}
.args{font-size:12px;color:var(--sub);background:var(--hover);
border:1px solid var(--line);border-radius:6px;padding:6px 10px;margin:8px 0}
.badge{display:inline-block;font-size:11.5px;padding:1px 8px;border-radius:3px;margin-left:8px}
.b-run{background:#e4efe8;color:var(--ok)}
.b-cli{background:var(--chip);color:var(--sub)}
#out{margin-top:14px;border-top:1px dashed var(--line);padding-top:12px}
.copybar{display:flex;justify-content:flex-end;align-items:center;gap:8px;margin:-4px 0 2px}
.ms{font-size:11.5px;color:var(--sub);background:var(--chip);border-radius:4px;padding:1px 7px}
.hist{display:flex;flex-wrap:wrap;gap:6px;margin:2px 0 8px}
.hist button{font:12px/1 inherit;padding:4px 10px;border-radius:12px;border:1px solid var(--line);
background:var(--card);color:var(--sub);cursor:pointer;max-width:260px;overflow:hidden;
white-space:nowrap;text-overflow:ellipsis}
.hist button:hover{border-color:var(--acc);color:var(--acc)}
.mini{font:12px/1 inherit;padding:4px 10px;border-radius:5px;border:1px solid var(--line2);
background:var(--card);color:var(--sub);cursor:pointer}
.mini:hover{border-color:var(--acc);color:var(--acc)}
#out .h{font-weight:600;margin:8px 0 6px}
#out .ref{color:var(--warn);background:#fdf6e7;border:1px solid #efe0bb;border-radius:6px;
padding:9px 12px;margin-bottom:8px;border-left:3px solid var(--warn)}
.seed{display:flex;gap:10px;align-items:baseline;padding:8px 12px;border:1px solid var(--line);
border-radius:6px;margin-bottom:6px;cursor:pointer;transition:background .12s,border-color .12s;
animation:seedin .18s ease-out backwards}
@keyframes seedin{from{opacity:0;transform:translateY(4px)}}
@media (prefers-reduced-motion:reduce){.seed{animation:none}}
.seed:hover{background:var(--hover);border-color:#c9d2e0}
.seed .kd{flex:none;font-size:11px;border-radius:4px;padding:1px 6px;min-width:50px;text-align:center;font-weight:550}
.kd-Method{background:#e8effb;color:#1d4fae}.kd-Table{background:#fdeedc;color:#935610}
.kd-Doc{background:#e9f5ee;color:#177a4a}.kd-Knowledge{background:#f1ecfb;color:#5f3bb3}
.kd-Service{background:#e6f2f5;color:#12617a}.kd-Route{background:#f5eee6;color:#8a5a2f}
.kd-Topic{background:#f4e9f0;color:#84356b}.kd-SqlStmt{background:#fdeaea;color:#a33227}
.kd-Class{background:#eef0f3;color:#44505f}.kd-Column{background:#eef0f3;color:#44505f}
.kd-Domain{background:#eef0f3;color:#44505f}
.kd-src{background:var(--chip);color:var(--sub)}
@media (prefers-color-scheme:dark){
.kd-Method{background:#182640;color:#8fb3f2}.kd-Table{background:#33270f;color:#e5b878}
.kd-Doc{background:#122e1f;color:#77d3a5}.kd-Knowledge{background:#241d3d;color:#c0a8f5}
.kd-Service{background:#0f2733;color:#7cc3dd}.kd-Route{background:#33230f;color:#dfae76}
.kd-Topic{background:#331528;color:#e39ed0}.kd-SqlStmt{background:#3a1611;color:#f2968b}
.kd-Class,.kd-Column,.kd-Domain{background:#232a33;color:#aeb9c5}
}
.seed .nm{font-weight:550;word-break:break-all}
.seed .fl{color:var(--sub);font-size:12px}
.seed .fl.path{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.seed .idx{flex:none;font-size:10.5px;color:var(--sub);border:1px solid var(--line);border-radius:3px;
width:16px;height:16px;line-height:15px;text-align:center;margin-left:2px}
.evc{cursor:copy;flex:none;white-space:nowrap;font-family:ui-monospace,Menlo,monospace;font-size:11px}
.dom-tag{flex:none;font-size:11px;color:var(--acc);background:rgba(31,95,214,.07);
border-radius:4px;padding:1px 6px;margin-left:2px;white-space:nowrap}
.evc:hover{color:var(--acc)}
.seed .fl.path:hover{white-space:normal;word-break:break-all}
.md .h1{font-size:15.5px;font-weight:700;margin:12px 0 6px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.md .h2{font-size:13.5px;font-weight:650;margin:12px 0 5px;color:var(--ink)}
.md .q{color:var(--sub);border-left:3px solid var(--line2);padding:2px 0 2px 10px;margin:5px 0;background:var(--hover);border-radius:0 5px 5px 0}
.md .li{padding-left:22px;text-indent:-22px;margin:3px 0;word-break:break-all;line-height:1.55}
.md .li::before{content:"·";color:var(--acc);margin-right:7px;font-weight:700}
.md .p{margin:4px 0;word-break:break-all;line-height:1.6}
.md .sp{height:6px}
.evmeta{display:grid;grid-template-columns:96px 1fr;gap:3px 10px;font-size:12.5px;margin-bottom:8px}
.evmeta .k{color:var(--sub)}
pre.blob{margin:0;padding:12px;background:#f7f8fa;border:1px solid var(--line);border-radius:6px;
white-space:pre-wrap;word-break:break-all;font:12.5px/1.55 ui-monospace,Menlo,Consolas,monospace;
max-height:180px;overflow-y:hidden;transition:max-height .25s}
pre.blob.exp{max-height:420px;overflow-y:auto}
.domgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:10px}
.dom{border:1px solid var(--line);border-radius:7px;padding:12px 14px;background:var(--hover);margin:0}
.dom .nm{font-weight:600}
.dom .row{font-size:12.5px;color:var(--sub);margin-top:2px;word-break:break-all}
.warnrow{color:var(--warn)}
.dep{font:12.5px/1.7 ui-monospace,Menlo,Consolas,monospace;word-break:break-all;
padding:2px 8px;margin:1px 0;border-radius:5px}
.dep:hover{background:var(--hover)}
.dep .src{color:var(--acc);font-weight:600}
.dep .rel{color:var(--warn)}
.dep .dst{color:var(--ink);font-weight:550}
.err{color:var(--err)}
.empty{color:var(--sub);border:1px dashed var(--line2);border-radius:8px;padding:18px 16px;
text-align:center;margin:6px 0;background:var(--hover)}
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-thumb{background:#c4ccd6;border-radius:5px;border:2px solid transparent;background-clip:content-box}
::-webkit-scrollbar-thumb:hover{background:#aab4c0;border:2px solid transparent;background-clip:content-box}
::-webkit-scrollbar-track{background:transparent}
*{scrollbar-width:thin;scrollbar-color:#c4ccd6 transparent}
@media (prefers-color-scheme:dark){
::-webkit-scrollbar-thumb{background:#39434f;border:2px solid transparent;background-clip:content-box}
*{scrollbar-color:#39434f transparent}
}
@media (max-width:980px){
main{flex-direction:column}
aside{width:auto;max-height:34vh;border-right:0;border-bottom:1px solid var(--line)}
aside .ps{display:none}
aside button{padding:7px 12px}
.frow label{width:60px}
}
@media (max-width:640px){
.frow input[type=text],.frow textarea{min-width:0}
.domgrid{grid-template-columns:1fr}
}
@media (prefers-color-scheme:dark){
:root{--bg:#101418;--card:#171c22;--line:#262d36;--ink:#e6eaf0;--sub:#9aa5b1;
--acc:#6b9aff;--acc-ink:#a8c4ff;--ok:#4cc38a;--warn:#e0b341;--err:#ff7a70;--chip:#20262e;
--hover:#1d232b;--line2:#333c47}
.node{box-shadow:0 1px 2px rgba(0,0,0,.35)}
#panel{box-shadow:0 1px 2px rgba(0,0,0,.3),0 4px 16px -8px rgba(0,0,0,.4)}
.seed:hover{background:var(--hover);border-color:#3a4552}
.cmd{background:#0b0f14;color:#c7d3e3}
pre.blob{background:#12171d;border-color:var(--line)}
.dom{background:var(--hover)}
}
/* ---------- 查询反馈条（retrieval-feedback） ---------- */
.fbbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px;
  padding:8px 10px;border:1px dashed var(--line);border-radius:8px}
.fbbar input{flex:1 1 180px;min-width:0}
.fbb{border:1px solid var(--line);background:var(--card);color:var(--ink);
  border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px}
.fbb:hover{border-color:var(--accent)}
.fbok{font-size:12px;color:var(--mut)}
</style>
</head>
<body>
<header>
<h1>domimap 工作台</h1>
<div class="stats" id="stats"></div>
</header>
<main>
<aside id="catalog" role="navigation" aria-label="工作流目录"></aside>
<div class="sec">
<div id="canvasWrap">
<p id="canvasTitle"></p>
<p id="canvasSub"></p>
<div id="canvasOuter"><div id="canvas" role="img" aria-label="工作流节点链图"></div></div>
</div>
<div id="panel" role="region" aria-label="运行面板"></div>
</div>
</main>
<footer id="cheat"></footer>
<script>
"use strict";
const STATS = __STATS_JSON__;

/* ---------- 基础 DOM 工具（禁用超文本注入，一律 textContent） ---------- */
function el(tag, cls, text){
  const n = document.createElement(tag);
  if(cls) n.className = cls;
  if(text !== undefined && text !== null) n.textContent = text;
  return n;
}

/* ---------- 工作流定义：与 CLI 能力一一对应 ---------- */
const KIND_LABEL = {input:"输入", proc:"处理", data:"数据", gate:"判定", out:"输出", term:"终端"};
const WORKFLOWS = [
{id:"search", zi:"检", name:"检索问答", mode:"run", purpose:"问题/符号 → 候选与证据（含拒答）",
 nodes:[{id:"i",t:"输入",s:"问题 / 符号名 / 表名",k:"input",c:0,r:0},
        {id:"bm",t:"词法召回",s:"BM25 种子检索",k:"proc",c:1,r:0},
        {id:"rk",t:"排序合并",s:"领域过滤（可选）",k:"proc",c:2,r:0},
        {id:"gt",t:"覆盖率判定",s:"低于阈值 → 拒答",k:"gate",c:3,r:0},
        {id:"o",t:"候选清单",s:"Top-6，同 CLI 排序",k:"out",c:4,r:0},
        {id:"ev",t:"证据阅读",s:"点候选读固化片段",k:"data",c:5,r:0}],
 edges:[["i","bm"],["bm","rk"],["rk","gt"],["gt","o"],["o","ev"]],
 fields:[{n:"q",l:"查询",ph:"如：订单改价 防并发 / t_order / PriceService",req:1},
         {n:"domain",l:"领域",ph:"可选；点开有领域建议",req:0}],
 act:"search"},

{id:"req", zi:"需", name:"需求定位卡", mode:"run", purpose:"需求文本 → 领域/服务/表/文档定位卡",
 nodes:[{id:"i",t:"输入",s:"需求描述文本",k:"input",c:0,r:0},
        {id:"cls",t:"领域分类",s:"种子词表命中",k:"proc",c:1,r:0},
        {id:"ext",t:"词表扩展",s:"命中域英文种子",k:"proc",c:2,r:0},
        {id:"sr",t:"分桶检索",s:"服务/接口/表/MQ/SQL/文档",k:"proc",c:3,r:0},
        {id:"path",t:"改动路径",s:"图上 2 跳建议",k:"proc",c:4,r:0},
        {id:"o",t:"定位卡",s:"分桶清单 + 下一步",k:"out",c:5,r:0}],
 edges:[["i","cls"],["cls","ext"],["ext","sr"],["sr","path"],["path","o"]],
 fields:[{n:"text",l:"需求",ph:"如：下单后自动拆单发货的流程要加冷却窗口",req:1,ta:1}],
 act:"scenario-req"},

{id:"trb", zi:"排", name:"问题排查卡", mode:"run", purpose:"症状 → 图+文档双路召回 → 疑点排序",
 nodes:[{id:"i",t:"输入",s:"故障症状描述",k:"input",c:0,r:0},
        {id:"g1",t:"图路召回",s:"结构命中（表/SQL/方法）",k:"proc",c:1,r:0},
        {id:"d1",t:"文档路召回",s:"文档/工单全文",k:"proc",c:1,r:1},
        {id:"sn",t:"摘句",s:"命中行原文",k:"data",c:2,r:1},
        {id:"gt",t:"疑点排序",s:"表>SQL>主题>方法>服务",k:"gate",c:3,r:0},
        {id:"o",t:"排障卡",s:"疑点 + 建议动作",k:"out",c:4,r:0}],
 edges:[["i","g1"],["i","d1"],["d1","sn"],["g1","gt"],["sn","gt"],["gt","o"]],
 fields:[{n:"text",l:"症状",ph:"如：改价后偶发库存超卖，日志有乐观锁冲突",req:1,ta:1}],
 act:"scenario-trb"},

{id:"impact", zi:"影", name:"影响面分析", mode:"run", purpose:"符号/表 → 反向依赖清单（谁会受影响）",
 nodes:[{id:"i",t:"输入",s:"符号名（子串匹配）",k:"input",c:0,r:0},
        {id:"st",t:"起点匹配",s:"图内符号定位",k:"proc",c:1,r:0},
        {id:"rv",t:"反向遍历",s:"谁依赖我（2 跳）",k:"proc",c:2,r:0},
        {id:"o",t:"依赖清单",s:"调用/读写/订阅关系",k:"out",c:3,r:0}],
 edges:[["i","st"],["st","rv"],["rv","o"]],
 fields:[{n:"symbol",l:"符号",ph:"如：t_order / PriceService",req:1}],
 act:"impact"},

{id:"domain", zi:"域", name:"领域地图", mode:"run", purpose:"领域 × 服务/表/主题/文档 + 跨域共享表",
 nodes:[{id:"g",t:"知识图",s:"当前已加载",k:"data",c:0,r:0},
        {id:"agg",t:"领域聚合",s:"域 → 资产清单",k:"proc",c:1,r:0},
        {id:"sh",t:"共享表检测",s:"多域共表 → 高风险",k:"gate",c:2,r:0},
        {id:"o",t:"领域地图",s:"聚合视图",k:"out",c:3,r:0}],
 edges:[["g","agg"],["agg","sh"],["sh","o"]],
 fields:[],
 act:"domain"},

{id:"read", zi:"证", name:"证据阅读", mode:"run", purpose:"证据 ID / 图节点 → 固化片段（点检索候选直接读）",
 nodes:[{id:"i",t:"输入",s:"ev:xxxx 或来源 ID",k:"input",c:0,r:0},
        {id:"q",t:"证据库查询",s:"store.db",k:"proc",c:1,r:0},
        {id:"v",t:"blob 校验",s:"sha256 定位原文",k:"gate",c:2,r:0},
        {id:"o",t:"固化片段",s:"源删除后仍为旧版本",k:"out",c:3,r:0}],
 edges:[["i","q"],["q","v"],["v","o"]],
 fields:[{n:"id",l:"证据/节点",ph:"ev:1a2b3c… / tbl:t_order / doc:mini:…",req:1}],
 act:"read"},

{id:"note", zi:"记", name:"笔记沉淀", mode:"run", purpose:"结论写入 knowledge.db（幂等，可检索）",
 nodes:[{id:"i",t:"输入",s:"笔记正文",k:"input",c:0,r:0},
        {id:"chk",t:"校验",s:"claims 类型检查",k:"gate",c:1,r:0},
        {id:"idm",t:"幂等",s:"同键同文不重复",k:"proc",c:2,r:0},
        {id:"db",t:"knowledge.db",s:"版本化保存",k:"data",c:3,r:0},
        {id:"o",t:"回执",s:"note_id / revision",k:"out",c:4,r:0}],
 edges:[["i","chk"],["chk","idm"],["idm","db"],["db","o"]],
 fields:[{n:"body",l:"正文",ph:"结论要可追溯：现象、依据（证据/文件）、决定",req:1,ta:1}],
 act:"note"},

{id:"fbhist", zi:"馈", name:"反馈与历史", mode:"run", purpose:"查询记录 + 反馈统计（H/(H+P+M)，unknown 不算 miss）",
 nodes:[{id:"db",t:"queries.db",s:"查询记录库",k:"data",c:0,r:0},
        {id:"eff",t:"有效相关性",s:"权威来源最新修订；矛盾=disputed",k:"gate",c:1,r:0},
        {id:"st",t:"分组统计",s:"命中率/覆盖率/来源分列",k:"proc",c:2,r:0},
        {id:"o",t:"历史列表",s:"状态/原因/反馈一览",k:"out",c:3,r:0}],
 edges:[["db","eff"],["eff","st"],["st","o"]],
 fields:[],
 act:"fbhist"},

{id:"build", zi:"建", name:"工作区建图", mode:"cli", purpose:"扫描工作区子仓 → 合并图 + 证据库",
 nodes:[{id:"ws",t:"工作区根",s:"多子仓目录",k:"input",c:0,r:0},
        {id:"disc",t:"子仓发现",s:"pom/gradle/git/package",k:"proc",c:1,r:0},
        {id:"scan",t:"扫描解析",s:"Java/SQL/文档摄入",k:"proc",c:2,r:0},
        {id:"merge",t:"合并图",s:"graph.json",k:"data",c:3,r:0},
        {id:"store",t:"证据库",s:"store.db 固化片段",k:"data",c:4,r:0},
        {id:"mf",t:"增量清单",s:"manifest（更新用）",k:"out",c:5,r:0}],
 edges:[["ws","disc"],["disc","scan"],["scan","merge"],["merge","store"],["store","mf"]],
 args:"--merge 单仓直出　--jobs N 并行度　产物：graph.json / store.db / manifest",
 cmd:g=>"domimap build <工作区目录> --discover -o "+dirOf(g)},

{id:"update", zi:"更", name:"增量更新", mode:"cli", purpose:"manifest 校验 → 只重建变更仓",
 nodes:[{id:"mf",t:"manifest",s:"指纹比对",k:"input",c:0,r:0},
        {id:"noop",t:"无变更",s:"毫秒级 no-op",k:"gate",c:1,r:1},
        {id:"rb",t:"变更仓重建",s:"仅重建变更仓",k:"proc",c:1,r:0},
        {id:"o",t:"合并图",s:"graph.json",k:"data",c:2,r:0}],
 edges:[["mf","rb"],["rb","o"],["mf","noop"]],
 args:"manifest 未变时毫秒级 no-op；只重建变更仓",
 cmd:g=>"domimap update -o "+dirOf(g)},

{id:"embed", zi:"嵌", name:"嵌入索引", mode:"cli", purpose:"docs/sql 全文本地嵌入 → 查询语义融合",
 nodes:[{id:"g",t:"知识图",s:"文档/SQL 节点",k:"data",c:0,r:0},
        {id:"seg",t:"分段",s:"长文档切块",k:"proc",c:1,r:0},
        {id:"emb",t:"本地嵌入",s:"bge-small-zh（离线）",k:"proc",c:2,r:0},
        {id:"o",t:"emb 索引",s:"图旁 .emb.json",k:"out",c:3,r:0}],
 edges:[["g","seg"],["seg","emb"],["emb","o"]],
 args:"--targets docs|sql|all　--limit N 试跑；本地 bge-small-zh 离线嵌入",
 cmd:g=>"domimap embed -g "+g},

{id:"enrich", zi:"草", name:"LLM 草稿笔记", mode:"cli", purpose:"可选：材料 → 模型 → 草稿（conf=LLM）",
 nodes:[{id:"g",t:"图内材料",s:"Doc/领域描述",k:"data",c:0,r:0},
        {id:"cap",t:"裁剪",s:"单篇字符上限",k:"proc",c:1,r:0},
        {id:"llm",t:"模型调用",s:"需 GLM_API_KEY；未配置退出码 6",k:"term",c:2,r:0},
        {id:"db",t:"knowledge.db",s:"草稿笔记 conf=LLM",k:"data",c:3,r:0},
        {id:"o",t:"审计",s:"enrichment.jsonl",k:"out",c:4,r:0}],
 edges:[["g","cap"],["cap","llm"],["llm","db"],["db","o"]],
 args:"--force 重生成　--budget-tokens N 预算　--dry-run 只统计不联网；未配置密钥退出码 6",
 cmd:g=>"domimap enrich -g "+g+" --dry-run"},

{id:"review", zi:"审", name:"人审队列导出", mode:"cli", purpose:"AMBIGUOUS 边 → Obsidian 待审页",
 nodes:[{id:"g",t:"知识图",s:"全部边",k:"data",c:0,r:0},
        {id:"f",t:"过滤",s:"conf=AMBIGUOUS",k:"gate",c:1,r:0},
        {id:"o",t:"待审页",s:"Markdown 勾选清单",k:"out",c:2,r:0}],
 edges:[["g","f"],["f","o"]],
 args:"导出 Markdown 勾选清单，人审结论写回 reviewed/ 双通道",
 cmd:g=>"domimap review -g "+g+" -o out/review"},

{id:"serve", zi:"M", name:"MCP 客户端接入", mode:"cli", purpose:"stdio 服务器：7 个只读 kg_* 工具含 kg_context（--enable-write 加 kg_feedback）",
 nodes:[{id:"cli",t:"客户端",s:"Claude Code / Codex / ZCode",k:"input",c:0,r:0},
        {id:"sv",t:"MCP 服务",s:"domimap serve（stdio）",k:"term",c:1,r:0},
        {id:"tools",t:"6 工具",s:"explore/domain_map/impact/doc_search/read/troubleshoot",k:"proc",c:2,r:0},
        {id:"o",t:"同一语义",s:"与 CLI/UI 同源同序",k:"out",c:3,r:0}],
 edges:[["cli","sv"],["sv","tools"],["tools","o"]],
 args:"stdio MCP 服务器：kg_explore/domain_map/impact/doc_search/read/troubleshoot",
 cmd:g=>"domimap serve -g "+g}
];

function dirOf(g){const i=g.lastIndexOf("/");return i>0?g.slice(0,i):"out/idx";}

/* ---------- 页眉统计（初始注入；笔记保存后经 /api/stats 刷新） ---------- */
function drawStats(s){
  const box = document.getElementById("stats");
  box.textContent = "";
  const main = el("span",null,(s.name||"-")+"  ·  "+s.nodes+" 节点 / "+s.edges+" 边");
  main.style.fontWeight = "550"; main.style.color = "var(--ink)";
  box.appendChild(main);
  const dot = (on,label)=>{
    const sp = el("span",null,null);
    const i = el("i",on?"on":"off"); sp.appendChild(i);
    sp.appendChild(document.createTextNode(label));
    return sp;
  };
  box.appendChild(dot(s.store,"证据库"));
  if(s.notes!==null) box.appendChild(dot(true,"笔记 "+s.notes));
  box.appendChild(dot(s.embed,"嵌入"));
}
drawStats(STATS);
async function refreshStats(){
  const {data} = await fetchJSON("/api/stats");
  if(data && data.nodes!==undefined) drawStats(data);
}

/* ---------- 目录 ---------- */
(function(){
  const cat = document.getElementById("catalog");
  const fbox = el("div","filter");
  const finp = el("input"); finp.type="text"; finp.placeholder="过滤工作流…（名称/用途）";
  finp.addEventListener("input",()=>{
    const q=finp.value.trim().toLowerCase();
    for(const b of document.querySelectorAll("#catalog button")){
      b.classList.toggle("hidden", !( !q || b.textContent.toLowerCase().includes(q) ));
    }
    // 分组标题：该组内无可见项时一并隐藏（filter 框在组标题之前，需跳过）
    for(const g of document.querySelectorAll("#catalog .grp")){
      let n=g.nextElementSibling, any=false;
      while(n && !n.classList.contains("grp")){
        if(n.tagName==="BUTTON" && !n.classList.contains("hidden")){ any=true; break; }
        n=n.nextElementSibling;
      }
      g.classList.toggle("hidden", !any);
    }
  });
  fbox.appendChild(finp);
  cat.appendChild(fbox);
  const groups = [["run","工作台直接运行"],["cli","终端命令（写盘/需密钥）"]];
  for(const [mode,label] of groups){
    cat.appendChild(el("div","grp",label));
    for(const wf of WORKFLOWS){
      if(wf.mode!==mode) continue;
      const b = el("button",null,null);
      b.setAttribute("aria-label","工作流："+wf.name+"。"+wf.purpose);
      b.title=wf.name;
      const zi = el("span","zi",wf.zi||wf.name.slice(0,1));
      b.appendChild(zi);
      const txt = el("span","txt");
      txt.appendChild(el("span","nm",wf.name));
      txt.appendChild(el("span","ps",wf.purpose));
      b.appendChild(txt);
      b.onclick = ()=>select(wf);
      b.dataset.wfid = wf.id;
      cat.appendChild(b);
    }
  }
})();

/* ---------- 画布 ---------- */
const NW=140, NH=60, GX=176, GY=96, PAD=16;
let CUR=null, RUNTIMER=[], CURDIVS={}, CUREDGE={};

function markRecent(){
  const btns=[...document.querySelectorAll("#catalog button")];
  for(const b of btns) b.classList.remove("recent");
  for(const id of recentIds()){
    const b=btns.find(x=>x.dataset.wfid===id);
    if(b){ b.classList.add("recent"); b.title=b.title+"（最近使用）"; }
  }
}
function recentIds(){
  try{ return JSON.parse(localStorage.getItem("dm-wb-recent")||"[]").slice(0,3); }catch(e){ return []; }
}
function select(wf){
  CUR = wf;
  try{
    const prev=recentIds().filter(x=>x!==wf.id);
    localStorage.setItem("dm-wb-recent", JSON.stringify([wf.id,...prev].slice(0,3)));
  }catch(e){}
  markRecent();
  if(history.replaceState) history.replaceState(null,"","#"+wf.id);
  document.title = "domimap · "+wf.name;
  for(const b of document.querySelectorAll("#catalog button"))
    b.classList.toggle("on", b.dataset.wfid===wf.id);
  const title = document.getElementById("canvasTitle");
  title.textContent = "";
  title.appendChild(document.createTextNode(wf.name));
  const bd = el("span","badge "+(wf.mode==="run"?"b-run":"b-cli"),
                wf.mode==="run"?"工作台运行":"终端命令");
  title.appendChild(bd);
  document.getElementById("canvasSub").textContent = wf.purpose;
  const cbtn=document.getElementById("canvasToggle");
  if(!cbtn){
    const b=el("button","mini","收起画布");
    b.id="canvasToggle";
    b.onclick=()=>{
      const w=document.getElementById("canvasWrap");
      const collapsed=w.classList.toggle("collapsed");
      b.textContent=collapsed?"展开画布":"收起画布";
    };
    document.querySelector(".sec").appendChild(b);
  }
  renderCanvas(wf);
  renderPanel(wf);
  const fi=document.querySelector("#panel input,#panel textarea");
  if(fi) fi.focus();              // 切换即聚焦，直接可输入
}
function nodeById(wf,id){return wf.nodes.find(n=>n.id===id);}
let ZOOM=1, CW=0, CH=0, HIST=[];
function applyZoom(){
  const cv=document.getElementById("canvas");
  cv.style.transformOrigin="0 0";
  cv.style.transform="scale("+ZOOM+")";
  const outer=document.getElementById("canvasOuter");
  if(outer && CW){ outer.style.width=(CW*ZOOM)+"px"; outer.style.height=(CH*ZOOM)+"px"; }
  const zs=document.getElementById("zoomLabel"); if(zs) zs.textContent=Math.round(ZOOM*100)+"%";
}
function zoombarHtml(){
  const bar=el("div","zoombar");
  const ct=document.getElementById("canvasToggle");   // 收起画布并入同一工具行
  if(ct) bar.appendChild(ct);
  const mk=(t,fn)=>{const b=el("button",null,t); b.onclick=fn; return b;};
  bar.appendChild(mk("−",()=>{ZOOM=Math.max(.5,+(ZOOM-.1).toFixed(2)); applyZoom();}));
  const lb=el("button",null,"100%"); lb.id="zoomLabel"; lb.style.minWidth="46px";
  lb.onclick=()=>{ZOOM=1; applyZoom();};
  bar.appendChild(lb);
  bar.appendChild(mk("+",()=>{ZOOM=Math.min(1.6,+(ZOOM+.1).toFixed(2)); applyZoom();}));
  return bar;
}
function renderCanvas(wf){
  RUNTIMER.forEach(clearTimeout); RUNTIMER=[]; CURDIVS={}; CUREDGE={};
  const cv = document.getElementById("canvas");
  cv.textContent = "";
  const wrap=document.getElementById("canvasWrap");
  if(!document.querySelector(".zoombar")) wrap.parentElement.appendChild(zoombarHtml());
  let maxC=0, maxR=0;
  for(const n of wf.nodes){maxC=Math.max(maxC,n.c);maxR=Math.max(maxR,n.r);}
  const W = PAD*2+(maxC)*GX+NW, H = PAD*2+(maxR)*GY+NH;
  cv.style.width=W+"px"; cv.style.height=H+"px";  // 绝对定位子节点不撑容器，必须显式给高
  CW=W; CH=H; applyZoom();
  const svg = document.createElementNS("http://www.w3.org/2000/svg","svg");
  svg.setAttribute("width",W); svg.setAttribute("height",H);
  const defs = document.createElementNS("http://www.w3.org/2000/svg","defs");
  const mk = document.createElementNS("http://www.w3.org/2000/svg","marker");
  mk.setAttribute("id","ar"); mk.setAttribute("viewBox","0 0 10 10");
  mk.setAttribute("refX","9"); mk.setAttribute("refY","5");
  mk.setAttribute("markerWidth","7"); mk.setAttribute("markerHeight","7");
  mk.setAttribute("orient","auto-start-reverse");
  const ph = document.createElementNS("http://www.w3.org/2000/svg","path");
  ph.setAttribute("d","M 0 1 L 9 5 L 0 9 z"); ph.setAttribute("fill","#98a2b0");
  mk.appendChild(ph); defs.appendChild(mk); svg.appendChild(defs);
  const pos = {};
  for(const n of wf.nodes){
    const x = PAD+n.c*GX, y = PAD+n.r*GY;
    pos[n.id]=[x,y];
    const d = el("div","node n-"+n.k);
    d.style.left=x+"px"; d.style.top=y+"px";
    d.appendChild(el("div","t",n.t));
    d.appendChild(el("div","s",n.s));
    d.appendChild(el("div","k",KIND_LABEL[n.k]||n.k));
    cv.appendChild(d); CURDIVS[n.id]=d;
  }
  for(const [a,b] of wf.edges){
    const [x1,y1]=pos[a], [x2,y2]=pos[b];
    const sxx=x1+NW, sy=y1+NH/2, ex=x2, ey=y2+NH/2;
    const p = document.createElementNS("http://www.w3.org/2000/svg","path");
    p.setAttribute("d","M "+sxx+" "+sy+" C "+(sxx+34)+" "+sy+", "+(ex-34)+" "+ey+", "+ex+" "+ey);
    p.setAttribute("fill","none"); p.setAttribute("stroke","#8f9aa8");
    p.setAttribute("stroke-width","1.6"); p.setAttribute("marker-end","url(#ar)");
    svg.appendChild(p); CUREDGE[a+">"+b]=p;
  }
  cv.appendChild(svg);
}
function animateRun(wf){
  for(const k in CUREDGE) CUREDGE[k].classList.add("eflow");
  wf.nodes.forEach((n,i)=>{
    RUNTIMER.push(setTimeout(()=>{if(CURDIVS[n.id])CURDIVS[n.id].classList.add("run");}, i*130));
  });
}
function finishRun(wf,ok){
  if(CUR!==wf) return;  // 迟到的旧响应不得把新工作流画布标成已运行（慢盘/隧道下的竞态窗口）
  RUNTIMER.forEach(clearTimeout); RUNTIMER=[];
  for(const k in CUREDGE) CUREDGE[k].classList.remove("eflow");
  for(const id in CURDIVS){CURDIVS[id].classList.remove("run");CURDIVS[id].classList.add(ok?"done":"fail");}
}

/* ---------- 运行面板 ---------- */
function renderPanel(wf){
  const p = document.getElementById("panel");
  p.textContent = "";
  const h = el("h3",null,wf.mode==="run"?"运行："+wf.name:"命令："+wf.name);
  p.appendChild(h);
  if(wf.mode==="cli"){
    const c = el("div","cmd",wf.cmd(STATS.path));
    const b = el("button","btn sub","复制");
    b.onclick = async()=>{
      try{ await navigator.clipboard.writeText(c.textContent); b.textContent="已复制";
           setTimeout(()=>{b.textContent="复制";},1200);}catch(e){b.textContent="复制失败";}
    };
    const row = el("div","frow"); row.appendChild(c); row.appendChild(b); p.appendChild(row);
    if(wf.args) p.appendChild(el("p","args",wf.args));
    p.appendChild(el("p","note","该工作流写盘/长任务"+(wf.id==="enrich"?"且需模型密钥":"")+"，在终端执行；完成后此页刷新即可看到新图。"));
    return;
  }
  const form = el("div");
  const inputs = {};
  const memoKey = "dm-wb-input:"+wf.id;
  let memo = null;
  try{ memo = JSON.parse(localStorage.getItem(memoKey)||"null"); }catch(e){ memo=null; }
  for(const f of (wf.fields||[])){
    const row = el("div","frow");
    row.appendChild(el("label",null,f.l));
    const inp = f.ta ? el("textarea") : el("input");
    if(!f.ta) inp.type="text";
    inp.placeholder = f.ph||"";
    if(f.n==="domain"){                        // 领域建议：来自当前图 /api/domain
      const dl=el("datalist"); dl.id="dm-domains";
      fetchJSON("/api/domain").then(({data})=>{
        for(const d of Object.keys(data.domains||{}))
          dl.appendChild(el("option",null,d));
      }).catch(()=>{});
      p.appendChild(dl); inp.setAttribute("list","dm-domains");
    }
    if(memo && typeof memo[f.n]==="string") inp.value = memo[f.n];
    if(wf.act==="search"){
      inp.addEventListener("paste",()=>{          // 粘贴即搜：报错文本贴进来直接查
        setTimeout(()=>{
          if(inp.value.trim()) document.querySelector("#panel .btn:not(.sub)").click();
        },0);
      });
    }
    inp.addEventListener("input",()=>{
      try{ const v={}; for(const k in inputs) v[k]=inputs[k].value;
           localStorage.setItem(memoKey, JSON.stringify(v)); }catch(e){}
    });
    inputs[f.n]=inp;
    row.appendChild(inp);
    form.appendChild(row);
  }
  const row = el("div","frow");
  const lab = el("label");
  const btn = el("button","btn","运行");
  btn.onclick = ()=>run(wf,inputs,btn);
  // Enter 运行（输入法组词态不触发；textarea Shift+Enter 保留换行）
  for(const key in inputs){
    const inp=inputs[key], ta=inp.tagName==="TEXTAREA";
    inp.addEventListener("keydown",e=>{
      if(e.key==="Enter" && !e.isComposing && !(ta && e.shiftKey)){e.preventDefault();btn.click();}
    });
  }
  row.appendChild(lab); row.appendChild(btn);
  form.appendChild(row);
  p.appendChild(form);
  const out = el("div"); out.id="out"; out.setAttribute("aria-live","polite"); p.appendChild(out);
  const hist=el("div","hist"); hist.id="hist";
  p.insertBefore(hist,out);
  drawHist();
  p.appendChild(el("p","note",wf.id==="search"?"拒答是契约行为：无依据时明确说不知道，不猜；拒答文案会给出真实原因。":wf.id==="read"?"证据只在 --discover 建图时固化；无证据库或来源无固化记录会如实告知。":""));
}
async function fetchJSON(url,opts){
  const r = await fetch(url,opts);
  const d = await r.json().catch(()=>({error:"响应不是 JSON（HTTP "+r.status+"）"}));
  return {status:r.status, data:d};
}

/* ---------- 各工作流执行与结果渲染 ---------- */
function drawHist(){
  const box=document.getElementById("hist");
  if(!box) return;
  box.textContent="";
  if(!HIST.length) return;
  box.appendChild(el("span","ms","最近："));
  for(const h of HIST){
    const b=el("button",null,h.q+(h.dom?" ·"+h.dom:""));
    b.title="重跑："+h.q;
    b.onclick=()=>{
      const i=document.querySelector("#panel input"); i.value=h.q;
      const d=document.querySelectorAll("#panel input")[1]; if(d) d.value=h.dom||"";
      document.querySelector("#panel .btn").click();
    };
    box.appendChild(b);
  }
}
function addMs(out,ms){
  const bar=out.querySelector(".copybar");
  const tag=el("span","ms",Math.round(ms)+" ms");
  if(bar) bar.insertBefore(tag,bar.firstChild);
}
function addCopyBar(out){
  const bar=el("div","copybar");
  const b=el("button","mini","复制结果");
  b.onclick=async()=>{
    const barNode=out.querySelector(".copybar");
    const prev=barNode&&barNode.parentNode; if(barNode) barNode.remove();
    const text=out.innerText.trim();
    if(prev) prev.insertBefore(barNode, prev.firstChild);
    try{ await navigator.clipboard.writeText(text);
         b.textContent="已复制"; setTimeout(()=>{b.textContent="复制结果";},1200);}catch(e){ b.textContent="复制失败"; }
  };
  bar.appendChild(b); out.appendChild(bar);
}
async function run(wf,inputs,btn){
  const out = document.getElementById("out");
  out.textContent = "";
  addCopyBar(out);
  const old = btn.textContent; btn.textContent="运行中…"; btn.disabled=true;
  btn.classList.add("busy");
  const t0 = performance.now();
  const titleKeep=document.title;
  document.title="运行中 · "+titleKeep;
  const bail = msg=>{out.appendChild(el("p","err",msg));finishRun(wf,false);};
  // GET 参数走 URL：超长输入必然撞 HTTP 414，前端诚实拦截（POST 型 note 不受限）
  const tooLong = v=>v.length>2000;
  const guard = (...vals)=>{
    if(vals.some(tooLong)){bail("输入过长（上限 2000 字符），请缩短后重试。");return true;}
    return false;
  };
  animateRun(wf);
  try{
    if(wf.act==="search"){
      const q=inputs.q.value.trim(), dom=inputs.domain.value.trim();
      if(!q){bail("查询不能为空");return;}
      if(guard(q,dom))return;
      const {data} = await fetchJSON("/api/search?q="+encodeURIComponent(q)+(dom?"&domain="+encodeURIComponent(dom):""));
      HIST=[{q:q,dom:dom}].concat(HIST.filter(h=>h.q!==q||h.dom!==dom)).slice(0,5);
      drawHist();
      renderSearch(out,data);
    }else if(wf.act==="scenario-req"||wf.act==="scenario-trb"){
      const t=inputs.text.value.trim();
      if(!t){bail("文本不能为空");return;}
      if(guard(t))return;
      const kind=wf.act==="scenario-req"?"req":"trb";
      const {status,data} = await fetchJSON("/api/scenario?kind="+kind+"&text="+encodeURIComponent(t));
      if(status!==200){bail(data.error||("HTTP "+status));return;}
      renderCard(out,data.card);
    }else if(wf.act==="impact"){
      const sym=inputs.symbol.value.trim();
      if(!sym){bail("符号不能为空");return;}
      if(guard(sym))return;
      const {status,data} = await fetchJSON("/api/impact?symbol="+encodeURIComponent(sym));
      if(status!==200){bail(data.error||("HTTP "+status));return;}
      renderImpact(out,data);
    }else if(wf.act==="domain"){
      const {status,data} = await fetchJSON("/api/domain");
      if(status!==200){bail(data.error||("HTTP "+status));return;}
      renderDomain(out,data);
    }else if(wf.act==="read"){
      const id=inputs.id.value.trim();
      if(!id){bail("ID 不能为空");return;}
      if(guard(id))return;
      const param = id.slice(0,3)==="ev:" ? "ev="+encodeURIComponent(id) : "node="+encodeURIComponent(id);
      const {status,data} = await fetchJSON("/api/read?"+param);
      if(status!==200){bail(data.error||data.reason||("HTTP "+status));return;}
      renderEvidence(out,data);
    }else if(wf.act==="note"){
      const body=inputs.body.value.trim();
      if(!body){bail("正文不能为空");return;}
      const {status,data} = await fetchJSON("/api/note/save",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({body:body,claims:[],idempotency_key:"ui-"+Date.now()})});
      if(status!==200){bail(data.error||("HTTP "+status));return;}
      out.appendChild(el("p",null,"已保存。note_id="+data.note_id+"，revision="+data.revision+"（检索时与事实种子同台呈现）"));
      refreshStats();
    }else if(wf.act==="fbhist"){
      const {status,data} = await fetchJSON("/api/feedback/stats");
      if(status!==200){bail(data.error||("HTTP "+status));return;}
      const h = await fetchJSON("/api/history?limit=20");
      if(h.status!==200){bail(h.data.error||("HTTP "+h.status));return;}
      renderFbHist(out,data,h.data);
      const iss = await fetchJSON("/api/issues");
      if(iss.status===200 && (iss.data.issues||[]).length){
        renderIssues(out,iss.data.issues);
      }
    }
    finishRun(wf,true);
    addMs(out, performance.now()-t0);
  }catch(e){
    bail("请求失败："+(e&&e.message?e.message:e));
    addMs(out, performance.now()-t0);
  }finally{
    btn.textContent=old; btn.disabled=false; btn.classList.remove("busy");
    document.title=titleKeep;
  }
}
function renderSearch(out,d){
  if(d.refused){
    const r=el("div","ref","拒答："+(d.text||""));
    out.appendChild(r);
  }
  const seeds=d.seeds||[];
  out.appendChild(el("div","h","候选 "+seeds.length+" 条（同 CLI 排序）"));
  if(!seeds.length && !d.refused){out.appendChild(el("div","empty","无候选——换关键词或符号名再试（支持中文/表名/类名）"));return;}
  seeds.forEach((s,i)=>{
    const row=el("div","seed");
    row.appendChild(el("span","kd kd-"+s.kind, s.kind));
    if(s.kind==="Knowledge") row.appendChild(el("span","kd kd-src", s.conf==="LLM"?"LLM 草稿":"人工"));
    if(s.domain) row.appendChild(el("span","dom-tag",s.domain));
    row.appendChild(el("span","nm",s.name));
    const fl=el("span","fl path","@"+s.file); fl.title=s.file; row.appendChild(fl);
    row.appendChild(el("span","idx",(i+1)+""));
    if(s.ev){
      const evb=el("span","fl evc",s.ev.slice(0,12));
      evb.title="点击复制证据 ID："+s.ev;
      evb.onclick=async ev=>{
        ev.stopPropagation();
        try{ await navigator.clipboard.writeText(s.ev); evb.textContent="已复制";
             setTimeout(()=>{evb.textContent=s.ev.slice(0,12);},1200);}catch(e){}
      };
      row.appendChild(evb);
    }
    row.title="点击读该来源固化证据";
    row.onclick=()=>{document.getElementById("panel").textContent="";
      CUR=WORKFLOWS.find(w=>w.id==="read");select(CUR);
      const inp=document.querySelector('#panel input[type=text]');
      inp.value=s.ev||s.id;
      document.querySelector('#panel .btn').click();};
    row.style.animationDelay=(i*30)+"ms";
    out.appendChild(row);
  });
  addFeedbackBar(out,d);
}
function addFeedbackBar(out,d){
  // 反馈条：只对已成功记录的真实查询显示；有候选≠hit，判定永远来自人（EV02）
  if(!d.query_id || d.recording!=="recorded") return;
  const bar=el("div","fbbar");
  const note=el("input"); note.type="text"; note.maxLength=200;
  note.placeholder="可选说明：哪里没找到 / 结果哪里有误（进本地反馈库）";
  const st=el("span","fbok",null);
  const send=async(rel,reason)=>{
    if(st.textContent && st.textContent.indexOf("已记录")>=0) return; // 一次查询一条反馈，改判走 CLI/再次提交修订
    try{
      const {status,data}=await fetchJSON("/api/feedback",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({event_id:d.query_id,relevance:rel,reason:reason||null})});
      if(status!==200){st.textContent="反馈失败："+(data.error||("HTTP "+status));return;}
      st.textContent="已记录（revision "+data.revision+"）";
    }catch(e){ st.textContent="反馈失败："+(e&&e.message?e.message:e); }
  };
  const mk=(label,rel,reasonPrefix)=>{
    const b=el("button","fbb",label);
    b.onclick=()=>send(rel,reasonPrefix?(reasonPrefix+(note.value.trim()||"")):note.value.trim()||null);
    return b;
  };
  bar.appendChild(mk("找到","hit"));
  bar.appendChild(mk("部分找到","partial"));
  bar.appendChild(mk("没找到","miss"));
  bar.appendChild(mk("结果有误","miss","结果有误："));
  bar.appendChild(note);
  bar.appendChild(st);
  out.appendChild(bar);
}
function renderFbHist(out,stats,hist){
  const e=stats.effective||{};
  out.appendChild(el("div","h","反馈统计（判定来自人；unknown 不算 miss）"));
  const box=el("div","md");
  box.appendChild(el("p",null,"事件 "+stats.events+"（profile "+ (stats.profiles?stats.profiles.distinct:"-")
    +"，重复 "+(stats.profiles?stats.profiles.repeated_events:"-")+"）｜触发 user "+stats.trigger.user
    +" / 非 user "+stats.trigger.non_user));
  box.appendChild(el("p",null,"hit="+e.hit+" partial="+e.partial+" miss="+e.miss
    +" unknown="+e.unknown+" not_applicable="+e.not_applicable+" disputed="+e.disputed));
  box.appendChild(el("p",null,"已判定完整命中率 H/(H+P+M) = "
    +(stats.hit_rate===null||stats.hit_rate===undefined?"无判定样本":stats.hit_rate)
    +"（分母 "+stats.hit_rate_denominator+"，partial 单列）｜判定覆盖率 "
    +(stats.judgment_coverage===null||stats.judgment_coverage===undefined?"-":stats.judgment_coverage)
    +"｜未反馈 "+(stats.unfeedbacked_ratio===null||stats.unfeedbacked_ratio===undefined?"-":stats.unfeedbacked_ratio)));
  box.appendChild(el("p",null,"正确拒答 "+stats.correct_refusal.correct_abstention
    +"/"+stats.correct_refusal.refused_with_feedback+"（refused 且有权威反馈者）"));
  for(const src in (stats.by_source||{})){
    const c=stats.by_source[src];
    box.appendChild(el("p",null,"来源 "+src+"：最新修订 "+c.latest_count
      +"（hit="+(c.hit||0)+" partial="+(c.partial||0)+" miss="+(c.miss||0)+"）"));
  }
  out.appendChild(box);
  const items=hist.items||[];
  out.appendChild(el("div","h","查询历史（最近 "+items.length+"/"+hist.total+"）"));
  if(!items.length){out.appendChild(el("div","empty","尚无查询记录（先在「检索问答」发起查询）"));return;}
  for(const it of items){
    const row=el("div","seed");
    row.appendChild(el("span","kd kd-"+it.status,it.status));
    if(it.refusal_reason) row.appendChild(el("span","dom-tag",it.refusal_reason));
    row.appendChild(el("span","nm",it.query_preview||("（未保存原文）#"+it.query_digest)));
    const fb=it.disputed?"disputed":(it.feedback_relevance||"-");
    row.appendChild(el("span","fl","fb="+fb+(it.feedback_sources.length?"("+it.feedback_sources.join(",")+")":"")));
    row.appendChild(el("span","idx",it.entry+"/"+it.trigger_kind));
    row.title="event_id="+it.event_id+"（反馈：domimap feedback "+it.event_id+" --relevance …）";
    out.appendChild(row);
  }
}
function renderIssues(out,issues){
  out.appendChild(el("div","h","问题簇（miss/失败/异常归并；诊断执行走 CLI）"));
  for(const ic of issues){
    const row=el("div","seed");
    row.appendChild(el("span","kd kd-diag",ic.status));
    row.appendChild(el("span","nm",ic.cluster_id));
    row.appendChild(el("span","fl","事件×"+ic.event_count));
    const dg=ic.last_diagnosis;
    row.appendChild(el("span","fl",dg?("诊断 "+dg.ai_status):"未诊断"));
    row.title="domimap diagnose --cluster "+ic.cluster_id+" [--ai] [--out out/diag.json]";
    out.appendChild(row);
  }
}
function renderCard(out,card){
  out.appendChild(el("div","h","结果卡片"));
  const box=el("div","md");
  for(const line of String(card||"").split("\n")){
    if(line.startsWith("# ")) box.appendChild(el("div","h1",line.slice(2)));
    else if(line.startsWith("## ")) box.appendChild(el("div","h2",line.slice(3)));
    else if(line.startsWith("> ")) box.appendChild(el("div","q",line.slice(2)));
    else if(line.startsWith("- ")) box.appendChild(el("div","li",line.slice(2)));
    else if(line.trim()==="") box.appendChild(el("div","sp"));
    else box.appendChild(el("div","p",line));
  }
  out.appendChild(box);
}
function renderImpact(out,d){
  const st=d.start||[];
  if(!st.length){out.appendChild(el("div","empty","无匹配符号——影响面用子串匹配，试试表名/类名/方法名片段"));return;}
  out.appendChild(el("div","h","起点"));
  for(const n of st) out.appendChild(el("p",null,"["+n.kind+"] "+n.name+"  @"+n.file));
  const deps=d.deps||[];
  out.appendChild(el("div","h","反向依赖 "+deps.length+(d.truncated?"（截断，共 "+d.total+"）":"")+" 条"));
  for(const e of deps){
    const row=el("div","dep");
    row.appendChild(el("span","src","← "+e.src));
    row.appendChild(el("span","rel","  --"+e.kind+"-->  "));
    row.appendChild(el("span","dst",e.dst));
    if(e.domain) row.appendChild(el("span","fl","  ["+e.domain+"]"));
    if(e.src_file) row.title=e.src_file;
    out.appendChild(row);
  }
}
function renderDomain(out,d){
  const doms=d.domains||{};
  out.appendChild(el("div","h","领域 "+Object.keys(doms).length+" 个"));
  const grid=el("div","domgrid");
  out.appendChild(grid);
  for(const name of Object.keys(doms).sort()){
    const a=doms[name];
    const box=el("div","dom");
    box.appendChild(el("div","nm",name));
    box.appendChild(el("div","row","服务 "+a.services.length+"："+(a.services.slice(0,8).join("、")||"-")));
    box.appendChild(el("div","row","表 "+a.tables.length+"："+(a.tables.slice(0,8).join("、")||"-")));
    box.appendChild(el("div","row","主题："+(a.topics.slice(0,5).join("、")||"-")+"　文档 "+a.docs));
    grid.appendChild(box);
  }
  const sh=d.shared||[];
  if(sh.length){
    out.appendChild(el("div","h","跨域共享表（改动需多域评审）"));
    for(const x of sh) out.appendChild(el("p","warnrow",x.table+" ← "+x.domains.join(" + ")));
  }
}
function renderEvidence(out,ev){
  if(!ev.available){
    out.appendChild(el("p","err","不可用："+(ev.reason||"未知原因")));return;
  }
  out.appendChild(el("div","h","固化证据"));
  const m=el("div","evmeta");
  const rows=[["ev_id",ev.ev_id],["来源",ev.sid],["sha256",ev.sha256]];
  for(const [k,v] of rows){m.appendChild(el("div","k",k));m.appendChild(el("div",null,v));}
  if(ev.locator){m.appendChild(el("div","k","定位"));m.appendChild(el("div",null,JSON.stringify(ev.locator)));}
  out.appendChild(m);
  const pre=el("pre","blob",ev.text||"");
  out.appendChild(pre);
  if((ev.text||"").length>800){
    const more=el("button","mini",null);
    const setOpen=t=>{pre.classList.toggle("exp",t); more.textContent=t?"收起":"展开全部（"+ev.text.length+" 字）";};
    more.onclick=()=>setOpen(!pre.classList.contains("exp"));
    setOpen(false);
    const bar=el("div","copybar"); bar.appendChild(more);
    out.appendChild(bar);
  }
}

(function(){
  const f=document.getElementById("cheat");
  const items=[["/","聚焦输入"],["↑ ↓","切换工作流"],["Enter","运行"],["Esc","清空"],
               ["Alt 1-9","打开候选证据"],["点证据徽标","复制证据 ID"]];
  for(const it of items){
    const sp=el("span");
    sp.appendChild(el("kbd","kbd",it[0]));
    sp.appendChild(document.createTextNode(" "+it[1]));
    f.appendChild(sp);
  }
})();

/* ---------- 键盘导航：↑↓ 切工作流 / Enter 运行 / Esc 清空 / 聚焦输入 ---------- */
document.addEventListener("keydown",e=>{
  if(e.target.tagName==="TEXTAREA") return;             // 多行输入内不劫持
  const isInput = e.target.tagName==="INPUT";
  if(e.key==="/" && !isInput){ e.preventDefault(); const i=document.querySelector("#panel input"); if(i) i.focus(); return; }
  if(e.key==="ArrowDown" || e.key==="ArrowUp"){
    if(isInput && e.key==="ArrowUp") return;            // 输入框内 ↑ 不切（避免误触）
    e.preventDefault();
    const btns=[...document.querySelectorAll("#catalog button")];
    const idx=btns.findIndex(b=>b.classList.contains("on"));
    const nxt=btns[(idx+(e.key==="ArrowDown"?1:btns.length-1))%btns.length];
    nxt.click(); nxt.scrollIntoView({block:"nearest"});
    const i=document.querySelector("#panel input"); if(i) i.focus();
    return;
  }
  if(e.key==="Enter" && isInput){
    e.preventDefault();
    const b=document.querySelector("#panel .btn:not(.sub)"); if(b) b.click();
    return;
  }
  if(e.key==="Escape" && isInput){ e.target.value=""; return; }
  if(e.altKey && /^[1-9]$/.test(e.key)){
    const rows=document.querySelectorAll("#out .seed");
    const n=parseInt(e.key,10)-1;
    if(rows[n]){ e.preventDefault(); rows[n].click(); }
  }
});

/* ---------- 初始选中（hash 路由优先） ---------- */
const fromHash=WORKFLOWS.find(w=>"#"+w.id===location.hash);
select(fromHash||WORKFLOWS[0]);
</script>
</body>
</html>
"""


def _page_stats(graph_path, g):
    """页眉统计：图规模 + 库状态（不打印任何源内容）。"""
    base = os.path.dirname(os.path.abspath(graph_path))
    stats = {
        "path": os.path.abspath(graph_path),
        "name": os.path.basename(graph_path),
        "nodes": len(g.nodes),
        "edges": len(g.edges),
        "store": os.path.exists(os.path.join(base, "store.db")),
        "embed": os.path.exists(graph_path + ".emb.json"),
        "notes": None,
    }
    kb_path = os.path.join(base, "knowledge.db")
    if os.path.exists(kb_path):
        from .knowledge import KnowledgeStore
        kb = KnowledgeStore(kb_path)
        try:
            stats["notes"] = len(kb.list_active())
        finally:
            kb.close()
    return stats


def render_page(graph_path, g):
    stats_json = json.dumps(_page_stats(graph_path, g), ensure_ascii=False)
    # 防 </script> 提前闭合（图路径来自本地文件名，仍做标准转义）
    stats_json = stats_json.replace("</", "<\\/")
    return PAGE_TEMPLATE.replace("__STATS_JSON__", stats_json)


def make_server(graph_path, host="127.0.0.1", port=0):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("本地 UI 仅允许回环绑定（安全边界 R08）")
    from .service import AppService, ServiceError
    svc = AppService(graph_path)  # 与 CLI/MCP 同一装配与默认参数（product#6）
    g, searcher, seeds, ev_by_rel = svc.g, svc.s, svc.seeds, svc.resolver

    def _refresh(force=False):
        """graph/knowledge/store 变化即重建（长驻 UI 不再冻结启动时刻的图与笔记）。"""
        nonlocal g, searcher, seeds, ev_by_rel
        if svc.refresh(force=force):
            g, searcher, seeds, ev_by_rel = svc.g, svc.s, svc.seeds, svc.resolver

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 安静模式
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if extra:
                for k, v in extra.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        _LOOPBACK = ("http://127.0.0.1", "http://localhost", "http://[::1]")

        def _origin_ok(self):
            """R08-02：Host 必须回环；Origin/Referer 若存在必须回环（跨站写拒绝）。"""
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost", "[::1]", "::1"):
                return False
            for h in ("Origin", "Referer"):
                v = self.headers.get(h)
                if v and not any(v.startswith(p) for p in self._LOOPBACK):
                    return False
            return True

        def do_POST(self):
            _refresh()
            if self.path == "/api/note/save":
                if not self._origin_ok():
                    n = int(self.headers.get("Content-Length") or 0)
                    if n:
                        self.rfile.read(min(n, 1 << 20))  # 排空请求体再应答，保证连接语义
                    self._send(403, json.dumps({"error": "跨站/非回环来源写入被拒绝"}, ensure_ascii=False))
                    return
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(min(n, 1 << 20)).decode("utf-8"))
                except Exception:
                    self._send(400, json.dumps({"error": "非法请求体"}, ensure_ascii=False))
                    return
                # 空参不静默：缺 body/纯空白正文/claims 非数组一律 4xx，不创建垃圾笔记
                nb = body.get("body")
                if not isinstance(nb, str) or not nb.strip():
                    self._send(400, json.dumps({"error": "正文不能为空"}, ensure_ascii=False))
                    return
                if "claims" in body and not isinstance(body["claims"], list):
                    self._send(400, json.dumps({"error": "claims 必须为数组"}, ensure_ascii=False))
                    return
                from .knowledge import KnowledgeStore
                kb_path = os.path.join(os.path.dirname(os.path.abspath(graph_path)), "knowledge.db")
                kb = KnowledgeStore(kb_path)
                try:
                    r = kb.submit(nb, body.get("claims") or [],
                                  idempotency_key=body.get("idempotency_key"))
                    _refresh(force=True)  # 整体重建装配：新笔记即时可检索，且不累加索引统计
                except ValueError as e:
                    self._send(409, json.dumps({"error": str(e)}, ensure_ascii=False))
                    return
                finally:
                    kb.close()
                self._send(200, json.dumps(r, ensure_ascii=False))
                return
            if self.path == "/api/feedback":
                if not self._origin_ok():
                    n = int(self.headers.get("Content-Length") or 0)
                    if n:
                        self.rfile.read(min(n, 1 << 20))
                    self._send(403, json.dumps({"error": "跨站/非回环来源写入被拒绝"}, ensure_ascii=False))
                    return
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(min(n, 1 << 20)).decode("utf-8"))
                except Exception:
                    self._send(400, json.dumps({"error": "非法请求体"}, ensure_ascii=False))
                    return
                from domimap.feedback import FeedbackStore, FeedbackError, RELEVANCE_VALUES
                ev = body.get("event_id")
                if not isinstance(ev, str) or not re.fullmatch(r"qe:[0-9a-f]{24}", ev):
                    self._send(400, json.dumps({"error": "非法 event_id"}, ensure_ascii=False))
                    return
                rel = body.get("relevance")
                if rel not in RELEVANCE_VALUES or rel == "unknown":
                    self._send(400, json.dumps({"error": "relevance 必须是 hit/partial/miss/not_applicable"}, ensure_ascii=False))
                    return
                reason = body.get("reason")
                if reason is not None and (not isinstance(reason, str) or len(reason) > 200):
                    self._send(400, json.dumps({"error": "reason 过长（上限 200 字符）"}, ensure_ascii=False))
                    return
                db = os.path.join(os.path.dirname(os.path.abspath(graph_path)), "queries.db")
                store = FeedbackStore(db)
                try:
                    r = store.submit(ev, rel, task_outcome="unknown",
                                     source="user_feedback", reason=reason,
                                     idempotency_key=body.get("idempotency_key"))
                except FeedbackError as e:
                    code = 404 if "未知查询事件" in str(e) else 409
                    self._send(code, json.dumps({"error": str(e)}, ensure_ascii=False))
                    return
                finally:
                    store.close()
                self._send(200, json.dumps(r, ensure_ascii=False))
                return
            self._send(404, json.dumps({"error": "not found"}))

        def do_GET(self):
            # DNS rebinding 加固：读请求同样要求回环 Host/来源，防止恶意网页重绑定域名读取索引内容
            if not self._origin_ok():
                self._send(403, json.dumps({"error": "非回环来源请求被拒绝"}, ensure_ascii=False))
                return
            _refresh()
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            if u.path == "/":
                # 每请求现渲染：stats（笔记/嵌入索引等）不能用启动时刻的冻结快照——
                # 长驻服务里保存笔记/建嵌入后，刷新页面必须看到当前状态（R01 如实呈现）
                csp = ("default-src 'none'; script-src 'unsafe-inline'; "
                       "style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
                       "font-src 'self'; base-uri 'none'; form-action 'none'")
                self._send(200, render_page(graph_path, g), "text/html; charset=utf-8",
                           extra={"Content-Security-Policy": csp})
                return
            if u.path == "/api/search":
                q = (qs.get("q") or [""])[0]
                dom = (qs.get("domain") or [None])[0]
                if not q.strip():
                    self._send(400, json.dumps({"error": "空查询"}, ensure_ascii=False))
                    return
                as_of = (qs.get("as_of") or [None])[0]
                top_k = (qs.get("top_k") or [None])[0]
                try:
                    if top_k is not None:
                        top_k = int(top_k)
                    r, obs = svc.query(q, "ui", domain=dom, as_of=as_of, top_k=top_k)
                except ValueError:
                    self._send(400, json.dumps({"error": "top_k 须为整数", "code": "invalid_params"}, ensure_ascii=False))
                    return
                except ServiceError as e:
                    self._send(400, json.dumps({"error": str(e), "code": e.code}, ensure_ascii=False))
                    return
                except Exception:
                    # 与 CLI/MCP 一样返回有界错误，而不是断开连接（内部异常文本不外泄）
                    self._send(500, json.dumps({"error": "内部错误（internal）", "code": "internal"},
                                               ensure_ascii=False))
                    return
                seeds_out = []
                for n in r["seeds"]:
                    item = {"id": n["id"], "kind": n["kind"], "name": n["name"],
                            "file": n["file"], "conf": n.get("conf", "")}
                    if n.get("time_note"):  # 时效可解释（F4）
                        item["time_note"] = n["time_note"]
                        if n.get("meta", {}).get("era_source"):
                            item["era_source"] = n["meta"]["era_source"]
                    if n.get("meta", {}).get("valid_until"):
                        item["valid_until"] = n["meta"]["valid_until"]
                    if n["kind"] == "Knowledge" and any(c.get("stale") for c in n["meta"].get("claims", [])):
                        item["stale"] = True  # 依据已变待复核（R06-02）
                    if n.get("meta", {}).get("domain"):
                        item["domain"] = n["meta"]["domain"]
                    ev_id = ev_by_rel.for_node(n)
                    if ev_id:
                        item["ev"] = ev_id  # 候选可直读固化证据（AC-F2-01 可打开完整证据）
                    seeds_out.append(item)
                payload = {"seeds": seeds_out,
                           "refused": r.get("refused", False), "text": r["text"][:400],
                           "coverage": r.get("coverage")}
                if obs["status"] != "disabled":  # recording_failed 等状态如实可见
                    payload["query_id"] = obs.get("event_id")
                    payload["recording"] = obs["status"]
                self._send(200, json.dumps(payload, ensure_ascii=False))
                return
            if u.path == "/api/stats":
                self._send(200, json.dumps(_page_stats(graph_path, g), ensure_ascii=False))
                return
            if u.path == "/api/history":
                from domimap.feedback import FeedbackStore
                qdb = os.path.join(os.path.dirname(os.path.abspath(graph_path)), "queries.db")
                if not os.path.exists(qdb):  # 不因查看历史而凭空建库
                    self._send(200, json.dumps({"items": [], "total": 0, "limit": 0,
                                                "offset": 0}, ensure_ascii=False))
                    return
                try:
                    store = FeedbackStore(qdb)
                except Exception:
                    self._send(200, json.dumps({"items": [], "total": 0, "limit": 0,
                                                "offset": 0}, ensure_ascii=False))
                    return
                try:
                    def _choice(name, allowed):
                        v = (qs.get(name) or [None])[0]
                        return v if v in allowed else None
                    limit = min(max(int((qs.get("limit") or ["20"])[0] or 20), 1), 100)
                    offset = max(int((qs.get("offset") or ["0"])[0] or 0), 0)
                    r = store.list_events(
                        entry=_choice("entry", ("cli", "mcp", "ui")),
                        status=_choice("status", ("ok", "refused", "error", "cancelled")),
                        refusal_reason=_choice("refusal_reason", (
                            "identifier_absent", "empty_query", "generic_only",
                            "coverage_below_min", "domain_filter_empty", "no_strong_candidate")),
                        trigger=_choice("trigger", ("user", "retry", "replay", "diagnostic")),
                        limit=limit, offset=offset)
                finally:
                    store.close()
                self._send(200, json.dumps(r, ensure_ascii=False))
                return
            if u.path == "/api/feedback/stats":
                from domimap.feedback import FeedbackStore
                qdb = os.path.join(os.path.dirname(os.path.abspath(graph_path)), "queries.db")
                if not os.path.exists(qdb):
                    self._send(404, json.dumps({"error": "无查询记录库（queries.db）"},
                                                ensure_ascii=False))
                    return
                store = FeedbackStore(qdb)
                try:
                    r = store.stats()
                finally:
                    store.close()
                self._send(200, json.dumps(r, ensure_ascii=False))
                return
            if u.path == "/api/event":
                # 记录详情：事件 + 反馈修订历史 + 有效判定（C6 入口补齐）
                from domimap.feedback import FeedbackStore
                ev = (qs.get("id") or [""])[0]
                if not re.fullmatch(r"qe:[0-9a-f]{24}", ev):
                    self._send(400, json.dumps({"error": "非法 event_id"},
                                                ensure_ascii=False))
                    return
                qdb = os.path.join(os.path.dirname(os.path.abspath(graph_path)),
                                   "queries.db")
                if not os.path.exists(qdb):
                    self._send(404, json.dumps({"error": "无查询记录库"},
                                                ensure_ascii=False))
                    return
                store = FeedbackStore(qdb)
                try:
                    detail = store.event_detail(ev)
                finally:
                    store.close()
                if detail is None:
                    self._send(404, json.dumps({"error": "事件不存在"},
                                                ensure_ascii=False))
                    return
                self._send(200, json.dumps(detail, ensure_ascii=False))
                return
            if u.path == "/api/issues":
                # 只读问题簇视图（诊断执行走 CLI，避免 UI 触发模型费用与重跑）
                from domimap.diagnosis import list_issues
                try:
                    r = list_issues(graph_path)
                except Exception:
                    r = []
                self._send(200, json.dumps({"issues": r}, ensure_ascii=False))
                return
            if u.path == "/api/scenario":
                # 工作台只读运行：与 CLI scenario 同一 graph/searcher/种子语义
                kind = (qs.get("kind") or [""])[0]
                text = (qs.get("text") or [""])[0]
                if kind not in ("req", "trb"):
                    self._send(400, json.dumps({"error": "kind 必须是 req 或 trb"}, ensure_ascii=False))
                    return
                if not text.strip():
                    self._send(400, json.dumps({"error": "文本不能为空"}, ensure_ascii=False))
                    return
                from . import scenario as _sc
                if kind == "req":
                    card = _sc.scenario_req(g, searcher, text, seeds)
                else:
                    card = _sc.scenario_trb(g, searcher, text)
                self._send(200, json.dumps({"card": card[:20000]}, ensure_ascii=False))
                return
            if u.path == "/api/impact":
                sym = (qs.get("symbol") or [""])[0]
                if not sym.strip():
                    self._send(400, json.dumps({"error": "符号不能为空"}, ensure_ascii=False))
                    return
                try:
                    depth = min(max(int((qs.get("depth") or ["2"])[0]), 1), 4)
                except ValueError:
                    self._send(400, json.dumps({"error": "depth 须为整数"}, ensure_ascii=False))
                    return
                try:
                    res = svc.impact(sym, depth=depth)
                except ServiceError as e:
                    self._send(404 if e.code == "not_found" else 400,
                               json.dumps({"error": str(e), "code": e.code}, ensure_ascii=False))
                    return
                def _nm(n):
                    return {"id": n["id"], "kind": n["kind"], "name": n["name"], "file": n["file"]}
                self._send(200, json.dumps({
                    "start": [_nm(n) for n in res["start"]],
                    "deps": [{"src": s_["name"], "src_file": s_["file"], "kind": k,
                              "dst": d["name"], "dst_file": d["file"],
                              "domain": s_["meta"].get("domain", "")}
                             for s_, k, d in res["deps"]],
                    "total": res["total"], "truncated": res["truncated"], "partial": res["partial"],
                    "max_nodes": res["max_nodes"]}, ensure_ascii=False))
                return
            if u.path == "/api/recheck":
                try:
                    self._send(200, json.dumps({"queue": svc.review_queue()}, ensure_ascii=False))
                except ServiceError as e:
                    self._send(200, json.dumps({"queue": [], "note": str(e)}, ensure_ascii=False))
                return
            if u.path == "/api/domain":
                m = g.domain_map()
                doms = {k: v for k, v in m.items() if k != "__shared__"}
                shared = m.get("__shared__", {}).get("shared", [])
                self._send(200, json.dumps({"domains": doms, "shared": shared}, ensure_ascii=False))
                return
            if u.path == "/api/read":
                ev = (qs.get("ev") or [""])[0]
                sid = (qs.get("sid") or [""])[0].strip()
                node = (qs.get("node") or [""])[0].strip()
                # node= ：图节点 → 其来源文件的固化证据（rel 路径映射，与 kg_explore 同粒度）
                if node and not ev and not sid:
                    n = g.nodes.get(node) or searcher.extra.get(node)
                    if n is None:
                        self._send(404, json.dumps({"available": False,
                                                    "reason": "图中无此节点"}, ensure_ascii=False))
                        return
                    ev = ev_by_rel.for_node(n) or ""
                    if not ev:
                        self._send(404, json.dumps(
                            {"available": False,
                             "reason": "该来源无固化证据（请重新 build 以固化）"},
                            ensure_ascii=False))
                        return
                # 先校验参数（400），再查证据库存在性（404）：参数错误不应被库缺失掩盖
                if ev and not re.fullmatch(r"ev:[0-9a-f]{4,64}", ev):
                    self._send(400, json.dumps({"error": "非法证据 ID"}, ensure_ascii=False))
                    return
                if not ev and not sid:
                    self._send(400, json.dumps({"error": "缺少 ev/sid/node 参数"}, ensure_ascii=False))
                    return
                from .store import EvidenceStore
                db = os.path.join(os.path.dirname(os.path.abspath(graph_path)), "store.db")
                if not os.path.exists(db):
                    self._send(404, json.dumps({"available": False, "reason": "无证据库"}))
                    return
                store = EvidenceStore(db)
                try:
                    if ev:
                        out = store.read_evidence(ev)
                        if out is None:
                            self._send(404, json.dumps({"available": False, "reason": "证据 ID 不存在"}))
                            return
                    else:
                        out = store.evidence_for_source(sid)
                        if out is None:
                            self._send(404, json.dumps(
                                {"available": False, "reason": "该来源无固化证据（证据仅在 --discover 建图时固化）"},
                                ensure_ascii=False))
                            return
                finally:
                    store.close()
                self._send(200, json.dumps({k: (v[:4000] if k == "text" else v)
                                            for k, v in out.items()}, ensure_ascii=False))
                return
            self._send(404, json.dumps({"error": "not found"}))

    return ThreadingHTTPServer((host, port), H)


def serve_forever(graph_path, host, port):
    srv = make_server(graph_path, host, port)
    print("domimap ui: http://%s:%d （仅回环，Ctrl-C 退出）" % (host, srv.server_address[1]))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
