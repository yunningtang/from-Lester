"""Build the combined app (app/): the release tool and the manifest tool in one page, with a mode switch at the top.
Each tool keeps its own stylesheet (only the active one is enabled), its own data, and its own render loop;
only the active mode draws and listens. Dark mode is shared between the two.
Run after editing release-tool/app.html or manifest-tool/app.html:  python3 tools/build_app.py"""
import json,os,re
R=os.path.dirname(os.path.dirname(os.path.abspath(__file__)));D=R+'/app';os.makedirs(D,exist_ok=True)

def parts(path,quotes):
    s=open(path).read().replace('/*QUOTES*/[]',json.dumps(json.load(open(quotes)),ensure_ascii=False,separators=(',',':')))
    css=re.search(r'<style>(.*?)</style>',s,re.S).group(1)
    js=re.search(r'<script>\n?(.*)</script>',s,re.S).group(1)
    return css,js

def patch(js,mode,pairs):
    for a,b in pairs:
        assert js.count(a)==1,(mode,a[:70],js.count(a)); js=js.replace(a,b)
    return js

THEME="Object.defineProperty(CFG,'theme',{get(){try{return localStorage.getItem('ui:theme')||'auto'}catch(e){return 'auto'}},set(v){try{localStorage.setItem('ui:theme',v)}catch(e){}},enumerable:false,configurable:true});"
rcss,rjs=parts(R+'/release-tool/app.html',R+'/release-tool/quotes.json')
mcss,mjs=parts(R+'/manifest-tool/app.html',R+'/manifest-tool/quotes.json')
rjs=patch(rjs,'release',[
 ("(function(){","(function(){\nconst MODE='release',ON=()=>document.body.dataset.app===MODE;"),
 ("let CFG=Object.assign({every:10,goal:2,awake:16,theme:'auto',haptic:true},store.get('cfg',{}));","let CFG=Object.assign({every:10,goal:2,awake:16,haptic:true},store.get('cfg',{}));"+THEME),
 ("document.addEventListener('pointerdown',e=>{const t=e.target.closest(TAPSEL);","document.addEventListener('pointerdown',e=>{if(!ON())return;const t=e.target.closest(TAPSEL);"),
 ("document.addEventListener('click',e=>{const t=e.target.closest('button');","document.addEventListener('click',e=>{if(!ON())return;const t=e.target.closest('button');"),
 ("applyTheme();matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{applyTheme();if(!F)render()});","matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{if(ON()&&!F)render()});"),
 ("setInterval(()=>{if(!SESS)return;","setInterval(()=>{if(!SESS||!ON())return;"),
 ("render(true);\nif(SESS)lockOn();","window.MODES=window.MODES||{};MODES.release={start(){render(true);if(SESS)lockOn()},stop(){if(F){F=null}const p=$('#ping');if(p)p.remove();$('#layer').innerHTML=''},theme:applyTheme};"),
 ("if('serviceWorker' in navigator","if(0&&'serviceWorker' in navigator"),
])
mjs=patch(mjs,'manifest',[
 ("(function(){","(function(){\nconst MODE='manifest',ON=()=>document.body.dataset.app===MODE;"),
 ("let CFG=Object.assign({theme:'auto',haptic:true,target:50,beat:3},store.get('cfg',{}));","let CFG=Object.assign({haptic:true,target:50,beat:3},store.get('cfg',{}));"+THEME),
 ("document.addEventListener('pointerdown',e=>{const t=e.target.closest('button,.qa,.tile');","document.addEventListener('pointerdown',e=>{if(!ON())return;const t=e.target.closest('button,.qa,.tile');"),
 ("document.addEventListener('click',e=>{const t=e.target.closest('button');","document.addEventListener('click',e=>{if(!ON())return;const t=e.target.closest('button');"),
 ("applyTheme();matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{applyTheme();render()});","matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{if(ON())render()});"),
 ("render(true);\nif('serviceWorker'","window.MODES=window.MODES||{};MODES.manifest={start(){render(true)},stop(){if(BEAT){clearInterval(BEAT);BEAT=null}if(P){clearInterval(P.timer);P=null}closeSheet(true);$('#layer').innerHTML=''},theme:applyTheme};\nif(0&&'serviceWorker'"),
])
# both tools re-render their own UI on theme changes; the mode bar and <meta theme-color> follow too
SHELL_CSS="""
.modebar{position:relative;z-index:15;display:flex;justify-content:center;padding:calc(12px + env(safe-area-inset-top,0px)) max(16px,env(safe-area-inset-right,0px)) 0 max(16px,env(safe-area-inset-left,0px))}
.mseg{position:relative;display:grid;grid-template-columns:1fr 1fr;width:min(240px,70vw);padding:3px;border-radius:999px;
  background:rgba(255,255,255,.42);-webkit-backdrop-filter:blur(24px) saturate(170%);backdrop-filter:blur(24px) saturate(170%);box-shadow:inset 0 1px 0 rgba(255,255,255,.8),inset 0 0 0 .5px rgba(255,255,255,.4),0 6px 14px rgba(0,0,0,.06)}
.mseg .mthumb{position:absolute;top:3px;bottom:3px;left:3px;width:calc(50% - 3px);border-radius:999px;background:rgba(255,255,255,.9);box-shadow:inset 0 1px 0 #fff,0 3px 8px rgba(0,0,0,.12);transition:transform .45s cubic-bezier(.32,1.25,.5,1)}
.mseg button{position:relative;z-index:1;font:600 14.5px/1 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC",sans-serif;padding:9px 0;border:0;background:none;color:rgba(40,45,50,.62);cursor:pointer;transition:color .3s;-webkit-tap-highlight-color:transparent}
.mseg button.on{color:#111}
body[data-app="manifest"] .mseg .mthumb{transform:translateX(100%)}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]) .mseg{background:rgba(255,255,255,.07);box-shadow:inset 0 1px 0 rgba(255,255,255,.12),0 6px 14px rgba(0,0,0,.3)}
  :root:not([data-theme="light"]) .mseg .mthumb{background:rgba(255,255,255,.18);box-shadow:inset 0 1px 0 rgba(255,255,255,.2)}
  :root:not([data-theme="light"]) .mseg button{color:rgba(235,240,245,.6)} :root:not([data-theme="light"]) .mseg button.on{color:#fff}}
:root[data-theme="dark"] .mseg{background:rgba(255,255,255,.07);box-shadow:inset 0 1px 0 rgba(255,255,255,.12),0 6px 14px rgba(0,0,0,.3)}
:root[data-theme="dark"] .mseg .mthumb{background:rgba(255,255,255,.18);box-shadow:inset 0 1px 0 rgba(255,255,255,.2)}
:root[data-theme="dark"] .mseg button{color:rgba(235,240,245,.6)} :root[data-theme="dark"] .mseg button.on{color:#fff}
body.switching main{animation:mswap .45s cubic-bezier(.22,1,.36,1) both}
@keyframes mswap{from{opacity:0;transform:translateY(10px) scale(.99)}}
@media (prefers-reduced-motion:reduce){body.switching main{animation:none}.mseg .mthumb{transition:none}}
"""
SHELL_JS="""
(function(){
  const S={get(k,d){try{return localStorage.getItem(k)||d}catch(e){return d}},set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
  const css={release:document.getElementById('css-release'),manifest:document.getElementById('css-manifest')};
  function theme(){const t=S.get('ui:theme','auto'),r=document.documentElement;if(t==='auto'){if(r.hasAttribute('data-theme'))r.removeAttribute('data-theme')}else if(r.getAttribute('data-theme')!==t)r.setAttribute('data-theme',t)}
  function setMode(m,first){const cur=document.body.dataset.app;if(cur===m&&!first)return;if(cur&&MODES[cur])MODES[cur].stop();
    Object.keys(css).forEach(k=>css[k].media=k===m?'all':'not all');document.body.dataset.app=m;S.set('ui:mode',m);theme();
    document.querySelectorAll('.mseg button').forEach(b=>{b.classList.toggle('on',b.dataset.app===m);b.setAttribute('aria-pressed',b.dataset.app===m)});
    if(!first){document.body.classList.remove('switching');void document.body.offsetWidth;document.body.classList.add('switching');setTimeout(()=>document.body.classList.remove('switching'),500)}
    MODES[m].start();scrollTo(0,0)}
  document.querySelectorAll('.mseg button').forEach(b=>b.onclick=()=>{try{navigator.vibrate&&navigator.vibrate(10)}catch(e){}setMode(b.dataset.app)});
  addEventListener('storage',e=>{if(e.key==='ui:theme')theme()});
  setMode(S.get('ui:mode','release'),true);
  if('serviceWorker' in navigator&&location.protocol==='https:'&&!/claude/.test(location.host)){try{navigator.serviceWorker.register('sw.js').catch(()=>{})}catch(e){}}
})();
"""
HEAD="""<title>释放与显化</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@500;700;900&display=swap">
"""
BODY="""<style id="css-release">%s</style>
<style id="css-manifest" media="not all">%s</style>
<style>%s</style>
<div class="amb" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
<div class="modebar"><div class="mseg" role="group" aria-label="切换模式"><span class="mthumb"></span><button data-app="release" aria-pressed="true">释放</button><button data-app="manifest" aria-pressed="false">显化</button></div></div>
<main id="main"></main>
<div class="dock"><nav class="tabs" id="tabs" aria-label="主导航"></nav></div>
<div id="layer"></div>
<script>
%s
</script>
<script>
%s
</script>
<script>
%s
</script>
"""%(rcss,mcss,SHELL_CSS,rjs,mjs,SHELL_JS)
art=HEAD+BODY
open(D+'/artifact.html','w').write(art)
open(D+'/index.html','w').write('''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#eef1ef">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="释放与显化">
<link rel="manifest" href="manifest.json">
<link rel="icon" href="icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="icon.svg">
<style>[hidden]{display:none!important}</style>
</head>
<body>
'''+art+'\n</body>\n</html>\n')
json.dump({"name":"释放与显化","short_name":"释放显化","start_url":"./","display":"standalone","background_color":"#eef1ef","theme_color":"#1f8a63",
  "icons":[{"src":"icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]},open(D+'/manifest.json','w'),ensure_ascii=False,indent=1)
open(D+'/icon.svg','w').write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="112" fill="#17322b"/><defs><radialGradient id="g" cx=".36" cy=".3" r=".75"><stop offset="0" stop-color="#e9fbf4"/><stop offset=".45" stop-color="#5fae9c"/><stop offset="1" stop-color="#0f4d42"/></radialGradient><radialGradient id="h" cx=".36" cy=".3" r=".75"><stop offset="0" stop-color="#eaf3fc"/><stop offset=".45" stop-color="#7fa9d2"/><stop offset="1" stop-color="#24486a"/></radialGradient></defs><circle cx="210" cy="270" r="120" fill="url(#g)"/><circle cx="320" cy="230" r="92" fill="url(#h)" opacity=".92"/></svg>')
open(D+'/sw.js','w').write("""const C='app-v1';
self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(['./','index.html','manifest.json','icon.svg'])).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;e.respondWith(fetch(e.request).then(r=>{const cp=r.clone();caches.open(C).then(c=>c.put(e.request,cp));return r}).catch(()=>caches.match(e.request)))});
""")
print('built app',len(art))
